"""기술적 지표 (pandas 기반, 의존성 최소화)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=max(2, n // 2)).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def vwap(df: pd.DataFrame) -> pd.Series:
    """당일 누적 VWAP. value(거래대금) 가 근사치면 typical price*volume 사용."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).cumsum()
    v = df["volume"].cumsum().replace(0, np.nan)
    return pv / v


def rolling_avg_turnover(df: pd.DataFrame, n: int = 20) -> float:
    if len(df) == 0:
        return float("nan")
    return float(df["value"].tail(n).mean())
