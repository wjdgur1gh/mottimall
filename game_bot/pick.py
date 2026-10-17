"""스크린샷에서 좌표를 찍고 템플릿(버튼 이미지)을 잘라내는 GUI 도구.

OpenCV 창을 띄운다. 왼쪽 클릭 → 좌표와 색 출력, 드래그 → 영역 선택, s → 선택 영역을 템플릿으로 저장.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .vision import color_hex, crop, pixel_color, save_image

HELP = """
┌─ gamebot pick ──────────────────────────────────────────────────────┐
│  왼쪽 클릭        : 그 지점의 좌표와 색을 출력 (tap / pixel 조건용)   │
│  드래그           : 영역 선택 (버튼 이미지를 템플릿으로 잘라낼 범위)   │
│  s                : 선택 영역을 PNG 템플릿으로 저장 (이름은 콘솔 입력) │
│  r                : 휴대폰 화면 다시 캡처 (라이브 모드일 때)           │
│  c                : 선택 취소                                        │
│  q / ESC          : 종료                                             │
└──────────────────────────────────────────────────────────────────────┘
팁: 버튼 글자/아이콘이 꽉 차게, 배경이 변하는 부분(숫자·게이지)은 피해서 잘라야 잘 인식됩니다.
"""


class Picker:
    def __init__(
        self,
        image: np.ndarray,
        out_dir: str | Path,
        grab: Callable[[], np.ndarray] | None = None,
        max_size: tuple[int, int] = (1100, 900),
        window: str = "gamebot pick",
    ):
        self.img = image
        self.out_dir = Path(out_dir)
        self.grab = grab
        self.max_size = max_size
        self.window = window
        self.sel: tuple[tuple[int, int], tuple[int, int]] | None = None   # 표시 좌표계
        self.drag_start: tuple[int, int] | None = None
        self.mouse = (0, 0)
        self.scale = 1.0
        self.base = image
        self._fit()

    # ---- 좌표 변환 ----
    def _fit(self) -> None:
        h, w = self.img.shape[:2]
        self.scale = min(1.0, self.max_size[0] / w, self.max_size[1] / h)
        if self.scale < 1.0:
            self.base = cv2.resize(self.img, (int(w * self.scale), int(h * self.scale)), interpolation=cv2.INTER_AREA)
        else:
            self.base = self.img.copy()

    def to_orig(self, x: int, y: int) -> tuple[int, int]:
        H, W = self.img.shape[:2]
        ox = min(W - 1, max(0, int(round(x / self.scale))))
        oy = min(H - 1, max(0, int(round(y / self.scale))))
        return ox, oy

    def selection_rect(self) -> tuple[int, int, int, int] | None:
        """선택 영역을 원본 좌표 (x, y, w, h) 로."""
        if not self.sel:
            return None
        (x0, y0), (x1, y1) = self.sel
        ax, ay = self.to_orig(min(x0, x1), min(y0, y1))
        bx, by = self.to_orig(max(x0, x1), max(y0, y1))
        if bx - ax < 2 or by - ay < 2:
            return None
        return (ax, ay, bx - ax + 1, by - ay + 1)

    # ---- 이벤트 ----
    def on_mouse(self, event: int, x: int, y: int, flags: int, param: object) -> None:
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
            self.sel = None
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.sel = (self.drag_start, (x, y))
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            sx, sy = self.drag_start
            if abs(x - sx) > 3 or abs(y - sy) > 3:
                self.sel = (self.drag_start, (x, y))
                rect = self.selection_rect()
                if rect:
                    print(f"선택 영역: x={rect[0]} y={rect[1]} w={rect[2]} h={rect[3]}   "
                          f"(region: [{rect[0]}, {rect[1]}, {rect[2]}, {rect[3]}])  → s 키로 저장")
            else:
                self.sel = None
                ox, oy = self.to_orig(x, y)
                rgb = pixel_color(self.img, ox, oy)
                print(f"클릭: ({ox}, {oy})  색 {color_hex(rgb)}  "
                      f"→ YAML:  - tap: [{ox}, {oy}]      또는  pixel: [{ox}, {oy}]  color: \"{color_hex(rgb)}\"")
            self.drag_start = None

    # ---- 그리기 ----
    def render(self) -> np.ndarray:
        out = self.base.copy()
        h, w = out.shape[:2]
        mx, my = self.mouse
        cv2.line(out, (mx, 0), (mx, h), (0, 255, 0), 1)
        cv2.line(out, (0, my), (w, my), (0, 255, 0), 1)
        if self.sel:
            (x0, y0), (x1, y1) = self.sel
            cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 2)
        ox, oy = self.to_orig(mx, my)
        H, W = self.img.shape[:2]
        status = f"({ox}, {oy})  screen {W}x{H}  [s]save [r]refresh [c]clear [q]quit"
        cv2.rectangle(out, (0, h - 26), (w, h), (0, 0, 0), -1)
        cv2.putText(out, status, (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        return out

    # ---- 저장 ----
    def save_selection(self) -> Path | None:
        rect = self.selection_rect()
        if not rect:
            print("저장할 영역이 없습니다. 먼저 드래그로 영역을 선택하세요.")
            return None
        x, y, w, h = rect
        default = datetime.now().strftime("template_%H%M%S")
        try:
            name = input(f"템플릿 이름 (영문 권장, 엔터 = {default}): ").strip()
        except EOFError:
            name = ""
        name = name or default
        if not name.lower().endswith(".png"):
            name += ".png"
        path = save_image(self.out_dir / name, crop(self.img, x, y, w, h))
        print(f"저장됨: {path}  ({w}x{h})")
        print("시나리오에 붙여 넣을 규칙 예시:")
        print(f"  - name: {Path(name).stem}")
        print("    when:")
        print(f"      image: {name}")
        print(f"      # region: [{x}, {y}, {w}, {h}]   # 이 근처에서만 찾게 하려면 주석 해제(여유를 더 주세요)")
        print("    do:")
        print("      - tap: match")
        return path

    # ---- 메인 루프 ----
    def run(self) -> None:
        try:
            cv2.namedWindow(self.window, cv2.WINDOW_AUTOSIZE)
        except cv2.error as e:  # headless OpenCV
            raise RuntimeError(
                "OpenCV 창을 열 수 없습니다. GUI 가 있는 OpenCV 가 필요합니다:\n"
                "  pip uninstall -y opencv-python-headless && pip install opencv-python"
            ) from e
        cv2.setMouseCallback(self.window, self.on_mouse)
        print(HELP)
        while True:
            cv2.imshow(self.window, self.render())
            k = cv2.waitKey(30) & 0xFF
            if k in (27, ord("q"), ord("Q")):
                break
            if k in (ord("c"), ord("C")):
                self.sel = None
            elif k in (ord("s"), ord("S")):
                self.save_selection()
            elif k in (ord("r"), ord("R")):
                if self.grab is None:
                    print("이미지 파일 모드에서는 다시 캡처할 수 없습니다 (--image 없이 실행하면 라이브 모드).")
                else:
                    print("화면 다시 캡처 중...")
                    self.img = self.grab()
                    self.sel = None
                    self._fit()
            try:
                if cv2.getWindowProperty(self.window, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break
        cv2.destroyAllWindows()
