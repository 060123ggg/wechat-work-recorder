import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from wechat_work_recorder.app import MainWindow


class ControlledOcr:
    def __init__(self):
        self.fail = False
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.fail:
            raise RuntimeError("OCR failed")
        return "2026-10-18 张三 一群 货号 8513-6 数量 2 单价 3"


@pytest.mark.parametrize("focused", ["output", "parse_button", "group_combo", "table"])
def test_real_ctrl_v_from_each_control(monkeypatch, tmp_path, focused):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    ocr = ControlledOcr()
    window = MainWindow(ocr=ocr)
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    window.show()
    app.processEvents()
    widget = getattr(window, focused)
    widget.setFocus()
    app.processEvents()
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    QTest.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert ocr.calls == 1
    assert window.table.rowCount() == 1
    assert window.table.item(0, 4).text() == "8513-6"
    window.close()


def test_ocr_failure_clears_old_records(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    ocr = ControlledOcr()
    window = MainWindow(ocr=ocr)
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    window.paste_image()
    assert window.table.rowCount() == 1
    ocr.fail = True
    window.paste_image()
    assert window.table.rowCount() == 0
    assert not window.output.toPlainText()
    assert not window.reviewed_records()
    window.close()


def test_reimport_in_same_session_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ocr=ControlledOcr())
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    window.paste_image()
    from wechat_work_recorder.parser import record_key
    key = record_key(window.reviewed_records()[0])
    window.saved_record_keys.add(key)
    assert key in window.saved_record_keys
    window.paste_image()
    assert record_key(window.reviewed_records()[0]) in window.saved_record_keys
    window.close()


def test_reimport_rejected_by_save_flow(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ocr=ControlledOcr())
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    filenames = iter([str(tmp_path / "first.xlsx"), str(tmp_path / "second.xlsx")])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (next(filenames), ""))
    window.paste_image()
    window.save_mock()
    assert (tmp_path / "first.xlsx").exists()
    window.paste_image()
    window.save_mock()
    assert warnings and "重复" in warnings[-1]
    assert not (tmp_path / "second.xlsx").exists()
    window.close()


def test_editing_ocr_text_requires_reparse(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ocr=ControlledOcr())
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    window.paste_image()
    assert not window.needs_parse
    window.output.setPlainText("修改后的文本")
    assert window.needs_parse
    window.close()
