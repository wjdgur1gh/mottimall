# pullback-trader — 국내주식 눌림목 1:2:3:4 분할매수 트레이딩 도구

데이트레이딩(분봉)과 스윙매매(일봉)에서 **눌림목 구간**을 찾아 **1:2:3:4 비율의 분할매수 사다리**, 손절가, 1·2차 목표가, 리스크 기반 수량을 계산하고,
주문표 출력 / 모의매매 / 한국투자증권 자동주문 / 백테스트까지 한 패키지로 제공합니다.

> **먼저 읽어야 할 전제**
> 1. **미래에셋증권은 개인용 Open API 를 제공하지 않습니다.** 그래서 이 프로그램은 미래에셋 계좌에 직접 주문을 넣지 못하고, 계산 결과를 **주문표**로 내어 카이로스(KAIROS) HTS 에서 입력하는 방식이 기본입니다. 완전 자동화를 원하면 한국투자증권 계좌(KIS Developers)를 추가로 쓰는 어댑터를 포함했습니다. → [docs/KAIROS_WORKFLOW.md](docs/KAIROS_WORKFLOW.md), [docs/KIS_SETUP.md](docs/KIS_SETUP.md)
> 2. 요구하신 조건 외에 **추가로 확인해야 할 사항**(2026년 세금, 호가단위, VI, 거래시간/NXT, 종목 제외 기준, 1:2:3:4 분할의 리스크 구조, 시가총액 100억 기준의 문제 등)을 [docs/CONSIDERATIONS.md](docs/CONSIDERATIONS.md) 에 정리했습니다. **실매매 전 반드시 읽어 주세요.**
> 3. 이 소프트웨어는 투자 조언이 아니며, 모든 매매 결과의 책임은 사용자에게 있습니다. 반드시 모의매매/백테스트로 검증 후 소액부터 시작하세요.

---

## 1. 기능

| 영역 | 내용 |
|---|---|
| 유니버스 | 코스피·코스닥, **시가총액 ≥ 100억**, 20일 평균 거래대금, 주가 하한, 신규상장 제외, 스팩/우선주/ETF/ETN/리츠 제외, 관리종목·투자경고·거래정지 제외, 수동 제외 목록 |
| 눌림목 감지 | 추세(MA20>MA60) → 상승 임펄스(≥10%) → 조정(깊이·피보나치 되돌림 23.6~61.8%·봉수) → 거래량 수축 → 이평/VWAP 지지 → 반등 확인봉 트리거 |
| 분할매수 | 1:2:3:4 사다리 (1차가~눌림 저점 균등 배치 / % / ATR / 지지선 모드), 손절은 눌림 저점 아래 |
| 수량 산정 | "4차까지 전량 체결 후 손절" 최악 손실 = 계좌의 N% (기본 1%), 종목당 최대 투자금 상한 |
| 청산 | 손절, 1차 목표(부분청산 + 손절 평단 상향), 2차 목표(R배수), 시간 청산, 데이트레이딩 15:15 강제청산 |
| 실행 | 주문표(MD/CSV) · 모의 브로커 · 한국투자증권 REST 브로커 · 텔레그램 알림 |
| 백테스트 | 일봉 스윙 / 분봉 데이 엔진, 보수적 체결 가정, 2026년 세금·수수료·슬리피지 반영, 체결차수별 성과 |
| 시장 규칙 | 호가단위(2023 개편), 상하한가 ±30%, 동적·정적 VI, KRX/NXT 거래시간, 2026 휴장일 |

## 2. 설치

```bash
git clone <this repo> && cd mottimall
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                    # pandas, numpy, requests, PyYAML
pip install -e ".[dev]"             # pytest
# 선택: 데이터 소스
pip install pykrx                   # KRX (일부 API 는 KRX_ID/KRX_PW 로그인 필요)
pip install finance-datareader      # FDR
```

Python 3.10 이상. Windows/Mac/Linux 모두 동작 (OCX 같은 Windows 전용 의존성 없음).

## 3. 5분 빠른 시작 (합성 샘플 데이터)

