from wechat_work_recorder.roster import load_builtin_roster
from wechat_work_recorder.bindings import NicknameBindingStore


def test_official_roster_has_17_stable_ids_and_names(tmp_path):
    employees = load_builtin_roster()
    assert len(employees) == 17
    assert employees[0].employee_id == "AM-1001"
    assert employees[0].name == "美娟"
    assert employees[2].employee_id == "AM-1003"
    assert employees[2].name == "雪琴"
    assert employees[-1].employee_id == "AM-1017"
    assert employees[-1].name == "吴雨娟"
    store = NicknameBindingStore(tmp_path / "bindings.sqlite3")
    store.install_roster(employees)
    assert [(e.employee_id, e.name) for e in store.employees()] == [(e.employee_id, e.name) for e in employees]
    store.close()


def test_real_roster_binding_persists_after_reopen(tmp_path):
    db = tmp_path / "bindings.sqlite3"
    first = NicknameBindingStore(db)
    first.install_roster(load_builtin_roster())
    first.bind("一群", "雪琴微信号", "AM-1003")
    first.bind("一群", "阿琴", "AM-1003")
    first.close()
    second = NicknameBindingStore(db)
    second.install_roster(load_builtin_roster())
    assert second.resolve("一群", "雪琴微信号") == "AM-1003"
    assert second.resolve("一群", "阿琴") == "AM-1003"
    second.close()
