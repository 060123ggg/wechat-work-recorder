"""工资表写入边界：待取得真实账本模板后实现列映射。"""
from pathlib import Path
from typing import Protocol, Sequence
from .models import WorkRecord


class PayrollWorkbookWriter(Protocol):
    def preview(self, records: Sequence[WorkRecord]) -> list[dict[str, str]]: ...
    def write_copy(self, source: Path, destination: Path, records: Sequence[WorkRecord]) -> None: ...


class TemplateMappingRequired(RuntimeError):
    pass


class UnconfiguredWorkbookWriter:
    """阻止未配置列映射时触及工资表。"""
    def preview(self, records: Sequence[WorkRecord]) -> list[dict[str, str]]:
        from .payroll import calculate_amount
        return [{"employee_id": r.employee_id, "date": r.work_date.isoformat(), "group_id": r.group_id,
                 "kind": r.kind.value, "item_code": r.item_code or "", "quantity": str(r.quantity or ""),
                 "unit_price": str(r.unit_price or ""), "hours": str(r.hours or ""),
                 "amount": str(calculate_amount(r))} for r in records]

    def write_copy(self, source: Path, destination: Path, records: Sequence[WorkRecord]) -> None:
        raise TemplateMappingRequired("需要真实账本的工作表和列映射，才可实现写入副本")
