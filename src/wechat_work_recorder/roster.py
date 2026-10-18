"""从当前 Windows 用户的私有目录读取正式名册，避免发布员工姓名。"""
import json
from pathlib import Path
from .models import Employee
from .settings import settings_path


def roster_path() -> Path:
    return settings_path().with_name('employees.private.json')


def validate_roster(employees: list[Employee]) -> None:
    if len(employees) != 17 or len({e.employee_id for e in employees}) != 17 or len({e.name for e in employees}) != 17:
        raise ValueError('正式员工名册必须恰好包含17名不同工号和姓名')
    if any(not e.employee_id.strip() or not e.name.strip() for e in employees):
        raise ValueError('工号和姓名均不能为空')


def save_private_roster(employees: list[Employee]) -> None:
    validate_roster(employees)
    path = roster_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps([{'employee_id': e.employee_id, 'name': e.name}
                                     for e in employees], ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_builtin_roster() -> list[Employee]:
    """保留旧调用接口；实际名单只保存在本机，不随程序发布。"""
    path = roster_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    employees = [Employee(str(row['employee_id']).strip(), str(row['name']).strip()) for row in data]
    validate_roster(employees)
    return employees
