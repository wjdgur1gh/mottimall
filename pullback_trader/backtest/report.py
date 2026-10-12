"""백테스트 성과 요약."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from .engine import BacktestResult, Trade


def trades_to_frame(trades: List[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([t.__dict__ for t in trades])


def max_drawdown(curve: pd.Series) -> float:
    if curve is None or len(curve) == 0:
        return 0.0
    peak = curve.cummax()
    dd = (curve / peak - 1) * 100
    return float(dd.min())


def summarize(res: BacktestResult) -> Dict:
    df = trades_to_frame(res.trades)
    out: Dict = {
        "mode": res.mode, "signals": res.signals, "expired_ladders": res.expired_ladders, "pending_ladders": res.pending_ladders,
        "trades": int(len(df)), "initial_equity": res.initial_equity, "final_equity": res.final_equity,
        "return_pct": (res.final_equity / res.initial_equity - 1) * 100 if res.initial_equity else 0.0,
        "max_drawdown_pct": max_drawdown(res.equity_curve),
    }
    if len(df) == 0:
        return out
    wins, losses = df[df.net_pnl > 0], df[df.net_pnl <= 0]
    gp, gl = float(wins.net_pnl.sum()), float(-losses.net_pnl.sum())
    out.update({
        "win_rate_pct": len(wins) / len(df) * 100,
        "avg_win": float(wins.net_pnl.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.net_pnl.mean()) if len(losses) else 0.0,
        "payoff_ratio": (float(wins.net_pnl.mean()) / abs(float(losses.net_pnl.mean()))) if len(wins) and len(losses) and losses.net_pnl.mean() != 0 else float("nan"),
        "profit_factor": gp / gl if gl > 0 else float("inf"),
        "expectancy": float(df.net_pnl.mean()),
        "expectancy_r": float(df.r_multiple.mean()),
        "avg_pnl_pct": float(df.pnl_pct.mean()),
        "total_net_pnl": float(df.net_pnl.sum()),
        "total_costs": float(df.costs.sum()),
        "avg_bars_held": float(df.bars_held.mean()),
        "avg_tranches_filled": float(df.tranches_filled.mean()),
        "tranche_fill_dist": df.tranches_filled.value_counts().sort_index().to_dict(),
        "exit_reasons": df.exit_reason.value_counts().to_dict(),
        "avg_mae_pct": float(df.mae_pct.mean()),
        "avg_mfe_pct": float(df.mfe_pct.mean()),
    })
    # 체결 차수별 승률 (1:2:3:4 분할의 효과 점검)
    by = df.groupby("tranches_filled").agg(n=("net_pnl", "size"), win_rate=("net_pnl", lambda s: (s > 0).mean() * 100), avg_r=("r_multiple", "mean"))
    out["by_tranches"] = {int(k): {"n": int(v.n), "win_rate": float(v.win_rate), "avg_r": float(v.avg_r)} for k, v in by.iterrows()}
    return out


def format_report(s: Dict) -> str:
    lines = [f"=== 백테스트 결과 ({'스윙' if s['mode'] == 'swing' else '데이트레이딩'}) ===",
             f"신호 {s['signals']} / 거래 {s['trades']} / 미체결 만료 {s['expired_ladders']} / 기간말 대기 {s.get('pending_ladders', 0)}",
             f"초기자산 {s['initial_equity']:,.0f} → 최종 {s['final_equity']:,.0f} ({s['return_pct']:+.2f}%)  MDD {s['max_drawdown_pct']:.2f}%"]
    if s["trades"] == 0:
        lines.append("거래 없음")
        return "\n".join(lines)
    lines += [
        f"승률 {s['win_rate_pct']:.1f}%  평균수익 {s['avg_win']:,.0f}  평균손실 {s['avg_loss']:,.0f}  손익비 {s['payoff_ratio']:.2f}  PF {s['profit_factor']:.2f}",
        f"기대값 {s['expectancy']:,.0f}원/거래 ({s['expectancy_r']:+.2f}R, {s['avg_pnl_pct']:+.2f}%)  순손익 {s['total_net_pnl']:,.0f}  비용 {s['total_costs']:,.0f}",
        f"평균 보유 {s['avg_bars_held']:.1f}봉  평균 체결차수 {s['avg_tranches_filled']:.2f}  MAE {s['avg_mae_pct']:.2f}%  MFE {s['avg_mfe_pct']:.2f}%",
        f"청산사유 {s['exit_reasons']}",
        "체결차수별: " + ", ".join(f"{k}차 n={v['n']} 승률 {v['win_rate']:.0f}% avgR {v['avg_r']:+.2f}" for k, v in s["by_tranches"].items()),
    ]
    return "\n".join(lines)
