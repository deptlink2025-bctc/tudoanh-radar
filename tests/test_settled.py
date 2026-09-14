"""Nguồn DNSE chưa chốt nến hôm nay (bẫy 14/09/2026): job phải nhận ra và không ghi giá giữa phiên."""
from datetime import date, datetime, timedelta

from common import dnse
from common.config import TZ
from job import run_daily

D = date(2026, 9, 14)  # thứ Hai


def _min(h, m, c=58.2, v=1000):
    t = int(datetime(2026, 9, 14, h, m, tzinfo=TZ).timestamp())
    return {"d": D, "o": c, "h": c, "l": c, "c": c, "v": v, "t": t}


def _minutes(until_h, until_m):
    """Nến 1' 09:15 → mốc cho trước, mỗi phút một nến (bỏ nghỉ trưa)."""
    out, cur = [], datetime(2026, 9, 14, 9, 15, tzinfo=TZ)
    end = datetime(2026, 9, 14, until_h, until_m, tzinfo=TZ)
    while cur <= end:
        if not (11 <= cur.hour < 13 and (cur.hour == 12 or cur.minute >= 30)):
            out.append(_min(cur.hour, cur.minute))
        cur += timedelta(minutes=1)
    return out


def test_session_settled_can_nen_atc():
    assert dnse.session_settled(_minutes(13, 49)) is False      # đúng ca 14/09/2026
    assert dnse.session_settled(_minutes(14, 29)) is False      # hết khớp liên tục, chưa ATC
    assert dnse.session_settled(_minutes(14, 29) + [_min(14, 45)]) is True
    assert dnse.session_settled([]) is False


