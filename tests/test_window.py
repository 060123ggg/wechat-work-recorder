import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from wechat_work_recorder.app import MainWindow


class FakeOcr:
    def recognize(self, image):
        assert image.size == (20, 20)
        return "2026-10-18 张三 一群 货号 WX-1 数量 2 单价 3"


def test_paste_image_parse_and_edit_amount(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ocr=FakeOcr())
    window.employees = ["张三"]
    window.groups = ["一群"]
    window.group_combo.addItem("一群")
    app.clipboard().setImage(QImage(20, 20, QImage.Format.Format_RGB32))
    window.paste_image()
    assert window.table.rowCount() == 1
    assert window.table.item(0, 8).text() == "6.00"
    window.table.item(0, 5).setText("4")
    assert window.table.item(0, 8).text() == "12.00"
    assert len(window.reviewed_records()) == 1
    window.close()
