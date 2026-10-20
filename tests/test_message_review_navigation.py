"""真实 Qt 鼠标操作回归；所有名册、绑定与审核资料仅使用临时合成数据。"""
import json
import os
import sqlite3
from decimal import Decimal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog

from wechat_work_recorder.app import MainWindow
from wechat_work_recorder.models import Employee
from wechat_work_recorder.review_dialog import ReviewDialog
from wechat_work_recorder.roster import save_private_roster
from wechat_work_recorder.settings import save_settings


@pytest.fixture
def ui(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    people = [Employee(f'T{i:02}', f'测试员工{i:02}') for i in range(1, 18)]
    save_private_roster(people)
    save_settings([p.name for p in people], ['测试群', '另一个群'])
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.bindings.bind('测试群', '测试昵称', 'T01')
    notices = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: notices.append(a[-1]))
    monkeypatch.setattr(QInputDialog, 'getItem', lambda *a: ('', False))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    window.show()
    app.processEvents()
    yield app, window, notices
    window.close()


def load(ui, body):
    app, window, _ = ui
    source = '测试昵称\n2026年10月18日 19:40\n' + body
    app.clipboard().setText(source)
    window.import_clipboard_text()
    app.processEvents()
    return source


def click_and_review(ui, click, check):
    """Exercise the real modal event loop without hiding exceptions in callbacks."""
    app, _, _ = ui
    seen, errors = [], []

    def complete():
        dialog = app.activeModalWidget()
        seen.append(dialog)
        try:
            assert isinstance(dialog, ReviewDialog), '按钮必须打开统一审核窗口'
            check(dialog)
        except BaseException as error:
            errors.append(error)
        finally:
            if isinstance(dialog, ReviewDialog):
                dialog.reject()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(complete)
    timer.start(20)
    click()
    timer.stop()
    assert seen, '点击后没有进入审核窗口'
    if errors:
        raise errors[0]


@pytest.mark.parametrize('hours,line', [('3', '计时 3×15'), ('3.5', '3.5×15')])
def test_real_review_button_opens_duplicate_hourly_and_can_keep(ui, hours, line):
    app, window, _ = ui
    source = load(ui, f'计时{hours}\n{line}')
    assert len(window.unresolved_warnings) == 1
    window.review_list.setCurrentRow(0)

    def check(dialog):
        assert dialog.kind.currentText() == '计时'
        assert dialog.hours.text() == hours
        assert dialog.work_date.text() == '2026/10/18'
        assert dialog.message_context.toPlainText() == source
        assert dialog.price_options.count() == 1  # no price-history lookup for hourly
        dialog.duplicate_action.setCurrentIndex(dialog.duplicate_action.findData('keep'))
        QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
        assert dialog.result() == ReviewDialog.DialogCode.Accepted

    click_and_review(ui, lambda: QTest.mouseClick(window.review_button, Qt.MouseButton.LeftButton), check)
    assert window.table.rowCount() == 2 and not window.unresolved_warnings
    assert window.total_label.text() == f'总计：{Decimal(hours) * 30:.2f}元'
    assert window.table.item(1, 5).text() == '15.00'
    assert window.reviewed_records()[1].duplicate_confirmed
    window.parse_text()
    assert window.table.rowCount() == 2  # reparse does not add a third row
    assert window.output.toPlainText() == source


@pytest.mark.parametrize('action', ['ignore', 'merge', 'cancel'])
@pytest.mark.parametrize('body,amount', [('计时3\n计时3', '45.00'), ('8393--6*4\n8393--6*4', '24.00')])
def test_duplicate_decisions_keep_existing_wage_and_can_defer(ui, action, body, amount):
    app, window, _ = ui
    source = load(ui, body)
    window.review_list.setCurrentRow(0)

    def check(dialog):
        if action == 'cancel':
            dialog.reject()
        else:
            dialog.duplicate_action.setCurrentIndex(dialog.duplicate_action.findData(action))
            dialog.confirm_button.click()
            assert dialog.result() == ReviewDialog.DialogCode.Accepted

    click_and_review(ui, lambda: QTest.mouseClick(window.review_button, Qt.MouseButton.LeftButton), check)
    assert window.total_label.text() == f'总计：{amount}元'
    assert window.table.rowCount() == 1
    assert bool(window.unresolved_warnings) == (action == 'cancel')
    window.parse_text()
    assert bool(window.unresolved_warnings) == (action == 'cancel')
    assert window.output.toPlainText() == source
    if action != 'cancel':
        with sqlite3.connect(window.import_history.path) as connection:
            audit = connection.execute('SELECT record_json FROM output_audit').fetchone()[0]
            assert connection.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
        assert json.loads(audit)['action'] == action
        assert json.loads(audit)['source_line'] == 4
        assert '已核对' in window.message_list.item(0).text()


