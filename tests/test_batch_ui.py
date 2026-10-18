import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QInputDialog
from wechat_work_recorder import app as app_module
from wechat_work_recorder.bindings import NicknameBindingStore
from wechat_work_recorder.models import Employee
from wechat_work_recorder.wechat_text import nickname_candidates


def roster():
    return [Employee(f"E{i:02d}", f"员工{i:02d}") for i in range(1, 18)]


def test_unknown_batch_nickname_prompts_then_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    calls = []

    def choose(*args):
        calls.append(args)
        return "E03  员工03", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    app.clipboard().setText("2026/10/9\n雪琴\n8513-7 70*1.7\n计时3.5")
    window.import_clipboard_text()
    assert len(calls) == 1
    assert window.table.rowCount() == 2
    assert not window.unresolved_warnings
    assert all(r.employee_id == "E03" for r in window.reviewed_records())
    window.close()
    store = NicknameBindingStore(tmp_path / "WechatWorkRecorder" / "bindings.sqlite3")
    assert store.resolve("一群", "雪琴") == "E03"
    store.close()


def test_confirmed_mapping_is_used_without_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    window.bindings.bind("一群", "雪琴", "E02")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (_ for _ in ()).throw(AssertionError("must not prompt")))
    app.clipboard().setText("2026/10/9\n雪琴\n8513-7 70*1.7")
    window.import_clipboard_text()
    assert window.reviewed_records()[0].employee_id == "E02"
    window.close()


def test_sender_prefix_on_same_line_is_candidate():
    assert nickname_candidates("雪琴：8513-7 70*1.7", ["一群"]) == ["雪琴"]


def test_unknown_nickname_cancel_blocks_accounting(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("", False))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    app.clipboard().setText("2026/10/9\n员工01\n8513-7 70*1.7")
    window.import_clipboard_text()
    assert window.table.rowCount() == 0
    assert window.unresolved_warnings
    assert "需人工核对" in window.statusBar().currentMessage()
    assert window.bindings.resolve("一群", "员工01") is None
    window.close()


def test_batch_copy_two_confirmed_senders_use_distinct_employee_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    window.bindings.bind("一群", "雪琴", "E02")
    window.bindings.bind("一群", "小李", "E03")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (_ for _ in ()).throw(AssertionError("已绑定昵称不应弹窗")))
    app.clipboard().setText("2026/10/9 09:30 雪琴\n8513-7 70*1.7\n2026/10/9 10:30 小李\n计时3.5")
    window.import_clipboard_text()
    assert [record.employee_id for record in window.reviewed_records()] == ["E02", "E03"]
    assert not window.unresolved_warnings
    window.close()


def test_similar_nickname_is_not_auto_bound(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    window.bindings.bind("一群", "雪琴", "E02")
    prompts = []
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (prompts.append(args) or "", False))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    app.clipboard().setText("2026/10/9\n雪芹\n8513-7 70*1.7")
    window.import_clipboard_text()
    assert len(prompts) == 1
    assert window.table.rowCount() == 0
    assert window.unresolved_warnings
    assert window.bindings.resolve("一群", "雪芹") is None
    window.close()


def test_same_nickname_in_two_groups_uses_selected_group(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群", "二群"]
    window.group_combo.addItems(window.groups)
    window.group_combo.setCurrentText("二群")
    window.bindings.bind("一群", "雪琴", "E01")
    window.bindings.bind("二群", "雪琴", "E02")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (_ for _ in ()).throw(AssertionError("已绑定昵称不应弹窗")))
    app.clipboard().setText("2026/10/9\n雪琴\n8513-7 70*1.7")
    window.import_clipboard_text()
    assert window.reviewed_records()[0].employee_id == "E02"
    window.close()


def test_actual_roster_requires_explicit_first_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    prompts = []

    def choose(parent, title, label, options, current, editable):
        prompts.append(options)
        return "AM-1003  雪琴", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    app.clipboard().setText("2026/10/9\n雪琴\n8513-7 70*1.7\n计时3.5")
    window.import_clipboard_text()
    assert len(prompts) == 1
    assert len(prompts[0]) == 18  # 首项为必须跳过的“请选择员工”
    assert [record.employee_id for record in window.reviewed_records()] == ["AM-1003", "AM-1003"]
    assert window.total_label.text() == "总计：171.50元"
    window.close()


def test_unknown_sender_after_known_sender_never_inherits_identity(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module, "load_builtin_roster", roster)
    app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    window.bindings.bind("一群", "雪琴", "E02")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("", False))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    app.clipboard().setText("2026/10/9\n雪琴\n8513-7 70*1.7\n陌生人\n8510-1 20*2")
    window.import_clipboard_text()
    records = window.reviewed_records()
    assert len(records) == 1
    assert records[0].employee_id == "E02"
    assert records[0].item_code == "8513-7"
    assert window.unresolved_warnings
    window.close()


def test_screenshot_ocr_uses_confirmed_binding_after_window_restart(monkeypatch, tmp_path):
    from PySide6.QtGui import QImage
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])

    class ScreenshotOcr:
        def recognize(self, image):
            return "2026/10/9\n雪琴\n8513-7 70*1.7\n计时3.5"

    first = app_module.MainWindow(ocr=ScreenshotOcr())
    first.groups = ["一群"]
    first.group_combo.addItem("一群")
    first.bindings.bind("一群", "雪琴", "AM-1003")
    first.close()

    second = app_module.MainWindow(ocr=ScreenshotOcr())
    second.groups = ["一群"]
    second.group_combo.addItem("一群")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (_ for _ in ()).throw(AssertionError("已绑定昵称不应弹窗")))
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    second.paste_image()
    assert [record.employee_id for record in second.reviewed_records()] == ["AM-1003", "AM-1003"]
    assert second.total_label.text() == "总计：171.50元"
    second.close()
