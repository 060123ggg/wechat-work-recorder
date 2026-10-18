"""截图粘贴、OCR、规则解析、人工核对与模拟账本窗口。"""
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog)
from .models import WorkKind, WorkRecord
from .ocr import TesseractOcr
from .parser import parse_messages, record_key
from .payroll import calculate_amount
from .settings import directory_from_settings, load_settings, save_settings
from .workbook import write_mock_workbook

HEADERS = ["员工", "日期", "群", "类型(piece/hourly)", "完整货号", "数量", "单价", "工时", "工资"]


class MainWindow(QMainWindow):
    def __init__(self, ocr=None):
        super().__init__()
        self.ocr = ocr or TesseractOcr()
        self.employees, self.groups = load_settings()
        self.unresolved_warnings = []
        self.saved_record_keys: set[tuple] = set()
        self.needs_parse = False
        self.setWindowTitle("微信记工助手")
        self.resize(1050, 720)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("先配置员工和群；选群后 Ctrl+V 粘贴截图。OCR 原文与记录可修改，确认后仅能保存新模拟账本。"))
        controls = QHBoxLayout()
        self.settings_button = QPushButton("设置员工和群")
        self.settings_button.clicked.connect(self.edit_settings)
        controls.addWidget(self.settings_button)
        self.group_combo = QComboBox()
        self.group_combo.addItems(self.groups)
        controls.addWidget(QLabel("当前微信群："))
        controls.addWidget(self.group_combo)
        self.parse_button = QPushButton("解析文字")
        self.parse_button.clicked.connect(self.parse_text)
        controls.addWidget(self.parse_button)
        self.add_button = QPushButton("手工添加记录")
        self.add_button.clicked.connect(self.add_empty_record)
        controls.addWidget(self.add_button)
        self.save_button = QPushButton("确认并保存模拟账本")
        self.save_button.clicked.connect(self.save_mock)
        controls.addWidget(self.save_button)
        layout.addLayout(controls)
        self.output = QPlainTextEdit()
        self.output.textChanged.connect(self.on_text_changed)
        self.output.setPlaceholderText("在此粘贴聊天文字，或粘贴截图自动 OCR……")
        layout.addWidget(self.output)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.itemChanged.connect(self.update_amount)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.setCentralWidget(panel)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_V
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and QApplication.activeWindow() is self
                and not QApplication.clipboard().image().isNull()):
            self.paste_image()
            return True
        return super().eventFilter(watched, event)

    def on_text_changed(self):
        self.needs_parse = True

    def edit_settings(self):
        names, ok = QInputDialog.getMultiLineText(self, "员工姓名", "每行一名员工，最多17名：", "\n".join(self.employees))
        if not ok:
            return
        groups, ok = QInputDialog.getMultiLineText(self, "微信群", "每行一个群名，最多3个：", "\n".join(self.groups))
        if not ok:
            return
        try:
            employees = [x.strip() for x in names.splitlines() if x.strip()]
            group_names = [x.strip() for x in groups.splitlines() if x.strip()]
            save_settings(employees, group_names)
        except ValueError as exc:
            QMessageBox.warning(self, "设置无效", str(exc))
            return
        self.employees, self.groups = employees, group_names
        self.group_combo.clear()
        self.group_combo.addItems(self.groups)
        self.table.setRowCount(0)
        self.unresolved_warnings = []

    def paste_image(self):
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            widget = QApplication.focusWidget()
            if widget is self.output:
                self.output.paste()
            else:
                self.statusBar().showMessage("剪贴板中没有图片", 5000)
            return
        self.output.clear()
        self.table.setRowCount(0)
        self.unresolved_warnings = []
        image = image.convertToFormat(image.Format.Format_RGBA8888)
        pil_image = Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()))
        try:
            self.output.setPlainText(self.ocr.recognize(pil_image))
            self.parse_text()
        except Exception as exc:
            self.statusBar().showMessage(f"OCR 失败：{exc}")

    def parse_text(self):
        if not self.employees or not self.groups:
            QMessageBox.warning(self, "缺少设置", "请先配置员工和微信群")
            return
        detected_groups = [g for g in self.groups if g in self.output.toPlainText()]
        if len(detected_groups) == 1:
            self.group_combo.setCurrentText(detected_groups[0])
        result = parse_messages(self.output.toPlainText(), directory_from_settings(self.employees, self.groups), self.group_combo.currentText())
        self.unresolved_warnings = list(result.warnings)
        self.needs_parse = False
        self.table.setRowCount(0)
        for record in result.records:
            self.add_record(record)
        msg = f"识别 {len(result.records)} 条；需人工核对 {len(result.warnings)} 行"
        self.statusBar().showMessage(msg)
        if result.warnings:
            QMessageBox.warning(self, "未解析的内容", "\n".join(result.warnings))

    def add_record(self, record: WorkRecord):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = next(e for e in self.employees if str(self.employees.index(e) + 1) == record.employee_id)
        values = [name, record.work_date.isoformat(), record.group_id, record.kind.value,
                  record.item_code or "", str(record.quantity or ""), str(record.unit_price or ""),
                  str(record.hours or ""), str(calculate_amount(record))]
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def add_empty_record(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = ["", date.today().isoformat(), self.group_combo.currentText(), "piece", "", "", "", "", ""]
        for col, value in enumerate(values):
            self.table.setItem(row, col, QTableWidgetItem(value))

    def update_amount(self, item):
        if item.column() not in (3, 4, 5, 6, 7):
            return
        row = item.row()
        value = lambda col: self.table.item(row, col).text().strip() if self.table.item(row, col) else ""
        try:
            kind = WorkKind(value(3))
            record = WorkRecord("preview", date.today(), kind, "preview", "", value(4) or None,
                Decimal(value(5)) if value(5) else None,
                Decimal(value(6)) if value(6) else None,
                Decimal(value(7)) if value(7) else None)
            amount = str(calculate_amount(record))
        except (ValueError, InvalidOperation):
            amount = ""
        self.table.blockSignals(True)
        self.table.setItem(row, 8, QTableWidgetItem(amount))
        self.table.blockSignals(False)

    def reviewed_records(self) -> list[WorkRecord]:
        records = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text().strip() if self.table.item(row, col) else "" for col in range(9)]
            if values[0] not in self.employees or values[2] not in self.groups:
                raise ValueError(f"第{row + 1}行员工或群不在设置中")
            kind = WorkKind(values[3])
            record = WorkRecord(str(self.employees.index(values[0]) + 1), date.fromisoformat(values[1]), kind,
                values[2], self.output.toPlainText(), values[4] or None,
                Decimal(values[5]) if values[5] else None,
                Decimal(values[6]) if values[6] else None,
                Decimal(values[7]) if values[7] else None)
            amount = calculate_amount(record)
            if values[8] != str(amount):
                raise ValueError(f"第{row + 1}行工资须为按规则计算的 {amount} 元")
            records.append(record)
        return records

    def save_mock(self):
        try:
            if self.needs_parse:
                raise ValueError("OCR 原文已修改，请重新解析后核对表格")
            if self.unresolved_warnings:
                raise ValueError("仍有未解析行；请修改 OCR 原文并重新解析，或核对后在原文中移除无关行")
            records = self.reviewed_records()
            if not records:
                raise ValueError("没有可保存的记录")
            keys = [record_key(record) for record in records]
            if len(keys) != len(set(keys)) or any(key in self.saved_record_keys for key in keys):
                raise ValueError("存在重复记录或本次运行中已保存的记录，请人工核对")
        except (ValueError, InvalidOperation) as exc:
            QMessageBox.warning(self, "核对失败", str(exc))
            return
        answer = QMessageBox.question(self, "确认记录", f"请确认 {len(records)} 条记录和工资均已核对。只会新建模拟账本，继续吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "保存新模拟账本", "模拟工资账本.xlsx", "Excel (*.xlsx)")
        if not filename:
            return
        try:
            write_mock_workbook(Path(filename), records, confirmed=True)
            self.saved_record_keys.update(record_key(record) for record in records)
            self.statusBar().showMessage(f"已保存模拟账本：{filename}", 10000)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
