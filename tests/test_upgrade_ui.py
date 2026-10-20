import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from decimal import Decimal as D
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
import pytest
from wechat_work_recorder.app import MainWindow
from wechat_work_recorder.models import Employee
from wechat_work_recorder.roster import save_private_roster
from wechat_work_recorder.settings import save_settings
from wechat_work_recorder.catalog import ItemCatalog
from wechat_work_recorder.catalog_dialog import ProjectDialog, CatalogDialog
from wechat_work_recorder.review_dialog import ReviewDialog


@pytest.fixture
def ui(monkeypatch,tmp_path):
    monkeypatch.setenv('APPDATA',str(tmp_path))
    people=[Employee(f'E{i:02}',f'员工{i:02}') for i in range(1,18)]
    save_private_roster(people)
    save_settings([p.name for p in people],['测试群'])
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    window.bindings.bind('测试群','测试昵称','E01')
    questions=[]
    notices=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:notices.append(a[-1]))
    monkeypatch.setattr(QMessageBox,'information',lambda *a:None)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:(questions.append(a[-1]) or QMessageBox.StandardButton.Yes))
    yield app,window,questions,notices
    window.close()


def import_body(ui,body,header='测试昵称\n2026年10月18日 19:40'):
    app,window,_,_=ui
    app.clipboard().setText(header+'\n'+body)
    window.import_clipboard_text()


def test_new_project_popup_prepopulates_then_reaches_payroll(ui,monkeypatch):
    app,window,_,_=ui
    calls=[]
    def save(dialog):
        calls.append((dialog.code.text(),dialog.price.text(),dialog.old_code))
        dialog.save()
        return dialog.result()
    monkeypatch.setattr(ProjectDialog,'exec',save)
    import_body(ui,'猫砂盆20个*10\n计时3')
    assert calls==[('猫砂盆','10','猫砂盆')]
    assert window.total_label.text()=='总计：245.00元'
    assert not window.unresolved_warnings
    assert window.catalog.default_price('猫砂盆')==D('10')
    import_body(ui,'猫砂盆2个')
    assert len(calls)==1 and window.total_label.text()=='总计：20.00元'


def test_unknown_project_cancel_keeps_original_blocks_entire_copy(ui,monkeypatch):
    app,window,_,notices=ui
    monkeypatch.setattr(ProjectDialog,'exec',lambda self:self.reject())
    import_body(ui,'猫砂盆20个*10\n计时3')
    assert window.table.rowCount()==1 and window.unresolved_warnings
    assert '猫砂盆20个*10' in '\n'.join(window.review_list.item(i).text() for i in range(window.review_list.count()))
    app.clipboard().setText('sentinel')
    window.copy_to_wps()
    assert app.clipboard().text()=='sentinel' and '待核对' in notices[-1]


def test_unknown_price_in_new_project_must_be_filled(ui,monkeypatch):
    app,window,_,_=ui
    def fill(dialog):
        assert dialog.price.text()==''
        dialog.price.setText('10')
        dialog.save()
        return dialog.result()
    monkeypatch.setattr(ProjectDialog,'exec',fill)
    import_body(ui,'猫砂盆20个')
    assert not window.unresolved_warnings and window.total_label.text()=='总计：200.00元'


def test_single_special_price_review_clears_only_it_and_retains_standard(ui,monkeypatch):
    app,window,_,_=ui
    window.catalog.update_item('猫食盆',D('10'))
    import_body(ui,'猫食盆2件*10\n1件*5\n计时2')
    assert len(window.price_warnings)==1 and window.table.rowCount()==3
    assert '待核对' in window.message_list.item(0).text()
    window.review_list.setCurrentRow(0)
    def accept(dialog):
        assert dialog.code.currentText()=='猫食盆' and dialog.quantity.text()=='1' and dialog.price.text()=='5'
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',accept)
    window.review_ambiguous_line()
    assert not window.price_warnings and not window.unresolved_warnings
    assert window.review_list.count()==0 and window.total_label.text()=='总计：55.00元'
    assert window.catalog.default_price('猫食盆')==D('10')
    import_body(ui,'猫食盆1件*5')
    assert len(window.price_warnings)==1  # 下一次必须重新核对


