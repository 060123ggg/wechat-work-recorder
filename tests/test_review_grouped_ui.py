import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal
from openpyxl import load_workbook
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox
from wechat_work_recorder.app import MainWindow, HEADERS
from wechat_work_recorder.review_dialog import ReviewDialog
from wechat_work_recorder.models import Employee
from wechat_work_recorder.roster import save_private_roster
from wechat_work_recorder.settings import save_settings
from wechat_work_recorder.workbook import write_mock_workbook


def setup_window(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    roster = [Employee(f'E{i:02d}', f'员工{i:02d}') for i in range(1, 18)]
    save_private_roster(roster)
    save_settings([employee.name for employee in roster], ['一群'])
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.bindings.bind('一群', '测试昵称甲', 'E01')
    window.bindings.bind('一群', '测试昵称乙', 'E02')
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: None)
    return app, window


def test_review_adds_record_without_rewriting_original(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    source = '测试昵称甲\n2026年10月12日 19:52\n8513-65*1.7\n计时3（贴标）'
    app.clipboard().setText(source)
    window.import_clipboard_text()
    assert window.table.rowCount() == 1
    assert len(window.unresolved_warnings) == 1
    assert '待核对' in window.message_list.item(0).text()
    assert '第1条消息｜原文第3行' in window.review_list.item(0).text()
    window.review_list.setCurrentRow(0)
    window.select_review_item(window.review_list.item(0))
    assert '8513-65*1.7' in window.output.textCursor().selectedText()
    def review(dialog):
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.70')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert window.output.toPlainText() == source
    assert window.table.rowCount() == 2
    assert not window.unresolved_warnings
    assert window.review_list.count() == 0
    assert '已核对' in window.message_list.item(0).text()
    assert window.statusBar().currentMessage() == '识别 2 条；需人工核对 0 项'
    assert window.total_label.text() == '总计：155.50元'
    records = window.reviewed_records()
    piece = next(record for record in records if record.item_code == '8513')
    assert (piece.quantity, piece.unit_price, piece.source_line, piece.message_number) == (
        Decimal('65'), Decimal('1.70'), 3, 1)
    assert window.table.rowSpan(0, 7) == 2
    assert window.table.item(0, 7).text() == '155.50'
    window.close()


def test_review_single_dialog_updates_amount_and_record(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513-65*1.7')
    window.import_clipboard_text()
    window.review_list.setCurrentRow(0)
    def complete_dialog():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, ReviewDialog)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert any('8513-65*1.7' in label for label in labels)
        assert not any('历史参考' in label for label in labels)
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.7')
        assert dialog.amount.text() == '本项工资：¥110.50'
        dialog.confirm_button.click()

    QTimer.singleShot(0, complete_dialog)
    window.review_ambiguous_line()
    assert window.table.rowCount() == 1
    assert window.total_label.text() == '总计：110.50元'
    assert not window.unresolved_warnings
    window.close()


def test_message_numbers_binding_status_and_grouped_wages(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    source = ('测试昵称甲\n2026/10/12\n8393--6*4\n计时3（贴标）\n'
              '测试昵称乙\n2026/10/12\n8352~~270*0.6\n'
              '测试昵称甲\n2026/10/13\n计时2')
    app.clipboard().setText(source)
    window.import_clipboard_text()
    assert window.output.toPlainText() == source
    assert window.message_list.count() == 3
    assert window.message_list.item(0).text() == '第1条｜测试昵称甲（员工01）｜已核对'
    assert window.message_list.item(1).text() == '第2条｜测试昵称乙（员工02）｜已核对'
    assert [record.message_number for record in window.reviewed_records()] == [1, 1, 2, 3]
    assert HEADERS == ['日期', '员工编号', '姓名', '货号/项目', '数量/工时', '单价', '单项工资', '当日合计工资']
    assert [window.table.item(0, col).text() for col in range(7)] == [
        '2026/10/12', 'E01', '员工01', '8393', '6', '4', '24.00']
    assert [window.table.item(1, col).text() for col in (3, 4, 5, 6)] == ['计时', '3', '15.00', '45.00']
    assert window.table.rowSpan(0, 7) == 2
    assert window.table.item(0, 7).text() == '69.00'
    assert window.table.item(0, 7).textAlignment() == Qt.AlignmentFlag.AlignCenter
    assert window.table.item(2, 7).text() == '162.00'
    assert window.total_label.text() == '总计：261.00元'
    book_path = tmp_path / 'grouped.xlsx'
    write_mock_workbook(book_path, window.reviewed_records(), confirmed=True,
                        employee_names={employee.employee_id: employee.name for employee in window.roster})
    book = load_workbook(book_path, read_only=False)
    try:
        sheet = book['模拟记工']
        assert list(sheet.values)[0] == tuple(HEADERS)
        assert sheet['H2'].value == 69
        assert str(sheet.merged_cells) == 'H2:H3'
        assert sheet['H2'].alignment.horizontal == 'center' and sheet['H2'].alignment.vertical == 'center'
        assert sheet['D3'].value == '计时' and sheet['F3'].value == 15
        assert book['审核追溯']['A3'].value == 1
        assert book['审核追溯']['D3'].value == '贴标'
    finally:
        book.close()
    window.close()


def test_unbound_message_stays_separate_from_code_review(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *args: ('', False))
    app.clipboard().setText('未知昵称\n2026/10/12\n8393--6*4')
    window.import_clipboard_text()
    assert window.message_list.count() == 1
    assert '未绑定员工' in window.message_list.item(0).text()
    assert '待核对' in window.message_list.item(0).text()
    assert window.table.rowCount() == 0
    assert all('数量边界' not in entry for entry in window.unresolved_warnings)
    window.close()


def test_review_one_of_multiple_pending_lines_only_clears_that_line(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    source = '测试昵称甲\n2026/10/12\n8513-65*1.7\n8513-70*1.7\n计时2'
    app.clipboard().setText(source)
    window.import_clipboard_text()
    assert window.table.rowCount() == 1 and len(window.unresolved_warnings) == 2
    window.review_list.setCurrentRow(0)
    def review(dialog):
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.70')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert window.table.rowCount() == 2
    assert len(window.unresolved_warnings) == 1
    assert '8513-70*1.7' in window.unresolved_warnings[0]
    assert window.total_label.text() == '总计：140.50元'
    assert window.statusBar().currentMessage() == '识别 2 条；需人工核对 1 项'
    assert '待核对' in window.message_list.item(0).text()
    window.close()


def test_editing_piece_quantity_recalculates_item_and_group_total(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8393--6*4\n计时3')
    window.import_clipboard_text()
    window.table.item(0, 4).setText('7')
    assert window.table.item(0, 6).text() == '28.00'
    assert window.table.item(0, 7).text() == '73.00'
    assert window.total_label.text() == '总计：73.00元'
    assert window.reviewed_records()[0].quantity == Decimal('7')
    window.close()


def test_review_rejects_duplicate_and_explains_failure(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513 65*1.7\n8513-65*1.7')
    window.import_clipboard_text()
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))
    window.review_list.setCurrentRow(0)
    def review(dialog):
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.70')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert window.table.rowCount() == 1
    assert window.unresolved_warnings and not window.review_overrides
    assert messages and '重复' in messages[-1]
    window.close()


def test_review_dialog_hourly_mode_and_note(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513-65*1.7')
    window.import_clipboard_text()
    window.review_list.setCurrentRow(0)

    def review(dialog):
        dialog.kind.setCurrentText('计时')
        dialog.hours.setText('3.5')
        dialog.note.setText('贴标套袋')
        assert dialog.amount.text() == '本项工资：¥52.50'
        dialog.confirm()

    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert window.total_label.text() == '总计：52.50元'
    assert window.reviewed_records()[0].note == '贴标套袋'
    assert not window.unresolved_warnings
    window.close()


def test_review_cancel_keeps_pending_record(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513-65*1.7')
    window.import_clipboard_text()
    window.review_list.setCurrentRow(0)
    monkeypatch.setattr(ReviewDialog, 'exec', lambda dialog: dialog.reject())
    window.review_ambiguous_line()
    assert window.table.rowCount() == 0
    assert len(window.unresolved_warnings) == 1
    assert not window.review_overrides
    window.close()


def test_review_dialog_uses_only_confirmed_default_price(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513-6 50')
    window.import_clipboard_text()
    dialog = ReviewDialog('8513-6 50', 1, '员工01', '2026/10/12',
                          ['8513-6'], lambda _: None,
                          confirmed_defaults={'8513-6': Decimal('1.70')})
    assert dialog.code.currentText() == '8513-6'
    assert dialog.price.text() == '1.70'
    assert not any('历史参考' in label.text() for label in dialog.findChildren(QLabel))
    dialog.close()
    window.close()


def test_review_rejects_unbound_employee(monkeypatch, tmp_path):
    app, window = setup_window(monkeypatch, tmp_path)
    app.clipboard().setText('测试昵称甲\n2026/10/12\n8513-65*1.7')
    window.import_clipboard_text()
    window.bindings.unbind('一群', '测试昵称甲')
    window.review_list.setCurrentRow(0)
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: messages.append(args[-1]))

    def review(dialog):
        dialog.code.setCurrentText('8513')
        dialog.confirm()

    monkeypatch.setattr(ReviewDialog, 'exec', review)
    window.review_ambiguous_line()
    assert window.table.rowCount() == 0
    assert not window.review_overrides
    assert any('员工未绑定' in message for message in messages)
    window.close()
