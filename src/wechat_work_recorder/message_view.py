"""把微信原文映射到界面消息序号；不改变原文或解析行号。"""
from dataclasses import dataclass
import re
from .parser import DATE
from .wechat_text import TIME, nickname_candidates


@dataclass(frozen=True)
class MessageBlock:
    number: int
    start_line: int
    end_line: int
    nickname: str | None
    raw_text: str


def split_messages(text: str, groups: list[str]) -> list[MessageBlock]:
    lines = text.replace('\\', '\n').splitlines()
    if not lines:
        return []
    candidates = set(nickname_candidates(text, groups))
    senders: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        nickname = stripped if stripped in candidates else None
        if nickname is None:
            prefix = re.match(r'^([^\s:：]{1,24})[：:]', stripped)
            if prefix and prefix.group(1) in candidates:
                nickname = prefix.group(1)
        if nickname is None:
            residue = TIME.sub('', DATE.sub('', stripped)).strip(' ：:，,\t')
            if residue in candidates:
                nickname = residue
        if nickname:
            senders.append((index, nickname))
    if not senders:
        return [MessageBlock(1, 1, len(lines), None, '\n'.join(lines))]
    starts = []
    for index, nickname in senders:
        start = index
        if index > 0 and DATE.search(lines[index - 1]) and not any(s >= index - 1 for s, _ in starts):
            start = index - 1
        starts.append((start, nickname))
    if starts[0][0] > 0:
        starts[0] = (0, starts[0][1])
    blocks = []
    for number, (start, nickname) in enumerate(starts, 1):
        end = starts[number][0] if number < len(starts) else len(lines)
        if end <= start:
            continue
        blocks.append(MessageBlock(number, start + 1, end, nickname, '\n'.join(lines[start:end])))
    return blocks


def message_for_line(blocks: list[MessageBlock], line: int | None) -> int | None:
    return next((block.number for block in blocks if line and block.start_line <= line <= block.end_line), None)
