import datetime as dt

import pandas as pd
import pytest

from pullback_trader.data.csv_provider import CsvProvider
from pullback_trader.strategy import build_plan, detect_pullback


def _daily(sample_dir, code):
    return CsvProvider(str(sample_dir)).daily(code, dt.date(2025, 1, 1), dt.date(2027, 1, 1))


def test_detects_confirmed_pullback(sample_dir, cfg):
    bars = _daily(sample_dir, "900001")
    rs = []
    s = detect_pullback(bars, cfg.swing, reasons=rs)
    assert s is not None, rs
    assert s.triggered
    assert cfg.swing.retrace_min <= s.retrace <= cfg.swing.retrace_max
    assert s.volume_ratio <= cfg.swing.volume_ratio_max
    assert s.pullback_low < s.close <= s.impulse_high


def test_rejects_without_confirmation_bar(sample_dir, cfg):
    bars = _daily(sample_dir, "900003")  # pullback_wait 패턴
    rs = []
    assert detect_pullback(bars, cfg.swing, reasons=rs) is None
    assert any("반등 확인봉" in r for r in rs)
    cfg.swing.entry_mode = "anticipate"
    s = detect_pullback(bars, cfg.swing)
    assert s is not None and not s.triggered


def test_rejects_downtrend(sample_dir, cfg):
    rs = []
    assert detect_pullback(_daily(sample_dir, "900005"), cfg.swing, reasons=rs) is None
    assert rs


def test_ladder_weights_and_risk(sample_dir, cfg):
    bars = _daily(sample_dir, "900001")
    s = detect_pullback(bars, cfg.swing)
    cfg.risk.max_position_pct = 100  # 리스크 한도만 작동하도록
    plan = build_plan(s, cfg, code="900001", name="t", market="KOSDAQ", equity=10_000_000)
    assert plan.ok
    prices = [t.price for t in plan.tranches]
    assert prices == sorted(prices, reverse=True) and len(set(prices)) == 4
    assert plan.stop_price < prices[-1] and plan.stop_price < s.pullback_low
    q = [t.qty for t in plan.tranches]
    total = sum(q)
    for i, w in enumerate([1, 2, 3, 4]):
        assert abs(q[i] / total - w / 10) < 0.03
    # 전량 체결 후 손절 시 손실 ≈ 계좌의 1% (수량 정수화로 약간 작음)
    assert 0.9 <= plan.risk_pct_all <= 1.0
    assert plan.target1_price <= plan.target2_price
    assert plan.target1_price > prices[0]
    assert abs(sum(t.weight for t in plan.tranches) - 1) < 1e-9


def test_position_cap_binds(sample_dir, cfg):
    s = detect_pullback(_daily(sample_dir, "900002"), cfg.swing)
    plan = build_plan(s, cfg, code="900002", market="KOSDAQ", equity=10_000_000)
    assert plan.total_amount <= 10_000_000 * cfg.risk.max_position_pct / 100 * 1.001
    assert any("최대 투자금" in w for w in plan.warnings)


def test_intraday_detection(sample_dir, cfg):
    prov = CsvProvider(str(sample_dir))
    code = "900001"
    date = sorted(p.name for p in (sample_dir / "minute").glob(f"{code}_*.csv"))[0].split("_")[1][:8]
    date = dt.date(int(date[:4]), int(date[4:6]), int(date[6:]))
    m = prov.minute(code, date, 3)
    assert len(m) > 100
    prev_close = float(_daily(sample_dir, code)["close"].iloc[-1])
    found = None
    for i in range(5, len(m)):
        s = detect_pullback(m.iloc[: i + 1], cfg.day, intraday=True, prev_close=prev_close)
        if s is not None:
            found = (m.index[i], s)
            break
    assert found is not None
    t, s = found
    assert dt.time(9, 30) <= t.time() <= dt.time(11, 0)
    assert s.support_name in ("VWAP", "MA5", "MA20")
    plan = build_plan(s, cfg, code=code, market="KOSDAQ", mode="day")
    assert plan.ok and plan.stop_price < plan.tranches[-1].price


def test_trigger_lookback_accepts_previous_confirmation_bar(sample_dir, cfg):
    """확인봉 다음 봉(보합 양봉)에서도 lookback=1 이면 셋업으로 인정, 0 이면 거부."""
    prov = CsvProvider(str(sample_dir))
    code = "900001"
    f = sorted((sample_dir / "minute").glob(f"{code}_*.csv"))[0].name.split("_")[1][:8]
    date = dt.date(int(f[:4]), int(f[4:6]), int(f[6:]))
    m = prov.minute(code, date, 3)
    prev_close = float(_daily(sample_dir, code)["close"].iloc[-1])
    cfg.day.trigger_lookback_bars = 0
    first = next(i for i in range(5, len(m)) if detect_pullback(m.iloc[: i + 1], cfg.day, intraday=True, prev_close=prev_close))
    # 확인봉 바로 다음 봉: lookback 0 이면 트리거 아님
    nxt = m.iloc[: first + 2]
    assert detect_pullback(nxt, cfg.day, intraday=True, prev_close=prev_close) is None
    cfg.day.trigger_lookback_bars = 1
    s = detect_pullback(nxt, cfg.day, intraday=True, prev_close=prev_close)
    assert s is not None and s.notes == ["확인봉 1봉 전"]
