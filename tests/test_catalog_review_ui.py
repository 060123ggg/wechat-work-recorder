import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from wechat_work_recorder import app as app_module
from wechat_work_recorder.models import Employee


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
    selections = iter([0, 1])
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: (args[3][next(selections)], True))
    entries = iter([('70', True), ('1.7', True)])
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: next(entries))
    window.review_ambiguous_line()
    assert not window.unresolved_warnings
    assert window.table.rowCount() == 2
    assert window.total_label.text() == '总计：171.50元'
    window.close()