def test_standard_change_never_changes_existing_wages(ui):
    _,window,_,_=ui
    window.catalog.update_item('8377',D('.3'))
    import_body(ui,'8377 100个')
    old=window.reviewed_records()[0]
    editor=ProjectDialog(window.catalog,'8377',parent=window)
    editor.price.setText('.2')
    editor.save()
    assert window.total_label.text()=='总计：30.00元'
    assert old.unit_price==D('.3') and old.standard_price_snapshot==D('.3')
    import_body(ui,'8377 200个')
    assert window.total_label.text()=='总计：40.00元'


def test_multivalue_price_choices_are_explicit_and_record_only(ui,monkeypatch,tmp_path):
    _,window,_,_=ui
    p=tmp_path/'price.csv'
    p.write_text('code,price,count,unit,month,source\n8377,.2,2,件,2026-10,测试来源\n8377,.3,5,件,2026-10,测试来源\n', encoding='utf-8')
    window.catalog.import_october_csv(p)
    import_body(ui,'8377 100个\n计时1')
    assert window.table.rowCount()==1 and window.unresolved_warnings
    window.review_list.setCurrentRow(0)
    def choose(dialog):
        assert dialog.price.text()==''
        assert dialog.price_options.count()==3
        dialog.price_options.setCurrentIndex(1)
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',choose)
    window.review_ambiguous_line()
    assert window.table.rowCount()==2 and not window.unresolved_warnings
    assert window.total_label.text()=='总计：35.00元'
    assert window.catalog.default_price('8377') is None


def test_missing_sender_can_be_manually_selected_without_nickname_guess(ui,monkeypatch):
    app,window,_,_=ui
    import_body(ui,'10月17号\n计时3\n8510 2个*0.55',header='2026年10月18日 19:40')
    assert window.table.rowCount()==0
    assert '发送人待确认' in '\n'.join(window.review_list.item(i).text() for i in range(window.review_list.count()))
    window.review_list.setCurrentRow(0)
    def choose(dialog):
        assert dialog.employee_choice.currentData() is None
        assert dialog.work_date.text()=='2026/10/17'
        dialog.employee_choice.setCurrentIndex(2)
        dialog.hours.setText('3')
        dialog.kind.setCurrentText('计时')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',choose)
    window.review_ambiguous_line()
    assert not window.unresolved_warnings
    assert window.table.rowCount()==2
    assert {r.employee_id for r in window.reviewed_records()}=={'E02'}
    assert '人工确认发送人（员工02）' in window.message_list.item(0).text()


def test_real_mixed_case_copy_preserves_columns_and_work_date(ui):
    app,window,questions,_=ui
    window.catalog.update_item('猫食盆',D('10'))
    window.catalog.update_item('打包',D('.2'),unit='捆')
    import_body(ui,'10.16\n8510 144个*0.55\n猫食盆2件*10\n1件*5\n打包20捆*0.2\n计时5*15')
    window.copy_to_wps()
    assert any('猫食盆' in q and '数量1' in q and '5.00' in q for q in questions)
    assert app.clipboard().text().splitlines()==['2026/10/16\tE01\t员工01']*5
    window.copy_wps_f()
    assert app.clipboard().text().splitlines()==['8510','猫食盆','猫食盆','打包','计时']
    window.copy_wps_hi()
    assert app.clipboard().text().splitlines()==['144\t0.55','2\t10','1\t5','20\t0.2','5\t15']


