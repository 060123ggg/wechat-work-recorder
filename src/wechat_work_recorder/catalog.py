"""历史货号用于识别；十月价格来源与本机确认的标准价独立保存。"""
import csv
import json
import os
import re
from decimal import Decimal
from pathlib import Path

DASHES = str.maketrans({char: '-' for char in '—–−‐‑－﹣'})
CONFIRMED_DEFAULTS = {'8513-6': Decimal('1.70')}
CONFIRMED_CODES = {'8513-6', '8513-7', '8510-1'}
NAMED_PROJECT = re.compile(r'[\u4e00-\u9fff]{2,24}')


def valid_catalog_code(code: str) -> bool:
    return bool(re.fullmatch(r'\d{4}(?:-\d)?', code) or
                (NAMED_PROJECT.fullmatch(code) and code not in ('计时', '工时')))


def normalize_code(value: str) -> str:
    value = value.strip().translate(DASHES)
    value = re.sub(r'(?<=\d)一(?=\d)', '-', value)
    return re.sub(r'\s*-\s*', '-', value)


def catalog_path() -> Path:
    base = Path(os.environ.get('APPDATA') or Path.home() / '.config')
    return base / 'WechatWorkRecorder' / 'catalog_overrides.json'


def money(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('单价须为有效的非负金额')
    return result


class ItemCatalog:
    def __init__(self, path: Path | None = None):
        self.path = path or catalog_path()
        self.historical: dict[str, list[dict]] = {}
        with (Path(__file__).parent / 'historical_items.csv').open(encoding='utf-8-sig', newline='') as source:
            for row in csv.DictReader(source):
                code = normalize_code(row['标准化候选'])
                if code and row['类别'] in ('四位数字-一位数字', '纯四位数字'):
                    self.historical.setdefault(code, []).append(row)
        self.additions: set[str] = set()
        self.defaults = dict(CONFIRMED_DEFAULTS)
        self.items: dict[str, dict] = {}
        self.legacy_backup = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema_version', 1) < 2:
                self.legacy_backup = self.path.read_bytes()
            self.additions = {normalize_code(x) for x in data.get('codes', [])}
            self.defaults.update({normalize_code(k): money(v) for k, v in data.get('defaults', {}).items()})
            self.items = data.get('items', {})
            for code, item in self.items.items():
                if item.get('confirmed') is False:
                    self.defaults.pop(code, None)
        self._validate_aliases(self.items)

    @property
    def codes(self) -> set[str]:
        return set(self.historical) | self.additions | set(self.items) | CONFIRMED_CODES

    def canonical(self, name: str) -> str:
        name = normalize_code(name)
        if name in self.codes:
            return name
        return next((code for code, data in self.items.items() if name in data.get('aliases', [])), name)

    @property
    def recognition_names(self) -> set[str]:
        return self.codes | {alias for data in self.items.values() for alias in data.get('aliases', [])}

    def historical_prices(self, code: str) -> str:
        # 旧接口仅提供查询，不参与当前标准价生成。
        return '; '.join(row['历史I列单价与次数（仅参考）'] for row in self.historical.get(normalize_code(code), []))

    def price_history(self, code: str) -> list[dict]:
        return list(self.items.get(self.canonical(code), {}).get('history', []))

    def default_price(self, code: str) -> Decimal | None:
        return self.defaults.get(self.canonical(code))

    def add_code(self, code: str) -> None:
        code = normalize_code(code)
        if not valid_catalog_code(code):
            raise ValueError('新增货号须为四位数字或四位数字-一位数字；工作项目须为2至24个汉字（不含计时）')
        if self.canonical(code) != code:
            raise ValueError('名称已用作其他项目别名')
        self.additions.add(code)
        self.save()

    def rename_added_code(self, old: str, new: str) -> None:
        old, new = normalize_code(old), normalize_code(new)
        if old not in self.additions or old in self.historical:
            raise ValueError('只能修改本机新增、非历史货号')
        self.update_item(new, self.default_price(old), old_code=old,
                         unit=self.items.get(old, {}).get('unit', '件'),
                         aliases=self.items.get(old, {}).get('aliases', []))

    def _validate_aliases(self, items):
        seen = {}
        codes = set(self.historical) | self.additions | set(items)
        for code, data in items.items():
            for alias in data.get('aliases', []):
                if not alias or alias == code or alias in codes or (alias in seen and seen[alias] != code):
                    raise ValueError('别名与项目名称或其他别名冲突')
                if not re.fullmatch(r'[\u4e00-\u9fff]{2,24}|[A-Za-z][A-Za-z0-9_.-]{1,39}|\d{4}(?:-\d)?', alias):
                    raise ValueError('别名须为中文名称或英文字母开头的完整项目代号，不能包含数量、空格或分隔符')
                if re.fullmatch(r'\d{4}(?:-\d)?', alias):
                    raise ValueError('数字货号必须保持独立身份，不能作为其他项目别名')
                seen[alias] = code

    def update_item(self, code: str, standard_price: Decimal | None, unit='件', aliases=(), old_code=None):
        code = normalize_code(code)
        old_code = normalize_code(old_code or code)
        if not valid_catalog_code(code):
            raise ValueError('项目名称或完整货号无效')
        if code != old_code and code in self.codes:
            raise ValueError('目标项目已存在，禁止合并不同货号')
        if standard_price is not None:
            standard_price = money(standard_price)
        aliases = list(dict.fromkeys(normalize_code(x) for x in aliases if x.strip()))
        data = dict(self.items.get(old_code, {}))
        data.update(unit=unit.strip() or '件', pricing_method='piece', aliases=aliases,
                    confirmed=standard_price is not None, standard_source='用户确认')
        items = dict(self.items)
        if code != old_code:
            # 历史数字货号不重命名，防止 8510 与 8510-1 身份混淆。
            if old_code in self.historical:
                raise ValueError('历史数字货号保留独立身份；可编辑标准价、单位和中文别名')
            items.pop(old_code, None)
        items[code] = data
        self._validate_aliases(items)
        self.items = items
        if code != old_code:
            self.additions.discard(old_code)
            self.defaults.pop(old_code, None)
        self.additions.add(code)
        if standard_price is None:
            self.defaults.pop(code, None)
        else:
            self.defaults[code] = standard_price
        self.save()

    def set_default(self, code: str, price: Decimal) -> None:
        code = self.canonical(code)
        if code not in self.codes:
            raise ValueError('货号或单价无效')
        self.defaults[code] = money(price)
        self.items.setdefault(code, {}).update(confirmed=True, standard_source='用户确认')
        self.save()

    def import_october_csv(self, path: Path) -> tuple[int, int]:
        """只接收脱敏十月价格表；先校验全部行，失败时不写本机资料库。"""
        rows: dict[str, list[dict]] = {}
        with Path(path).open(encoding='utf-8-sig', newline='') as source:
            for row in csv.DictReader(source):
                if row.get('month') != '2026-10':
                    raise ValueError('本版只接受 month=2026-10 的十月价格资料')
                code = normalize_code(row.get('code', ''))
                if not valid_catalog_code(code):
                    raise ValueError('价格表包含无效项目名称')
                price = money(row['price'])
                count = int(row.get('count', '1'))
                if count <= 0:
                    raise ValueError('历史次数无效')
                rows.setdefault(code, []).append(dict(price=str(price), count=count,
                    source=row.get('source') or '十月价格导入', month='2026-10', unit=row.get('unit') or '件'))
        if not rows:
            raise ValueError('价格表没有有效数据')
        ambiguous = 0
        for code, history in rows.items():
            data = self.items.setdefault(code, {})
            data['history'] = history
            data.setdefault('unit', history[0]['unit'])
            data.setdefault('aliases', [])
            prices = {money(row['price']) for row in history}
            # 重复导入不覆盖用户标准价，亦不把多价项目按次数选价。
            if code not in self.defaults:
                if len(prices) == 1:
                    self.defaults[code] = prices.pop()
                    data.update(confirmed=True, standard_source='十月单一历史价初始化')
                else:
                    data.update(confirmed=False, standard_source='多价待确认')
                    ambiguous += 1
        self.save()
        return len(rows), ambiguous

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.legacy_backup is not None:
            backup = self.path.with_name('catalog_overrides.v1.backup.json')
            if not backup.exists():
                with backup.open('xb') as output:
                    output.write(self.legacy_backup)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema_version': 2, 'codes': sorted(self.additions),
            'defaults': {k: str(v) for k, v in self.defaults.items()}, 'items': self.items},
            ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)
        self.legacy_backup = None

    def candidates(self, text: str) -> list[str]:
        text = normalize_code(text)
        return sorted({self.canonical(name) for name in self.recognition_names if name in text},
                      key=lambda x: (-len(x), x))[:8]

    def review_candidates(self, text: str) -> str:
        codes = ', '.join(self.candidates(text)) or '无'
        pair = re.search(r'(\d+(?:\.\d+)?)\s*[＊*×✘xX]\s*(\d+(?:\.\d+)?)', text)
        if pair:
            return f'历史货号候选：{codes}；乘号前数字：{pair.group(1)}（数量边界待确认）；单价候选：{pair.group(2)}'
        return f'历史货号候选：{codes}；数量/单价待确认'
