"""保守的规则解析：每行一条，字段不全时交由人工核对。"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from .employees import EmployeeDirectory
from .models import ParseResult, WorkKind, WorkRecord

DATE = re.compile(r"(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})")
PIECE = re.compile(r"货号\s*[:：]?\s*(?P<code>[A-Za-z0-9][A-Za-z0-9._/-]*)\s+数量\s*[:：]?\s*(?P<qty>\d+(?:\.\d+)?)\s+单价\s*[:：]?\s*(?P<price>\d+(?:\.\d+)?)")
HOURLY = re.compile(r"(?:计时|工时)\s*[:：]?\s*(?P<hours>\d+(?:\.\d+)?)\s*(?:小时|时|h)?")


def parse_messages(text: str, directory: EmployeeDirectory, group_id: str) -> ParseResult:
    directory.require_group(group_id)
    records, warnings = [], []
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        date_match = DATE.search(line)
        people = [e for e in directory.employees if re.search(rf"(?<!\w){re.escape(e.name)}(?!\w)", line) or any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", line) for a in e.aliases)]
        piece_match, hourly_match = PIECE.search(line), HOURLY.search(line)
        if not date_match or len(people) != 1 or bool(piece_match) == bool(hourly_match):
            warnings.append(f"第{line_number}行需人工核对：日期、员工或工种不明确")
            continue
        try:
            work_date = date.fromisoformat(date_match.group("date").replace("/", "-"))
            if piece_match:
                qty, price = Decimal(piece_match.group("qty")), Decimal(piece_match.group("price"))
                if qty <= 0 or price < 0:
                    raise ValueError("数量或单价无效")
                record = WorkRecord(people[0].employee_id, work_date, WorkKind.PIECE, group_id, line, piece_match.group("code"), qty, price)
            else:
                hours = Decimal(hourly_match.group("hours"))
                if hours <= 0 or hours > 24:
                    raise ValueError("工时无效")
                record = WorkRecord(people[0].employee_id, work_date, WorkKind.HOURLY, group_id, line, hours=hours)
            records.append(record)
        except (ValueError, InvalidOperation):
            warnings.append(f"第{line_number}行需人工核对：数值或日期无效")
    return ParseResult(tuple(records), tuple(warnings))
