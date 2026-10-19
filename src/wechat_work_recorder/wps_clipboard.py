"""将已核对的记工记录复制为适合 WPS B:J 粘贴的 TSV。"""
from decimal import Decimal
from typing import Sequence
from .models import WorkKind, WorkRecord
from .payroll import calculate_amount

def to_wps_tsv(records: Sequence[WorkRecord], names_by_id: dict[str, str]) -> str:
    """B 日期 C 工号 D 姓名 E 空 F 货号/计时 G 空 H 数量/工时 I 单价 J 金额。"""
    if not records:
        raise ValueError("没有可复制的记录")
    lines = []
    for record in records:
        name = names_by_id.get(record.employee_id)
        if not name:
            raise ValueError(f"找不到员工 {record.employee_id} 的姓名")
        if record.kind == WorkKind.HOURLY:
            code, quantity, rate = "计时", record.hours, Decimal("15")
        elif record.kind == WorkKind.PIECE:
            code, quantity, rate = record.item_code, record.quantity, record.unit_price
        else:
            raise ValueError("未知工作类型")
        amount = calculate_amount(record)
        if not code or quantity is None or rate is None:
            raise ValueError("存在不完整记录")
        cells = [record.work_date.isoformat().replace("-", "/"), record.employee_id,
                 name, "", str(code), "", str(quantity), str(rate), f"{amount:.2f}"]
        if any("\t" in str(v) or "\n" in str(v) or "\r" in str(v) for v in cells):
            raise ValueError("数据中包含非法换行或制表符")
        lines.append("\t".join(cells))
    return "\r\n".join(lines)
