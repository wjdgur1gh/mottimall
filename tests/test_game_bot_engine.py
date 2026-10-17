import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from game_bot import scenario as S  # noqa: E402
from game_bot.engine import Engine  # noqa: E402
from game_bot.vision import crop, save_image  # noqa: E402


# ---------------------------------------------------------------- 도구
def _button(img, x, y, text, color):
    cv2.rectangle(img, (x, y), (x + 120, y + 50), color, -1)
    cv2.rectangle(img, (x, y), (x + 120, y + 50), (255, 255, 255), 2)
    cv2.putText(img, text, (x + 8, y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)


def blank(seed=0, size=(600, 400)):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 60, size=(size[0], size[1], 3), dtype=np.uint8)


def screen_with(*names, seed=0):
    """names 에 든 버튼이 그려진 화면. start=(100,200) close=(250,40) win=(140,480)"""
    spec = {
        "start": (100, 200, "START", (40, 160, 240)),
        "close": (250, 40, "X", (60, 60, 200)),
        "win": (140, 480, "WIN", (60, 200, 60)),
    }
    img = blank(seed)
    for n in names:
        x, y, t, c = spec[n]
        _button(img, x, y, t, c)
    return img


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeDevice:
    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.actions = []

    def screenshot(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f.copy()

    def tap(self, x, y):
        self.actions.append(("tap", round(x), round(y)))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.actions.append(("swipe", round(x1), round(y1), round(x2), round(y2), duration_ms))

    def long_press(self, x, y, duration_ms=800):
        self.actions.append(("long_press", round(x), round(y), duration_ms))

    def key(self, key):
        self.actions.append(("key", str(key)))

    def text(self, s):
        self.actions.append(("text", s))

    def launch(self, package):
        self.actions.append(("launch", package))

    def stop_app(self, package):
        self.actions.append(("stop_app", package))


@pytest.fixture
def tpl_dir(tmp_path):
    full = screen_with("start", "close", "win")
    save_image(tmp_path / "start.png", crop(full, 100, 200, 120, 50))
    save_image(tmp_path / "close.png", crop(full, 250, 40, 120, 50))
    save_image(tmp_path / "win.png", crop(full, 140, 480, 120, 50))
    return tmp_path


def make_engine(tpl_dir, rules, frames, dry_run=False, **extra):
    sc = S.parse_scenario({"name": "t", "templates_dir": ".", "interval": 1, "rules": rules, **extra}, tpl_dir)
    dev = FakeDevice(frames)
    clock = FakeClock()
    eng = Engine(sc, dev, dry_run=dry_run, sleep=clock.sleep, clock=clock)
    return eng, dev, clock


# ---------------------------------------------------------------- 테스트
def test_tap_match_center(tpl_dir):
    eng, dev, _ = make_engine(
        tpl_dir,
        [{"name": "start", "when": "start.png", "do": [{"tap": "match"}]}],
        [screen_with("start")],
    )
    assert eng.step().name == "start"
    assert dev.actions == [("tap", 160, 225)]


def test_priority_and_cooldown(tpl_dir):
    rules = [
        {"name": "start", "priority": 0, "when": "start.png", "do": [{"tap": "match"}]},
        {"name": "close", "priority": 10, "cooldown": 5, "when": "close.png", "do": [{"tap": "match"}]},
    ]
    eng, dev, clock = make_engine(tpl_dir, rules, [screen_with("start", "close")])
    assert eng.step().name == "close"          # 우선순위 높은 close 먼저
    clock.sleep(1)
    assert eng.step().name == "start"          # close 는 cooldown 중 → start
    clock.sleep(5)
    assert eng.step().name == "close"          # cooldown 지나면 다시 close
    assert dev.actions == [("tap", 310, 65), ("tap", 160, 225), ("tap", 310, 65)]


def test_max_runs_and_idle_limit(tpl_dir):
    rules = [{"name": "start", "max_runs": 2, "when": "start.png", "do": [{"tap": "match"}]}]
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with("start")], idle_limit=3)
    stats = eng.run()
    assert stats.per_rule == {"start": 2}
    assert stats.loops == 5                     # 2회 실행 + idle 3회
    assert "idle_limit" in stats.stop_reason
    assert len(dev.actions) == 2


def test_dry_run_sends_nothing(tpl_dir):
    eng, dev, _ = make_engine(
        tpl_dir,
        [{"name": "start", "when": "start.png", "do": [{"tap": "match"}, {"swipe": [1, 2, 3, 4]}, {"key": "BACK"}]}],
        [screen_with("start")],
        dry_run=True,
    )
    assert eng.step() is not None
    assert dev.actions == []


def test_stop_action_and_stats(tpl_dir):
    rules = [{"name": "start", "when": "start.png", "do": [{"log": "hi"}, {"stop": "끝"}]}]
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with("start")])
    stats = eng.run()
    assert stats.stop_reason == "stop: 끝"
    assert stats.matched == 1 and "start: 1회" in stats.summary()


