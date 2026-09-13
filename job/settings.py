"""Ngưỡng cảnh báo + công ty tắt. Nguồn: Cloudflare Worker KV (giao diện sửa) → fallback
data/settings.json (commit trong repo) → mặc định trong code."""
from __future__ import annotations

import json
import logging

import httpx

from common.config import HTTP_TIMEOUT, SITE_DATA, WORKER_TOKEN, WORKER_URL

logger = logging.getLogger(__name__)

DEFAULTS = {
    "r1_pct": 7.0,            # một mã ±X % trong phiên
    "r1_min_value": 20e9,     # ...và CTCK giữ ≥ Y VND mã đó
    "r2_value": 100e9,        # danh mục một CTCK ±Z VND trong phiên
    "r3_weight": 0.20,        # mã chiếm > 20 % danh mục chạm sàn/trần
    "r3_pct": 6.5,            # ngưỡng coi là sàn/trần (HOSE ±7 %)
    "r4_pct": 15.0,           # lãi/lỗ so giá vốn vượt ±W % lần đầu
    "brokers_disabled": [],
}

LOCAL = SITE_DATA / "settings.json"


def load() -> dict:
    s = dict(DEFAULTS)
    if LOCAL.exists():
        try:
            s.update(json.loads(LOCAL.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings.json hỏng: %s", exc)
    if WORKER_URL and WORKER_TOKEN:
        try:
            r = httpx.get(f"{WORKER_URL}/settings", headers={"Authorization": f"Bearer {WORKER_TOKEN}"}, timeout=HTTP_TIMEOUT)
            if r.status_code == 200 and r.text.strip():
                s.update(r.json())
                s["_source"] = "worker"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Worker /settings không trả lời: %s — dùng bản local", exc)
    return s
