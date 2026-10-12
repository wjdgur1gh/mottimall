"""모의(페이퍼) 브로커 — 봉 데이터로 체결을 시뮬레이션한다.

체결 규칙 (보수적)
- 매수 지정가: 봉 저가 <= 주문가 이면 체결. 시가가 주문가보다 낮으면 시가에 체결(갭 유리), 아니면 주문가
- 매도 지정가: 봉 고가 >= 주문가 이면 체결. 시가가 더 높으면 시가
- 시장가: 다음 봉 시가 (+/- 슬리피지 틱)
- 스탑(조건부 매도): 봉 저가 <= 스탑가 이면 발동, 체결가 = min(시가, 스탑가) - 슬리피지
- 같은 봉에서 스탑과 목표가 모두 닿으면 스탑 우선 (보수적)
"""
from __future__ import annotations

import datetime as dt
import itertools
from typing import Dict, List, Optional

import pandas as pd

from ..market.costs import CostModel
from .base import Fill, Order, Position


class PaperBroker:
    name = "paper"

    def __init__(self, cost_model: CostModel, cash: float, markets: Optional[Dict[str, str]] = None):
        self.cost_model = cost_model
        self._cash = float(cash)
        self.initial_cash = float(cash)
        self.markets = markets or {}
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self.fills: List[Fill] = []
        self._seq = itertools.count(1)
        self.now: Optional[dt.datetime] = None

    # ------------------------------------------------------------ orders
    def _new(self, code: str, side: str, qty: int, price: Optional[int], kind: str, tag: str,
             stop_price: Optional[int] = None) -> Order:
        if qty <= 0:
            raise ValueError("수량은 1 이상")
        o = Order(id=f"P{next(self._seq):06d}", code=code, side=side, qty=int(qty), price=price, kind=kind,
                  stop_price=stop_price, tag=tag, created_at=self.now)
        self._orders[o.id] = o
        return o

    def submit_limit(self, code: str, side: str, qty: int, price: int, tag: str = "") -> Order:
        return self._new(code, side, qty, int(price), "limit", tag)

    def submit_market(self, code: str, side: str, qty: int, tag: str = "") -> Order:
        return self._new(code, side, qty, None, "market", tag)

    def submit_stop(self, code: str, qty: int, stop_price: int, tag: str = "") -> Order:
        return self._new(code, "sell", qty, None, "stop", tag, stop_price=int(stop_price))

    def cancel(self, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if o and o.status == "open":
            o.status = "cancelled"
            return True
        return False

    def cancel_all(self, code: Optional[str] = None) -> int:
        n = 0
        for o in self._orders.values():
            if o.status == "open" and (code is None or o.code == code):
                o.status = "cancelled"
                n += 1
        return n

    def open_orders(self, code: Optional[str] = None) -> List[Order]:
        return [o for o in self._orders.values() if o.status == "open" and (code is None or o.code == code)]

    def positions(self) -> Dict[str, Position]:
        return {c: p for c, p in self._positions.items() if p.qty > 0}

    def cash(self) -> float:
        return self._cash

    def equity(self, last_prices: Dict[str, float]) -> float:
        return self._cash + sum(p.qty * last_prices.get(c, p.avg_price) for c, p in self.positions().items())

    # ------------------------------------------------------------ fills
    def _fill(self, o: Order, price: float, qty: int, when: dt.datetime) -> Fill:
        market = self.markets.get(o.code, "KOSPI")
        amount = price * qty
        pos = self._positions.setdefault(o.code, Position(code=o.code))
        if o.side == "buy":
            cost = self.cost_model.buy_fee(amount)
            new_qty = pos.qty + qty
            pos.avg_price = (pos.avg_price * pos.qty + amount) / new_qty
            pos.qty = new_qty
            pos.costs += cost
            if pos.first_fill is None:
                pos.first_fill = when
            self._cash -= amount + cost
        else:
            if qty > pos.qty:
                qty = pos.qty
                amount = price * qty
            cost = self.cost_model.sell_fee(amount, market)
            pos.realized_pnl += (price - pos.avg_price) * qty - cost
            pos.costs += cost
            pos.qty -= qty
            self._cash += amount - cost
            if pos.qty == 0:
                pos.first_fill = None
        o.filled_qty += qty
        o.avg_fill = price
        o.status = "filled"
        f = Fill(order_id=o.id, code=o.code, side=o.side, qty=qty, price=price, cost=cost, time=when, tag=o.tag)
        self.fills.append(f)
        return f

    def on_bar(self, code: str, bar: pd.Series, when: dt.datetime) -> List[Fill]:
        """해당 종목의 새 봉으로 미체결 주문을 평가한다. 스탑 → 매수 → 매도지정가 순."""
        self.now = when
        fills: List[Fill] = []
        o_, h_, l_ = float(bar["open"]), float(bar["high"]), float(bar["low"])
        orders = self.open_orders(code)
        # 1) 스탑 매도
        for o in [x for x in orders if x.kind == "stop"]:
            if l_ <= o.stop_price:
                px = self.cost_model.slippage(min(o_, o.stop_price), "sell")
                fills.append(self._fill(o, px, o.qty, when))
        # 2) 시장가
        for o in [x for x in orders if x.kind == "market" and x.status == "open"]:
            px = self.cost_model.slippage(o_, o.side)
            fills.append(self._fill(o, px, o.qty, when))
        # 3) 지정가
        for o in [x for x in orders if x.kind == "limit" and x.status == "open"]:
            if o.side == "buy" and l_ <= o.price:
                fills.append(self._fill(o, min(o_, o.price), o.qty, when))
            elif o.side == "sell" and h_ >= o.price:
                pos = self._positions.get(code)
                if pos and pos.qty > 0:
                    fills.append(self._fill(o, max(o_, o.price), min(o.qty, pos.qty), when))
                else:
                    o.status = "cancelled"
        return fills
