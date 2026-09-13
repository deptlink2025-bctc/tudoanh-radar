"""Nguồn dự phòng chung: kho tài liệu của Vietstock (finance.vietstock.vn/<MÃ>/tai-tai-lieu.htm).

Web IR của đa số CTCK dựng bằng JavaScript hoặc chặn máy (MBS, TCX, VND trả 403; BSI, CTS, VCI,
VDS không có link trong HTML). Vietstock gom BCTC của mọi mã với tiêu đề chuẩn "BCTC quý 2 năm 2026"
và file .zip trên static2.vietstock.vn. Cách gọi (đọc từ bundle /bundles/company/document/jsx):

    GET  /<MÃ>/tai-tai-lieu.htm            → cookie + __RequestVerificationToken (input hidden)
    POST /data/getdocument  {code, page, year, type=1, __RequestVerificationToken}
         → [{Title, Url, FileExt, LastUpdate, ...}]   (type 1 = Báo cáo tài chính)

Zip thường chứa BCTC chính (lớn) + công văn giải trình (nhỏ): chọn PDF có điểm tên file cao
nhất, hoà thì lấy file lớn nhất.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import httpx

from common.config import BROWSER_HEADERS, HTTP_TIMEOUT
from common.quarters import parse

from .fetch import FetchError, _strip_vn, score_candidate

logger = logging.getLogger(__name__)

BASE = "https://finance.vietstock.vn"
DOC_TYPE_BCTC = 1
_TOKEN_RE = re.compile(r'name=["\']?__RequestVerificationToken["\']?[^>]*value=["\']?([^"\'\s>]+)')


def list_documents(symbol: str, year: int) -> list[dict]:
    """Danh sách BCTC của một mã trong một năm. Ném FetchError nếu Vietstock không trả lời."""
    sym = symbol.upper()
    page_url = f"{BASE}/{sym}/tai-tai-lieu.htm"
    try:
        with httpx.Client(headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
            page = c.get(page_url)
            page.raise_for_status()
            m = _TOKEN_RE.search(page.text)
            if not m:
                raise FetchError("Vietstock đổi cấu trúc trang: không thấy __RequestVerificationToken")
            hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": page_url, "Origin": BASE}
            out: list[dict] = []
            for pg in (1, 2):
                r = c.post(f"{BASE}/data/getdocument", headers=hdr,
                           data={"code": sym, "page": pg, "year": year, "type": DOC_TYPE_BCTC, "__RequestVerificationToken": m.group(1)})
                r.raise_for_status()
                rows = r.json() or []
                out += [{"title": (x.get("Title") or "").strip(), "url": x.get("Url") or "", "ext": (x.get("FileExt") or "").lower()} for x in rows]
                if len(rows) < 20:
                    break
            return out
    except httpx.HTTPError as exc:
        raise FetchError(f"Vietstock lỗi: {exc}") from exc


def find_report(symbol: str, quarter: str) -> dict:
    """Tài liệu 'BCTC quý N năm Y' — ưu tiên bản riêng lẻ (tiêu đề không có 'hợp nhất')."""
    y, n = parse(quarter)
    docs = list_documents(symbol, y)
    scored = []
    for d in docs:
        t = _strip_vn(d["title"])
        if not re.search(rf"\bquy\s*0?{n}\b", t):
            continue
        if any(k in t for k in ("soat xet", "ban nien", "kiem toan", "thuong nien", "6 thang", "giai trinh")):
            continue
        s = 10 - (3 if "hop nhat" in t else 0) - (5 if "cong ty me" in t and "hop nhat" in t else 0)
        scored.append((s, d))
    if not scored:
        titles = "; ".join(d["title"] for d in docs[:6]) or "(không có tài liệu nào)"
        raise FetchError(f"Vietstock chưa có BCTC {quarter} của {symbol}. Có: {titles}")
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def download_report(symbol: str, quarter: str, dest: Path) -> tuple[Path, str, str]:
    """Tải tài liệu (zip hoặc pdf) → PDF tại dest. Trả về (path, sha256, url nguồn)."""
    import hashlib

    doc = find_report(symbol, quarter)
    url = doc["url"]
    with httpx.Client(headers=BROWSER_HEADERS, timeout=httpx.Timeout(HTTP_TIMEOUT, read=300), follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        blob = r.content
    if blob[:4] == b"%PDF":
        pdf = blob
    elif blob[:2] == b"PK":
        pdf = _best_pdf_in_zip(blob, quarter)
    else:
        raise FetchError(f"Vietstock trả về định dạng lạ ({r.headers.get('content-type')}) cho {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf)
    return dest, hashlib.sha256(pdf).hexdigest(), url


def _best_pdf_in_zip(blob: bytes, quarter: str) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(blob))
    pdfs = [i for i in z.infolist() if i.filename.lower().endswith(".pdf") and not i.is_dir()]
    if not pdfs:
        # zip lồng zip (hiếm)
        for i in z.infolist():
            if i.filename.lower().endswith(".zip"):
                return _best_pdf_in_zip(z.read(i), quarter)
        raise FetchError("Zip Vietstock không chứa PDF nào")
    # Điểm theo tên file (riêng > hợp nhất > công văn), hoà thì file lớn nhất
    def key(i):
        s = score_candidate(i.filename, "", quarter)
        name = _strip_vn(i.filename)
        if "giai trinh" in name or "explanation" in name or "cbtt" in name or "cong van" in name:
            s -= 8
        return (s, i.file_size)
    pdfs.sort(key=key, reverse=True)
    logger.info("Chọn %s (%d KB) trong zip", pdfs[0].filename, pdfs[0].file_size // 1024)
    return z.read(pdfs[0])
