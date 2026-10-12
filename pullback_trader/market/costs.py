"""거래비용 모델 (2026년 세율 반영).

- 위탁수수료: 매수/매도 양방향 (증권사 요율, 유관기관 제비용 포함 여부는 설정으로)
- 증권거래세+농어촌특별세: 매도 시에만. 2026.1.1~ 코스피 0.05%+0.15%=0.20%, 코스닥 0.20%
- 슬리피지: 백테스트에서 호가단위 틱으로 보정
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import CostConfig
from .tick import tick_size


@dataclass
class CostBreakdown:
    buy_commission: float
    sell_commission: float
    sell_tax: float

    @property
    def total(self) -> float:
        return self.buy_commission + self.sell_commission + self.sell_tax


class CostModel:
    def __init__(self, cfg: CostConfig):
        self.cfg = cfg

    def sell_tax_pct(self, market: str) -> float:
        m = (market or "").upper()
        if m in ("KOSDAQ", "KQ", "코스닥"):
            return self.cfg.sell_tax_pct_kosdaq
        return self.cfg.sell_tax_pct_kospi

    def buy_fee(self, amount: float) -> float:
        return amount * self.cfg.commission_pct / 100

    def sell_fee(self, amount: float, market: str) -> float:
        return amount * (self.cfg.commission_pct + self.sell_tax_pct(market)) / 100

    def round_trip(self, buy_amount: float, sell_amount: float, market: str) -> CostBreakdown:
        return CostBreakdown(
            buy_commission=self.buy_fee(buy_amount),
            sell_commission=sell_amount * self.cfg.commission_pct / 100,
            sell_tax=sell_amount * self.sell_tax_pct(market) / 100,
        )

    def round_trip_pct(self, market: str) -> float:
        """매수+매도 왕복 비용(%) — 세금·수수료만."""
        return self.cfg.commission_pct * 2 + self.sell_tax_pct(market)

    def breakeven_move_pct(self, price: float, market: str, include_spread: bool = True) -> float:
        """손익분기 상승률(%): 왕복 비용 + (선택) 1틱 스프레드."""
        pct = self.round_trip_pct(market)
        if include_spread and price > 0:
            pct += tick_size(price) / price * 100
        return pct

    def slippage(self, price: float, side: str) -> float:
        """체결가 보정: 매수는 위로, 매도는 아래로 N틱."""
        t = tick_size(price) * self.cfg.slippage_ticks
        return price + t if side == "buy" else price - t
