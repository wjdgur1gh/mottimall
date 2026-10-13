"""설정 스키마와 로더.

모든 전략 파라미터는 dataclass 기본값을 가지며, YAML 파일로 일부만 덮어쓸 수 있다.
금액 단위는 원(KRW), 비율 단위는 % 또는 소수(필드명에 _pct 가 붙으면 %)이다.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# --------------------------------------------------------------------------------------
# 유니버스(종목 선별)
# --------------------------------------------------------------------------------------
@dataclass
class UniverseConfig:
    markets: List[str] = field(default_factory=lambda: ["KOSPI", "KOSDAQ"])
    # 시가총액 하한. 100억은 상장사 거의 전부가 통과해 의미가 없으므로 1,000억을 권장 기본값으로 둔다
    # (관리종목·거래정지·투자경고 지정이 집중되는 소형주 구간 회피, 기관·외국인 수급 존재, 호가 두께 확보).
    # 더 많은 소형주를 원하면 500억까지만 낮출 것. 0이면 미적용.
    min_market_cap: int = 100_000_000_000
    # 20일 평균 거래대금 하한 (실질 유동성 필터). 스윙 50억: 300만 원 사다리 4건 + 시장가 청산이 호가 1~2틱 안에서 처리됨.
    # 계좌가 5,000만 원 이상이면 100억 이상으로 올릴 것 (포지션이 일 거래대금의 0.5% 를 넘지 않게). 0이면 미적용
    min_avg_turnover: int = 5_000_000_000
    avg_turnover_days: int = 20
    # 데이트레이딩 전용 상향 기준 (0이면 위 값과 동일). 분 단위 체결·15:15 시장가 청산에는 더 두꺼운 호가가 필요하다
    day_min_market_cap: int = 0
    day_min_avg_turnover: int = 10_000_000_000
    # 데이트레이딩: 신호 시점까지 당일 누적 거래대금 하한 (오늘 거래가 죽은 종목 제외). 0이면 미적용
    day_min_intraday_turnover: int = 2_000_000_000
    # 저가주 제외 (호가단위 1원 구간은 스프레드 비용이 큼)
    min_price: int = 1_000
    max_price: int = 0  # 0 = 제한 없음
    # 신규상장 종목 제외 (상장 후 N 거래일 미만)
    min_listing_days: int = 60
    # 종목명 패턴으로 제외: 스팩, 우선주, ETF/ETN, 리츠 등
    exclude_name_regex: List[str] = field(default_factory=lambda: [
        r"스팩", r"SPAC", r"우(B|C)?$", r"[0-9]우(B|C)?$",
        r"ETF", r"ETN", r"KODEX", r"TIGER", r"KBSTAR", r"ARIRANG", r"HANARO",
        r"SOL ", r"ACE ", r"RISE ", r"PLUS ", r"리츠", r"인프라", r"펀드",
    ])
    # 상태 플래그 제외 (데이터 소스가 제공할 때만 적용)
    exclude_flags: List[str] = field(default_factory=lambda: [
        "관리종목", "투자경고", "투자위험", "거래정지", "정리매매", "불성실공시", "단일가매매",
    ])
    # 수동 제외 목록 파일(코드 1열). 카이로스에서 관리/경고 종목을 내보내 넣을 수 있다.
    exclusion_file: str = "config/exclusions.csv"
    # 스캔 대상 상한(거래대금 상위 N). 0 이면 전체
    max_candidates: int = 300


# --------------------------------------------------------------------------------------
# 눌림목(스윙, 일봉) 파라미터
# --------------------------------------------------------------------------------------
@dataclass
class SwingPullbackConfig:
    # 추세 필터
    trend_ma_fast: int = 20
    trend_ma_slow: int = 60
    require_close_above_fast_ma: bool = True
    require_fast_above_slow: bool = True
    # 상승 임펄스(직전 상승파동)
    impulse_lookback: int = 30      # 최근 N봉 안에 고점이 있어야 함
    impulse_max_bars: int = 25      # 저점 -> 고점 까지 최대 봉 수
    impulse_min_gain_pct: float = 10.0
    # 눌림(조정)
    pullback_min_bars: int = 2
    pullback_max_bars: int = 12
    pullback_min_depth_pct: float = 3.0
    pullback_max_depth_pct: float = 20.0
    retrace_min: float = 0.236      # 피보나치 되돌림 범위
    retrace_max: float = 0.618
    volume_ratio_max: float = 0.85  # 조정 구간 평균 거래량 / 임펄스 구간 평균 거래량
    # 지지
    support_mas: List[int] = field(default_factory=lambda: [5, 10, 20])
    support_tolerance_pct: float = 2.0  # 눌림 저점이 지지 이평선 ±N% 안에 있어야 함
    must_hold_ma: int = 20              # 종가가 이 이평선 아래로 마감하면 무효 (0=미적용)
    # 진입 트리거
    entry_mode: str = "confirm"         # confirm: 반등 확인봉 필요 / anticipate: 지지선 예약매수
    trigger_close_above_prev_high: bool = True
    trigger_volume_ratio: float = 1.2   # 트리거봉 거래량 >= 직전봉 거래량 * ratio
    trigger_lookback_bars: int = 0      # 직전 N봉 안의 확인봉도 인정 (이후 봉이 확인봉 시가 위를 유지할 때)
    # 청산
    stop_buffer_pct: float = 1.0        # 눌림 저점 아래 N%
    stop_below_last_pct: float = 1.5    # 손절가는 4차 매수가보다 최소 N% 아래
    first_tranche_market: bool = False  # True: 1차는 다음 봉 시가 시장가, False: 확인봉 종가 지정가
    target_r_multiple: float = 2.0      # 2차 목표 = 평단 + R * (평단-손절)
    partial_exit_at_impulse_high: float = 0.5  # 1차 목표(직전 고점)에서 청산 비중
    move_stop_to_breakeven_after_t1: bool = True
    max_hold_days: int = 10
    ladder_valid_days: int = 3          # 미체결 분할매수 주문 유효 일수


# --------------------------------------------------------------------------------------
# 눌림목(데이트레이딩, 분봉) 파라미터
# --------------------------------------------------------------------------------------
@dataclass
class DayPullbackConfig:
    bar_minutes: int = 3
    # 장 시작 후 임펄스: 당일 저점 -> 당일 고점 상승률
    impulse_min_gain_pct: float = 3.0
    impulse_max_bars: int = 40
    gap_up_max_pct: float = 15.0        # 갭 과대 종목 제외
    # 눌림
    pullback_min_bars: int = 2
    pullback_max_bars: int = 20
    pullback_min_depth_pct: float = 1.0
    pullback_max_depth_pct: float = 7.0
    retrace_min: float = 0.236
    retrace_max: float = 0.618
    volume_ratio_max: float = 0.8
    # 지지: VWAP 또는 분봉 이평
    support_mas: List[int] = field(default_factory=lambda: [5, 20])
    support_tolerance_pct: float = 1.0
    require_above_vwap: bool = True
    # 트리거
    entry_mode: str = "confirm"
    trigger_close_above_prev_high: bool = True
    trigger_volume_ratio: float = 1.2
    trigger_lookback_bars: int = 1      # 폴링 간격 때문에 확인봉을 놓치지 않도록 1봉 유예
    # 시간 규칙 (HH:MM)
    first_entry_time: str = "09:10"     # 시초가 변동 구간 회피
    last_entry_time: str = "14:30"
    force_exit_time: str = "15:15"      # 장마감 동시호가(15:20) 전 청산
    # 청산
    stop_buffer_pct: float = 0.5
    stop_below_last_pct: float = 0.5
    first_tranche_market: bool = True   # 확인봉 직후 1차는 시장가(다음 봉 시가)
    target_r_multiple: float = 1.5
    partial_exit_at_impulse_high: float = 0.5
    move_stop_to_breakeven_after_t1: bool = True
    ladder_valid_minutes: int = 60


# --------------------------------------------------------------------------------------
# 분할매수 사다리(1:2:3:4)
# --------------------------------------------------------------------------------------
@dataclass
class LadderConfig:
    # 분할 비중 (1차→4차). 기본 4:3:2:1 정피라미드: 확인봉 근처(승률 높은 얕은 눌림)에서 가장 많이 사고,
    # 깊이 밀릴수록(확인이 틀려가는 구간) 적게 산다. 1:2:3:4 역피라미드는 이기는 거래에서는 10~30% 수량만 들고
    # 지는 거래에서는 항상 100% 수량을 들게 되는 음의 비대칭 구조라 권장하지 않는다 (설정은 가능, 경고 표시).
    weights: List[float] = field(default_factory=lambda: [4, 3, 2, 1])
    step_mode: str = "range"            # range(1차가~눌림저점 균등) | pct | atr | support
    step_pct: List[float] = field(default_factory=lambda: [0.0, 1.5, 3.0, 4.5])
    step_atr: List[float] = field(default_factory=lambda: [0.0, 0.5, 1.0, 1.5])
    min_qty_per_tranche: int = 1


# --------------------------------------------------------------------------------------
# 리스크/자금관리
# --------------------------------------------------------------------------------------
@dataclass
class RiskConfig:
    account_equity: int = 10_000_000
    risk_per_trade_pct: float = 1.0     # 전 사다리 체결 후 손절 시 최대 손실 (계좌 대비 %)
    max_position_pct: float = 30.0      # 종목당 최대 투자금 (계좌 대비 %)
    max_open_positions: int = 3
    daily_loss_limit_pct: float = 3.0   # 당일 누적 손실 한도 도달 시 신규 진입 중단
    max_consecutive_losses: int = 3
    margin_rate_pct: float = 100.0      # 증거금률 100% 권장 (미수 방지)


# --------------------------------------------------------------------------------------
# 거래비용 (2026년 기준)
# --------------------------------------------------------------------------------------
@dataclass
class CostConfig:
    # 편도 위탁수수료(%). 미래에셋 다이렉트 계좌 우대요율은 유관기관 제비용 수준(≈0.0036%)이나
    # 보수적으로 0.015%를 기본값으로 둔다. 본인 계좌 요율로 수정할 것.
    commission_pct: float = 0.015
    # 매도 시 세금(%): 2026.1.1~ 코스피 거래세 0.05% + 농특세 0.15% = 0.20%, 코스닥 0.20%
    sell_tax_pct_kospi: float = 0.20
    sell_tax_pct_kosdaq: float = 0.20
    slippage_ticks: int = 1            # 백테스트 체결가 보정(호가단위 틱)


# --------------------------------------------------------------------------------------
# 데이터/브로커/알림
# --------------------------------------------------------------------------------------
@dataclass
class DataConfig:
    provider: str = "csv"              # csv | naver | pykrx | fdr | kis
    csv_dir: str = "data/csv"
    cache_dir: str = "data/cache"
    lookback_days: int = 300
    request_interval_sec: float = 0.3  # 외부 API 호출 간격(차단 방지)


@dataclass
class KisConfig:
    app_key: str = ""
    app_secret: str = ""
    account_no: str = ""      # 종합계좌번호 8자리
    product_code: str = "01"  # 계좌상품코드
    paper: bool = True        # 모의투자 여부
    token_cache: str = "state/kis_token.json"


@dataclass
class BrokerConfig:
    mode: str = "sheet"       # sheet(주문표 출력) | paper(모의) | kis(한국투자증권 자동주문)
    kis: KisConfig = field(default_factory=KisConfig)


@dataclass
class AlertConfig:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    console: bool = True


@dataclass
class AppConfig:
    mode: str = "swing"       # swing | day
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    swing: SwingPullbackConfig = field(default_factory=SwingPullbackConfig)
    day: DayPullbackConfig = field(default_factory=DayPullbackConfig)
    ladder: LadderConfig = field(default_factory=LadderConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    data: DataConfig = field(default_factory=DataConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    output_dir: str = "output"
    state_dir: str = "state"
    # KRX 휴장일(YYYY-MM-DD). 2026년 예정일 — 매년 KRX 공지로 갱신할 것.
    holidays: List[str] = field(default_factory=lambda: [
        "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
        "2026-05-01", "2026-05-05", "2026-05-25", "2026-06-03", "2026-08-17",
        "2026-09-24", "2026-09-25", "2026-09-28", "2026-10-05", "2026-10-09",
        "2026-12-25", "2026-12-31",
    ])

    def pullback(self):
        return self.swing if self.mode == "swing" else self.day


# --------------------------------------------------------------------------------------
# 로더
# --------------------------------------------------------------------------------------
def _merge(dc_obj: Any, data: Dict[str, Any]) -> Any:
    """dict 값을 dataclass 인스턴스에 재귀적으로 덮어쓴다. 알 수 없는 키는 오류."""
    if not isinstance(data, dict):
        raise TypeError(f"{type(dc_obj).__name__} 섹션은 매핑이어야 합니다: {data!r}")
    names = {f.name: f for f in fields(dc_obj)}
    for key, value in data.items():
        if key not in names:
            raise KeyError(f"알 수 없는 설정 키: {type(dc_obj).__name__}.{key}")
        current = getattr(dc_obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(dc_obj, key, value)
    return dc_obj


def _apply_env(cfg: AppConfig) -> AppConfig:
    """민감정보는 환경변수로도 받을 수 있다."""
    env = os.environ
    cfg.broker.kis.app_key = env.get("KIS_APP_KEY", cfg.broker.kis.app_key)
    cfg.broker.kis.app_secret = env.get("KIS_APP_SECRET", cfg.broker.kis.app_secret)
    cfg.broker.kis.account_no = env.get("KIS_ACCOUNT_NO", cfg.broker.kis.account_no)
    cfg.broker.kis.product_code = env.get("KIS_PRODUCT_CODE", cfg.broker.kis.product_code)
    if env.get("KIS_PAPER") is not None:
        cfg.broker.kis.paper = env["KIS_PAPER"].strip().lower() in ("1", "true", "y", "yes")
    cfg.alert.telegram_bot_token = env.get("TELEGRAM_BOT_TOKEN", cfg.alert.telegram_bot_token)
    cfg.alert.telegram_chat_id = env.get("TELEGRAM_CHAT_ID", cfg.alert.telegram_chat_id)
    return cfg


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg = AppConfig()
    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"설정 파일이 없습니다: {p}")
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        _merge(cfg, raw)
    else:
        # 기본 경로가 있으면 자동 로드
        for candidate in ("config/config.yaml", "config.yaml"):
            if Path(candidate).exists():
                with open(candidate, "r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                _merge(cfg, raw)
                break
    cfg = _apply_env(cfg)
    validate(cfg)
    return cfg


def validate(cfg: AppConfig) -> None:
    if cfg.mode not in ("swing", "day"):
        raise ValueError("mode 는 swing 또는 day 여야 합니다")
    if len(cfg.ladder.weights) != 4 or any(w <= 0 for w in cfg.ladder.weights):
        raise ValueError("ladder.weights 는 양수 4개여야 합니다 (예: [1,2,3,4])")
    if len(cfg.ladder.step_pct) != 4 or len(cfg.ladder.step_atr) != 4:
        raise ValueError("ladder.step_pct / step_atr 는 4개 값이어야 합니다")
    if cfg.ladder.step_mode not in ("range", "pct", "atr", "support"):
        raise ValueError("ladder.step_mode 는 range|pct|atr|support")
    if not (0 < cfg.risk.risk_per_trade_pct <= 10):
        raise ValueError("risk.risk_per_trade_pct 는 0~10% 범위를 권장합니다")
    if cfg.broker.mode not in ("sheet", "paper", "kis"):
        raise ValueError("broker.mode 는 sheet|paper|kis")
    if cfg.data.provider not in ("csv", "naver", "pykrx", "fdr", "kis"):
        raise ValueError("data.provider 는 csv|naver|pykrx|fdr|kis")
    for pb in (cfg.swing, cfg.day):
        if pb.entry_mode not in ("confirm", "anticipate"):
            raise ValueError("entry_mode 는 confirm|anticipate")
        if not (0 < pb.retrace_min < pb.retrace_max <= 1.0):
            raise ValueError("retrace_min < retrace_max <= 1.0 이어야 합니다")


def to_dict(cfg: AppConfig) -> Dict[str, Any]:
    return dataclasses.asdict(cfg)
