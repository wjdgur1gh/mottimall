from __future__ import annotations

from ..config import AppConfig
from .base import BAR_COLUMNS, UNIVERSE_COLUMNS, DataProvider, empty_bars, empty_universe, normalize_bars, normalize_universe, resample_bars
from .cache import BarCache
from .csv_provider import CsvProvider


def make_provider(cfg: AppConfig):
    """설정의 data.provider 에 따라 공급자 생성."""
    p = cfg.data.provider
    if p == "csv":
        return CsvProvider(cfg.data.csv_dir)
    if p == "naver":
        from .naver import NaverProvider
        return NaverProvider(cfg.data.request_interval_sec)
    if p == "pykrx":
        from .pykrx_provider import PykrxProvider
        return PykrxProvider(max(cfg.data.request_interval_sec, 0.5))
    if p == "fdr":
        from .fdr_provider import FdrProvider
        return FdrProvider()
    if p == "kis":
        from .kis_client import KisClient
        from .kis_provider import KisProvider
        from .naver import NaverProvider
        client = KisClient(cfg.broker.kis)
        return KisProvider(client, fallback=NaverProvider(cfg.data.request_interval_sec))
    raise ValueError(f"알 수 없는 provider: {p}")


__all__ = [
    "BAR_COLUMNS", "UNIVERSE_COLUMNS", "DataProvider", "empty_bars", "empty_universe",
    "normalize_bars", "normalize_universe", "resample_bars", "BarCache", "CsvProvider", "make_provider",
]
