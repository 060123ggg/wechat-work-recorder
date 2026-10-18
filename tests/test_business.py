from datetime import date
from decimal import Decimal
import pytest
from wechat_work_recorder.employees import EmployeeDirectory
from wechat_work_recorder.models import Employee, WorkKind, WorkRecord
from wechat_work_recorder.parser import parse_messages
from wechat_work_recorder.payroll import calculate_amount
from wechat_work_recorder.workbook import TemplateMappingRequired, UnconfiguredWorkbookWriter


def directory():
    return EmployeeDirectory([Employee("e1", "张三", ("小张",)), Employee("e2", "李四")], ["g1", "g2", "g3"])


def test_piece_and_hourly_parsing_and_pay():
    result = parse_messages("2026-10-18 张三 货号 AB-123/45 数量 10 单价 2.50\n2026/10/18 小张 计时 3.5小时", directory(), "g1")
    assert not result.warnings
    assert [r.kind for r in result.records] == [WorkKind.PIECE, WorkKind.HOURLY]
    assert result.records[0].item_code == "AB-123/45"
    assert [calculate_amount(r) for r in result.records] == [Decimal("25.00"), Decimal("52.50")]


def test_unclear_lines_need_review():
    result = parse_messages("2026-10-18 王五 计时 3\n2026-10-18 张三 货号 AB 数量 2\n2026-10-18 张三 计时 25", directory(), "g1")
    assert not result.records
    assert len(result.warnings) == 3


def test_unknown_group_and_duplicate_alias():
    with pytest.raises(ValueError):
        parse_messages("2026-10-18 张三 计时 2", directory(), "g4")
    with pytest.raises(ValueError):
        EmployeeDirectory([Employee("1", "张三"), Employee("2", "李四", ("张三",))], ["g1"])


def test_workbook_requires_mapping_and_does_not_touch_files(tmp_path):
    record = WorkRecord("e1", date(2026, 10, 18), WorkKind.HOURLY, "g1", "source", hours=Decimal("2"))
    writer = UnconfiguredWorkbookWriter()
    assert writer.preview([record])[0]["amount"] == "30.00"
    source = tmp_path / "real.xlsx"
    source.write_bytes(b"untouched")
    with pytest.raises(TemplateMappingRequired):
        writer.write_copy(source, tmp_path / "output.xlsx", [record])
    assert source.read_bytes() == b"untouched"
    assert not (tmp_path / "output.xlsx").exists()
