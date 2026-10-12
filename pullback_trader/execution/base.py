"""브로커 공통 인터페이스."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass
class Order:
    id: str
    code: str
    side: str            # buy | sell
    qty: int
    price: Optional[int]  # None = 시장가
    kind: str = "limit"   # limit | market | stop (조건부 시장가 매도)
    stop_price: Optional[int] = None
    status: str = "open"  # open | filled | cancelled | rejected
    filled_qty: int = 0
    avg_fill: float = 0.0
    tag: str = ""
    created_at: Optional[dt.datetime] = None
    meta: Dict = field(default_factory=dict)


@dataclass
class Fill:
    order_id: str
    code: str
    side: str
    qty: int
    price: float
    cost: float
    time: dt.datetime
    tag: str = ""


@dataclass
class Position:
    code: str
    qty: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    costs: float = 0.0
    first_fill: Optional[dt.datetime] = None

    @property
    def value(self) -> float:
        return self.qty * self.avg_price


class Broker(Protocol):
    name: str

    def submit_limit(self, code: str, side: str, qty: int, price: int, tag: str = "") -> Order: ...

    def submit_market(self, code: str, side: str, qty: int, tag: str = "") -> Order: ...

    def submit_stop(self, code: str, qty: int, stop_price: int, tag: str = "") -> Order: ...

    def cancel(self, order_id: str) -> bool: ...

    def cancel_all(self, code: Optional[str] = None) -> int: ...

    def open_orders(self, code: Optional[str] = None) -> List[Order]: ...

    def positions(self) -> Dict[str, Position]: ...

    def cash(self) -> float: ...
