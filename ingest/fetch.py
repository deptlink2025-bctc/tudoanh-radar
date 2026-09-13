"""Bước 1 — tải PDF BCTC quý về data/pdf/<MÃ>_<QUÝ>.pdf.

Cách tìm: mở trang IR, gom mọi link .pdf, chấm điểm theo từ khoá của quý (Q2, quý 2,
quy 2, 2026, 'tai chinh', 'rieng'...). Điểm cao nhất thắng. Không có ứng viên → ném
FetchError để pipeline đánh dấu 'stuck' và người dùng dán URL tay.

HTTP theo pattern kingstock/app/sources/ssc.py: header trình duyệt, retry 3, backoff tuyến tính.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

from common.config import BROWSER_HEADERS, HTTP_TIMEOUT, PDF_DIR
from common.quarters import parse

logger = logging.getLogger(__name__)

RETRIES = 3
_LINK_RE = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+?\.pdf(?:\?[^"']*)?)["']""", re.I)
_TEXT_RE = re.compile(r">([^<]{0,160})<")


class FetchError(Exception):
    pass


def _strip_vn(s: str) -> str:
    """Bỏ dấu để so từ khoá: 'Quý 2 năm 2026' → 'quy 2 nam 2026'."""
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    # Tên file hay dùng _ - . %20 thay cho khoảng trắng: "Quy_2_nam_2026" → "quy 2 nam 2026"
    return re.sub(r"%20|[_\-.]", " ", s)


def score_candidate(url: str, context: str, quarter: str) -> int:
    """Điểm càng cao càng giống 'BCTC riêng quý X năm Y'. Âm = chắc chắn sai."""
    y, n = parse(quarter)
    text = _strip_vn(url + " " + context)
    s = 0
    if str(y) in text:
        s += 3
    # Đúng quý là BẮT BUỘC; nhắc tới quý khác là loại. Dấu hiệu quý: "Q2", "quý 2", "quy 2", "_q2_", "quarter 2".
    def has_q(k: int) -> bool:
        return re.search(rf"(?<![a-z0-9])q\s*0?{k}(?![0-9])|quy\s*0?{k}(?![0-9])|quarter\s*0?{k}(?![0-9])", text) is not None
    if has_q(n):
        s += 4
    else:
        s -= 10
    if any(has_q(k) for k in range(1, 5) if k != n):
        s -= 6
    if "tai chinh" in text or "bctc" in text or "financial" in text:
        s += 2
    if "rieng" in text or "separate" in text:
        s += 2
    if "hop nhat" in text or "consolidated" in text:
        s -= 1                     # ưu tiên riêng lẻ, nhưng hợp nhất vẫn dùng được
    if "soat xet" in text or "ban nien" in text or "kiem toan" in text or "6 thang" in text:
        s -= 3                     # bán niên/ năm không phải quý
    if "thuong nien" in text or "annual" in text:
        s -= 5
    if "atlc" in text or "attc" in text or "ty le an toan" in text:
        s -= 5
    # sai năm → loại
    for other in range(y - 3, y + 2):
        if other != y and str(other) in text and str(y) not in text:
            s -= 4
    return s


