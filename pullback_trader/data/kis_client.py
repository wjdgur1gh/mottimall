"""한국투자증권 KIS Developers REST 클라이언트 (시세 + 주문 공통).

- 실전: https://openapi.koreainvestment.com:9443 / 모의: https://openapivts.koreainvestment.com:29443
- 토큰: POST /oauth2/tokenP {grant_type: client_credentials, appkey, appsecret} (하루 1회 발급 권장, 파일 캐시)
- 호출 제한: 실전 초당 20건, 모의 초당 2건 → 간격 조절
- tr_id 는 KIS Developers 포털 문서 기준(2025~2026). 변경 시 TR 사전만 수정하면 된다.

미래에셋증권은 개인용 Open API 를 제공하지 않으므로, 완전 자동주문이 필요하면
한국투자증권 계좌를 추가로 개설해 이 클라이언트를 사용한다.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..config import KisConfig

REAL_URL = "https://openapi.koreainvestment.com:9443"
PAPER_URL = "https://openapivts.koreainvestment.com:29443"

TR = {
    # 시세
    "price": "FHKST01010100",            # 주식현재가 시세
    "daily_chart": "FHKST03010100",      # 국내주식 기간별 시세 (일/주/월/년)
    "minute_chart": "FHKST03010200",     # 주식 당일 분봉 조회 (30건/회)
    "minute_chart_past": "FHKST03010230",  # 주식 일별 분봉 조회 (120건/회)
    # 주문/계좌 (실전 / 모의)
    "order_buy": ("TTTC0012U", "VTTC0012U"),
    "order_sell": ("TTTC0011U", "VTTC0011U"),
    "order_modify_cancel": ("TTTC0013U", "VTTC0013U"),
    "balance": ("TTTC8434R", "VTTC8434R"),
    "psbl_order": ("TTTC8908R", "VTTC8908R"),      # 매수가능조회
    "open_orders": ("TTTC0084R", None),           # 정정취소가능주문조회 (실전 전용)
}


class KisError(RuntimeError):
    pass


class KisClient:
    def __init__(self, cfg: KisConfig, request_interval_sec: Optional[float] = None):
        if not cfg.app_key or not cfg.app_secret:
            raise KisError("KIS app_key / app_secret 이 설정되지 않았습니다 (환경변수 KIS_APP_KEY, KIS_APP_SECRET)")
        self.cfg = cfg
        self.base = PAPER_URL if cfg.paper else REAL_URL
        self.interval = request_interval_sec if request_interval_sec is not None else (0.55 if cfg.paper else 0.06)
        self._last = 0.0
        self._token: Optional[str] = None
        self._token_exp: Optional[dt.datetime] = None
        self.session = requests.Session()

    # ------------------------------------------------------------------ auth
    def _load_token_cache(self) -> None:
        p = Path(self.cfg.token_cache)
        if not p.exists():
            return
        try:
            js = json.loads(p.read_text(encoding="utf-8"))
            if js.get("base") != self.base:
                return
            exp = dt.datetime.fromisoformat(js["expires_at"])
            if exp - dt.datetime.now() > dt.timedelta(minutes=10):
                self._token, self._token_exp = js["access_token"], exp
        except Exception:
            return

    def _save_token_cache(self) -> None:
        p = Path(self.cfg.token_cache)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"base": self.base, "access_token": self._token,
                                 "expires_at": self._token_exp.isoformat()}), encoding="utf-8")

    def token(self) -> str:
        if self._token is None:
            self._load_token_cache()
        if self._token and self._token_exp and self._token_exp - dt.datetime.now() > dt.timedelta(minutes=10):
            return self._token
        r = self.session.post(f"{self.base}/oauth2/tokenP",
                              json={"grant_type": "client_credentials", "appkey": self.cfg.app_key,
                                    "appsecret": self.cfg.app_secret}, timeout=10)
        if r.status_code != 200:
            raise KisError(f"토큰 발급 실패: {r.status_code} {r.text[:200]}")
        js = r.json()
        self._token = js["access_token"]
        expires_in = int(js.get("expires_in", 86400))
        self._token_exp = dt.datetime.now() + dt.timedelta(seconds=expires_in)
        self._save_token_cache()
        return self._token

    def _headers(self, tr_id: str, tr_cont: str = "") -> Dict[str, str]:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": self.cfg.app_key,
            "appsecret": self.cfg.app_secret,
            "tr_id": tr_id,
            "tr_cont": tr_cont,
            "custtype": "P",
        }

    def tr(self, key: str) -> str:
        v = TR[key]
        if isinstance(v, tuple):
            v = v[1] if self.cfg.paper else v[0]
        if v is None:
            raise KisError(f"'{key}' 는 모의투자에서 지원되지 않습니다")
        return v

    # ------------------------------------------------------------------ http
    def _throttle(self) -> None:
        wait = self.interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, path: str, tr_id: str, params: Dict[str, Any], tr_cont: str = "") -> Dict[str, Any]:
        self._throttle()
        r = self.session.get(f"{self.base}{path}", headers=self._headers(tr_id, tr_cont), params=params, timeout=10)
        return self._check(r)

    def post(self, path: str, tr_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self._throttle()
        r = self.session.post(f"{self.base}{path}", headers=self._headers(tr_id), data=json.dumps(body), timeout=10)
        return self._check(r)

    @staticmethod
    def _check(r: requests.Response) -> Dict[str, Any]:
        try:
            js = r.json()
        except ValueError:
            raise KisError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code != 200 or str(js.get("rt_cd", "0")) != "0":
            raise KisError(f"KIS 오류 rt_cd={js.get('rt_cd')} msg_cd={js.get('msg_cd')} msg={js.get('msg1')}")
        return js

    # ----------------------------------------------------------- shortcuts
    def account_parts(self):
        acct = self.cfg.account_no.replace("-", "")
        cano, prdt = (acct[:8], acct[8:10]) if len(acct) >= 10 else (acct, self.cfg.product_code)
        return cano, prdt or self.cfg.product_code
