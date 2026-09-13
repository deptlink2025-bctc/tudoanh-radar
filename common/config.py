"""Cấu hình chung cho cả Tầng A (local) và Tầng B (GitHub Actions).

Mọi thứ qua biến môi trường. Local đọc từ .env; trên GitHub Actions đọc từ Secrets.
"""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "pdf"
PAGES_DIR = DATA_DIR / "pages"
# JSON mà giao diện tĩnh đọc — nằm trong docs/ vì GitHub Pages phục vụ thư mục /docs (cách BCTC Radar).
SITE_DATA = ROOT / "docs" / "data"

# utf-8-sig: Notepad/PowerShell ghi BOM ở đầu file; thiếu cái này thì biến đầu tiên
# thành "﻿ANTHROPIC_API_KEY" và mọi thứ chết im lặng (bài học KingStock).
load_dotenv(ROOT / ".env", encoding="utf-8-sig")

# Offset cố định +7: VN không có giờ mùa hè, và Windows mặc định thiếu bộ tzdata (như KingStock).
TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
DNSE_BASE = os.getenv("DNSE_BASE", "https://services.entrade.com.vn/chart-api/v2/ohlcs")
VNDIRECT_FINFO = os.getenv("VNDIRECT_FINFO", "https://api-finfo.vndirect.com.vn/v4")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "claude-opus-5")
LOCATE_MODEL = os.getenv("LOCATE_MODEL", "claude-haiku-4-5")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")

WORKER_URL = os.getenv("WORKER_URL", "").rstrip("/")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "")
PUSH_SUBS_FALLBACK = os.getenv("PUSH_SUBS_FALLBACK", "")

# Header giả trình duyệt — finfo có WAF chặn UA lạ (bctc-radar từng bị chặn HeadlessChrome).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}
