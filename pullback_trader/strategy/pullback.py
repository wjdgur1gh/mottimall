"""눌림목(Pullback) 셋업 감지.

정의 (스윙/데이 공통, 파라미터만 다름):
 1. 추세 : 종가 > 단기 이평(MA20) 이고 단기 이평 > 장기 이평(MA60)  [일봉]
           데이트레이딩은 VWAP 위 + 당일 임펄스로 대체
 2. 임펄스: 최근 N봉 안의 최고가(H) 와 그 이전 M봉 안의 최저가(L) 사이 상승률 >= impulse_min_gain_pct
 3. 눌림  : H 이후 봉 수가 [min,max] 이내, 눌림 저점(PL) 의 깊이/되돌림 비율이 범위 안
 4. 거래량: 눌림 구간 평균 거래량 / 임펄스 구간 평균 거래량 <= volume_ratio_max (매물 소화 확인)
 5. 지지  : PL 이 지지 이평선(5/10/20 또는 VWAP) 근처 또는 위에서 유지, 종가가 must_hold_ma 위
 6. 트리거: (confirm) 마지막 봉이 양봉 & 직전봉 고가 돌파 & 거래량 증가, 아직 과도하게 반등하지 않음
            (anticipate) 트리거 없이 지지선 예약 매수 (사다리 1차가 = 지지선)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .indicators import atr as _atr
from .indicators import vwap as _vwap

MAX_RECOVERY_RATIO = 0.6   # 트리거 시점 (close-PL)/(H-PL) 상한 — 추격매수 방지


@dataclass
class PullbackSetup:
    as_of: pd.Timestamp
    close: float
    impulse_low: float
    impulse_low_time: pd.Timestamp
    impulse_high: float
    impulse_high_time: pd.Timestamp
    impulse_gain_pct: float
    pullback_low: float
    pullback_low_time: pd.Timestamp
    pullback_bars: int
    depth_pct: float
    retrace: float
    volume_ratio: float
    support_level: float
    support_name: str
    atr: float
    triggered: bool
    score: float
    ma: Dict[int, float] = field(default_factory=dict)
    vwap: float = float("nan")
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"임펄스 {self.impulse_low:,.0f}→{self.impulse_high:,.0f} (+{self.impulse_gain_pct:.1f}%), "
                f"눌림 {self.pullback_bars}봉 저점 {self.pullback_low:,.0f} (깊이 {self.depth_pct:.1f}%, 되돌림 {self.retrace:.2f}), "
                f"거래량비 {self.volume_ratio:.2f}, 지지 {self.support_name} {self.support_level:,.0f}, "
                f"{'반등확인' if self.triggered else '대기'} score {self.score:.0f}")


def _cfg(cfg, name, default):
    return getattr(cfg, name, default)


def detect_pullback(bars: pd.DataFrame, cfg, *, intraday: bool = False,
                    prev_close: Optional[float] = None,
                    reasons: Optional[List[str]] = None) -> Optional[PullbackSetup]:
    """bars 의 마지막 봉 시점에서 눌림목 셋업을 평가한다. 조건 미충족이면 None (reasons 에 사유 기록)."""
    rs: List[str] = reasons if reasons is not None else []
    n = len(bars)
    lookback = int(_cfg(cfg, "impulse_lookback", 0) or (_cfg(cfg, "impulse_max_bars", 40) + _cfg(cfg, "pullback_max_bars", 20)))
    trend_slow = int(_cfg(cfg, "trend_ma_slow", 0) or 0)
    # 일봉은 장기 이평 계산분, 분봉은 임펄스+눌림 최소 봉수만 있으면 된다
    min_bars = 10 if intraday else max(trend_slow + 1 if trend_slow else 0, 10)
    if n < min_bars:
        rs.append(f"데이터 부족 ({n}<{min_bars})")
        return None

    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    vol = bars["volume"].astype(float).fillna(0)
    c = float(close.iloc[-1])

    # ---------------- 0. 빠른 사전검사: 탐색창 안에 임펄스가 될 만한 범위가 없으면 즉시 종료
    lookback = int(_cfg(cfg, "impulse_lookback", 0) or (_cfg(cfg, "impulse_max_bars", 40) + _cfg(cfg, "pullback_max_bars", 20)))
    span = max(lookback + int(_cfg(cfg, "impulse_max_bars", 25)) + 1, 10)
    hw_, lw_ = high.iloc[-span:], low.iloc[-span:]
    if lw_.min() <= 0 or (hw_.max() / lw_.min() - 1) * 100 < float(_cfg(cfg, "impulse_min_gain_pct", 10)):
        rs.append("탐색창 내 임펄스 없음")
        return None

    # ---------------- 1. 추세 / 갭 필터
    ma: Dict[int, float] = {}
    needed = set(_cfg(cfg, "support_mas", [5, 10, 20]))
    fast, slow = int(_cfg(cfg, "trend_ma_fast", 0) or 0), trend_slow
    for k in (fast, slow, int(_cfg(cfg, "must_hold_ma", 0) or 0)):
        if k:
            needed.add(k)
    for k in sorted(needed):
        if k and n >= k:
            ma[k] = float(close.iloc[-k:].mean())
    if fast and _cfg(cfg, "require_close_above_fast_ma", True) and fast in ma and c < ma[fast]:
        rs.append(f"종가<MA{fast}")
        return None
    if fast and slow and _cfg(cfg, "require_fast_above_slow", True) and fast in ma and slow in ma and ma[fast] < ma[slow]:
        rs.append(f"MA{fast}<MA{slow}")
        return None
    vw = float("nan")
    if intraday:
        vw = float(_vwap(bars).iloc[-1])
        if _cfg(cfg, "require_above_vwap", True) and not np.isnan(vw) and c < vw:
            rs.append("종가<VWAP")
            return None
        gap_max = _cfg(cfg, "gap_up_max_pct", 0)
        if prev_close and gap_max and (float(bars["open"].iloc[0]) / prev_close - 1) * 100 > gap_max:
            rs.append(f"갭상승>{gap_max}%")
            return None

    # ---------------- 2. 임펄스
    win_start = max(0, n - lookback - 1)
    hw = high.iloc[win_start:]
    # 최고가가 여러 번이면 가장 최근 것
    iH = win_start + int(np.flatnonzero(hw.values == hw.values.max())[-1])
    H = float(high.iloc[iH])
    pb_bars = n - 1 - iH
    if pb_bars < int(_cfg(cfg, "pullback_min_bars", 2)):
        rs.append(f"눌림 봉수 부족 ({pb_bars})")
        return None
    if pb_bars > int(_cfg(cfg, "pullback_max_bars", 12)):
        rs.append(f"눌림 길이 초과 ({pb_bars})")
        return None
    seg_start = max(0, iH - int(_cfg(cfg, "impulse_max_bars", 25)))
    lw = low.iloc[seg_start:iH + 1]
    iL = seg_start + int(np.flatnonzero(lw.values == lw.values.min())[0])
    L = float(low.iloc[iL])
    if L <= 0 or H <= L:
        rs.append("임펄스 없음")
        return None
    gain = (H - L) / L * 100
    if gain < float(_cfg(cfg, "impulse_min_gain_pct", 10)):
        rs.append(f"임펄스 상승률 부족 ({gain:.1f}%)")
        return None

    # ---------------- 3. 눌림 깊이/되돌림
    pb = bars.iloc[iH + 1:]
    iPL = iH + 1 + int(np.flatnonzero(pb["low"].values == pb["low"].values.min())[0])
    PL = float(low.iloc[iPL])
    depth = (H - PL) / H * 100
    retrace = (H - PL) / (H - L)
    if depth < float(_cfg(cfg, "pullback_min_depth_pct", 3)):
        rs.append(f"눌림 깊이 부족 ({depth:.1f}%)")
        return None
    if depth > float(_cfg(cfg, "pullback_max_depth_pct", 20)):
        rs.append(f"눌림 과대 ({depth:.1f}%)")
        return None
    if not (float(_cfg(cfg, "retrace_min", 0.236)) <= retrace <= float(_cfg(cfg, "retrace_max", 0.618))):
        rs.append(f"되돌림 비율 범위 밖 ({retrace:.2f})")
        return None

    # ---------------- 4. 거래량 수축
    imp_vol = float(vol.iloc[iL:iH + 1].mean())
    pb_vol = float(vol.iloc[iH + 1:].mean())
    vratio = pb_vol / imp_vol if imp_vol > 0 else float("nan")
    if not np.isnan(vratio) and vratio > float(_cfg(cfg, "volume_ratio_max", 0.85)):
        rs.append(f"눌림 거래량 과다 (비율 {vratio:.2f})")
        return None

    # ---------------- 5. 지지
    tol = float(_cfg(cfg, "support_tolerance_pct", 2.0))
    candidates: List[tuple] = []
    for k in _cfg(cfg, "support_mas", [5, 10, 20]):
        if k in ma and not np.isnan(ma[k]):
            candidates.append((f"MA{k}", ma[k]))
    if intraday and not np.isnan(vw):
        candidates.append(("VWAP", vw))
    support_name, support_level = "", float("nan")
    best = None
    for name, lvl in candidates:
        if lvl <= 0:
            continue
        if PL >= lvl * (1 - tol / 100):  # 저점이 지지선 위 또는 허용오차 안
            dist = abs(PL - lvl) / lvl
            if best is None or dist < best[0]:
                best = (dist, name, lvl)
    if best is None:
        rs.append("지지 이평선 이탈")
        return None
    _, support_name, support_level = best
    hold = int(_cfg(cfg, "must_hold_ma", 0) or 0)
    if hold and hold in ma and c < ma[hold]:
        rs.append(f"종가<MA{hold} (지지 붕괴)")
        return None

    # ---------------- 6. 트리거
    recovery = (c - PL) / (H - PL) if H > PL else 1.0
    triggered = False
    trigger_offset = 0
    if _cfg(cfg, "entry_mode", "confirm") == "confirm":
        need_brk = _cfg(cfg, "trigger_close_above_prev_high", True)
        vr = float(_cfg(cfg, "trigger_volume_ratio", 1.2))
        opens, closes, highs, vols = bars["open"].values, close.values, high.values, vol.values

        def is_trigger(i: int) -> bool:  # i: 음수 인덱스
            if n + i - 1 < iH + 1:       # 확인봉은 눌림 구간 안에 있어야 함
                return False
            bullish = closes[i] > opens[i]
            brk = (closes[i] > highs[i - 1]) if need_brk else True
            vol_ok = vols[i] >= vols[i - 1] * vr
            return bool(bullish and brk and vol_ok)

        for k in range(0, int(_cfg(cfg, "trigger_lookback_bars", 0)) + 1):
            i = -1 - k
            if n + i - 1 < 0:
                break
            if is_trigger(i):
                # 확인봉 이후 봉들은 확인봉 시가 위에서 마감해야 유효(반등이 꺾이지 않음)
                held = all(closes[j] >= opens[i] for j in range(n + i + 1, n))
                if held:
                    triggered, trigger_offset = True, k
                    break
        if not triggered:
            rs.append("반등 확인봉 없음 (양봉+직전고가 돌파+거래량 증가 필요)")
            return None
        if recovery > MAX_RECOVERY_RATIO:
            rs.append(f"이미 반등 진행 ({recovery:.0%} 회복) — 추격 금지")
            return None
    else:
        if c >= H:
            rs.append("신고가 갱신 — 눌림 아님")
            return None

    # ---------------- 점수
    r_s = max(0.0, 1 - abs(retrace - 0.45) / 0.45)
    v_s = min(1.0, max(0.0, 1 - vratio)) if not np.isnan(vratio) else 0.5
    base_ma = ma.get(slow) if slow and slow in ma else (vw if intraday and not np.isnan(vw) else ma.get(fast, c))
    t_s = min(1.0, max(0.0, (c / base_ma - 1) / 0.2)) if base_ma and base_ma > 0 else 0.5
    g_s = min(1.0, gain / (2 * float(_cfg(cfg, "impulse_min_gain_pct", 10))))
    score = 100 * (0.35 * r_s + 0.25 * v_s + 0.2 * t_s + 0.2 * g_s)

    a = _atr(bars.iloc[-16:], 14)
    atr_v = float(a.iloc[-1]) if len(a) and not np.isnan(a.iloc[-1]) else float(high.iloc[-5:].mean() - low.iloc[-5:].mean())
    return PullbackSetup(
        as_of=bars.index[-1], close=c,
        impulse_low=L, impulse_low_time=bars.index[iL],
        impulse_high=H, impulse_high_time=bars.index[iH], impulse_gain_pct=gain,
        pullback_low=PL, pullback_low_time=bars.index[iPL], pullback_bars=pb_bars,
        depth_pct=depth, retrace=retrace, volume_ratio=vratio,
        support_level=support_level, support_name=support_name, atr=atr_v,
        triggered=triggered, score=score, ma=ma, vwap=vw,
        notes=[f"확인봉 {trigger_offset}봉 전"] if trigger_offset else [],
    )
