import datetime as dt

import pytest

from pullback_trader.config import CostConfig
from pullback_trader.market import CostModel, KrxCalendar, Session, price_limits, round_to_tick, tick_size, ticks_between
from pullback_trader.market.vi import dynamic_vi_band, static_vi_band


@pytest.mark.parametrize("price,tick", [
    (1999, 1), (2000, 5), (4999, 5), (5000, 10), (19999, 10), (20000, 50),
    (49999, 50), (50000, 100), (199999, 100), (200000, 500), (499999, 500), (500000, 1000), (1_000_000, 1000),
])
def test_tick_table(price, tick):
    assert tick_size(price) == tick


def test_round_to_tick_directions():
    assert round_to_tick(12345) == 12340
    assert round_to_tick(12345, "up") == 12350
    assert round_to_tick(12345, "down") == 12340
    assert round_to_tick(19995, "up") == 20000
    assert round_to_tick(20010, "down") == 20000
    assert round_to_tick(0) == 0


def test_price_limits():
    assert price_limits(10000) == (7000, 13000)
    lo, hi = price_limits(23450)
    assert hi == 30450 and lo == 16420


def test_ticks_between_crosses_boundary():
    assert ticks_between(9900, 10100) == 20
    assert ticks_between(19990, 20050) == 2  # 10원 1틱 + 50원 1틱


def test_costs_2026():
    cm = CostModel(CostConfig())
    assert abs(cm.round_trip_pct("KOSPI") - 0.23) < 1e-9
    assert abs(cm.round_trip_pct("KOSDAQ") - 0.23) < 1e-9
    b = cm.round_trip(1_000_000, 1_000_000, "KOSDAQ")
    assert round(b.sell_tax) == 2000 and round(b.buy_commission) == 150
    assert cm.breakeven_move_pct(10000, "KOSDAQ") == pytest.approx(0.33)


def test_calendar_sessions():
    cal = KrxCalendar(["2026-10-09"])
    assert not cal.is_trading_day(dt.date(2026, 10, 9))
    assert not cal.is_trading_day(dt.date(2026, 10, 10))  # 토요일
    assert cal.is_trading_day(dt.date(2026, 10, 12))
    assert cal.session_at(dt.datetime(2026, 10, 12, 10, 0)) == Session.REGULAR
    assert cal.session_at(dt.datetime(2026, 10, 12, 15, 25)) == Session.CLOSE_AUCTION
    assert cal.session_at(dt.datetime(2026, 10, 12, 8, 45)) == Session.KRX_PRE_AUCTION
    assert cal.session_at(dt.datetime(2026, 10, 12, 16, 30)) == Session.AFTER_SINGLE
    assert cal.session_at(dt.datetime(2026, 10, 9, 10, 0)) == Session.CLOSED
    assert cal.next_trading_day(dt.date(2026, 10, 8)) == dt.date(2026, 10, 12)


def test_vi_bands():
    assert static_vi_band(10000) == (9000, 11000)
    assert dynamic_vi_band(10000, False) == (9400, 10600)
    assert dynamic_vi_band(10000, True) == (9700, 10300)
    assert dynamic_vi_band(10000, False, dt.datetime(2026, 10, 12, 15, 22)) == (9600, 10400)
