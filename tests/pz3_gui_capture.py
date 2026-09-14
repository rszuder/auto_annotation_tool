"""Capture just the requested Tk window on Windows, even when obscured."""
import ctypes
from ctypes import wintypes
from PIL import Image


def capture_window(widget, destination):
    widget.update_idletasks()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]

    class Header(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
            ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
            ("image_size", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
            ("colors", wintypes.DWORD), ("important", wintypes.DWORD),
        ]

    hwnd = user32.GetAncestor(widget.winfo_id(), 2)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    source_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(source_dc)
    bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            raise RuntimeError("PrintWindow failed")
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width*height*4)
        gdi32.SelectObject(memory_dc, previous)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            raise RuntimeError("GetDIBits failed")
        Image.frombuffer("RGB", (width, height), buffer.raw, "raw", "BGRX", 0, 1).save(destination)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, source_dc)

