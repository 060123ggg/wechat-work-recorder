"""在界面中确认17名员工的正式工号与姓名。"""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)
from .models import Employee
from .roster import validate_roster


class RosterDialog(QDialog):
    def __init__(self, employees: list[Employee], existing_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle('管理正式员工名册')
        self.resize(580, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('核对17名员工的正式工号和姓名。已有姓名已预填；首次显示的工号仅为建议，保存前请核对。\n'
                                '名册只保存在本机，不会上传到 GitHub。'))
        self.table = QTableWidget(17, 2)
        self.table.setHorizontalHeaderLabels(['正式工号', '员工姓名'])
        self.table.horizontalHeader().setStretchLastSection(True)
        for row in range(17):
            employee_id = employees[row].employee_id if row < len(employees) else f'AM-{1001 + row}'
            name = employees[row].name if row < len(employees) else (
                existing_names[row] if row < len(existing_names) else '')
            self.table.setItem(row, 0, QTableWidgetItem(employee_id))
            self.table.setItem(row, 1, QTableWidgetItem(name))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def employees(self) -> list[Employee]:
        return [Employee(self.table.item(row, 0).text().strip() if self.table.item(row, 0) else '',
                         self.table.item(row, 1).text().strip() if self.table.item(row, 1) else '')
                for row in range(17)]

    def validate_and_accept(self):
        try:
            validate_roster(self.employees())
        except ValueError as exc:
            QMessageBox.warning(self, '名册不完整', str(exc))
            return
        self.accept()
