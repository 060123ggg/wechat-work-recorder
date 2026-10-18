import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from wechat_work_recorder.app import MainWindow
from wechat_work_recorder.models import Employee
from wechat_work_recorder.roster import load_builtin_roster, roster_path
from wechat_work_recorder.settings import save_settings


def roster():
    return [Employee(f'AM-{1000+i}', f'测试员工{i:02d}') for i in range(1, 18)]


def test_first_setup_prefills_names_and_bindings_survive_restart(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    save_settings([employee.name for employee in roster()], ['一群'])
    QApplication.instance() or QApplication([])
    first = MainWindow()
    assert not first.roster
    assert '首次使用' in first.guide_label.text()
    from wechat_work_recorder.roster_dialog import RosterDialog
    preview = RosterDialog([], first.employees)
    assert preview.table.item(0, 1).text() == '测试员工01'
    assert preview.table.item(16, 1).text() == '测试员工17'
    preview.close()
    monkeypatch.setattr(RosterDialog, 'exec', lambda self: RosterDialog.DialogCode.Accepted)
    assert first.manage_roster()
    assert roster_path().exists()
    assert len(load_builtin_roster()) == 17
    first.bindings.bind('一群', '测试昵称', 'AM-1001')
    first.close()
    second = MainWindow()
    assert second.roster[0].name == '测试员工01'
    assert second.bindings.resolve('一群', '测试昵称') == 'AM-1001'
    second.close()


def test_binding_button_opens_first_setup_with_existing_names(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    save_settings([employee.name for employee in roster()], ['一群'])
    QApplication.instance() or QApplication([])
    window = MainWindow()
    from wechat_work_recorder.roster_dialog import RosterDialog
    from wechat_work_recorder.binding_dialog import BindingDialog
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(RosterDialog, 'exec', lambda self: RosterDialog.DialogCode.Accepted)
    opened = []
    monkeypatch.setattr(BindingDialog, 'exec', lambda self: opened.append(True))
    window.manage_bindings()
    assert opened and window.roster[0].name == '测试员工01'
    assert roster_path().exists()
    window.close()


@pytest.mark.parametrize('work_line,code,qty,price,amount', [
    ('8393--6*4', '8393', '6', '4', '24.00'),
    ('8352~~270*0.6', '8352', '270', '0.6', '162.00'),
])
def test_wechat_text_to_table_without_quantity_warning(monkeypatch, tmp_path, work_line, code, qty, price, amount):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    save_settings([employee.name for employee in roster()], ['一群'])
    from wechat_work_recorder.roster import save_private_roster
    save_private_roster(roster())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.bindings.bind('一群', '测试昵称', 'AM-1001')
    app.clipboard().setText(f'测试昵称\n2026年10月12日 19:52\n{work_line}')
    window.import_clipboard_text()
    assert window.table.rowCount() == 1
    assert [window.table.item(0, column).text() for column in (1, 4, 5, 6, 8)] == [
        '2026-10-12', code, qty, price, amount]
    assert not window.unresolved_warnings
    assert not window.review_notes.toPlainText()
    assert window.total_label.text() == f'总计：{amount}元'
    assert window.reviewed_records()[0].source_text == window.output.toPlainText()
    window.close()


def test_unknown_nickname_reports_identity_only(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    save_settings([employee.name for employee in roster()], ['一群'])
    from wechat_work_recorder.roster import save_private_roster
    save_private_roster(roster())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: ('', False))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    app.clipboard().setText('测试昵称\n2026年10月12日 19:52\n8393--6*4')
    window.import_clipboard_text()
    assert window.table.rowCount() == 0
    notes = window.review_notes.toPlainText()
    assert '员工未绑定' in notes
    assert '缺少有效工作日期' not in notes
    assert '数量边界待确认' not in notes
    assert '8393--6*4' in notes
    window.close()
