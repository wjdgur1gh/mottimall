"""한국투자증권 REST 시세 공급자 — 일봉/당일 분봉/현재가(상태 플래그 포함)."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd

from .base import empty_bars, empty_universe, normalize_bars, resample_bars
from .kis_client import KisClient


def _f(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")


class KisProvider:
    name = "kis"

    def __init__(self, client: KisClient, fallback=None):
        self.client = client
        self.fallback = fallback  # 유니버스 목록은 KIS 가 제공하지 않으므로 다른 공급자 사용

    def universe(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        if self.fallback is not None:
            return self.fallback.universe(date)
        return empty_universe()

    def daily(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        rows: List[Dict] = []
        cur_end = end
        while cur_end >= start:
            js = self.client.get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                                 self.client.tr("daily_chart"), {
                                     "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                     "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                                     "FID_INPUT_DATE_2": cur_end.strftime("%Y%m%d"),
                                     "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
            out = [o for o in js.get("output2", []) if o.get("stck_bsop_date")]
            if not out:
                break
            rows.extend(out)
            oldest = min(o["stck_bsop_date"] for o in out)
            nxt = dt.datetime.strptime(oldest, "%Y%m%d").date() - dt.timedelta(days=1)
            if nxt >= cur_end or len(out) < 100:
                break
            cur_end = nxt
        if not rows:
            return empty_bars()
        df = pd.DataFrame({
            "datetime": [r["stck_bsop_date"] for r in rows],
            "open": [_f(r.get("stck_oprc")) for r in rows],
            "high": [_f(r.get("stck_hgpr")) for r in rows],
            "low": [_f(r.get("stck_lwpr")) for r in rows],
            "close": [_f(r.get("stck_clpr")) for r in rows],
            "volume": [_f(r.get("acml_vol")) for r in rows],
            "value": [_f(r.get("acml_tr_pbmn")) for r in rows],
        })
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y%m%d")
        return normalize_bars(df.set_index("datetime"))

    def minute(self, code: str, date: dt.date, bar_minutes: int = 1) -> pd.DataFrame:
        """당일 분봉: 30건씩 역순으로 반복 조회해 하루치(09:00~) 를 모은다."""
        today = dt.date.today()
        rows: List[Dict] = []
        if date == today:
            hour = "153000"
            seen = set()
            for _ in range(20):
                js = self.client.get("/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
                                     self.client.tr("minute_chart"), {
                                         "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
                                         "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": hour,
                                         "FID_PW_DATA_INCU_YN": "Y"})
                out = [o for o in js.get("output2", []) if o.get("stck_cntg_hour")]
                new = [o for o in out if o["stck_cntg_hour"] not in seen]
                if not new:
                    break
                for o in new:
                    seen.add(o["stck_cntg_hour"])
                rows.extend(new)
                earliest = min(o["stck_cntg_hour"] for o in new)
                if earliest <= "090100":
                    break
                t = dt.datetime.strptime(earliest, "%H%M%S") - dt.timedelta(minutes=1)
                hour = t.strftime("%H%M%S")
        else:
            hour = "153000"
            for _ in range(5):
                js = self.client.get("/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
                                     self.client.tr("minute_chart_past"), {
                                         "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                         "FID_INPUT_HOUR_1": hour, "FID_INPUT_DATE_1": date.strftime("%Y%m%d"),
                                         "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": "N"})
                out = [o for o in js.get("output2", []) if o.get("stck_cntg_hour")]
                if not out:
                    break
                rows.extend(out)
                earliest = min(o["stck_cntg_hour"] for o in out)
                if earliest <= "090100" or len(out) < 120:
                    break
                t = dt.datetime.strptime(earliest, "%H%M%S") - dt.timedelta(minutes=1)
                hour = t.strftime("%H%M%S")
        if not rows:
            return empty_bars()
        d = date.strftime("%Y%m%d")
        df = pd.DataFrame({
            "datetime": [(r.get("stck_bsop_date") or d) + r["stck_cntg_hour"] for r in rows],
            "open": [_f(r.get("stck_oprc")) for r in rows],
            "high": [_f(r.get("stck_hgpr")) for r in rows],
            "low": [_f(r.get("stck_lwpr")) for r in rows],
            "close": [_f(r.get("stck_prpr")) for r in rows],
            "volume": [_f(r.get("cntg_vol")) for r in rows],
            "value": [float("nan")] * len(rows),
        })
        df["datetime"] = pd.to_datetime(df["datetime"], format="%Y%m%d%H%M%S", errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime")
        # KIS 분봉 시각은 봉의 '종료' 시각(09:01 = 09:00~09:01). 시작 시각 기준으로 1분 당긴다.
        df.index = df.index - pd.Timedelta(minutes=1)
        df = normalize_bars(df)
        return resample_bars(df, bar_minutes)

    def snapshot(self, code: str) -> Dict:
        js = self.client.get("/uapi/domestic-stock/v1/quotations/inquire-price", self.client.tr("price"),
                             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        o = js.get("output", {})
        flags = []
        if str(o.get("mang_issu_cls_code", "N")).upper() == "Y":
            flags.append("관리종목")
        warn = str(o.get("mrkt_warn_cls_code", "00"))
        flags += {"01": ["투자주의"], "02": ["투자경고"], "03": ["투자위험"]}.get(warn, [])
        if str(o.get("temp_stop_yn", "N")).upper() == "Y":
            flags.append("거래정지")
        if str(o.get("sltr_yn", "N")).upper() == "Y":
            flags.append("정리매매")
        if str(o.get("invt_caful_yn", "N")).upper() == "Y":
            flags.append("투자유의")
        return {
            "code": code,
            "name": o.get("hts_kor_isnm", ""),
            "market": "KOSDAQ" if "KOSDAQ" in str(o.get("rprs_mrkt_kor_name", "")).upper() or "코스닥" in str(o.get("rprs_mrkt_kor_name", "")) else "KOSPI",
            "price": _f(o.get("stck_prpr")),
            "open": _f(o.get("stck_oprc")),
            "high": _f(o.get("stck_hgpr")),
            "low": _f(o.get("stck_lwpr")),
            "prev_close": _f(o.get("stck_prpr")) - _f(o.get("prdy_vrss")),
            "upper_limit": _f(o.get("stck_mxpr")),
            "lower_limit": _f(o.get("stck_llam")),
            "volume": _f(o.get("acml_vol")),
            "turnover": _f(o.get("acml_tr_pbmn")),
            "market_cap": _f(o.get("hts_avls")) * 1e8,  # 억원 -> 원
            "shares": _f(o.get("lstn_stcn")),
            "vi": str(o.get("vi_cls_code", "")),
            "flags": ";".join(flags),
            "raw": o,
        }
