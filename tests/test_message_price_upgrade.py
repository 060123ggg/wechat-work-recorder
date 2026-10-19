"""业务案例仅保留工作内容；发送人和员工均为合成测试数据。"""
from datetime import date
from decimal import Decimal as D
from pathlib import Path
import csv
import pytest
from wechat_work_recorder.catalog import ItemCatalog
from wechat_work_recorder.employees import EmployeeDirectory
from wechat_work_recorder.models import Employee, WorkKind
from wechat_work_recorder.parser import parse_messages
from wechat_work_recorder.message_context import split_messages, date_for_line
from wechat_work_recorder.wechat_text import nickname_candidates
from wechat_work_recorder.payroll import calculate_amount


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    return ItemCatalog()


def parse(body, catalog, *, header='测试昵称\n2026年10月18日 19:40'):
    directory = EmployeeDirectory([Employee('E01', '测试昵称'), Employee('E02', '另一个昵称')], ['测试群'])
    return parse_messages(header + '\n' + body, directory, '测试群', catalog=catalog)


@pytest.mark.parametrize('line,code,qty,price,amount', [
    ('8510 154个*0.55','8510','154','0.55','84.70'),
    ('8510-1 216个*0.55','8510-1','216','0.55','118.80'),
    ('8510-216个×0.55','8510','216','0.55','118.80'),
    ('8510-216个*0.55','8510','216','0.55','118.80'),
    ('8510-2 216件X0.6','8510-2','216','0.6','129.60'),
    ('8513一6 50件x1.7','8513-6','50','1.7','85.00'),
    ('8393--6件✘4','8393','6','4','24.00'),
    ('8352~~270个×0.6','8352','270','0.6','162.00'),
])
def test_complete_item_before_quantity(catalog,line,code,qty,price,amount):
    result = parse(line,catalog)
    assert not result.warnings and len(result.records)==1
    record=result.records[0]
    assert (record.item_code,record.quantity,record.unit_price)==(code,D(qty),D(price))
    assert calculate_amount(record)==D(amount)
    assert record.source_text==line


@pytest.mark.parametrize('line,hours,note', [
    ('计时 5*15','5',None),('计时5小时','5',None),('计时拆箱 7*15','7','拆箱'),
    ('计时。3x15','3',None),('计时 3.5 *15','3.5',None),
    ('计时3（贴标套袋打包）','3','贴标套袋打包'),('3小时30分拆快递','3.5','拆快递'),
])
def test_hourly_never_becomes_piece(catalog,line,hours,note):
    result=parse(line,catalog)
    assert not result.warnings and len(result.records)==1
    record=result.records[0]
    assert record.kind==WorkKind.HOURLY and record.hours==D(hours) and record.note==note
    assert calculate_amount(record)==(D(hours)*15).quantize(D('.01'))


def test_five_jobs_with_inheritance_and_special_price(catalog):
    catalog.update_item('猫食盆',D('10'))
    catalog.update_item('打包',D('.2'),unit='捆')
    result=parse('10.16\n8510 144个*0.55\n猫食盆2件*10\n1件*5\n打包 20捆*0.2\n计时 5*15',catalog)
    assert not result.warnings and len(result.records)==5
    assert [r.item_code for r in result.records]==['8510','猫食盆','猫食盆','打包',None]
    assert len(result.price_warnings)==1 and '数量1' in result.price_warnings[0] and '5.00' in result.price_warnings[0]
    assert {r.work_date for r in result.records}=={date(2026,10,16)}
    assert result.records[2].note=='沿用本消息项目：猫食盆'
    assert catalog.default_price('猫食盆')==D('10')


def test_inheritance_updates_and_never_crosses_message(catalog):
    catalog.update_item('猫食盆',D('10'))
    catalog.update_item('打包',D('.2'),unit='捆')
    result=parse('猫食盆2件*10\n1件*5\n打包23捆*0.2\n2捆*0.2\n另一个昵称\n2026年10月18日 20:00\n1件*5',catalog)
    assert [r.item_code for r in result.records]==['猫食盆','猫食盆','打包','打包']
    assert len(result.warnings)==1 and '继承不确定' in result.warnings[0]


@pytest.mark.parametrize('body_date,expected', [('10.17',date(2026,10,17)),('10月17号',date(2026,10,17)),
                                             ('2025/10/17',date(2025,10,17)),('',date(2026,10,18))])
def test_body_date_has_priority(catalog,body_date,expected):
    result=parse(body_date+'\n计时 3.5*15\n8510 235个*0.55\n8377 100个*0.2',catalog)
    assert len(result.records)==3 and not result.warnings
    assert {r.work_date for r in result.records}=={expected}
    assert nickname_candidates('测试昵称\n2026年10月18日 19:40\n'+body_date+'\n计时3.5', ['测试群'])==['测试昵称']


