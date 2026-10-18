"""员工和微信群配置接口；实际名单由用户提供。"""
from collections.abc import Iterable
from .models import Employee


class EmployeeDirectory:
    def __init__(self, employees: Iterable[Employee], group_ids: Iterable[str]):
        self.employees = tuple(employees)
        self.group_ids = frozenset(group_ids)
        if len(self.employees) > 17 or len(self.group_ids) > 3:
            raise ValueError("第一版最多支持17名员工和3个微信群")
        names = [alias for employee in self.employees for alias in (employee.name, *employee.aliases)]
        if len(names) != len(set(names)):
            raise ValueError("员工姓名或别名重复")
        ids = [employee.employee_id for employee in self.employees]
        if len(ids) != len(set(ids)):
            raise ValueError("员工编号重复")

    def resolve(self, name: str) -> Employee | None:
        return next((e for e in self.employees if name in (e.name, *e.aliases)), None)

    def require_group(self, group_id: str) -> None:
        if group_id not in self.group_ids:
            raise ValueError(f"未知微信群：{group_id}")
