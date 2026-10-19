"""本机项目、别名和已确认标准价管理。"""
from decimal import Decimal, InvalidOperation
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QMessageBox, QListWidget, QPushButton, QHBoxLayout, QFileDialog, QComboBox)
from .catalog import ItemCatalog


class ProjectDialog(QDialog):
    def __init__(self, catalog: ItemCatalog, code='', price=None, parent=None, *, original='', new=False):
        super().__init__(parent)
        self.catalog, self.old_code, self.new = catalog, code, new
        self.setWindowTitle('新增项目并确认标准价' if new else '编辑项目与标准价')
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        if original:
            label = QLabel('原始微信文字：' + original)
            label.setWordWrap(True)
            layout.addWidget(label)
        data = catalog.items.get(code, {})
        form = QFormLayout()
        self.code = QLineEdit(code)
        default = catalog.default_price(code)
        self.price = QLineEdit(str(default if default is not None else price) if default is not None or price is not None else '')
        self.unit = QLineEdit(data.get('unit', '件'))
        self.aliases = QLineEdit('，'.join(data.get('aliases', [])))
        form.addRow('完整货号 / 标准项目名', self.code)
        form.addRow('当前标准价（元）', self.price)
        form.addRow('数量单位', self.unit)
        form.addRow('多个别名（逗号分隔）', self.aliases)
        layout.addLayout(form)
        history = catalog.price_history(code)
        self.history_choice = QComboBox()
        self.history_choice.addItem('从十月历史价格选择（须确认后保存）', '')
        for value in sorted({row['price'] for row in history}, key=Decimal):
            self.history_choice.addItem(value, value)
        self.history_choice.currentIndexChanged.connect(
            lambda index: self.price.setText(self.history_choice.itemData(index)) if index else None)
        if len(history) > 1:
            layout.addWidget(self.history_choice)
        label = QLabel('十月历史来源：' + ('；'.join(f"{h['price']}元，{h['count']}次，{h['source']}" for h in history) or '未导入'))
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(QLabel('保存标准价只影响以后新解析的记录，不修改已确认工资。不同数字货号不能互作别名。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        import re
        try:
            price = Decimal(self.price.text().strip()) if self.price.text().strip() else None
            if self.new and price is None:
                raise ValueError('新增项目须确认标准单价')
            self.catalog.update_item(self.code.text(), price, self.unit.text(),
                                     re.split(r'[,，;；\n]', self.aliases.text()),
                                     old_code=self.old_code or self.code.text())
        except (ValueError, InvalidOperation, OSError) as exc:
            QMessageBox.warning(self, '项目未保存', str(exc))
            return
        self.accept()


class CatalogDialog(QDialog):
    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.setWindowTitle('项目价格资料库（仅保存在本机）')
        self.setMinimumSize(700, 500)
        layout = QVBoxLayout(self)
        self.state = QLabel()
        layout.addWidget(self.state)
        self.items = QListWidget()
        layout.addWidget(self.items)
        controls = QHBoxLayout()
        for label, callback in [('新增项目', self.add), ('编辑选中项目/别名/标准价', self.edit),
                                ('导入随包十月资料', self.import_builtin), ('导入价格CSV', self.import_csv)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.items.itemDoubleClicked.connect(lambda _: self.edit())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        imported = sum(bool(data.get('history')) for data in self.catalog.items.values())
        self.state.setText(f'十月价格已导入 {imported} 个项目；未导入时历史货号仅用于识别，不提供默认价。')
        self.items.clear()
        self.codes = sorted(self.catalog.codes)
        for code in self.codes:
            data = self.catalog.items.get(code, {})
            price = self.catalog.default_price(code)
            self.items.addItem(f'{code}｜标准价：{price if price is not None else "待确认"}｜{data.get("unit", "件")}｜别名：{", ".join(data.get("aliases", []))}')

    def add(self):
        ProjectDialog(self.catalog, parent=self, new=True).exec()
        self.refresh()

    def edit(self):
        row = self.items.currentRow()
        if row < 0:
            return
        ProjectDialog(self.catalog, self.codes[row], parent=self).exec()
        self.refresh()

    def import_file(self, path):
        if QMessageBox.question(self, '确认导入十月价格',
            '只导入项目和价格资料。单一历史价作为初始标准价；多价保持待确认；已有用户标准价保持不变。继续吗？') != QMessageBox.StandardButton.Yes:
            return
        try:
            count, pending = self.catalog.import_october_csv(Path(path))
            QMessageBox.information(self, '导入完成', f'已导入{count}个项目；其中{pending}个多价项目等待确认当前标准价。')
        except (ValueError, KeyError, InvalidOperation, OSError) as exc:
            QMessageBox.warning(self, '导入失败', str(exc))
        self.refresh()

    def import_builtin(self):
        self.import_file(Path(__file__).with_name('october_prices.csv'))

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择脱敏价格资料', '', 'CSV (*.csv)')
        if path:
            self.import_file(path)