def test_october_reference_price_difference_is_not_silently_accepted(catalog):
    path=Path(__file__).parents[1]/'src/wechat_work_recorder/october_prices.csv'
    count,pending=catalog.import_october_csv(path)
    assert count==39 and pending>0
    assert catalog.default_price('8377')==D('.3')
    assert catalog.default_price('8510') is None
    result=parse('10月17号\n计时 3.5*15\n8510 235个*0.55\n8377 100个*0.2',catalog)
    assert len(result.records)==3 and not result.warnings
    assert len(result.price_warnings)==2
    assert any('8377' in w and '.3' in w and '.2' in w for w in result.price_warnings)


def test_missing_sender_is_not_guessed_from_body(catalog):
    result=parse('10月17号\n计时3',catalog,header='2026年10月18日 19:40')
    assert not result.records and result.warnings
    assert '发送人待确认' in result.warnings[0]
    assert nickname_candidates('10.17\n计时3',[])==[]


def test_many_messages_do_not_share_people_dates_or_inheritance(catalog):
    result=parse('10.16\n8510 2个*0.55\n另一个昵称\n2026年10月19日 20:00\n计时2\n测试昵称\n2026年10月20日 20:00\n10月18号\n8510-1 3个*0.55',catalog)
    assert not result.warnings
    assert [(r.employee_id,r.work_date,r.message_number) for r in result.records]==[
        ('E01',date(2026,10,16),1),('E02',date(2026,10,19),2),('E01',date(2026,10,18),3)]


def test_unknown_new_project_is_a_review_proposal(catalog):
    result=parse('猫砂盆 20个*10',catalog)
    assert not result.records and len(result.proposals)==1
    assert '新增项目' in result.warnings[0]
    assert (result.proposals[0].item_code,result.proposals[0].quantity,result.proposals[0].unit_price)==('猫砂盆',D('20'),D('10'))
    catalog.update_item('猫砂盆',D('10'),aliases=['砂盆'])
    assert len(parse('砂盆20个*10',catalog).records)==1
    assert parse('砂盆20个*10',catalog).records[0].item_code=='猫砂盆'
    assert '猫砂盆组装' not in catalog.codes


def test_missing_price_waits_for_confirmed_standard(catalog):
    catalog.update_item('8377',None)
    result=parse('8377 100个',catalog)
    assert not result.records and len(result.proposals)==1 and result.proposals[0].unit_price is None
    catalog.set_default('8377',D('.3'))
    old=parse('8377 100个',catalog).records[0]
    catalog.set_default('8377',D('.2'))
    assert calculate_amount(old)==D('30.00')
    assert calculate_amount(parse('8377 100个',catalog).records[0])==D('20.00')


def test_current_standard_overrides_reference_but_never_message_code(catalog):
    catalog.update_item('8510',D('.6'))
    catalog.update_item('8510-1',D('.55'))
    first=parse('8510 120个*0.55',catalog)
    assert first.records[0].item_code=='8510' and first.price_warnings
    assert catalog.default_price('8510')==D('.6')
    assert parse('8510 120个*0.55',catalog).price_warnings
    assert not parse('8510-1 120个*0.55',catalog).price_warnings


def test_duplicate_and_similar_messages_are_withheld_for_decision(catalog):
    result=parse('8510 120个*0.55\n测试昵称\n2026年10月18日 20:00\n8510 121个*0.55',catalog)
    assert len(result.records)==1 and len(result.proposals)==1
    assert '疑似重复消息' in result.warnings[0]
    repeated=parse('8510 120个*0.55\n8510 120个*0.55',catalog)
    assert len(repeated.records)==1 and len(repeated.proposals)==1 and repeated.warnings


def test_old_catalog_migration_preserves_defaults_and_local_projects(tmp_path):
    path=tmp_path/'catalog.json'
    path.write_text('{"codes":["打包"],"defaults":{"打包":"0.2","8513-6":"1.8"}}', encoding='utf-8')
    catalog=ItemCatalog(path)
    catalog.update_item('猫砂盆',D('10'),aliases=['砂盆','猫盆'])
    reopened=ItemCatalog(path)
    assert reopened.default_price('打包')==D('.2') and reopened.default_price('8513-6')==D('1.8')
    assert reopened.canonical('砂盆')==reopened.canonical('猫盆')=='猫砂盆'
    with pytest.raises(ValueError):reopened.update_item('猫砂盆',D('10'),aliases=['8510'])
    with pytest.raises(ValueError):reopened.update_item('另一个项目',D('10'),aliases=['砂盆'])


