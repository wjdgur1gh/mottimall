"""명령줄 인터페이스.  사용법: python -m game_bot <명령> ...  (또는 설치 후 gamebot <명령>)"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .adb import NO_DEVICE_MSG, AdbDevice, AdbError, connect, list_devices
from .engine import Engine
from .scenario import ScenarioError, load_scenario
from .vision import best_score, crop, draw_matches, find_all, load_image, save_image

PKG_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = PKG_DIR / "screenshots"
TEMPLATE_DIR = PKG_DIR / "templates"

log = logging.getLogger("game_bot")


# ---------------------------------------------------------------- 도우미
def _device(args: argparse.Namespace, fallback_serial: str | None = None) -> AdbDevice:
    """-s 옵션이 우선, 없으면 시나리오의 device, 그것도 없으면 첫 기기."""
    return AdbDevice(serial=args.serial or fallback_serial, adb=args.adb)


def _parse_region(s: str | None) -> tuple[int, int, int, int] | None:
    if not s:
        return None
    parts = [p for p in s.replace(" ", "").split(",") if p]
    if len(parts) != 4:
        raise ValueError(f"--region 은 x,y,w,h 네 숫자여야 합니다: {s!r}")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------- 명령들
def cmd_devices(args: argparse.Namespace) -> int:
    devices = list_devices(args.adb)
    if not devices:
        print("연결된 기기가 없습니다.")
        print(NO_DEVICE_MSG)
        return 1
    hints = {
        "device": "정상 — 사용 가능",
        "unauthorized": "휴대폰 화면의 'USB 디버깅 허용' 창에서 허용을 눌러 주세요",
        "offline": "케이블을 다시 연결하거나 `adb kill-server` 후 재시도",
        "no": "드라이버 문제 — 제조사 USB 드라이버 설치 필요",
    }
    print(f"{'시리얼':<24}{'상태':<14}설명")
    for d in devices:
        print(f"{d.serial:<24}{d.state:<14}{d.description}  ← {hints.get(d.state, '')}".rstrip(" ←"))
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    print(connect(args.address, args.adb))
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    dev = _device(args)
    img = dev.screenshot()
    out = Path(args.out) if args.out else SCREENSHOT_DIR / f"screen_{_timestamp()}.png"
    save_image(out, img)
    h, w = img.shape[:2]
    print(f"저장: {out}  ({w}x{h})")
    return 0


def cmd_size(args: argparse.Namespace) -> int:
    w, h = _device(args).screen_size()
    print(f"{w}x{h}")
    print(f"시나리오 파일에 적을 값:  screen: [{w}, {h}]")
    return 0


def cmd_tap(args: argparse.Namespace) -> int:
    _device(args).tap(args.x, args.y)
    print(f"tap ({args.x:g}, {args.y:g})")
    return 0


def cmd_swipe(args: argparse.Namespace) -> int:
    _device(args).swipe(args.x1, args.y1, args.x2, args.y2, args.ms)
    print(f"swipe ({args.x1:g}, {args.y1:g}) → ({args.x2:g}, {args.y2:g}) {args.ms}ms")
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    _device(args).key(args.key)
    print(f"key {args.key}")
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    _device(args).text(args.text)
    print(f"text {args.text!r}")
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    dev = _device(args)
    if args.launch:
        dev.launch(args.launch)
        print(f"실행: {args.launch}")
    elif args.stop:
        dev.stop_app(args.stop)
        print(f"종료: {args.stop}")
    else:
        print(dev.current_app() or "(현재 앱을 알 수 없음)")
    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    img = load_image(args.image)
    tpl = crop(img, args.x, args.y, args.w, args.h)
    out = Path(args.out) if args.out else TEMPLATE_DIR / f"template_{_timestamp()}.png"
    save_image(out, tpl)
    print(f"템플릿 저장: {out}  ({tpl.shape[1]}x{tpl.shape[0]})")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    tpl = load_image(args.template)
    if args.image:
        screen = load_image(args.image)
        source = str(args.image)
    else:
        dev = _device(args)
        screen = dev.screenshot()
        source = f"기기 {dev.serial} 현재 화면"
    region = _parse_region(args.region)
    label = Path(args.template).stem

    if args.all:
        matches = find_all(screen, tpl, args.threshold, region, args.grayscale, args.scale)
        print(f"{source} 에서 '{label}' {len(matches)}개 발견 (threshold {args.threshold})")
        for i, m in enumerate(matches, 1):
            print(f"  {i}. 중심 {m.center}  영역 {m.region}  점수 {m.score:.3f}")
        shown = matches
    else:
        score, m = best_score(screen, tpl, region, args.grayscale, args.scale)
        found = m is not None and score >= args.threshold
        verdict = "발견 ✓" if found else "미발견 ✗"
        print(f"{source} 에서 '{label}' 최고 점수 {score:.3f} (threshold {args.threshold}) → {verdict}")
        if m is not None:
            print(f"  가장 비슷한 위치: 중심 {m.center}, 영역 {m.region}")
            if not found and score >= 0.5:
                print(f"  힌트: threshold 를 {max(0.5, round(score - 0.05, 2))} 정도로 낮추면 잡힙니다. "
                      "단, 너무 낮추면 다른 버튼을 오인할 수 있습니다.")
        matches = [m] if found and m else []
        shown = [m] if m else []

    if args.mark:
        out = save_image(args.mark, draw_matches(screen, shown, label))
        print(f"표시 이미지 저장: {out}")
    return 0 if matches else 2


def cmd_pick(args: argparse.Namespace) -> int:
    from .pick import Picker

    out_dir = Path(args.out) if args.out else TEMPLATE_DIR
    if args.image:
        img = load_image(args.image)
        grab = None
        print(f"이미지 파일 모드: {args.image}")
    else:
        dev = _device(args)
        grab = dev.screenshot
        img = grab()
        h, w = img.shape[:2]
        print(f"기기 {dev.serial} 화면 캡처 ({w}x{h}). r 키로 다시 캡처할 수 있습니다.")
    print(f"템플릿 저장 폴더: {out_dir}")
    Picker(img, out_dir, grab).run()
    return 0


def _print_rules(sc) -> None:
    print(f"시나리오: {sc.name}")
    print(f"  규칙 {len(sc.rules)}개, 루프 간격 {sc.interval}s, 템플릿 폴더 {sc.templates_dir}")
    if sc.package:
        print(f"  앱 패키지: {sc.package}")
    if sc.screen:
        print(f"  기준 해상도: {sc.screen[0]}x{sc.screen[1]}")
    for r in sc.sorted_rules():
        flag = "" if r.enabled else "  (비활성)"
        cd = f", cooldown {r.cooldown:g}s" if r.cooldown else ""
        mr = f", 최대 {r.max_runs}회" if r.max_runs is not None else ""
        print(f"  [{r.priority:>4}] {r.name}  (동작 {len(r.do)}개{cd}{mr}){flag}")


def cmd_check(args: argparse.Namespace) -> int:
    sc = load_scenario(args.scenario)
    _print_rules(sc)
    engine = Engine(sc, device=None)  # type: ignore[arg-type]  # check() 는 기기를 쓰지 않음
    problems = engine.check()
    names = sc.template_names()
    if problems:
        print(f"\n템플릿 문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        print(f"\n해결: gamebot pick -o \"{sc.templates_dir}\"  로 휴대폰 화면에서 해당 버튼을 잘라 저장하세요.")
        return 1
    print(f"\n템플릿 {len(names)}개 모두 확인됨. 다음 단계:  gamebot run \"{args.scenario}\" --dry-run")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    sc = load_scenario(args.scenario)
    if args.interval is not None:
        sc.interval = args.interval
    dev = _device(args, fallback_serial=sc.device)
    engine = Engine(sc, dev, dry_run=args.dry_run, debug_dir=args.debug_dir)
    problems = engine.check()
    if problems:
        print("템플릿 파일 문제로 실행할 수 없습니다:")
        for p in problems:
            print(f"  - {p}")
        return 1
    w, h = dev.screen_size()
    _print_rules(sc)
    print(f"  기기: {dev.serial} ({w}x{h})" + ("  [DRY-RUN: 터치하지 않고 인식만]" if args.dry_run else ""))
    if sc.screen and (w, h) != tuple(sc.screen):
        print(f"  ※ 기준 해상도와 다름 → 배율 {w / sc.screen[0]:.3f} 적용")
    if args.debug_dir:
        print(f"  매칭 장면 저장: {args.debug_dir}")
    print("Ctrl+C 로 중단합니다.\n")
    stats = engine.run(max_loops=(1 if args.once else args.max_loops))
    print("\n" + stats.summary())
    return 0


# ---------------------------------------------------------------- 파서
def _add_common_tail_options(c: argparse.ArgumentParser) -> None:
    """서브커맨드 뒤에 붙여도 되는 -v / --log (앞에 붙인 값과 합쳐짐)."""
    c.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    c.add_argument("--log", metavar="FILE", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gamebot",
        description="ADB 로 연결한 안드로이드 휴대폰의 게임을 화면 인식으로 자동 플레이한다.",
        epilog="자세한 설명: game_bot/README.md",
    )
    p.add_argument("--version", action="version", version=f"gamebot {__version__}")
    p.add_argument("-s", "--serial", help="기기 시리얼 (gamebot devices 첫 열). 생략하면 첫 번째 기기")
    p.add_argument("--adb", help="adb 실행 파일 경로 (기본: PATH 또는 환경변수 ADB_PATH)")
    p.add_argument("-v", "--verbose", action="store_true", help="규칙별 불일치 사유까지 출력")
    p.add_argument("--log", metavar="FILE", help="로그를 파일에도 기록")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<명령>")

    c = sub.add_parser("devices", help="연결된 기기 목록과 상태")
    c.set_defaults(func=cmd_devices)

    c = sub.add_parser("connect", help="무선 ADB 연결 (예: 192.168.0.10:5555)")
    c.add_argument("address")
    c.set_defaults(func=cmd_connect)

    c = sub.add_parser("screenshot", help="현재 화면을 PNG 로 저장")
    c.add_argument("-o", "--out", help=f"저장 경로 (기본: {SCREENSHOT_DIR}/screen_<시각>.png)")
    c.set_defaults(func=cmd_screenshot)

    c = sub.add_parser("size", help="화면 해상도 (시나리오 screen 값)")
    c.set_defaults(func=cmd_size)

    c = sub.add_parser("tap", help="좌표 탭")
    c.add_argument("x", type=float)
    c.add_argument("y", type=float)
    c.set_defaults(func=cmd_tap)

    c = sub.add_parser("swipe", help="스와이프")
    for n in ("x1", "y1", "x2", "y2"):
        c.add_argument(n, type=float)
    c.add_argument("--ms", type=int, default=300, help="지속 시간(ms), 기본 300")
    c.set_defaults(func=cmd_swipe)

    c = sub.add_parser("key", help="키 입력 (BACK, HOME, ENTER, 키코드 숫자 등)")
    c.add_argument("key")
    c.set_defaults(func=cmd_key)

    c = sub.add_parser("text", help="영문/숫자 텍스트 입력")
    c.add_argument("text")
    c.set_defaults(func=cmd_text)

    c = sub.add_parser("app", help="현재 앱 확인 / 실행 / 종료")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--launch", metavar="PACKAGE", help="패키지 실행 (예: com.yunbu.xgz.free.kr)")
    g.add_argument("--stop", metavar="PACKAGE", help="패키지 강제 종료")
    c.set_defaults(func=cmd_app)

    c = sub.add_parser("crop", help="스크린샷 파일에서 영역을 잘라 템플릿 저장")
    c.add_argument("image")
    for n in ("x", "y", "w", "h"):
        c.add_argument(n, type=int)
    c.add_argument("-o", "--out", help="저장 경로 (.png)")
    c.set_defaults(func=cmd_crop)

    c = sub.add_parser("find", help="템플릿이 화면(또는 이미지 파일)에서 어디에, 몇 점으로 매칭되는지 확인")
    c.add_argument("template", help="템플릿 PNG")
    c.add_argument("--image", help="기기 대신 이 스크린샷 파일에서 찾기")
    c.add_argument("--threshold", type=float, default=0.8)
    c.add_argument("--region", help="x,y,w,h 로 탐색 범위 제한")
    c.add_argument("--scale", type=float, default=1.0, help="템플릿 배율 (다른 해상도 기기일 때)")
    c.add_argument("--grayscale", action="store_true")
    c.add_argument("--all", action="store_true", help="threshold 이상인 모든 위치")
    c.add_argument("--mark", metavar="OUT.png", help="매칭 위치를 표시한 이미지를 저장")
    c.set_defaults(func=cmd_find)

    c = sub.add_parser("pick", help="GUI 창에서 좌표 찍기 / 드래그로 템플릿 잘라 저장")
    c.add_argument("--image", help="기기 대신 이 스크린샷 파일을 열기")
    c.add_argument("-o", "--out", help=f"템플릿 저장 폴더 (기본: {TEMPLATE_DIR})")
    c.set_defaults(func=cmd_pick)

    c = sub.add_parser("check", help="시나리오 문법과 템플릿 파일 검사 (기기 불필요)")
    c.add_argument("scenario")
    c.set_defaults(func=cmd_check)

    c = sub.add_parser("run", help="시나리오 실행")
    c.add_argument("scenario")
    c.add_argument("--dry-run", action="store_true", help="터치/키 입력 없이 인식 결과만 로그로 출력")
    c.add_argument("--once", action="store_true", help="한 루프만 실행")
    c.add_argument("--max-loops", type=int, help="N 루프 후 종료")
    c.add_argument("--interval", type=float, help="루프 간격(초) 덮어쓰기")
    c.add_argument("--debug-dir", metavar="DIR", help="규칙이 매칭된 장면을 표시해 이 폴더에 저장")
    c.set_defaults(func=cmd_run)

    for name, sp in sub.choices.items():
        _add_common_tail_options(sp)
    return p


def _setup_logging(verbose: bool, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose, args.log)
    try:
        return int(args.func(args) or 0)
    except (AdbError, ScenarioError, FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"\n오류: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단됨")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
