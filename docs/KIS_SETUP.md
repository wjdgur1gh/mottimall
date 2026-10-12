# 한국투자증권(KIS) 자동주문 설정

완전 자동매매(사다리 자동 발주, 손절·목표 자동 집행)가 필요하면 한국투자증권 계좌와 KIS Developers API 키가 필요합니다.
미래에셋 계좌는 그대로 두고, 자동매매용 소액 계좌를 따로 두는 구성을 권장합니다.

## 1. 신청
1. 한국투자증권 계좌 개설 (비대면 가능) → HTS/MTS 로그인
2. https://apiportal.koreainvestment.com 접속 → *KIS Developers 서비스 신청* → 실전/모의 각각 **App Key / App Secret** 발급
3. 모의투자 신청(모의계좌 발급) — 먼저 모의로 최소 2주 이상 검증

## 2. 환경변수 (권장) 또는 config
```bash
export KIS_APP_KEY=...
export KIS_APP_SECRET=...
export KIS_ACCOUNT_NO=12345678     # 종합계좌번호 8자리 (또는 10자리 전체)
export KIS_PRODUCT_CODE=01
export KIS_PAPER=1                  # 모의투자. 실전은 0
```
```yaml
broker:
  mode: kis
data:
  provider: kis        # 시세도 KIS 로 (유니버스 목록은 네이버에서 보조)
```

## 3. 실행
```bash
pullback live --mode day --broker kis --provider kis --poll 60   # 장중 루프
pullback live --mode swing --broker kis --provider kis          # 장 마감 후 1회: 다음날 사다리 발주
```

## 4. 주의
- KIS 현금주문 API 에는 **서버 스탑(조건부) 주문이 없습니다.** 프로그램이 현재가를 폴링해 손절가 이하이면 시장가 매도를 냅니다 (`KisBroker.check_stops`). 프로그램이 꺼지면 손절도 멈추므로, 장중에는 반드시 실행 상태를 확인하거나 HTS 에 별도 스탑을 걸어 두세요.
- 호출 제한: 실전 20건/초, 모의 2건/초. 유니버스가 크면 분봉 폴링에 시간이 걸리므로 `universe.max_candidates` 를 50~100 으로 줄이세요.
- 토큰은 `state/kis_token.json` 에 캐시됩니다 (하루 1회 발급 권장). 키는 절대 저장소에 커밋하지 마세요.
- `tr_id` 는 2025~2026 문서 기준입니다 (`pullback_trader/data/kis_client.py` 의 `TR` 사전). 포털 문서가 바뀌면 그 사전만 수정하면 됩니다.
- 모의투자는 체결 규칙이 실전과 다릅니다(미체결 많음). 실전 전환 시 소액으로 시작하세요.
