"""주문표 생성 — 미래에셋증권 카이로스(HTS) 등에서 수동 입력하기 위한 표.

출력
- Markdown: 종목별 사다리(1~4차), 손절/목표, 리스크 요약, 무효화 규칙
- CSV: 한 줄에 주문 하나 (종목코드, 종목명, 구분, 주문유형, 가격, 수량, 금액, 비고)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..strategy.sizing import OrderPlan


def plans_to_rows(plans: List[OrderPlan]) -> List[Dict]:
    rows: List[Dict] = []
    for p in plans:
        for t in p.tranches:
            kind = "시장가(즉시)" if (t.level == 1 and p.first_tranche_market) else "지정가"
            rows.append({"종목코드": p.code, "종목명": p.name, "시장": p.market, "구분": "매수", "주문유형": kind,
                         "가격": t.price, "수량": t.qty, "금액": t.amount, "비고": f"{t.level}차 ({t.weight:.0%})", "유효기간": p.valid_until})
        rows.append({"종목코드": p.code, "종목명": p.name, "시장": p.market, "구분": "매도", "주문유형": "스탑(조건부)",
                     "가격": p.stop_price, "수량": p.total_qty, "금액": p.stop_price * p.total_qty, "비고": "손절 — 보유 전량", "유효기간": p.valid_until})
        q1 = int(round(p.total_qty * p.partial_exit_ratio))
        rows.append({"종목코드": p.code, "종목명": p.name, "시장": p.market, "구분": "매도", "주문유형": "지정가",
                     "가격": p.target1_price, "수량": q1, "금액": p.target1_price * q1, "비고": f"1차 목표 (보유의 {p.partial_exit_ratio:.0%})", "유효기간": p.valid_until})
        rows.append({"종목코드": p.code, "종목명": p.name, "시장": p.market, "구분": "매도", "주문유형": "지정가",
                     "가격": p.target2_price, "수량": p.total_qty - q1, "금액": p.target2_price * (p.total_qty - q1), "비고": "2차 목표 (잔량)", "유효기간": p.valid_until})
    return rows


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def plan_to_markdown(p: OrderPlan) -> str:
    s = p.setup
    lines = [f"### {p.name} ({p.code}, {p.market}) — {'스윙' if p.mode == 'swing' else '데이트레이딩'}  score {p.score:.0f}"]
    if s is not None:
        lines.append(f"- 셋업: {s.describe()}")
        lines.append(f"- 기준시각 {p.as_of} / 기준가 {_fmt(p.reference_price)}원 / ATR {_fmt(s.atr)}")
    lines.append("")
    lines.append("| 차수 | 비중 | 매수가 | 수량 | 금액 |")
    lines.append("|---:|---:|---:|---:|---:|")
    for t in p.tranches:
        tag = " (시장가)" if (t.level == 1 and p.first_tranche_market) else ""
        lines.append(f"| {t.level}차 | {t.weight:.0%} | {_fmt(t.price)}{tag} | {t.qty:,} | {_fmt(t.amount)} |")
    lines.append(f"| 합계 | 100% | 평단 {_fmt(p.avg_price_all)} | {p.total_qty:,} | {_fmt(p.total_amount)} |")
    lines.append("")
    lines.append(f"- **손절가 {_fmt(p.stop_price)}원** (전량 체결 시 최대손실 {_fmt(p.risk_amount_all)}원 = 계좌 {p.risk_pct_all:.2f}%, 1차만 체결 시 {_fmt(p.risk_amount_first)}원)")
    lines.append(f"- **1차 목표 {_fmt(p.target1_price)}원** ({p.partial_exit_ratio:.0%} 청산, 1차가 대비 손익비 {p.rr_first:.2f}) / **2차 목표 {_fmt(p.target2_price)}원** (평단 대비 손익비 {p.rr_all:.2f})")
    lines.append(f"- 손익분기 상승률(수수료+세금+1틱) ≈ {p.breakeven_pct:.2f}% / 유효기간 {p.valid_until or '-'}")
    for r in p.invalidation_rules():
        lines.append(f"- 규칙: {r}")
    for w in p.warnings:
        lines.append(f"- ⚠ {w}")
    return "\n".join(lines)


def plans_to_markdown(plans: List[OrderPlan], title: str = "주문표") -> str:
    head = [f"# {title}", "", f"생성 {dt.datetime.now():%Y-%m-%d %H:%M} · 종목 {len(plans)}개", ""]
    if not plans:
        head.append("조건을 만족하는 종목이 없습니다.")
        return "\n".join(head)
    total_amt = sum(p.total_amount for p in plans)
    total_risk = sum(p.risk_amount_all for p in plans)
    head.append(f"총 매수예정금액 {_fmt(total_amt)}원 · 전량체결 시 총 리스크 {_fmt(total_risk)}원")
    head.append("")
    head.append("| 종목 | score | 1차가 | 4차가 | 손절 | 1차목표 | 2차목표 | 총수량 | 금액 | 리스크 |")
    head.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in plans:
        head.append(f"| {p.name}({p.code}) | {p.score:.0f} | {_fmt(p.tranches[0].price)} | {_fmt(p.tranches[-1].price)} | {_fmt(p.stop_price)} | {_fmt(p.target1_price)} | {_fmt(p.target2_price)} | {p.total_qty:,} | {_fmt(p.total_amount)} | {_fmt(p.risk_amount_all)} |")
    head.append("")
    body = [plan_to_markdown(p) for p in plans]
    return "\n".join(head) + "\n\n" + "\n\n".join(body) + "\n"


def save_order_sheet(plans: List[OrderPlan], out_dir: str, stem: Optional[str] = None,
                     title: str = "주문표") -> Tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = stem or f"orders_{dt.datetime.now():%Y%m%d_%H%M}"
    md_path, csv_path = out / f"{stem}.md", out / f"{stem}.csv"
    md_path.write_text(plans_to_markdown(plans, title), encoding="utf-8")
    pd.DataFrame(plans_to_rows(plans)).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return md_path, csv_path
