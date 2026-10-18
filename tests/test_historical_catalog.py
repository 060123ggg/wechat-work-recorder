from decimal import Decimal
import pytest
from wechat_work_recorder.catalog import ItemCatalog, normalize_code
from wechat_work_recorder.employees import EmployeeDirectory
from wechat_work_recorder.models import Employee, WorkKind
from wechat_work_recorder.parser import parse_messages
from wechat_work_recorder.payroll import calculate_amount


def directory():
    return EmployeeDirectory([Employee('AM-1003', '测试员工')], ['一群'])


def parse(line):
    return parse_messages('2026/10/9\n测试员工\n' + line, directory(), '一群')


@pytest.mark.parametrize('dash', ['-', '—', '一', '–', '−'])
def test_full_code_with_dash_variants(dash):
    result = parse(f'8513{dash}6 50*1.7\n计时3.5')
    assert not result.warnings
    assert [(r.kind, r.item_code, calculate_amount(r)) for r in result.records] == [
        (WorkKind.PIECE, '8513-6', Decimal('85.00')),
        (WorkKind.HOURLY, None, Decimal('52.50'))]
    assert result.records[0].source_text == f'8513{dash}6 50*1.7'


def test_double_separator_and_hourly_on_one_line():
    result = parse('8393--6✘4 计时3.5小时')
    assert not result.warnings
    assert len(result.records) == 2
    assert sum((calculate_amount(record) for record in result.records), Decimal('0')) == Decimal('76.50')


@pytest.mark.parametrize('line,code,quantity,price,amount', [
    ('8393--6*4', '8393', '6', '4', '24.00'),
    ('8352~~270*0.6', '8352', '270', '0.6', '162.00'),
    ('8510--140*0.55', '8510', '140', '0.55', '77.00'),
    ('6002--3*10', '6002', '3', '10', '30.00'),
    ('8087-2--12*3.5', '8087-2', '12', '3.5', '42.00'),
    ('8510-1--40✘0.55', '8510-1', '40', '0.55', '22.00'),
    ('8393--6×4', '8393', '6', '4', '24.00'),
])
def test_known_code_double_separator_keeps_full_code_and_pay(line, code, quantity, price, amount):
    result = parse(line + '\n计时3.5')
    assert not result.warnings
    assert len(result.records) == 2
    piece, hourly = result.records
    assert piece.item_code == code and piece.source_text == line
    assert piece.quantity == Decimal(quantity) and piece.unit_price == Decimal(price)
    assert calculate_amount(piece) == Decimal(amount)
    assert calculate_amount(hourly) == Decimal('52.50')


@pytest.mark.parametrize('line', ['8513-70*1.7', '9999--6*4',
                                  '8393--6*4 8352~~270*0.6', '8393--6*4 10*3'])
def test_ambiguous_or_unknown_keeps_original_and_requires_review(line):
    result = parse(line + '\n计时3.5')
    assert len(result.records) == 1 and result.records[0].kind == WorkKind.HOURLY
    assert result.warnings and line in result.warnings[0]


def test_default_price_is_confirmed_not_historical():
    catalog = ItemCatalog()
    assert catalog.default_price('8513—6') == Decimal('1.70')
    assert catalog.default_price('8510-1') is None
    assert catalog.historical_prices('8510-1')
    assert '8510' in catalog.codes and '8510-1' in catalog.codes
    result = parse('8513—6 50')
    assert len(result.records) == 1
    assert result.records[0].unit_price == Decimal('1.70')
    assert calculate_amount(result.records[0]) == Decimal('85.00')


def test_explicit_price_override_warning_and_no_default_mutation():
    result = parse('8513—6 50*2')
    assert len(result.records) == 1 and calculate_amount(result.records[0]) == Decimal('100.00')
    assert result.price_warnings and '默认价' in result.price_warnings[0]
    assert ItemCatalog().default_price('8513-6') == Decimal('1.70')


def test_local_catalog_add_and_update(tmp_path):
    path = tmp_path / 'catalog.json'
    catalog = ItemCatalog(path)
    catalog.add_code('8513—7')
    catalog.set_default('8513-7', Decimal('1.80'))
    catalog.rename_added_code('8513-7', '8513-8')
    reopened = ItemCatalog(path)
    assert reopened.default_price('8513-8') == Decimal('1.80')
    assert reopened.default_price('8513-7') is None
    assert normalize_code('8513一7') == '8513-7'
    assert not ItemCatalog(tmp_path / 'other.json').default_price('8513-7')
