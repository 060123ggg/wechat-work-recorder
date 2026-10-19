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
from .models import Employee, WorkKind, WorkRecord
from .bindings import BindingConflict, NicknameBindingStore
from .binding_dialog import BindingDialog
from .roster import load_builtin_roster
from .wechat_text import nickname_candidates
from .employees import EmployeeDirectory
from .ocr import TesseractOcr
from .parser import parse_messages, record_key
from .payroll import calculate_amount
from .settings import directory_from_settings, load_settings, save_settings
from .workbook import write_mock_workbook
from .wps_clipboard import to_wps_tsv

HEADERS = ["员工", "日期", "群", "类型(piece/hourly)", "完整货号", "数量", "单价", "工时", "工资"]


class MainWindow(QMainWindow):
    def __init__(self, ocr=None):
        super().__init__()
        self.ocr = ocr or TesseractOcr()
        self.employees, self.groups = load_settings()
        self.roster = load_builtin_roster()
        self.bindings = NicknameBindingStore()
        if self.roster:
            self.bindings.install_roster(self.roster)
            self.employees = [employee.name for employee in self.roster]
        self.employee_by_id = {employee.employee_id: employee for employee in self.roster}
        self.unresolved_warnings = []
        self.saved_record_keys: set[tuple] = set()
        self.needs_parse = False
        self.setWindowTitle("微信记工助手")
        self.resize(1050, 720)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("先设置微信群；复制聊天文字后点导入，或选群后 Ctrl+V 粘贴截图。确认后仅能保存新模拟账本。"))
        controls = QHBoxLayout()
        self.settings_button = QPushButton("设置员工和群")
        self.settings_button.clicked.connect(self.edit_settings)
        controls.addWidget(self.settings_button)
        self.bindings_button = QPushButton("管理昵称绑定")
        self.bindings_button.clicked.connect(self.manage_bindings)
        controls.addWidget(self.bindings_button)
        self.import_button = QPushButton("导入微信复制文字")
        self.import_button.clicked.connect(self.import_clipboard_text)
        controls.addWidget(self.import_button)
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
        self.copy_wps_button = QPushButton("复制到 WPS（B:J）")
        self.copy_wps_button.clicked.connect(self.copy_to_wps)
        controls.addWidget(self.copy_wps_button)
        layout.addLayout(controls)
        self.output = QPlainTextEdit()
        self.output.textChanged.connect(self.on_text_changed)
        self.output.setPlaceholderText("在此粘贴聊天文字，或粘贴截图自动 OCR……")
        layout.addWidget(self.output)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.itemChanged.connect(self.update_amount)
        self.table.itemChanged.connect(self.refresh_total)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.total_label = QLabel("总计：0.00元")
        layout.addWidget(self.total_label)
        self.setCentralWidget(panel)
        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.bindings.close()
        super().closeEvent(event)

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
        if self.roster:
            names = "\n".join(self.employees)
        else:
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

    def manage_bindings(self):
        if not self.roster:
            QMessageBox.warning(self, "缺少正式名册", "尚未内置17名员工的正式工号和姓名，不能建立可信绑定")
            return
        BindingDialog(self.bindings, self.groups, self).exec()
        self.table.setRowCount(0)
        self.needs_parse = True

    def import_clipboard_text(self):
        if not self.roster:
            QMessageBox.warning(self, "缺少正式名册", "尚未内置17名员工的正式工号和姓名，不能确认微信文字中的员工")
            return
        copied = QApplication.clipboard().text().strip()
        if not copied:
            QMessageBox.warning(self, "剪贴板为空", "请先在微信中复制聊天文字")
            return
        self.output.setPlainText(copied)
        self.parse_text()

    def resolved_directory(self, group: str) -> EmployeeDirectory:
        aliases: dict[str, list[str]] = {}
        for bound_group, nickname, employee_id, _ in self.bindings.list_bindings():
            if bound_group == group:
                aliases.setdefault(employee_id, []).append(nickname)
        return EmployeeDirectory([Employee(employee_id, names[0], tuple(names[1:]))
                                  for employee_id, names in aliases.items()], [group])

    def confirm_unknown_nicknames(self, group: str, text: str) -> list[str]:
        warnings = []
        for nickname in nickname_candidates(text, self.groups):
            if self.bindings.resolve(group, nickname):
                continue
            options = ["请选择员工…"] + [f"{employee.employee_id}  {employee.name}" for employee in self.roster]
            choice, ok = QInputDialog.getItem(self, "确认微信昵称", f"“{nickname}”在“{group}”中尚未绑定。请选择员工：", options, 0, False)
            if not ok or not choice or choice == options[0]:
                warnings.append(f"昵称“{nickname}”未确认员工，禁止保存")
                continue
            employee_id = self.roster[options.index(choice) - 1].employee_id
            try:
                self.bindings.bind(group, nickname, employee_id)
            except BindingConflict as exc:
                warnings.append(f"昵称“{nickname}”绑定冲突：{exc}")
        return warnings

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
        self.refresh_total()
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
        group = self.group_combo.currentText()
        identity_warnings = self.confirm_unknown_nicknames(group, self.output.toPlainText()) if self.roster else []
        directory = self.resolved_directory(group) if self.roster else directory_from_settings(self.employees, self.groups)
        candidates = set(nickname_candidates(self.output.toPlainText(), self.groups)) if self.roster else None
        result = parse_messages(self.output.toPlainText(), directory, group, sender_hints=candidates)
        self.unresolved_warnings = identity_warnings + list(result.warnings)
        self.needs_parse = False
        self.table.setRowCount(0)
        for record in result.records:
            self.add_record(record)
        self.refresh_total()
        msg = f"识别 {len(result.records)} 条；需人工核对 {len(self.unresolved_warnings)} 项"
        self.statusBar().showMessage(msg)
        if self.unresolved_warnings:
            QMessageBox.warning(self, "未解析的内容", "\n".join(self.unresolved_warnings))

    def add_record(self, record: WorkRecord):
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = (self.employee_by_id[record.employee_id].name if self.roster else
                next(e for e in self.employees if str(self.employees.index(e) + 1) == record.employee_id))
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

    def refresh_total(self, *_):
        try:
            amounts = [Decimal(self.table.item(row, 8).text()) for row in range(self.table.rowCount())]
            total = sum(amounts, Decimal("0"))
            self.total_label.setText(f"总计：{total:.2f}元")
        except (AttributeError, InvalidOperation):
            self.total_label.setText("总计：请核对未完成的记录")

    def reviewed_records(self) -> list[WorkRecord]:
        records = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text().strip() if self.table.item(row, col) else "" for col in range(9)]
            if values[0] not in self.employees or values[2] not in self.groups:
                raise ValueError(f"第{row + 1}行员工或群不在设置中")
            kind = WorkKind(values[3])
            employee_id = (next(e.employee_id for e in self.roster if e.name == values[0]) if self.roster
                           else str(self.employees.index(values[0]) + 1))
            record = WorkRecord(employee_id, date.fromisoformat(values[1]), kind,
                values[2], self.output.toPlainText(), values[4] or None,
                Decimal(values[5]) if values[5] else None,
                Decimal(values[6]) if values[6] else None,
                Decimal(values[7]) if values[7] else None)
            amount = calculate_amount(record)
            if values[8] != str(amount):
                raise ValueError(f"第{row + 1}行工资须为按规则计算的 {amount} 元")
            records.append(record)
        return records

    def copy_to_wps(self):
        try:
            if self.needs_parse or self.unresolved_warnings:
                raise ValueError("存在未重新解析或待核对的内容，暂不能复制")
            records = self.reviewed_records()
            keys = [record_key(record) for record in records]
            if len(keys) != len(set(keys)):
                raise ValueError("存在重复记录，请先核对")
            names = {employee.employee_id: employee.name for employee in self.roster}
            if not self.roster:
                names = {str(i + 1): name for i, name in enumerate(self.employees)}
            data = to_wps_tsv(records, names)
        except (ValueError, InvalidOperation) as exc:
            QMessageBox.warning(self, "复制失败", str(exc))
            return
        QApplication.clipboard().setText(data)
        QMessageBox.information(self, "已复制", f"已复制 {len(records)} 条记录。请在 WPS 对应月份空白行的 B 列单元格粘贴。\\n粘贴前请确认目标区域为空，且不包含合并单元格；不会自动写入 K 列小计。")

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
    try:
        window = MainWindow()
    except (BindingConflict, ValueError) as exc:
        QMessageBox.critical(None, "员工名册或绑定冲突", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