def test_merge_today_lay_ban_nhieu_khoi_luong_hon():
    minutes = _minutes(14, 29) + [_min(14, 45, c=58.5)]
    agg = dnse.aggregate_minutes(minutes)
    stale_1d = {"d": D, "o": 58.2, "h": 58.7, "l": 58.0, "c": 58.2, "v": agg["v"] // 2, "t": 0}
    assert dnse.merge_today(stale_1d, minutes)["c"] == 58.5
    full_1d = {"d": D, "o": 58.2, "h": 58.8, "l": 58.0, "c": 58.5, "v": agg["v"] * 2, "t": 0}
    assert dnse.merge_today(full_1d, minutes) is full_1d
    # Nến 1' của ngày khác hoặc rỗng → giữ 1D
    assert dnse.merge_today(full_1d, []) is full_1d


class _FakeClient:
    def __init__(self, daily, minutes):
        self._d, self._m, self.calls = daily, minutes, []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def daily(self, s):
        self.calls.append(("1D", s))
        return list(self._d.get(s, []))

    def today_minutes(self, s):
        self.calls.append(("1", s))
        return list(self._m.get(s, []))


def _daily(last_d, c=58.2, v=2_903_300):
    return [{"d": last_d - timedelta(days=1), "o": 58, "h": 58, "l": 58, "c": 58.0, "v": 4_000_000, "t": 1},
            {"d": last_d, "o": 58.2, "h": 58.7, "l": 58.0, "c": c, "v": v, "t": 2}]


def test_fetch_bars_bao_nguon_chua_chot_khi_nhieu_ma_thieu_atc(monkeypatch):
    """Ca 14/09/2026: mọi mã thanh khoản dừng ở 13:49 → nguồn chưa chốt."""
    monkeypatch.setattr(dnse, "today_vn", lambda: D)
    fake = _FakeClient({"VCB": _daily(D), "HPG": _daily(D), "TDM": _daily(D, c=59.0, v=800)},
                       {"VCB": _minutes(13, 49), "HPG": _minutes(13, 49),
                        # TDM chỉ 4 nến — không được bỏ phiếu
                        "TDM": [_min(9, 15), _min(14, 21), _min(14, 22), _min(14, 24)]})
    bars, unsettled = run_daily.fetch_bars(["VCB", "HPG", "TDM"], client=fake)
    assert unsettled == ["HPG", "VCB"]
    assert bars["VCB"][-1]["d"] == D


def test_fetch_bars_mot_ma_thanh_khoan_thap_thieu_atc_khong_chan_job(monkeypatch):
    """Nguồn đã chốt (đa số có ATC) thì mã lẻ thiếu ATC chỉ là không khớp lệnh ATC."""
    monkeypatch.setattr(dnse, "today_vn", lambda: D)
    liquid = {s: _minutes(14, 29) + [_min(14, 45, c=20.9, v=10**7)] for s in ["A", "B", "C", "D", "E"]}
    liquid["TDM"] = _minutes(14, 20)               # ≥30 nến nhưng không có ATC — 1/6 < 20%
    fake = _FakeClient({s: _daily(D) for s in liquid}, liquid)
    bars, unsettled = run_daily.fetch_bars(list(liquid), client=fake)
    assert unsettled == []
    assert bars["A"][-1]["c"] == 20.9              # bản gộp có ATC, nhiều KL hơn → thay 1D


def test_fetch_bars_khong_hoi_1phut_khi_nen_cuoi_khong_phai_hom_nay(monkeypatch):
    monkeypatch.setattr(dnse, "today_vn", lambda: date(2026, 9, 15))
    fake = _FakeClient({"VCB": _daily(D)}, {"VCB": _minutes(13, 49)})
    bars, unsettled = run_daily.fetch_bars(["VCB"], client=fake)
    assert unsettled == [] and ("1", "VCB") not in fake.calls


def test_fetch_bars_ma_khong_khop_lenh_thi_giu_1D(monkeypatch):
    monkeypatch.setattr(dnse, "today_vn", lambda: D)
    fake = _FakeClient({"IDP": _daily(D, c=40.0, v=0)}, {})
    bars, unsettled = run_daily.fetch_bars(["IDP"], client=fake)
    assert unsettled == [] and bars["IDP"][-1]["c"] == 40.0


def test_run_khong_ghi_file_khi_nguon_chua_chot(tmp_path, monkeypatch):
    """Ca 14/09/2026: phải thoát 0 (để commit state.json) mà KHÔNG tạo daily/<ngày>.json."""
    daily_dir = tmp_path / "daily"
    monkeypatch.setattr(run_daily, "DAILY", daily_dir)
    monkeypatch.setattr(run_daily, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(run_daily, "LATEST", tmp_path / "latest.json")
    monkeypatch.setattr(run_daily, "HOLDINGS", tmp_path / "holdings.json")
    hold = {"generated_at": "x", "brokers": [{"symbol": "BSI", "enabled": True}],
            "reports": [{"broker": "BSI", "quarter": "2026Q2", "stmt_type": "rieng", "approved_at": "x",
                         "holdings": [{"ticker": "VCB", "is_listed": True, "quantity": 100, "fair_value": 5e6}]}]}
    (tmp_path / "holdings.json").write_text(__import__("json").dumps(hold), encoding="utf-8")
    monkeypatch.setattr(run_daily, "fetch_bars", lambda tickers: ({"VCB": _daily(D)}, ["VCB"]))
    monkeypatch.setattr(run_daily.settings, "load", lambda: {"r1_pct": 7, "r1_min_value": 2e10, "r2_value": 1e11,
                                                             "r3_weight": .2, "r3_pct": 6.5, "r4_pct": 15})

    assert run_daily.run(no_push=True) == 0
    assert not (daily_dir / "2026-09-14.json").exists()
    assert not (tmp_path / "latest.json").exists()
    st = __import__("json").loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert st["unsettled"]["tickers"] == ["VCB"] and st["unsettled"]["trade_date"] == "2026-09-14"

    # --force thì vẫn ghi, nhưng khai rõ mã dùng giá chưa chốt
    assert run_daily.run(force=True, no_push=True) == 0
    assert (daily_dir / "2026-09-14.json").exists()
    latest = __import__("json").loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["source"]["unsettled"] == ["VCB"]
    st = __import__("json").loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "unsettled" not in st
