"""오프라인 테스트용 합성 데이터 생성기.

실제 시세가 아니다. 눌림목 패턴(상승 임펄스 → 거래량 감소 조정 → 반등 확인봉)을 포함한
가상 종목들의 일봉/분봉/유니버스를 data/sample/ 에 만든다.

사용: python scripts/make_sample_data.py [--out data/sample] [--seed 7]
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pullback_trader.config import AppConfig  # noqa: E402
from pullback_trader.market.calendar import KrxCalendar  # noqa: E402
from pullback_trader.market.tick import round_to_tick  # noqa: E402


def _bday_index(end: dt.date, n: int) -> pd.DatetimeIndex:
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    return idx


def synth_daily(seed: int, base: float, n: int = 260, pattern: str = "pullback_confirm",
                end: dt.date = dt.date(2026, 10, 8)) -> pd.DataFrame:
    """pattern: pullback_confirm | pullback_wait | uptrend_noise | downtrend"""
    rng = np.random.default_rng(seed)
    idx = _bday_index(end, n)
    rets = rng.normal(0.0008, 0.018, n)
    vol = rng.lognormal(mean=np.log(400_000), sigma=0.35, size=n)
    if pattern.startswith("pullback"):
        # 마지막 18봉: 임펄스 10봉(+2%/일) → 조정 5봉(-1.3%/일) → 반등 또는 대기
        imp = slice(n - 18, n - 8)
        pb = slice(n - 8, n - 3)
        rets[imp] = rng.normal(0.02, 0.008, 10)
        vol[imp] *= np.linspace(1.4, 2.6, 10)
        rets[pb] = rng.normal(-0.013, 0.005, 5)
        vol[pb] *= np.linspace(0.9, 0.45, 5)
        rets[n - 3: n - 1] = rng.normal(-0.004, 0.004, 2)
        vol[n - 3: n - 1] *= 0.5
        if pattern == "pullback_confirm":
            rets[n - 1] = 0.028
            vol[n - 1] *= 1.3
        else:
            rets[n - 1] = -0.002
            vol[n - 1] *= 0.45
        rets[: n - 18] += 0.0012  # 사전 완만한 상승 (MA20>MA60)
    elif pattern == "downtrend":
        rets -= 0.003
    close = base * np.cumprod(1 + rets)
    open_ = close / (1 + rets) * (1 + rng.normal(0, 0.003, n))
    if pattern == "pullback_confirm":
        open_[-1] = close[-2] * 1.002  # 확인봉은 양봉
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol.round()}, index=idx)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].map(lambda x: round_to_tick(x))
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    df["value"] = (df["close"] * df["volume"]).round()
    df.index.name = "datetime"
    return df


def synth_minute(seed: int, prev_close: float, date: dt.date, pattern: str = "pullback_confirm") -> pd.DataFrame:
    """1분봉 09:00~15:29. 오전 임펄스(+4%) → 조정(-1.8%) → 반등."""
    rng = np.random.default_rng(seed)
    times = pd.date_range(pd.Timestamp(date) + pd.Timedelta(hours=9), periods=390, freq="1min")
    n = len(times)
    rets = rng.normal(0, 0.0012, n)
    vol = rng.lognormal(mean=np.log(3_000), sigma=0.5, size=n)
    vol[:30] *= 3.0
    # 09:05~09:40 임펄스
    rets[5:40] = rng.normal(0.0012, 0.0008, 35)
    vol[5:40] *= np.linspace(2.5, 4.0, 35)
    # 09:40~10:10 조정
    rets[40:70] = rng.normal(-0.0006, 0.0005, 30)
    vol[40:70] *= np.linspace(1.0, 0.35, 30)
    if pattern == "pullback_confirm":
        rets[70:73] = [0.004, 0.003, 0.002]
        vol[70:73] *= [2.5, 2.0, 1.5]
        rets[73:] = rng.normal(0.0002, 0.0008, n - 73)
    else:
        rets[70:] = rng.normal(-0.0001, 0.0008, n - 70)
    close = prev_close * 1.005 * np.cumprod(1 + rets)
    open_ = np.r_[prev_close * 1.005, close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0008, n)))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol.round()}, index=times)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].map(lambda x: round_to_tick(x))
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    df["value"] = (df["close"] * df["volume"]).round()
    df.index.name = "datetime"
    return df


SAMPLE_STOCKS = [
    # code, name, market, base price, pattern, market cap(원)
    ("900001", "가상반도체", "KOSDAQ", 12_000, "pullback_confirm", 3.5e11),
    ("900002", "가상바이오", "KOSDAQ", 38_000, "pullback_confirm", 8.0e11),
    ("900003", "가상전자", "KOSPI", 125_000, "pullback_wait", 4.2e12),
    ("900004", "가상화학", "KOSPI", 7_800, "uptrend_noise", 2.1e11),
    ("900005", "가상건설", "KOSPI", 4_300, "downtrend", 1.6e11),
    ("900006", "가상스팩5호", "KOSDAQ", 2_050, "uptrend_noise", 9.0e9),
    ("900007", "가상소형주", "KOSDAQ", 1_500, "pullback_confirm", 6.0e9),
    ("900008", "가상게임", "KOSDAQ", 21_500, "pullback_confirm", 5.5e11),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default="2026-10-08")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "daily").mkdir(parents=True, exist_ok=True)
    (out / "minute").mkdir(parents=True, exist_ok=True)
    end = dt.date.fromisoformat(args.end)
    minute_day = KrxCalendar(AppConfig().holidays).next_trading_day(end)
    rows = []
    for i, (code, name, market, base, pattern, cap) in enumerate(SAMPLE_STOCKS):
        d = synth_daily(args.seed + i, base, pattern=pattern, end=end)
        d.to_csv(out / "daily" / f"{code}.csv")
        m = synth_minute(args.seed + 100 + i, float(d["close"].iloc[-1]), minute_day, pattern)
        m.to_csv(out / "minute" / f"{code}_{m.index[0]:%Y%m%d}.csv")
        rows.append({"code": code, "name": name, "market": market, "market_cap": int(cap),
                     "shares": int(cap // d["close"].iloc[-1]), "close": int(d["close"].iloc[-1]),
                     "turnover": int(d["value"].tail(20).mean()), "flags": ""})
    pd.DataFrame(rows).to_csv(out / "universe.csv", index=False)
    print(f"생성 완료: {out} ({len(rows)} 종목, 일봉 {len(d)}봉, 분봉 {len(m)}봉, 분봉일자 {m.index[0]:%Y-%m-%d})")


if __name__ == "__main__":
    main()