_ANCHOR_RE = re.compile(r"""<a\s[^>]*href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _pdf_candidates(page: str, base_url: str, quarter: str) -> list[tuple[int, str]]:
    cands: list[tuple[int, str]] = []
    seen = set()
    for m in _LINK_RE.finditer(page):
        url = urljoin(base_url, html.unescape(m.group(1)))
        if url in seen:
            continue
        seen.add(url)
        # ngữ cảnh = 300 ký tự quanh link, thường chứa tiêu đề
        ctx = page[max(0, m.start() - 300): m.end() + 300]
        ctx = " ".join(t.strip() for t in _TEXT_RE.findall(ctx))
        cands.append((score_candidate(url, ctx, quarter), url))
    cands.sort(reverse=True)
    return cands


def _subpage_candidates(page: str, base_url: str, quarter: str) -> list[tuple[int, str]]:
    """Link nội bộ (không phải .pdf) có tiêu đề giống 'BCTC quý X' — SHS đặt PDF ở trang con."""
    host = re.sub(r"^https?://([^/]+).*$", r"\1", base_url)
    out: list[tuple[int, str]] = []
    seen = set()
    for m in _ANCHOR_RE.finditer(page):
        url = urljoin(base_url, html.unescape(m.group(1)))
        if url in seen or url.lower().endswith(".pdf") or host not in url:
            continue
        seen.add(url)
        text = html.unescape(_TAG_RE.sub(" ", m.group(2)))
        s = score_candidate("", text, quarter)
        if s >= 5:
            out.append((s, url))
    out.sort(reverse=True)
    return out[:4]


def resolve_ir_url(ir_url: str, quarter: str) -> str:
    """ir_url có thể là mẫu theo quý: '.../bao-cao-tai-chinh-quy-{q}-nam-{y}' (SHS dựng trang
    danh sách bằng JS nên không quét được, nhưng trang chi tiết có URL cố định)."""
    y, n = parse(quarter)
    return ir_url.replace("{q}", str(n)).replace("{y}", str(y))


def find_pdf_url(ir_url: str, quarter: str) -> tuple[str, int]:
    """Trả về (url_tốt_nhất, điểm). Ném FetchError nếu không mở được trang hoặc không có ứng viên.
    Trang chính không có PDF hợp → thử tối đa 4 trang con có tiêu đề giống BCTC quý đó."""
    ir_url = resolve_ir_url(ir_url, quarter)
    page = _get_text(ir_url)
    cands = _pdf_candidates(page, ir_url, quarter)
    if cands and cands[0][0] >= 5:
        return cands[0][1], cands[0][0]

    for s, sub in _subpage_candidates(page, ir_url, quarter):
        try:
            sub_page = _get_text(sub)
        except FetchError:
            continue
        sub_c = _pdf_candidates(sub_page, sub, quarter)
        if sub_c and sub_c[0][0] >= 5:
            logger.info("Tìm thấy PDF ở trang con %s", sub)
            return sub_c[0][1], sub_c[0][0]

    if not cands:
        raise FetchError("Trang IR không có link .pdf nào (kể cả trang con)")
    best_score, best = cands[0]
    raise FetchError(f"Không thấy PDF nào giống BCTC {quarter} (ứng viên tốt nhất: {best} · điểm {best_score})")


def _get_text(url: str) -> str:
    last = None
    for attempt in range(RETRIES):
        try:
            with httpx.Client(headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("Tải trang lỗi (lần %d/%d) %s: %s", attempt + 1, RETRIES, url, exc)
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"Không mở được trang IR: {last}")


def download_pdf(url: str, dest: Path) -> tuple[Path, str]:
    """Tải PDF về dest, kiểm tra đúng là PDF, trả về (path, sha256)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(RETRIES):
        try:
            with httpx.Client(headers=BROWSER_HEADERS, timeout=httpx.Timeout(HTTP_TIMEOUT, read=180), follow_redirects=True) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    h = hashlib.sha256()
                    with open(dest, "wb") as f:
                        first = True
                        for chunk in r.iter_bytes(1 << 16):
                            if first:
                                if not chunk.startswith(b"%PDF"):
                                    raise FetchError("Link không trả về PDF (có thể là trang HTML đòi đăng nhập)")
                                first = False
                            f.write(chunk)
                            h.update(chunk)
            return dest, h.hexdigest()
        except FetchError:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("Tải PDF lỗi (lần %d/%d): %s", attempt + 1, RETRIES, exc)
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"Không tải được PDF: {last}")


def pdf_path_for(symbol: str, quarter: str) -> Path:
    return PDF_DIR / f"{symbol.upper()}_{quarter}.pdf"


def fetch(symbol: str, quarter: str, ir_url: str = "", pdf_url: str = "") -> dict:
    """Tải BCTC. Ưu tiên pdf_url (người dùng dán); không có thì tự tìm trên ir_url."""
    if not pdf_url:
        if not ir_url:
            raise FetchError("Chưa cấu hình trang IR cho công ty này")
        pdf_url, _ = find_pdf_url(ir_url, quarter)
    path, sha = download_pdf(pdf_url, pdf_path_for(symbol, quarter))
    return {"url": pdf_url, "path": str(path), "sha256": sha}
