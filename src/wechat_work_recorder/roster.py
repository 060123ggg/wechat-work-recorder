"""读取随程序发布的正式员工名册。"""
import json
from importlib.resources import files
from .models import Employee


def load_builtin_roster() -> list[Employee]:
    resource = files("wechat_work_recorder").joinpath("employees.json")
    if not resource.is_file():
        return []
    data = json.loads(resource.read_text(encoding="utf-8"))
    employees = [Employee(str(row["employee_id"]).strip(), str(row["name"]).strip()) for row in data]
    if len(employees) != 17 or len({e.employee_id for e in employees}) != 17 or len({e.name for e in employees}) != 17:
        raise ValueError("内置员工名册必须恰好包含17名不同工号和姓名")
    return employees
