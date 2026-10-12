import datetime as dt

import pandas as pd

from pullback_trader.backtest import DayBacktester, PositionSim, SwingBacktester, summarize
from pullback_trader.data.csv_provider import CsvProvider
from pullback_trader.market.costs import CostModel
from pullback_trader.strategy import detect_pullback, build_plan


def _bars(rows):
    idx = pd.date_range("2026-01-05", periods=len(rows), freq="B")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    df["value"] = df["close"] * df["volume"]
    return df


def _plan(sample_dir, cfg, code="900001"):
    bars = CsvProvider(str(sample_dir)).daily(code, dt.date(2025, 1, 1), dt.date(2027, 1, 1))
    s = detect_pullback(bars, cfg.swing)
    return build_plan(s, cfg, code=code, name="t", market="KOSDAQ", equity=10_000_000)


def test_position_sim_fills_all_tranches_then_stops(sample_dir, cfg):
    plan = _plan(sample_dir, cfg)
    cm = CostModel(cfg.cost)
    sim = PositionSim(plan, cm, valid_bars=3, first_tranche_market=False, move_stop_to_breakeven=True, signal_time=pd.Timestamp("2026-01-02"))
    p1, p4, stop = plan.tranches[0].price, plan.tranches[-1].price, plan.stop_price
    # 1봉: 4차가까지 하락 → 전부 체결. 2봉: 손절 이탈
    t = sim.on_bar(pd.Series({"open": p1, "high": p1 * 1.01, "low": p4 - 1, "close": p4}), pd.Timestamp("2026-01-05"))
    assert t is None and sim.qty == plan.total_qty and len(sim.filled) == 4
    t = sim.on_bar(pd.Series({"open": p4, "high": p4, "low": stop - 10, "close": stop - 10}), pd.Timestamp("2026-01-06"))
    assert t is not None and t.exit_reason == "stop" and t.tranches_filled == 4
    assert t.net_pnl < 0
    # 손실이 계획 리스크(+비용/슬리피지) 근방
    assert abs(t.net_pnl) <= plan.risk_amount_all * 1.3 + 2000


def test_position_sim_partial_then_target2(sample_dir, cfg):
    plan = _plan(sample_dir, cfg)
    cm = CostModel(cfg.cost)
    sim = PositionSim(plan, cm, valid_bars=3, first_tranche_market=False, move_stop_to_breakeven=True, signal_time=pd.Timestamp("2026-01-02"))
    p1 = plan.tranches[0].price
    sim.on_bar(pd.Series({"open": p1, "high": p1, "low": p1 - 1, "close": p1}), pd.Timestamp("2026-01-05"))
    assert sim.qty == plan.tranches[0].qty
    t = sim.on_bar(pd.Series({"open": p1, "high": plan.target1_price + 1, "low": p1, "close": plan.target1_price}), pd.Timestamp("2026-01-06"))
    if plan.target1_price == plan.target2_price:
        assert t is not None and t.exit_reason == "target2"
    else:
        assert t is None and sim.t1_done and not sim.ladder_active and sim.stop >= plan.stop_price
        t = sim.on_bar(pd.Series({"open": plan.target2_price, "high": plan.target2_price + 5, "low": plan.target2_price, "close": plan.target2_price}), pd.Timestamp("2026-01-07"))
        assert t is not None and t.exit_reason == "target2"
    assert t.net_pnl > 0


def test_position_sim_expires_without_fill(sample_dir, cfg):
    plan = _plan(sample_dir, cfg)
    sim = PositionSim(plan, CostModel(cfg.cost), valid_bars=2, first_tranche_market=False, move_stop_to_breakeven=True, signal_time=pd.Timestamp("2026-01-02"))
    hi = plan.tranches[0].price * 1.05
    for d in pd.date_range("2026-01-05", periods=3, freq="B"):
        t = sim.on_bar(pd.Series({"open": hi, "high": hi, "low": hi * 0.999, "close": hi}), d)
    assert t is None and sim.closed and sim.exit_reason == "expired" and sim.qty == 0


def test_swing_backtest_runs(sample_dir, cfg):
    prov = CsvProvider(str(sample_dir))
    uni = prov.universe()
    daily = {c: prov.daily(c, dt.date(2025, 1, 1), dt.date(2027, 1, 1)) for c in uni.code}
    meta = {r.code: {"name": r.name, "market": r.market} for r in uni.itertuples()}
    res = SwingBacktester(cfg, daily, meta).run(dt.date(2025, 11, 1), dt.date(2026, 10, 8))
    s = summarize(res)
    assert res.signals >= 1
    assert s["final_equity"] == res.initial_equity + sum(t.net_pnl for t in res.trades)
    assert len(res.equity_curve) > 100
    for t in res.trades:
        assert 1 <= t.tranches_filled <= 4 and t.exit_reason in {"stop", "breakeven_stop", "target1", "target2", "time", "end"}


def test_day_backtest_runs(sample_dir, cfg):
    prov = CsvProvider(str(sample_dir))
    uni = prov.universe()
    daily = {c: prov.daily(c, dt.date(2025, 1, 1), dt.date(2027, 1, 1)) for c in uni.code}
    meta = {r.code: {"name": r.name, "market": r.market} for r in uni.itertuples()}
    f = sorted((sample_dir / "minute").glob("900001_*.csv"))[0].name.split("_")[1][:8]
    date = dt.date(int(f[:4]), int(f[4:6]), int(f[6:]))
    bt = DayBacktester(cfg, lambda c, d: prov.minute(c, d, cfg.day.bar_minutes), lambda c, d: float(daily[c]["close"].iloc[-1]), meta)
    res = bt.run(list(uni.code), [date])
    assert res.signals >= 1 and len(res.trades) >= 1
    t_exit = dt.time(*map(int, cfg.day.force_exit_time.split(":")))
    for t in res.trades:
        assert t.exit_time.time() <= t_exit or t.exit_reason == "force_exit"
        assert t.entry_time.time() >= dt.time(*map(int, cfg.day.first_entry_time.split(":")))