def test_real_issue_click_locates_and_opens_ordinary_review(ui):
    app, window, _ = ui
    source = load(ui, '8513-65*1.7')
    item = window.review_list.item(0)

    def check(dialog):
        assert window.output.textCursor().blockNumber() == 2
        assert window.output.textCursor().selectedText() == '8513-65*1.7'
        assert len(window.output.extraSelections()) == 2
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.7')
        dialog.confirm_button.click()

    click_and_review(ui, lambda: QTest.mouseClick(window.review_list.viewport(), Qt.MouseButton.LeftButton,
                    pos=window.review_list.visualItemRect(item).center()), check)
    assert window.table.rowCount() == 1 and window.review_list.count() == 0
    assert window.total_label.text() == '总计：110.50元'
    assert window.output.toPlainText() == source


def test_late_long_message_issue_scrolls_to_exact_line_and_highlights_context(ui):
    app, window, _ = ui
    messages = [f'测试昵称\n2026年10月{day}日 19:40\n8393--{day}*4' for day in range(1, 18)]
    messages[7] += '\n' + '\n'.join('普通 说明 text' for _ in range(30)) + '\n8513-65*1.7'
    source = '\n\n'.join(messages)
    window.output.setPlainText(source)
    window.parse_text()
    app.processEvents()
    assert len(window.message_blocks) == 17
    issue_row = next(i for i, entry in enumerate(window.warning_entries) if entry[2] == 8)
    window.output.verticalScrollBar().setValue(0)
    window.review_list.setCurrentRow(issue_row)
    app.processEvents()
    _, line, number = window.warning_entries[issue_row]
    assert number == 8
    assert window.output.textCursor().blockNumber() == line - 1
    assert window.output.textCursor().selectedText() == '8513-65*1.7'
    assert window.output.viewport().rect().intersects(window.output.cursorRect())
    assert window.output.verticalScrollBar().value() > 0
    assert window.message_list.currentItem().data(Qt.ItemDataRole.UserRole) == 8
    selected = window.output.extraSelections()
    assert len(selected) == 2
    assert '测试昵称' in selected[0].cursor.selectedText()
    assert selected[1].cursor.selectedText() == '8513-65*1.7'
    # Clicking the message title brings its beginning into view, not its bottom.
    window.select_message_item(window.message_list.item(7))
    app.processEvents()
    assert window.output.textCursor().blockNumber() == window.message_blocks[7].start_line - 1
    assert window.output.viewport().rect().intersects(window.output.cursorRect())
    assert window.output.toPlainText() == source


def test_separators_and_spacing_do_not_change_original_or_invalidate_review(ui):
    app, window, _ = ui
    source = load(ui, '8393--6*4\n\n测试昵称\n2026年10月19日 20:00\n8352~~270*0.6')
    assert window.output.message_starts == [window.message_blocks[1].start_line]
    line = window.message_blocks[1].start_line
    assert window.output.document().findBlockByNumber(line - 1).blockFormat().topMargin() == 24
    assert window.output.separator_positions(), '可见消息之间需要有实际绘制的分隔线'
    positions = [(b.start_line, b.end_line) for b in window.message_blocks]
    window.refresh_review_display()
    app.processEvents()
    assert window.output.toPlainText() == source
    assert not window.needs_parse
    assert positions == [(b.start_line, b.end_line) for b in window.message_blocks]
    assert window.output.document().blockCount() == len(source.splitlines())
    assert not hasattr(window, 'review_notes'), '不应再显示第二个重复的问题框'


def test_pending_issues_are_grouped_by_message_without_losing_prices(ui):
    _, window, _ = ui
    window.catalog.set_default('8393', Decimal('5'))
    load(ui, '8393--6*4\n8513-65*1.7\n\n测试昵称\n2026年10月19日 20:00\n8513-70*1.7')
    assert [entry[2] for entry in window.warning_entries] == [1, 1, 2]
    assert [entry[1] for entry in window.warning_entries] == [3, 4, 8]
    assert '当前标准价' in window.review_list.item(0).text()
    assert '测试员工01' in window.review_list.item(0).text()
    assert window.review_list.wordWrap()


def test_bare_rate_never_becomes_unconfirmed_hourly_wage(ui):
    _, window, _ = ui
    load(ui, '3.5×15')
    assert window.table.rowCount() == 0
    assert len(window.unresolved_warnings) == 1
    assert '未标明项目或计时' in window.unresolved_warnings[0]


def test_changed_source_invalidates_decisions_and_blocks_stale_review(ui):
    app, window, notices = ui
    load(ui, '计时3\n计时3')
    window.review_list.setCurrentRow(0)
    def ignore(dialog):
        dialog.duplicate_action.setCurrentIndex(dialog.duplicate_action.findData('ignore'))
        dialog.confirm()
    click_and_review(ui, lambda: window.review_button.click(), ignore)
    assert window.duplicate_resolutions
    window.output.appendPlainText('计时2')
    window.review_button.click()
    assert not window.duplicate_resolutions and window.needs_parse
    assert '原文或设置已经改变' in notices[-1]
    window.parse_text()
    assert window.unresolved_warnings  # previous ignore cannot silence new source