```bash
pullback sample                                   # data/sample/ 에 가상 종목 8개 생성 (실제 시세 아님)
pullback scan --mode swing --provider csv --csv-dir data/sample --date 2026-10-08 -v
pullback scan --mode day   --provider csv --csv-dir data/sample --at 2026-10-12T10:12
pullback backtest --mode swing --provider csv --csv-dir data/sample --start 2025-11-01 --end 2026-10-08
pullback backtest --mode day   --provider csv --csv-dir data/sample --start 2026-10-12 --end 2026-10-12
pullback plan --mode swing --provider csv --csv-dir data/sample --code 900001 --date 2026-10-08
pullback costs --price 12000 --qty 300 --market KOSDAQ
```

`scan` 은 `output/orders_YYYYMMDD_<mode>.md/.csv` 주문표를 만듭니다. 예:

```
| 차수 | 비중 | 매수가 | 수량 | 금액 |
| 1차 | 10% | 11,130 | 27 | 300,510 |
| 2차 | 20% | 11,010 | 55 | 605,550 |
| 3차 | 30% | 10,900 | 82 | 893,800 |
| 4차 | 40% | 10,800 | 111 | 1,198,800 |
- 손절가 10,630원 (전량 체결 시 최대손실 75,625원 = 계좌 0.76%)
- 1차 목표 11,380원 (50% 청산) / 2차 목표 11,940원
```

## 4. 실데이터로 쓰기

```bash
cp config/config.example.yaml config/config.yaml     # 계좌 자산, 수수료율, 리스크% 등 수정
pullback universe --provider naver                   # 유니버스 생성 (output/universe_YYYYMMDD.csv)
pullback scan --mode swing --provider naver          # 장 마감 후 스윙 스캔
pullback live --mode day --provider naver --broker sheet --poll 60   # 장중 데이트레이딩 알림 루프
```

| provider | 유니버스(시총) | 일봉 | 분봉 | 비고 |
|---|---|---|---|---|
| `naver` | ○ (비공식 모바일 API) | ○ | ○ (1분, 최근 며칠) | 로그인 불필요. 비공식이라 형식 변경 가능 |
| `pykrx` | ○ | ○ | × | KRX 정보데이터시스템. 최근 일부 API 에 `KRX_ID`/`KRX_PW` 필요 |
| `fdr` | ○ | ○ | × | FinanceDataReader |
| `csv` | 파일 | 파일 | 파일 | 카이로스 차트 → 엑셀 내보내기. 형식은 [KAIROS_WORKFLOW.md](docs/KAIROS_WORKFLOW.md) §4 |
| `kis` | 네이버 보조 | ○ | ○ (당일/과거) + 관리·경고·정지 플래그 | 한국투자증권 API 키 필요 |

외부 접근이 막힌 환경에서는 `csv` 로만 동작합니다. 일봉은 `data/cache/` 에 자동 캐시됩니다.

## 5. 전략 정의

### 5.1 눌림목 셋업 (`strategy/pullback.py`)
마지막 봉 시점에서 아래 6단계를 모두 통과해야 셋업입니다. 각 단계의 수치는 `config` 의 `swing:` / `day:` 섹션입니다.

1. **추세** — 스윙: 종가 > MA20, MA20 > MA60. 데이: 종가 > VWAP, 갭상승 ≤ 15%
2. **임펄스** — 최근 30봉(데이: 60봉) 안의 최고가 H 와 그 앞 25봉 안의 최저가 L. (H−L)/L ≥ 10% (데이: 3%)
3. **눌림** — H 이후 2~12봉(데이: 2~20봉), 눌림 저점 PL 의 깊이 3~20%(데이: 1~7%), 되돌림 (H−PL)/(H−L) 이 0.236~0.618
4. **거래량 수축** — 눌림 구간 평균 거래량 / 임펄스 구간 평균 거래량 ≤ 0.85 (데이: 0.8)
5. **지지** — PL 이 MA5/10/20(데이: MA5/20, VWAP) 위 또는 허용오차 안, 종가가 MA20 위 유지
6. **트리거** — `confirm`: 마지막 봉이 양봉 + 직전봉 고가 돌파 + 거래량 ≥ 직전봉 × 1.2, 그리고 아직 눌림의 60% 이상 회복하지 않음(추격 방지). `anticipate`: 트리거 없이 지지선 예약매수

