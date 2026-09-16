"""Job sau phiên — chạy trong GitHub Actions 15:20 T2–T6 (hoặc local: python -m job.run_daily).

Luồng: holdings.json → giá DNSE cho mọi mã đang giữ → định giá từng công ty → so sánh 2 quý →
soi 4 quy tắc → Web Push → ghi data/latest.json, data/state.json, data/daily/<ngày>.json.

Idempotent: nếu hôm nay đã có file daily và không có --force thì thoát (các cron dự phòng chạy
lại chỉ khi lần trước bị GitHub trễ/bỏ hoặc nguồn chưa chốt). Ngày không có phiên (lễ) → ghi
'no_session', không bắn.

Nguồn chưa chốt: 14/09/2026 DNSE sau 15:00 vẫn trả nến hôm đó dừng ở ~13:45 (HTTP 200), job
15:32 ghi 29/37 giá sai. Giờ mỗi mã có nến hôm nay phải có thêm nến 1' chạm ATC 14:45 mới được
tin; thiếu thì KHÔNG ghi file hôm nay, để cron sau (15:50, 16:30, 18:00) thử lại. --force bỏ qua.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from common import dnse, quarters
from common.config import SITE_DATA, TZ

from . import diff as diffmod
from . import push, rules, settings, valuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("job")

HOLDINGS = SITE_DATA / "holdings.json"
LATEST = SITE_DATA / "latest.json"
STATE = SITE_DATA / "state.json"
DAILY = SITE_DATA / "daily"


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _dump(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


# Mã có ít nhất ngần này nến 1' trong ngày mới đủ thanh khoản để "bỏ phiếu" nguồn đã chốt
# chưa. TDM ngày 14/09/2026 chỉ có 4 nến và không khớp ATC — xét từng mã sẽ báo nhầm mãi.
LIQUID_MIN_BARS = 30
# Tỷ lệ mã thanh khoản thiếu nến ATC từ mức này trở lên → coi nguồn chưa chốt (14/09/2026: 100%).
UNSETTLED_RATIO = 0.2


def fetch_bars(tickers: list[str], client=None) -> tuple[dict[str, list[dict]], list[str]]:
    """Nến ngày cho từng mã + danh sách mã thanh khoản mà nến HÔM NAY chưa chốt (rỗng = nguồn ổn).

    Mã nào có nến ngày của hôm nay thì lấy thêm nến 1' hôm nay; nến hôm nay là bản nhiều khối
    lượng hơn giữa 1D và bản gộp 1'. Nguồn bị coi là chưa chốt khi ≥ UNSETTLED_RATIO số mã
    thanh khoản chưa có nến ATC — mã ít khớp lệnh (UPCOM, mã nhỏ) không được tính.
    """
    bars: dict[str, list[dict]] = {}
    voters: list[str] = []
    lacking: list[str] = []
    today = dnse.today_vn()
    with (client or dnse.DnseClient(days=400)) as c:
        for i, t in enumerate(sorted(tickers), 1):
            b = c.daily(t)
            if not b:
                continue
            if b[-1]["d"] == today:
                minutes = c.today_minutes(t)
                if len(minutes) >= LIQUID_MIN_BARS:
                    voters.append(t)
                    if not dnse.session_settled(minutes):
                        lacking.append(t)
                b[-1] = dnse.merge_today(b[-1], minutes)
            bars[t] = b
            if i % 25 == 0:
                log.info("giá: %d/%d mã", i, len(tickers))
    unsettled = lacking if voters and len(lacking) / len(voters) >= UNSETTLED_RATIO else []
    if lacking and not unsettled:
        log.info("Mã thiếu nến ATC nhưng nguồn nhìn chung đã chốt (%d/%d): %s",
                 len(lacking), len(voters), ", ".join(lacking))
    return bars, unsettled


def run(force: bool = False, dry_run: bool = False, no_push: bool = False) -> int:
    now = datetime.now(TZ)
    st = _load(STATE, {})
    hold = _load(HOLDINGS, None)
    if not hold or not hold.get("reports"):
        log.error("Chưa có data/holdings.json hoặc chưa có báo cáo nào đã chốt")
        return 2

    # Máy mới đăng ký (địa chỉ chưa thấy bao giờ) → gửi ngay một thông báo chào mừng, TRƯỚC cả
    # bước idempotent bên dưới, để người dùng chỉ cần "Re-run" là biết đường dây thông.
    if not dry_run and not no_push:
        _welcome_new_devices(st, now)

    cfg = settings.load()
    disabled = set(cfg.get("brokers_disabled") or [])
    brokers = [b for b in hold["brokers"] if b.get("enabled") and b["symbol"] not in disabled]
    reports = hold["reports"]

    # --- giá ---
    tickers = sorted({h["ticker"] for r in reports for h in r["holdings"] if h.get("ticker") and h.get("is_listed")})
    log.info("Lấy giá %d mã cho %d công ty", len(tickers), len(brokers))
    bars, unsettled = fetch_bars(tickers)
    if not bars:
        log.error("DNSE không trả về gì: %s", dnse.last_error)
        st["dnse_error"], st["last_run"] = dnse.last_error, now.isoformat(timespec="seconds")
        _dump(STATE, st)
        return 3
    trade_date = max(b[-1]["d"] for b in bars.values())
    trade_iso = trade_date.isoformat()
    daily_file = DAILY / f"{trade_iso}.json"
    if daily_file.exists() and not force:
        log.info("Đã có %s — không chạy lại (dùng --force nếu muốn)", daily_file.name)
        return 0
    if unsettled and not force:
        # Ghi file lúc này là ghi giá giữa phiên rồi giữ tới hôm sau (đã xảy ra 14/09/2026).
        # Không ghi; cron dự phòng sẽ thử lại. Thoát 0 để bước commit vẫn đẩy state.json.
        msg = (f"Nguồn chưa chốt phiên {trade_iso}: {len(unsettled)}/{len(bars)} mã chưa có nến ATC "
               f"({', '.join(unsettled[:8])}{'…' if len(unsettled) > 8 else ''}) — chờ cron sau")
        log.warning(msg)
        st.update({"last_run": now.isoformat(timespec="seconds"), "unsettled": {"trade_date": trade_iso,
                   "tickers": unsettled, "at": now.isoformat(timespec="seconds")}})
        _dump(STATE, st)
        return 0
    st.pop("unsettled", None)
    if (now.date() - trade_date).days > 4:
        log.warning("Phiên gần nhất %s cách hôm nay quá 4 ngày — DNSE có thể chưa cập nhật", trade_iso)

    # --- định giá từng công ty ---
    out_brokers: list[dict] = []
    diffs: dict[str, dict] = {}
    all_alerts: list[dict] = []
    r4_state = st.setdefault("r4", {})
    for b in brokers:
        sym = b["symbol"]
        rep = valuation.latest_report(reports, sym)
        entry = {"symbol": sym, "name": b.get("name", ""), "floor": b.get("floor", ""), "quarter": None,
                 "detail": False, "manual": False, "size": None, "totals": {}, "n_tracked": 0,
                 "today": None, "since_quarter": None, "vs_cost": None, "holdings": [], "other_fair": 0.0,
                 "diff": None, "alerts": []}
        if rep is None:
            entry["pending"] = True
            out_brokers.append(entry)
            continue
        qend = quarters.end_date(rep["quarter"])
        val = valuation.value_holdings(rep["holdings"], bars, qend, trade_date=trade_date)
        entry.update({
            "quarter": rep["quarter"], "approved_at": rep.get("approved_at"), "stmt_type": rep.get("stmt_type"),
            "detail": val["n_tracked"] > 0,
            "manual": any(h.get("quantity_source") == "manual" or h.get("fair_source") == "manual" for h in rep["holdings"]),
            "totals": rep.get("totals") or {},
            "size": (rep.get("totals") or {}).get("st_fin_assets") or (sum(h.get("fair_value") or 0 for h in rep["holdings"]) or None),
            "n_tracked": val["n_tracked"], "today": val["today"], "since_quarter": val["since_quarter"],
            "vs_cost": val["vs_cost"], "holdings": val["tracked"], "other_fair": val["other_fair"],
        })
        # diff với quý trước
        prev_rep = valuation.report_for(reports, sym, quarters.prev(rep["quarter"]))
        if prev_rep is not None:
            closes_cur = {t: dnse.close_on_or_before(bb, qend) for t, bb in bars.items()}
            d = diffmod.diff_quarters(prev_rep["holdings"], rep["holdings"], {k: v for k, v in closes_cur.items() if v})
            d["prev_quarter"] = prev_rep["quarter"]
            entry["diff"] = d
            diffs[sym] = d
        # cảnh báo
        alerts, r4_state[sym] = rules.evaluate(sym, val, cfg, r4_state.get(sym) or {})
        entry["alerts"] = alerts
        all_alerts.extend(alerts)
        out_brokers.append(entry)

    # --- toàn ngành ---
    with_today = [b for b in out_brokers if b["today"]]
    industry = {
        "today_change": sum(b["today"]["change"] for b in with_today),
        "n_today": len(with_today),
        "vs_cost_change": sum(b["vs_cost"]["change"] for b in out_brokers if b["vs_cost"]),
        "size_total": sum(b["size"] or 0 for b in out_brokers),
        "rollup": diffmod.industry_rollup(diffs),
        "n_with_diff": len(diffs),
        "buy": sum(d["buy"] for d in diffs.values()), "sell": sum(d["sell"] for d in diffs.values()),
    }
    hot_first = sorted(all_alerts, key=lambda a: (not a["hot"], a["rule"]))

    latest = {
        "generated_at": now.isoformat(timespec="seconds"), "trade_date": trade_iso,
        "holdings_generated_at": hold.get("generated_at"),
        "source": {"dnse_ok": bool(dnse.last_ok), "dnse_error": dnse.last_error, "n_tickers": len(tickers), "n_priced": len(bars),
                   # Mã ghi bằng giá chưa chốt (chỉ có khi --force ép chạy lúc nguồn còn thiếu)
                   "unsettled": unsettled},
        "settings": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "brokers": out_brokers, "industry": industry, "alerts": hot_first,
    }

    # --- push ---
    push_res = {"skipped": True}
    if not dry_run and not no_push:
        subs, src = push.subscriptions()
        push_res = {"source": src, "n_devices": len(subs), "sent": 0, "gone": 0, "failed": 0, "errors": []}
        if subs and push.configured():
            for a in hot_first:
                r = push.send(push.alert_payload(a), subs)
                for k in ("sent", "gone", "failed"):
                    push_res[k] += r[k]
                push_res["errors"] += r["errors"]
            if now.weekday() == 0:  # thứ Hai: nhịp tim
                week_n = _alerts_last_week(now) + len(hot_first)
                r = push.send(push.heartbeat_payload(week_n, trade_iso), subs)
                push_res["heartbeat"] = r["sent"]
            if push.test_requested():
                push_res["test"] = push.send(push.test_payload(), subs)["sent"]
        elif not push.configured():
            push_res["errors"].append("Thiếu khoá VAPID")
        if push_res.get("gone"):
            st["push_gone_at"] = now.isoformat(timespec="seconds")
    latest["push"] = push_res

    if dry_run:
        print(json.dumps({k: v for k, v in latest.items() if k != "brokers"}, ensure_ascii=False, indent=1, default=str))
        for b in out_brokers:
            t = b["today"]
            print(f"  {b['symbol']:4} {b['quarter'] or '-':7} theo dõi {b['n_tracked']:2} mã · hôm nay "
                  f"{(t['change'] / 1e9):+9.1f} tỷ ({t['pct']:+.2f}%)" if t else f"  {b['symbol']:4} không tính được")
        return 0

    _dump(LATEST, latest)
    _dump(daily_file, {"trade_date": trade_iso, "generated_at": latest["generated_at"], "industry": industry,
                       "alerts": hot_first,
                       "brokers": [{k: b[k] for k in ("symbol", "quarter", "n_tracked", "today", "since_quarter", "vs_cost")} for b in out_brokers]})
    st.update({"last_run": now.isoformat(timespec="seconds"), "last_trade_date": trade_iso,
               "dnse_error": dnse.last_error, "push": push_res})
    _dump(STATE, st)
    log.info("Xong: %d công ty, %d cảnh báo, push %s", len(out_brokers), len(hot_first), push_res)
    return 0


def _welcome_new_devices(st: dict, now: datetime) -> None:
    subs, src = push.subscriptions()
    st["devices"] = {"n": len(subs), "source": src, "vapid": push.configured(), "checked_at": now.isoformat(timespec="seconds")}
    if not subs or not push.configured():
        _dump(STATE, st)
        return
    known = set(st.get("known_subs") or [])
    new = [s for s in subs if push._sub_id(s) not in known]
    if new:
        payload = {"kind": "welcome", "title": "Đã kết nối — máy này sẽ nhận cảnh báo",
                   "body": "Cảnh báo sau phiên 15:20 các ngày T2–T6, nhịp tim mỗi thứ Hai.", "url": "./#alert", "tag": "td-welcome"}
        r = push.send(payload, new)
        log.info("Chào mừng %d máy mới (nguồn %s): %s", len(new), src, r)
        st["welcome"] = {"at": now.isoformat(timespec="seconds"), **r}
    st["known_subs"] = sorted(known | {push._sub_id(s) for s in subs})
    _dump(STATE, st)


def _alerts_last_week(now: datetime) -> int:
    n = 0
    for i in range(1, 8):
        f = DAILY / f"{(now - timedelta(days=i)).date().isoformat()}.json"
        if f.exists():
            try:
                n += len(json.loads(f.read_text(encoding="utf-8")).get("alerts") or [])
            except Exception:  # noqa: BLE001
                pass
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="chạy lại dù hôm nay đã có file")
    ap.add_argument("--dry-run", action="store_true", help="in kết quả, không ghi file, không push")
    ap.add_argument("--no-push", action="store_true", help="ghi file nhưng không gửi thông báo")
    a = ap.parse_args()
    sys.exit(run(force=a.force, dry_run=a.dry_run, no_push=a.no_push))


if __name__ == "__main__":
    main()
