"""Quy ước quý: chuỗi '2026Q2' ↔ ngày cuối quý '2026-06-30'."""
from __future__ import annotations

import re
from datetime import date

_Q_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_RE = re.compile(r"^(\d{4})Q([1-4])$")


def parse(q: str) -> tuple[int, int]:
    m = _RE.match(q.strip().upper())
    if not m:
        raise ValueError(f"Quý không hợp lệ: {q!r} (đúng dạng: 2026Q2)")
    return int(m.group(1)), int(m.group(2))


def end_date(q: str) -> date:
    y, n = parse(q)
    return date(y, *_Q_END[n])


def prev(q: str) -> str:
    y, n = parse(q)
    return f"{y - 1}Q4" if n == 1 else f"{y}Q{n - 1}"


def label(q: str) -> str:
    """'2026Q2' → 'Q2/2026' — cách người Việt đọc."""
    y, n = parse(q)
    return f"Q{n}/{y}"


def latest_reported(today: date | None = None) -> str:
    """Quý gần nhất mà BCTC đã có thể được công bố (≥ 20 ngày sau khi kết thúc quý)."""
    today = today or date.today()
    y, m = today.year, today.month
    n = (m - 1) // 3 + 1          # quý hiện tại
    # Lùi về quý trước; nếu chưa qua 20 ngày kể từ cuối quý trước thì lùi thêm một quý.
    n -= 1
    if n == 0:
        y, n = y - 1, 4
    if (today - end_date(f"{y}Q{n}")).days < 20:
        n -= 1
        if n == 0:
            y, n = y - 1, 4
    return f"{y}Q{n}"
