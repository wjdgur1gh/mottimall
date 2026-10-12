"""호가가격단위(틱)와 가격제한폭.

2023-01-25 개편 이후 코스피·코스닥·코넥스 공통 (한국거래소):
    2,000원 미만            1원
    2,000 ~ 5,000원 미만     5원
    5,000 ~ 20,000원 미만    10원
    20,000 ~ 50,000원 미만   50원
    50,000 ~ 200,000원 미만  100원
    200,000 ~ 500,000원 미만 500원
    500,000원 이상           1,000원
가격제한폭: 기준가(전일 종가) 대비 ±30% (2015-06-15~).
"""
from __future__ import annotations

import math
from typing import Tuple

_TICK_TABLE = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),
)

PRICE_LIMIT_PCT = 30.0


def tick_size(price: float) -> int:
    """주어진 가격대의 호가단위."""
    if price is None or price <= 0 or math.isnan(price):
        return 1
    for upper, tick in _TICK_TABLE:
        if price < upper:
            return tick
    return 1_000


def round_to_tick(price: float, direction: str = "nearest") -> int:
    """가격을 호가단위에 맞춘다. direction: nearest | down | up.

    구간 경계에서는 '내림/올림한 결과'의 호가단위를 다시 확인해 경계를 넘는 오류를 막는다.
    """
    if price is None or math.isnan(price) or price <= 0:
        return 0
    tick = tick_size(price)
    if direction == "down":
        out = math.floor(price / tick) * tick
    elif direction == "up":
        out = math.ceil(price / tick) * tick
    else:
        out = round(price / tick) * tick
    # 경계 보정: 예) 19,995 -> up -> 20,000 (틱 50 구간) 은 유효, 19,990 nearest 등
    t2 = tick_size(out)
    if t2 != tick and out % t2 != 0:
        out = math.floor(out / t2) * t2 if direction != "up" else math.ceil(out / t2) * t2
    return int(out)


def price_limits(prev_close: float) -> Tuple[int, int]:
    """(하한가, 상한가). 상한가는 호가단위 미만 절사, 하한가는 올림."""
    upper = round_to_tick(prev_close * (1 + PRICE_LIMIT_PCT / 100), "down")
    lower = round_to_tick(prev_close * (1 - PRICE_LIMIT_PCT / 100), "up")
    return lower, upper


def ticks_between(p1: float, p2: float) -> int:
    """두 가격 사이의 틱 수(근사, 구간이 바뀌면 각 구간별로 합산)."""
    lo, hi = sorted((p1, p2))
    n = 0
    cur = lo
    while cur < hi:
        t = tick_size(cur)
        # 이 구간 상한
        bound = next(u for u, _ in _TICK_TABLE if cur < u)
        step_to = min(hi, bound)
        n += int(round((step_to - cur) / t))
        cur = step_to
    return n


def spread_cost_pct(price: float, ticks: int = 1) -> float:
    """틱 기준 스프레드 비용(%)."""
    if price <= 0:
        return 0.0
    return tick_size(price) * ticks / price * 100
