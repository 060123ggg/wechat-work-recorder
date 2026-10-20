"""本机已复制/已保存项目的重复提醒；不代表 WPS 已实际入账。"""
import json
import sqlite3
from dataclasses import asdict
from contextlib import closing
from difflib import SequenceMatcher
from pathlib import Path
from .settings import settings_path


def _number(value):
    return format(value.normalize(), 'f') if value is not None else ''


def signature(record):
    return json.dumps([record.kind.value, record.item_code or '', _number(record.quantity),
                       _number(record.unit_price), _number(record.hours), record.note or ''], ensure_ascii=False)


class ImportHistory:
    def __init__(self, path=None):
        self.path = Path(path) if path else settings_path().with_name('imports.sqlite3')

    def find(self, record):
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute('SELECT signature FROM imports WHERE employee=? AND work_date=? AND kind=? AND code=?',
                (record.employee_id, record.work_date.isoformat(), record.kind.value, record.item_code or '')).fetchall()
        value = signature(record)
        for (previous,) in rows:
            if previous == value:
                return '与本机以前已复制/已保存的项目完全相同'
            if SequenceMatcher(None, previous, value).ratio() >= .92:
                return '与本机以前已复制/已保存的项目高度相似'
        return None

    def remember(self, records, output='WPS剪贴板'):
        records = list(records)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS imports (employee TEXT, work_date TEXT, kind TEXT, code TEXT, signature TEXT, UNIQUE(employee,work_date,kind,code,signature))')
            connection.execute('CREATE TABLE IF NOT EXISTS output_audit (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, output TEXT, record_json TEXT)')
            connection.executemany('INSERT OR IGNORE INTO imports VALUES(?,?,?,?,?)',
                [(r.employee_id, r.work_date.isoformat(), r.kind.value, r.item_code or '', signature(r)) for r in records])
            connection.executemany('INSERT INTO output_audit(output,record_json) VALUES(?,?)',
                [(output, json.dumps(asdict(r), ensure_ascii=False, default=str)) for r in records])

    def audit_review(self, decision):
        """Append a local review explanation without altering remembered wages/schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS imports (employee TEXT, work_date TEXT, kind TEXT, code TEXT, signature TEXT, UNIQUE(employee,work_date,kind,code,signature))')
            connection.execute('CREATE TABLE IF NOT EXISTS output_audit (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, output TEXT, record_json TEXT)')
            connection.execute('INSERT INTO output_audit(output,record_json) VALUES(?,?)',
                ('人工审核重复项', json.dumps(decision, ensure_ascii=False)))
