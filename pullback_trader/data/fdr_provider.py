"""FinanceDataReader 공급자. StockListing('KRX') 에 Marcap(시가총액), Stocks(상장주식수) 가 포함된다."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

import pandas as pd

from .base import empty_bars, empty_universe, normalize_bars, normalize_universe


class FdrProvider:
    name = "fdr"

    def __init__(self):
        try:
            import FinanceDataReader as fdr  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError("pip install finance-datareader 가 필요합니다") from e
        import FinanceDataReader as fdr
        self.fdr = fdr

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        df = self.fdr.StockListing("KRX")
        if df is None or len(df) == 0:
            return empty_universe()
        df = df.rename(columns={"Code": "code", "Name": "name", "Market": "market", "Marcap": "market_cap",
                                "Stocks": "shares", "Close": "close", "Amount": "turnover"})
        df["flags"] = ""
        if "market" in df.columns:
            df["market"] = df["market"].astype(str).str.upper().replace({"KOSDAQ GLOBAL": "KOSDAQ"})
        return normalize_universe(df)

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        df = self.fdr.DataReader(code, start.isoformat(), end.isoformat())
        if df is None or len(df) == 0:
            return empty_bars()
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.index.name = "datetime"
        return normalize_bars(df)

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame:
        return empty_bars()

    def snapshot(self, code: str) -> Dict:
        return {}
