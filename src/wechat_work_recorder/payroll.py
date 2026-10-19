"""工资金额计算。"""
from decimal import Decimal, ROUND_HALF_UP
from .models import WorkKind, WorkRecord

HOURLY_RATE = Decimal("15")


def calculate_amount(record: WorkRecord) -> Decimal:
    if record.kind == WorkKind.HOURLY:
        if record.hours is None or not record.hours.is_finite() or record.hours <= 0 or record.hours > 24:
            raise ValueError("有效工时必填")
        amount = record.hours * HOURLY_RATE
    elif record.kind == WorkKind.PIECE:
        if (record.quantity is None or record.unit_price is None or not record.quantity.is_finite()
                or not record.unit_price.is_finite() or record.quantity <= 0 or record.unit_price < 0 or not record.item_code):
            raise ValueError("完整货号、数量和单价必填")
        amount = record.quantity * record.unit_price
    else:
        raise ValueError("未知工种")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
