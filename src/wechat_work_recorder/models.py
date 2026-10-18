"""跨模块的数据契约；金额统一使用 Decimal。"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class WorkKind(str, Enum):
    PIECE = "piece"
    HOURLY = "hourly"


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkRecord:
    employee_id: str
    work_date: date
    kind: WorkKind
    group_id: str
    source_text: str
    item_code: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    hours: Decimal | None = None


@dataclass(frozen=True)
class ParseResult:
    records: tuple[WorkRecord, ...]
    warnings: tuple[str, ...]
    price_warnings: tuple[str, ...] = ()