def test_duplicate_requires_decision_then_can_be_included_once(ui,monkeypatch):
    app,window,questions,_=ui
    import_body(ui,'8510 2个*0.55\n8510 2个*0.55')
    assert window.table.rowCount()==1 and window.unresolved_warnings
    window.review_list.setCurrentRow(0)
    monkeypatch.setattr(ReviewDialog,'exec',lambda dialog:dialog.confirm())
    # 未选择如何处理时仍保持待核对
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No)
    window.review_ambiguous_line()
    assert window.table.rowCount()==1 and window.unresolved_warnings
    monkeypatch.setattr(ReviewDialog,'exec',lambda dialog:(dialog.duplicate_action.setCurrentIndex(1),dialog.confirm()))
    window.review_ambiguous_line()
    assert window.table.rowCount()==2 and not window.unresolved_warnings
    assert window.reviewed_records()[1].duplicate_confirmed
    assert window.total_label.text()=='总计：2.20元'
    monkeypatch.setattr(QMessageBox,'question',lambda *a:(questions.append(a[-1]) or QMessageBox.StandardButton.Yes))
    window.copy_to_wps()
    assert app.clipboard().text().splitlines()==['2026/10/18\tE01\t员工01']*2
    window.parse_text()
    assert window.table.rowCount()==2  # 重解析不叠加第三条


def test_catalog_aliases_and_prices_survive_window_restart(ui):
    _,window,_,_=ui
    window.catalog.update_item('猫砂盆',D('10'),unit='件',aliases=['砂盆','猫盆'])
    window.close()
    second=MainWindow()
    try:
        assert second.bindings.resolve('测试群','测试昵称')=='E01'
        assert second.catalog.canonical('猫盆')=='猫砂盆'
        assert second.catalog.default_price('砂盆')==D('10')
        second.output.setPlainText('测试昵称\n2026年10月18日 19:40\n砂盆2件')
        second.parse_text()
        assert second.total_label.text()=='总计：20.00元'
    finally:second.close()


def test_builtin_october_import_is_separate_and_multi_price_has_no_default(ui):
    _,window,_,_=ui
    dialog=CatalogDialog(window.catalog,window)
    assert '已导入 0' in dialog.state.text()
    dialog.import_builtin()
    assert '已导入 39' in dialog.state.text()
    assert window.catalog.default_price('8510') is None
    assert window.catalog.default_price('8377')==D('.3')
    assert window.catalog.default_price('8513-6')==D('1.70')
    dialog.close()


def test_completed_copy_is_remembered_after_restart_but_can_be_reviewed(ui,monkeypatch):
    app,window,questions,notices=ui
    import_body(ui,'8510 120个*0.55')
    window.copy_to_wps(); window.copy_wps_f(); window.copy_wps_hi()
    window.close()
    second=MainWindow()
    try:
        second.output.setPlainText('测试昵称\n2026年10月18日 20:40\n8510 121个*0.55')
        second.parse_text()
        assert second.table.rowCount()==0 and '本机以前已复制' in second.unresolved_warnings[0]
        assert '高度相似' in second.unresolved_warnings[0]
        second.review_list.setCurrentRow(0)
        monkeypatch.setattr(ReviewDialog,'exec',lambda dialog:(dialog.duplicate_action.setCurrentIndex(1),dialog.confirm()))
        second.review_ambiguous_line()
        assert second.table.rowCount()==1 and not second.unresolved_warnings
        assert second.reviewed_records()[0].duplicate_confirmed
    finally:second.close()


def test_switch_group_clears_manual_identity_and_copy_context(ui,monkeypatch):
    _,window,_,_=ui
    import_body(ui,'计时3',header='2026年10月18日 19:40')
    window.review_list.setCurrentRow(0)
    def choose(dialog):
        dialog.employee_choice.setCurrentIndex(1)
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',choose)
    window.review_ambiguous_line()
    assert window.message_employees=={1:'E01'}
    window.groups.append('另一个群')
    window.group_combo.addItem('另一个群')
    window.group_combo.setCurrentText('另一个群')
    assert not window.message_employees and not window.message_dates and not window.review_overrides
    assert window.table.rowCount()==0 and window.needs_parse
    window.parse_text()
    assert window.table.rowCount()==0 and window.unresolved_warnings


