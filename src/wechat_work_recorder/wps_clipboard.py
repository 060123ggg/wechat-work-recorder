"""准备 WPS 分列粘贴数据；从不生成 E/G/J/K 单元格。"""
from decimal import Decimal
from typing import Sequence
from .models import WorkKind, WorkRecord
from .payroll import calculate_amount

def to_wps_segments(records: Sequence[WorkRecord], names_by_id: dict[str, str]) -> dict[str, str]:
    """分别复制 B:D（日期/工号/姓名）、F（项目）、H:I（数量/单价）。"""
    if not records:
        raise ValueError("没有可复制的记录")
    rows: dict[str, list[str]] = {"B:D": [], "F": [], "H:I": []}
    for record in records:
        name = names_by_id.get(record.employee_id)
        if not name:
            raise ValueError(f"找不到员工 {record.employee_id} 的姓名")
        if record.kind == WorkKind.HOURLY:
            if record.unit_price is not None and record.unit_price != Decimal("15"):
                raise ValueError("计时时薪必须为15元，请核对该记录")
            code, quantity, rate = "计时", record.hours, Decimal("15")
        elif record.kind == WorkKind.PIECE:
            code, quantity, rate = record.item_code, record.quantity, record.unit_price
        else:
            raise ValueError("未知工作类型")
        calculate_amount(record)
        if not code or quantity is None or rate is None:
            raise ValueError("存在不完整记录")
        values = [record.work_date.isoformat().replace("-", "/"), record.employee_id,
                  name, str(code), str(quantity), str(rate)]
        if any("\t" in value or "\n" in value or "\r" in value for value in values):
            raise ValueError("数据中包含非法换行或制表符")
        if any(value.lstrip().startswith(("=", "+", "-", "@"))
               for value in (record.employee_id, name, str(code))):
            raise ValueError("货号、工号或姓名不能以公式符号开头，请核对原文")
        rows["B:D"].append("\t".join(values[:3]))
        rows["F"].append(values[3])
        rows["H:I"].append("\t".join(values[4:]))
    return {column: "\r\n".join(lines) for column, lines in rows.items()}
