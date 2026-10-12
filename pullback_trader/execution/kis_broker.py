"""한국투자증권 REST 주문 브로커.

주의
- 실전투자 전 반드시 모의투자(paper=True) 로 검증할 것
- 정정취소에는 주문 시 받은 KRX_FWDG_ORD_ORGNO(주문조직번호) 와 ODNO(주문번호) 가 필요하므로 저장해 둔다
- 스탑(조건부) 주문은 KIS 현금주문 API 에 없다. 이 브로커는 스탑을 '감시' 상태로 두고
  live 러너가 현재가가 스탑가 이하가 되면 시장가 매도를 낸다 (check_stops 호출)
- 호출 제한: 실전 20건/초, 모의 2건/초
"""
from __future__ import annotations

import datetime as dt
import itertools
from typing import Dict, List, Optional

from ..data.kis_client import KisClient, KisError
from .base import Order, Position

ORD_DVSN = {"limit": "00", "market": "01"}


class KisBroker:
    name = "kis"

    def __init__(self, client: KisClient):
        self.client = client
        self.cano, self.prdt = client.account_parts()
        self._orders: Dict[str, Order] = {}
        self._stops: Dict[str, Order] = {}
        self._seq = itertools.count(1)

    # ------------------------------------------------------------ orders
    def _order(self, code: str, side: str, qty: int, price: Optional[int], kind: str, tag: str) -> Order:
        body = {
            "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "PDNO": code,
            "ORD_DVSN": ORD_DVSN[kind], "ORD_QTY": str(int(qty)),
            "ORD_UNPR": str(int(price)) if kind == "limit" else "0",
            "EXCG_ID_DVSN_CD": "KRX",
        }
        if side == "sell":
            body["SLL_TYPE"] = "01"
        tr = self.client.tr("order_buy" if side == "buy" else "order_sell")
        js = self.client.post("/uapi/domestic-stock/v1/trading/order-cash", tr, body)
        out = js.get("output", {})
        o = Order(id=str(out.get("ODNO", f"K{next(self._seq)}")), code=code, side=side, qty=int(qty), price=price,
                  kind=kind, tag=tag, created_at=dt.datetime.now(),
                  meta={"KRX_FWDG_ORD_ORGNO": out.get("KRX_FWDG_ORD_ORGNO", ""), "ORD_TMD": out.get("ORD_TMD", "")})
        self._orders[o.id] = o
        return o

    def submit_limit(self, code: str, side: str, qty: int, price: int, tag: str = "") -> Order:
        return self._order(code, side, qty, int(price), "limit", tag)

    def submit_market(self, code: str, side: str, qty: int, tag: str = "") -> Order:
        return self._order(code, side, qty, None, "market", tag)

    def submit_stop(self, code: str, qty: int, stop_price: int, tag: str = "") -> Order:
        """서버 스탑이 없으므로 로컬 감시 주문으로 등록."""
        o = Order(id=f"S{next(self._seq):06d}", code=code, side="sell", qty=int(qty), price=None, kind="stop",
                  stop_price=int(stop_price), tag=tag, created_at=dt.datetime.now())
        self._stops[o.id] = o
        return o

    def check_stops(self, last_prices: Dict[str, float]) -> List[Order]:
        """현재가가 스탑가 이하이면 시장가 매도. 발동된 주문 목록 반환."""
        fired: List[Order] = []
        for o in list(self._stops.values()):
            if o.status != "open":
                continue
            px = last_prices.get(o.code)
            if px is not None and px <= o.stop_price:
                mo = self.submit_market(o.code, "sell", o.qty, tag=o.tag or "stop")
                o.status = "filled"
                o.meta["market_order_id"] = mo.id
                fired.append(mo)
        return fired

    def cancel(self, order_id: str) -> bool:
        if order_id in self._stops:
            self._stops[order_id].status = "cancelled"
            return True
        o = self._orders.get(order_id)
        if o is None:
            return False
        body = {
            "CANO": self.cano, "ACNT_PRDT_CD": self.prdt,
            "KRX_FWDG_ORD_ORGNO": o.meta.get("KRX_FWDG_ORD_ORGNO", ""), "ORGN_ODNO": o.id,
            "ORD_DVSN": ORD_DVSN.get(o.kind, "00"), "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": "0", "ORD_UNPR": "0", "QTY_ALL_ORD_YN": "Y",
        }
        try:
            self.client.post("/uapi/domestic-stock/v1/trading/order-rvsecncl", self.client.tr("order_modify_cancel"), body)
        except KisError:
            return False
        o.status = "cancelled"
        return True

    def cancel_all(self, code: Optional[str] = None) -> int:
        n = 0
        for o in list(self._orders.values()) + list(self._stops.values()):
            if o.status == "open" and (code is None or o.code == code):
                if self.cancel(o.id):
                    n += 1
        return n

    def open_orders(self, code: Optional[str] = None) -> List[Order]:
        """실전: 정정취소가능주문조회로 동기화. 모의: 로컬 기록."""
        if not self.client.cfg.paper:
            try:
                js = self.client.get("/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl", self.client.tr("open_orders"), {
                    "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
                    "INQR_DVSN_1": "0", "INQR_DVSN_2": "0"})
                live_ids = {str(o.get("odno")) for o in js.get("output", [])}
                for o in self._orders.values():
                    if o.status == "open" and o.id not in live_ids:
                        o.status = "filled"
            except KisError:
                pass
        return [o for o in list(self._orders.values()) + list(self._stops.values())
                if o.status == "open" and (code is None or o.code == code)]

    # ------------------------------------------------------------ account
    def _balance(self) -> Dict:
        return self.client.get("/uapi/domestic-stock/v1/trading/inquire-balance", self.client.tr("balance"), {
            "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})

    def positions(self) -> Dict[str, Position]:
        js = self._balance()
        out: Dict[str, Position] = {}
        for h in js.get("output1", []):
            qty = int(float(h.get("hldg_qty", 0) or 0))
            if qty > 0:
                out[h["pdno"]] = Position(code=h["pdno"], qty=qty, avg_price=float(h.get("pchs_avg_pric", 0) or 0))
        return out

    def cash(self) -> float:
        js = self._balance()
        o2 = js.get("output2") or [{}]
        row = o2[0] if isinstance(o2, list) else o2
        return float(row.get("dnca_tot_amt", 0) or 0)

    def buyable_cash(self, code: str, price: int) -> float:
        js = self.client.get("/uapi/domestic-stock/v1/trading/inquire-psbl-order", self.client.tr("psbl_order"), {
            "CANO": self.cano, "ACNT_PRDT_CD": self.prdt, "PDNO": code, "ORD_UNPR": str(price), "ORD_DVSN": "00",
            "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"})
        return float(js.get("output", {}).get("ord_psbl_cash", 0) or 0)
