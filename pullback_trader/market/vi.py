"""변동성완화장치(VI) 계산.

동적 VI: 직전 체결가 대비 코스피200 종목 ±3%, 코스피 일반/코스닥 ±6% (장마감 전 15:20~15:30 은 ±2%/±4%)
정적 VI: 기준가(전일 종가 또는 직전 단일가) 대비 ±10%
발동 시 2분간 단일가매매 (KRX 전용, NXT 에는 정적 VI 없음)
"""
from __future__ import annotations

import datetime as dt
from typing import Tuple

from .tick import round_to_tick


def dynamic_vi_threshold_pct(is_kospi200: bool, when: dt.datetime | None = None) -> float:
    closing = False
    if when is not None:
        t = when.time()
        closing = dt.time(15, 20) <= t < dt.time(15, 30)
    if is_kospi200:
        return 2.0 if closing else 3.0
    return 4.0 if closing else 6.0


def dynamic_vi_band(last_price: float, is_kospi200: bool, when: dt.datetime | None = None) -> Tuple[int, int]:
    pct = dynamic_vi_threshold_pct(is_kospi200, when)
    return (
        round_to_tick(last_price * (1 - pct / 100), "up"),
        round_to_tick(last_price * (1 + pct / 100), "down"),
    )


def static_vi_band(ref_price: float) -> Tuple[int, int]:
    return (
        round_to_tick(ref_price * 0.9, "up"),
        round_to_tick(ref_price * 1.1, "down"),
    )


def order_may_trigger_vi(order_price: float, last_price: float, ref_price: float,
                         is_kospi200: bool = False, when: dt.datetime | None = None) -> bool:
    """지정 주문가가 동적/정적 VI 를 유발할 수 있는지(그 가격에 체결되면)."""
    dlo, dhi = dynamic_vi_band(last_price, is_kospi200, when)
    slo, shi = static_vi_band(ref_price)
    return not (dlo < order_price < dhi) or not (slo < order_price < shi)
