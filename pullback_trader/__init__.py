"""pullback_trader — 국내주식 눌림목(Pullback) 분할매수 트레이딩 도구.

구성
- market    : 호가단위, 상하한가, 거래비용(수수료/세금), 거래시간, VI 계산
- data      : 시세 데이터 공급자 (CSV / 네이버 / pykrx / FinanceDataReader / 한국투자증권)
- screener  : 유니버스(시가총액·거래대금·제외종목) 필터
- strategy  : 눌림목 감지, 1:2:3:4 분할매수 사다리(ladder) 및 리스크 기반 수량 산정
- execution : 주문표(HTS 수동 주문용), 모의 브로커, 한국투자증권 REST 브로커
- backtest  : 일봉(스윙)/분봉(데이트레이딩) 백테스트 엔진과 리포트
- live      : 장중 실시간 스캔 루프, 알림
"""

__version__ = "0.1.0"
