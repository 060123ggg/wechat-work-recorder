"""工资表边界：真实账本需要列映射；测试账本仅保存人工确认的记录。"""
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from openpyxl import Workbook
from openpyxl.styles import Alignment
from .models import WorkRecord
from .models import WorkKind
from .payroll import calculate_amount


class PayrollWorkbookWriter(Protocol):
    def preview(self, records: Sequence[WorkRecord]) -> list[dict[str, str]]: ...
    def write_copy(self, source: Path, destination: Path, records: Sequence[WorkRecord]) -> None: ...


class TemplateMappingRequired(RuntimeError):
    pass


class UnconfiguredWorkbookWriter:
    """阻止未配置列映射时触及工资表。"""
    def preview(self, records: Sequence[WorkRecord]) -> list[dict[str, str]]:
        return [{"employee_id": r.employee_id, "date": r.work_date.isoformat(), "group_id": r.group_id,
                 "kind": r.kind.value, "item_code": r.item_code or "", "quantity": str(r.quantity or ""),
                 "unit_price": str(r.unit_price or ""), "hours": str(r.hours or ""),
                 "amount": str(calculate_amount(r)), "note": r.note or ""} for r in records]

    def write_copy(self, source: Path, destination: Path, records: Sequence[WorkRecord]) -> None:
        raise TemplateMappingRequired("需要真实账本的工作表和列映射，才可实现写入副本")


def write_mock_workbook(destination: Path, records: Sequence[WorkRecord], confirmed: bool = False,
                        employee_names: Mapping[str, str] | None = None) -> None:
    """只新建模拟表；拒绝覆盖任何已有文件。"""
    if not confirmed:
        raise PermissionError("必须先人工确认记录")
    if not records:
        raise ValueError("没有可写入的记录")
    destination = Path(destination)
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("模拟表必须为 .xlsx 文件")
    wb = Workbook()
    ws = wb.active
    ws.title = "模拟记工"
    headers = ["日期", "员工编号", "姓名", "货号/项目", "数量/工时", "单价", "单项工资", "当日合计工资"]
    ws.append(headers)
    ordered = sorted(records, key=lambda record: (record.work_date, record.employee_id,
                                                  record.source_line or 0, record.kind.value))
    names = employee_names or {}
    groups: dict[tuple, list[int]] = {}
    totals: dict[tuple, object] = {}
    for record in ordered:
        hourly = record.kind == WorkKind.HOURLY
        key = (record.work_date, record.employee_id)
        row_number = ws.max_row + 1
        groups.setdefault(key, []).append(row_number)
        amount = calculate_amount(record)
        totals[key] = totals.get(key, 0) + amount
        ws.append([f'{record.work_date.year}/{record.work_date.month}/{record.work_date.day}',
                   record.employee_id, names.get(record.employee_id, ''),
                   '计时' if hourly else record.item_code,
                   float(record.hours if hourly else record.quantity),
                   15 if hourly else float(record.unit_price), float(amount), None])
        for column in (6, 7):
            ws.cell(row_number, column).number_format = '0.00'
    for key, row_numbers in groups.items():
        first, last = row_numbers[0], row_numbers[-1]
        cell = ws.cell(first, 8, float(totals[key]))
        cell.number_format = '0.00'
        cell.alignment = Alignment(horizontal='center', vertical='center')
        if last > first:
            ws.merge_cells(start_row=first, start_column=8, end_row=last, end_column=8)
    ws.freeze_panes = 'A2'
    audit = wb.create_sheet('审核追溯')
    audit.append(['消息序号', '原文行号', '微信群', '工作备注', '原始消息'])
    for record in ordered:
        audit.append([record.message_number, record.source_line, record.group_id,
                      record.note or '', record.source_text])
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = destination.open("xb")
    try:
        with output:
            wb.save(output)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
