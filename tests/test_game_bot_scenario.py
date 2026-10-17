import textwrap

import pytest

yaml = pytest.importorskip("yaml")

from game_bot import scenario as S  # noqa: E402


def _load(text, tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return S.load_scenario(p)


def test_full_scenario_parses(tmp_path):
    sc = _load(
        """
        name: 테스트
        package: com.example.game
        templates_dir: tpl
        interval: 0.5
        screen: [1080, 2400]
        stop_after: 60
        idle_limit: 10
        rules:
          - name: 닫기
            priority: 100
            cooldown: 2
            max_runs: 5
            when: { image: close.png, threshold: 0.9, region: [0, 0, 1080, 300], grayscale: true }
            do:
              - tap: match
              - wait: 0.5
          - name: 복합
            when:
              all:
                - image: a.png
                - any: [ { image: b.png }, { pixel: [10, 20], color: "#ff0000", tolerance: 30 } ]
                - not: { image: c.png }
            do:
              - tap: { at: match, offset: [0, -20], times: 2, interval: 0.2 }
              - tap: [100, 200]
              - long_press: { x: 5, y: 6, duration_ms: 1000 }
              - swipe: [1, 2, 3, 4, 500]
              - swipe: { from: [0, 0], to: [10, 10] }
              - key: BACK
              - text: hello
              - wait_for: { image: d.png, timeout: 3, interval: 0.1, on_timeout: continue }
              - wait_gone: e.png
              - log: 메시지
              - launch: com.example.game
              - stop_app: com.example.game
              - screenshot: shots/%Y.png
              - stop: 끝
          - name: 축약
            when: start.png
            do: stop
          - name: 항상
            enabled: false
            when: always
            do:
              - stop
        """,
        tmp_path,
    )
    assert sc.name == "테스트" and sc.package == "com.example.game"
    assert sc.templates_dir == (tmp_path / "tpl").resolve()
    assert sc.screen == (1080, 2400) and sc.interval == 0.5
    assert sc.stop_after == 60 and sc.idle_limit == 10
    assert [r.name for r in sc.sorted_rules()] == ["닫기", "복합", "축약", "항상"]

    r0 = sc.rules[0]
    assert isinstance(r0.when, S.ImageCond)
    assert r0.when.threshold == 0.9 and r0.when.region == (0, 0, 1080, 300) and r0.when.grayscale
    assert r0.cooldown == 2 and r0.max_runs == 5 and r0.priority == 100
    assert isinstance(r0.do[0], S.TapAction) and r0.do[0].target == "match"
    assert isinstance(r0.do[1], S.WaitAction) and r0.do[1].seconds == 0.5

    r1 = sc.rules[1]
    assert isinstance(r1.when, S.AllCond) and len(r1.when.items) == 3
    assert isinstance(r1.when.items[1], S.AnyCond)
    px = r1.when.items[1].items[1]
    assert isinstance(px, S.PixelCond) and (px.x, px.y, px.color, px.tolerance) == (10, 20, (255, 0, 0), 30)
    assert isinstance(r1.when.items[2], S.NotCond)
    kinds = [type(a) for a in r1.do]
    assert kinds == [
        S.TapAction, S.TapAction, S.LongPressAction, S.SwipeAction, S.SwipeAction, S.KeyAction,
        S.TextAction, S.WaitForAction, S.WaitForAction, S.LogAction, S.LaunchAction,
        S.StopAppAction, S.ScreenshotAction, S.StopAction,
    ]
    t0 = r1.do[0]
    assert t0.offset == (0, -20) and t0.times == 2 and t0.interval == 0.2
    assert r1.do[1].target == (100, 200)
    assert r1.do[2].target == (5, 6) and r1.do[2].duration_ms == 1000
    assert (r1.do[3].x1, r1.do[3].y2, r1.do[3].duration_ms) == (1, 4, 500)
    assert r1.do[4].duration_ms == 300
    wf = r1.do[7]
    assert wf.timeout == 3 and wf.interval == 0.1 and wf.on_timeout == "continue" and not wf.gone
    assert r1.do[8].gone and isinstance(r1.do[8].cond, S.ImageCond)
    assert r1.do[13].reason == "끝"

    assert isinstance(sc.rules[2].when, S.ImageCond) and sc.rules[2].when.name == "start.png"
    assert isinstance(sc.rules[2].do[0], S.StopAction)
    assert isinstance(sc.rules[3].when, S.AlwaysCond) and not sc.rules[3].enabled

    assert sc.template_names() == ["close.png", "a.png", "b.png", "c.png", "d.png", "e.png", "start.png"]
    assert sc.template_path("a.png") == sc.templates_dir / "a.png"


def test_screen_string_form(tmp_path):
    sc = _load("rules: [{name: r, when: always, do: stop}]\nscreen: 720x1600\n", tmp_path)
    assert sc.screen == (720, 1600)


@pytest.mark.parametrize(
    "body, msg",
    [
        ("rules: []", "규칙이 하나 이상"),
        ("rules: [{name: r, do: stop}]", "when"),
        ("rules: [{name: r, when: always}]", "do"),
        ("rules: [{name: r, when: always, do: stop, bogus: 1}]", "알 수 없는 항목"),
        ("rules: [{name: r, when: {image: a.png, foo: 1}, do: stop}]", "알 수 없는 항목"),
        ("rules: [{name: r, when: {image: a.png, threshold: 1.5}, do: stop}]", "threshold"),
        ("rules: [{name: r, when: {image: a.png, region: [1, 2, 3]}, do: stop}]", "region"),
        ("rules: [{name: r, when: {pixel: [1, 2]}, do: stop}]", "color"),
        ("rules: [{name: r, when: {pixel: [1, 2], color: '#12'}, do: stop}]", "색상"),
        ("rules: [{name: r, when: {image: a.png, pixel: [1, 2]}, do: stop}]", "정확히 하나"),
        ("rules: [{name: r, when: always, do: [{tap: 'there'}]}]", "match"),
        ("rules: [{name: r, when: always, do: [{swipe: [1, 2, 3]}]}]", "swipe"),
        ("rules: [{name: r, when: always, do: [{wait: -1}]}]", "wait"),
        ("rules: [{name: r, when: always, do: [{wait_for: a.png, on_timeout: explode}]}]", "on_timeout"),
        ("rules: [{name: r, when: always, do: [{jump: 1}]}]", "정확히 하나"),
        ("rules: [{name: r, when: always, do: stop}, {name: r, when: always, do: stop}]", "중복"),
        ("rules: [{name: r, when: always, do: stop}]\nunknown_top: 1", "알 수 없는 항목"),
        ("rules: [{name: r, when: always, do: stop}]\nscreen: [1]", "screen"),
        ("rules: [{name: r, when: always, do: stop, cooldown: -1}]", "cooldown"),
    ],
)
def test_errors(tmp_path, body, msg):
    with pytest.raises(S.ScenarioError) as ei:
        _load(body, tmp_path)
    assert msg in str(ei.value)


def test_yaml_syntax_error_and_missing_file(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("rules: [\n  - name: x\n", encoding="utf-8")
    with pytest.raises(S.ScenarioError) as ei:
        S.load_scenario(p)
    assert "YAML" in str(ei.value)
    with pytest.raises(S.ScenarioError):
        S.load_scenario(tmp_path / "nope.yaml")


def test_shipped_scenarios_parse():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "game_bot" / "scenarios"
    for f in sorted(root.glob("*.yaml")):
        sc = S.load_scenario(f)
        assert sc.rules, f
    cheonji = S.load_scenario(root / "cheonji.yaml")
    assert cheonji.package == "com.yunbu.xgz.free.kr"
    assert cheonji.templates_dir.name == "cheonji"