### 5.2 1:2:3:4 사다리 (`strategy/sizing.py`)
- 1차가 = 확인봉 종가(데이: 다음 봉 시가 시장가), 4차가 = 눌림 저점 + 1틱, 2·3차는 그 사이 균등 (`range` 모드)
- 손절가 = min(눌림 저점 × (1−1%), 4차가 × (1−1.5%)) → 호가단위 내림
- 평단(전량 체결) = Σ(가격×비중). **총수량 = 계좌 × 리스크% ÷ (평단 − 손절가)**, 종목당 최대 투자금으로 상한
- 수량 배분 = 총수량 × {0.1, 0.2, 0.3, 0.4}
- 목표: 직전 고점과 "평단 + 2R" 중 가까운 쪽이 1차(50% 청산 후 손절을 평단으로), 먼 쪽이 2차
- 무효화 규칙: 손절 이탈 시 전량 매도 + 사다리 취소 / 1차 목표 도달 시 미체결 사다리 취소 / 유효기간(3거래일, 데이 60분) 경과 시 취소

### 5.3 데이트레이딩 시간 규칙
09:10 이전·14:30 이후 신규 진입 없음, **15:15 전량 강제청산**(장마감 동시호가 회피), 일 손실 한도 −3%·연속 3패 시 당일 중단.

## 6. 명령어

```
pullback universe   [--date D] [--no-turnover]                     유니버스 생성
pullback scan       [--mode swing|day] [--date D] [--at T] [--codes ...] [-v]
pullback plan       --code 005930 [--mode ...] [--date D | --at T]
pullback backtest   [--mode ...] --start D --end D [--codes ...]
pullback live       [--mode ...] [--broker sheet|paper|kis] [--poll 60]
pullback costs      --price 10000 --qty 100 --market KOSDAQ
pullback config                                                     적용 설정 출력
pullback sample                                                     합성 샘플 데이터
공통: --config, --provider, --csv-dir, --equity
```

## 7. 프로젝트 구조

```
pullback_trader/
  config.py            설정 dataclass + YAML 로더
  market/              tick(호가단위·상하한가) costs(2026 세금) calendar(거래시간·휴장) vi(변동성완화장치)
  data/                base(표준 스키마) csv naver pykrx fdr kis_client kis_provider cache
  screener/universe.py 유니버스 필터
  strategy/            indicators pullback(셋업 감지) sizing(1:2:3:4 사다리·수량)
  execution/           base paper(모의) order_sheet(주문표) kis_broker
  backtest/            engine(PositionSim·Swing·Day) report
  live/                runner(Scanner·LiveRunner) alerts
  cli.py
config/config.example.yaml   docs/   scripts/make_sample_data.py   tests/
```

## 8. 테스트

```bash
pytest -q          # 호가단위/세금/달력/VI, 감지기, 사다리 수량, 체결 시뮬레이터, 백테스트, 필터, 주문표, 설정
```

## 9. 한계

- 백테스트는 봉 데이터 기반 보수적 가정(같은 봉에서 손절·목표 동시 접촉 시 손절 우선, 사다리 체결 후 손절)이며 호가 잔량·체결 순서는 모릅니다. 실제보다 체결이 잘 되는 쪽으로 편향될 수 있습니다.
- 네이버 공급자는 비공식 API 입니다. 응답 형식이 바뀌면 `data/naver.py` 수정이 필요합니다.
- 관리종목·투자경고 플래그는 KIS 공급자만 자동 제공합니다. 다른 공급자는 `config/exclusions.csv` 로 수동 관리하세요.
- KIS 브로커의 손절은 서버 스탑이 아니라 프로그램 폴링입니다. 프로그램이 꺼지면 손절도 멈춥니다.
