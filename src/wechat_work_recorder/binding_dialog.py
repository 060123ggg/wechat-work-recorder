"""查看、新增、修改与解除微信昵称绑定。"""
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QMessageBox,
                              QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)
from .bindings import BindingConflict, NicknameBindingStore


class BindingDialog(QDialog):
    def __init__(self, store: NicknameBindingStore, groups: list[str], parent=None):
        super().__init__(parent)
        self.store = store
        self.groups = groups
        self.setWindowTitle("微信昵称与员工绑定")
        self.resize(650, 420)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["微信群", "微信昵称", "工号", "员工姓名"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for title, callback in (("添加绑定", self.add_binding), ("修改绑定", self.change_binding),
                                ("解除绑定", self.remove_binding)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        rows = self.store.list_bindings()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col, value in enumerate(row):
                self.table.setItem(row_index, col, QTableWidgetItem(value))

    def selected_binding(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "请选择绑定", "请先选择一条绑定")
            return None
        return self.table.item(row, 0).text(), self.table.item(row, 1).text()

    def choose_employee(self, current_employee_id: str | None = None):
        employees = self.store.employees()
        labels = ["请选择员工…"] + [f"{e.employee_id}  {e.name}" for e in employees]
        selected = next((i + 1 for i, e in enumerate(employees) if e.employee_id == current_employee_id), 0)
        choice, ok = QInputDialog.getItem(self, "选择员工", "请选择正式员工：", labels, selected, False)
        return employees[labels.index(choice) - 1].employee_id if ok and choice and choice != labels[0] else None

    def add_binding(self):
        if not self.groups:
            QMessageBox.warning(self, "缺少群", "请先设置微信群")
            return
        group, ok = QInputDialog.getItem(self, "微信群", "选择群：", self.groups, 0, False)
        if not ok:
            return
        nickname, ok = QInputDialog.getText(self, "微信昵称", "输入准确的微信昵称：")
        if not ok:
            return
        employee_id = self.choose_employee()
        if employee_id is None:
            return
        try:
            self.store.bind(group, nickname, employee_id)
        except (BindingConflict, ValueError) as exc:
            QMessageBox.warning(self, "绑定失败", str(exc))
        self.refresh()

    def change_binding(self):
        selected = self.selected_binding()
        if selected is None:
            return
        old_group, old_nickname = selected
        group, ok = QInputDialog.getItem(self, "微信群", "选择群：", self.groups,
                                         self.groups.index(old_group) if old_group in self.groups else 0, False)
        if not ok:
            return
        nickname, ok = QInputDialog.getText(self, "微信昵称", "修改准确的微信昵称：", text=old_nickname)
        if not ok:
            return
        employee_id = self.choose_employee(self.store.resolve(old_group, old_nickname))
        if employee_id is None:
            return
        try:
            self.store.replace(old_group, old_nickname, group, nickname, employee_id)
        except (BindingConflict, ValueError) as exc:
            QMessageBox.warning(self, "修改失败", str(exc))
        self.refresh()

    def remove_binding(self):
        selected = self.selected_binding()
        if selected is None:
            return
        if QMessageBox.question(self, "解除绑定", f"确认解除 {selected[0]} 中 {selected[1]} 的绑定？") == QMessageBox.StandardButton.Yes:
            self.store.unbind(*selected)
            self.refresh()
