"""按消息上下文解析跨行记工内容；含糊字段交由人工核对。"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from .catalog import ItemCatalog, normalize_code
from .employees import EmployeeDirectory
from .models import ParseResult, WorkKind, WorkRecord

DATE = re.compile(r"(?P<year>\d{4})[-/年](?P<month>\d{1,2})[-/月](?P<day>\d{1,2})日?")
CODE = re.compile(r"货号\s*[:：]?\s*(?P<value>[A-Za-z0-9][A-Za-z0-9._/-]*)")
QUANTITY = re.compile(r"数量\s*[:：]?\s*(?P<value>\d+(?:\.\d+)?)(?=\s|件|个|单价|$)")
PRICE = re.compile(r"单价\s*[:：]?\s*(?P<value>\d+(?:\.\d+)?)(?=\s|元|$)")
PRICELESS_PIECE = re.compile(r"(?<![\w./-])(?P<code>\d{4}(?:-\d)?)\s+(?P<qty>\d+(?:\.\d+)?)(?=\s|件|个|$)")
SEPARATED_PIECE = re.compile(
    r"(?<![\w./-])(?P<code>\d{4}(?:-\d)?)(?:--|~~)"
    r"(?P<qty>\d+(?:\.\d+)?)\s*[＊*×✘xX]\s*"
    r"(?P<price>\d+(?:\.\d+)?)(?=\s|元|计时|工时|$|[,，;；])"
)
COMPACT_PIECE = re.compile(
    r"(?<![\w./-])(?P<code>[A-Za-z0-9][A-Za-z0-9._/-]*)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s*[＊*×✘xX]\s*"
    r"(?P<price>\d+(?:\.\d+)?)(?=\s|元|计时|工时|$|[,，;；])"
)
STANDALONE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*-\d+")
WORKLIKE = re.compile(r"货号|数量|单价|计时|工时|计\s*\d|\d+(?:\.\d+)?\s*(?:小时|时|[＊*×✘xX])|[A-Za-z0-9][A-Za-z0-9._/-]*-\d+")
HOURLY_START = re.compile(r"计时|工时|计(?=\s*[:：]?\s*\d)|\d+(?:\.\d+)?\s*(?:小时|时)")
HOUR_VALUE = re.compile(
    r"^(?:计时|工时|计)?\s*[:：]?\s*(?P<hours>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>小时|时|h)?\s*(?:(?P<minutes>\d+)\s*分(?:钟)?|(?P<half>半))?"
    r"(?:\s*[＊*×✘xX]\s*(?P<rate>\d+(?:\.\d+)?))?"
    r"\s*(?P<note>（[^（）]+）|\([^()]+\)|[\u4e00-\u9fff]+)?\s*$"
)


def record_key(record: WorkRecord) -> tuple:
    """用于识别同一批/同一会话中完全相同的记工记录。"""
    return (record.employee_id, record.work_date, record.group_id, record.kind,
            record.item_code, record.quantity, record.unit_price, record.hours, record.note)


def parse_hours(value: str) -> Decimal:
    return parse_hour_entry(value)[0]


def parse_hour_entry(value: str) -> tuple[Decimal, str | None]:
    match = HOUR_VALUE.fullmatch(value.strip())
    if not match:
        raise ValueError("无法确认工时格式")
    rate = match.group('rate')
    if rate is not None and Decimal(rate) != Decimal('15'):
        raise ValueError('消息中的计时时薪不是已确认的15元，请人工确认')
    hours = Decimal(match.group("hours"))
    minutes = int(match.group("minutes") or 0)
    if match.group("half"):
        if not match.group("unit"):
            raise ValueError("半小时缺少单位")
        minutes = 30
    if minutes >= 60 or (minutes and not match.group("unit")) or (minutes and hours != hours.to_integral_value()):
        raise ValueError("分钟数无效")
    result = hours + Decimal(minutes) / Decimal(60)
    if result <= 0 or result > 24:
        raise ValueError("工时超出范围")
    note = match.group('note')
    if note:
        if note.startswith(('（', '(')):
            note = note[1:-1].strip()
        if note.startswith(('小时', '时', '分钟', '分', '半', '多')):
            raise ValueError('工时后的文字可能是未解析的时间，请人工确认')
    return result, note


def parse_messages(text: str, directory: EmployeeDirectory, group_id: str,
                   sender_hints: set[str] | None = None) -> ParseResult:
    directory.require_group(group_id)
    records: list[WorkRecord] = []
    warnings: list[str] = []
    price_warnings: list[str] = []
    catalog = ItemCatalog()
    seen: set[tuple] = set()
    current_date: date | None = None
    current_employee: str | None = None
    pending: list[str] = []
    pending_original: list[str] = []
    pending_kind: WorkKind | None = None
    pending_line = 0
    pending_date: date | None = None
    pending_employee: str | None = None

    def finish_pending() -> None:
        nonlocal pending, pending_original, pending_kind
        if not pending:
            return
        body = " ".join(pending)
        original_body = " ".join(pending_original)
        try:
            if pending_date is None:
                raise ValueError("缺少有效工作日期")
            if pending_employee is None:
                raise ValueError("员工未绑定或未确认")
            if pending_kind == WorkKind.PIECE:
                if len(re.findall(r"\d+(?:\.\d+)?\s*[＊*×✘xX]\s*\d+(?:\.\d+)?", body)) > 1:
                    raise ValueError("多条疑似计件内容混在一起")
                code = CODE.search(body)
                quantity = QUANTITY.search(body)
                price = PRICE.search(body)
                compact_matches = list(COMPACT_PIECE.finditer(body))
                separated_matches = list(SEPARATED_PIECE.finditer(body))
                if len(compact_matches) + len(separated_matches) > 1:
                    raise ValueError("多条计件内容混在一起")
                compact = compact_matches[0] if compact_matches else None
                separated = separated_matches[0] if separated_matches else None
                no_price = PRICELESS_PIECE.search(body) if not compact else None
                if code and quantity and price:
                    item_code = code.group("value")
                    qty, unit_price = Decimal(quantity.group("value")), Decimal(price.group("value"))
                elif code and quantity:
                    item_code = normalize_code(code.group("value"))
                    qty = Decimal(quantity.group("value"))
                    unit_price = catalog.default_price(item_code)
                    if unit_price is None:
                        raise ValueError(f"{item_code} 未确认现行默认单价，请人工填写单价")
                elif separated:
                    item_code = separated.group("code")
                    if item_code not in catalog.codes:
                        raise ValueError(f"{item_code} 未在已知完整货号库中，双分隔符含义需人工确认")
                    qty, unit_price = Decimal(separated.group("qty")), Decimal(separated.group("price"))
                elif compact:
                    item_code = compact.group("code")
                    qty, unit_price = Decimal(compact.group("qty")), Decimal(compact.group("price"))
                    if code and code.group("value") != item_code:
                        raise ValueError("货号存在冲突")
                elif no_price:
                    item_code = no_price.group("code")
                    qty = Decimal(no_price.group("qty"))
                    unit_price = catalog.default_price(item_code)
                    if unit_price is None:
                        raise ValueError(f"{item_code} 未确认现行默认单价，请人工填写单价")
                else:
                    raise ValueError("货号、数量或单价不完整")
                item_code = normalize_code(item_code)
                if not re.fullmatch(r"\d{4}(?:-\d)?", item_code) and item_code.isdigit():
                    raise ValueError("货号格式异常，请核对完整货号")
                if DATE.fullmatch(item_code) or qty <= 0 or unit_price < 0:
                    raise ValueError("货号、数量或单价无效")
                confirmed = catalog.default_price(item_code)
                if confirmed is not None and unit_price != confirmed:
                    price_warnings.append(f"第{pending_line}行 {item_code} 消息单价{unit_price}元，与已确认默认价{confirmed}元不同；按消息单价计算，保存前须确认")
                record = WorkRecord(pending_employee, pending_date, WorkKind.PIECE, group_id,
                                    original_body, item_code, qty, unit_price, source_line=pending_line)
            else:
                marker = HOURLY_START.search(body)
                if marker is None:
                    raise ValueError("缺少计时内容")
                hours, note = parse_hour_entry(body[marker.start():])
                record = WorkRecord(pending_employee, pending_date, WorkKind.HOURLY, group_id,
                                    original_body, hours=hours, note=note, source_line=pending_line)
            key = record_key(record)
            if key in seen:
                raise ValueError("疑似重复记录，请人工确认")
            seen.add(key)
            records.append(record)
        except (ValueError, InvalidOperation) as exc:
            if pending_employee is None:
                warnings.append(f"第{pending_line}行需人工核对：员工未绑定或未确认；原文：{original_body}")
            else:
                warnings.append(f"第{pending_line}行需人工核对：{exc}；原文：{original_body}；{catalog.review_candidates(body)}")
        pending = []
        pending_original = []
        pending_kind = None

    # 截图 OCR 通常换行；也接受用户粘贴的反斜杠分隔示例。
    for line_number, raw_line in enumerate(text.replace("\\", "\n").splitlines(), 1):
        raw_original = raw_line.strip()
        raw_line = normalize_code(raw_line.strip())
        if not raw_line:
            continue
        labelled_piece = re.search(r"货号", raw_line)
        compact_piece = SEPARATED_PIECE.search(raw_line) or COMPACT_PIECE.search(raw_line) or PRICELESS_PIECE.search(raw_line)
        piece_start = (labelled_piece or compact_piece).start() if (labelled_piece or compact_piece) else None
        hourly_label = HOURLY_START.search(raw_line)
        hour_start = hourly_label.start() if hourly_label else None
        if piece_start is not None and hour_start is not None:
            split_at = max(piece_start, hour_start)
            segments = (raw_line[:split_at].strip(), raw_line[split_at:].strip())
            original_segments = (raw_original[:split_at].strip(), raw_original[split_at:].strip())
        else:
            segments = (raw_line,)
            original_segments = (raw_original,)
        for line, original_line in zip(segments, original_segments):
            if not line:
                continue
            date_match = DATE.search(line)
            matched_people = [employee for employee in directory.employees
                              if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", line)
                                     for name in (employee.name, *employee.aliases))]
            unknown_sender = bool(sender_hints and not matched_people and any(
                re.search(rf"(?<!\w){re.escape(name)}(?!\w)", line) for name in sender_hints))
            piece_marker = re.search(r"货号", line)
            compact = SEPARATED_PIECE.search(line) or COMPACT_PIECE.search(line) or PRICELESS_PIECE.search(line)
            standalone_code = STANDALONE_CODE.fullmatch(line)
            hour_marker = HOURLY_START.search(line)
            new_kind = (WorkKind.PIECE if piece_marker or compact or (standalone_code and pending_kind != WorkKind.PIECE)
                        else WorkKind.HOURLY if hour_marker else None)
            if (new_kind == WorkKind.HOURLY and pending_kind == WorkKind.HOURLY
                    and len(pending) == 1 and re.search(r"(?:计时|工时)\s*[:：]?\s*$", pending[0])
                    and not re.search(r"计时|工时", line)):
                new_kind = None
            if pending and new_kind is None and WORKLIKE.search(line):
                body = " ".join(pending)
                complete_piece = (SEPARATED_PIECE.search(body) is not None or
                                  COMPACT_PIECE.search(body) is not None or
                                  all(pattern.search(body) for pattern in (CODE, QUANTITY, PRICE)))
                complete_hour = False
                if pending_kind == WorkKind.HOURLY:
                    marker = HOURLY_START.search(body)
                    try:
                        if marker:
                            parse_hours(body[marker.start():])
                            complete_hour = True
                    except ValueError:
                        pass
                if complete_piece or complete_hour:
                    finish_pending()
            if pending and (new_kind is not None or date_match or matched_people or unknown_sender):
                finish_pending()
            if date_match:
                try:
                    current_date = date(*(int(date_match.group(key)) for key in ("year", "month", "day")))
                except ValueError:
                    current_date = None
                    warnings.append(f"第{line_number}行需人工核对：日期无效")
            if matched_people:
                current_employee = matched_people[0].employee_id if len(matched_people) == 1 else None
                if len(matched_people) != 1:
                    warnings.append(f"第{line_number}行需人工核对：员工不唯一")
            elif unknown_sender:
                current_employee = None
                warnings.append(f"第{line_number}行需人工核对：员工未绑定（微信昵称尚未确认）")
            if new_kind is not None:
                pending = [line]
                pending_original = [original_line]
                pending_kind = new_kind
                pending_line = line_number
                pending_date = current_date
                pending_employee = current_employee
            elif pending:
                pending.append(line)
                pending_original.append(original_line)
            else:
                residue = DATE.sub("", line)
                for employee in directory.employees:
                    for name in (employee.name, *employee.aliases):
                        residue = residue.replace(name, "")
                if WORKLIKE.search(residue):
                    warnings.append(f"第{line_number}行需人工核对：疑似记工内容无法解析；原文：{original_line}；{catalog.review_candidates(line)}")
    finish_pending()
    return ParseResult(tuple(records), tuple(warnings), tuple(price_warnings))
