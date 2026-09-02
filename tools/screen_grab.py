#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면 DC에서 창 영역을 잘라 캡처한다(D3D 창도 화면 합성본이라 잡힌다)."""
from __future__ import annotations
import ctypes, sys
from ctypes import wintypes
from pathlib import Path
from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.GetWindowDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

SRCCOPY = 0x00CC0020

def list_windows(pid=None):
    out=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd,_):
        wpid=wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if pid and wpid.value!=pid: return True
        if not user32.IsWindowVisible(hwnd): return True
        r=wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        n=user32.GetWindowTextLengthW(hwnd); buf=ctypes.create_unicode_buffer(n+1)
        user32.GetWindowTextW(hwnd, buf, n+1)
        out.append((hwnd, wpid.value, (r.left,r.top,r.right,r.bottom), buf.value))
        return True
    user32.EnumWindows(cb,0)
    return out

def grab(hwnd, path):
    r=wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w,h=r.right-r.left, r.bottom-r.top
    screen=user32.GetDC(0)
    mem=gdi32.CreateCompatibleDC(screen)
    bmp=gdi32.CreateCompatibleBitmap(screen,w,h)
    gdi32.SelectObject(mem,bmp)
    gdi32.BitBlt(mem,0,0,w,h,screen,r.left,r.top,SRCCOPY)
    class BIH(ctypes.Structure):
        _fields_=[("size",wintypes.DWORD),("width",wintypes.LONG),("height",wintypes.LONG),
                  ("planes",wintypes.WORD),("bits",wintypes.WORD),("comp",wintypes.DWORD),
                  ("sizeimg",wintypes.DWORD),("xppm",wintypes.LONG),("yppm",wintypes.LONG),
                  ("used",wintypes.DWORD),("imp",wintypes.DWORD)]
    bi=BIH(); bi.size=ctypes.sizeof(BIH); bi.width=w; bi.height=-h; bi.planes=1; bi.bits=32
    buf=ctypes.create_string_buffer(w*h*4)
    gdi32.GetDIBits(mem,bmp,0,h,buf,ctypes.byref(bi),0)
    img=Image.frombuffer("RGBA",(w,h),buf,"raw","BGRA",0,1).convert("RGB")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem); user32.ReleaseDC(0,screen)
    return w,h

if __name__=="__main__":
    if sys.argv[1]=="list":
        pid=int(sys.argv[2]) if len(sys.argv)>2 else None
        for hwnd,p,rect,title in list_windows(pid):
            print(hwnd,p,rect,repr(title))
    else:
        hwnd=int(sys.argv[1]); print(grab(hwnd, sys.argv[2]))
