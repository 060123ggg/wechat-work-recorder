"""原文只保存文字；间距、分隔线与高亮均由显示层绘制。"""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QListWidget, QListView, QTextEdit


class MessageEditor(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.message_starts = []
        self._spaced_lines = set()

    def appendPlainText(self, text):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(('\n' if self.toPlainText() else '') + text)
        self.setTextCursor(cursor)

    def set_message_blocks(self, blocks):
        starts = {block.start_line for block in blocks[1:]}
        # Block margins insert no characters, so all source positions remain intact.
        with QSignalBlocker(self):
            for line in self._spaced_lines | starts:
                block = self.document().findBlockByNumber(line - 1)
                if block.isValid():
                    cursor = QTextCursor(block)
                    fmt = cursor.blockFormat()
                    fmt.setTopMargin(24 if line in starts else 0)
                    cursor.setBlockFormat(fmt)
        self._spaced_lines = starts
        self.message_starts = sorted(starts)
        self.viewport().update()

    def separator_positions(self):
        positions = []
        for line in self.message_starts:
            block = self.document().findBlockByNumber(line - 1)
            if block.isValid():
                y = self.cursorRect(QTextCursor(block)).top() - 12
                if 0 <= y <= self.viewport().height():
                    positions.append(y)
        return positions

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor('#75a68d'), 2))
        for y in self.separator_positions():
            painter.drawLine(8, y, self.viewport().width() - 8, y)


class ReviewList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(4)
