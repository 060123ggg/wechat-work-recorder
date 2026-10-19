import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from wechat_work_recorder import app as app_module
from wechat_work_recorder.models import Employee
from wechat_work_recorder.review_dialog import ReviewDialog


def window_with_binding(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr(app_module, 'load_builtin_roster',
                        lambda: [Employee(f'E{i:02d}', f'员工{i:02d}') for i in range(1, 18)])
    QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ['一群']
    window.group_combo.addItem('一群')
    window.bindings.bind('一群', '测试昵称', 'E03')
    return window


def test_ambiguous_line_is_visible_and_blocks_save(monkeypatch, tmp_path):
    window = window_with_binding(monkeypatch, tmp_path)
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    window.output.setPlainText('2026/10/9\n测试昵称\n8513-70*1.7\n计时3.5')
    window.parse_text()
    window.review_list.setCurrentRow(0)
    assert window.table.rowCount() == 1
    assert '8513-70*1.7' in window.review_notes.toPlainText()
    assert '单价候选：1.7' in window.review_notes.toPlainText()
    window.save_mock()
    assert any('仍有未解析行' in msg for msg in messages)
    window.close()


def test_review_choice_reparses_and_recalculates(monkeypatch, tmp_path):
    window = window_with_binding(monkeypatch, tmp_path)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    window.output.setPlainText('2026/10/9\n测试昵称\n8513-70*1.7\n计时3.5')
    window.parse_text()
    window.review_list.setCurrentRow(0)
    def review(dialog):
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('70')
        dialog.price.setText('1.7')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert not window.unresolved_warnings
    assert window.table.rowCount() == 2
    assert window.total_label.text() == '总计：171.50元'
    window.close()


def test_catalog_ui_accepts_named_project_and_imports_work(monkeypatch, tmp_path):
    window = window_with_binding(monkeypatch, tmp_path)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: (args[3][0], True))
    answers = iter([('打包', True), ('', True)])
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: next(answers))
    window.manage_catalog()
    assert '打包' in window.catalog.codes
    assert window.catalog.default_price('打包') is None
    window.output.setPlainText('测试昵称\n2026/10/9\n打包-45*0.2\n计时2')
    window.parse_text()
    assert not window.unresolved_warnings
    assert [record.item_code for record in window.reviewed_records()] == ['打包', None]
    assert window.total_label.text() == '总计：39.00元'
    window.close()
