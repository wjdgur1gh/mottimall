import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from game_bot.vision import (  # noqa: E402
    Match, best_score, crop, draw_matches, find_all, find_template, load_image,
    parse_color, pixel_color, pixel_matches, save_image,
)


def _button(img, x, y, text="START"):
    cv2.rectangle(img, (x, y), (x + 120, y + 50), (40, 160, 240), -1)
    cv2.rectangle(img, (x, y), (x + 120, y + 50), (255, 255, 255), 2)
    cv2.putText(img, text, (x + 10, y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)


def make_screen(seed=0, buttons=((100, 200),)):
    rng = np.random.default_rng(seed)
    screen = rng.integers(0, 60, size=(600, 400, 3), dtype=np.uint8)
    for x, y in buttons:
        _button(screen, x, y)
    return screen


def test_find_template_exact_position():
    screen = make_screen()
    tpl = crop(screen, 100, 200, 120, 50)
    m = find_template(screen, tpl, threshold=0.9)
    assert m is not None
    assert (m.x, m.y, m.w, m.h) == (100, 200, 120, 50)
    assert m.center == (160, 225)
    assert m.score > 0.99


def test_not_found_when_button_absent():
    tpl = crop(make_screen(), 100, 200, 120, 50)
    other = make_screen(seed=1, buttons=())
    assert find_template(other, tpl, threshold=0.8) is None
    score, m = best_score(other, tpl)
    assert score < 0.5 and m is not None


def test_region_limits_search():
    screen = make_screen()
    tpl = crop(screen, 100, 200, 120, 50)
    assert find_template(screen, tpl, 0.9, region=(0, 0, 400, 150)) is None
    m = find_template(screen, tpl, 0.9, region=(50, 150, 250, 200))
    assert m is not None and (m.x, m.y) == (100, 200)   # 절대 좌표로 돌아와야 함
    # 화면 밖으로 벗어난 region 도 잘려서 동작
    assert find_template(screen, tpl, 0.9, region=(90, 190, 10000, 10000)) is not None


def test_find_all_two_buttons():
    screen = make_screen(buttons=((100, 200), (200, 450)))
    tpl = crop(screen, 100, 200, 120, 50)
    ms = find_all(screen, tpl, threshold=0.9)
    assert len(ms) == 2
    assert {(m.x, m.y) for m in ms} == {(100, 200), (200, 450)}
    assert ms[0].score >= ms[1].score


def test_scaled_template_on_smaller_screen():
    screen = make_screen()
    tpl = crop(screen, 100, 200, 120, 50)
    small = cv2.resize(screen, (200, 300), interpolation=cv2.INTER_AREA)
    m = find_template(small, tpl, threshold=0.6, scale=0.5)
    assert m is not None
    cx, cy = m.center
    assert abs(cx - 80) <= 2 and abs(cy - 112) <= 2


def test_grayscale_mode_and_large_template():
    screen = make_screen()
    tpl = crop(screen, 100, 200, 120, 50)
    assert find_template(screen, tpl, 0.9, grayscale=True) is not None
    big = np.zeros((700, 500, 3), np.uint8)
    big[::7, ::5] = 255
    assert find_template(screen, big) is None   # 템플릿이 화면보다 크면 None


def test_uniform_template_rejected():
    screen = make_screen()
    with pytest.raises(ValueError):
        find_template(screen, np.zeros((20, 20, 3), np.uint8))


def test_pixel_helpers():
    screen = np.zeros((50, 50, 3), np.uint8)
    screen[10, 20] = (30, 136, 255)   # BGR
    assert pixel_color(screen, 20, 10) == (255, 136, 30)
    assert pixel_matches(screen, 20, 10, (250, 130, 35), tolerance=10)
    assert not pixel_matches(screen, 20, 10, (200, 136, 30), tolerance=10)
    with pytest.raises(ValueError):
        pixel_color(screen, 999, 0)


def test_parse_color():
    assert parse_color("#ff8800") == (255, 136, 0)
    assert parse_color("FF8800") == (255, 136, 0)
    assert parse_color([1, 2, 3]) == (1, 2, 3)
    for bad in ("#ff88", "zzzzzz", [1, 2], [0, 0, 300]):
        with pytest.raises(ValueError):
            parse_color(bad)


def test_save_and_load_with_korean_path(tmp_path):
    screen = make_screen()
    p = tmp_path / "템플릿 폴더" / "시작.png"
    save_image(p, screen)
    loaded = load_image(p)
    assert loaded.shape == screen.shape
    assert np.array_equal(loaded, screen)
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "없음.png")


def test_crop_bounds_and_draw():
    screen = make_screen()
    assert crop(screen, 390, 590, 100, 100).shape == (10, 10, 3)
    with pytest.raises(ValueError):
        crop(screen, 500, 700, 10, 10)
    out = draw_matches(screen, [Match(100, 200, 120, 50, 0.97)], "start")
    assert out.shape == screen.shape and not np.array_equal(out, screen)
