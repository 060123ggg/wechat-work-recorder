"""工资表边界：真实账本需要列映射；测试账本仅保存人工确认的记录。"""
from pathlib import Path
from typing import Protocol, Sequence
from openpyxl import Workbook
from .models import WorkRecord
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


def write_mock_workbook(destination: Path, records: Sequence[WorkRecord], confirmed: bool = False) -> None:
    """只新建模拟表；拒绝覆盖任何已有文件。"""
    if not confirmed:
        raise PermissionError("必须先人工确认记录")
    if not records:
        raise ValueError("没有可写入的记录")
    destination = Path(destination)
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("模拟表必须为 .xlsx 文件")
    rows = UnconfiguredWorkbookWriter().preview(records)
    wb = Workbook()
    ws = wb.active
    ws.title = "模拟记工"
    headers = ["employee_id", "date", "group_id", "kind", "item_code", "quantity", "unit_price", "hours", "amount", "note"]
    ws.append(headers)
    for row in rows:
        ws.append([row[key] for key in headers])
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = destination.open("xb")
    try:
        with output:
            wb.save(output)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
