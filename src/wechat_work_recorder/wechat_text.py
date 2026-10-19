"""只从明确消息头提取昵称，不把正文日期当作昵称。"""
from .message_context import TIME, split_messages


def nickname_candidates(text: str, group_names: list[str]) -> list[str]:
    return list(dict.fromkeys(block.nickname for block in split_messages(text, group_names) if block.nickname))
