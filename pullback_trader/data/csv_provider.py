"""CSV 공급자 — 카이로스(HTS) 등에서 내보낸 파일이나 캐시된 데이터를 사용.

디렉터리 구조:
    {csv_dir}/universe.csv                 : code,name,market,market_cap[,shares,close,turnover,flags]
    {csv_dir}/daily/{code}.csv             : 일자,시가,고가,저가,종가,거래량[,거래대금]  (영문 헤더도 가능)
    {csv_dir}/minute/{code}_{YYYYMMDD}.csv : 일시(YYYYMMDDHHMM 또는 'YYYY-MM-DD HH:MM'),시가,고가,저가,종가,거래량
    {csv_dir}/minute/{code}.csv            : 여러 날짜가 섞인 분봉도 허용 (date 로 필터)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from .base import empty_bars, empty_universe, normalize_bars, normalize_universe, resample_bars


def _read_csv_any(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str, encoding_errors="replace")


class CsvProvider:
    name = "csv"

    def __init__(self, csv_dir: str):
        self.root = Path(csv_dir)

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        p = self.root / "universe.csv"
        if not p.exists():
            return empty_universe()
        return normalize_universe(_read_csv_any(p))

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        p = self.root / "daily" / f"{code}.csv"
        if not p.exists():
            return empty_bars()
        df = normalize_bars(_read_csv_any(p))
        return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end) + pd.Timedelta(days=1))]

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame:
        p = self.root / "minute" / f"{code}_{date:%Y%m%d}.csv"
        if not p.exists():
            p = self.root / "minute" / f"{code}.csv"
            if not p.exists():
                return empty_bars()
        df = normalize_bars(_read_csv_any(p))
        df = df.loc[df.index.date == date] if len(df) else df
        return resample_bars(df, bar_minutes)

    def snapshot(self, code: str) -> Dict:
        df = self.daily(code, dt.date(2000, 1, 1), dt.date.today())
        if len(df) == 0:
            return {}
        last = df.iloc[-1]
        return {"code": code, "price": float(last["close"]), "date": df.index[-1].date(), "flags": ""}
