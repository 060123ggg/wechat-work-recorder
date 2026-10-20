"""截图粘贴、OCR、规则解析、人工核对与模拟账本窗口。"""
import os
import sys
import re
import sqlite3
import traceback
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from PIL import Image
from . import __version__
from .catalog import ItemCatalog, normalize_code, valid_catalog_code
from .catalog_dialog import CatalogDialog, ProjectDialog
from .message_context import date_for_line
from .message_widgets import MessageEditor, ReviewList
from .import_history import ImportHistory
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
from .wps_clipboard import to_wps_segments

def unconfirmed_duplicates(records):
    seen = set()
    for record in records:
        key = record_key(record)
        if key in seen and not record.duplicate_confirmed:
            return True
        seen.add(key)
    return False


HEADERS = ["日期", "员工编号", "姓名", "货号/项目", "数量/工时", "单价", "单项工资", "当日合计工资"]


def duplicate_warning(warning):
    reason = re.sub(r'^第\d+行(?:需人工核对：)?', '', warning).split('；原文：', 1)[0]
    return reason.startswith(('疑似重复', '人工确认记录与其他记录重复'))


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
        self.copied_record_keys: set[tuple] = set()
        self.wps_copy_batch: tuple[tuple[tuple, ...], dict[str, str]] | None = None
        self.wps_copy_step = 0
        self.display_records: list[WorkRecord] = []
        self.review_overrides: dict[int, tuple[str, str, WorkRecord]] = {}
        self.duplicate_resolutions: dict[int, tuple[str, str, str]] = {}
        self.message_blocks = []
        self.message_employees = {}
        self.message_dates = {}
        self.parse_proposals = []
        self.new_project_prompts = set()
        self.import_history = ImportHistory()
        self.history_source = None
        self.price_approvals = set()
        self.confirmed_snapshot = None
        self.warning_entries: list[tuple[str, int | None, int | None]] = []
        self.needs_parse = False
        self.setWindowTitle(f"微信记工助手 {__version__}")
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
        wps_controls = QHBoxLayout()
        wps_controls.addWidget(QLabel("WPS 分列复制（同一首行依次粘贴）："))
        self.copy_wps_button = QPushButton("第1步：复制 B:D")
        self.copy_wps_button.clicked.connect(self.copy_to_wps)
        wps_controls.addWidget(self.copy_wps_button)
        self.copy_wps_f_button = QPushButton("第2步：复制 F")
        self.copy_wps_f_button.clicked.connect(self.copy_wps_f)
        wps_controls.addWidget(self.copy_wps_f_button)
        self.copy_wps_hi_button = QPushButton("第3步：复制 H:I")
        self.copy_wps_hi_button.clicked.connect(self.copy_wps_hi)
        wps_controls.addWidget(self.copy_wps_hi_button)
        layout.addLayout(wps_controls)
        self.output = MessageEditor()
        self.last_source = ''
        self.output.textChanged.connect(self.on_text_changed)
        self.output.setPlaceholderText("在此粘贴聊天文字，或粘贴截图自动 OCR……")
        layout.addWidget(QLabel("微信消息（编号和绑定姓名只用于显示，不修改原文）："))
        self.message_list = QListWidget()
        self.message_list.setMaximumHeight(115)
        self.message_list.itemClicked.connect(self.select_message_item)
        layout.addWidget(self.message_list)
        layout.addWidget(self.output)
        layout.addWidget(QLabel("待核对问题（按消息排列；点击定位原文并打开审核，取消可暂不处理）："))
        self.review_list = ReviewList()
        self.review_list.setMinimumHeight(100)
        self.review_list.setMaximumHeight(195)
        self.review_list.currentItemChanged.connect(lambda item, previous: self.select_review_item(item) if item else None)
        self.review_list.itemClicked.connect(self.activate_review_item)
        layout.addWidget(self.review_list)
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.itemChanged.connect(self.recompute_table)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.total_label = QLabel("总计：0.00元")
        layout.addWidget(self.total_label)
        self.setCentralWidget(panel)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
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
        source = self.output.toPlainText()
        if source == self.last_source:
            return  # Display formatting must not invalidate human approvals.
        self.last_source = source
        self.invalidate_review()

    def invalidate_review(self):
        self.needs_parse = True
        self.review_overrides.clear()
        self.duplicate_resolutions.clear()
        self.message_employees.clear()
        self.message_dates.clear()
        self.new_project_prompts.clear()
        self.history_source = None
        self.price_approvals.clear()
        self.confirmed_snapshot = None

    def on_group_changed(self, *_):
        self.invalidate_review()
        self.wps_copy_batch = None
        self.wps_copy_step = 0
        self.display_records = []
        self.table.setRowCount(0)
        self.message_blocks = []
        self.message_list.clear()
        self.review_list.clear()
        self.warning_entries = []
        self.output.setExtraSelections([])
        self.output.set_message_blocks([])
        self.parse_proposals = []
        self.unresolved_warnings = []
        self.price_warnings = []
        self.refresh_total()
        self.statusBar().showMessage('微信群已改变，请重新解析并核对员工身份')

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
        self.invalidate_review()
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
        self.invalidate_review()
        self.table.setRowCount(0)
        self.display_records = []
        self.review_overrides.clear()
        self.needs_parse = True

    def manage_catalog(self):
        action, ok = QInputDialog.getItem(self, "管理货号", "选择操作：",
                                         ["新增货号或工作项目/维护现行价", "更正本机新增货号或项目", "完整价格资料库/别名/导入十月价格"], 0, False)
        if not ok:
            return
        if action == "完整价格资料库/别名/导入十月价格":
            CatalogDialog(self.catalog, self).exec()
            self.statusBar().showMessage("本机资料库已更新；现有工资不变，新导入文字使用新标准价")
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
            historical = "；".join(f"{h['price']}元" for h in self.catalog.price_history(code)) or "尚未导入十月价格"
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
        # Qt slot exceptions otherwise only reach stderr (invisible in a GUI build).
        try:
            self.open_review()
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '审核无法打开', f'未保存本次审核。请重新解析后再试。\n原因：{exc}')

    def open_review(self):
        if self.needs_parse:
            QMessageBox.warning(self, '请先重新解析', '原文或设置已经改变，请先点击「解析文字」，再核对问题')
            return
        selected_item = self.review_list.currentItem()
        index = self.review_list.row(selected_item) if selected_item else -1
        if 0 <= index < len(self.warning_entries):
            selected = self.warning_entries[index][0]
        else:
            selected = next((warning for warning in self.unresolved_warnings + self.price_warnings if '；原文：' in warning), None)
        line_match = re.match(r'第(\d+)行', selected or '')
        if not line_match:
            QMessageBox.warning(self, '无法核对', '请选择带原文的工作项目；员工问题也可通过昵称绑定管理处理')
            return
        line_number = int(line_match[1])
        if '；原文：' not in selected:
            number = message_for_line(self.message_blocks, line_number)
            # An unbound sender warning points at the header, not the work row.
            related = next((entry for entry in self.warning_entries
                            if entry[2] == number and '；原文：' in entry[0]), None)
            if related:
                selected, line_number, _ = related
            else:
                QMessageBox.warning(self, '无法核对', '本项没有工作原文，请在「管理正式员工名册」或「管理昵称绑定」处理')
                return
        source = self.output.toPlainText()
        source_lines = source.splitlines()
        if not 1 <= line_number <= len(source_lines):
            QMessageBox.warning(self, '无法核对', '原文行号已变化，请重新解析')
            return
        original = source_lines[line_number - 1]
        is_duplicate = duplicate_warning(selected)
        block = next((b for b in self.message_blocks if b.start_line <= line_number <= b.end_line), None)
        group = self.group_combo.currentText()
        nickname = block.nickname if block else None
        employee_id = self.bindings.resolve(group, nickname) if group and nickname else self.message_employees.get(block.number if block else 0)
        employee = self.employee_by_id.get(employee_id)
        try:
            work_date = self.message_dates.get(block.number) or date_for_line(block, line_number) if block else None
        except ValueError:
            work_date = None
        candidate_record = next((record for record in self.parse_proposals + self.display_records
                                 if record.source_line == line_number), None)
        candidates = self.catalog.candidates(original)
        if candidate_record and candidate_record.item_code:
            candidates = list(dict.fromkeys([candidate_record.item_code, *candidates]))

        def multiple_projects():
            related = [r for r in self.parse_proposals + self.display_records if r.source_line == line_number]
            return (len({(r.kind, r.item_code, r.quantity, r.hours) for r in related}) > 1 or
                    bool(re.search(r'\d{4}.*[＊*×✘xX]', original) and re.search(r'计时|工时|计\s*\d', original)))

        def resolve_duplicate(action):
            if multiple_projects():
                return '同一原文行包含多个工作项目，请先拆成两行再解析，避免忽略其他工作'
            if self.output.toPlainText() != source or self.group_combo.currentText() != group:
                return '原文或群已变化，请取消后重新解析'
            try:
                self.import_history.audit_review(dict(action=action, source_text=original,
                    message_number=block.number if block else None, source_line=line_number,
                    group=group, reason=selected))
            except (OSError, sqlite3.Error) as exc:
                return f'无法保存本机审核说明，尚未忽略本项：{exc}'
            self.duplicate_resolutions[line_number] = (original, group, action)
            self.parse_text()
            if any(warning.startswith(f'第{line_number}行') and duplicate_warning(warning) for warning in self.unresolved_warnings):
                self.duplicate_resolutions.pop(line_number, None)
                return '本项仍有重复问题，处理未生效，请重新核对'
            return None

        def confirm(values):
            kind, code, quantity, price, hours, note = values
            if multiple_projects():
                return '原文同一行包含多个工作项目；请先拆成两行再解析，避免审核时漏记'
            if self.output.toPlainText() != source or self.group_combo.currentText() != group:
                return '原文或群已变化，请取消后重新解析'
            if not group or block is None:
                return '请先选择微信群并重新解析消息'
            chosen = self.employee_by_id.get(dialog.employee_choice.currentData())
            if chosen is None:
                return '员工未绑定或发送人待确认；请在本窗口选择正式员工'
            try:
                confirmed_date = date(*map(int, re.split(r'[-/]', dialog.work_date.text().strip())))
            except (ValueError, TypeError):
                return '请填写有效工作日期 YYYY/M/D'
            if kind == WorkKind.PIECE:
                code = self.catalog.canonical(code)
                if code not in self.catalog.codes:
                    answer = QMessageBox.question(self, '确认新增项目',
                        f'将 {code} 新增到本机资料库，并将 {price} 元确认为标准价。继续吗？')
                    if answer != QMessageBox.StandardButton.Yes:
                        return '新增项目尚未确认'
                    try:
                        self.catalog.update_item(code, Decimal(price))
                    except (ValueError, InvalidOperation) as exc:
                        return str(exc)
            record = WorkRecord(chosen.employee_id, confirmed_date, kind, group, original,
                item_code=code if kind == WorkKind.PIECE else None,
                quantity=Decimal(quantity) if quantity else None, unit_price=Decimal(price) if price else None,
                hours=Decimal(hours) if hours else None,
                note=(note or (candidate_record.note if candidate_record else None)),
                source_line=line_number, message_number=block.number,
                quantity_unit=(candidate_record.quantity_unit if candidate_record else None),
                price_source="人工确认", standard_price_snapshot=self.catalog.default_price(code) if kind == WorkKind.PIECE else Decimal("15"))
            calculate_amount(record)
            duplicates = [other for other in self.reviewed_records()
                          if other.source_line != line_number and record_key(other) == record_key(record)]
            if duplicates or is_duplicate:
                if not is_duplicate:
                    return '疑似重复记录，请核对已有工资明细'
                record = replace(record, duplicate_confirmed=True)
            if nickname:
                try:
                    self.bindings.bind(group, nickname, chosen.employee_id)
                except BindingConflict as exc:
                    return str(exc)
            self.message_employees[block.number] = chosen.employee_id
            if work_date is None:
                self.message_dates[block.number] = confirmed_date
            self.review_overrides[line_number] = (original, group, record)
            self.parse_text()
            if any(warning.startswith(f'第{line_number}行') for warning in self.unresolved_warnings):
                self.review_overrides.pop(line_number, None)
                self.parse_text()
                return '本行仍需核对，人工确认未生效，请查看具体原因'
            return None

        dialog = ReviewDialog(original, block.number if block else None,
                              employee.name if employee else None,
                              work_date.strftime('%Y/%m/%d') if work_date else None,
                              candidates, confirm, self,
                              {code: self.catalog.default_price(code) for code in candidates if self.catalog.default_price(code) is not None},
                              employees=self.roster, reason=selected,
                              price_options=[h['price'] for h in self.catalog.price_history(candidate_record.item_code)]
                              if candidate_record and candidate_record.kind == WorkKind.PIECE and
                              candidate_record.item_code and candidate_record.unit_price is None else (), catalog=self.catalog,
                              duplicate=is_duplicate, on_resolve_duplicate=resolve_duplicate,
                              message_text=block.raw_text if block else original)
        if candidate_record:
            dialog.prefill_record(candidate_record)
        dialog.exec()

    def import_clipboard_text(self):
        if not self.ensure_roster():
            return
        copied = QApplication.clipboard().text().strip()
        if not copied:
            QMessageBox.warning(self, "剪贴板为空", "请先在微信中复制聊天文字")
            return
        self.invalidate_review()  # A new import is a new batch, even with identical text.
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
        self.invalidate_review()
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
            self.refresh_review_display()
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
        self.message_blocks = split_messages(source, self.groups,
            [name for employee in directory.employees for name in (employee.name, *employee.aliases)],
            self.catalog.recognition_names)
        candidates = set(nickname_candidates(source, self.groups)) if self.roster else None
        if self.confirmed_snapshot and self.confirmed_snapshot[:2] == (source, group):
            self.unresolved_warnings = []
            self.price_warnings = []
            self.render_records(list(self.confirmed_snapshot[2]))
            self.refresh_review_display()
            self.needs_parse = False
            self.statusBar().showMessage('已保留本批已确认工资；新标准价只用于新导入的文字')
            return
        result = parse_messages(source, directory, group, sender_hints=candidates, catalog=self.catalog,
                                identity_overrides=self.message_employees, date_overrides=self.message_dates)
        for proposal in result.proposals:
            code = proposal.item_code
            prompt_key = (source, group, code)
            if code and code not in self.catalog.codes and prompt_key not in self.new_project_prompts:
                self.new_project_prompts.add(prompt_key)
                ProjectDialog(self.catalog, code, proposal.unit_price, self,
                              original=proposal.source_text, new=True).exec()
        result = parse_messages(source, directory, group, sender_hints=candidates, catalog=self.catalog,
                                identity_overrides=self.message_employees, date_overrides=self.message_dates)
        self.parse_proposals = list(result.proposals)
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
            records = [other for other in records if other.source_line != line]
            if not record.duplicate_confirmed and any(record_key(other) == record_key(record) for other in records):
                warnings.append(f'第{line}行需人工核对：人工确认记录与其他记录重复；原文：{original}')
            else:
                records.append(record)
        if self.history_source != (source, group):
            retained = []
            for record in records:
                history = self.import_history.find(record)
                if history and not record.duplicate_confirmed:
                    self.parse_proposals.append(record)
                    warnings.append(f'第{record.source_line}行需人工核对：疑似重复记录，{history}；请确认是否独立工作；原文：{record.source_text}')
                else:
                    retained.append(record)
            records = retained
        for line, (original, resolution_group, _) in list(self.duplicate_resolutions.items()):
            if resolution_group != group or not 1 <= line <= len(source_lines) or source_lines[line - 1] != original:
                self.duplicate_resolutions.pop(line, None)
                continue
            warnings = [warning for warning in warnings
                        if not (warning.startswith(f'第{line}行') and duplicate_warning(warning))]
            records = [record for record in records if record.source_line != line]
        self.unresolved_warnings = warnings
        self.price_warnings = [warning for warning in result.price_warnings
                               if not any(warning.startswith(f'第{line}行') for line in self.review_overrides)
                               and not any(warning.startswith(f'第{line}行') for line in self.duplicate_resolutions)
                               and not any(warning.startswith(f'第{r.source_line}行') and
                                           (r.source_line, record_key(r)) in self.price_approvals for r in records)]
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
        self.output.set_message_blocks(self.message_blocks)
        issues = []
        for warning in self.unresolved_warnings + self.price_warnings:
            found = re.match(r'第(\d+)行', warning)
            line = int(found.group(1)) if found else None
            number = message_for_line(self.message_blocks, line)
            issues.append((warning, line, number))
        for warning, line, number in sorted(issues, key=lambda entry: (entry[2] or 0, entry[1] or 0)):
            block = next((b for b in self.message_blocks if b.number == number), None)
            employee_id = (self.bindings.resolve(self.group_combo.currentText(), block.nickname)
                           if block and block.nickname else self.message_employees.get(number))
            employee = self.employee_by_id.get(employee_id)
            identity = f'{block.nickname or "人工确认发送人"}（{employee.name}）' if block and employee else f'{block.nickname if block else "发送人待确认"}（未绑定员工）'
            try:
                work_date = self.message_dates.get(number) or (date_for_line(block, line) if block and line else None)
            except ValueError:
                work_date = None
            date_label = str(work_date) if work_date else '日期待确认'
            reason = re.sub(r'^第\d+行(?:需人工核对：)?', '', warning)
            label = f'第{number or 1}条消息｜原文第{line or 1}行｜{identity}｜{date_label}\n{reason}'
            self.warning_entries.append((warning, line, number))
            item = QListWidgetItem(label)
            item.setToolTip(warning)
            item.setBackground(QColor('#f0f7f3' if (number or 1) % 2 else '#f5f5f5'))
            self.review_list.addItem(item)
        pending = {number for _, _, number in self.warning_entries}
        self.message_list.clear()
        for block in self.message_blocks:
            employee_id = self.bindings.resolve(self.group_combo.currentText(), block.nickname) if block.nickname else self.message_employees.get(block.number)
            employee = self.employee_by_id.get(employee_id) if employee_id else None
            identity = f'{block.nickname or "人工确认发送人"}（{employee.name}）' if employee else f'{block.nickname or "发送人待确认"}（未绑定员工）'
            state = '待核对' if block.number in pending else '已核对'
            item = QListWidgetItem(f'第{block.number}条｜{identity}｜{state}')
            item.setData(Qt.ItemDataRole.UserRole, block.number)
            item.setToolTip(block.raw_text)
            self.message_list.addItem(item)

    def highlight_message(self, number: int | None, line: int | None = None):
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
        selections = [selection]
        target = document.findBlockByNumber((line or block.start_line) - 1)
        focus = QTextCursor(target)
        if line:
            focus.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            focus.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
            issue_selection = QTextEdit.ExtraSelection()
            issue_selection.cursor = focus
            issue_selection.format.setBackground(QColor('#ffd38a'))
            issue_selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selections.append(issue_selection)
        self.output.setExtraSelections(selections)
        # Keep the active cursor at the target, not at the end of a long message.
        self.output.setTextCursor(focus)
        self.output.ensureCursorVisible()

    def select_message_item(self, item):
        self.highlight_message(item.data(Qt.ItemDataRole.UserRole))

    def select_review_item(self, item):
        index = self.review_list.row(item)
        if 0 <= index < len(self.warning_entries):
            _, line, number = self.warning_entries[index]
            self.highlight_message(number, line)
            for row in range(self.message_list.count()):
                if self.message_list.item(row).data(Qt.ItemDataRole.UserRole) == number:
                    self.message_list.setCurrentRow(row)
                    self.message_list.scrollToItem(self.message_list.item(row))
                    break

    def activate_review_item(self, item):
        self.select_review_item(item)
        self.review_ambiguous_line()

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
            record = replace(base, employee_id=employee_id, work_date=work_date, kind=WorkKind.HOURLY,
                             item_code=None, quantity=None, unit_price=None, hours=Decimal(value(4)))
        else:
            record = replace(base, employee_id=employee_id, work_date=work_date, kind=WorkKind.PIECE,
                             item_code=value(3), quantity=Decimal(value(4)), unit_price=Decimal(value(5)), hours=None)
        if record_key(record) != record_key(base):
            record = replace(record, duplicate_confirmed=False, price_source='表格人工修改')
        return record

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

    def copy_to_wps(self):
        try:
            if self.needs_parse or self.unresolved_warnings:
                raise ValueError('原文未重新解析或仍有待核对内容，暂不能复制')
            if not self.roster:
                raise ValueError('缺少已确认的正式员工名册，不能复制到 WPS')
            records = self.reviewed_records()
            keys = [record_key(record) for record in records]
            if unconfirmed_duplicates(records):
                raise ValueError('存在重复记录，请先核对')
            already_copied = [key in self.copied_record_keys for key in keys]
            if (any(already_copied) and not all(already_copied)
                    and any(copied and not record.duplicate_confirmed for copied, record in zip(already_copied, records))):
                raise ValueError('本批记录有部分已复制；请核对目标行，避免重复粘贴')
            names = {employee.employee_id: employee.name for employee in self.roster}
            if any(record.kind == WorkKind.PIECE and valid_catalog_code(record.item_code or '')
                   and record.item_code not in self.catalog.codes for record in records):
                raise ValueError('存在未确认的新增项目，请先加入本机价格资料库')
            segments = to_wps_segments(records, names)
        except (ValueError, InvalidOperation) as exc:
            QMessageBox.warning(self, '复制失败', str(exc))
            return
        if all(already_copied):
            again = QMessageBox.question(self, '确认重新复制',
                '这些记录本次运行已复制过。仅用于核对或测试时才重新复制；请先检查 WPS 目标行，避免重复粘贴。继续吗？')
            if again != QMessageBox.StandardButton.Yes:
                return
        differences = [f'{record.item_code} 当前标准价{default}元，填写价{record.unit_price}元，数量{record.quantity}，本次金额{calculate_amount(record):.2f}元'
                       for record in records if record.kind == WorkKind.PIECE
                       if (default := self.catalog.default_price(record.item_code or '')) is not None
                       and record.unit_price != default]
        differences += self.price_warnings
        detail = ('\n单价差异或标准价待确认：' + '；'.join(differences)) if differences else ''
        answer = QMessageBox.question(self, '确认复制到 WPS',
            f'请核对这 {len(records)} 条记录的员工、日期、项目、数量、单价和工资。{detail}\n'
            '将在同一批行分三步粘贴 B:D、F、H:I，不复制 E、G、J、K。'
            '先在账本副本检查 J 列工资公式、K 列布局，并把 F 列目标单元格设为“文本”，防止 8513-7 被识别成日期。'
            '若 J 列缺少公式，请先在副本中补齐并核对；软件不会代填。确认开始吗？')
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.price_approvals.update((r.source_line, record_key(r)) for r in records)
        self.price_warnings = []
        self.refresh_review_display()
        self.statusBar().showMessage(f'识别 {len(records)} 条；需人工核对 0 项')
        self.wps_copy_batch = (tuple(keys), segments)
        self.wps_copy_step = 1
        QApplication.clipboard().setText(segments['B:D'])
        QMessageBox.information(self, '第1步：B:D',
            '请在 WPS 副本目标首行的 B 列粘贴日期、工号和姓名；然后返回软件点“第2步：复制 F”。')

    def copy_wps_f(self):
        self.copy_wps_segment('F', 1)

    def copy_wps_hi(self):
        self.copy_wps_segment('H:I', 2)

    def copy_wps_segment(self, column: str, expected_step: int):
        if self.wps_copy_batch is None or self.wps_copy_step != expected_step:
            QMessageBox.warning(self, '复制顺序错误', '请先完成前一步的复制和粘贴')
            return
        try:
            if self.needs_parse or self.unresolved_warnings:
                raise ValueError('原文已改变或出现待核对内容，请重新开始复制')
            keys = tuple(record_key(record) for record in self.reviewed_records())
            if keys != self.wps_copy_batch[0]:
                raise ValueError('工资明细已改变，请重新开始复制并核对目标行')
        except (ValueError, InvalidOperation) as exc:
            self.wps_copy_batch = None
            self.wps_copy_step = 0
            QMessageBox.warning(self, '复制失败', str(exc))
            return
        QApplication.clipboard().setText(self.wps_copy_batch[1][column])
        self.wps_copy_step += 1
        if column == 'F':
            QMessageBox.information(self, '第2步：F',
                '先确认 WPS 目标 F 列已设为文本，再在同一首行的 F 列粘贴货号/计时；然后点“第3步：复制 H:I”。')
        else:
            self.copied_record_keys.update(keys)
            self.import_history.remember(self.reviewed_records())
            self.history_source = (self.output.toPlainText(), self.group_combo.currentText())
            self.confirmed_snapshot = (*self.history_source, tuple(self.reviewed_records()))
            self.wps_copy_batch = None
            self.wps_copy_step = 0
            QMessageBox.information(self, '第3步：H:I',
                '请在同一首行的 H 列粘贴数量/工时和单价，并核对 J 列原公式计算的工资及 K 列布局。')

    def save_mock(self):
        try:
            if self.needs_parse:
                raise ValueError("OCR 原文已修改，请重新解析后核对表格")
            if self.unresolved_warnings:
                raise ValueError("仍有未解析行或疑似重复；请在人工审核中逐项确认后再保存")
            records = self.reviewed_records()
            for record in records:
                if record.kind == WorkKind.PIECE and valid_catalog_code(record.item_code or '') and record.item_code not in self.catalog.codes:
                    raise ValueError('存在未确认的新增项目，请先加入本机价格资料库')
                default = self.catalog.default_price(record.item_code or "")
                if record.kind == WorkKind.PIECE and default is not None and record.unit_price != default:
                    detail = f"{record.item_code} 单价{record.unit_price}元，与已确认默认价{default}元不同；按填写价计算"
                    if detail not in self.price_warnings:
                        self.price_warnings.append(detail)
            if not records:
                raise ValueError("没有可保存的记录")
            keys = [record_key(record) for record in records]
            if unconfirmed_duplicates(records) or any(record_key(r) in self.saved_record_keys and not r.duplicate_confirmed for r in records):
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
            self.import_history.remember(records, output="模拟账本")
            self.history_source = (self.output.toPlainText(), self.group_combo.currentText())
            self.confirmed_snapshot = (*self.history_source, tuple(self.reviewed_records()))
            self.statusBar().showMessage(f"已保存模拟账本：{filename}", 10000)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))


def main() -> int:
    smoke_test = "--packaging-smoke-test" in sys.argv
    app = QApplication([sys.argv[0]] if smoke_test else sys.argv)
    try:
        window = MainWindow()
    except (BindingConflict, ValueError) as exc:
        QMessageBox.critical(None, "员工名册或绑定冲突", str(exc))
        return 1
    if smoke_test:
        # Windows CI 用实际打包后的 exe 验证界面、货号库和中文 OCR 均可加载。
        try:
            window.ocr.recognize(Image.new("RGB", (80, 40), "white"))
            languages = window.ocr.available_languages()
            ready = (window.catalog.codes and {"chi_sim", "eng"} <= languages
                     and window.copy_wps_button.text() and window.copy_wps_f_button.text()
                     and window.copy_wps_hi_button.text())
            detail = f"OCR languages: {sorted(languages)}; bundled command: {window.ocr.executable}"
        except Exception as exc:
            ready = False
            detail = f"Packaging smoke test error: {exc!r}"
        if report := os.environ.get("WECHAT_SMOKE_RESULT"):
            Path(report).write_text(detail, encoding="utf-8")
        window.close()
        return 0 if ready else 2
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
