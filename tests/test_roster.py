import json
from wechat_work_recorder.roster import load_builtin_roster, roster_path
from wechat_work_recorder.bindings import NicknameBindingStore


def test_private_roster_has_17_stable_ids_and_names(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    path = roster_path()
    assert load_builtin_roster() == []
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{'employee_id': f'E{i:02d}', 'name': f'测试员工{i:02d}'} for i in range(17)], ensure_ascii=False), encoding='utf-8')
    employees = load_builtin_roster()
    assert len(employees) == 17
    store = NicknameBindingStore(tmp_path / 'bindings.sqlite3')
    store.install_roster(employees)
    store.bind('一群', '测试昵称', 'E02')
    store.close()
    reopened = NicknameBindingStore(tmp_path / 'bindings.sqlite3')
    assert reopened.resolve('一群', '测试昵称') == 'E02'
    reopened.close()
