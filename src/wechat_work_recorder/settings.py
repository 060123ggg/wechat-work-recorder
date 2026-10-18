"""保存非敏感的员工姓名和群名，供规则解析使用。"""
import json
import os
from pathlib import Path
from .employees import EmployeeDirectory
from .models import Employee


def settings_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "WechatWorkRecorder" / "settings.json"


def load_settings(path: Path | None = None) -> tuple[list[str], list[str]]:
    path = path or settings_path()
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["employees"]), list(data["groups"])


def save_settings(employees: list[str], groups: list[str], path: Path | None = None) -> None:
    employees = [x.strip() for x in employees if x.strip()]
    groups = [x.strip() for x in groups if x.strip()]
    if len(employees) > 17 or len(groups) > 3 or len(employees) != len(set(employees)) or len(groups) != len(set(groups)):
        raise ValueError("最多17名员工、3个群，名称不能重复")
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"employees": employees, "groups": groups}, ensure_ascii=False, indent=2), encoding="utf-8")


def directory_from_settings(employees: list[str], groups: list[str]) -> EmployeeDirectory:
    return EmployeeDirectory([Employee(str(i + 1), name) for i, name in enumerate(employees)], groups)
