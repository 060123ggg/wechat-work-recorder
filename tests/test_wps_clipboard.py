from datetime import date
from decimal import Decimal
import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from wechat_work_recorder import app as app_module
from wechat_work_recorder.models import Employee
from wechat_work_recorder.models import WorkKind, WorkRecord
from wechat_work_recorder.wps_clipboard import to_wps_tsv

def test_wps_columns_piece_and_hour():
    records = [
        WorkRecord("E01", date(2026,10,9), WorkKind.PIECE, "一群", "", "8513-7", Decimal("70"), Decimal("1.7")),
        WorkRecord("E01", date(2026,10,9), WorkKind.HOURLY, "一群", "", hours=Decimal("3.5")),
    ]
    payload = to_wps_tsv(records, {"E01":"测试员工"})
    assert payload.count('\r\n') == 1
    lines = payload.splitlines()
    assert lines[0].split("\t") == ["2026/10/09","E01","测试员工","","8513-7","","70","1.7","119.00"]
    assert lines[1].split("\t") == ["2026/10/09","E01","测试员工","","计时","","3.5","15","52.50"]

def test_unknown_employee_blocked():
    r = WorkRecord("missing",date(2026,10,9),WorkKind.HOURLY,"一群","",hours=Decimal("2"))
    with pytest.raises(ValueError):
        to_wps_tsv([r], {})


def test_formula_like_item_is_not_copied():
    record = WorkRecord('E01', date(2026, 10, 9), WorkKind.PIECE, '一群', '',
                        '=HYPERLINK("unsafe")', Decimal('1'), Decimal('2'))
    with pytest.raises(ValueError, match='公式符号'):
        to_wps_tsv([record], {'E01': '测试员工'})


def test_hourly_rate_conflict_is_blocked():
    record = WorkRecord('E01', date(2026, 10, 9), WorkKind.HOURLY, '一群', '',
                        unit_price=Decimal('20'), hours=Decimal('2'))
    with pytest.raises(ValueError, match='15元'):
        to_wps_tsv([record], {'E01': '测试员工'})


def setup_window(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr(app_module, 'load_builtin_roster',
                        lambda: [Employee(f'E{i:02d}', f'员工{i:02d}') for i in range(1, 18)])
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ['一群']
    window.group_combo.addItem('一群')
    window.bindings.bind('一群', '测试昵称', 'E01')
    return app, window


def test_copy_from_ui_mixed_records_and_block_repeat(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('2026/10/9\n测试昵称\n8513-7 70*1.7\n计时3.5')
    window.import_clipboard_text()
    assert window.table.rowCount() == 2
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: (prompts.append(args[-1]) or QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    blocked = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: blocked.append(args[-1]))
    window.copy_to_wps()
    cells = [line.split('\t') for line in app.clipboard().text().splitlines()]
    assert cells == [
        ['2026/10/09', 'E01', '员工01', '', '8513-7', '', '70', '1.7', '119.00'],
        ['2026/10/09', 'E01', '员工01', '', '计时', '', '3.5', '15', '52.50'],
    ]
    assert 'J 列的工资公式' in prompts[0]
    window.copy_to_wps()
    assert blocked and '已复制' in blocked[-1]
    assert len(prompts) == 1
    window.close()


def test_copy_blocks_unresolved_and_stale_text(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('2026/10/9\n测试昵称\n8513-7 70*1.7\n8513-65*1.7')
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    window.import_clipboard_text()
    assert window.unresolved_warnings
    app.clipboard().setText('sentinel')
    window.copy_to_wps()
    assert app.clipboard().text() == 'sentinel'
    window.output.setPlainText('changed')
    window.copy_to_wps()
    assert app.clipboard().text() == 'sentinel'
    window.close()


def test_copy_blocks_unconfirmed_nickname(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: ('', False))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    app.clipboard().setText('2026/10/9\n未知昵称\n8513-7 70*1.7')
    window.import_clipboard_text()
    assert window.unresolved_warnings
    app.clipboard().setText('sentinel')
    window.copy_to_wps()
    assert app.clipboard().text() == 'sentinel'
    window.close()


def test_copy_cancellation_leaves_clipboard_and_can_retry(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('2026/10/9\n测试昵称\n计时2')
    window.import_clipboard_text()
    app.clipboard().setText('sentinel')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    window.copy_to_wps()
    assert app.clipboard().text() == 'sentinel'
    assert not window.copied_record_keys
    window.close()


def test_copy_blocks_duplicate_table_rows(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('2026/10/9\n测试昵称\n计时2')
    window.import_clipboard_text()
    window.add_record(window.reviewed_records()[0])
    app.clipboard().setText('sentinel')
    blocked = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: blocked.append(args[-1]))
    window.copy_to_wps()
    assert '重复记录' in blocked[-1]
    assert app.clipboard().text() == 'sentinel'
    window.close()
