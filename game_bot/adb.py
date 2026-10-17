"""ADB(Android Debug Bridge) 래퍼.

adb 실행 파일을 subprocess 로 호출한다. 별도 파이썬 ADB 라이브러리 없이
Android platform-tools 만 있으면 동작한다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np

log = logging.getLogger("game_bot.adb")


class AdbError(RuntimeError):
    """adb 를 찾지 못했거나 명령이 실패했을 때."""


# adb 가 PATH 에 없을 때 흔히 설치되는 위치들
_CANDIDATES = [
    "adb",
    r"C:\platform-tools\adb.exe",
    r"C:\adb\adb.exe",
    r"C:\Android\platform-tools\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\Downloads\platform-tools\adb.exe"),
    os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
    os.path.expanduser("~/platform-tools/adb"),
    "/opt/platform-tools/adb",
]

ADB_NOT_FOUND_MSG = (
    "adb 를 찾을 수 없습니다.\n"
    "  1) https://developer.android.com/tools/releases/platform-tools 에서 "
    "'SDK Platform-Tools for Windows' 를 내려받아 압축을 풉니다.\n"
    "  2) 푼 폴더(platform-tools)를 C:\\platform-tools 로 옮기거나,\n"
    "  3) 환경변수 ADB_PATH 에 adb.exe 전체 경로를 넣거나, --adb 옵션으로 경로를 지정하세요."
)


def find_adb(explicit: str | None = None) -> str:
    """adb 실행 파일 경로. 우선순위: 인자 > 환경변수 ADB_PATH > PATH > 흔한 설치 위치."""
    for cand in [explicit, os.environ.get("ADB_PATH"), *_CANDIDATES]:
        if not cand:
            continue
        found = shutil.which(cand)
        if found:
            return found
        if os.path.isfile(cand):
            return cand
    raise AdbError(ADB_NOT_FOUND_MSG)


def _run(cmd: Sequence[str], timeout: float = 30, binary: bool = False) -> str | bytes:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise AdbError(f"adb 실행 실패: {cmd[0]} ({e})") from e
    except subprocess.TimeoutExpired as e:
        raise AdbError(f"adb 명령이 {timeout}초 안에 끝나지 않았습니다: {' '.join(cmd)}") from e
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise AdbError(f"adb 명령 실패(code {proc.returncode}): {' '.join(cmd)}\n{err}")
    return proc.stdout if binary else proc.stdout.decode(errors="replace")


@dataclass
class DeviceInfo:
    serial: str
    state: str  # device / offline / unauthorized / no permissions ...
    description: str = ""

    def __str__(self) -> str:
        return f"{self.serial}\t{self.state}\t{self.description}".rstrip()


def list_devices(adb: str | None = None) -> list[DeviceInfo]:
    """`adb devices -l` 결과를 파싱한다."""
    out = _run([find_adb(adb), "devices", "-l"])
    devices: list[DeviceInfo] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append(DeviceInfo(parts[0], parts[1], " ".join(parts[2:])))
    return devices


def connect(host_port: str, adb: str | None = None) -> str:
    """무선 ADB 연결 (`adb connect 192.168.0.10:5555`)."""
    return _run([find_adb(adb), "connect", host_port], timeout=20).strip()


NO_DEVICE_MSG = (
    "연결된 안드로이드 기기가 없습니다.\n"
    "  - USB 케이블로 연결하고 휴대폰에서 'USB 디버깅' 이 켜져 있는지 확인하세요 "
    "(설정 > 개발자 옵션).\n"
    "  - 휴대폰 화면에 'USB 디버깅을 허용하시겠습니까?' 창이 뜨면 '항상 허용' 으로 승인하세요.\n"
    "  - 상태가 'unauthorized' 면 위 승인 창을 아직 누르지 않은 것이고, "
    "'offline' 이면 케이블을 뽑았다 다시 꽂아 보세요.\n"
    "  - `gamebot devices` 로 현재 상태를 볼 수 있습니다."
)


class AdbDevice:
    """특정 기기(serial)에 대한 adb 명령 묶음."""

    def __init__(self, serial: str | None = None, adb: str | None = None):
        self.adb = find_adb(adb)
        self.serial = serial or self._pick_default()
        self._size: tuple[int, int] | None = None

    # ---- 연결 ----
    def _pick_default(self) -> str:
        devices = list_devices(self.adb)
        ready = [d for d in devices if d.state == "device"]
        if not ready:
            detail = "\n".join(f"    {d}" for d in devices) if devices else "    (목록 비어 있음)"
            raise AdbError(NO_DEVICE_MSG + "\n  현재 adb devices 결과:\n" + detail)
        if len(ready) > 1:
            log.warning("기기가 %d대 연결되어 있어 첫 번째(%s)를 사용합니다. -s 옵션으로 지정 가능.",
                        len(ready), ready[0].serial)
        return ready[0].serial

    def _cmd(self, *args: str) -> list[str]:
        return [self.adb, "-s", self.serial, *args]

    def shell(self, *args: str, timeout: float = 30) -> str:
        return _run(self._cmd("shell", *args), timeout=timeout)  # type: ignore[return-value]

    # ---- 화면 ----
    def screenshot(self) -> np.ndarray:
        """현재 화면을 BGR numpy 배열로 반환."""
        raw: bytes = _run(self._cmd("exec-out", "screencap", "-p"), timeout=25, binary=True)  # type: ignore[assignment]
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None and b"\r\n" in raw:
            # 일부 구형 기기/윈도우 adb 조합은 PNG 안의 \n 을 \r\n 으로 바꿔 보낸다
            img = cv2.imdecode(np.frombuffer(raw.replace(b"\r\n", b"\n"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError(
                "스크린샷을 읽지 못했습니다. 게임이 화면 캡처를 막고 있거나(보안 설정), "
                "기기가 잠금 화면일 수 있습니다."
            )
        return img

    def screen_size(self) -> tuple[int, int]:
        """(가로, 세로) 픽셀. `wm size` 의 Override 값이 있으면 그것을 우선."""
        if self._size is None:
            out = self.shell("wm", "size")
            phys = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
            over = re.search(r"Override size:\s*(\d+)x(\d+)", out)
            m = over or phys
            if not m:
                h, w = self.screenshot().shape[:2]
                self._size = (w, h)
            else:
                self._size = (int(m.group(1)), int(m.group(2)))
        return self._size

    # ---- 입력 ----
    def tap(self, x: float, y: float) -> None:
        self.shell("input", "tap", str(int(round(x))), str(int(round(y))))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        self.shell("input", "swipe", *(str(int(round(v))) for v in (x1, y1, x2, y2)), str(int(duration_ms)))

    def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        self.swipe(x, y, x, y, duration_ms)

    def key(self, key: str | int) -> None:
        """키 이벤트. 예: BACK, HOME, ENTER, 4(=BACK 키코드)."""
        k = str(key).strip()
        if not k.isdigit() and not k.startswith("KEYCODE_"):
            k = "KEYCODE_" + k.upper()
        self.shell("input", "keyevent", k)

    def text(self, s: str) -> None:
        """영문/숫자 입력. `adb shell input text` 는 한글을 지원하지 않는다."""
        if any(ord(ch) > 127 for ch in s):
            log.warning("input text 는 ASCII 만 지원합니다. 한글 등은 입력되지 않습니다: %r", s)
        escaped = s.replace(" ", "%s")
        for ch in "\\()<>|;&*~\"'$":
            escaped = escaped.replace(ch, "\\" + ch)
        self.shell("input", "text", escaped)

    # ---- 앱 ----
    def launch(self, package: str) -> None:
        self.shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)

    def stop_app(self, package: str) -> None:
        self.shell("am", "force-stop", package)

    def current_app(self) -> str:
        """현재 포그라운드 앱의 패키지명 (못 찾으면 빈 문자열)."""
        try:
            out = self.shell("dumpsys", "window", timeout=20)
        except AdbError:
            return ""
        for line in out.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                m = re.search(r"\s([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+", line)
                if m:
                    return m.group(1)
        return ""

    def __repr__(self) -> str:
        return f"AdbDevice(serial={self.serial!r})"
