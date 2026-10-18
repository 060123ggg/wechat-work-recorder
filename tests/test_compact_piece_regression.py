"""Windows 实机反馈：无“货号”标签的紧凑计件行不得被静默跳过。"""
from decimal import Decimal
import pytest
from wechat_work_recorder.employees import EmployeeDirectory
from wechat_work_recorder.models import Employee, WorkKind
from wechat_work_recorder.parser import parse_messages
from wechat_work_recorder.payroll import calculate_amount


def directory():
    return EmployeeDirectory([Employee("xq", "雪琴")], ["一群"])


@pytest.mark.parametrize("separator", ["\n", "\\"])
def test_reported_piece_and_hourly_message(separator):
    text = separator.join(("2026/10/9", "雪琴", "8513-7 70*1.7", "计时3.5"))
    result = parse_messages(text, directory(), "一群")
    assert result.warnings == ()
    assert len(result.records) == 2
    piece, hourly = result.records
    assert piece.kind == WorkKind.PIECE
    assert piece.employee_id == "xq"
    assert piece.item_code == "8513-7"
    assert piece.quantity == Decimal("70")
    assert piece.unit_price == Decimal("1.7")
    assert calculate_amount(piece) == Decimal("119.00")
    assert hourly.kind == WorkKind.HOURLY
    assert hourly.hours == Decimal("3.5")
    assert calculate_amount(hourly) == Decimal("52.50")
    assert sum(map(calculate_amount, result.records), Decimal("0")) == Decimal("171.50")


@pytest.mark.parametrize("message", [
    "8513-6 70*1.7 计时3.5",
    "计时3.5 8513-7 70*1.7",
    "8510-1 70×1.7 计时3.5",
    "8513-7 70x1.7 计时3.5",
    "8513-7 70＊1.7 计时3.5",
    "8513-7 70 * 1.7 计时3.5",
    "货号 8513-7 70*1.7 计时3.5",
])
def test_compact_piece_and_time_on_one_line(message):
    result = parse_messages("2026/10/9\n雪琴\n" + message, directory(), "一群")
    assert not result.warnings
    assert len(result.records) == 2
    assert {record.kind for record in result.records} == {WorkKind.PIECE, WorkKind.HOURLY}
    assert sum(map(calculate_amount, result.records), Decimal("0")) == Decimal("171.50")


def test_compact_piece_split_across_lines():
    result = parse_messages("2026/10/9\n雪琴\n8513-7\n70*1.7\n计时3.5", directory(), "一群")
    assert not result.warnings
    assert [record.item_code for record in result.records] == ["8513-7", None]


@pytest.mark.parametrize("suspect", ["8513-7 70*", "8513-7 70*?", "70*1.7", "8513-7"])
def test_unparsed_worklike_line_is_reported(suspect):
    result = parse_messages("2026/10/9\n雪琴\n" + suspect + "\n计时3.5", directory(), "一群")
    assert len(result.records) == 1
    assert result.records[0].kind == WorkKind.HOURLY
    assert result.warnings
    assert "人工核对" in result.warnings[0]


def test_repeated_compact_piece_is_flagged():
    result = parse_messages("2026/10/9\n雪琴\n8513-7 70*1.7\n8513-7 70*1.7", directory(), "一群")
    assert len(result.records) == 1
    assert "重复" in result.warnings[0]


def test_valid_record_before_unparseable_piece_is_kept_and_warned():
    result = parse_messages("2026/10/9\n雪琴\n计时3.5\n8513-7 70*", directory(), "一群")
    assert len(result.records) == 1
    assert result.records[0].kind == WorkKind.HOURLY
    assert result.warnings


def test_valid_compact_piece_before_unparseable_piece_is_kept_and_warned():
    result = parse_messages("2026/10/9\n雪琴\n8513-7 70*1.7\n8510-1 10*", directory(), "一群")
    assert len(result.records) == 1
    assert result.records[0].item_code == "8513-7"
    assert result.warnings
