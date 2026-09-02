#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DuckStation 구동 헬퍼 (Windows 전용).

emucap의 Mednafen 어댑터는 이 호스트에 빌드돼 있지 않다. 런타임 시각 검증은
사용자 PC에 설치된 DuckStation을 띄우고, DuckStation 자신의 스크린샷 핫키(F10)로
캡처한다. PrintWindow(D3D) 캡처가 검게 나오는 문제를 피한다.

주의: 창을 포그라운드로 올리고 키를 보내므로 사람의 입력과 겹친다.
"""
from __future__ import annotations

import argparse
import ctypes
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

EXE = Path(r"C:\Users\blari\Desktop\Duck Station\duckstation-qt-x64-ReleaseLTCG.exe")
SHOTS = Path(r"C:\Users\blari\Documents\DuckStation\screenshots")

user32 = ctypes.WinDLL("user32", use_last_error=True)

VK = {
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "cross": 0x4B,      # K
    "circle": 0x4C,     # L
    "square": 0x4A,     # J
    "triangle": 0x49,   # I
    "start": 0x0D,      # Return
    "select": 0x08,     # Backspace
    "f10": 0x79, "space": 0x20, "escape": 0x1B, "tab": 0x09,
}

KEYEVENTF_KEYUP = 0x0002


def find_window(pid: int) -> int | None:
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            if area > 10000:
                found.append((area, hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return max(found)[1] if found else None


def focus(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)


def key(hwnd: int, name: str, hold: float = 0.08, after: float = 0.20) -> None:
    focus(hwnd)
    vk = VK[name]
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(after)


def shot(hwnd: int, out: Path, label: str) -> Path | None:
    before = {p.name for p in SHOTS.glob("*.png")}
    key(hwnd, "f10", after=1.2)
    for _ in range(20):
        new = [p for p in SHOTS.glob("*.png") if p.name not in before]
        if new:
            newest = max(new, key=lambda p: p.stat().st_mtime)
            out.mkdir(parents=True, exist_ok=True)
            dst = out / f"{label}.png"
            shutil.copyfile(newest, dst)
            return dst
        time.sleep(0.3)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cue", required=True)
    ap.add_argument("--out", default="analysis/emulator")
    ap.add_argument("--label", default="run")
    ap.add_argument("--boot-seconds", type=float, default=20.0)
    ap.add_argument("--script", default="", help="쉼표 구분: wait:3, key:start, shot:title ...")
    args = ap.parse_args()

    proc = subprocess.Popen([str(EXE), "-batch", "-fastboot", args.cue])
    print("duckstation pid", proc.pid)
    hwnd = None
    deadline = time.time() + 30
    while time.time() < deadline and hwnd is None:
        time.sleep(1.0)
        hwnd = find_window(proc.pid)
    if hwnd is None:
        proc.terminate()
        raise SystemExit("DuckStation 창을 찾지 못했다")
    print("hwnd", hwnd)
    time.sleep(args.boot_seconds)

    out = Path(args.out)
    for step in [s.strip() for s in args.script.split(",") if s.strip()]:
        op, _, val = step.partition(":")
        if op == "wait":
            time.sleep(float(val))
        elif op == "key":
            key(hwnd, val)
        elif op == "keyx":          # key:N번 반복 -> keyx:name*N
            name, _, n = val.partition("*")
            for _ in range(int(n or 1)):
                key(hwnd, name)
        elif op == "shot":
            p = shot(hwnd, out, f"{args.label}_{val}")
            print("shot:", p)
        else:
            raise SystemExit(f"unknown step {step}")
    print("done; leaving emulator running (pid %d)" % proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
