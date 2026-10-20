"""按消息上下文解析跨行记工内容；含糊字段交由人工核对。"""
import re
from decimal import Decimal, InvalidOperation
from .catalog import ItemCatalog, normalize_code, valid_catalog_code
from .employees import EmployeeDirectory
from .models import ParseResult, WorkKind, WorkRecord
from .payroll import calculate_amount

from .message_context import DATE, WORKLIKE

STANDALONE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*-\d+")
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
    value = value.strip()
    prefix_note = ""
    prefix = re.match(r"^(?:计时|工时)([^\d]*)(?=\d)", value)
    if prefix:
        prefix_note = prefix[1].strip(" 。.：:，,;；")
        value = "计时" + value[prefix.end():]
    match = HOUR_VALUE.fullmatch(value)
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
    note = "；".join(x for x in (prefix_note, note) if x) or None
    return result, note


# 完整项目优先匹配；单横杠紧挨数字时，只有明确数量单位才解除边界歧义。
NUMBER = r'\d+(?:\.\d+)?'
UNIT = r'个|件|捆|套|只|箱|袋|组|包'
MULTIPLY = r'[＊*×✘xX]'
TAIL = rf'(?P<qty>{NUMBER})\s*(?P<unit>{UNIT})?\s*(?:{MULTIPLY}\s*(?P<price>{NUMBER})\s*元?)?'


def piece_fields(body: str, catalog: ItemCatalog, inherited: str | None = None):
    """返回明确项目、数量、消息价格与单位；不依照价格改写货号。"""
    body = normalize_code(body).strip(' ，,；;。')
    patterns = [
        # 8510-216个：单位明确了数量边界，不截为 8510-2 / 16。
        rf'(?P<code>\d{{4}})-(?P<qty>{NUMBER})\s*(?P<unit>{UNIT})\s*(?:{MULTIPLY}\s*(?P<price>{NUMBER})\s*元?)?',
        rf'(?P<code>\d{{4}}(?:-\d)?)(?:--|~~){TAIL}',
        rf'(?P<code>[A-Za-z0-9][A-Za-z0-9._/-]*)\s+{TAIL}',
        rf'(?P<code>[\u4e00-\u9fff]{{2,24}})\s*[-:：]?\s*{TAIL}',
    ]
    for pattern in patterns:
        if match := re.fullmatch(pattern, body):
            code = catalog.canonical(match['code'])
            if match['code'].isdigit() and not re.fullmatch(r'\d{4}', match['code']):
                raise ValueError('货号格式异常，请核对完整货号')
            if '--' in body or '~~' in body:
                if code not in catalog.codes:
                    raise ValueError(f'{code} 未在已知完整货号库中，双分隔符含义需人工确认')
            return code, Decimal(match['qty']), (Decimal(match['price']) if match['price'] else None), match['unit'] or catalog.items.get(code, {}).get('unit', '件'), False
    if match := re.fullmatch(rf'(?P<qty>{NUMBER})\s*(?P<unit>{UNIT})\s*(?:{MULTIPLY}\s*(?P<price>{NUMBER})\s*元?)?', body):
        if not inherited:
            raise ValueError('项目继承不确定：同一消息内没有最近的明确项目')
        return inherited, Decimal(match['qty']), Decimal(match['price']) if match['price'] else None, match['unit'], True
    raise ValueError('货号、数量边界或单价不完整，需人工确认')


def _clean_body(raw, block, groups):
    from .message_context import TIME
    value = DATE.sub('', raw)
    value = TIME.sub('', value).strip(' ：:，,')
    value = re.sub(r'^(?:发送人|微信昵称|微信发送时间|正文)[：:]\s*', '', value)
    if block.nickname:
        value = re.sub(rf'^{re.escape(block.nickname)}(?:[：:]|\s+|$)', '', value).strip()
    for group in groups:
        value = re.sub(rf'(?<!\w){re.escape(group)}(?!\w)', '', value).strip()
    if value in groups:
        return ''
    return value


