"""미래에셋증권 카이로스(KAIROS) HTS 화면 세팅값 시트 생성.

설정(config) 의 수치를 그대로 HTS 각 화면에 입력할 수 있는 형태로 풀어 쓴다.
- 계좌/주문 환경, 차트 지표, [0544] 종합종목검색 조건식, [0545] 실시간종목검색(데이), [0635] 서버 자동주문,
  관심종목 그룹, 신호 모니터링, 주문표 CSV ↔ 주문창 매핑
화면번호와 항목명은 카이로스 버전에 따라 다를 수 있다. 같은 의미의 항목을 찾아 입력한다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List

from ..config import AppConfig


def _억(v: float) -> str:
    return f"{v / 1e8:,.0f}억"


def _pct(v: float) -> str:
    return f"{v:g}%"


def _weights(ws: List[float]) -> str:
    return ":".join(str(int(w)) if float(w).is_integer() else str(w) for w in ws)


def render_hts_settings(cfg: AppConfig) -> str:
    u, sw, dy, lc, rk, ct = cfg.universe, cfg.swing, cfg.day, cfg.ladder, cfg.risk, cfg.cost
    day_cap = u.day_min_market_cap or u.min_market_cap
    day_turn = u.day_min_avg_turnover or u.min_avg_turnover
    wsum = sum(lc.weights)
    wpct = [f"{w / wsum:.0%}" for w in lc.weights]
    L: List[str] = []
    a = L.append

    a(f"# 카이로스(KAIROS) HTS 화면 세팅값")
    a("")
    a(f"생성 {dt.datetime.now():%Y-%m-%d %H:%M} · 설정 모드 `{cfg.mode}` · 계좌 자산 {rk.account_equity:,}원")
    a("")
    a("> 화면번호·항목명은 카이로스 버전마다 다를 수 있습니다. 상단 화면검색창에 화면명을 입력해 찾고, 조건식 항목은 같은 뜻의 항목(범위지정/시세분석/기술적분석/거래량/패턴)을 고르세요.")
    a("> 이 시트는 `pullback hts` 명령으로 설정값에서 자동 생성됩니다. 설정을 바꾸면 다시 생성하세요.")
    a("")

    # ------------------------------------------------------------ 1. 계좌/주문 환경
    a("## 1. 계좌·주문 환경 (한 번만 설정)")
    a("")
    a("| 화면 | 항목 | 값 | 이유 |")
    a("|---|---|---|---|")
    a(f"| 계좌 설정 (고객센터/MTS 가능) | 증거금률 | **{rk.margin_rate_pct:g}%** | 미수 발생·반대매매 차단. 투자경고 종목은 어차피 100% |")
    a("| 주문 설정 | 주문 확인창 | **사용** | 수량·가격 오입력 방지 |")
    a("| 주문 설정 | 키보드 즉시주문 / 더블클릭 주문 | **사용 안 함** | 데이트레이딩 중 실수 주문 방지 |")
    a("| 주문 설정 | 매도 수량 기본값 | **보유수량 전량** | 손절 시 잔량 남기지 않기 |")
    a("| 주문 설정 | 시장가 주문 | 허용 (데이 1차·강제청산·손절에만 사용) | 그 외는 지정가 |")
    a("| 주문 설정 | 거래소 선택 | **KRX 정규장** (NXT 자동 라우팅은 스윙 손절 기준이 흔들리므로 선택 시 주의) | 종가·VI 기준 통일 |")
    a("| 환경 설정 | 매매 알림(체결/미체결) 팝업·소리 | **사용** | 사다리 체결 즉시 손절 등록 |")
    a("")

    # ------------------------------------------------------------ 2. 차트
    a("## 2. 차트 설정")
    a("")
    a("### 2.1 일봉 (스윙)")
    a("")
    a("| 지표 | 설정값 | 용도 |")
    a("|---|---|---|")
    mas = sorted(set(sw.support_mas + [sw.trend_ma_fast, sw.trend_ma_slow]))
    a(f"| 이동평균(종가, 단순) | **{' / '.join(str(m) for m in mas)}** (+120 참고선) | 추세: 종가 > MA{sw.trend_ma_fast} > MA{sw.trend_ma_slow} / 지지: MA{', MA'.join(str(m) for m in sw.support_mas)} |")
    a("| 거래량 + 거래량 이동평균 | **20** | 눌림 구간 거래량이 20일 평균·임펄스 구간보다 줄었는지 |")
    a("| ATR | **14** | 사다리 간격(atr 모드)·변동성 확인 |")
    a("| 피보나치 되돌림 (수동 도구) | 임펄스 저점→고점에 긋기, **23.6 / 38.2 / 50 / 61.8** 표시 | 눌림 저점이 23.6~61.8 안에 있는지 |")
    a(f"| 가격 표시선 | 직전 임펄스 고점(1차 목표 후보), 눌림 저점 −{sw.stop_buffer_pct:g}% (손절) | 주문표 값과 대조 |")
    a("")
    a(f"### 2.2 {dy.bar_minutes}분봉 (데이트레이딩)")
    a("")
    a("| 지표 | 설정값 | 용도 |")
    a("|---|---|---|")
    a(f"| 이동평균(종가, 단순) | **{' / '.join(str(m) for m in dy.support_mas)}** | 지지 |")
    a("| VWAP (매매가중평균가) | **당일 누적** — 지표 목록에 없으면 수식지표 `누적(거래대금)/누적(거래량)` 로 추가 | 종가가 VWAP 위일 때만 매수 |")
    a("| 거래량 + 거래량 이동평균 | **20** | 조정 중 거래량 수축 확인 |")
    a(f"| 전일 종가선 / 당일 시가선 / 당일 고가·저가선 | 표시 | 갭(≤{_pct(dy.gap_up_max_pct)})·임펄스(저점→고점 ≥{_pct(dy.impulse_min_gain_pct)}) 판단 |")
    a(f"| 시간 구분선 | **{dy.first_entry_time} / {dy.last_entry_time} / {dy.force_exit_time}** | 진입 시작 / 신규진입 마감 / 강제청산 |")
    a("| VI 표시 | 정적 VI(기준가 ±10%)·동적 VI 발동 표시 켜기 | 발동 직후 추격 금지 |")
    a("")

    # ------------------------------------------------------------ 3. 0544
    a("## 3. [0544] 종합종목검색 — 스윙 눌림목 후보 (장 마감 후 검색)")
    a("")
    a("조건식 이름: `눌림목_스윙`. A~L 을 **AND** 로 결합. 괄호 안은 프로그램 설정 키.")
    a("")
    a("| 조건 | 분류(예상) | 항목 | 설정값 |")
    a("|---|---|---|---|")
    a(f"| A | 범위지정 | 시가총액 | **{_억(u.min_market_cap)} 이상** (`universe.min_market_cap`) |")
    a(f"| B | 범위지정 | {u.avg_turnover_days}일 평균 거래대금 | **{_억(u.min_avg_turnover)} 이상** (`universe.min_avg_turnover`) |")
    a(f"| C | 범위지정 | 현재가(종가) | **{u.min_price:,}원 이상** (`universe.min_price`) |")
    a(f"| D | 범위지정 | 상장일 | **상장 {u.min_listing_days}거래일 이상 경과** |")
    a("| E | 범위지정 / 종목구분 | 제외 | **관리종목·투자주의/경고/위험·거래정지·정리매매 제외**, 스팩·우선주·ETF/ETN·리츠 제외 (보통주만) |")
    a(f"| F | 기술적분석 | 이동평균 배열 | **종가 > MA{sw.trend_ma_fast} AND MA{sw.trend_ma_fast} > MA{sw.trend_ma_slow}** (단순, 종가) |")
    a(f"| G | 시세분석 | 신고가 대비 | **{sw.impulse_lookback}일 최고가 대비 −{sw.pullback_min_depth_pct:g}% ~ −{sw.pullback_max_depth_pct:g}%** (눌림 깊이) |")
    a(f"| H | 시세분석 | 신고가 경과일 | **{sw.impulse_lookback}일 최고가 발생 후 {sw.pullback_min_bars}~{sw.pullback_max_bars}일 경과** |")
    a(f"| I | 시세분석 | 기간 등락률 | **{sw.impulse_lookback + sw.pullback_max_bars}일 내 저점→고점 상승률 ≥ {sw.impulse_min_gain_pct:g}%** (항목이 없으면 '{sw.impulse_max_bars}일 전 대비 등락률 ≥ {sw.impulse_min_gain_pct:g}%' 로 대체) |")
    a(f"| J | 거래량 | 거래량 비율 | **최근 {max(2, sw.pullback_min_bars + 2)}일 평균 거래량 < 이전 {min(10, sw.impulse_max_bars)}일 평균 거래량 × {sw.volume_ratio_max:g}** |")
    a(f"| K | 기술적분석 | 이격도/지지 | **종가 ≥ MA{sw.must_hold_ma}** AND 최근 {sw.pullback_max_bars}일 최저가 ≥ MA{max(sw.support_mas)} × (1 − {sw.support_tolerance_pct:g}%) |")
    if sw.entry_mode == "confirm":
        a(f"| L | 패턴분석 / 시세분석 | 반등 확인봉 | **당일 양봉** AND **종가 > 전일 고가** AND **거래량 ≥ 전일 거래량 × {sw.trigger_volume_ratio:g}** |")
    else:
        a("| L | — | (anticipate 모드) | 확인봉 조건 없음. 지지선 예약매수 |")
    a("")
    a("- 검색 결과를 **관심종목 그룹 `스윙후보`** 로 저장 → `pullback scan --mode swing` 결과와 교차. 둘 다 잡힌 종목만 주문표대로 진행")
    a("- 조건식 저장 후 **서버 저장**을 켜면 M-STOCK(MTS) MY전략에서도 같은 결과를 볼 수 있음")
    a("")

    # ------------------------------------------------------------ 4. 0545
    a("## 4. [0545] 실시간종목검색 — 데이트레이딩 (장중)")
    a("")
    a(f"조건식 이름: `눌림목_데이`. 재검색 주기 **1분**, 감시 시간 **{dy.first_entry_time}~{dy.last_entry_time}**. 신호가 뜨면 `pullback plan --mode day --code 종목코드` 로 사다리 계산.")
    a("")
    a("| 조건 | 분류(예상) | 항목 | 설정값 |")
    a("|---|---|---|---|")
    a(f"| A | 범위지정 | 시가총액 | **{_억(day_cap)} 이상** |")
    a(f"| B | 범위지정 | {u.avg_turnover_days}일 평균 거래대금 | **{_억(day_turn)} 이상** (`universe.day_min_avg_turnover`) |")
    a(f"| C | 시세분석 | 당일 거래대금 | **{_억(u.day_min_intraday_turnover)} 이상** (`universe.day_min_intraday_turnover`) |")
    a(f"| D | 범위지정 | 현재가 | **{u.min_price:,}원 이상**, 관리·경고·정지 제외, 보통주만 |")
    a(f"| E | 시세분석 | 시가 갭 | **시가 ≤ 전일 종가 × (1 + {dy.gap_up_max_pct:g}%)** |")
    a(f"| F | 시세분석 | 당일 저가 대비 고가 | **(당일 고가 − 당일 저가) / 당일 저가 ≥ {dy.impulse_min_gain_pct:g}%** (임펄스) |")
    a(f"| G | 시세분석 | 당일 고가 대비 현재가 | **−{dy.pullback_min_depth_pct:g}% ~ −{dy.pullback_max_depth_pct:g}%** (눌림) |")
    a(f"| H | 기술적분석 | VWAP | **현재가 ≥ VWAP** (`require_above_vwap`) |")
    a(f"| I | 기술적분석 ({dy.bar_minutes}분봉) | 이동평균 | **현재가 ≥ {dy.bar_minutes}분봉 MA{max(dy.support_mas)} × (1 − {dy.support_tolerance_pct:g}%)** |")
    a(f"| J | 거래량 ({dy.bar_minutes}분봉) | 거래량 수축 | **최근 {dy.pullback_min_bars + 1}봉 평균 거래량 < 당일 평균 봉 거래량 × {dy.volume_ratio_max:g}** |")
    a(f"| K | 패턴 ({dy.bar_minutes}분봉) | 반등 확인봉 | **직전 완료봉 양봉 AND 종가 > 그 전 봉 고가 AND 거래량 ≥ 그 전 봉 × {dy.trigger_volume_ratio:g}** |")
    a(f"| L | 시세분석 | 상한가 근접 제외 | **현재가 ≤ 상한가 × 0.97** |")
    a("")
    a("- 필터설정 창: 등락률 **+1% ~ +25%**, 거래대금 상위 정렬. 조건 중 F·G·K 는 HTS 항목이 없을 수 있음 → 그 경우 A~E, H 만 HTS 에서 걸고 F~K 는 프로그램(`pullback live --mode day`)이 판정")
    a("")

    # ------------------------------------------------------------ 5. 0635
    a("## 5. [0635] 서버 자동주문 — 종목마다 체결 직후 등록")
    a("")
    a(f"주문표(`output/orders_*.md`) 의 손절가·목표가를 그대로 입력합니다. 분할 비중 **{_weights(lc.weights)}** = {' / '.join(wpct)}.")
    a("")
    a("| 템플릿 | 감시 조건 | 주문 | 수량 | 유효기간 | 비고 |")
    a("|---|---|---|---|---|---|")
    a("| 손절 | 현재가 **≤ 손절가** | 매도 **시장가** (또는 지정가 −2틱) | **보유수량 전량** | 스윙: 기간(보유 종료까지) / 데이: 당일 | 발동 즉시 미체결 매수 사다리 **수동 취소** |")
    a(f"| 1차 목표 | 현재가 **≥ 1차목표** | 매도 지정가(1차목표) 또는 시장가 | **보유수량의 {sw.partial_exit_at_impulse_high:.0%}** | 동일 | 체결 후 미체결 사다리 취소, 손절 감시가를 **평단**으로 수정 (`move_stop_to_breakeven_after_t1`) |")
    a("| 2차 목표 | 현재가 **≥ 2차목표** | 매도 지정가(2차목표) | **잔량 전량** | 동일 | |")
    a(f"| 시간 청산(데이) | 시각 **{dy.force_exit_time}** | 매도 시장가 | 보유수량 전량 | 당일 | 예약주문/시간조건 지원 시. 없으면 알람 맞춰 수동 |")
    a(f"| 시간 청산(스윙) | 보유 **{sw.max_hold_days}거래일** 경과 | 종가 매도 | 전량 | — | 수동 (캘린더 알림) |")
    a("")
    a("감시 시작/종료 시간: **09:00:30 ~ 15:19** (장마감 동시호가 전). 스탑 감시가는 호가단위에 맞춰 입력 (프로그램이 이미 맞춰 둠).")
    a("")

    # ------------------------------------------------------------ 6. 사다리 입력
    a("## 6. 매수 사다리 입력 (주문창)")
    a("")
    a("| 차수 | 비중 | 스윙 주문유형 | 스윙 유효 | 데이 주문유형 | 데이 유효 |")
    a("|---|---|---|---|---|---|")
    sw1 = "다음날 시가 시장가" if sw.first_tranche_market else "지정가(확인봉 종가, 다음날 아침 입력)"
    dy1 = "시장가(확인봉 직후)" if dy.first_tranche_market else "지정가(확인봉 종가)"
    for i, w in enumerate(wpct, start=1):
        if i == 1:
            a(f"| 1차 | {w} | {sw1} | {sw.ladder_valid_days}거래일 | {dy1} | 즉시 |")
        else:
            a(f"| {i}차 | {w} | 지정가 (주문표 {i}차가) | {sw.ladder_valid_days}거래일 (예약주문) | 지정가 (주문표 {i}차가) | {dy.ladder_valid_minutes}분 후 미체결 취소 |")
    a("")
    a("- 1차 체결 확인 → 즉시 [0635] 손절 등록 → 2~4차 지정가 입력 순서")
    a("- 1차 목표 체결 시 남은 사다리 **반드시 취소** (안 하면 되돌림에서 재매수되어 포지션이 커짐)")
    a("")

    # ------------------------------------------------------------ 7. 관심종목/모니터링
    a("## 7. 관심종목 그룹과 신호 모니터링")
    a("")
    a("| 그룹 | 내용 | 표시 열 |")
    a("|---|---|---|")
    a("| 스윙후보 | [0544] 결과 ∩ `pullback scan --mode swing` | 현재가, 등락률, 거래대금, 시가총액, 20일선 이격도, 전일 고가 |")
    a("| 데이후보 | 전일 거래대금 상위 + 시총 조건 (장전 준비) | 현재가, 등락률, 당일 거래대금, VWAP 대비, 당일 고가 대비 |")
    a("| 보유 | 포지션 | 평단, 손익률, 손절가(메모), 1·2차 목표(메모), 보유일 |")
    a("| 제외 | 관리·경고·정지 종목 (주 1회 갱신 → `config/exclusions.csv`) | — |")
    a("")
    a("신호 모니터링 화면: 스탑로스 신호, 조건검색 신호, 체결 통보 **모두 ON**, 소리 알림 ON. 종목메모에 손절·목표가를 적어 두면 주문창에서 바로 보임.")
    a("")

    # ------------------------------------------------------------ 8. 리스크 숫자
    a("## 8. 리스크 숫자 (계좌 기준)")
    a("")
    a("| 항목 | 값 |")
    a("|---|---|")
    a(f"| 종목당 최대 손실 (4차 전량 체결 후 손절) | 계좌 × {rk.risk_per_trade_pct:g}% = **{rk.account_equity * rk.risk_per_trade_pct / 100:,.0f}원** |")
    a(f"| 종목당 최대 투자금 | 계좌 × {rk.max_position_pct:g}% = **{rk.account_equity * rk.max_position_pct / 100:,.0f}원** |")
    a(f"| 동시 보유 종목 | **{rk.max_open_positions}** |")
    a(f"| 일 손실 한도 (도달 시 당일 중단) | 계좌 × {rk.daily_loss_limit_pct:g}% = **{rk.account_equity * rk.daily_loss_limit_pct / 100:,.0f}원** |")
    a(f"| 연속 손실 중단 | **{rk.max_consecutive_losses}회** |")
    a(f"| 왕복 비용 (수수료 {ct.commission_pct:g}%×2 + 세금 {ct.sell_tax_pct_kosdaq:g}%) | **{ct.commission_pct * 2 + ct.sell_tax_pct_kosdaq:.3f}%** + 1틱 |")
    a("")

    # ------------------------------------------------------------ 9. 매핑
    a("## 9. 주문표 CSV → 주문창 매핑")
    a("")
    a("| CSV 열 | 주문창 | 비고 |")
    a("|---|---|---|")
    a("| 종목코드 | 종목 | 6자리 |")
    a("| 구분 | 매수/매도 탭 | |")
    a("| 주문유형 | 지정가 / 시장가 / 스탑(조건부) | 스탑은 [0635] 서버 자동주문에 입력 |")
    a("| 가격 | 주문가격 또는 감시가격 | 호가단위 맞춤 완료 |")
    a("| 수량 | 주문수량 | 비중은 비고 열 |")
    a("| 유효기간 | 예약주문 기간 / 감시 종료일 | |")
    a("")
    return "\n".join(L)


def save_hts_settings(cfg: AppConfig, out_dir: str, stem: str = "hts_settings") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{stem}_{cfg.mode}.md"
    p.write_text(render_hts_settings(cfg), encoding="utf-8")
    return p
