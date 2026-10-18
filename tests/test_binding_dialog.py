import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from wechat_work_recorder.binding_dialog import BindingDialog
from wechat_work_recorder.bindings import NicknameBindingStore
from wechat_work_recorder.models import Employee


def test_dialog_add_modify_and_unbind(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NicknameBindingStore(tmp_path / "bindings.sqlite3")
    store.install_roster([Employee(f"E{i:02d}", f"员工{i:02d}") for i in range(1, 18)])
    dialog = BindingDialog(store, ["一群", "二群"])
    monkeypatch.setattr(QInputDialog, "getItem", lambda parent, title, label, choices, current, editable: (choices[1] if len(choices) > 2 else choices[current], True))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("昵称甲", True))
    dialog.add_binding()
    assert dialog.table.rowCount() == 1
    assert store.resolve("一群", "昵称甲") == "E01"
    dialog.table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getItem", lambda parent, title, label, choices, current, editable: (choices[2] if len(choices) > 2 else choices[1], True))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("昵称乙", True))
    dialog.change_binding()
    assert store.resolve("一群", "昵称甲") is None
    assert store.resolve("二群", "昵称乙") == "E02"
    dialog.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.remove_binding()
    assert dialog.table.rowCount() == 0
    store.close()
    dialog.close()
