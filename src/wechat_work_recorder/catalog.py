"""脱敏历史货号仅供识别参考；已确认现行价格独立保存。"""
import csv
import json
import os
import re
from decimal import Decimal
from pathlib import Path

DASHES = str.maketrans({char: '-' for char in '—–−‐‑－﹣'})
CONFIRMED_DEFAULTS = {'8513-6': Decimal('1.70')}
NAMED_PROJECT = re.compile(r'[\u4e00-\u9fff]{2,12}')


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
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.additions = {normalize_code(x) for x in data.get('codes', [])}
            self.defaults.update({normalize_code(k): Decimal(str(v)) for k, v in data.get('defaults', {}).items()})

    @property
    def codes(self) -> set[str]:
        return set(self.historical) | self.additions

    def historical_prices(self, code: str) -> str:
        return '; '.join(row['历史I列单价与次数（仅参考）'] for row in self.historical.get(normalize_code(code), []))

    def default_price(self, code: str) -> Decimal | None:
        return self.defaults.get(normalize_code(code))

    def add_code(self, code: str) -> None:
        code = normalize_code(code)
        if not valid_catalog_code(code):
            raise ValueError('新增货号须为四位数字或四位数字-一位数字；工作项目须为2至12个汉字（不含计时）')
        self.additions.add(code)
        self.save()

    def rename_added_code(self, old: str, new: str) -> None:
        """只能更正本机新增货号；历史原始记录保持不变。"""
        old, new = normalize_code(old), normalize_code(new)
        if old not in self.additions or old in self.historical:
            raise ValueError('只能修改本机新增、非历史货号')
        if new in self.codes or not valid_catalog_code(new):
            raise ValueError('新货号无效或已存在')
        self.additions.remove(old)
        self.additions.add(new)
        if old in self.defaults:
            self.defaults[new] = self.defaults.pop(old)
        self.save()

    def set_default(self, code: str, price: Decimal) -> None:
        code = normalize_code(code)
        if code not in self.codes or price < 0:
            raise ValueError('货号或单价无效')
        self.defaults[code] = price
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({'codes': sorted(self.additions),
            'defaults': {k: str(v) for k, v in self.defaults.items() if k not in CONFIRMED_DEFAULTS or v != CONFIRMED_DEFAULTS[k]}},
            ensure_ascii=False, indent=2), encoding='utf-8')

    def candidates(self, text: str) -> list[str]:
        text = normalize_code(text)
        return sorted((code for code in self.codes if code in text), key=lambda x: (-len(x), x))[:8]

    def review_candidates(self, text: str) -> str:
        """只展示候选，不把连写的数字擅自拆成已确认数量。"""
        codes = ', '.join(self.candidates(text)) or '无'
        pair = re.search(r'(\d+(?:\.\d+)?)\s*[＊*×✘xX]\s*(\d+(?:\.\d+)?)', text)
        if pair:
            return f'历史货号候选：{codes}；乘号前数字：{pair.group(1)}（数量边界待确认）；单价候选：{pair.group(2)}'
        return f'历史货号候选：{codes}；数量/单价待确认'
