"""截图粘贴、OCR、规则解析、人工核对与模拟账本窗口。"""
import sys
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from PIL import Image
from .catalog import ItemCatalog, normalize_code
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog, QListWidget,
    QListWidgetItem, QTextEdit)
from .models import Employee, WorkKind, WorkRecord
from .bindings import BindingConflict, NicknameBindingStore
from .binding_dialog import BindingDialog
from .roster import load_builtin_roster, save_private_roster
from .roster_dialog import RosterDialog
from .wechat_text import nickname_candidates
from .message_view import split_messages, message_for_line
from .employees import EmployeeDirectory
from .ocr import TesseractOcr
from .parser import DATE, parse_messages, record_key
from .payroll import calculate_amount
from .review_dialog import ReviewDialog
from .settings import directory_from_settings, load_settings, save_settings
from .workbook import write_mock_workbook

HEADERS = ["日期", "员工编号", "姓名", "货号/项目", "数量/工时", "单价", "单项工资", "当日合计工资"]


class MainWindow(QMainWindow):
    def __init__(self, ocr=None):
        super().__init__()
        self.ocr = ocr or TesseractOcr()
        self.employees, self.groups = load_settings()
        self.bindings = NicknameBindingStore()
        self.roster = load_builtin_roster() or self.bindings.employees()
        if self.roster and len(self.roster) != 17:
            self.roster = []
        if self.roster:
            self.bindings.install_roster(self.roster)
            self.employees = [employee.name for employee in self.roster]
        self.employee_by_id = {employee.employee_id: employee for employee in self.roster}
        self.unresolved_warnings = []
        self.price_warnings = []
        self.catalog = ItemCatalog()
        self.saved_record_keys: set[tuple] = set()
        self.display_records: list[WorkRecord] = []
        self.review_overrides: dict[int, tuple[str, str, WorkRecord]] = {}
        self.message_blocks = []
        self.warning_entries: list[tuple[str, int | None, int | None]] = []
        self.needs_parse = False
        self.setWindowTitle("微信记工助手")
        self.resize(1050, 720)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.guide_label = QLabel()
        layout.addWidget(self.guide_label)
        self.update_guide()
        controls = QHBoxLayout()
        self.settings_button = QPushButton("设置员工和群")
        self.settings_button.clicked.connect(self.edit_settings)
        controls.addWidget(self.settings_button)
        self.roster_button = QPushButton("管理正式员工名册")
        self.roster_button.clicked.connect(self.manage_roster)
        controls.addWidget(self.roster_button)
        self.bindings_button = QPushButton("管理昵称绑定")
        self.bindings_button.clicked.connect(self.manage_bindings)
        controls.addWidget(self.bindings_button)
        self.catalog_button = QPushButton("管理货号/项目与默认价")
        self.catalog_button.clicked.connect(self.manage_catalog)
        controls.addWidget(self.catalog_button)
        self.group_combo = QComboBox()
        self.group_combo.addItems(self.groups)
        controls.addWidget(QLabel("当前微信群："))
        controls.addWidget(self.group_combo)
        layout.addLayout(controls)
        controls = QHBoxLayout()
        self.import_button = QPushButton("导入微信复制文字")
        self.import_button.clicked.connect(self.import_clipboard_text)
        controls.addWidget(self.import_button)
        self.parse_button = QPushButton("解析文字")
        self.parse_button.clicked.connect(self.parse_text)
        controls.addWidget(self.parse_button)
        self.review_button = QPushButton("核对疑似记工行")
        self.review_button.clicked.connect(self.review_ambiguous_line)
        controls.addWidget(self.review_button)
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
        layout.addWidget(QLabel("微信消息（编号和绑定姓名只用于显示，不修改原文）："))
        self.message_list = QListWidget()
        self.message_list.setMaximumHeight(115)
        self.message_list.itemClicked.connect(self.select_message_item)
        layout.addWidget(self.message_list)
        layout.addWidget(self.output)
        layout.addWidget(QLabel("待核对原文与货号候选："))
        self.review_list = QListWidget()
        self.review_list.setMaximumHeight(105)
        self.review_list.itemClicked.connect(self.select_review_item)
        layout.addWidget(self.review_list)
        self.review_notes = QPlainTextEdit()
        self.review_notes.setReadOnly(True)
        self.review_notes.setMaximumHeight(100)
        layout.addWidget(self.review_notes)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.itemChanged.connect(self.recompute_table)
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
        self.review_overrides.clear()

    def update_guide(self):
        if self.roster:
            self.guide_label.setText('先设置微信群；复制聊天文字后点导入，或选群后 Ctrl+V 粘贴截图。确认后仅能保存新模拟账本。')
        else:
            self.guide_label.setText('首次使用：点击「管理正式员工名册」，核对预填的17名员工姓名和工号并保存到本机；再设置微信群、绑定微信昵称。')

    def manage_roster(self) -> bool:
        existing = self.roster or self.bindings.employees()
        dialog = RosterDialog(existing, self.employees, self)
        if dialog.exec() != RosterDialog.DialogCode.Accepted:
            return False
        employees = dialog.employees()
        try:
            self.bindings.update_roster(employees)
            save_private_roster(employees)
            save_settings([employee.name for employee in employees], self.groups)
        except (BindingConflict, ValueError, OSError) as exc:
            QMessageBox.warning(self, '名册保存失败', str(exc))
            return False
        self.roster = employees
        self.employees = [employee.name for employee in employees]
        self.employee_by_id = {employee.employee_id: employee for employee in employees}
        self.table.setRowCount(0)
        self.display_records = []
        self.unresolved_warnings = []
        self.review_overrides.clear()
        self.needs_parse = True
        self.update_guide()
        self.statusBar().showMessage('17名正式员工已保存到本机；请核对微信群和昵称绑定')
        return True

    def ensure_roster(self) -> bool:
        if self.roster:
            return True
        answer = QMessageBox.question(self, '首次设置正式员工',
            '已有员工姓名会自动预填。请在软件中核对17名员工的正式工号和姓名，保存到本机后再导入。现在设置吗？')
        return answer == QMessageBox.StandardButton.Yes and self.manage_roster()

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
        self.display_records = []
        self.unresolved_warnings = []
        self.review_overrides.clear()

    def manage_bindings(self):
        if not self.ensure_roster():
            return
        BindingDialog(self.bindings, self.groups, self).exec()
        self.table.setRowCount(0)
        self.display_records = []
        self.review_overrides.clear()
        self.needs_parse = True

    def manage_catalog(self):
        action, ok = QInputDialog.getItem(self, "管理货号", "选择操作：",
                                         ["新增货号或工作项目/维护现行价", "更正本机新增货号或项目"], 0, False)
        if not ok:
            return
        if action == "更正本机新增货号或项目":
            if not self.catalog.additions:
                QMessageBox.information(self, "管理货号", "本机尚无新增货号")
                return
            old, ok = QInputDialog.getItem(self, "更正货号", "选择本机新增货号：",
                                           sorted(self.catalog.additions), 0, False)
            if not ok:
                return
            new, ok = QInputDialog.getText(self, "更正货号", "输入新的完整货号：")
            if ok:
                try:
                    self.catalog.rename_added_code(old, new)
                    self.needs_parse = True
                    self.statusBar().showMessage("货号已更正，请重新解析")
                except ValueError as exc:
                    QMessageBox.warning(self, "货号设置无效", str(exc))
            return
        code, ok = QInputDialog.getText(self, "管理货号/项目", "输入完整货号或工作项目：")
        if not ok or not code.strip():
            return
        try:
            code = normalize_code(code)
            if code not in self.catalog.codes:
                self.catalog.add_code(code)
            historical = self.catalog.historical_prices(code) or "无历史价格"
            current = self.catalog.default_price(code)
            price, ok = QInputDialog.getText(self, "已确认现行价",
                f"{code}；历史参考：{historical}\n现行默认价（留空仅保存货号）：",
                text=str(current) if current is not None else "")
            if ok and price.strip():
                self.catalog.set_default(code, Decimal(price.strip()))
            self.needs_parse = True
            self.statusBar().showMessage(f"货号 {code} 已保存到本机；请重新解析")
        except (ValueError, InvalidOperation) as exc:
            QMessageBox.warning(self, "货号设置无效", str(exc))

    def review_ambiguous_line(self):
        selected_item = self.review_list.currentItem()
        if selected_item is not None:
            entry = self.warning_entries[self.review_list.row(selected_item)]
            selected = entry[0]
        else:
            choices = [warning for warning in self.unresolved_warnings if '；原文：' in warning]
            if not choices:
                QMessageBox.information(self, '待核对内容', '当前没有可人工审核的记工行')
                return
            selected = choices[0]
        line_match = re.match(r'第(\d+)行', selected)
        if not line_match or '；原文：' not in selected:
            QMessageBox.warning(self, '无法核对', '该项目没有可定位的原文行')
            return
        line_number = int(line_match.group(1))
        source_lines = self.output.toPlainText().splitlines()
        if not 1 <= line_number <= len(source_lines):
            QMessageBox.warning(self, '无法核对', '原文行号已变化，请重新解析')
            return
        original = source_lines[line_number - 1]
        candidates = self.catalog.candidates(original)
        group = self.group_combo.currentText()
        block = next((b for b in self.message_blocks if b.start_line <= line_number <= b.end_line), None)
        nickname = block.nickname if block else None
        employee_id = self.bindings.resolve(group, nickname) if group and nickname else None
        employee = self.employee_by_id.get(employee_id) if employee_id else None
        dates = list(DATE.finditer('\n'.join(source_lines[:line_number])))
        work_date = None
        if dates:
            last = dates[-1]
            try:
                work_date = date(int(last['year']), int(last['month']), int(last['day']))
            except ValueError:
                pass

        def confirm(values):
            kind, code, quantity, price, hours, note = values
            if re.search(r'\d+(?:\.\d+)?\s*[＊*×✘xX]\s*\d', original) and re.search(r'计时|工时|计\s*\d|\d+(?:\.\d+)?\s*小时', original):
                return '原文同一行包含计件和计时；请先拆成两行再解析，避免漏记'
            if not group:
                return '请先选择微信群'
            if employee is None:
                return '员工未绑定；请先确认微信昵称与正式员工的绑定'
            if work_date is None:
                return '缺少有效工作日期'
            if kind == WorkKind.PIECE and not (re.fullmatch(r'\d{4}(?:-\d)?', code) or code.strip()):
                return '请确认完整货号或工作项目'
            record = WorkRecord(employee.employee_id, work_date, kind, group, original,
                item_code=code if kind == WorkKind.PIECE else None,
                quantity=Decimal(quantity) if quantity else None,
                unit_price=Decimal(price) if price else None,
                hours=Decimal(hours) if hours else None, note=note or None,
                source_line=line_number, message_number=message_for_line(self.message_blocks, line_number))
            if any(record_key(other) == record_key(record) for other in self.reviewed_records()):
                return '疑似重复记录，请核对已有工资明细'
            self.review_overrides[line_number] = (original, group, record)
            self.parse_text()
            if any(warning.startswith(f'第{line_number}行') for warning in self.unresolved_warnings):
                self.review_overrides.pop(line_number, None)
                self.parse_text()
                return '本行仍需核对，人工确认未生效'
            return None

        dialog = ReviewDialog(original, message_for_line(self.message_blocks, line_number),
                              employee.name if employee else None,
                              work_date.strftime('%Y/%m/%d') if work_date else None,
                              candidates, confirm, self,
                              {code: self.catalog.default_price(code) for code in candidates
                               if self.catalog.default_price(code) is not None})
        dialog.exec()

    def import_clipboard_text(self):
        if not self.ensure_roster():
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
                line = next((i for i, value in enumerate(text.splitlines(), 1) if nickname in value), 1)
                warnings.append(f"第{line}行需人工核对：员工未绑定；微信昵称“{nickname}”在“{group}”中尚未确认，禁止保存")
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
        self.display_records = []
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
        if not self.ensure_roster():
            self.table.setRowCount(0)
            self.display_records = []
            self.unresolved_warnings = ['员工未绑定：请先在「管理正式员工名册」中完成首次设置']
            self.review_notes.setPlainText('\n'.join(self.unresolved_warnings))
            self.refresh_total()
            return
        if not self.employees or not self.groups:
            QMessageBox.warning(self, "缺少设置", "请先配置员工和微信群")
            return
        detected_groups = [g for g in self.groups if g in self.output.toPlainText()]
        if len(detected_groups) == 1:
            self.group_combo.setCurrentText(detected_groups[0])
        group = self.group_combo.currentText()
        source = self.output.toPlainText()
        self.message_blocks = split_messages(source, self.groups)
        identity_warnings = self.confirm_unknown_nicknames(group, source) if self.roster else []
        directory = self.resolved_directory(group) if self.roster else directory_from_settings(self.employees, self.groups)
        candidates = set(nickname_candidates(source, self.groups)) if self.roster else None
        result = parse_messages(source, directory, group, sender_hints=candidates)
        records = [replace(record, message_number=message_for_line(self.message_blocks, record.source_line))
                   for record in result.records]
        warnings = list(dict.fromkeys(identity_warnings + list(result.warnings)))
        source_lines = source.splitlines()
        for line, (original, override_group, record) in list(self.review_overrides.items()):
            if override_group != group or not 1 <= line <= len(source_lines) or source_lines[line - 1] != original:
                self.review_overrides.pop(line, None)
                continue
            warnings = [warning for warning in warnings
                        if not (warning.startswith(f'第{line}行') and '；原文：' in warning)]
            if any(record_key(other) == record_key(record) for other in records):
                warnings.append(f'第{line}行需人工核对：人工确认记录与其他记录重复；原文：{original}')
            else:
                records.append(record)
        self.unresolved_warnings = warnings
        self.price_warnings = list(result.price_warnings)
        for line, (_, override_group, record) in self.review_overrides.items():
            if override_group == group:
                default = self.catalog.default_price(record.item_code or '')
                if default is not None and record.unit_price != default:
                    self.price_warnings.append(
                        f'第{line}行 {record.item_code} 消息单价{record.unit_price}元，与已确认默认价{default}元不同；按消息单价计算，保存前须确认')
        self.needs_parse = False
        self.render_records(records)
        self.refresh_review_display()
        msg = f"识别 {len(records)} 条；需人工核对 {len(self.unresolved_warnings) + len(self.price_warnings)} 项"
        self.statusBar().showMessage(msg)
        if self.unresolved_warnings:
            QMessageBox.warning(self, "未解析的内容", "\n".join(self.unresolved_warnings))

    def refresh_review_display(self):
        self.warning_entries = []
        self.review_list.clear()
        display_lines = []
        for warning in self.unresolved_warnings + self.price_warnings:
            found = re.match(r'第(\d+)行', warning)
            line = int(found.group(1)) if found else None
            number = message_for_line(self.message_blocks, line)
            reason = re.sub(r'^第\d+行(?:需人工核对：)?', '', warning)
            label = f'第{number or 1}条消息｜原文第{line or 1}行｜{reason}'
            self.warning_entries.append((warning, line, number))
            item = QListWidgetItem(label)
            item.setToolTip(warning)
            self.review_list.addItem(item)
            display_lines.append(label)
        self.review_notes.setPlainText('\n'.join(display_lines))
        pending = {number for _, _, number in self.warning_entries}
        self.message_list.clear()
        for block in self.message_blocks:
            employee_id = self.bindings.resolve(self.group_combo.currentText(), block.nickname) if block.nickname else None
            employee = self.employee_by_id.get(employee_id) if employee_id else None
            identity = f'{block.nickname}（{employee.name}）' if employee else f'{block.nickname or "未知昵称"}（未绑定员工）'
            state = '待核对' if block.number in pending else '已核对'
            item = QListWidgetItem(f'第{block.number}条｜{identity}｜{state}')
            item.setData(Qt.ItemDataRole.UserRole, block.number)
            item.setToolTip(block.raw_text)
            self.message_list.addItem(item)

    def highlight_message(self, number: int | None):
        block = next((entry for entry in self.message_blocks if entry.number == number), None)
        if block is None:
            return
        document = self.output.document()
        first = document.findBlockByNumber(block.start_line - 1)
        last = document.findBlockByNumber(block.end_line - 1)
        if not first.isValid() or not last.isValid():
            return
        cursor = QTextCursor(document)
        cursor.setPosition(first.position())
        cursor.setPosition(last.position() + max(0, last.length() - 1), QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(QColor('#fff1a8'))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.output.setExtraSelections([selection])
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def select_message_item(self, item):
        self.highlight_message(item.data(Qt.ItemDataRole.UserRole))

    def select_review_item(self, item):
        index = self.review_list.row(item)
        if 0 <= index < len(self.warning_entries):
            self.highlight_message(self.warning_entries[index][2])

    def render_records(self, records: list[WorkRecord]):
        self.display_records = sorted(records, key=lambda record: (
            record.work_date, record.employee_id, record.source_line or 0, record.kind.value))
        self.table.blockSignals(True)
        self.table.clearSpans()
        self.table.setRowCount(len(self.display_records))
        for row, record in enumerate(self.display_records):
            employee = self.employee_by_id.get(record.employee_id)
            name = employee.name if employee else next((name for index, name in enumerate(self.employees, 1)
                if str(index) == record.employee_id), '')
            hourly = record.kind == WorkKind.HOURLY
            values = [f'{record.work_date.year}/{record.work_date.month}/{record.work_date.day}',
                      record.employee_id, name, '计时' if hourly else (record.item_code or ''),
                      str(record.hours or '') if hourly else str(record.quantity or ''),
                      '15.00' if hourly else str(record.unit_price or ''),
                      f'{calculate_amount(record):.2f}', '']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (6, 7):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.recompute_table()

    def add_record(self, record: WorkRecord):
        self.render_records([*self.display_records, record])

    def add_empty_record(self):
        self.display_records.append(WorkRecord('', date.today(), WorkKind.PIECE,
            self.group_combo.currentText(), self.output.toPlainText()))
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        values = [f'{date.today().year}/{date.today().month}/{date.today().day}', '', '', '', '', '', '', '']
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.recompute_table()

    def row_record(self, row: int) -> WorkRecord:
        value = lambda column: self.table.item(row, column).text().strip() if self.table.item(row, column) else ''
        base = self.display_records[row]
        date_parts = value(0).split('/')
        work_date = date(*map(int, date_parts)) if len(date_parts) == 3 else date.fromisoformat(value(0))
        employee_id = value(1)
        employee = self.employee_by_id.get(employee_id)
        if self.roster:
            if employee is None or employee.name != value(2):
                raise ValueError(f'第{row + 1}行工号与姓名不匹配')
        elif value(2) not in self.employees or employee_id != str(self.employees.index(value(2)) + 1):
            raise ValueError(f'第{row + 1}行工号与姓名不匹配')
        hourly = value(3) == '计时'
        if hourly:
            if value(5) != '15.00':
                raise ValueError(f'第{row + 1}行计时时薪必须为15.00元')
            return WorkRecord(employee_id, work_date, WorkKind.HOURLY, base.group_id,
                base.source_text, hours=Decimal(value(4)), note=base.note,
                source_line=base.source_line, message_number=base.message_number)
        return WorkRecord(employee_id, work_date, WorkKind.PIECE, base.group_id,
            base.source_text, value(3), Decimal(value(4)), Decimal(value(5)),
            note=base.note, source_line=base.source_line, message_number=base.message_number)

    def recompute_table(self, *_):
        self.table.blockSignals(True)
        try:
            self.table.clearSpans()
            calculated = []
            for row in range(self.table.rowCount()):
                try:
                    record = self.row_record(row)
                    amount = calculate_amount(record)
                    calculated.append((record.work_date, record.employee_id, amount))
                    value = f'{amount:.2f}'
                except (ValueError, InvalidOperation, IndexError):
                    calculated.append(None)
                    value = ''
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 6, item)
            grouped = {}
            for entry in calculated:
                if entry is not None:
                    key = entry[:2]
                    grouped[key] = grouped.get(key, Decimal('0')) + entry[2]
            row = 0
            while row < len(calculated):
                entry = calculated[row]
                if entry is None:
                    row += 1
                    continue
                key = entry[:2]
                end = row + 1
                while end < len(calculated) and calculated[end] is not None and calculated[end][:2] == key:
                    end += 1
                item = QTableWidgetItem(f'{grouped[key]:.2f}')
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 7, item)
                for clear_row in range(row + 1, end):
                    self.table.setItem(clear_row, 7, QTableWidgetItem(''))
                if end - row > 1:
                    self.table.setSpan(row, 7, end - row, 1)
                row = end
            if any(entry is None for entry in calculated):
                self.total_label.setText('总计：请核对未完成的记录')
            else:
                total = sum((entry[2] for entry in calculated), Decimal('0'))
                self.total_label.setText(f'总计：{total:.2f}元')
        finally:
            self.table.blockSignals(False)

    def refresh_total(self, *_):
        self.recompute_table()

    def reviewed_records(self) -> list[WorkRecord]:
        records = []
        for row in range(self.table.rowCount()):
            record = self.row_record(row)
            amount = calculate_amount(record)
            if self.table.item(row, 6).text() != f'{amount:.2f}':
                raise ValueError(f'第{row + 1}行单项工资应为 {amount:.2f} 元')
            records.append(record)
        return records

    def save_mock(self):
        try:
            if self.needs_parse:
                raise ValueError("OCR 原文已修改，请重新解析后核对表格")
            if self.unresolved_warnings:
                raise ValueError("仍有未解析行；请修改 OCR 原文并重新解析，或核对后在原文中移除无关行")
            records = self.reviewed_records()
            for record in records:
                default = self.catalog.default_price(record.item_code or "")
                if record.kind == WorkKind.PIECE and default is not None and record.unit_price != default:
                    detail = f"{record.item_code} 单价{record.unit_price}元，与已确认默认价{default}元不同；按填写价计算"
                    if detail not in self.price_warnings:
                        self.price_warnings.append(detail)
            if not records:
                raise ValueError("没有可保存的记录")
            keys = [record_key(record) for record in records]
            if len(keys) != len(set(keys)) or any(key in self.saved_record_keys for key in keys):
                raise ValueError("存在重复记录或本次运行中已保存的记录，请人工核对")
        except (ValueError, InvalidOperation) as exc:
            QMessageBox.warning(self, "核对失败", str(exc))
            return
        details = "\n".join(self.price_warnings)
        answer = QMessageBox.question(self, "确认记录", f"请确认 {len(records)} 条记录和工资均已核对。\n{details}\n只会新建模拟账本，继续吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "保存新模拟账本", "模拟工资账本.xlsx", "Excel (*.xlsx)")
        if not filename:
            return
        try:
            write_mock_workbook(Path(filename), records, confirmed=True,
                                employee_names={employee.employee_id: employee.name for employee in self.roster})
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
