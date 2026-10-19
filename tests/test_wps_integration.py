import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from wechat_work_recorder.app import MainWindow, HEADERS
from wechat_work_recorder.models import Employee, WorkKind, WorkRecord
from wechat_work_recorder.roster import save_private_roster
from wechat_work_recorder.settings import save_settings
from wechat_work_recorder.wps_clipboard import to_wps_segments


def setup_window(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    roster = [Employee(f'E{i:02d}', f'员工{i:02d}') for i in range(1, 18)]
    save_private_roster(roster)
    save_settings([employee.name for employee in roster], ['测试群'])
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.bindings.bind('测试群', '测试昵称', 'E01')
    return app, window


def quiet_dialogs(monkeypatch):
    questions = []
    messages = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: (questions.append(args[-1]) or QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    return questions, messages


def test_segment_map_never_contains_gap_or_formula_columns():
    records = [
        WorkRecord('E01', date(2026, 10, 9), WorkKind.PIECE, '测试群', '',
                   '8513-7', Decimal('70'), Decimal('1.7')),
        WorkRecord('E01', date(2026, 10, 9), WorkKind.HOURLY, '测试群', '',
                   hours=Decimal('3.5')),
    ]
    parts = to_wps_segments(records, {'E01': '员工01'})
    assert set(parts) == {'B:D', 'F', 'H:I'}
    assert parts['B:D'].splitlines() == [
        '2026/10/09\tE01\t员工01', '2026/10/09\tE01\t员工01']
    assert parts['F'].splitlines() == ['8513-7', '计时']
    assert parts['H:I'].splitlines() == ['70\t1.7', '3.5\t15']
    assert not any('119.00' in part or '52.50' in part for part in parts.values())


def test_full_ui_retained_and_mixed_records_copy(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    assert window.review_button.text() == '核对疑似记工行'
    assert window.roster_button.text() == '管理正式员工名册'
    assert HEADERS == ['日期', '员工编号', '姓名', '货号/项目', '数量/工时', '单价', '单项工资', '当日合计工资']
    app.clipboard().setText('测试昵称\n2026/10/9\n8513-7 70*1.7\n计时3.5')
    window.import_clipboard_text()
    assert window.table.rowCount() == 2 and not window.unresolved_warnings
    assert window.total_label.text() == '总计：171.50元'
    assert window.message_list.count() == 1
    questions, messages = quiet_dialogs(monkeypatch)
    window.copy_to_wps()
    assert app.clipboard().text().splitlines() == ['2026/10/09\tE01\t员工01'] * 2
    assert 'F 列目标单元格设为“文本”' in questions[0]
    window.copy_wps_f()
    assert app.clipboard().text().splitlines() == ['8513-7', '计时']
    window.copy_wps_hi()
    assert app.clipboard().text().splitlines() == ['70\t1.7', '3.5\t15']
    assert len(window.copied_record_keys) == 2 and not messages
    window.close()


def test_unresolved_record_cannot_copy(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    _, messages = quiet_dialogs(monkeypatch)
    app.clipboard().setText('测试昵称\n2026/10/9\n8513-65*1.7')
    window.import_clipboard_text()
    assert window.unresolved_warnings
    app.clipboard().setText('sentinel')
    window.copy_to_wps()
    assert app.clipboard().text() == 'sentinel'
    assert messages and '待核对' in messages[-1]
    window.close()


def test_recopy_requires_explicit_confirmation(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称\n2026/10/9\n计时2')
    window.import_clipboard_text()
    quiet_dialogs(monkeypatch)
    window.copy_to_wps()
    window.copy_wps_f()
    window.copy_wps_hi()
    app.clipboard().setText('sentinel')
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: (prompts.append(args[1]) or QMessageBox.StandardButton.No))
    window.copy_to_wps()
    assert prompts == ['确认重新复制']
    assert app.clipboard().text() == 'sentinel'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: (prompts.append(args[1]) or QMessageBox.StandardButton.Yes))
    window.copy_to_wps()
    assert prompts[-2:] == ['确认重新复制', '确认复制到 WPS']
    assert app.clipboard().text() == '2026/10/09\tE01\t员工01'
    window.close()


def test_named_packing_project_survives_integration(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    window.catalog.add_code('打包')
    app.clipboard().setText('测试昵称\n2026/10/9\n打包- 45*0.2\n计时2')
    window.import_clipboard_text()
    assert not window.unresolved_warnings
    assert window.total_label.text() == '总计：39.00元'
    quiet_dialogs(monkeypatch)
    window.copy_to_wps()
    window.copy_wps_f()
    assert app.clipboard().text().splitlines() == ['打包', '计时']
    window.copy_wps_hi()
    assert app.clipboard().text().splitlines() == ['45\t0.2', '2\t15']
    window.close()


def test_changed_record_aborts_remaining_copy(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称\n2026/10/9\n8513-7 70*1.7')
    window.import_clipboard_text()
    _, messages = quiet_dialogs(monkeypatch)
    window.copy_to_wps()
    first = app.clipboard().text()
    window.table.item(0, 4).setText('71')
    window.copy_wps_f()
    assert app.clipboard().text() == first
    assert messages and '已改变' in messages[-1]
    window.close()


def test_copy_blocks_duplicate_rows_and_prompts_on_price_difference(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称\n2026/10/9\n8513-6 50*2')
    window.import_clipboard_text()
    assert not window.unresolved_warnings and window.price_warnings
    questions, messages = quiet_dialogs(monkeypatch)
    window.copy_to_wps()
    assert questions and '单价差异' in questions[0]
    assert window.wps_copy_batch is not None
    window.add_record(window.reviewed_records()[0])
    app.clipboard().setText('sentinel')
    window.copy_to_wps()
    assert messages and '重复记录' in messages[-1]
    assert app.clipboard().text() == 'sentinel'
    window.close()


def test_formula_like_item_and_wrong_hourly_rate_are_blocked():
    piece = WorkRecord('E01', date(2026, 10, 9), WorkKind.PIECE, '测试群', '',
                       '=SUM(1,2)', Decimal('1'), Decimal('1'))
    hour = WorkRecord('E01', date(2026, 10, 9), WorkKind.HOURLY, '测试群', '',
                      unit_price=Decimal('20'), hours=Decimal('2'))
    with pytest.raises(ValueError, match='公式符号'):
        to_wps_segments([piece], {'E01': '员工01'})
    with pytest.raises(ValueError, match='15元'):
        to_wps_segments([hour], {'E01': '员工01'})
