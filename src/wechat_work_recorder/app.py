"""可运行的粘贴入口；识别结果必须经过人工核对。"""
import sys
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget
from PIL import Image
from .ocr import TesseractOcr


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("微信记工助手")
        self.resize(760, 520)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("复制微信群聊天截图后按 Ctrl+V；下方显示本地 OCR 原文，录入前请人工核对。"))
        self.output = QPlainTextEdit()
        self.output.setPlaceholderText("等待粘贴截图……")
        layout.addWidget(self.output)
        self.setCentralWidget(panel)
        self.paste_shortcut = QShortcut(QKeySequence.Paste, self)
        self.paste_shortcut.activated.connect(self.paste_image)

    def paste_image(self):
        image = QApplication.clipboard().image()
        if image.isNull():
            self.statusBar().showMessage("剪贴板中没有图片", 5000)
            return
        image = image.convertToFormat(image.Format.Format_RGBA8888)
        pil_image = Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()))
        try:
            self.output.setPlainText(TesseractOcr().recognize(pil_image))
            self.statusBar().showMessage("识别完成，请核对原文")
        except Exception as exc:
            self.statusBar().showMessage(f"OCR 失败：{exc}")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