def test_price_audit_and_source_survive_mock_export(ui,tmp_path):
    from openpyxl import load_workbook
    from wechat_work_recorder.workbook import write_mock_workbook
    _,window,_,_=ui
    window.catalog.update_item('打包',D('.2'),unit='捆')
    source='打包20捆*0.2\n2捆*0.2'
    import_body(ui,source)
    path=tmp_path/'mock.xlsx'
    write_mock_workbook(path,window.reviewed_records(),confirmed=True)
    b=load_workbook(path,read_only=True)
    try:
        row=list(b['审核追溯'].values)[2]
        assert row[0:2]==(1,4)
        assert row[3]=='沿用本消息项目：打包' and row[4]=='2捆*0.2'
        assert row[5:8]==('捆','消息单价','0.2')
    finally:b.close()


def test_invalid_work_date_requires_edit_in_review(ui,monkeypatch):
    _,window,_,_=ui
    import_body(ui,'10月32号\n计时3')
    assert window.table.rowCount()==0 and window.unresolved_warnings
    window.review_list.setCurrentRow(0)
    def fix(dialog):
        dialog.kind.setCurrentText('计时')
        dialog.hours.setText('3')
        dialog.work_date.setText('2026/10/17')
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',fix)
    window.review_ambiguous_line()
    assert window.table.rowCount()==1 and not window.unresolved_warnings
    assert window.table.item(0,0).text()=='2026/10/17'


def test_approval_does_not_survive_changed_original(ui,monkeypatch):
    _,window,_,_=ui
    window.catalog.set_default('8510',D('.6'))
    import_body(ui,'8510 120个*0.55')
    window.review_list.setCurrentRow(0)
    monkeypatch.setattr(ReviewDialog,'exec',lambda dialog:dialog.confirm())
    window.review_ambiguous_line()
    assert not window.price_warnings
    window.output.appendPlainText('计时1')
    window.parse_text()
    assert window.price_warnings and not window.review_overrides


def test_confirmed_batch_keeps_price_snapshot_when_reparsed_after_standard_edit(ui):
    _,window,_,_=ui
    window.catalog.set_default('8377',D('.3'))
    import_body(ui,'8377 100个')
    window.copy_to_wps();window.copy_wps_f();window.copy_wps_hi()
    window.catalog.set_default('8377',D('.2'))
    window.parse_text()
    assert window.total_label.text()=='总计：30.00元'
    assert window.reviewed_records()[0].standard_price_snapshot==D('.3')


def test_local_output_history_keeps_original_and_price_provenance(ui):
    import json, sqlite3
    _,window,_,_=ui
    window.catalog.set_default('8377',D('.3'))
    import_body(ui,'8377 100个')
    window.copy_to_wps();window.copy_wps_f();window.copy_wps_hi()
    with sqlite3.connect(window.import_history.path) as db:
        row=db.execute('SELECT output,record_json FROM output_audit').fetchone()
    data=json.loads(row[1])
    assert row[0]=='WPS剪贴板'
    assert data['source_text']=='8377 100个' and data['source_line']==3
    assert data['standard_price_snapshot']=='0.3' and data['price_source']=='当前标准价'


def test_unresolved_identity_does_not_lose_unit_quantity_price_prefill(ui,monkeypatch):
    _,window,_,_=ui
    import_body(ui,'8510 235个*0.55',header='2026年10月18日 19:40')
    window.review_list.setCurrentRow(0)
    def choose(dialog):
        assert dialog.code.currentText()=='8510'
        assert dialog.quantity.text()=='235' and dialog.price.text()=='0.55'
        dialog.employee_choice.setCurrentIndex(1)
        dialog.confirm()
    monkeypatch.setattr(ReviewDialog,'exec',choose)
    window.review_ambiguous_line()
    assert window.total_label.text()=='总计：129.25元' and not window.unresolved_warnings
