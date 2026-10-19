"""消息编号和原文定位使用同一份解析上下文。"""
from .message_context import MessageBlock, split_messages, message_for_line

__all__ = ['MessageBlock', 'split_messages', 'message_for_line']
