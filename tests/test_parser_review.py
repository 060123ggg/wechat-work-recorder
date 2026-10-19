from decimal import Decimal
import pytest
from wechat_work_recorder.employees import EmployeeDirectory
from wechat_work_recorder.models import Employee, WorkKind
from wechat_work_recorder.parser import parse_hours, parse_messages
from wechat_work_recorder.payroll import calculate_amount


def directory():
    return EmployeeDirectory([Employee("1", "张三", ("阿三",)), Employee("2", "李四")], ["一群"])


@pytest.mark.parametrize(("input_text", "hours", "amount"), [
    ("计时3小时30分", "3.5", "52.50"),
    ("3.5小时", "3.5", "52.50"),
    ("计时3.5", "3.5", "52.50"),
    ("计时3小时半", "3.5", "52.50"),
    ("计时2小时15分", "2.25", "33.75"),
])
def test_hour_formats(input_text, hours, amount):
    result = parse_messages(f"2026-10-18 张三 {input_text}", directory(), "一群")
    assert not result.warnings
    assert result.records[0].hours == Decimal(hours)
    assert calculate_amount(result.records[0]) == Decimal(amount)


@pytest.mark.parametrize(('input_text', 'hours', 'note', 'amount'), [
    ('计时3（贴标套袋打包）', '3', '贴标套袋打包', '45.00'),
    ('计时6（拆废品）', '6', '拆废品', '90.00'),
    ('计3.5快递', '3.5', '快递', '52.50'),
    ('计2.5*15快递', '2.5', '快递', '37.50'),
    ('3小时30分拆快递', '3.5', '拆快递', '52.50'),
    ('计6.5贴标快递', '6.5', '贴标快递', '97.50'),
    ('计时3(贴标套袋打包)', '3', '贴标套袋打包', '45.00'),
])
def test_hourly_notes_are_preserved(input_text, hours, note, amount):
    result = parse_messages(f'2026年10月12日 张三 {input_text}', directory(), '一群')
    assert not result.warnings and len(result.records) == 1
    record = result.records[0]
    assert record.hours == Decimal(hours) and record.note == note
    assert record.source_text.endswith(input_text)
    assert calculate_amount(record) == Decimal(amount)


def test_hourly_rate_other_than_15_requires_review():
    result = parse_messages('2026年10月12日 张三 计2.5*12快递', directory(), '一群')
    assert not result.records
    assert result.warnings and '时薪' in result.warnings[0]


def test_duplicate_hourly_note_is_not_added_twice():
    result = parse_messages('2026年10月12日 张三 计时3（贴标套袋打包）\n计时3（贴标套袋打包）', directory(), '一群')
    assert len(result.records) == 1
    assert result.warnings and '重复' in result.warnings[0]


def test_piece_and_hourly_note_on_same_line_are_both_kept():
    result = parse_messages('2026年10月12日 张三 8352~~270*0.6 计时3（贴标套袋打包）', directory(), '一群')
    assert not result.warnings and len(result.records) == 2
    assert [calculate_amount(record) for record in result.records] == [Decimal('162.00'), Decimal('45.00')]
    assert result.records[1].note == '贴标套袋打包'


@pytest.mark.parametrize("value", ["计时3小时30", "计时3小时75分", "计时3小时半多", "计时3.5小时30分", "计时3小时半小时"])
def test_uncertain_time_requires_review(value):
    result = parse_messages(f"2026-10-18 张三 {value}", directory(), "一群")
    assert not result.records
    assert result.warnings


def test_multiline_names_date_piece_and_hourly():
    text = """一群
2026年10月18日
阿三
货号
8513-6
数量
10
单价
2.50
李四
计时
3小时半
"""
    result = parse_messages(text, directory(), "一群")
    assert not result.warnings
    assert len(result.records) == 2
    assert result.records[0].employee_id == "1"
    assert result.records[0].item_code == "8513-6"
    assert calculate_amount(result.records[0]) == Decimal("25.00")
    assert result.records[1].employee_id == "2"
    assert result.records[1].kind == WorkKind.HOURLY
    assert calculate_amount(result.records[1]) == Decimal("52.50")


@pytest.mark.parametrize("code", ["8513-6", "8513-7", "8510-1"])
def test_complete_hyphenated_item_codes(code):
    result = parse_messages(f"2026-10-18 张三 货号 {code} 数量 2 单价 1.25", directory(), "一群")
    assert not result.warnings
    assert result.records[0].item_code == code
    assert result.records[0].quantity == Decimal("2")
    assert calculate_amount(result.records[0]) == Decimal("2.50")


def test_duplicate_in_same_screenshot_requires_review():
    line = "2026-10-18 张三 货号 8513-6 数量 2 单价 1.25"
    result = parse_messages(f"{line}\n{line}", directory(), "一群")
    assert len(result.records) == 1
    assert len(result.warnings) == 1
    assert "重复" in result.warnings[0]