def test_review_startup_error_is_visible_not_silently_swallowed(ui, monkeypatch):
    _, window, notices = ui
    load(ui, '计时3\n计时3')
    monkeypatch.setattr('wechat_work_recorder.app.ReviewDialog', lambda *a, **kw: (_ for _ in ()).throw(OSError('测试错误')))
    window.review_button.click()
    assert '原因：测试错误' in notices[-1]
    assert len(window.unresolved_warnings) == 1 and window.table.rowCount() == 1


def test_audit_failure_does_not_ignore_pending_item(ui, monkeypatch):
    _, window, notices = ui
    load(ui, '计时3\n计时3')
    window.review_list.setCurrentRow(0)
    monkeypatch.setattr(window.import_history, 'audit_review', lambda *a: (_ for _ in ()).throw(OSError('磁盘只读')))
    def ignore(dialog):
        dialog.duplicate_action.setCurrentIndex(dialog.duplicate_action.findData('ignore'))
        dialog.confirm()
        assert dialog.result() != ReviewDialog.DialogCode.Accepted
    click_and_review(ui, lambda: window.review_button.click(), ignore)
    assert len(window.unresolved_warnings) == 1 and not window.duplicate_resolutions
    assert '磁盘只读' in notices[-1]


def test_old_private_data_and_history_survive_review_and_restart(ui):
    _, window, _ = ui
    window.catalog.update_item('打包', Decimal('.2'), aliases=['包装'])
    load(ui, '计时3')
    window.import_history.remember(window.reviewed_records())
    protected = [window.catalog.path, window.catalog.path.with_name('employees.private.json'),
                 window.catalog.path.with_name('bindings.sqlite3'), window.catalog.path.with_name('settings.json')]
    before = {path: path.read_bytes() for path in protected if path.exists()}
    source = load(ui, '计时3\n计时3')
    window.review_list.setCurrentRow(0)
    def ignore(dialog):
        dialog.duplicate_action.setCurrentIndex(dialog.duplicate_action.findData('ignore'))
        dialog.confirm()
    click_and_review(ui, lambda: window.review_button.click(), ignore)
    window.close()
    second = MainWindow()
    try:
        assert second.bindings.resolve('测试群', '测试昵称') == 'T01'
        assert len(second.roster) == 17
        assert second.catalog.default_price('包装') == Decimal('.2')
        for path, content in before.items():
            assert path.read_bytes() == content
        second.output.setPlainText(source)
        second.parse_text()
        assert second.unresolved_warnings, '重启重新导入仍需复核，不能用以前的忽略决定静默略过'
        with sqlite3.connect(second.import_history.path) as connection:
            assert connection.execute('SELECT count(*) FROM imports').fetchone()[0] == 1
    finally:
        second.close()


def test_unbound_sender_header_issue_opens_work_review_without_guessing(ui):
    _, window, _ = ui
    window.bindings.unbind('测试群', '测试昵称')
    load(ui, '8393--6*4')
    assert '员工未绑定' in window.review_list.item(0).text()
    window.review_list.setCurrentRow(0)
    def select_employee(dialog):
        assert dialog.employee_choice.currentData() is None
        assert dialog.quantity.text() == '6'
        dialog.employee_choice.setCurrentIndex(2)
        dialog.confirm()
    click_and_review(ui, lambda: window.review_button.click(), select_employee)
    assert window.bindings.resolve('测试群', '测试昵称') == 'T02'
    assert window.table.item(0, 1).text() == 'T02'
    assert window.total_label.text() == '总计：24.00元'
    assert not window.unresolved_warnings


def test_unresolved_hourly_opens_and_keeps_body_date_priority(ui):
    _, window, _ = ui
    load(ui, '10.17\n计时3小时90分')
    window.review_list.setCurrentRow(0)
    def correct(dialog):
        assert dialog.work_date.text() == '2026/10/17'
        dialog.kind.setCurrentText('计时')
        dialog.hours.setText('3.5')
        dialog.note.setText('测试备注')
        dialog.confirm()
    click_and_review(ui, lambda: window.review_button.click(), correct)
    assert window.table.item(0, 0).text() == '2026/10/17'
    assert window.total_label.text() == '总计：52.50元'
    assert window.reviewed_records()[0].note == '测试备注'


def test_bare_unknown_line_cannot_inherit_previous_piece_project(ui):
    _, window, _ = ui
    load(ui, '8393--6*4\n3.5×15\n2件*4')
    assert window.table.rowCount() == 1
    assert len(window.unresolved_warnings) == 2
    assert any('项目继承不确定' in w for w in window.unresolved_warnings)


def test_confirm_callback_exception_stays_visible_and_pending(ui):
    _, window, notices = ui
    load(ui, '8513-65*1.7')
    window.review_list.setCurrentRow(0)
    def fail(dialog):
        dialog.code.setCurrentText('8513')
        dialog.quantity.setText('65')
        dialog.price.setText('1.7')
        dialog.on_confirm = lambda *a: (_ for _ in ()).throw(OSError('测试写入失败'))
        dialog.confirm_button.click()
        assert dialog.result() != ReviewDialog.DialogCode.Accepted
    click_and_review(ui, lambda: window.review_button.click(), fail)
    assert '测试写入失败' in notices[-1]
    assert window.table.rowCount() == 0 and window.unresolved_warnings
