# 천지명장전 템플릿 폴더

`game_bot/scenarios/cheonji.yaml` 이 참조하는 버튼 이미지(PNG)를 이 폴더에 넣습니다.
모두 **본인 휴대폰 화면에서** `gamebot pick -o game_bot/templates/cheonji` 로 잘라 저장하세요.

| 파일명 | 무엇을 잘라야 하나 | 팁 |
|---|---|---|
| `close.png` | 팝업/공지/광고 창의 **X(닫기)** 버튼 | X 아이콘만 꽉 차게. 배경 포함 금지 |
| `confirm.png` | **확인** 버튼 (보상 수령, 알림창) | 글자 "확인" 과 버튼 테두리까지 |
| `reconnect.png` | 접속 끊김 창의 **재접속/확인** 버튼 | 없으면 이 규칙 삭제해도 됨 |
| `defeat.png` | **패배** 결과 화면의 고유 문구/아이콘 | 봇을 안전하게 멈추는 용도 |
| `victory.png` | **승리** 결과 화면의 고유 문구/아이콘 | 경험치 숫자처럼 매번 바뀌는 부분은 피하기 |
| `in_battle.png` | **전투 중에만** 보이는 고정 UI (스킬 아이콘, 턴 표시 등) | 전투 밖에서는 절대 보이지 않는 부분 |
| `auto_off.png` | 자동전투 버튼이 **꺼진 상태** 의 모양 | 켜진 상태와 색/모양 차이가 드러나는 부분을 잘라야 함. 차이가 없으면 시나리오의 주석 처리된 대안(고정 좌표) 사용 |
| `battle_start.png` | 스테이지/던전 화면의 **전투 시작/도전** 버튼 | 글자 포함 |

저장 후 `gamebot check game_bot/scenarios/cheonji.yaml` 로 빠진 파일을 확인하고,
`gamebot find game_bot/templates/cheonji/close.png` 로 현재 화면에서 몇 점으로 잡히는지 볼 수 있습니다.
