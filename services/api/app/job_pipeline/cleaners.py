from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from app.job_pipeline.contracts import CleanedJobText

_BLOCK_TAGS = {"br", "div", "p", "li", "section", "article", "h1", "h2", "h3", "h4", "tr"}
_SKIP_TAGS = {"script", "style", "svg", "noscript", "iframe", "template"}
_NOISE_PATTERNS = (
    re.compile(r"^(?:立即沟通|在线沟通|收藏|举报|分享|扫码分享|查看更多|展开|收起)$"),
    re.compile(r"^(?:登录|注册|下载app|打开app|关注我们|职位收藏成功)$", re.I),
    re.compile(r"^(?:boss直聘|智联招聘|前程无忧|牛客网)\s*$", re.I),
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def _strip_html(value: str) -> str:
    parser = _TextParser()
    try:
        parser.feed(value)
        parser.close()
        return "".join(parser.parts)
    except Exception:
        return re.sub(r"<[^>]+>", " ", value)


def clean_job_text(value: str | None) -> CleanedJobText:
    """Remove presentation noise while retaining source wording and headings."""

    raw = html.unescape(value or "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = _strip_html(raw)
    raw = re.sub(r"[\u200b-\u200f\ufeff\u2060]", "", raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    lines: list[str] = []
    removed: list[str] = []
    for line in raw.splitlines():
        clean = line.strip(" \t•·-—")
        if not clean:
            continue
        if any(pattern.match(clean) for pattern in _NOISE_PATTERNS):
            removed.append(clean)
            continue
        lines.append(line.strip())
    text = "\n".join(lines)
    warnings: list[str] = []
    if not text:
        warnings.append("clean_text_empty")
    if len(text) < 40:
        warnings.append("description_too_short")
    if re.search(r"[�\ue000-\uf8ff]", text):
        warnings.append("unmapped_private_or_replacement_character")
    return CleanedJobText(
        text=text,
        removed_noise=tuple(dict.fromkeys(removed)),
        warnings=tuple(warnings),
    )
