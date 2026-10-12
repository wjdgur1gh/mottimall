"""네이버 금융 비공식 API 공급자 (로그인 불필요).

- 일봉/분봉: https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=day|minute&count=N&requestType=0
  (XML <item data="YYYYMMDD[HHMM]|시가|고가|저가|종가|거래량"/>; 거래대금 없음 → close*volume 근사)
- 시가총액 목록: https://m.stock.naver.com/api/stocks/marketValue/{KOSPI|KOSDAQ}?page=N&pageSize=100
  (JSON. marketValue 는 억원, accumulatedTradingValue 는 백만원 단위로 알려져 있으며
   단위가 바뀌면 _scale_* 에서 자동 보정한다. 비공식 API 이므로 응답 형식 변경 가능)

주의: 과도한 호출은 차단될 수 있다. request_interval_sec 로 간격을 둔다.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base import empty_bars, empty_universe, normalize_bars, normalize_universe, resample_bars

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) pullback-trader/0.1"}
_ITEM_RE = re.compile(r'<item\s+data="([^"]+)"')


def _num(s) -> float:
    if s is None:
        return float("nan")
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return float("nan")


class NaverProvider:
    name = "naver"

    def __init__(self, request_interval_sec: float = 0.3, timeout: float = 10.0):
        self.interval = request_interval_sec
        self.timeout = timeout
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update(_UA)

    def _throttle(self) -> None:
        wait = self.interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    # ------------------------------------------------------------------ bars
    def _fchart(self, code: str, timeframe: str, count: int) -> pd.DataFrame:
        self._throttle()
        url = ("https://fchart.stock.naver.com/sise.nhn"
               f"?symbol={code}&timeframe={timeframe}&count={count}&requestType=0")
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        rows: List[List[float]] = []
        for raw in _ITEM_RE.findall(r.text):
            parts = raw.split("|")
            if len(parts) < 6:
                continue
            rows.append(parts[:6])
        if not rows:
            return empty_bars()
        df = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume"])
        fmt = "%Y%m%d" if timeframe == "day" else "%Y%m%d%H%M"
        df["datetime"] = pd.to_datetime(df["datetime"], format=fmt, errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime")
        return normalize_bars(df)

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        days = (end - start).days
        count = max(50, int(days * 0.75) + 30)
        df = self._fchart(code, "day", min(count, 3000))
        return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end) + pd.Timedelta(days=1))]

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame:
        # 1분봉 기준 하루 약 390봉. 최근 N일치가 섞여 오므로 날짜로 필터
        df = self._fchart(code, "minute", 2000)
        if len(df) == 0:
            return df
        df = df.loc[df.index.date == date]
        return resample_bars(df, bar_minutes)

    # -------------------------------------------------------------- universe
    def _market_value_pages(self, market: str) -> List[Dict]:
        out: List[Dict] = []
        page = 1
        while True:
            self._throttle()
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                break
            js = r.json()
            stocks = js.get("stocks") or js.get("result") or []
            if not stocks:
                break
            out.extend(stocks)
            total = int(js.get("totalCount") or 0)
            if total and len(out) >= total:
                break
            if len(stocks) < 100:
                break
            page += 1
            if page > 40:
                break
        return out

    @staticmethod
    def _scale_market_cap(values: pd.Series) -> pd.Series:
        # 억원 단위로 오면 삼성전자가 수백만 수준(< 1e9). 원 단위면 1e14 이상.
        if values.max() < 1e10:
            return values * 1e8
        return values

    @staticmethod
    def _scale_turnover(values: pd.Series) -> pd.Series:
        # 백만원 단위면 상위 종목이 수백만 미만
        if values.max() < 1e9:
            return values * 1e6
        return values

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        rows = []
        for market in ("KOSPI", "KOSDAQ"):
            for s in self._market_value_pages(market):
                rows.append({
                    "code": s.get("itemCode") or s.get("stockCode") or "",
                    "name": s.get("stockName") or s.get("itemName") or "",
                    "market": market,
                    "market_cap": _num(s.get("marketValue")),
                    "shares": _num(s.get("listedStockCount") or s.get("stockCount")),
                    "close": _num(s.get("closePrice") or s.get("currentPrice")),
                    "turnover": _num(s.get("accumulatedTradingValue")),
                    "flags": "",
                })
        if not rows:
            return empty_universe()
        df = pd.DataFrame(rows)
        df["market_cap"] = self._scale_market_cap(pd.to_numeric(df["market_cap"], errors="coerce").fillna(0))
        df["turnover"] = self._scale_turnover(pd.to_numeric(df["turnover"], errors="coerce").fillna(0))
        return normalize_universe(df)

    def snapshot(self, code: str) -> Dict:
        self._throttle()
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code != 200:
            return {}
        js = r.json()
        return {
            "code": code,
            "name": js.get("stockName", ""),
            "price": _num(js.get("closePrice")),
            "prev_close": _num(js.get("closePrice")) - _num(js.get("compareToPreviousClosePrice")),
            "flags": "",
            "raw": js,
        }
