"""스캐너와 장중 실행 루프.

Scanner  : 유니버스 → 데이터 로드 → 필터 → 눌림목 탐지 → 주문 플랜 (스윙: 일봉 / 데이: 분봉)
LiveRunner: 장중 주기적으로 Scanner 를 돌려 broker 에 전달
    - sheet : 주문표 파일 갱신 + 알림 (미래에셋 카이로스 HTS 에서 수동 주문)
    - paper : 모의 브로커로 체결 시뮬레이션
    - kis   : 한국투자증권 자동 주문

상태(state/live_state.json)에 이미 낸 플랜을 기록해 같은 종목에 중복 신호를 내지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from ..config import AppConfig
from ..data import BarCache, make_provider
from ..data.base import DataProvider
from ..execution.base import Broker
from ..execution.order_sheet import plans_to_markdown, save_order_sheet
from ..execution.paper import PaperBroker
from ..market.calendar import KST, KrxCalendar, Session
from ..market.costs import CostModel
from ..screener import UniverseFilter
from ..strategy.indicators import rolling_avg_turnover
from ..strategy.pullback import detect_pullback
from ..strategy.sizing import OrderPlan, build_plan
from .alerts import Alerter

log = logging.getLogger("pullback")


class Scanner:
    def __init__(self, cfg: AppConfig, provider: Optional[DataProvider] = None, cache: Optional[BarCache] = None):
        self.cfg = cfg
        self.provider = provider or make_provider(cfg)
        self.cache = cache or BarCache(cfg.data.cache_dir)
        self.filter = UniverseFilter(cfg.universe, cfg.mode)
        self.calendar = KrxCalendar(cfg.holidays)

    # ------------------------------------------------------------ data
    def load_daily(self, code: str, end: dt.date, use_cache: bool = True) -> pd.DataFrame:
        start = end - dt.timedelta(days=int(self.cfg.data.lookback_days * 1.5))
        cached = self.cache.load_daily(code) if use_cache else None
        if cached is not None and len(cached) and cached.index[-1].date() >= end:
            return cached.loc[cached.index <= pd.Timestamp(end) + pd.Timedelta(days=1)]
        try:
            df = self.provider.daily(code, start, end)
        except Exception as e:
            log.warning("%s 일봉 로드 실패: %s", code, e)
            return cached if cached is not None else pd.DataFrame()
        if len(df) and use_cache and self.provider.name != "csv":
            self.cache.save_daily(code, df)
        return df

    def build_universe(self, date: Optional[dt.date] = None, with_turnover: bool = True,
                       progress: Optional[Callable[[str], None]] = None) -> Tuple[pd.DataFrame, str]:
        date = date or dt.date.today()
        uni = self.provider.universe(date)
        if len(uni) == 0:
            return uni, "유니버스 비어 있음 (데이터 공급자 확인)"
        # 1차: 가격/시총/이름/플래그 필터 (거래대금은 당일값으로 선별 후 2차에서 평균으로 재검증)
        first = self.filter.apply(uni)
        avg_turnover: Dict[str, float] = {}
        listing_days: Dict[str, int] = {}
        if with_turnover:
            for i, code in enumerate(first.passed["code"]):
                df = self.load_daily(code, date)
                if len(df):
                    avg_turnover[code] = rolling_avg_turnover(df, self.cfg.universe.avg_turnover_days)
                    listing_days[code] = len(df)
                if progress and i % 50 == 0:
                    progress(f"일봉 로드 {i}/{len(first.passed)}")
            second = self.filter.apply(first.passed, pd.Series(avg_turnover), pd.Series(listing_days))
            return second.passed, f"1차 {first.summary()} / 2차 {second.summary()}"
        return first.passed, first.summary()

    # ------------------------------------------------------------ scan
    def scan_swing(self, universe: pd.DataFrame, date: Optional[dt.date] = None,
                   equity: Optional[float] = None) -> Tuple[List[OrderPlan], Dict[str, List[str]]]:
        date = date or dt.date.today()
        plans: List[OrderPlan] = []
        reasons: Dict[str, List[str]] = {}
        for row in universe.itertuples():
            df = self.load_daily(row.code, date)
            if len(df) == 0:
                reasons[row.code] = ["데이터 없음"]
                continue
            df = df.loc[df.index <= pd.Timestamp(date) + pd.Timedelta(days=1)]
            rs: List[str] = []
            setup = detect_pullback(df, self.cfg.swing, reasons=rs)
            if setup is None:
                reasons[row.code] = rs
                continue
            valid = self.calendar.next_trading_day(date)
            for _ in range(self.cfg.swing.ladder_valid_days - 1):
                valid = self.calendar.next_trading_day(valid)
            plan = build_plan(setup, self.cfg, code=row.code, name=row.name, market=row.market,
                              equity=equity, mode="swing", valid_until=valid.isoformat())
            plans.append(plan)
        plans.sort(key=lambda p: -p.score)
        return plans, reasons

    def scan_day(self, universe: pd.DataFrame, now: Optional[dt.datetime] = None,
                 equity: Optional[float] = None) -> Tuple[List[OrderPlan], Dict[str, List[str]]]:
        now = now or dt.datetime.now(KST).replace(tzinfo=None)
        date = now.date()
        pb = self.cfg.day
        plans: List[OrderPlan] = []
        reasons: Dict[str, List[str]] = {}
        for row in universe.itertuples():
            try:
                m = self.provider.minute(row.code, date, pb.bar_minutes)
            except Exception as e:
                reasons[row.code] = [f"분봉 로드 실패: {e}"]
                continue
            if len(m) == 0:
                reasons[row.code] = ["분봉 없음"]
                continue
            # 완료된 봉만 사용 (봉 시작시각 + 봉길이 <= 현재)
            m = m.loc[m.index + pd.Timedelta(minutes=pb.bar_minutes) <= pd.Timestamp(now)]
            if len(m) == 0:
                reasons[row.code] = ["완료된 분봉 없음"]
                continue
            min_intra = self.cfg.universe.day_min_intraday_turnover
            if min_intra > 0 and float(m["value"].sum()) < min_intra:
                reasons[row.code] = [f"당일 누적 거래대금<{min_intra/1e8:.0f}억"]
                continue
            prev_close = None
            d = self.load_daily(row.code, date - dt.timedelta(days=1))
            if len(d):
                prev_close = float(d["close"].iloc[-1])
            rs: List[str] = []
            setup = detect_pullback(m, pb, intraday=True, prev_close=prev_close, reasons=rs)
            if setup is None:
                reasons[row.code] = rs
                continue
            valid = (now + dt.timedelta(minutes=pb.ladder_valid_minutes)).strftime("%H:%M")
            plan = build_plan(setup, self.cfg, code=row.code, name=row.name, market=row.market,
                              equity=equity, mode="day", valid_until=valid)
            plans.append(plan)
        plans.sort(key=lambda p: -p.score)
        return plans, reasons


class LiveRunner:
    def __init__(self, cfg: AppConfig, scanner: Optional[Scanner] = None, broker: Optional[Broker] = None,
                 alerter: Optional[Alerter] = None):
        self.cfg = cfg
        self.scanner = scanner or Scanner(cfg)
        self.alerter = alerter or Alerter(cfg.alert)
        self.calendar = self.scanner.calendar
        self.cm = CostModel(cfg.cost)
        self.broker = broker or self._make_broker()
        self.state_path = Path(cfg.state_dir) / "live_state.json"
        self.state = self._load_state()

    def _make_broker(self) -> Optional[Broker]:
        mode = self.cfg.broker.mode
        if mode == "paper":
            return PaperBroker(self.cm, self.cfg.risk.account_equity)
        if mode == "kis":
            from ..data.kis_client import KisClient
            from ..execution.kis_broker import KisBroker
            return KisBroker(KisClient(self.cfg.broker.kis))
        return None  # sheet

    def _load_state(self) -> Dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"date": "", "planned": {}, "orders": []}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _reset_if_new_day(self, today: dt.date) -> None:
        if self.state.get("date") != today.isoformat():
            self.state = {"date": today.isoformat(), "planned": {}, "orders": []}
            self._save_state()

    # ------------------------------------------------------------ dispatch
    def dispatch(self, plans: List[OrderPlan]) -> List[OrderPlan]:
        """새 플랜만 브로커/주문표로 보낸다."""
        new: List[OrderPlan] = []
        open_count = len(self.state["planned"])
        for p in plans:
            if p.code in self.state["planned"]:
                continue
            if open_count >= self.cfg.risk.max_open_positions:
                break
            if not p.ok:
                self.alerter.send(f"[건너뜀] {p.name}({p.code}) 수량 산정 불가: {p.warnings}")
                continue
            new.append(p)
            open_count += 1
        if not new:
            return []
        if self.broker is None:
            md, csv = save_order_sheet(new, self.cfg.output_dir, stem=f"orders_{dt.datetime.now():%Y%m%d_%H%M}_{self.cfg.mode}",
                                       title=f"{'스윙' if self.cfg.mode == 'swing' else '데이트레이딩'} 주문표")
            self.alerter.send(f"주문표 생성: {md} / {csv}\n" + plans_to_markdown(new)[:1500])
        else:
            for p in new:
                for t in p.tranches:
                    o = self.broker.submit_limit(p.code, "buy", t.qty, t.price, tag=f"L{t.level}")
                    self.state["orders"].append({"code": p.code, "id": o.id, "tag": o.tag, "price": t.price, "qty": t.qty})
                s = self.broker.submit_stop(p.code, p.total_qty, p.stop_price, tag="stop")
                self.state["orders"].append({"code": p.code, "id": s.id, "tag": "stop", "price": p.stop_price, "qty": p.total_qty})
                self.alerter.send(f"[{self.broker.name}] {p.name}({p.code}) 사다리 {[(t.price, t.qty) for t in p.tranches]} 손절 {p.stop_price:,} 목표 {p.target1_price:,}/{p.target2_price:,}")
        for p in new:
            self.state["planned"][p.code] = {"as_of": p.as_of, "stop": p.stop_price, "t1": p.target1_price, "t2": p.target2_price,
                                             "tranches": [(t.price, t.qty) for t in p.tranches], "valid_until": p.valid_until}
        self._save_state()
        return new

    # ------------------------------------------------------------ loops
    def run_once(self, now: Optional[dt.datetime] = None, universe: Optional[pd.DataFrame] = None) -> List[OrderPlan]:
        now = now or dt.datetime.now(KST).replace(tzinfo=None)
        self._reset_if_new_day(now.date())
        if universe is None:
            universe, summary = self.scanner.build_universe(now.date())
            self.alerter.send(f"유니버스: {summary}")
        if self.cfg.mode == "swing":
            plans, _ = self.scanner.scan_swing(universe, now.date())
        else:
            plans, _ = self.scanner.scan_day(universe, now)
        self.alerter.send(f"스캔 {len(universe)}종목 → 셋업 {len(plans)}개: " + ", ".join(f"{p.name}({p.score:.0f})" for p in plans[:10]))
        return self.dispatch(plans)

    def run_day_loop(self, poll_seconds: int = 60, universe: Optional[pd.DataFrame] = None) -> None:
        """데이트레이딩: 장중 poll_seconds 마다 스캔. 강제청산 시각에 종료."""
        pb = self.cfg.day
        today = dt.datetime.now(KST).date()
        if not self.calendar.is_trading_day(today):
            self.alerter.send("휴장일입니다.")
            return
        if universe is None:
            universe, summary = self.scanner.build_universe(today)
            self.alerter.send(f"유니버스: {summary}")
        t_last = self.calendar.parse_hhmm(pb.last_entry_time)
        t_exit = self.calendar.parse_hhmm(pb.force_exit_time)
        self.alerter.send(f"데이트레이딩 루프 시작 ({len(universe)}종목, {poll_seconds}s 주기, 신규진입 {pb.first_entry_time}~{pb.last_entry_time}, 강제청산 {pb.force_exit_time})")
        while True:
            now = dt.datetime.now(KST).replace(tzinfo=None)
            sess = self.calendar.session_at(now)
            if now.time() >= t_exit:
                self._force_exit_all(now)
                self.alerter.send("강제청산 시각 도달 — 루프 종료")
                break
            if sess == Session.REGULAR and now.time() <= t_last:
                try:
                    self.run_once(now, universe)
                except Exception as e:
                    log.exception("스캔 오류: %s", e)
                    self.alerter.send(f"스캔 오류: {e}")
            self._check_local_stops()
            time.sleep(poll_seconds)

    def _check_local_stops(self) -> None:
        """KIS 브로커의 로컬 스탑 감시."""
        b = self.broker
        if b is None or not hasattr(b, "check_stops"):
            return
        prices: Dict[str, float] = {}
        for code in self.state["planned"]:
            try:
                snap = self.scanner.provider.snapshot(code)
                if snap.get("price"):
                    prices[code] = float(snap["price"])
            except Exception:
                continue
        fired = b.check_stops(prices)
        for o in fired:
            self.alerter.send(f"[손절] {o.code} 시장가 매도 {o.qty}주")

    def _force_exit_all(self, now: dt.datetime) -> None:
        b = self.broker
        if b is None:
            self.alerter.send(f"[{now:%H:%M}] 강제청산 시각 — HTS 에서 보유 포지션 전량 매도 및 미체결 취소 필요")
            return
        b.cancel_all()
        for code, pos in b.positions().items():
            if pos.qty > 0:
                b.submit_market(code, "sell", pos.qty, tag="force_exit")
                self.alerter.send(f"[강제청산] {code} {pos.qty}주 시장가 매도")
