"""명령행 인터페이스.

  pullback universe   [--date YYYY-MM-DD]                 유니버스 생성/저장
  pullback scan       [--mode swing|day] [--date ...]     눌림목 스캔 + 주문표 생성
  pullback plan       --code 005930 [--mode ...]          단일 종목 플랜
  pullback backtest   [--mode ...] --start --end [--codes ...]
  pullback live       [--mode ...] [--poll 60]            장중 루프 (sheet/paper/kis)
  pullback costs      --price 10000 --qty 100 --market KOSDAQ
  pullback config                                         적용 설정 출력
  pullback hts        [--mode ...]                        카이로스 HTS 화면 세팅값 시트
  pullback sample                                         합성 샘플 데이터 생성
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

from . import __version__
from .config import AppConfig, load_config, to_dict
from .data import BarCache, make_provider
from .market.costs import CostModel
from .market.tick import price_limits, tick_size


def _date(s: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(s) if s else None


def _cfg(args) -> AppConfig:
    cfg = load_config(args.config)
    if getattr(args, "mode", None):
        cfg.mode = args.mode
    if getattr(args, "provider", None):
        cfg.data.provider = args.provider
    if getattr(args, "csv_dir", None):
        cfg.data.csv_dir = args.csv_dir
    if getattr(args, "equity", None):
        cfg.risk.account_equity = int(args.equity)
    if getattr(args, "broker", None):
        cfg.broker.mode = args.broker
    if getattr(args, "weights", None):
        cfg.ladder.weights = [float(x) for x in args.weights.replace(":", ",").split(",")]
        from .config import validate
        validate(cfg)
    return cfg


def _load_universe(cfg: AppConfig, scanner, date: dt.date, codes: Optional[List[str]], no_turnover: bool):
    if codes:
        uni = scanner.provider.universe(date)
        if len(uni):
            sel = uni[uni["code"].isin(codes)]
            missing = set(codes) - set(sel["code"])
            if missing:
                sel = pd.concat([sel, pd.DataFrame([{"code": c, "name": c, "market": "KOSPI", "market_cap": float("nan"),
                                                     "shares": float("nan"), "close": float("nan"), "turnover": float("nan"), "flags": ""} for c in missing])])
            return sel.reset_index(drop=True), f"지정 종목 {len(sel)}"
        return pd.DataFrame([{"code": c, "name": c, "market": "KOSPI", "market_cap": float("nan"), "shares": float("nan"),
                              "close": float("nan"), "turnover": float("nan"), "flags": ""} for c in codes]), f"지정 종목 {len(codes)}"
    return scanner.build_universe(date, with_turnover=not no_turnover, progress=lambda m: print("  ", m))


# ---------------------------------------------------------------------- commands
def cmd_universe(args) -> int:
    from .live.runner import Scanner
    cfg = _cfg(args)
    sc = Scanner(cfg)
    date = _date(args.date) or dt.date.today()
    uni, summary = sc.build_universe(date, with_turnover=not args.no_turnover, progress=lambda m: print("  ", m))
    print(summary)
    out = Path(cfg.output_dir) / f"universe_{date:%Y%m%d}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    uni.to_csv(out, index=False, encoding="utf-8-sig")
    print(uni.head(30).to_string())
    print(f"저장: {out} ({len(uni)} 종목)")
    return 0


def cmd_scan(args) -> int:
    from .execution.order_sheet import plans_to_markdown, save_order_sheet
    from .live.runner import Scanner
    cfg = _cfg(args)
    sc = Scanner(cfg)
    date = _date(args.date) or dt.date.today()
    uni, summary = _load_universe(cfg, sc, date, args.codes, args.no_turnover)
    print(f"유니버스: {summary}")
    if cfg.mode == "swing":
        plans, reasons = sc.scan_swing(uni, date)
    else:
        now = dt.datetime.fromisoformat(args.at) if args.at else dt.datetime.now()
        date = now.date()
        plans, reasons = sc.scan_day(uni, now)
    print(plans_to_markdown(plans, title=f"{'스윙' if cfg.mode == 'swing' else '데이트레이딩'} 주문표 {date}"))
    if args.verbose:
        print("--- 미충족 사유 ---")
        for code, rs in reasons.items():
            print(f"{code}: {'; '.join(rs)}")
    if plans:
        md, csv = save_order_sheet(plans, cfg.output_dir, stem=f"orders_{date:%Y%m%d}_{cfg.mode}",
                                   title=f"{'스윙' if cfg.mode == 'swing' else '데이트레이딩'} 주문표 {date}")
        print(f"저장: {md}, {csv}")
    return 0


def cmd_plan(args) -> int:
    from .execution.order_sheet import plan_to_markdown
    from .live.runner import Scanner
    from .strategy.pullback import detect_pullback
    from .strategy.sizing import build_plan
    cfg = _cfg(args)
    sc = Scanner(cfg)
    date = _date(args.date) or dt.date.today()
    code = args.code.zfill(6)
    uni = sc.provider.universe(date)
    name, market = code, args.market or "KOSPI"
    if len(uni) and code in set(uni["code"]):
        row = uni.set_index("code").loc[code]
        name, market = str(row["name"]), str(row["market"])
    rs: List[str] = []
    if cfg.mode == "swing":
        df = sc.load_daily(code, date)
        setup = detect_pullback(df, cfg.swing, reasons=rs)
        valid = date
        for _ in range(cfg.swing.ladder_valid_days):
            valid = sc.calendar.next_trading_day(valid)
        valid_until = valid.isoformat()
    else:
        now = dt.datetime.fromisoformat(args.at) if args.at else dt.datetime.now()
        m = sc.provider.minute(code, now.date(), cfg.day.bar_minutes)
        m = m.loc[m.index + pd.Timedelta(minutes=cfg.day.bar_minutes) <= pd.Timestamp(now)]
        d = sc.load_daily(code, now.date() - dt.timedelta(days=1))
        setup = detect_pullback(m, cfg.day, intraday=True, prev_close=float(d["close"].iloc[-1]) if len(d) else None, reasons=rs)
        valid_until = (now + dt.timedelta(minutes=cfg.day.ladder_valid_minutes)).strftime("%H:%M")
    if setup is None:
        print(f"{name}({code}): 눌림목 조건 미충족 — {'; '.join(rs)}")
        return 1
    plan = build_plan(setup, cfg, code=code, name=name, market=market, mode=cfg.mode, valid_until=valid_until)
    print(plan_to_markdown(plan))
    return 0


def cmd_backtest(args) -> int:
    from .backtest import DayBacktester, SwingBacktester, format_report, summarize
    from .backtest.report import trades_to_frame
    from .live.runner import Scanner
    cfg = _cfg(args)
    sc = Scanner(cfg)
    start, end = _date(args.start), _date(args.end) or dt.date.today()
    if start is None:
        start = end - dt.timedelta(days=365)
    uni, summary = _load_universe(cfg, sc, end, args.codes, args.no_turnover)
    print(f"유니버스: {summary}")
    meta = {r.code: {"name": r.name, "market": r.market} for r in uni.itertuples()}
    if cfg.mode == "swing":
        daily = {}
        for i, code in enumerate(uni["code"]):
            df = sc.load_daily(code, end)
            if len(df):
                daily[code] = df
        bt = SwingBacktester(cfg, daily, meta)
        res = bt.run(start, end, progress=lambda m: print("  ", m))
    else:
        cal = sc.calendar
        dates = []
        d = start
        while d <= end:
            if cal.is_trading_day(d):
                dates.append(d)
            d += dt.timedelta(days=1)
        daily_cache = {}

        def prev_close(code: str, date: dt.date) -> Optional[float]:
            df = daily_cache.get(code)
            if df is None:
                df = sc.load_daily(code, end)
                daily_cache[code] = df
            if df is None or len(df) == 0:
                return None
            prior = df.loc[df.index < pd.Timestamp(date)]
            return float(prior["close"].iloc[-1]) if len(prior) else None

        bt = DayBacktester(cfg, lambda c, dd: sc.provider.minute(c, dd, cfg.day.bar_minutes), prev_close, meta)
        res = bt.run(list(uni["code"]), dates, progress=lambda m: print("  ", m))
    s = summarize(res)
    print(format_report(s))
    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"backtest_{cfg.mode}_{start:%Y%m%d}_{end:%Y%m%d}"
    trades_to_frame(res.trades).to_csv(out / f"{stem}_trades.csv", index=False, encoding="utf-8-sig")
    res.equity_curve.to_csv(out / f"{stem}_equity.csv", header=["equity"], index_label="date")
    (out / f"{stem}_summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"저장: {out / stem}_*.csv/json")
    return 0


def cmd_live(args) -> int:
    from .live.runner import LiveRunner, Scanner
    cfg = _cfg(args)
    runner = LiveRunner(cfg, Scanner(cfg))
    if cfg.mode == "day":
        runner.run_day_loop(poll_seconds=args.poll)
    else:
        plans = runner.run_once()
        print(f"스윙 플랜 {len(plans)}건 전달")
    return 0


def cmd_costs(args) -> int:
    cfg = _cfg(args)
    cm = CostModel(cfg.cost)
    price, qty, market = args.price, args.qty, args.market.upper()
    amt = price * qty
    b = cm.round_trip(amt, amt, market)
    lo, hi = price_limits(price)
    print(f"가격 {price:,}원 × {qty:,}주 = {amt:,}원 ({market})")
    print(f"호가단위 {tick_size(price)}원 / 하한가 {lo:,} 상한가 {hi:,}")
    print(f"매수수수료 {b.buy_commission:,.0f}  매도수수료 {b.sell_commission:,.0f}  세금 {b.sell_tax:,.0f}  합계 {b.total:,.0f}원")
    print(f"왕복비용 {cm.round_trip_pct(market):.3f}%  손익분기(+1틱) {cm.breakeven_move_pct(price, market):.3f}%")
    return 0


def cmd_config(args) -> int:
    cfg = _cfg(args)
    d = to_dict(cfg)
    d["broker"]["kis"]["app_secret"] = "***" if d["broker"]["kis"]["app_secret"] else ""
    d["broker"]["kis"]["app_key"] = "***" if d["broker"]["kis"]["app_key"] else ""
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


def cmd_hts(args) -> int:
    from .execution.hts_settings import render_hts_settings, save_hts_settings
    cfg = _cfg(args)
    print(render_hts_settings(cfg))
    p = save_hts_settings(cfg, cfg.output_dir)
    print(f"저장: {p}")
    return 0


def cmd_sample(args) -> int:
    import runpy
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_sample_data.py"
    sys.argv = [str(script), "--out", args.out]
    runpy.run_path(str(script), run_name="__main__")
    return 0


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pullback", description="국내주식 눌림목 1:2:3:4 분할매수 도구")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", "-c", default=None, help="설정 YAML (기본 config/config.yaml)")
    p.add_argument("--log", default="INFO")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, mode=True):
        sp.add_argument("--provider", choices=["csv", "naver", "pykrx", "fdr", "kis"])
        sp.add_argument("--csv-dir")
        sp.add_argument("--equity", type=float, help="계좌 자산(원)")
        sp.add_argument("--weights", help="분할 비중, 예: 4,3,2,1 또는 1:2:3:4 (백테스트 비교용)")
        if mode:
            sp.add_argument("--mode", choices=["swing", "day"])

    sp = sub.add_parser("universe", help="유니버스 생성")
    common(sp, mode=False)
    sp.add_argument("--date")
    sp.add_argument("--no-turnover", action="store_true", help="평균 거래대금 계산 생략(빠름)")
    sp.set_defaults(func=cmd_universe)

    sp = sub.add_parser("scan", help="눌림목 스캔 + 주문표")
    common(sp)
    sp.add_argument("--date")
    sp.add_argument("--at", help="데이모드 기준시각 (YYYY-MM-DDTHH:MM)")
    sp.add_argument("--codes", nargs="*")
    sp.add_argument("--no-turnover", action="store_true")
    sp.add_argument("--verbose", "-v", action="store_true")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("plan", help="단일 종목 플랜")
    common(sp)
    sp.add_argument("--code", required=True)
    sp.add_argument("--market")
    sp.add_argument("--date")
    sp.add_argument("--at")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("backtest", help="백테스트")
    common(sp)
    sp.add_argument("--start")
    sp.add_argument("--end")
    sp.add_argument("--codes", nargs="*")
    sp.add_argument("--no-turnover", action="store_true")
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("live", help="장중 루프 / 스윙 1회 실행")
    common(sp)
    sp.add_argument("--broker", choices=["sheet", "paper", "kis"])
    sp.add_argument("--poll", type=int, default=60)
    sp.set_defaults(func=cmd_live)

    sp = sub.add_parser("costs", help="거래비용 계산")
    sp.add_argument("--price", type=int, required=True)
    sp.add_argument("--qty", type=int, default=100)
    sp.add_argument("--market", default="KOSDAQ")
    sp.set_defaults(func=cmd_costs)

    sp = sub.add_parser("config", help="적용 설정 출력")
    common(sp)
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("hts", help="카이로스 HTS 화면 세팅값 시트 생성 (설정값 기반)")
    common(sp)
    sp.set_defaults(func=cmd_hts)

    sp = sub.add_parser("sample", help="합성 샘플 데이터 생성")
    sp.add_argument("--out", default="data/sample")
    sp.set_defaults(func=cmd_sample)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("중단")
        return 130


if __name__ == "__main__":
    sys.exit(main())
