from datetime import date
from decimal import Decimal
from openpyxl import load_workbook
import pytest
from wechat_work_recorder.models import WorkKind, WorkRecord
from wechat_work_recorder.settings import directory_from_settings, load_settings, save_settings
from wechat_work_recorder.parser import parse_messages
from wechat_work_recorder.workbook import write_mock_workbook


def test_settings_parse_and_confirmed_mock_workbook(tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(["张三", "李四"], ["一群", "二群", "三群"], settings)
    employees, groups = load_settings(settings)
    result = parse_messages("2026-10-18 张三 货号 WX-123/ABC 数量 4 单价 1.50", directory_from_settings(employees, groups), "一群")
    assert not result.warnings
    path = tmp_path / "mock.xlsx"
    with pytest.raises(PermissionError):
        write_mock_workbook(path, result.records)
    write_mock_workbook(path, result.records, confirmed=True)
    ws = load_workbook(path, read_only=True).active
    assert ws["E2"].value == "WX-123/ABC"
    assert ws["I2"].value == "6.00"
    with pytest.raises(FileExistsError):
        write_mock_workbook(path, result.records, confirmed=True)


def test_settings_limits(tmp_path):
    with pytest.raises(ValueError):
        save_settings([str(i) for i in range(18)], ["一群"], tmp_path / "settings.json")
