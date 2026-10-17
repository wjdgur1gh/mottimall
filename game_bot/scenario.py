"""YAML 시나리오 → 규칙(조건 + 동작) 객체.

시나리오 파일 예시는 game_bot/scenarios/example.yaml, 문법 설명은 game_bot/README.md 참고.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import yaml

from .vision import RGB, Region, parse_color


class ScenarioError(ValueError):
    """시나리오 파일 문법 오류."""


# ================================================================ 조건
@dataclass
class AlwaysCond:
    pass


@dataclass
class ImageCond:
    name: str                   # templates_dir 기준 파일명
    threshold: float = 0.8
    region: Region | None = None
    grayscale: bool = False


@dataclass
class PixelCond:
    x: int
    y: int
    color: RGB
    tolerance: int = 20


@dataclass
class AllCond:
    items: list["Cond"]


@dataclass
class AnyCond:
    items: list["Cond"]


@dataclass
class NotCond:
    item: "Cond"


Cond = Union[AlwaysCond, ImageCond, PixelCond, AllCond, AnyCond, NotCond]


# ================================================================ 동작
Point = tuple[float, float]
Target = Union[str, Point]      # "match" 또는 (x, y)


@dataclass
class TapAction:
    target: Target = "match"
    offset: tuple[float, float] = (0.0, 0.0)
    times: int = 1
    interval: float = 0.15


@dataclass
class LongPressAction:
    target: Target = "match"
    duration_ms: int = 800
    offset: tuple[float, float] = (0.0, 0.0)


@dataclass
class SwipeAction:
    x1: float
    y1: float
    x2: float
    y2: float
    duration_ms: int = 300


@dataclass
class KeyAction:
    key: str


@dataclass
class TextAction:
    text: str


@dataclass
class WaitAction:
    seconds: float


@dataclass
class WaitForAction:
    cond: Cond
    timeout: float = 10.0
    interval: float = 0.5
    gone: bool = False            # True 면 "사라질 때까지" 대기
    on_timeout: str = "abort"     # abort: 이 규칙의 남은 동작 취소 / continue: 계속


@dataclass
class LogAction:
    message: str


@dataclass
class LaunchAction:
    package: str


@dataclass
class StopAppAction:
    package: str


@dataclass
class ScreenshotAction:
    path: str


@dataclass
class StopAction:
    reason: str = "시나리오의 stop 동작"


Action = Union[
    TapAction, LongPressAction, SwipeAction, KeyAction, TextAction, WaitAction,
    WaitForAction, LogAction, LaunchAction, StopAppAction, ScreenshotAction, StopAction,
]


# ================================================================ 규칙 / 시나리오
@dataclass
class Rule:
    name: str
    when: Cond
    do: list[Action]
    priority: int = 0
    cooldown: float = 0.0
    max_runs: int | None = None
    enabled: bool = True


@dataclass
class Scenario:
    name: str
    rules: list[Rule]
    base_dir: Path
    templates_dir: Path
    interval: float = 1.0
    screen: tuple[int, int] | None = None   # 템플릿을 캡처한 해상도 (가로, 세로)
    package: str | None = None
    stop_after: float | None = None
    idle_limit: int | None = None
    device: str | None = None

    def sorted_rules(self) -> list[Rule]:
        """우선순위 높은 순 (같으면 파일에 적힌 순서)."""
        return sorted(self.rules, key=lambda r: -r.priority)

    def template_names(self) -> list[str]:
        names: list[str] = []

        def walk_cond(c: Cond) -> None:
            if isinstance(c, ImageCond):
                names.append(c.name)
            elif isinstance(c, (AllCond, AnyCond)):
                for it in c.items:
                    walk_cond(it)
            elif isinstance(c, NotCond):
                walk_cond(c.item)

        for r in self.rules:
            walk_cond(r.when)
            for a in r.do:
                if isinstance(a, WaitForAction):
                    walk_cond(a.cond)
        seen: dict[str, None] = {}
        for n in names:
            seen.setdefault(n, None)
        return list(seen)

    def template_path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.templates_dir / p


# ================================================================ 파싱 도우미
_COND_KEYS = {"image", "pixel", "all", "any", "not", "always"}
_IMAGE_MODIFIERS = {"threshold", "region", "grayscale"}
_PIXEL_MODIFIERS = {"color", "tolerance"}


def _ctx(where: str) -> str:
    return f"[{where}] " if where else ""


def _as_float(v: Any, where: str, what: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ScenarioError(f"{_ctx(where)}{what} 은(는) 숫자여야 합니다: {v!r}") from None


def _as_int(v: Any, where: str, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ScenarioError(f"{_ctx(where)}{what} 은(는) 정수여야 합니다: {v!r}")
    return int(v)


def _as_point(v: Any, where: str, what: str) -> Point:
    if isinstance(v, dict) and {"x", "y"} <= set(v):
        return (_as_float(v["x"], where, what + ".x"), _as_float(v["y"], where, what + ".y"))
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return (_as_float(v[0], where, what), _as_float(v[1], where, what))
    raise ScenarioError(f"{_ctx(where)}{what} 은(는) [x, y] 형식이어야 합니다: {v!r}")


def _as_region(v: Any, where: str) -> Region:
    if isinstance(v, (list, tuple)) and len(v) == 4:
        vals = tuple(_as_int(x, where, "region") for x in v)
        if vals[2] <= 0 or vals[3] <= 0:
            raise ScenarioError(f"{_ctx(where)}region 의 w, h 는 양수여야 합니다: {v!r}")
        return vals  # type: ignore[return-value]
    raise ScenarioError(f"{_ctx(where)}region 은 [x, y, w, h] 형식이어야 합니다: {v!r}")


def _as_target(v: Any, where: str, what: str) -> Target:
    if isinstance(v, str):
        if v.strip().lower() == "match":
            return "match"
        raise ScenarioError(f"{_ctx(where)}{what} 은(는) 'match' 또는 [x, y] 여야 합니다: {v!r}")
    return _as_point(v, where, what)


def _check_keys(d: dict, allowed: set[str], where: str, what: str) -> None:
    extra = set(d) - allowed
    if extra:
        raise ScenarioError(
            f"{_ctx(where)}{what} 에 알 수 없는 항목이 있습니다: {sorted(extra)} "
            f"(허용: {sorted(allowed)})"
        )


# ================================================================ 조건 파싱
def parse_cond(v: Any, where: str = "") -> Cond:
    if v is None:
        raise ScenarioError(f"{_ctx(where)}조건(when)이 비어 있습니다")
    if isinstance(v, str):
        s = v.strip()
        if s.lower() == "always":
            return AlwaysCond()
        return ImageCond(name=s)   # when: close.png 축약형
    if isinstance(v, bool):
        if v:
            return AlwaysCond()
        raise ScenarioError(f"{_ctx(where)}when: false 는 의미가 없습니다 (enabled: false 를 쓰세요)")
    if not isinstance(v, dict):
        raise ScenarioError(f"{_ctx(where)}조건 형식이 잘못되었습니다: {v!r}")

    keys = set(v)
    main = keys & _COND_KEYS
    if len(main) != 1:
        raise ScenarioError(
            f"{_ctx(where)}조건에는 {sorted(_COND_KEYS)} 중 정확히 하나가 있어야 합니다: {sorted(keys)}"
        )
    kind = main.pop()

    if kind == "always":
        _check_keys(v, {"always"}, where, "always 조건")
        return AlwaysCond()

    if kind == "image":
        _check_keys(v, {"image"} | _IMAGE_MODIFIERS, where, "image 조건")
        name = v["image"]
        if not isinstance(name, str) or not name.strip():
            raise ScenarioError(f"{_ctx(where)}image 는 템플릿 파일명이어야 합니다: {name!r}")
        cond = ImageCond(name=name.strip())
        if "threshold" in v:
            cond.threshold = _as_float(v["threshold"], where, "threshold")
            if not 0 < cond.threshold <= 1:
                raise ScenarioError(f"{_ctx(where)}threshold 는 0~1 사이여야 합니다: {cond.threshold}")
        if "region" in v:
            cond.region = _as_region(v["region"], where)
        if "grayscale" in v:
            cond.grayscale = bool(v["grayscale"])
        return cond

    if kind == "pixel":
        _check_keys(v, {"pixel"} | _PIXEL_MODIFIERS, where, "pixel 조건")
        spec = v["pixel"]
        if isinstance(spec, dict):
            _check_keys(spec, {"x", "y", "color", "tolerance"}, where, "pixel")
            x, y = _as_point(spec, where, "pixel")
            color = spec.get("color", v.get("color"))
            tol = spec.get("tolerance", v.get("tolerance", 20))
        else:
            x, y = _as_point(spec, where, "pixel")
            color = v.get("color")
            tol = v.get("tolerance", 20)
        if color is None:
            raise ScenarioError(f"{_ctx(where)}pixel 조건에는 color 가 필요합니다 (예: color: '#ff0000')")
        try:
            rgb = parse_color(color)
        except ValueError as e:
            raise ScenarioError(f"{_ctx(where)}{e}") from None
        return PixelCond(int(x), int(y), rgb, _as_int(tol, where, "tolerance"))

    if kind in ("all", "any"):
        _check_keys(v, {kind}, where, f"{kind} 조건")
        items = v[kind]
        if not isinstance(items, list) or not items:
            raise ScenarioError(f"{_ctx(where)}{kind} 는 조건 목록이어야 합니다")
        parsed = [parse_cond(it, where) for it in items]
        return AllCond(parsed) if kind == "all" else AnyCond(parsed)

    # not
    _check_keys(v, {"not"}, where, "not 조건")
    return NotCond(parse_cond(v["not"], where))


# ================================================================ 동작 파싱
_ACTION_KEYS = {
    "tap", "long_press", "swipe", "key", "text", "wait", "wait_for", "wait_gone",
    "log", "launch", "stop_app", "screenshot", "stop",
}


def parse_action(v: Any, where: str = "") -> Action:
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "stop":
            return StopAction()
        raise ScenarioError(f"{_ctx(where)}동작 형식이 잘못되었습니다: {v!r} (예: '- tap: match')")
    if not isinstance(v, dict):
        raise ScenarioError(f"{_ctx(where)}동작 형식이 잘못되었습니다: {v!r}")
    main = set(v) & _ACTION_KEYS
    if len(main) != 1:
        raise ScenarioError(
            f"{_ctx(where)}동작에는 {sorted(_ACTION_KEYS)} 중 정확히 하나가 있어야 합니다: {sorted(v)}"
        )
    kind = main.pop()
    arg = v[kind]

    if kind in ("tap", "long_press"):
        _check_keys(v, {kind, "offset", "times", "interval", "duration_ms"}, where, kind)
        offset = (0.0, 0.0)
        times, interval, duration = 1, 0.15, 800
        if isinstance(arg, dict):
            _check_keys(arg, {"at", "x", "y", "offset", "times", "interval", "duration_ms"}, where, kind)
            if "at" in arg:
                target = _as_target(arg["at"], where, kind)
            elif "x" in arg and "y" in arg:
                target = _as_point(arg, where, kind)
            else:
                target = "match"
            src = {**v, **arg}
        else:
            target = _as_target(arg, where, kind)
            src = v
        if "offset" in src:
            offset = _as_point(src["offset"], where, "offset")
        if "times" in src:
            times = _as_int(src["times"], where, "times")
        if "interval" in src:
            interval = _as_float(src["interval"], where, "interval")
        if "duration_ms" in src:
            duration = _as_int(src["duration_ms"], where, "duration_ms")
        if kind == "tap":
            return TapAction(target, offset, max(1, times), interval)
        return LongPressAction(target, duration, offset)

    if kind == "swipe":
        _check_keys(v, {"swipe", "duration_ms"}, where, "swipe")
        if isinstance(arg, dict):
            _check_keys(arg, {"from", "to", "duration_ms"}, where, "swipe")
            p1 = _as_point(arg.get("from"), where, "swipe.from")
            p2 = _as_point(arg.get("to"), where, "swipe.to")
            dur = arg.get("duration_ms", v.get("duration_ms", 300))
        elif isinstance(arg, (list, tuple)) and len(arg) in (4, 5):
            p1 = (_as_float(arg[0], where, "swipe"), _as_float(arg[1], where, "swipe"))
            p2 = (_as_float(arg[2], where, "swipe"), _as_float(arg[3], where, "swipe"))
            dur = arg[4] if len(arg) == 5 else v.get("duration_ms", 300)
        else:
            raise ScenarioError(f"{_ctx(where)}swipe 는 [x1, y1, x2, y2, (ms)] 형식이어야 합니다: {arg!r}")
        return SwipeAction(p1[0], p1[1], p2[0], p2[1], _as_int(dur, where, "duration_ms"))

    if kind == "key":
        _check_keys(v, {"key"}, where, "key")
        return KeyAction(str(arg))

    if kind == "text":
        _check_keys(v, {"text"}, where, "text")
        return TextAction(str(arg))

    if kind == "wait":
        _check_keys(v, {"wait"}, where, "wait")
        sec = _as_float(arg, where, "wait")
        if sec < 0:
            raise ScenarioError(f"{_ctx(where)}wait 는 0 이상이어야 합니다: {sec}")
        return WaitAction(sec)

    if kind in ("wait_for", "wait_gone"):
        _check_keys(v, {kind, "timeout", "interval", "on_timeout"}, where, kind)
        if isinstance(arg, dict):
            cond_dict = {k: x for k, x in arg.items() if k not in ("timeout", "interval", "on_timeout")}
            opts = {**v, **{k: x for k, x in arg.items() if k in ("timeout", "interval", "on_timeout")}}
            cond = parse_cond(cond_dict, where)
        else:
            cond = parse_cond(arg, where)
            opts = v
        on_timeout = str(opts.get("on_timeout", "abort")).lower()
        if on_timeout not in ("abort", "continue"):
            raise ScenarioError(f"{_ctx(where)}on_timeout 은 abort 또는 continue 여야 합니다: {on_timeout!r}")
        return WaitForAction(
            cond,
            timeout=_as_float(opts.get("timeout", 10), where, "timeout"),
            interval=_as_float(opts.get("interval", 0.5), where, "interval"),
            gone=(kind == "wait_gone"),
            on_timeout=on_timeout,
        )

    if kind == "log":
        return LogAction(str(arg))
    if kind == "launch":
        return LaunchAction(str(arg))
    if kind == "stop_app":
        return StopAppAction(str(arg))
    if kind == "screenshot":
        return ScreenshotAction(str(arg))
    # stop
    return StopAction(str(arg) if arg not in (None, True) else "시나리오의 stop 동작")


# ================================================================ 규칙 / 시나리오 파싱
_RULE_KEYS = {"name", "when", "do", "priority", "cooldown", "max_runs", "enabled"}
_SCENARIO_KEYS = {
    "name", "rules", "templates_dir", "interval", "screen", "package",
    "stop_after", "idle_limit", "device",
}


def parse_rule(d: Any, index: int) -> Rule:
    if not isinstance(d, dict):
        raise ScenarioError(f"rules[{index}] 는 name/when/do 를 가진 항목이어야 합니다: {d!r}")
    name = str(d.get("name") or f"규칙 {index + 1}")
    where = name
    _check_keys(d, _RULE_KEYS, where, "규칙")
    if "when" not in d:
        raise ScenarioError(f"{_ctx(where)}when (조건) 이 없습니다")
    if "do" not in d:
        raise ScenarioError(f"{_ctx(where)}do (동작 목록) 이 없습니다")
    do = d["do"]
    if isinstance(do, (str, dict)):
        do = [do]
    if not isinstance(do, list) or not do:
        raise ScenarioError(f"{_ctx(where)}do 는 동작 목록이어야 합니다 (예: '- tap: match')")
    rule = Rule(
        name=name,
        when=parse_cond(d["when"], where),
        do=[parse_action(a, where) for a in do],
        priority=_as_int(d.get("priority", 0), where, "priority"),
        cooldown=_as_float(d.get("cooldown", 0), where, "cooldown"),
        max_runs=(None if d.get("max_runs") is None else _as_int(d["max_runs"], where, "max_runs")),
        enabled=bool(d.get("enabled", True)),
    )
    if rule.cooldown < 0:
        raise ScenarioError(f"{_ctx(where)}cooldown 은 0 이상이어야 합니다")
    return rule


def parse_scenario(d: Any, base_dir: str | Path = ".") -> Scenario:
    if not isinstance(d, dict):
        raise ScenarioError("시나리오 파일의 최상위는 name/rules 를 가진 매핑이어야 합니다")
    _check_keys(d, _SCENARIO_KEYS, "", "시나리오")
    base = Path(base_dir).resolve()
    rules_raw = d.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ScenarioError("rules 에 규칙이 하나 이상 있어야 합니다")
    rules = [parse_rule(r, i) for i, r in enumerate(rules_raw)]
    names = [r.name for r in rules]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ScenarioError(f"규칙 이름이 중복됩니다: {sorted(dup)}")

    tdir = Path(str(d.get("templates_dir", ".")))
    if not tdir.is_absolute():
        tdir = (base / tdir).resolve()

    screen = None
    if d.get("screen") is not None:
        s = d["screen"]
        if isinstance(s, str) and "x" in s:
            s = s.lower().split("x")
        if not isinstance(s, (list, tuple)) or len(s) != 2:
            raise ScenarioError("screen 은 [가로, 세로] 또는 '1080x2400' 형식이어야 합니다")
        screen = (_as_int(int(s[0]), "", "screen"), _as_int(int(s[1]), "", "screen"))
        if screen[0] <= 0 or screen[1] <= 0:
            raise ScenarioError("screen 값은 양수여야 합니다")

    interval = _as_float(d.get("interval", 1.0), "", "interval")
    if interval < 0:
        raise ScenarioError("interval 은 0 이상이어야 합니다")

    return Scenario(
        name=str(d.get("name") or base.name),
        rules=rules,
        base_dir=base,
        templates_dir=tdir,
        interval=interval,
        screen=screen,
        package=(str(d["package"]) if d.get("package") else None),
        stop_after=(None if d.get("stop_after") is None else _as_float(d["stop_after"], "", "stop_after")),
        idle_limit=(None if d.get("idle_limit") is None else _as_int(d["idle_limit"], "", "idle_limit")),
        device=(str(d["device"]) if d.get("device") else None),
    )


def load_scenario(path: str | Path) -> Scenario:
    p = Path(path)
    if not p.is_file():
        raise ScenarioError(f"시나리오 파일이 없습니다: {p}")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ScenarioError(f"YAML 문법 오류 ({p}):\n{e}") from None
    return parse_scenario(data, p.parent)
