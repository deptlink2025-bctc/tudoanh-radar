"""VNDirect finfo — dùng cho ba việc, tất cả đã kiểm chứng bằng request thật 13/09/2026:

1. Universe CTCK: `financial_models?q=modelType:90` → trường `codeList` là danh sách mọi
   mã dùng mẫu BCKQKD của CTCK (TT334/2016). bctc-radar hiện drop trường này khi map.
2. Metadata mã: `stocks?q=code:A,B,...` — trả 500 nếu hỏi hơn ~8 mã, nên chia lô 8.
3. Số TỔNG quý (AFS, HTM, TSTC ngắn hạn, tổng tài sản) từ `financial_statements`, lọc
   modelType 89 — dùng để ĐỐI CHIẾU kết quả bóc, không thay được chi tiết từng mã.
"""
from __future__ import annotations

import logging
import time

import httpx

from .config import BROWSER_HEADERS, HTTP_TIMEOUT, VNDIRECT_FINFO
from .quarters import end_date

logger = logging.getLogger(__name__)

MODEL_BS_SEC = 89      # bảng cân đối kế toán — chứng khoán
MODEL_IS_SEC = 90      # kết quả kinh doanh — chứng khoán

# itemCode trong modelType 89 (đọc từ financial_models?q=modelType:89)
ITEM_TOTAL_ASSETS = 12700
ITEM_ST_FIN_ASSETS = 700000    # Tài sản tài chính ngắn hạn (chứa FVTPL + AFS + HTM + cho vay)
ITEM_AFS = 700002
ITEM_HTM = 412320

# Mã dùng chung mẫu CTCK nhưng không phải công ty chứng khoán — loại khỏi universe.
NOT_A_BROKER = {"IPA", "TVC", "EVF", "PCB", "PIV", "DCV", "TIN", "API"}


def _get(client: httpx.Client, path: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = client.get(f"{VNDIRECT_FINFO}/{path}", params=params)
            if r.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            if attempt == retries - 1:
                raise
            logger.warning("finfo %s lỗi (lần %d): %s", path, attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    return {}


def _client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, headers=BROWSER_HEADERS)


def broker_universe() -> list[dict]:
    """Mọi CTCK đang niêm yết: [{code, name, floor}], sắp theo sàn rồi mã."""
    with _client() as c:
        models = _get(c, "financial_models", {"q": f"modelType:{MODEL_IS_SEC}", "size": 5})
        code_list = (models.get("data") or [{}])[0].get("codeList") or ""
        codes = sorted({x for x in code_list.split(",") if len(x) == 3 and x.isalpha() and x.isupper()})
        codes = [x for x in codes if x not in NOT_A_BROKER]

        out: list[dict] = []
        for i in range(0, len(codes), 8):
            chunk = codes[i:i + 8]
            j = _get(c, "stocks", {"q": "code:" + ",".join(chunk), "size": 50})
            for s in j.get("data") or []:
                if s.get("type") == "STOCK" and s.get("status") == "listed" and s.get("floor") in ("HOSE", "HNX", "UPCOM"):
                    out.append({"code": s["code"], "name": (s.get("companyName") or "").strip(), "floor": s["floor"]})
            time.sleep(0.3)
    order = {"HOSE": 0, "HNX": 1, "UPCOM": 2}
    out.sort(key=lambda s: (order[s["floor"]], s["code"]))
    return out


def stock_meta(codes: list[str]) -> dict[str, dict]:
    """{code: {floor, status, type, name}} — dùng để kiểm tra mã bóc ra có niêm yết không."""
    res: dict[str, dict] = {}
    codes = sorted({c.upper() for c in codes if c})
    with _client() as c:
        for i in range(0, len(codes), 8):
            chunk = codes[i:i + 8]
            try:
                j = _get(c, "stocks", {"q": "code:" + ",".join(chunk), "size": 50})
            except httpx.HTTPError:
                continue
            for s in j.get("data") or []:
                res[s["code"]] = {
                    "floor": s.get("floor"), "status": s.get("status"),
                    "type": s.get("type"), "name": (s.get("companyName") or "").strip(),
                }
            time.sleep(0.3)
    return res


def quarter_totals(symbol: str, quarter: str) -> dict | None:
    """Số tổng trên CĐKT của một CTCK tại cuối quý (VND). None nếu finfo chưa có kỳ đó."""
    fd = end_date(quarter).isoformat()
    q = f"code:{symbol.upper()}~reportType:QUARTER~fiscalDate:gte:{fd}~fiscalDate:lte:{fd}"
    with _client() as c:
        j = _get(c, "financial_statements", {"q": q, "size": 5000, "page": 1, "sort": "fiscalDate"})
    rows = [r for r in j.get("data") or [] if int(r.get("modelType") or 0) == MODEL_BS_SEC]
    if not rows:
        return None
    by = {int(r["itemCode"]): float(r.get("numericValue") or 0) for r in rows if r.get("itemCode") is not None}
    return {
        "fiscalDate": fd,
        "total_assets": by.get(ITEM_TOTAL_ASSETS),
        "st_fin_assets": by.get(ITEM_ST_FIN_ASSETS),
        "afs": by.get(ITEM_AFS),
        "htm": by.get(ITEM_HTM),
    }
