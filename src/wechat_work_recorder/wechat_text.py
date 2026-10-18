"""从微信批量复制文本中提取明确的发送者昵称候选。"""
import re
from .parser import DATE, WORKLIKE

TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
NICKNAME = re.compile(r"^[^\s:：]{1,24}$")


def nickname_candidates(text: str, group_names: list[str]) -> list[str]:
    lines = [line.strip() for line in text.replace("\\", "\n").splitlines() if line.strip()]
    candidates: list[str] = []
    for index, line in enumerate(lines):
        if line in group_names:
            continue
        sender_prefix = re.match(r"^(?P<nick>[^\s:：]{1,24})[：:]\s*(?P<body>.*)$", line)
        if sender_prefix and WORKLIKE.search(sender_prefix.group("body")):
            nickname = sender_prefix.group("nick")
            if nickname not in group_names and nickname not in candidates:
                candidates.append(nickname)
            continue
        residue = TIME.sub("", DATE.sub("", line)).strip(" ：:，,\t")
        if residue in group_names:
            continue
        if not residue or WORKLIKE.search(residue):
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        is_header = DATE.search(line) or line.endswith((":", "："))
        is_standalone_sender = NICKNAME.fullmatch(residue) and (WORKLIKE.search(next_line) or DATE.search(next_line))
        if (is_header or is_standalone_sender) and NICKNAME.fullmatch(residue) and residue not in candidates:
            candidates.append(residue)
    return candidates
