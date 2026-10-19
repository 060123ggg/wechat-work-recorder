"""独立的微信消息边界与日期上下文；不依赖工资解析器。"""
from dataclasses import dataclass
from datetime import date
import re

DATE = re.compile(r'(?P<year>\d{4})[./年-](?P<month>\d{1,2})[./月-](?P<day>\d{1,2})[日号]?')
PARTIAL_DATE = re.compile(r'(?<![\d.])(?P<month>\d{1,2})(?:月|[./])(?P<day>\d{1,2})[日号]?(?![\d.])')
TIME = re.compile(r'(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)')
WORKLIKE = re.compile(r'货号|数量|单价|计时|工时|计\s*\d|\d+(?:\.\d+)?\s*(?:小时|时|个|件|捆|套|只|箱|[＊*×✘xX])|\d{4}[-~]\d+')
NICKNAME = re.compile(r'^[^\s:：]{1,40}$')
FIELDS = {'货号', '数量', '单价', '计时', '工时', '发送人', '正文', '微信发送时间'}


@dataclass(frozen=True)
class MessageBlock:
    number: int
    start_line: int
    end_line: int
    nickname: str | None
    raw_text: str
    sent_date: date | None = None
    shared_date: date | None = None


def _full_date(value):
    m = DATE.search(value)
    return date(int(m['year']), int(m['month']), int(m['day'])) if m else None


def _date_only(value):
    return bool(DATE.fullmatch(value.strip(' ：:')) or PARTIAL_DATE.fullmatch(value.strip(' ：:')))


def _sender(lines, index, groups, known):
    value = lines[index].strip()
    if not value or value in groups or value in FIELDS or _date_only(value) or re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    explicit = re.fullmatch(r'(?:发送人|微信昵称)[：:]\s*(.+)', value)
    if explicit:
        return explicit[1].strip()
    prefix = re.match(r'^([^\s:：]{1,40})[：:]\s*(.*)$', value)
    if prefix and prefix[1] not in FIELDS and WORKLIKE.search(prefix[2]):
        return prefix[1]
    value = value.rstrip('：:')
    if value in FIELDS:
        return None
    residue = TIME.sub('', DATE.sub('', value)).strip(' ：:，,\t')
    if DATE.search(value) and NICKNAME.fullmatch(residue) and not WORKLIKE.search(residue):
        return residue if residue not in groups and residue not in FIELDS else None
    if DATE.search(value):
        for name in known:
            if re.search(rf'(?<!\w){re.escape(name)}(?!\w)', value):
                return name
        inline = re.match(r'^([^\s:：]+)\s+(?=货号|计时|工时|\d{4}(?:\s|-))', residue)
        if inline and inline[1] not in groups:
            return inline[1]
    if WORKLIKE.search(value) or DATE.search(value) or TIME.fullmatch(value):
        return None
    next_line = next((line.strip() for line in lines[index + 1:] if line.strip()), '')
    previous_line = next((line.strip() for line in reversed(lines[:index]) if line.strip()), '')
    if len(value) <= 80 and ((DATE.search(next_line) and TIME.search(next_line))
                            or (DATE.search(previous_line) and TIME.search(previous_line))):
        return value
    if value in known or (NICKNAME.fullmatch(value) and (DATE.search(next_line) or WORKLIKE.search(next_line))):
        return value.rstrip('：:')
    return None


def split_messages(text: str, groups: list[str], known_names=()) -> list[MessageBlock]:
    lines = text.replace('\\', '\n').splitlines()
    if not lines:
        return []
    senders = [(i, nick) for i in range(len(lines))
               if (nick := _sender(lines, i, groups, set(known_names)))]
    if not senders:
        sent = None
        for value in [line for line in lines if line.strip()][:3]:
            if DATE.search(value) and TIME.search(value):
                try:
                    sent = _full_date(value)
                except ValueError:
                    pass
        return [MessageBlock(1, 1, len(lines), None, '\n'.join(lines), sent)]
    starts = []
    shared = None
    for i in range(senders[0][0]):
        if DATE.fullmatch(lines[i].strip()):
            try:
                shared = _full_date(lines[i])
            except ValueError:
                pass
    for index, nickname in senders:
        start = index
        previous = index - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        if previous >= 0 and DATE.search(lines[previous]) and not WORKLIKE.search(DATE.sub('', TIME.sub('', lines[previous]))):
            if not starts or previous > starts[-1][0]:
                start = previous
        starts.append((start, nickname))
    starts[0] = (0, starts[0][1])
    blocks = []
    for n, (start, nickname) in enumerate(starts, 1):
        end = starts[n][0] if n < len(starts) else len(lines)
        if end <= start:
            continue
        sent = None
        # 发送时间只来自发送人旁的头部，正文中包含时间不创建新消息。
        for line in [value for value in lines[start:end] if value.strip()][:4]:
            if DATE.search(line) and TIME.search(line):
                try:
                    sent = _full_date(line)
                except ValueError:
                    pass
                break
        blocks.append(MessageBlock(n, start + 1, end, nickname,
                                   '\n'.join(lines[start:end]), sent, shared))
    return blocks


def date_for_line(block: MessageBlock, line_number: int) -> date | None:
    current = block.sent_date or block.shared_date
    year = block.sent_date.year if block.sent_date else (current.year if current else None)
    for offset, raw in enumerate(block.raw_text.splitlines(), block.start_line):
        if offset > line_number:
            break
        if TIME.search(raw) and DATE.search(raw):
            # 不让发送时间覆盖正文已写的记工日期。
            continue
        full = DATE.search(raw)
        if full:
            current = _full_date(raw)
            year = current.year
        elif partial := PARTIAL_DATE.fullmatch(raw.strip(' ：:')):
            if year is None:
                raise ValueError('工作日期缺少年份，且没有微信发送年份可补全')
            current = date(year, int(partial['month']), int(partial['day']))
    return current


def message_for_line(blocks: list[MessageBlock], line: int | None) -> int | None:
    return next((b.number for b in blocks if line and b.start_line <= line <= b.end_line), None)
