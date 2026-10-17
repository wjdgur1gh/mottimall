"""game_bot — ADB 기반 안드로이드 게임 자동 플레이 프레임워크.

PC 에 USB(또는 무선 ADB)로 연결한 휴대폰의 화면을 캡처하고, 화면에서 버튼 이미지를
찾아 터치/스와이프하는 동작을 YAML 시나리오로 정의해 반복 실행한다.

구성:
- adb.py       : adb 실행 파일 래퍼 (기기 목록, 스크린샷, 탭, 스와이프, 키 입력)
- vision.py    : OpenCV 템플릿 매칭 / 픽셀 색 비교
- scenario.py  : YAML 시나리오 → 규칙(조건 + 동작) 파싱
- engine.py    : 캡처 → 규칙 평가 → 동작 실행 루프
- pick.py      : 스크린샷에서 좌표 찍기 / 템플릿 잘라내기 GUI
- cli.py       : `python -m game_bot ...` 명령줄
"""

__version__ = "0.1.0"
