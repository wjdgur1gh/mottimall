"""유니버스 필터 — 시가총액/거래대금/가격/상장일/종목명 패턴/상태 플래그/수동 제외."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import pandas as pd

from ..config import UniverseConfig


@dataclass
class FilterResult:
    passed: pd.DataFrame
    rejected: Dict[str, int] = field(default_factory=dict)  # 사유별 탈락 수

    def summary(self) -> str:
        parts = [f"통과 {len(self.passed)}"] + [f"{k} {v}" for k, v in self.rejected.items()]
        return ", ".join(parts)


class UniverseFilter:
    def __init__(self, cfg: UniverseConfig):
        self.cfg = cfg
        self._name_patterns = [re.compile(p) for p in cfg.exclude_name_regex]
        self.manual_exclusions: Set[str] = self._load_exclusions(cfg.exclusion_file)

    @staticmethod
    def _load_exclusions(path: str) -> Set[str]:
        p = Path(path)
        if not p.exists():
            return set()
        codes: Set[str] = set()
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            code = re.sub(r"\D", "", line.split(",")[0])
            if code:
                codes.add(code.zfill(6))
        return codes

    def name_excluded(self, name: str) -> bool:
        return any(p.search(name or "") for p in self._name_patterns)

    def flags_excluded(self, flags: str) -> Optional[str]:
        for f in (flags or "").split(";"):
            f = f.strip()
            if f and f in self.cfg.exclude_flags:
                return f
        return None

    def apply(self, universe: pd.DataFrame,
              avg_turnover: Optional[pd.Series] = None,
              listing_days: Optional[pd.Series] = None) -> FilterResult:
        """
        universe     : data.base.UNIVERSE_COLUMNS 형식
        avg_turnover : code -> N일 평균 거래대금 (없으면 당일 turnover 로 대체)
        listing_days : code -> 상장 후 거래일 수 (없으면 미적용)
        """
        df = universe.copy()
        rejected: Dict[str, int] = {}

        def drop(mask: pd.Series, reason: str) -> None:
            nonlocal df
            n = int(mask.sum())
            if n:
                rejected[reason] = rejected.get(reason, 0) + n
                df = df.loc[~mask]

        if self.cfg.markets:
            drop(~df["market"].isin([m.upper() for m in self.cfg.markets]), "시장제외")
        drop(df["code"].isin(self.manual_exclusions), "수동제외")
        drop(df["name"].astype(str).map(self.name_excluded), "종목명패턴(스팩/우선주/ETF 등)")
        drop(df["flags"].astype(str).map(lambda f: self.flags_excluded(f) is not None), "상태플래그(관리/경고/정지)")
        cap = pd.to_numeric(df["market_cap"], errors="coerce")
        drop(cap.isna() | (cap < self.cfg.min_market_cap), f"시가총액<{self.cfg.min_market_cap/1e8:.0f}억")
        close = pd.to_numeric(df["close"], errors="coerce")
        if self.cfg.min_price > 0:
            drop(close.notna() & (close < self.cfg.min_price), f"주가<{self.cfg.min_price:,}원")
        if self.cfg.max_price > 0:
            drop(close.notna() & (close > self.cfg.max_price), f"주가>{self.cfg.max_price:,}원")
        if self.cfg.min_avg_turnover > 0:
            if avg_turnover is not None:
                t = df["code"].map(avg_turnover)
            else:
                t = pd.to_numeric(df["turnover"], errors="coerce")
            drop(t.isna() | (t < self.cfg.min_avg_turnover), f"거래대금<{self.cfg.min_avg_turnover/1e8:.0f}억")
        if listing_days is not None and self.cfg.min_listing_days > 0:
            ld = df["code"].map(listing_days)
            drop(ld.notna() & (ld < self.cfg.min_listing_days), f"상장{self.cfg.min_listing_days}일미만")
        # 거래대금 상위 N 으로 제한
        if self.cfg.max_candidates and len(df) > self.cfg.max_candidates:
            key = df["code"].map(avg_turnover) if avg_turnover is not None else pd.to_numeric(df["turnover"], errors="coerce")
            df = df.assign(_k=key.fillna(0)).sort_values("_k", ascending=False).head(self.cfg.max_candidates).drop(columns="_k")
        return FilterResult(passed=df.reset_index(drop=True), rejected=rejected)
