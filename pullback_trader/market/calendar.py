"""KRX / NXT 거래시간과 휴장일.

KRX(정규): 08:30~09:00 장전 동시호가, 09:00~15:30 정규장(15:20~15:30 장마감 동시호가),
           15:40~16:00 장후 시간외 종가, 16:00~18:00 시간외 단일가(10분 단위)
NXT(대체거래소): 08:00~08:50 프리마켓, 09:00:30~15:20 메인마켓, 15:40~20:00 애프터마켓
                (프리/애프터는 지정가만, KRX 시가·종가 결정 구간은 거래 없음)
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Iterable, Optional, Set

KST = dt.timezone(dt.timedelta(hours=9))


class Session(str, Enum):
    CLOSED = "closed"
    NXT_PRE = "nxt_pre"               # 08:00~08:50
    KRX_PRE_AUCTION = "krx_pre_auction"   # 08:30~09:00
    REGULAR = "regular"               # 09:00~15:20 (연속매매)
    CLOSE_AUCTION = "close_auction"   # 15:20~15:30
    AFTER_CLOSE_PRICE = "after_close_price"  # 15:40~16:00
    AFTER_SINGLE = "after_single"     # 16:00~18:00
    NXT_AFTER = "nxt_after"           # 15:40~20:00


def _t(h: int, m: int, s: int = 0) -> dt.time:
    return dt.time(h, m, s)


class KrxCalendar:
    def __init__(self, holidays: Iterable[str] = ()):
        self.holidays: Set[dt.date] = {dt.date.fromisoformat(h) for h in holidays}

    # ----- 영업일 -----
    def is_trading_day(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_trading_day(self, d: dt.date) -> dt.date:
        n = d + dt.timedelta(days=1)
        while not self.is_trading_day(n):
            n += dt.timedelta(days=1)
        return n

    def prev_trading_day(self, d: dt.date) -> dt.date:
        n = d - dt.timedelta(days=1)
        while not self.is_trading_day(n):
            n -= dt.timedelta(days=1)
        return n

    # ----- 세션 -----
    def session_at(self, when: Optional[dt.datetime] = None) -> Session:
        now = when or dt.datetime.now(KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=KST)
        if not self.is_trading_day(now.date()):
            return Session.CLOSED
        t = now.timetz().replace(tzinfo=None)
        if _t(9, 0) <= t < _t(15, 20):
            return Session.REGULAR
        if _t(15, 20) <= t < _t(15, 30):
            return Session.CLOSE_AUCTION
        if _t(8, 30) <= t < _t(9, 0):
            return Session.KRX_PRE_AUCTION
        if _t(8, 0) <= t < _t(8, 30):
            return Session.NXT_PRE
        if _t(15, 40) <= t < _t(16, 0):
            return Session.AFTER_CLOSE_PRICE
        if _t(16, 0) <= t < _t(18, 0):
            return Session.AFTER_SINGLE
        if _t(18, 0) <= t < _t(20, 0):
            return Session.NXT_AFTER
        return Session.CLOSED

    def is_regular_open(self, when: Optional[dt.datetime] = None) -> bool:
        return self.session_at(when) == Session.REGULAR

    @staticmethod
    def parse_hhmm(s: str) -> dt.time:
        h, m = s.split(":")
        return dt.time(int(h), int(m))

    def within(self, when: dt.datetime, start_hhmm: str, end_hhmm: str) -> bool:
        t = when.timetz().replace(tzinfo=None) if when.tzinfo else when.time()
        return self.parse_hhmm(start_hhmm) <= t <= self.parse_hhmm(end_hhmm)
