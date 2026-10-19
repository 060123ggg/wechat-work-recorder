"""Single-window manual review; historical prices are never displayed or applied."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget)

from .catalog import normalize_code
from .models import WorkKind
from .payroll import HOURLY_RATE
from .parser import HOURLY_START, parse_hour_entry, piece_fields


def suggestions(original: str, candidates: list[str], catalog=None) -> tuple[str, str, str, str, str]:
    """Return a cautious code, quantity, price, hours, note preview."""
    code = candidates[0] if len(candidates) == 1 else ''
    quantity = price = hours = note = ''
    pair = re.search(r'(\d+(?:\.\d+)?)\s*[＊*×✘xX]\s*(\d+(?:\.\d+)?)', original)
    if pair:
        price = pair.group(2)
        quantity = pair.group(1)
        prefix = original[:pair.start(1)]
        if code and normalize_code(prefix).removeprefix(code).strip() not in ('', '-', '--', '~~'):
            quantity = ''
    if catalog is not None:
        try:
            parsed_code, qty, parsed_price, _, _ = piece_fields(original, catalog)
            code, quantity = parsed_code, str(qty)
            price = str(parsed_price) if parsed_price is not None else ''
        except ValueError:
            pass
    marker = HOURLY_START.search(original)
    if marker:
        try:
            parsed_hours, parsed_note = parse_hour_entry(original[marker.start():])
            hours, note = str(parsed_hours), parsed_note or ''
        except ValueError:
            pass
    return code, quantity, price, hours, note


class ReviewDialog(QDialog):
    def __init__(self, original: str, number: int | None, employee: str | None,
                 work_date: str | None, candidates: list[str], on_confirm, parent=None,
                 confirmed_defaults: dict[str, Decimal] | None = None,
                 employees=(), reason: str = '', price_options=(), catalog=None):
        super().__init__(parent)
        self.setWindowTitle('人工审核')
        self.setMinimumWidth(520)
        self.on_confirm = on_confirm
        self.confirmed_defaults = confirmed_defaults or {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'第{number or 1}条消息｜员工：{employee or "未绑定员工"}｜日期：{work_date or "缺少有效日期"}'))
        context = QFormLayout()
        self.employee_choice = QComboBox()
        self.employee_choice.addItem('发送人待确认：请选择正式员工', None)
        for person in employees:
            self.employee_choice.addItem(f'{person.employee_id}  {person.name}', person.employee_id)
            if person.name == employee:
                self.employee_choice.setCurrentIndex(self.employee_choice.count() - 1)
        self.work_date = QLineEdit(work_date or '')
        context.addRow('正式员工', self.employee_choice)
        context.addRow('工作日期 YYYY/M/D', self.work_date)
        layout.addLayout(context)
        if reason:
            issue = QLabel(reason.split('；原文：')[0])
            issue.setWordWrap(True)
            layout.addWidget(issue)
        layout.addWidget(QLabel('微信原文'))
        source = QLabel(original)
        source.setWordWrap(True)
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(source)
        self.kind = QComboBox()
        self.kind.addItems(['计件', '计时'])
        layout.addWidget(self.kind)
        code, quantity, price, hours, note = suggestions(original, candidates, catalog)
        self.piece_panel = QWidget()
        piece_layout = QFormLayout(self.piece_panel)
        self.code = QComboBox()
        self.code.setEditable(True)
        self.code.addItems(['', *candidates])
        self.code.setCurrentText(code)
        self.quantity = QLineEdit(quantity)
        self.price = QLineEdit(price or str(self.confirmed_defaults.get(code, '')))
        piece_layout.addRow('完整货号 / 工作项目', self.code)
        piece_layout.addRow('数量', self.quantity)
        piece_layout.addRow('单价（元）', self.price)
        self.price_options = QComboBox()
        self.price_options.addItem('请选择本次单价（不改变标准价）', '')
        for option in sorted(set(price_options), key=Decimal):
            self.price_options.addItem(str(option), str(option))
        self.price_options.currentIndexChanged.connect(
            lambda index: self.price.setText(self.price_options.itemData(index)) if index else None)
        if price_options:
            piece_layout.addRow('待确认单价候选', self.price_options)
        layout.addWidget(self.piece_panel)
        self.hour_panel = QWidget()
        hour_layout = QFormLayout(self.hour_panel)
        self.hours = QLineEdit(hours)
        self.note = QLineEdit(note)
        hour_layout.addRow('工时', self.hours)
        hour_layout.addRow('固定时薪', QLabel('15.00元/小时'))
        hour_layout.addRow('工作备注', self.note)
        layout.addWidget(self.hour_panel)
        self.amount = QLabel('本项工资：—')
        layout.addWidget(self.amount)
        buttons = QDialogButtonBox()
        self.confirm_button = buttons.addButton('确认并加入工资表', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        self.confirm_button.clicked.connect(self.confirm)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self.refresh_amount)
        self.code.currentTextChanged.connect(self.prefill_default)
        for field in (self.quantity, self.price, self.hours):
            field.textChanged.connect(self.refresh_amount)
        self.refresh_amount()
        if hours:
            self.kind.setCurrentIndex(1)

    def prefill_record(self, record):
        self.code.setCurrentText(record.item_code or '')
        self.quantity.setText(str(record.quantity) if record.quantity is not None else '')
        self.price.setText(str(record.unit_price) if record.unit_price is not None else '')
        self.hours.setText(str(record.hours) if record.hours is not None else '')
        self.note.setText(record.note or '')
        self.kind.setCurrentIndex(1 if record.kind == WorkKind.HOURLY else 0)

    def refresh_amount(self):
        hourly = self.kind.currentIndex() == 1
        self.piece_panel.setVisible(not hourly)
        self.hour_panel.setVisible(hourly)
        try:
            amount = (Decimal(self.hours.text()) * HOURLY_RATE if hourly else
                      Decimal(self.quantity.text()) * Decimal(self.price.text()))
            if amount < 0:
                raise ValueError
            self.amount.setText(f'本项工资：¥{amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):.2f}')
        except (InvalidOperation, ValueError):
            self.amount.setText('本项工资：—')

    def prefill_default(self, code):
        if not self.price.text().strip():
            default = self.confirmed_defaults.get(normalize_code(code))
            if default is not None:
                self.price.setText(str(default))

    def values(self):
        if self.kind.currentIndex() == 1:
            hours = Decimal(self.hours.text().strip())
            if not hours.is_finite() or hours <= 0 or hours > 24:
                raise ValueError('工时须大于0且不超过24小时')
            return WorkKind.HOURLY, '', '', '', str(hours), self.note.text().strip()
        code = normalize_code(self.code.currentText())
        if not code:
            raise ValueError('请确认完整货号或工作项目')
        quantity, price = Decimal(self.quantity.text().strip()), Decimal(self.price.text().strip())
        if not quantity.is_finite() or not price.is_finite() or quantity <= 0 or price < 0:
            raise ValueError('数量须大于0，单价不能小于0')
        return WorkKind.PIECE, code, str(quantity), str(price), '', ''

    def confirm(self):
        try:
            error = self.on_confirm(self.values())
        except (InvalidOperation, ValueError):
            error = '请填写有效的货号、数量、单价或工时'
        if error:
            QMessageBox.warning(self, '审核失败', error)
        else:
            self.accept()
