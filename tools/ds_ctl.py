#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""이미 떠 있는 DuckStation 창에 붙어 키를 보내고 화면을 캡처한다."""
from __future__ import annotations
import ctypes, sys, time
from ctypes import wintypes
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen_grab import grab, list_windows

user32 = ctypes.WinDLL("user32", use_last_error=True)
VK = {"up":0x26,"down":0x28,"left":0x25,"right":0x27,
      "cross":0x4B,"circle":0x4C,"square":0x4A,"triangle":0x49,
      "start":0x0D,"select":0x08,"f10":0x79,"space":0x20,"escape":0x1B,"tab":0x09}
KEYUP=0x0002
EXTENDED=0x0001
MAPVK_VK_TO_VSC=0
# 방향키/Insert 계열은 확장 키다. 확장 플래그가 없으면 스캔코드가 숫자패드로 잡혀
# DuckStation 바인딩(Keyboard/Up 등)에 도달하지 않는다.
EXT_VKS={0x25,0x26,0x27,0x28,0x2D,0x2E,0x24,0x23,0x21,0x22,0x2C,0x90,0x6F,0x0D_0 if False else 0x5B}

def find_game():
    for hwnd,pid,rect,title in list_windows():
        if "スーパーロボット" in title or "SUPER ROBOT" in title.upper():
            return hwnd
    return None

_focused=set()
def focus(hwnd, force=False):
    if hwnd in _focused and not force:
        return
    user32.ShowWindow(hwnd,9); user32.SetForegroundWindow(hwnd); time.sleep(0.35)
    _focused.add(hwnd)

def key(hwnd,name,hold=0.10,after=0.25):
    focus(hwnd)
    vk=VK[name]; sc=user32.MapVirtualKeyW(vk,MAPVK_VK_TO_VSC)
    flags=EXTENDED if vk in EXT_VKS else 0
    user32.keybd_event(vk,sc,flags,0); time.sleep(hold)
    user32.keybd_event(vk,sc,flags|KEYUP,0); time.sleep(after)

def main():
    hwnd=find_game()
    if not hwnd: raise SystemExit("game window not found")
    out=Path(sys.argv[1]) if len(sys.argv)>1 else Path("analysis/emulator")
    label=sys.argv[2] if len(sys.argv)>2 else "s"
    steps=[s.strip() for s in (sys.argv[3] if len(sys.argv)>3 else "").split(",") if s.strip()]
    print("hwnd",hwnd)
    for st in steps:
        op,_,val=st.partition(":")
        if op=="wait": time.sleep(float(val))
        elif op=="key": key(hwnd,val)
        elif op=="rep":
            name,_,n=val.partition("*")
            for _ in range(int(n)): key(hwnd,name)
        elif op=="shot":
            out.mkdir(parents=True,exist_ok=True)
            p=out/f"{label}_{val}.png"; grab(hwnd,str(p)); print("shot",p)
        else: raise SystemExit("bad step "+st)

if __name__=="__main__": main()
