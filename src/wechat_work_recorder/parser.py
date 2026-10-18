"""按消息上下文解析跨行记工内容；含糊字段交由人工核对。"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from .employees import EmployeeDirectory
from .models import ParseResult, WorkKind, WorkRecord

DATE = re.compile(r"(?P<year>\d{4})[-/年](?P<month>\d{1,2})[-/月](?P<day>\d{1,2})日?")
CODE = re.compile(r"货号\s*[:：]?\s*(?P<value>[A-Za-z0-9][A-Za-z0-9._/-]*)")
QUANTITY = re.compile(r"数量\s*[:：]?\s*(?P<value>\d+(?:\.\d+)?)(?=\s|件|个|单价|$)")
PRICE = re.compile(r"单价\s*[:：]?\s*(?P<value>\d+(?:\.\d+)?)(?=\s|元|$)")
HOURLY_START = re.compile(r"计时|工时|\d+(?:\.\d+)?\s*(?:小时|时)")
HOUR_VALUE = re.compile(
    r"^(?:计时|工时)?\s*[:：]?\s*(?P<hours>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>小时|时|h)?\s*(?:(?P<minutes>\d+)\s*分(?:钟)?|(?P<half>半))?\s*$"
)


def record_key(record: WorkRecord) -> tuple:
    """用于识别同一批/同一会话中完全相同的记工记录。"""
    return (record.employee_id, record.work_date, record.group_id, record.kind,
            record.item_code, record.quantity, record.unit_price, record.hours)


def parse_hours(value: str) -> Decimal:
    match = HOUR_VALUE.fullmatch(value.strip())
    if not match:
        raise ValueError("无法确认工时格式")
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
    return result


def parse_messages(text: str, directory: EmployeeDirectory, group_id: str) -> ParseResult:
    directory.require_group(group_id)
    records: list[WorkRecord] = []
    warnings: list[str] = []
    seen: set[tuple] = set()
    current_date: date | None = None
    current_employee: str | None = None
    pending: list[str] = []
    pending_kind: WorkKind | None = None
    pending_line = 0
    pending_date: date | None = None
    pending_employee: str | None = None

    def finish_pending() -> None:
        nonlocal pending, pending_kind
        if not pending:
            return
        body = " ".join(pending)
        try:
            if pending_date is None or pending_employee is None:
                raise ValueError("缺少完整日期或唯一员工")
            if pending_kind == WorkKind.PIECE:
                code = CODE.search(body)
                quantity = QUANTITY.search(body)
                price = PRICE.search(body)
                if not (code and quantity and price):
                    raise ValueError("货号、数量或单价不完整")
                qty, unit_price = Decimal(quantity.group("value")), Decimal(price.group("value"))
                if qty <= 0 or unit_price < 0:
                    raise ValueError("数量或单价无效")
                record = WorkRecord(pending_employee, pending_date, WorkKind.PIECE, group_id,
                                    body, code.group("value"), qty, unit_price)
            else:
                marker = HOURLY_START.search(body)
                if marker is None:
                    raise ValueError("缺少计时内容")
                hours = parse_hours(body[marker.start():])
                record = WorkRecord(pending_employee, pending_date, WorkKind.HOURLY, group_id,
                                    body, hours=hours)
            key = record_key(record)
            if key in seen:
                raise ValueError("疑似重复记录，请人工确认")
            seen.add(key)
            records.append(record)
        except (ValueError, InvalidOperation) as exc:
            warnings.append(f"第{pending_line}行需人工核对：{exc}")
        pending = []
        pending_kind = None

    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        date_match = DATE.search(line)
        matched_people = [employee for employee in directory.employees
                          if any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", line)
                                 for name in (employee.name, *employee.aliases))]
        piece_marker = re.search(r"货号", line)
        hour_marker = HOURLY_START.search(line)
        new_kind = WorkKind.PIECE if piece_marker else WorkKind.HOURLY if hour_marker else None
        if (new_kind == WorkKind.HOURLY and pending_kind == WorkKind.HOURLY
                and len(pending) == 1 and re.search(r"(?:计时|工时)\s*[:：]?\s*$", pending[0])
                and not re.search(r"计时|工时", line)):
            new_kind = None
        if pending and (new_kind is not None or date_match or matched_people):
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
        if piece_marker and hour_marker:
            warnings.append(f"第{line_number}行需人工核对：同时包含按件和计时")
            continue
        if new_kind is not None:
            pending = [line]
            pending_kind = new_kind
            pending_line = line_number
            pending_date = current_date
            pending_employee = current_employee
        elif pending:
            pending.append(line)
    finish_pending()
    return ParseResult(tuple(records), tuple(warnings))
