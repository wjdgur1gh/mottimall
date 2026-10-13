"""백테스트 엔진.

- PositionSim      : 플랜(사다리 1~4차 + 손절 + 1·2차 목표) 하나의 생애주기를 봉 단위로 시뮬레이션
- SwingBacktester  : 일봉. 매일 종가에서 셋업 탐지 → 다음 날부터 사다리 체결/청산
- DayBacktester    : 분봉. 장중 봉마다 탐지, 강제청산 시각에 전량 청산

체결 가정 (보수적)
- 매수 지정가: 봉 저가 <= 주문가 → 체결가 = min(시가, 주문가)
- 손절: 봉 저가 <= 손절가 → 체결가 = min(시가, 손절가) − 슬리피지. 같은 봉에서 목표가도 닿으면 손절 우선
- 목표: 봉 고가 >= 목표가 → 체결가 = max(시가, 목표가)
- 사다리 체결과 손절이 같은 봉에서 발생하면 '체결 후 손절' 로 처리 (최악 가정)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from ..config import AppConfig
from ..market.costs import CostModel
from ..market.tick import round_to_tick
from ..strategy.pullback import detect_pullback
from ..strategy.sizing import OrderPlan, build_plan


@dataclass
class Trade:
    code: str
    name: str
    market: str
    mode: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    tranches_filled: int
    qty: int
    avg_entry: float
    avg_exit: float
    gross_pnl: float
    costs: float
    net_pnl: float
    pnl_pct: float
    r_multiple: float
    exit_reason: str
    bars_held: int
    score: float
    risk_planned: float
    mae_pct: float
    mfe_pct: float


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: pd.Series
    initial_equity: float
    final_equity: float
    mode: str
    signals: int = 0
    expired_ladders: int = 0
    pending_ladders: int = 0   # 기간 종료 시점에 아직 봉을 받지 못한 신규 사다리 (마지막 날 신호)
    notes: List[str] = field(default_factory=list)


class PositionSim:
    def __init__(self, plan: OrderPlan, cost_model: CostModel, *, valid_bars: int,
                 first_tranche_market: bool, move_stop_to_breakeven: bool, signal_time: pd.Timestamp):
        self.plan = plan
        self.cm = cost_model
        self.valid_bars = valid_bars
        self.first_market = first_tranche_market
        self.move_be = move_stop_to_breakeven
        self.signal_time = signal_time
        self.filled: List[Tuple[int, float, int]] = []
        self.qty = 0
        self.avg = 0.0
        self.costs = 0.0
        self.realized = 0.0
        self.exit_value = 0.0
        self.exit_qty = 0
        self.stop = plan.stop_price
        self.t1, self.t2 = plan.target1_price, plan.target2_price
        self.t1_done = False
        self.ladder_active = True
        self.bars = 0
        self.bars_held = 0
        self.entry_time: Optional[pd.Timestamp] = None
        self.closed = False
        self.exit_reason = ""
        self.max_price = 0.0
        self.min_price = float("inf")

    # ------------------------------------------------------------ helpers
    def _buy(self, level: int, price: float, qty: int, when: pd.Timestamp) -> None:
        amount = price * qty
        self.costs += self.cm.buy_fee(amount)
        self.avg = (self.avg * self.qty + amount) / (self.qty + qty)
        self.qty += qty
        self.filled.append((level, price, qty))
        if self.entry_time is None:
            self.entry_time = when

    def _sell(self, price: float, qty: int) -> None:
        qty = min(qty, self.qty)
        amount = price * qty
        self.costs += self.cm.sell_fee(amount, self.plan.market)
        self.realized += (price - self.avg) * qty
        self.exit_value += amount
        self.exit_qty += qty
        self.qty -= qty

    def unrealized(self, price: float) -> float:
        return (price - self.avg) * self.qty if self.qty else 0.0

    def _make_trade(self, when: pd.Timestamp, reason: str) -> Trade:
        self.closed = True
        self.exit_reason = reason
        gross = self.realized
        net = gross - self.costs
        total_qty = sum(q for _, _, q in self.filled)
        invested = sum(p * q for _, p, q in self.filled)
        risk = self.plan.risk_amount_all if self.plan.risk_amount_all > 0 else max(invested * 0.01, 1)
        return Trade(
            code=self.plan.code, name=self.plan.name, market=self.plan.market, mode=self.plan.mode,
            signal_time=self.signal_time, entry_time=self.entry_time or when, exit_time=when,
            tranches_filled=len(self.filled), qty=total_qty, avg_entry=invested / total_qty if total_qty else 0.0,
            avg_exit=self.exit_value / self.exit_qty if self.exit_qty else 0.0,
            gross_pnl=gross, costs=self.costs, net_pnl=net,
            pnl_pct=net / invested * 100 if invested else 0.0,
            r_multiple=net / risk, exit_reason=reason, bars_held=self.bars_held, score=self.plan.score,
            risk_planned=self.plan.risk_amount_all,
            mae_pct=(self.min_price / self.avg - 1) * 100 if self.avg and self.min_price < float("inf") else 0.0,
            mfe_pct=(self.max_price / self.avg - 1) * 100 if self.avg else 0.0,
        )

    # ------------------------------------------------------------ main
    def on_bar(self, bar: pd.Series, when: pd.Timestamp) -> Optional[Trade]:
        if self.closed:
            return None
        self.bars += 1
        o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])

        # 1) 사다리 체결
        if self.ladder_active:
            if self.bars > self.valid_bars and not self.filled:
                self.ladder_active = False
                self.closed = True
                self.exit_reason = "expired"
                return None
            if self.bars > self.valid_bars:
                self.ladder_active = False
            else:
                done = {lv for lv, _, _ in self.filled}
                for t in self.plan.tranches:
                    if t.level in done or t.qty <= 0:
                        continue
                    if t.level == 1 and self.first_market and self.bars == 1:
                        self._buy(1, self.cm.slippage(o, "buy"), t.qty, when)
                    elif l <= t.price:
                        self._buy(t.level, min(o, t.price), t.qty, when)
        if self.qty <= 0:
            return None
        self.bars_held += 1
        self.max_price = max(self.max_price, h)
        self.min_price = min(self.min_price, l)

        # 2) 손절 (우선)
        if l <= self.stop:
            px = self.cm.slippage(min(o, self.stop), "sell")
            self._sell(px, self.qty)
            self.ladder_active = False
            return self._make_trade(when, "breakeven_stop" if self.t1_done else "stop")

        # 3) 목표
        if not self.t1_done and h >= self.t1:
            q1 = int(round(self.qty * self.plan.partial_exit_ratio))
            q1 = max(1, min(q1, self.qty))
            self._sell(max(o, self.t1), q1)
            self.t1_done = True
            self.ladder_active = False
            if self.move_be:
                self.stop = max(self.stop, round_to_tick(self.avg, "down"))
            if self.qty == 0:
                return self._make_trade(when, "target1")
        if self.t1_done and self.qty > 0 and h >= self.t2:
            self._sell(max(o, self.t2), self.qty)
            return self._make_trade(when, "target2")
        return None

    def force_exit(self, price: float, when: pd.Timestamp, reason: str) -> Optional[Trade]:
        if self.closed:
            return None
        self.ladder_active = False
        if self.qty <= 0:
            self.closed = True
            self.exit_reason = "expired"
            return None
        self._sell(self.cm.slippage(price, "sell"), self.qty)
        return self._make_trade(when, reason)


# ======================================================================================
class SwingBacktester:
    def __init__(self, cfg: AppConfig, daily: Dict[str, pd.DataFrame], meta: Optional[Dict[str, Dict]] = None,
                 window_bars: int = 130):
        self.cfg = cfg
        self.cm = CostModel(cfg.cost)
        self.daily = {c: df for c, df in daily.items() if df is not None and len(df) > 0}
        self.meta = meta or {}
        self.window = window_bars

    def run(self, start: dt.date, end: dt.date, initial_equity: Optional[float] = None,
            progress: Optional[Callable[[str], None]] = None) -> BacktestResult:
        cfg, pb = self.cfg, self.cfg.swing
        equity = float(initial_equity or cfg.risk.account_equity)
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        all_dates = sorted({d for df in self.daily.values() for d in df.index if start_ts <= d <= end_ts})
        sims: Dict[str, PositionSim] = {}
        trades: List[Trade] = []
        curve: Dict[pd.Timestamp, float] = {}
        signals = expired = 0
        for d in all_dates:
            # (a) 기존 포지션/사다리
            for code, sim in list(sims.items()):
                df = self.daily[code]
                if d not in df.index:
                    continue
                bar = df.loc[d]
                trade = sim.on_bar(bar, d)
                if trade is None and not sim.closed and sim.qty > 0 and sim.bars_held >= pb.max_hold_days:
                    trade = sim.force_exit(float(bar["close"]), d, "time")
                if trade is not None:
                    trades.append(trade)
                    equity += trade.net_pnl
                    del sims[code]
                elif sim.closed:
                    expired += 1
                    del sims[code]
            # (b) 신규 신호 (종가 기준)
            slots = cfg.risk.max_open_positions - len(sims)
            if slots > 0:
                cands = []
                for code, df in self.daily.items():
                    if code in sims or d not in df.index:
                        continue
                    pos = df.index.get_loc(d)
                    if pos < pb.trend_ma_slow + 2:
                        continue
                    window = df.iloc[max(0, pos - self.window + 1): pos + 1]
                    setup = detect_pullback(window, pb)
                    if setup is not None:
                        cands.append((setup.score, code, setup))
                cands.sort(key=lambda x: -x[0])
                for score, code, setup in cands[:slots]:
                    m = self.meta.get(code, {})
                    plan = build_plan(setup, cfg, code=code, name=m.get("name", code), market=m.get("market", "KOSPI"),
                                      equity=equity, mode="swing", valid_until=f"{pb.ladder_valid_days}일")
                    signals += 1
                    if plan.ok:
                        sims[code] = PositionSim(plan, self.cm, valid_bars=pb.ladder_valid_days,
                                                 first_tranche_market=pb.first_tranche_market,
                                                 move_stop_to_breakeven=pb.move_stop_to_breakeven_after_t1, signal_time=d)
            # (c) 평가 자산
            unreal = 0.0
            for code, sim in sims.items():
                df = self.daily[code]
                if d in df.index:
                    unreal += sim.unrealized(float(df.loc[d, "close"]))
            curve[d] = equity + unreal
            if progress and len(curve) % 50 == 0:
                progress(f"{d.date()} equity {equity + unreal:,.0f} trades {len(trades)}")
        # 미청산 포지션 정리
        pending = 0
        for code, sim in sims.items():
            df = self.daily[code]
            last = df.loc[df.index <= end_ts]
            if len(last) and sim.qty > 0:
                t = sim.force_exit(float(last["close"].iloc[-1]), last.index[-1], "end")
                if t:
                    trades.append(t)
                    equity += t.net_pnl
            elif sim.bars == 0:
                pending += 1
        series = pd.Series(curve, dtype="float64").sort_index()
        return BacktestResult(trades=trades, equity_curve=series, initial_equity=float(initial_equity or cfg.risk.account_equity),
                              final_equity=equity, mode="swing", signals=signals, expired_ladders=expired, pending_ladders=pending)


# ======================================================================================
class DayBacktester:
    def __init__(self, cfg: AppConfig, minute_loader: Callable[[str, dt.date], pd.DataFrame],
                 prev_close: Callable[[str, dt.date], Optional[float]], meta: Optional[Dict[str, Dict]] = None):
        self.cfg = cfg
        self.cm = CostModel(cfg.cost)
        self.load = minute_loader
        self.prev_close = prev_close
        self.meta = meta or {}

    def run(self, codes: Iterable[str], dates: Iterable[dt.date], initial_equity: Optional[float] = None,
            progress: Optional[Callable[[str], None]] = None) -> BacktestResult:
        cfg, pb = self.cfg, self.cfg.day
        equity = float(initial_equity or cfg.risk.account_equity)
        codes = list(codes)
        trades: List[Trade] = []
        curve: Dict[pd.Timestamp, float] = {}
        signals = expired = 0
        t_first, t_last, t_exit = (dt.time(*map(int, s.split(":"))) for s in (pb.first_entry_time, pb.last_entry_time, pb.force_exit_time))
        valid_bars = max(1, pb.ladder_valid_minutes // max(1, pb.bar_minutes))
        for date in dates:
            bars: Dict[str, pd.DataFrame] = {}
            for code in codes:
                df = self.load(code, date)
                if df is not None and len(df) >= 10:
                    bars[code] = df
            if not bars:
                continue
            day_start_equity = equity
            day_pnl = 0.0
            consecutive_losses = 0
            sims: Dict[str, PositionSim] = {}
            traded_today: set = set()
            times = sorted({t for df in bars.values() for t in df.index})
            for t in times:
                tt = t.time()
                # (a) 기존
                for code, sim in list(sims.items()):
                    df = bars[code]
                    if t not in df.index:
                        continue
                    bar = df.loc[t]
                    trade = sim.on_bar(bar, t) if tt < t_exit else None
                    if trade is None and tt >= t_exit and not sim.closed:
                        trade = sim.force_exit(float(bar["open"]), t, "force_exit")
                    if trade is not None:
                        trades.append(trade)
                        equity += trade.net_pnl
                        day_pnl += trade.net_pnl
                        consecutive_losses = consecutive_losses + 1 if trade.net_pnl < 0 else 0
                        del sims[code]
                    elif sim.closed:
                        expired += 1
                        del sims[code]
                # (b) 신규 — 시간창, 슬롯, 일손실한도, 연속손실 체크
                if not (t_first <= tt <= t_last):
                    continue
                if day_pnl <= -day_start_equity * cfg.risk.daily_loss_limit_pct / 100:
                    continue
                if consecutive_losses >= cfg.risk.max_consecutive_losses:
                    continue
                slots = cfg.risk.max_open_positions - len(sims)
                if slots <= 0:
                    continue
                cands = []
                min_intra = cfg.universe.day_min_intraday_turnover
                for code, df in bars.items():
                    if code in sims or code in traded_today or t not in df.index:
                        continue
                    window = df.loc[:t]
                    if min_intra > 0 and float(window["value"].sum()) < min_intra:
                        continue
                    setup = detect_pullback(window, pb, intraday=True, prev_close=self.prev_close(code, date))
                    if setup is not None:
                        cands.append((setup.score, code, setup))
                cands.sort(key=lambda x: -x[0])
                for score, code, setup in cands[:slots]:
                    m = self.meta.get(code, {})
                    plan = build_plan(setup, cfg, code=code, name=m.get("name", code), market=m.get("market", "KOSPI"),
                                      equity=equity, mode="day", valid_until=f"{pb.ladder_valid_minutes}분")
                    signals += 1
                    if plan.ok:
                        sims[code] = PositionSim(plan, self.cm, valid_bars=valid_bars,
                                                 first_tranche_market=pb.first_tranche_market,
                                                 move_stop_to_breakeven=pb.move_stop_to_breakeven_after_t1, signal_time=t)
                        traded_today.add(code)
            # 장 종료: 남은 포지션 강제 청산
            for code, sim in sims.items():
                df = bars[code]
                trade = sim.force_exit(float(df["close"].iloc[-1]), df.index[-1], "force_exit")
                if trade is not None:
                    trades.append(trade)
                    equity += trade.net_pnl
                else:
                    expired += 1
            curve[pd.Timestamp(date)] = equity
            if progress:
                progress(f"{date} equity {equity:,.0f} trades {len(trades)}")
        series = pd.Series(curve, dtype="float64").sort_index()
        return BacktestResult(trades=trades, equity_curve=series, initial_equity=float(initial_equity or cfg.risk.account_equity),
                              final_equity=equity, mode="day", signals=signals, expired_ladders=expired)
