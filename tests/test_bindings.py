import pytest
from wechat_work_recorder.bindings import BindingConflict, NicknameBindingStore
from wechat_work_recorder.models import Employee
from wechat_work_recorder.wechat_text import nickname_candidates


def roster():
    return [Employee(f"E{i:02d}", f"员工{i:02d}") for i in range(1, 18)]


def test_bindings_persist_and_allow_many_nicknames(tmp_path):
    path = tmp_path / "bindings.sqlite3"
    store = NicknameBindingStore(path)
    store.install_roster(roster())
    store.bind("一群", "小雪", "E01")
    store.bind("一群", "雪琴", "E01")
    store.close()
    reopened = NicknameBindingStore(path)
    assert reopened.resolve("一群", "小雪") == "E01"
    assert reopened.resolve("一群", "雪琴") == "E01"
    assert len(reopened.list_bindings()) == 2
    reopened.unbind("一群", "小雪")
    assert reopened.resolve("一群", "小雪") is None
    reopened.close()


def test_group_scoped_conflict_and_explicit_change(tmp_path):
    store = NicknameBindingStore(tmp_path / "bindings.sqlite3")
    store.install_roster(roster())
    store.bind("一群", "小雪", "E01")
    with pytest.raises(BindingConflict):
        store.bind("一群", "小雪", "E02")
    assert store.resolve("一群", "小雪") == "E01"
    store.bind("二群", "小雪", "E02")
    store.change("一群", "小雪", "E03")
    assert store.resolve("一群", "小雪") == "E03"
    assert store.resolve("二群", "小雪") == "E02"
    store.close()


def test_roster_change_cannot_silently_reassign_existing_bindings(tmp_path):
    store = NicknameBindingStore(tmp_path / "bindings.sqlite3")
    store.install_roster(roster())
    changed = roster()
    changed[0] = Employee("E01", "另一个人")
    with pytest.raises(BindingConflict):
        store.install_roster(changed)
    store.close()


def test_nickname_candidates_from_batch_copy():
    text = "2026/10/9 09:30 雪琴\n8513-7 70*1.7\n计时3.5\n小李：\n8510-1 20*2"
    assert nickname_candidates(text, ["一群"]) == ["雪琴", "小李"]
    assert nickname_candidates("2026/10/9\n雪琴\n8513-7 70*1.7", ["一群"]) == ["雪琴"]


def test_replace_binding_is_atomic_on_conflict(tmp_path):
    store = NicknameBindingStore(tmp_path / "bindings.sqlite3")
    store.install_roster(roster())
    store.bind("一群", "旧昵称", "E01")
    store.bind("二群", "已占用", "E02")
    with pytest.raises(BindingConflict):
        store.replace("一群", "旧昵称", "二群", "已占用", "E03")
    assert store.resolve("一群", "旧昵称") == "E01"
    assert store.resolve("二群", "已占用") == "E02"
    store.replace("一群", "旧昵称", "三群", "新昵称", "E03")
    assert store.resolve("一群", "旧昵称") is None
    assert store.resolve("三群", "新昵称") == "E03"
    store.close()
