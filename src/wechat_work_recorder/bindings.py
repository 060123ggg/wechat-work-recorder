"""按微信群保存已确认的微信昵称与稳定工号。"""
import sqlite3
from pathlib import Path
from .models import Employee
from .settings import settings_path


class BindingConflict(ValueError):
    pass


class NicknameBindingStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else settings_path().with_name("bindings.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS nickname_bindings (
                group_id TEXT NOT NULL,
                nickname TEXT NOT NULL,
                employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                PRIMARY KEY (group_id, nickname)
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def install_roster(self, employees: list[Employee]) -> None:
        if len(employees) != 17 or len({e.employee_id for e in employees}) != 17 or len({e.name for e in employees}) != 17:
            raise ValueError("正式员工名册必须恰好包含17个不同工号和姓名")
        if any(not e.employee_id.strip() or not e.name.strip() for e in employees):
            raise ValueError("工号和姓名不能为空")
        with self.connection:
            existing = dict(self.connection.execute("SELECT employee_id, name FROM employees"))
            incoming = {e.employee_id: e.name for e in employees}
            if existing and existing != incoming:
                raise BindingConflict("内置员工名册与本地数据库不一致；请先核对，避免旧绑定指向错误员工")
            self.connection.executemany("INSERT OR IGNORE INTO employees(employee_id, name) VALUES (?, ?)", incoming.items())

    def employees(self) -> list[Employee]:
        return [Employee(employee_id, name) for employee_id, name in
                self.connection.execute("SELECT employee_id, name FROM employees ORDER BY employee_id")]

    def resolve(self, group_id: str, nickname: str) -> str | None:
        row = self.connection.execute("SELECT employee_id FROM nickname_bindings WHERE group_id=? AND nickname=?",
                                      (group_id.strip(), nickname.strip())).fetchone()
        return row[0] if row else None

    def list_bindings(self) -> list[tuple[str, str, str, str]]:
        return list(self.connection.execute("""
            SELECT b.group_id, b.nickname, b.employee_id, e.name
            FROM nickname_bindings AS b JOIN employees AS e USING(employee_id)
            ORDER BY b.group_id, b.nickname
        """))

    def bind(self, group_id: str, nickname: str, employee_id: str) -> None:
        group_id, nickname = group_id.strip(), nickname.strip()
        if not group_id or not nickname:
            raise ValueError("群和微信昵称不能为空")
        if not self.connection.execute("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)).fetchone():
            raise ValueError("员工工号不在正式名册中")
        existing = self.resolve(group_id, nickname)
        if existing and existing != employee_id:
            raise BindingConflict("该群中的昵称已绑定其他员工，请通过绑定管理明确修改")
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO nickname_bindings(group_id, nickname, employee_id) VALUES (?, ?, ?)",
                                    (group_id, nickname, employee_id))

    def change(self, group_id: str, nickname: str, employee_id: str) -> None:
        if not self.connection.execute("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)).fetchone():
            raise ValueError("员工工号不在正式名册中")
        with self.connection:
            cursor = self.connection.execute("UPDATE nickname_bindings SET employee_id=? WHERE group_id=? AND nickname=?",
                                             (employee_id, group_id.strip(), nickname.strip()))
            if cursor.rowcount != 1:
                raise ValueError("绑定不存在")

    def replace(self, old_group: str, old_nickname: str, new_group: str,
                new_nickname: str, employee_id: str) -> None:
        new_group, new_nickname = new_group.strip(), new_nickname.strip()
        if not new_group or not new_nickname:
            raise ValueError("群和微信昵称不能为空")
        if not self.connection.execute("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)).fetchone():
            raise ValueError("员工工号不在正式名册中")
        old_key = (old_group.strip(), old_nickname.strip())
        new_key = (new_group, new_nickname)
        if self.resolve(*old_key) is None:
            raise ValueError("原绑定不存在")
        if new_key != old_key and self.resolve(*new_key) is not None:
            raise BindingConflict("目标群中的昵称已存在绑定")
        with self.connection:
            self.connection.execute("DELETE FROM nickname_bindings WHERE group_id=? AND nickname=?", old_key)
            self.connection.execute("INSERT INTO nickname_bindings(group_id, nickname, employee_id) VALUES (?, ?, ?)",
                                    (*new_key, employee_id))

    def unbind(self, group_id: str, nickname: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM nickname_bindings WHERE group_id=? AND nickname=?",
                                    (group_id.strip(), nickname.strip()))