def parse_messages(text: str, directory: EmployeeDirectory, group_id: str,
                   sender_hints: set[str] | None = None, *, catalog: ItemCatalog | None = None,
                   identity_overrides: dict | None = None, date_overrides: dict | None = None) -> ParseResult:
    from dataclasses import replace
    from difflib import SequenceMatcher
    from .message_context import split_messages, date_for_line, PARTIAL_DATE, WORKLIKE as NEW_WORKLIKE
    directory.require_group(group_id)
    catalog = catalog or ItemCatalog()
    names = [name for e in directory.employees for name in (e.name, *e.aliases)]
    blocks = split_messages(text, list(directory.group_ids), names, catalog.recognition_names)
    records, proposals, warnings, price_warnings = [], [], [], []
    seen, previous_messages = set(), []
    for block in blocks:
        employee = directory.resolve(block.nickname) if block.nickname else None
        employee_id = (identity_overrides or {}).get(block.number) or (employee.employee_id if employee else None)
        inherited = None
        entries = []
        lines = block.raw_text.splitlines()
        index = 0
        while index < len(lines):
            raw = lines[index].strip()
            body = _clean_body(raw, block, directory.group_ids)
            line = block.start_line + index
            index += 1
            if not body or PARTIAL_DATE.fullmatch(body):
                continue
            if body.startswith('货号') or STANDALONE_CODE.fullmatch(body) or re.fullmatch(r'\d{4}', body) or body in ('计时', '工时'):
                while index < len(lines):
                    following = lines[index].strip()
                    if (re.fullmatch(rf'(?:数量|单价)\s*[:：]?\s*(?:{NUMBER})?\s*(?:{UNIT}|元)?\s*', following)
                            or (re.fullmatch(NUMBER, following) and (not PARTIAL_DATE.fullmatch(following) or body.endswith(('数量','单价'))))
                            or following in ('数量', '单价')
                            or (body.rstrip('：:') == '货号' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', following))
                            or ((STANDALONE_CODE.fullmatch(body) or re.fullmatch(r'\d{4}', body)) and re.fullmatch(TAIL, following))
                            or (body in ('计时', '工时') and re.match(r'\d', following))):
                        body += ' ' + following
                        raw += '\n' + following
                        index += 1
                    else:
                        break
            if index < len(lines) and re.fullmatch(rf'\s*{MULTIPLY}\s*{NUMBER}\s*元?\s*', lines[index]):
                body += ' ' + lines[index].strip()
                raw += '\n' + lines[index].strip()
                index += 1
            # 同行混合计件/计时按标记分割，计时内部的 *15 不参与计件判断。
            marker = HOURLY_START.search(body)
            if marker and marker.start() > 0 and NEW_WORKLIKE.search(body[:marker.start()]):
                entries.extend([(line, body[:marker.start()].strip(), raw),
                                (line, body[marker.start():], raw)])
            elif marker and marker.start() == 0:
                # 支持“计时3.5 8513-7 70*1.7”。
                next_piece = re.search(r'\s+(?=\d{4}(?:-\d)?(?:\s|--|~~))', body)
                if next_piece:
                    entries.extend([(line, body[:next_piece.start()], raw),
                                    (line, body[next_piece.end():], raw)])
                else:
                    entries.append((line, body, raw))
            else:
                entries.append((line, body, raw))
        start_records = len(records)
        block_work = []
        for line, body, original in entries:
            identified = False
            body = normalize_code(body)
            if not (NEW_WORKLIKE.search(body) or re.match(r'^\d{4}', body) or
                    any(name in body for name in catalog.recognition_names)):
                # 日期/群名/闲聊没有工作标记，不生成工资记录。
                continue
            try:
                if employee_id is None:
                    raise ValueError('员工未绑定或发送人待确认；请人工选择正式员工')
                work_date = (date_overrides or {}).get(block.number) or date_for_line(block, line)
                if work_date is None:
                    raise ValueError('缺少有效工作日期')
                if HOURLY_START.match(body):
                    inherited = None
                    hours, note = parse_hour_entry(body)
                    identified = True
                    record = WorkRecord(employee_id, work_date, WorkKind.HOURLY, group_id,
                                        original, hours=hours, note=note, source_line=line, message_number=block.number,
                                        quantity_unit='小时', price_source='固定时薪15元', standard_price_snapshot=Decimal('15'))
                elif re.fullmatch(rf'{NUMBER}\s*{MULTIPLY}\s*15(?:\.0+)?', body):
                    # A bare "3.5×15" is never auto-paid. A matching hourly item
                    # supplies a review draft only, not proof that it is hourly.
                    inherited = None
                    hours, note = parse_hour_entry(body)
                    record = WorkRecord(employee_id, work_date, WorkKind.HOURLY, group_id,
                                        original, hours=hours, source_line=line, message_number=block.number,
                                        quantity_unit='小时', price_source='待人工确认计时', standard_price_snapshot=Decimal('15'))
                    identified = True
                    if any(r.employee_id == employee_id and r.work_date == work_date and
                           r.kind == WorkKind.HOURLY and r.hours == hours for r in records + proposals):
                        proposals.append(record)
                        raise ValueError('疑似重复计时记录：省略了计时标记，请确认类型及是否为独立工作')
                    raise ValueError('未标明项目或计时，不能仅凭乘以15元确认工资类型')
                elif body.startswith('货号'):
                    labelled = re.fullmatch(
                        rf'货号\s*[:：]?\s*(?P<code>[A-Za-z0-9][A-Za-z0-9._/-]*)\s+'
                        rf'数量\s*[:：]?\s*(?P<qty>{NUMBER})\s*(?:{UNIT})?\s*'
                        rf'(?:单价\s*[:：]?\s*(?P<price>{NUMBER})\s*元?)?', body)
                    if labelled:
                        code = normalize_code(labelled['code'])
                        qty = Decimal(labelled['qty'])
                        message_price = Decimal(labelled['price']) if labelled['price'] else None
                    else:
                        code, qty, message_price, _, _ = piece_fields(re.sub(r'^货号\s*[:：]?\s*', '', body), catalog)
                    price = message_price if message_price is not None else catalog.default_price(code)
                    record = WorkRecord(employee_id, work_date, WorkKind.PIECE, group_id, original,
                                        code, qty, price, source_line=line, message_number=block.number,
                                        quantity_unit=catalog.items.get(code, {}).get('unit', '件'),
                                        price_source='消息单价' if message_price is not None else '当前标准价',
                                        standard_price_snapshot=catalog.default_price(code))
                    inherited = code
                    identified = True
                    if price is None:
                        proposals.append(record)
                        raise ValueError(f'{code} 当前标准价未确认，请人工填写单价')
                    if valid_catalog_code(code) and code not in catalog.codes:
                        proposals.append(record)
                        raise ValueError(f'新增项目 {code} 尚未确认，请新增并确认标准单价')
                else:
                    code, qty, price, unit, was_inherited = piece_fields(body, catalog, inherited)
                    inherited = code
                    identified = True
                    record = WorkRecord(employee_id, work_date, WorkKind.PIECE, group_id, original,
                                        code, qty, price if price is not None else catalog.default_price(code),
                                        note=f'沿用本消息项目：{code}' if was_inherited else None,
                                        source_line=line, message_number=block.number, quantity_unit=unit,
                                        price_source='消息单价' if price is not None else '当前标准价',
                                        standard_price_snapshot=catalog.default_price(code))
                    if code not in catalog.codes:
                        proposals.append(record)
                        raise ValueError(f'新增项目 {code} 尚未确认，请新增并确认标准单价')
                    if record.unit_price is None:
                        proposals.append(record)
                        raise ValueError(f'{code} 当前标准价尚未确认，请选择或填写单价')
                calculate = calculate_amount
                calculate(record)
                key = record_key(record)
                if key in seen:
                    proposals.append(record)
                    raise ValueError('疑似重复记录，请人工确认是否为独立工作，不会自动计入第二条')
                seen.add(key)
                records.append(record)
                block_work.append(body)
                if record.kind == WorkKind.PIECE:
                    current = catalog.default_price(record.item_code)
                    if current is not None and current != record.unit_price:
                        price_warnings.append(f'第{line}行需人工核对：{record.item_code} 当前标准价（默认价）{current}元；本次单价{record.unit_price}元；数量{record.quantity}；金额{calculate(record):.2f}元；原文：{original}')
                    elif current is None and catalog.price_history(record.item_code):
                        price_warnings.append(f'第{line}行需人工核对：{record.item_code} 当前标准价未确认（多个历史价格），本次单价{record.unit_price}元；数量{record.quantity}；金额{calculate(record):.2f}元；原文：{original}')
            except (ValueError, InvalidOperation) as exc:
                if not identified:
                    inherited = None
                reason = str(exc)
                suffix = '' if identified or HOURLY_START.match(body) or '员工未绑定' in reason else f'；{catalog.review_candidates(body)}'
                warnings.append(f'第{line}行需人工核对：{reason}；原文：{original}{suffix}')
        # 高度相似消息只做提醒；保留草稿供人工决定，禁止直接重复计入。
        current_records = records[start_records:]
        if current_records:
            fingerprint = ' '.join(block_work)
            same = next((old for old in previous_messages if old[0] == employee_id
                         and old[1] == current_records[0].work_date
                         and SequenceMatcher(None, old[2], fingerprint).ratio() >= .92), None)
            if same:
                for record in current_records:
                    proposals.append(record)
                    warnings.append(f'第{record.source_line}行需人工核对：疑似重复消息，与第{same[3]}条高度相似，请确认是否独立工作；原文：{record.source_text}')
                del records[start_records:]
            previous_messages.append((employee_id, current_records[0].work_date, fingerprint, block.number))
    return ParseResult(tuple(records), tuple(warnings), tuple(price_warnings), tuple(proposals))
