"""데이터 공급자 공통 인터페이스.

모든 공급자는 아래 형식의 pandas DataFrame 을 돌려준다.

일봉/분봉 (bars):
    index : DatetimeIndex (naive, KST), 오름차순, 이름 'datetime'
    columns: open, high, low, close, volume, value   (value = 거래대금(원), 없으면 close*volume 근사)

유니버스 (universe):
    columns: code(6자리 str), name, market(KOSPI|KOSDAQ|KONEX), market_cap(원), shares, close, turnover(당일 거래대금, 원)
             flags(str, '관리종목;투자경고' 처럼 ';' 구분, 없으면 ''), listing_date(선택)
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Protocol, runtime_checkable

import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume", "value"]
UNIVERSE_COLUMNS = ["code", "name", "market", "market_cap", "shares", "close", "turnover", "flags"]

# 한글/영문 컬럼명 매핑 (CSV 내보내기 호환)
_COLUMN_ALIASES = {
    "date": "datetime", "일자": "datetime", "날짜": "datetime", "시간": "datetime", "datetime": "datetime",
    "time": "datetime", "일시": "datetime", "체결시간": "datetime",
    "open": "open", "시가": "open", "high": "high", "고가": "high", "low": "low", "저가": "low",
    "close": "close", "종가": "close", "현재가": "close", "volume": "volume", "거래량": "volume",
    "value": "value", "거래대금": "value", "amount": "value",
}


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """임의 컬럼명의 DataFrame 을 표준 bars 형식으로 정규화."""
    if df is None or len(df) == 0:
        return empty_bars()
    out = df.copy()
    rename = {}
    for c in out.columns:
        key = str(c).strip().lower()
        if key in _COLUMN_ALIASES:
            rename[c] = _COLUMN_ALIASES[key]
        elif str(c).strip() in _COLUMN_ALIASES:
            rename[c] = _COLUMN_ALIASES[str(c).strip()]
    out = out.rename(columns=rename)
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"].astype(str).str.replace(r"[^0-9]", "", regex=True),
                                         format="mixed", errors="coerce") if out["datetime"].dtype == object else pd.to_datetime(out["datetime"])
        out = out.dropna(subset=["datetime"]).set_index("datetime")
    elif not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out.index.name = "datetime"
    for c in ("open", "high", "low", "close", "volume"):
        if c not in out.columns:
            raise ValueError(f"bars 에 '{c}' 컬럼이 없습니다: {list(df.columns)}")
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ""), errors="coerce")
    if "value" not in out.columns or out["value"].isna().all():
        out["value"] = out["close"] * out["volume"]
    else:
        out["value"] = pd.to_numeric(out["value"].astype(str).str.replace(",", ""), errors="coerce")
        out["value"] = out["value"].fillna(out["close"] * out["volume"])
    out = out[BAR_COLUMNS].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[out["volume"].fillna(0) >= 0]
    return out


def empty_bars() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], name="datetime")
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS}, index=idx)


def empty_universe() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in UNIVERSE_COLUMNS})


def normalize_universe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in UNIVERSE_COLUMNS:
        if c not in out.columns:
            out[c] = "" if c in ("name", "market", "flags") else float("nan")
    out["code"] = out["code"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
    out["market"] = out["market"].astype(str).str.upper().replace({"KQ": "KOSDAQ", "KS": "KOSPI", "코스피": "KOSPI", "코스닥": "KOSDAQ"})
    for c in ("market_cap", "shares", "close", "turnover"):
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ""), errors="coerce")
    out["flags"] = out["flags"].fillna("").astype(str)
    extra = [c for c in out.columns if c not in UNIVERSE_COLUMNS]
    return out[UNIVERSE_COLUMNS + extra].drop_duplicates("code").reset_index(drop=True)


def resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """1분봉 -> N분봉. 09:00 기준으로 정렬(label=left, closed=left)."""
    if minutes <= 1 or len(df) == 0:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "value": "sum"}
    out = df.resample(f"{minutes}min", label="left", closed="left", origin="start_day").agg(agg)
    return out.dropna(subset=["open"])


@runtime_checkable
class DataProvider(Protocol):
    name: str

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame: ...

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame: ...

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame: ...

    def snapshot(self, code: str) -> Dict: ...
