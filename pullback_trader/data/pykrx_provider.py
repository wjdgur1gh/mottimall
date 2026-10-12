"""pykrx 공급자 (KRX 정보데이터시스템). 일부 API 는 KRX_ID / KRX_PW 환경변수(로그인)가 필요할 수 있다."""
from __future__ import annotations

import datetime as dt
import time
from typing import Dict, Optional

import pandas as pd

from .base import empty_bars, empty_universe, normalize_bars, normalize_universe


class PykrxProvider:
    name = "pykrx"

    def __init__(self, request_interval_sec: float = 0.5):
        try:
            from pykrx import stock  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install pykrx 가 필요합니다") from e
        from pykrx import stock
        self.stock = stock
        self.interval = request_interval_sec

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        d = (date or dt.date.today()).strftime("%Y%m%d")
        frames = []
        for market in ("KOSPI", "KOSDAQ"):
            time.sleep(self.interval)
            cap = self.stock.get_market_cap(d, market=market)  # 시가총액, 거래량, 거래대금, 상장주식수, 외국인보유주식수
            if cap is None or len(cap) == 0:
                continue
            cap = cap.reset_index().rename(columns={"티커": "code", "시가총액": "market_cap", "상장주식수": "shares", "거래대금": "turnover", "종가": "close"})
            cap["market"] = market
            try:
                names = {c: self.stock.get_market_ticker_name(c) for c in cap["code"]}
            except Exception:
                names = {}
            cap["name"] = cap["code"].map(names).fillna("")
            frames.append(cap)
        if not frames:
            return empty_universe()
        df = pd.concat(frames, ignore_index=True)
        if "close" not in df.columns:
            df["close"] = float("nan")
        df["flags"] = ""
        return normalize_universe(df)

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        time.sleep(self.interval)
        df = self.stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        if df is None or len(df) == 0:
            return empty_bars()
        df = df.reset_index()
        return normalize_bars(df)

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame:
        # pykrx 는 분봉을 제공하지 않는다
        return empty_bars()

    def snapshot(self, code: str) -> Dict:
        return {}
