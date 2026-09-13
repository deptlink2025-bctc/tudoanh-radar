"""Giá cổ phiếu từ DNSE/Entrade — miễn phí, không token. Chép từ KingStock, sửa hai chỗ:

1. Dùng MỘT httpx.Client cho cả vòng lặp (KingStock tạo client mới mỗi lần gọi — chấp nhận
   được với 10 mã, lãng phí với 200 mã).
2. Nghỉ 0,3 giây giữa các mã. Đây là API nội bộ của một CTCK, không có cam kết; gọi dồn
   dập là cách nhanh nhất để bị chặn.

Endpoint: GET {DNSE_BASE}/stock?symbol=VNM&resolution=1D&from=<epoch>&to=<epoch>
Trả về JSON dạng cột song song: {"t":[...],"o":[...],"h":[...],"l":[...],"c":[...],"v":[...]}
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import httpx

from .config import BROWSER_HEADERS, DNSE_BASE, HTTP_TIMEOUT, TZ

logger = logging.getLogger(__name__)

THROTTLE_SECONDS = 0.3
HISTORY_DAYS = 260
# DNSE trả giá theo NGHÌN đồng (HPG = 23.3 nghĩa là 23.300 đ). Mọi phép tính trong app dùng VND,
# nên nhân ngay lúc parse để không ai phải nhớ điều này ở chỗ khác.
PRICE_UNIT = 1000.0

# Trạng thái nguồn, job ghi vào state.json để giao diện biết khi nguồn chết.
last_ok: datetime | None = None
last_error: str = ""


def _parse(payload: dict) -> list[dict]:
    out: list[dict] = []
    for i, t in enumerate(payload.get("t") or []):
        try:
            out.append({
                "d": datetime.fromtimestamp(t, TZ).date(),
                "o": float(payload["o"][i]) * PRICE_UNIT,
                "h": float(payload["h"][i]) * PRICE_UNIT,
                "l": float(payload["l"][i]) * PRICE_UNIT,
                "c": float(payload["c"][i]) * PRICE_UNIT,
                "v": int(payload["v"][i]),
                "t": int(t),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    out.sort(key=lambda b: b["t"])
    return out


class DnseClient:
    """Dùng trong `with` để giữ kết nối qua nhiều mã."""

    def __init__(self, days: int = HISTORY_DAYS):
        self.days = days
        self._client = httpx.Client(timeout=HTTP_TIMEOUT, headers=BROWSER_HEADERS)
        self._last_call = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._client.close()

    def daily(self, symbol: str) -> list[dict]:
        """Nến ngày, cũ → mới. Lỗi thì trả [] và ghi last_error, không ném ra ngoài."""
        global last_ok, last_error
        wait = THROTTLE_SECONDS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        now = datetime.now(TZ)
        params = {
            "symbol": symbol.upper(),
            "resolution": "1D",
            "from": int((now - timedelta(days=self.days)).timestamp()),
            "to": int((now + timedelta(days=1)).timestamp()),
        }
        try:
            r = self._client.get(f"{DNSE_BASE}/stock", params=params)
            self._last_call = time.monotonic()
            r.raise_for_status()
            bars = _parse(r.json())
        except Exception as exc:  # noqa: BLE001 — một mã hỏng không được làm chết cả vòng
            self._last_call = time.monotonic()
            last_error = f"{symbol}: {exc}"
            logger.warning("DNSE lỗi %s: %s", symbol, exc)
            return []
        if bars:
            last_ok = datetime.now(TZ)
            last_error = ""
        return bars


def close_on_or_before(bars: list[dict], d: date) -> float | None:
    """Giá đóng cửa (VND) của phiên gần nhất ≤ d (cuối quý rơi vào cuối tuần thì lùi về thứ Sáu)."""
    for b in reversed(bars):
        if b["d"] <= d:
            return b["c"]
    return None


def today_vn() -> date:
    return datetime.now(TZ).date()
