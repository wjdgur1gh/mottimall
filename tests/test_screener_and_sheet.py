import datetime as dt

import pandas as pd

from pullback_trader.config import UniverseConfig
from pullback_trader.data import normalize_universe
from pullback_trader.data.csv_provider import CsvProvider
from pullback_trader.execution.order_sheet import plans_to_markdown, plans_to_rows, save_order_sheet
from pullback_trader.execution.paper import PaperBroker
from pullback_trader.market.costs import CostModel
from pullback_trader.screener import UniverseFilter
from pullback_trader.strategy import build_plan, detect_pullback


def test_universe_filter_rules(tmp_path):
    u = normalize_universe(pd.DataFrame([
        {"code": "005930", "name": "삼성전자", "market": "KOSPI", "market_cap": 4e14, "close": 80000, "turnover": 1e12, "flags": ""},
        {"code": "005935", "name": "삼성전자우", "market": "KOSPI", "market_cap": 5e13, "close": 65000, "turnover": 1e11, "flags": ""},
        {"code": "000001", "name": "테스트스팩3호", "market": "KOSDAQ", "market_cap": 5e10, "close": 2000, "turnover": 1e9, "flags": ""},
        {"code": "000002", "name": "작은회사", "market": "KOSDAQ", "market_cap": 5e9, "close": 5000, "turnover": 1e10, "flags": ""},
        {"code": "000003", "name": "경고회사", "market": "KOSDAQ", "market_cap": 5e11, "close": 5000, "turnover": 1e10, "flags": "투자경고"},
        {"code": "000004", "name": "정상회사", "market": "KOSDAQ", "market_cap": 5e11, "close": 5000, "turnover": 1e10, "flags": ""},
        {"code": "000005", "name": "KODEX 200", "market": "KOSPI", "market_cap": 5e12, "close": 30000, "turnover": 1e11, "flags": ""},
        {"code": "000006", "name": "대우건설", "market": "KOSPI", "market_cap": 5e12, "close": 4000, "turnover": 1e11, "flags": ""},
        {"code": "000007", "name": "현대차2우B", "market": "KOSPI", "market_cap": 5e12, "close": 4000, "turnover": 1e11, "flags": ""},
        {"code": "000008", "name": "동전주", "market": "KOSDAQ", "market_cap": 5e11, "close": 800, "turnover": 1e10, "flags": ""},
        {"code": "000009", "name": "거래부진", "market": "KOSDAQ", "market_cap": 5e11, "close": 8000, "turnover": 1e8, "flags": ""},
    ]))
    ex = tmp_path / "ex.csv"
    ex.write_text("code\n000004\n", encoding="utf-8")
    cfg = UniverseConfig(exclusion_file=str(ex))
    r = UniverseFilter(cfg).apply(u)
    assert set(r.passed.code) == {"005930", "000006"}
    assert r.rejected["수동제외"] == 1


def test_order_sheet_and_paper_broker(sample_dir, cfg, tmp_path):
    prov = CsvProvider(str(sample_dir))
    bars = prov.daily("900001", dt.date(2025, 1, 1), dt.date(2027, 1, 1))
    s = detect_pullback(bars, cfg.swing)
    plan = build_plan(s, cfg, code="900001", name="가상반도체", market="KOSDAQ", equity=10_000_000, valid_until="2026-10-14")
    rows = plans_to_rows([plan])
    assert len(rows) == 7  # 매수 4 + 손절 1 + 목표 2
    assert sum(r["수량"] for r in rows if r["구분"] == "매수") == plan.total_qty
    md = plans_to_markdown([plan])
    assert "손절가" in md and "1차 목표" in md
    md_path, csv_path = save_order_sheet([plan], str(tmp_path), stem="t")
    assert md_path.exists() and csv_path.exists()

    broker = PaperBroker(CostModel(cfg.cost), 10_000_000, {"900001": "KOSDAQ"})
    for t in plan.tranches:
        broker.submit_limit("900001", "buy", t.qty, t.price, tag=f"L{t.level}")
    broker.submit_stop("900001", plan.total_qty, plan.stop_price, tag="stop")
    p1, p4 = plan.tranches[0].price, plan.tranches[-1].price
    fills = broker.on_bar("900001", pd.Series({"open": p1, "high": p1, "low": p4, "close": p4}), dt.datetime(2026, 10, 12, 15, 30))
    assert len(fills) == 4 and broker.positions()["900001"].qty == plan.total_qty
    assert broker.cash() < 10_000_000
    fills = broker.on_bar("900001", pd.Series({"open": p4, "high": p4, "low": plan.stop_price - 5, "close": plan.stop_price - 5}), dt.datetime(2026, 10, 13, 15, 30))
    assert len(fills) == 1 and fills[0].side == "sell" and not broker.positions()
    assert broker.open_orders() == []
