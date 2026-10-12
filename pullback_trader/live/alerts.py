"""알림 — 콘솔 + (선택) 텔레그램."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

import requests

from ..config import AlertConfig

log = logging.getLogger("pullback")


class Alerter:
    def __init__(self, cfg: AlertConfig):
        self.cfg = cfg

    def send(self, text: str, level: str = "info") -> None:
        if self.cfg.console:
            stamp = dt.datetime.now().strftime("%H:%M:%S")
            print(f"[{stamp}] {text}")
        if self.cfg.telegram_bot_token and self.cfg.telegram_chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage",
                              json={"chat_id": self.cfg.telegram_chat_id, "text": text[:4000]}, timeout=5)
            except Exception as e:  # pragma: no cover
                log.warning("텔레그램 전송 실패: %s", e)
