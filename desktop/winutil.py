"""Llamadas a Win32/DWM que pywebview no expone."""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

LONG_PTR = ctypes.c_ssize_t
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromRect.restype = wintypes.HMONITOR
user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x10, 0x40
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def hwnd_of(window):
    """HWND de una ventana de pywebview (WinForms)."""
    return int(window.native.Handle.ToInt64())


def _dwm_int(hwnd, attr, value):
    v = ctypes.c_int(value)
    dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))


def style_titlebar(hwnd, bgr=0x0017110D, text_bgr=0x00F3EDE6):
    """Barra de título oscura con el color de fondo de la app (Windows 11)."""
    _dwm_int(hwnd, 20, 1)        # modo oscuro
    _dwm_int(hwnd, 35, bgr)      # color de la barra
    _dwm_int(hwnd, 36, text_bgr) # color del texto


def round_corners(hwnd):
    _dwm_int(hwnd, 33, 2)


def exclude_from_capture(hwnd):
    """La ventana no aparece en capturas ni grabaciones (WDA_EXCLUDEFROMCAPTURE)."""
    return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))


def make_tool_window(hwnd):
    """Sin botón en la barra de tareas ni en Alt+Tab."""
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)


def move_topmost(hwnd, x, y, w=0, h=0):
    flags = SWP_NOACTIVATE | SWP_SHOWWINDOW | (0 if w and h else SWP_NOSIZE)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h), flags)


def window_rect(hwnd):
    """(izq, arriba, der, abajo) visibles, sin la sombra invisible de Windows 11."""
    if not user32.IsWindow(hwnd):
        return None
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def outer_rect(hwnd):
    """Rectángulo real de la ventana (el que usa SetWindowPos)."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]


def cursor_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def left_button_down():
    """Botón principal del mouse presionado (respeta el mouse para zurdos)."""
    vk = 0x02 if user32.GetSystemMetrics(23) else 0x01  # SM_SWAPBUTTON
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def point_on_screen(x, y):
    """True si el punto cae dentro de algún monitor conectado."""
    return bool(user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 0))  # DEFAULTTONULL


def is_window(hwnd):
    return bool(user32.IsWindow(hwnd))


def is_minimized(hwnd):
    return bool(user32.IsIconic(hwnd))


def work_area_for(rect):
    """Área de trabajo (sin barra de tareas) del monitor que contiene el rectángulo."""
    r = wintypes.RECT(*rect)
    mon = user32.MonitorFromRect(ctypes.byref(r), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(info))
    w = info.rcWork
    return w.left, w.top, w.right, w.bottom


def primary_work_area():
    return work_area_for((0, 0, 1, 1))


# ------------------------------------------------------------------ papelera

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def send_to_recycle_bin(paths):
    """Mueve archivos a la Papelera de reciclaje (se pueden recuperar). True si funcionó."""
    if not paths:
        return True
    op = SHFILEOPSTRUCTW(wFunc=3,  # FO_DELETE
                         pFrom="\0".join(str(p) for p in paths) + "\0\0",
                         fFlags=0x40 | 0x10 | 0x4 | 0x400)  # ALLOWUNDO|NOCONFIRMATION|SILENT|NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


# --------------------------------------------------------------- portapapeles

kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def copy_text(text):
    data = (text + "\0").encode("utf-16-le")
    for _ in range(10):  # otro programa puede tener el portapapeles abierto un instante
        if user32.OpenClipboard(None):
            break
        kernel32.Sleep(50)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(13, h)  # CF_UNICODETEXT
        return True
    finally:
        user32.CloseClipboard()