def test_import_rejects_other_months_atomically_and_never_overrides_manual_price(catalog,tmp_path):
    p=tmp_path/'prices.csv'
    def write(month):
        p.write_text('code,price,count,unit,month,source\n8377,.3,4,件,'+month+',测试价格源\n8510,.6,2,件,'+month+',测试价格源\n8510,.55,8,件,'+month+',测试价格源\n', encoding='utf-8')
    write('2026-09')
    with pytest.raises(ValueError):catalog.import_october_csv(p)
    assert not catalog.path.exists()
    write('2026-10')
    assert catalog.import_october_csv(p)==(2,1)
    assert catalog.default_price('8510') is None
    catalog.set_default('8377',D('.2'))
    catalog.import_october_csv(p)
    assert ItemCatalog(catalog.path).default_price('8377')==D('.2')


def test_migration_creates_one_original_backup(tmp_path):
    original='{"codes":["打包"],"defaults":{"打包":"0.2"}}'.encode("utf-8")
    path=tmp_path/'catalog_overrides.json'
    path.write_bytes(original)
    catalog=ItemCatalog(path)
    catalog.set_default('打包',D('.3'))
    backup=path.with_name('catalog_overrides.v1.backup.json')
    assert backup.read_bytes()==original
    catalog.set_default('打包',D('.4'))
    assert backup.read_bytes()==original


@pytest.mark.parametrize('bad',['8510 5个*','8510-12*0.55','计时拆箱7*12','8510 3个*0.55 9件*2'])
def test_unresolved_work_never_silently_disappears(catalog,bad):
    result=parse(bad+'\n计时1',catalog)
    assert len(result.records)==1 and result.records[0].kind==WorkKind.HOURLY
    assert any(bad in warning for warning in result.warnings)


def test_decimal_rounding_and_identity_are_stable(catalog):
    catalog.update_item('猫砂盆',D('.335'))
    result=parse('猫砂盆3件',catalog)
    assert calculate_amount(result.records[0])==D('1.01')
    assert result.records[0].unit_price==D('.335')


@pytest.mark.parametrize('header', ['测试昵称\n2026年10月18日19:40','2026年10月18日 19:40 测试昵称','测试昵称 2026年10月18日 19:40'])
def test_sender_header_variants_keep_body_date(catalog,header):
    result=parse('10月17号\n8510 235个*0.55\n计时3.5',catalog,header=header)
    assert not result.warnings and len(result.records)==2
    assert {r.work_date for r in result.records}=={date(2026,10,17)}


@pytest.mark.parametrize('body', ['8510\n154个*0.55','8510 154个\n*0.55','货号 8510\n数量 154个\n单价0.55'])
def test_line_wraps_keep_quantity_and_explicit_price(catalog,body):
    catalog.set_default('8510',D('.6'))
    result=parse(body,catalog)
    assert not result.warnings and len(result.records)==1
    assert result.records[0].item_code=='8510'
    assert result.records[0].quantity==D('154') and result.records[0].unit_price==D('.55')
    assert result.price_warnings  # 不能因为换行而错误采用 .60


def test_cleared_standard_stays_unconfirmed_after_restart(catalog):
    catalog.update_item('8513-6',None)
    assert ItemCatalog(catalog.path).default_price('8513-6') is None


@pytest.mark.parametrize('middle',['计时1','8513-70*1.7'])
def test_uncertain_or_different_work_does_not_leak_previous_project(catalog,middle):
    catalog.update_item('猫食盆',D('10'))
    result=parse('猫食盆2件*10\n'+middle+'\n1件*5',catalog)
    assert '继承不确定' in result.warnings[-1]


def test_explicit_header_labels_never_become_nicknames(catalog):
    text='发送人：测试昵称\n\n微信发送时间：2026年10月18日 19:40\n\n正文：\n10月17号\n计时3.5'
    directory=EmployeeDirectory([Employee('E01','测试昵称')],['测试群'])
    result=parse_messages(text,directory,'测试群',catalog=catalog)
    assert nickname_candidates(text,['测试群'])==['测试昵称']
    assert not result.warnings and result.records[0].work_date==date(2026,10,17)


def test_unknown_spaced_sender_with_timestamp_does_not_inherit_employee(catalog):
    result=parse('8510 2个*0.55\n测试 陌生昵称\n2026年10月18日 20:00\n计时3',catalog)
    assert len(result.records)==1 and result.records[0].employee_id=='E01'
    assert '员工未绑定' in result.warnings[0]
