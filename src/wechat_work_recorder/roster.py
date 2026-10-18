"""从当前 Windows 用户的私有目录读取正式名册，避免发布员工姓名。"""
import json
from pathlib import Path
from .models import Employee
from .settings import settings_path


def roster_path() -> Path:
    return settings_path().with_name('employees.private.json')


def load_builtin_roster() -> list[Employee]:
    """保留旧调用接口；实际名单只保存在本机，不随程序发布。"""
    path = roster_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    employees = [Employee(str(row['employee_id']).strip(), str(row['name']).strip()) for row in data]
    if len(employees) != 17 or len({e.employee_id for e in employees}) != 17 or len({e.name for e in employees}) != 17:
        raise ValueError('本机员工名册必须恰好包含17名不同工号和姓名')
    return employees
