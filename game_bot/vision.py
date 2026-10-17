"""OpenCV 기반 화면 인식: 템플릿(버튼 이미지) 매칭, 픽셀 색 비교, 이미지 입출력.

좌표계: 모든 좌표는 (x, y) = (가로, 세로) 픽셀, 왼쪽 위가 (0, 0).
영역(region)은 (x, y, w, h).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

Region = tuple[int, int, int, int]
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Match:
    """템플릿이 발견된 위치. (x, y) 는 왼쪽 위, score 는 0~1 유사도."""

    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def region(self) -> Region:
        return (self.x, self.y, self.w, self.h)

    def __str__(self) -> str:
        cx, cy = self.center
        return f"({cx}, {cy}) score={self.score:.3f}"


# ---------------------------------------------------------------- 이미지 입출력
def _ensure_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def load_image(path: str | Path) -> np.ndarray:
    """PNG/JPG 를 BGR 배열로 읽는다. 한글 경로도 지원 (cv2.imread 는 윈도우에서 한글 경로 실패)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"이미지 파일이 없습니다: {p}")
    data = np.fromfile(str(p), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다 (손상되었거나 지원하지 않는 형식): {p}")
    return _ensure_bgr(img)


def save_image(path: str | Path, img: np.ndarray) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"이미지 인코딩 실패: {p}")
    buf.tofile(str(p))
    return p


def crop(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """영역을 잘라낸다 (화면 밖은 잘라서 맞춤)."""
    H, W = img.shape[:2]
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(W, int(x + w)), min(H, int(y + h))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"잘라낼 영역이 화면({W}x{H}) 밖입니다: x={x}, y={y}, w={w}, h={h}")
    return img[y0:y1, x0:x1].copy()


# ---------------------------------------------------------------- 템플릿 매칭
def scale_template(template: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-3:
        return template
    h, w = template.shape[:2]
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(template, (nw, nh), interpolation=interp)


def _clamp_region(region: Region, W: int, H: int) -> Region:
    x, y, w, h = (int(v) for v in region)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))


def _match_map(
    screen: np.ndarray,
    template: np.ndarray,
    region: Region | None,
    grayscale: bool,
    scale: float,
):
    """matchTemplate 결과 행렬과 (영역 오프셋, 템플릿 크기) 를 돌려준다. 매칭 불가면 None."""
    tpl = scale_template(_ensure_bgr(template), scale)
    scr = _ensure_bgr(screen)
    ox = oy = 0
    if region is not None:
        x, y, w, h = _clamp_region(region, scr.shape[1], scr.shape[0])
        if w == 0 or h == 0:
            return None
        scr = scr[y : y + h, x : x + w]
        ox, oy = x, y
    th, tw = tpl.shape[:2]
    sh, sw = scr.shape[:2]
    if th > sh or tw > sw:
        return None
    if grayscale:
        scr = cv2.cvtColor(scr, cv2.COLOR_BGR2GRAY)
        tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if float(tpl.std()) < 1e-6:
        raise ValueError("템플릿이 단색입니다. 글자나 테두리가 포함되도록 조금 더 넓게 잘라 주세요.")
    res = cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED)
    return res, ox, oy, tw, th


def find_template(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8,
    region: Region | None = None,
    grayscale: bool = False,
    scale: float = 1.0,
) -> Match | None:
    """화면에서 템플릿과 가장 비슷한 위치 하나. threshold 미만이면 None."""
    prepared = _match_map(screen, template, region, grayscale, scale)
    if prepared is None:
        return None
    res, ox, oy, tw, th = prepared
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    return Match(max_loc[0] + ox, max_loc[1] + oy, tw, th, float(max_val))


def best_score(
    screen: np.ndarray,
    template: np.ndarray,
    region: Region | None = None,
    grayscale: bool = False,
    scale: float = 1.0,
) -> tuple[float, Match | None]:
    """threshold 와 무관하게 최고 점수와 그 위치 (튜닝용)."""
    prepared = _match_map(screen, template, region, grayscale, scale)
    if prepared is None:
        return 0.0, None
    res, ox, oy, tw, th = prepared
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return float(max_val), Match(max_loc[0] + ox, max_loc[1] + oy, tw, th, float(max_val))


def find_all(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8,
    region: Region | None = None,
    grayscale: bool = False,
    scale: float = 1.0,
    max_results: int = 20,
) -> list[Match]:
    """threshold 이상인 모든 위치 (겹치는 것은 하나로). 점수 높은 순."""
    prepared = _match_map(screen, template, region, grayscale, scale)
    if prepared is None:
        return []
    res, ox, oy, tw, th = prepared
    res = res.copy()
    out: list[Match] = []
    rh, rw = res.shape[:2]
    while len(out) < max_results:
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < threshold:
            break
        mx, my = max_loc
        out.append(Match(mx + ox, my + oy, tw, th, float(max_val)))
        # 같은 자리를 다시 뽑지 않도록 템플릿 절반 크기 이웃을 지운다
        x0, x1 = max(0, mx - tw // 2), min(rw, mx + tw // 2 + 1)
        y0, y1 = max(0, my - th // 2), min(rh, my + th // 2 + 1)
        res[y0:y1, x0:x1] = -1.0
    return out


# ---------------------------------------------------------------- 픽셀 색
def parse_color(value: str | Sequence[int]) -> RGB:
    """'#ff8800' / 'ff8800' / [255, 136, 0] → (r, g, b)."""
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
            raise ValueError(f"색상 형식이 잘못되었습니다 (예: '#ff8800'): {value!r}")
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    vals = [int(v) for v in value]
    if len(vals) != 3 or not all(0 <= v <= 255 for v in vals):
        raise ValueError(f"색상은 [r, g, b] 0~255 세 값이어야 합니다: {value!r}")
    return (vals[0], vals[1], vals[2])


def pixel_color(screen: np.ndarray, x: int, y: int) -> RGB:
    H, W = screen.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < W and 0 <= yi < H):
        raise ValueError(f"픽셀 좌표가 화면({W}x{H}) 밖입니다: ({x}, {y})")
    b, g, r = (int(v) for v in _ensure_bgr(screen)[yi, xi][:3])
    return (r, g, b)


def pixel_matches(screen: np.ndarray, x: int, y: int, color: RGB, tolerance: int = 20) -> bool:
    actual = pixel_color(screen, x, y)
    return max(abs(a - b) for a, b in zip(actual, color)) <= tolerance


def color_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# ---------------------------------------------------------------- 디버그 표시
def draw_matches(screen: np.ndarray, matches: Iterable[Match], label: str = "") -> np.ndarray:
    """매칭 위치에 빨간 사각형과 점수를 그린 복사본."""
    out = _ensure_bgr(screen).copy()
    for m in matches:
        cv2.rectangle(out, (m.x, m.y), (m.x + m.w, m.y + m.h), (0, 0, 255), 3)
        cx, cy = m.center
        cv2.circle(out, (cx, cy), 6, (0, 255, 255), -1)
        text = f"{label} {m.score:.2f}".strip()
        cv2.putText(out, text, (m.x, max(20, m.y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return out
