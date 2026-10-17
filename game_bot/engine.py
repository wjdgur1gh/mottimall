"""실행 엔진: 화면 캡처 → 규칙 평가 → 동작 실행 을 반복한다."""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from . import scenario as S
from .vision import Match, color_hex, draw_matches, find_template, load_image, pixel_color, save_image

log = logging.getLogger("game_bot.engine")


class DeviceLike(Protocol):
    """엔진이 기기에 요구하는 최소 인터페이스 (AdbDevice 또는 테스트용 가짜 기기)."""

    def screenshot(self) -> np.ndarray: ...
    def tap(self, x: float, y: float) -> None: ...
    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None: ...
    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None: ...
    def key(self, key: str | int) -> None: ...
    def text(self, s: str) -> None: ...
    def launch(self, package: str) -> None: ...
    def stop_app(self, package: str) -> None: ...


class StopRequested(Exception):
    """시나리오의 stop 동작."""


class RuleAborted(Exception):
    """wait_for 타임아웃 등으로 현재 규칙의 남은 동작을 취소."""


@dataclass
class Frame:
    """한 번 캡처한 화면. scale 은 시나리오 좌표 → 실제 화면 좌표 배율."""

    screen: np.ndarray
    captured_at: float
    scale: float = 1.0

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.screen.shape[:2]
        return (w, h)

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale, y * self.scale)

    def region(self, r: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(int(round(v * self.scale)) for v in r)  # type: ignore[return-value]


@dataclass
class EvalResult:
    ok: bool
    match: Match | None = None
    detail: str = ""


@dataclass
class RuleState:
    runs: int = 0
    last_run: float = -math.inf


@dataclass
class Stats:
    loops: int = 0
    matched: int = 0
    per_rule: dict[str, int] = field(default_factory=dict)
    started_at: float = 0.0
    ended_at: float = 0.0
    stop_reason: str = ""

    @property
    def elapsed(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    def summary(self) -> str:
        lines = [
            f"실행 시간 {self.elapsed:.0f}초, 루프 {self.loops}회, 규칙 실행 {self.matched}회"
            + (f" — 종료 사유: {self.stop_reason}" if self.stop_reason else "")
        ]
        for name, n in sorted(self.per_rule.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name}: {n}회")
        return "\n".join(lines)


class Engine:
    def __init__(
        self,
        scenario: S.Scenario,
        device: DeviceLike,
        *,
        dry_run: bool = False,
        debug_dir: str | Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.sc = scenario
        self.dev = device
        self.dry_run = dry_run
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self._sleep = sleep
        self._clock = clock
        self._templates: dict[str, np.ndarray] = {}
        self._states = {r.name: RuleState() for r in scenario.rules}
        self._rules = scenario.sorted_rules()
        self._warned_geometry = False
        self._last_match: Match | None = None
        self.stats = Stats()

    # ------------------------------------------------------------ 템플릿
    def template(self, name: str) -> np.ndarray:
        if name not in self._templates:
            self._templates[name] = load_image(self.sc.template_path(name))
        return self._templates[name]

    def check(self) -> list[str]:
        """모든 템플릿 파일을 미리 읽어 본다. 문제 목록을 돌려준다 (비어 있으면 정상)."""
        problems: list[str] = []
        for name in self.sc.template_names():
            try:
                self.template(name)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{name}: {e}")
        return problems

    # ------------------------------------------------------------ 캡처
    def capture(self) -> Frame:
        screen = self.dev.screenshot()
        h, w = screen.shape[:2]
        scale = 1.0
        if self.sc.screen:
            sw, sh = self.sc.screen
            if (w > h) != (sw > sh) and not self._warned_geometry:
                log.warning(
                    "화면 방향이 시나리오(%dx%d)와 실제(%dx%d)에서 다릅니다. "
                    "게임을 같은 방향으로 돌려 두고 템플릿을 다시 캡처하세요.", sw, sh, w, h,
                )
                self._warned_geometry = True
            scale = w / sw
            if not self._warned_geometry and abs((w / h) - (sw / sh)) > 0.02:
                log.warning(
                    "화면 비율이 다릅니다: 시나리오 %dx%d, 실제 %dx%d. 고정 좌표가 조금 어긋날 수 있습니다.",
                    sw, sh, w, h,
                )
                self._warned_geometry = True
        return Frame(screen, self._clock(), scale)

    # ------------------------------------------------------------ 조건 평가
    def evaluate(self, cond: S.Cond, frame: Frame) -> EvalResult:
        if isinstance(cond, S.AlwaysCond):
            return EvalResult(True, detail="always")

        if isinstance(cond, S.ImageCond):
            tpl = self.template(cond.name)
            region = frame.region(cond.region) if cond.region else None
            m = find_template(frame.screen, tpl, cond.threshold, region, cond.grayscale, frame.scale)
            if m is None:
                return EvalResult(False, detail=f"{cond.name} 없음")
            return EvalResult(True, m, f"{cond.name} @{m}")

        if isinstance(cond, S.PixelCond):
            x, y = frame.pt(cond.x, cond.y)
            try:
                actual = pixel_color(frame.screen, x, y)
            except ValueError as e:
                log.warning("%s", e)
                return EvalResult(False, detail=str(e))
            ok = max(abs(a - b) for a, b in zip(actual, cond.color)) <= cond.tolerance
            return EvalResult(
                ok, detail=f"pixel({cond.x},{cond.y})={color_hex(actual)} 기대 {color_hex(cond.color)}±{cond.tolerance}"
            )

        if isinstance(cond, S.AllCond):
            first: Match | None = None
            details = []
            for c in cond.items:
                r = self.evaluate(c, frame)
                if not r.ok:
                    return EvalResult(False, detail=f"all 실패: {r.detail}")
                details.append(r.detail)
                if first is None and r.match is not None:
                    first = r.match
            return EvalResult(True, first, "all: " + "; ".join(details))

        if isinstance(cond, S.AnyCond):
            for c in cond.items:
                r = self.evaluate(c, frame)
                if r.ok:
                    return r
            return EvalResult(False, detail="any: 모두 불일치")

        if isinstance(cond, S.NotCond):
            r = self.evaluate(cond.item, frame)
            return EvalResult(not r.ok, detail=f"not({r.detail})")

        raise TypeError(f"알 수 없는 조건: {cond!r}")

    # ------------------------------------------------------------ 한 루프
    def step(self) -> S.Rule | None:
        """화면을 한 번 캡처해 우선순위 순으로 규칙을 평가하고, 첫 번째로 맞는 규칙을 실행한다."""
        frame = self.capture()
        now = frame.captured_at
        for rule in self._rules:
            if not rule.enabled:
                continue
            st = self._states[rule.name]
            if rule.max_runs is not None and st.runs >= rule.max_runs:
                continue
            if rule.cooldown > 0 and (now - st.last_run) < rule.cooldown:
                continue
            res = self.evaluate(rule.when, frame)
            if not res.ok:
                log.debug("  ✗ %s (%s)", rule.name, res.detail)
                continue

            log.info("▶ %s  [%s]", rule.name, res.detail)
            st.runs += 1
            st.last_run = now
            self.stats.matched += 1
            self.stats.per_rule[rule.name] = self.stats.per_rule.get(rule.name, 0) + 1
            if self.debug_dir is not None:
                self._save_debug(frame, rule, res)
            self._last_match = res.match
            try:
                for action in rule.do:
                    self._execute(action, frame)
            except RuleAborted as e:
                log.warning("규칙 '%s' 의 남은 동작을 건너뜁니다: %s", rule.name, e)
            return rule
        return None

    # ------------------------------------------------------------ 전체 실행
    def run(self, max_loops: int | None = None) -> Stats:
        self.stats = Stats(started_at=self._clock())
        idle = 0
        reason = ""
        try:
            if self.sc.package:
                self._do("launch", self.sc.package, lambda: self.dev.launch(self.sc.package or ""))
                if not self.dry_run:
                    self._sleep(3.0)
            while True:
                if max_loops is not None and self.stats.loops >= max_loops:
                    reason = f"최대 반복 {max_loops}회 도달"
                    break
                if self.sc.stop_after is not None and (self._clock() - self.stats.started_at) >= self.sc.stop_after:
                    reason = f"stop_after {self.sc.stop_after:.0f}초 경과"
                    break
                rule = self.step()
                self.stats.loops += 1
                if rule is None:
                    idle += 1
                    if self.sc.idle_limit is not None and idle >= self.sc.idle_limit:
                        reason = f"규칙이 {idle}회 연속 매칭되지 않음 (idle_limit)"
                        break
                else:
                    idle = 0
                self._sleep(self.sc.interval)
        except StopRequested as e:
            reason = f"stop: {e}"
        except KeyboardInterrupt:
            reason = "사용자가 Ctrl+C 로 중단"
        self.stats.ended_at = self._clock()
        self.stats.stop_reason = reason
        return self.stats

    # ------------------------------------------------------------ 동작 실행
    def _resolve(self, target: S.Target, offset: tuple[float, float], frame: Frame) -> tuple[float, float]:
        ox, oy = offset[0] * frame.scale, offset[1] * frame.scale
        if target == "match":
            if self._last_match is None:
                raise RuleAborted("'tap: match' 를 쓰려면 규칙 조건에 image 가 있거나 바로 앞에 wait_for 가 있어야 합니다")
            cx, cy = self._last_match.center
            return (cx + ox, cy + oy)
        x, y = frame.pt(target[0], target[1])  # type: ignore[index]
        return (x + ox, y + oy)

    def _do(self, what: str, args: object, fn: Callable[[], None]) -> None:
        if self.dry_run:
            log.info("  [dry-run] %s %s", what, args)
            return
        log.debug("  %s %s", what, args)
        fn()

    def _execute(self, a: S.Action, frame: Frame) -> None:
        if isinstance(a, S.TapAction):
            x, y = self._resolve(a.target, a.offset, frame)
            for i in range(a.times):
                self._do("tap", (int(x), int(y)), lambda: self.dev.tap(x, y))
                if i < a.times - 1:
                    self._sleep(a.interval)
        elif isinstance(a, S.LongPressAction):
            x, y = self._resolve(a.target, a.offset, frame)
            self._do("long_press", (int(x), int(y), a.duration_ms), lambda: self.dev.long_press(x, y, a.duration_ms))
        elif isinstance(a, S.SwipeAction):
            x1, y1 = frame.pt(a.x1, a.y1)
            x2, y2 = frame.pt(a.x2, a.y2)
            self._do("swipe", (int(x1), int(y1), int(x2), int(y2), a.duration_ms),
                     lambda: self.dev.swipe(x1, y1, x2, y2, a.duration_ms))
        elif isinstance(a, S.KeyAction):
            self._do("key", a.key, lambda: self.dev.key(a.key))
        elif isinstance(a, S.TextAction):
            self._do("text", a.text, lambda: self.dev.text(a.text))
        elif isinstance(a, S.WaitAction):
            log.debug("  wait %.2fs", a.seconds)
            self._sleep(a.seconds)
        elif isinstance(a, S.WaitForAction):
            self._wait_for(a)
        elif isinstance(a, S.LogAction):
            log.info("  %s", a.message)
        elif isinstance(a, S.LaunchAction):
            self._do("launch", a.package, lambda: self.dev.launch(a.package))
        elif isinstance(a, S.StopAppAction):
            self._do("stop_app", a.package, lambda: self.dev.stop_app(a.package))
        elif isinstance(a, S.ScreenshotAction):
            path = Path(datetime.now().strftime(a.path))
            if not path.is_absolute():
                path = self.sc.base_dir / path
            save_image(path, self.dev.screenshot())
            log.info("  스크린샷 저장: %s", path)
        elif isinstance(a, S.StopAction):
            raise StopRequested(a.reason)
        else:
            raise TypeError(f"알 수 없는 동작: {a!r}")

    def _wait_for(self, a: S.WaitForAction) -> None:
        deadline = self._clock() + a.timeout
        label = "사라지기" if a.gone else "나타나기"
        while True:
            frame = self.capture()
            res = self.evaluate(a.cond, frame)
            if res.ok != a.gone:
                if res.match is not None:
                    self._last_match = res.match
                log.debug("  wait_for 완료: %s", res.detail)
                return
            if self._clock() >= deadline:
                msg = f"{a.timeout:.0f}초 동안 조건이 {label}를 기다렸지만 실패 ({res.detail})"
                if a.on_timeout == "abort":
                    raise RuleAborted(msg)
                log.warning("  %s — 계속 진행", msg)
                return
            self._sleep(a.interval)

    # ------------------------------------------------------------ 디버그
    def _save_debug(self, frame: Frame, rule: S.Rule, res: EvalResult) -> None:
        assert self.debug_dir is not None
        safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", rule.name)[:40]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        img = draw_matches(frame.screen, [res.match] if res.match else [])
        try:
            save_image(self.debug_dir / f"{ts}_{safe}.png", img)
        except Exception as e:  # noqa: BLE001
            log.warning("디버그 스크린샷 저장 실패: %s", e)