def test_wait_for_updates_match_target(tpl_dir):
    rules = [{
        "name": "start→win",
        "when": "start.png",
        "do": [{"tap": "match"}, {"wait_for": {"image": "win.png", "timeout": 10, "interval": 1}}, {"tap": "match"}],
    }]
    frames = [screen_with("start"), screen_with("start"), screen_with("start"), screen_with("win")]
    eng, dev, _ = make_engine(tpl_dir, rules, frames)
    assert eng.step() is not None
    assert dev.actions == [("tap", 160, 225), ("tap", 200, 505)]   # 두 번째 탭은 win 중심


def test_wait_for_timeout_aborts_rest(tpl_dir):
    rules = [{
        "name": "r",
        "when": "start.png",
        "do": [{"wait_for": {"image": "win.png", "timeout": 2, "interval": 1}}, {"tap": [1, 1]}],
    }]
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with("start")])
    assert eng.step() is not None
    assert dev.actions == []
    # on_timeout: continue 면 뒤의 동작이 실행됨
    rules[0]["do"][0]["wait_for"]["on_timeout"] = "continue"
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with("start")])
    eng.step()
    assert dev.actions == [("tap", 1, 1)]


def test_wait_gone(tpl_dir):
    rules = [{"name": "r", "when": "close.png", "do": [{"tap": "match"}, {"wait_gone": "close.png"}, {"tap": [7, 7]}]}]
    frames = [screen_with("close"), screen_with("close"), screen_with()]
    eng, dev, _ = make_engine(tpl_dir, rules, frames)
    eng.step()
    assert dev.actions == [("tap", 310, 65), ("tap", 7, 7)]


def test_scaled_coordinates(tpl_dir):
    """시나리오는 400x600 기준, 실제 기기는 800x1200 → 좌표·템플릿 2배."""
    big = cv2.resize(screen_with("start"), (800, 1200), interpolation=cv2.INTER_LINEAR)
    rules = [{
        "name": "start",
        "when": {"image": "start.png", "threshold": 0.7, "region": [50, 150, 250, 200]},
        "do": [{"tap": "match"}, {"tap": {"at": [10, 20], "offset": [1, 1]}}, {"swipe": [0, 0, 100, 100]}],
    }]
    eng, dev, _ = make_engine(tpl_dir, rules, [big], screen=[400, 600])
    assert eng.step() is not None
    (kind, cx, cy), fixed, swipe = dev.actions
    assert kind == "tap" and abs(cx - 320) <= 4 and abs(cy - 450) <= 4
    assert fixed == ("tap", 22, 42)
    assert swipe == ("swipe", 0, 0, 200, 200, 300)


def test_pixel_not_and_all(tpl_dir):
    scr = screen_with("start")
    scr[500, 50] = (0, 0, 255)   # BGR → 빨강
    rules = [
        {"name": "red", "priority": 5,
         "when": {"all": [{"image": "start.png"}, {"pixel": [50, 500], "color": "#ff0000"}]},
         "do": [{"tap": "match"}]},
        {"name": "not_red", "when": {"all": [{"image": "start.png"}, {"not": {"pixel": [50, 500], "color": "#ff0000"}}]},
         "do": [{"tap": [1, 1]}]},
    ]
    eng, dev, _ = make_engine(tpl_dir, rules, [scr])
    assert eng.step().name == "red"
    assert dev.actions == [("tap", 160, 225)]       # all 의 첫 image 매치 중심
    scr2 = screen_with("start")
    eng2, dev2, _ = make_engine(tpl_dir, rules, [scr2])
    assert eng2.step().name == "not_red"


def test_tap_match_without_image_is_skipped(tpl_dir):
    rules = [{"name": "r", "when": "always", "do": [{"tap": "match"}, {"tap": [3, 3]}]}]
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with()])
    assert eng.step() is not None
    assert dev.actions == []                         # 규칙 중단, 뒤 동작도 실행 안 됨


def test_package_launch_and_stop_after(tpl_dir):
    rules = [{"name": "r", "when": "always", "do": [{"key": "BACK"}]}]
    eng, dev, _ = make_engine(tpl_dir, rules, [screen_with()], package="com.x.y", stop_after=4)
    stats = eng.run()
    assert dev.actions[0] == ("launch", "com.x.y")
    assert "stop_after" in stats.stop_reason
    assert stats.loops >= 1


def test_check_reports_missing_templates(tpl_dir):
    rules = [{"name": "r", "when": "missing.png", "do": [{"wait_for": "also_missing.png"}]}]
    eng, _, _ = make_engine(tpl_dir, rules, [screen_with()])
    problems = eng.check()
    assert len(problems) == 2 and all("없습니다" in p for p in problems)
