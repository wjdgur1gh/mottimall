"""간단한 CSV 캐시 (일봉/분봉/유니버스)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import normalize_bars


class BarCache:
    def __init__(self, root: str):
        self.root = Path(root)
        (self.root / "daily").mkdir(parents=True, exist_ok=True)
        (self.root / "minute").mkdir(parents=True, exist_ok=True)
        (self.root / "universe").mkdir(parents=True, exist_ok=True)

    def _daily_path(self, code: str) -> Path:
        return self.root / "daily" / f"{code}.csv"

    def load_daily(self, code: str) -> Optional[pd.DataFrame]:
        p = self._daily_path(code)
        if not p.exists():
            return None
        try:
            return normalize_bars(pd.read_csv(p))
        except Exception:
            return None

    def save_daily(self, code: str, df: pd.DataFrame) -> None:
        old = self.load_daily(code)
        if old is not None and len(old):
            df = pd.concat([old, df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(self._daily_path(code), index_label="datetime")

    def _minute_path(self, code: str, date: dt.date) -> Path:
        return self.root / "minute" / f"{code}_{date:%Y%m%d}.csv"

    def load_minute(self, code: str, date: dt.date) -> Optional[pd.DataFrame]:
        p = self._minute_path(code, date)
        if not p.exists():
            return None
        try:
            return normalize_bars(pd.read_csv(p))
        except Exception:
            return None

    def save_minute(self, code: str, date: dt.date, df: pd.DataFrame) -> None:
        df.to_csv(self._minute_path(code, date), index_label="datetime")

    def _universe_path(self, date: dt.date) -> Path:
        return self.root / "universe" / f"universe_{date:%Y%m%d}.csv"

    def load_universe(self, date: dt.date) -> Optional[pd.DataFrame]:
        p = self._universe_path(date)
        if not p.exists():
            return None
        return pd.read_csv(p, dtype={"code": str})

    def save_universe(self, date: dt.date, df: pd.DataFrame) -> None:
        df.to_csv(self._universe_path(date), index=False)
