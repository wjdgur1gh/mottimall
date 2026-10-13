"""1:2:3:4 분할매수 사다리와 리스크 기반 수량 산정.

원칙
- 기본 비중 4:3:2:1 (1차 40%, 2차 30%, 3차 20%, 4차 10%). 확인봉 근처에서 가장 많이, 깊이 밀릴수록 적게.
  (1:2:3:4 등 역피라미드도 설정 가능하지만 경고를 표시한다)
- 사다리 가격은 1차가(현재가/지지선) 에서 눌림 저점 쪽으로 내려가며 배치 (range 모드)
- 손절가는 눌림 저점 아래(버퍼) 이면서 4차가보다 최소 N% 아래
- 수량은 '4차까지 전부 체결된 뒤 손절' 이라는 최악 시나리오 손실이 계좌의 risk_per_trade_pct 가 되도록 산정
- 종목당 최대 투자금(max_position_pct) 로 상한
- 목표가: 직전 임펄스 고점과 '평단 + R × (평단 − 손절)' 중 가까운 쪽 = 1차(부분청산), 먼 쪽 = 2차
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..config import AppConfig
from ..market.costs import CostModel
from ..market.tick import round_to_tick, tick_size
from .pullback import PullbackSetup


@dataclass
class Tranche:
    level: int
    price: int
    qty: int
    weight: float

    @property
    def amount(self) -> int:
        return self.price * self.qty


@dataclass
class OrderPlan:
    code: str
    name: str
    market: str
    mode: str
    as_of: str
    reference_price: float
    tranches: List[Tranche]
    stop_price: int
    target1_price: int
    target2_price: int
    partial_exit_ratio: float
    avg_price_all: float
    total_qty: int
    total_amount: int
    risk_amount_all: float
    risk_pct_all: float
    risk_amount_first: float
    rr_first: float
    rr_all: float
    breakeven_pct: float
    valid_until: str
    setup: Optional[PullbackSetup] = None
    warnings: List[str] = field(default_factory=list)
    score: float = 0.0
    first_tranche_market: bool = False
    risk_by_fill: List[float] = field(default_factory=list)   # k차까지 체결 후 손절 시 손실 (k=1..4)

    @property
    def ok(self) -> bool:
        return self.total_qty > 0 and all(t.qty > 0 for t in self.tranches)

    def invalidation_rules(self) -> List[str]:
        return [
            f"종가(또는 체결가)가 손절가 {self.stop_price:,}원 아래로 내려가면 보유 전량 매도, 미체결 사다리 전부 취소",
            f"1차 목표 {self.target1_price:,}원 도달 시 보유 {self.partial_exit_ratio:.0%} 매도, 미체결 사다리 취소, 손절가를 평단으로 상향",
            f"2차 목표 {self.target2_price:,}원 도달 시 잔량 매도",
            f"유효기간 {self.valid_until} 경과 시 미체결 사다리 취소",
        ]


def _ladder_prices(setup: PullbackSetup, p1: float, cfg: AppConfig) -> List[float]:
    lc = cfg.ladder
    if lc.step_mode == "range":
        lo = setup.pullback_low
        if lo >= p1:  # 1차가가 저점 이하이면 pct 로 대체
            return [p1 * (1 - s / 100) for s in lc.step_pct]
        span = p1 - lo
        fr = [0.0, 1 / 3, 2 / 3, 1.0]
        prices = [p1 - span * f for f in fr]
        # 4차는 저점 위 1틱에 둔다 (저점 이탈 = 셋업 무효)
        prices[3] = lo + tick_size(lo)
        return prices
    if lc.step_mode == "pct":
        return [p1 * (1 - s / 100) for s in lc.step_pct]
    if lc.step_mode == "atr":
        a = setup.atr if setup.atr and setup.atr > 0 else p1 * 0.02
        return [p1 - s * a for s in lc.step_atr]
    # support: 1차가, 이후 지지 이평선 순서대로 (하향 정렬), 모자라면 pct 로 채움
    levels = sorted({v for v in setup.ma.values() if v and v < p1}, reverse=True)
    out = [p1]
    for lvl in levels:
        if len(out) == 4:
            break
        out.append(lvl)
    i = 1
    while len(out) < 4:
        out.append(p1 * (1 - cfg.ladder.step_pct[min(i, 3)] / 100))
        i += 1
    return out


def build_plan(setup: PullbackSetup, cfg: AppConfig, *, code: str, name: str = "", market: str = "KOSPI",
               equity: Optional[float] = None, mode: Optional[str] = None,
               reference_price: Optional[float] = None, valid_until: str = "") -> OrderPlan:
    mode = mode or cfg.mode
    pb = cfg.swing if mode == "swing" else cfg.day
    lc, rc = cfg.ladder, cfg.risk
    equity = float(equity if equity is not None else rc.account_equity)
    warnings: List[str] = []

    # 1차 기준가: confirm 모드는 현재(확인봉) 종가, anticipate 는 지지선
    if reference_price is None:
        reference_price = setup.close if pb.entry_mode == "confirm" else min(setup.support_level, setup.close)
    p1 = float(reference_price)

    raw_prices = _ladder_prices(setup, p1, cfg)
    prices: List[int] = []
    for i, p in enumerate(raw_prices):
        rp = round_to_tick(p, "down" if i else "nearest")
        if prices and rp >= prices[-1]:
            rp = prices[-1] - tick_size(prices[-1])
        prices.append(max(rp, tick_size(rp)))

    # 손절가
    stop = min(setup.pullback_low * (1 - pb.stop_buffer_pct / 100),
               prices[-1] * (1 - pb.stop_below_last_pct / 100))
    stop_price = round_to_tick(stop, "down")
    if stop_price >= prices[-1]:
        stop_price = prices[-1] - tick_size(prices[-1])

    # 수량: 최악 시나리오(전량 체결 후 손절) 손실 = equity × risk%
    wsum = float(sum(lc.weights))
    avg_all = sum(p * w for p, w in zip(prices, lc.weights)) / wsum
    risk_per_share = avg_all - stop_price
    if risk_per_share <= 0:
        warnings.append("손절가가 평균단가 이상 — 수량 산정 불가")
        risk_per_share = max(avg_all * 0.01, 1.0)
    budget = equity * rc.risk_per_trade_pct / 100
    total_qty = int(budget // risk_per_share)
    cap_qty = int(equity * rc.max_position_pct / 100 // avg_all) if avg_all > 0 else 0
    if total_qty > cap_qty:
        warnings.append(f"(정보) 종목당 최대 투자금 {rc.max_position_pct}% 제한 적용: {total_qty}→{cap_qty}주 (실제 리스크는 {rc.risk_per_trade_pct}% 미만)")
        total_qty = cap_qty
    qtys: List[int] = []
    for w in lc.weights:
        qtys.append(int(total_qty * w // wsum))
    qtys[-1] += total_qty - sum(qtys)
    if any(q < lc.min_qty_per_tranche for q in qtys):
        warnings.append(f"수량이 너무 적어 1:2:3:4 분할 불가 (총 {total_qty}주). 리스크% 상향 또는 저가 종목 선택 필요")

    tranches = [Tranche(level=i + 1, price=p, qty=q, weight=w / wsum)
                for i, (p, q, w) in enumerate(zip(prices, qtys, lc.weights))]
    total_amount = sum(t.amount for t in tranches)
    if total_qty > 0:
        avg_all = total_amount / total_qty      # 실제 수량 기준 평단
    risk_by_fill: List[float] = []
    acc = 0.0
    for p, q in zip(prices, qtys):
        acc += (p - stop_price) * q
        risk_by_fill.append(acc)
    risk_all = risk_by_fill[-1]
    risk_first = risk_by_fill[0]
    w = list(lc.weights)
    if all(w[i] < w[i + 1] for i in range(len(w) - 1)):
        warnings.append(f"역피라미드 비중 {':'.join(str(int(x)) if float(x).is_integer() else str(x) for x in w)}: "
                        "깊이 밀릴수록 더 사는 구조 — 이기는 거래는 1~2차 수량만, 지는 거래는 전량. 4:3:2:1 권장")

    # 목표가: 직전 고점과 R 배수 목표 중 가까운 쪽이 1차(부분청산), 먼 쪽이 2차
    t_high = round_to_tick(setup.impulse_high, "down")
    t_r = round_to_tick(avg_all + pb.target_r_multiple * (avg_all - stop_price), "down")
    t1, t2 = min(t_high, t_r), max(t_high, t_r)
    if t1 <= prices[0]:
        warnings.append("1차 목표가 1차 매수가 이하 — 2차 목표로 대체")
        t1 = t2
    if t2 <= prices[0]:
        warnings.append("목표가가 1차 매수가 이하 — 손익비 불량")
    rr_first = (t1 - prices[0]) / (prices[0] - stop_price) if prices[0] > stop_price else 0.0
    rr_all = (t2 - avg_all) / (avg_all - stop_price) if avg_all > stop_price else 0.0

    cm = CostModel(cfg.cost)
    be = cm.breakeven_move_pct(prices[0], market)
    if (t1 - prices[0]) / prices[0] * 100 < be * 2:
        warnings.append(f"1차 목표 수익률이 손익분기({be:.2f}%) 2배 미만 — 비용 대비 기대이익 부족")

    return OrderPlan(
        code=code, name=name, market=market, mode=mode, as_of=str(setup.as_of),
        reference_price=p1, tranches=tranches, stop_price=stop_price,
        target1_price=t1, target2_price=t2, partial_exit_ratio=pb.partial_exit_at_impulse_high,
        avg_price_all=avg_all, total_qty=total_qty, total_amount=total_amount,
        risk_amount_all=risk_all, risk_pct_all=risk_all / equity * 100 if equity else 0.0,
        risk_amount_first=risk_first, rr_first=rr_first, rr_all=rr_all, breakeven_pct=be,
        valid_until=valid_until, setup=setup, warnings=warnings, score=setup.score,
        first_tranche_market=bool(pb.first_tranche_market), risk_by_fill=risk_by_fill,
    )
