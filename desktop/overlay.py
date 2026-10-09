"""Borde rojo punteado alrededor de lo que se graba.

Ventana Win32 propia (en su hilo): transparente a los clics y excluida de la captura,
así que nunca aparece en el video. Si se graba una ventana, la sigue cuando se mueve.
"""

import ctypes
import threading
from ctypes import wintypes

import winutil

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.BeginPaint.restype = wintypes.HDC
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WM_DESTROY, WM_CLOSE, WM_PAINT, WM_ERASEBKGND, WM_TIMER = 0x2, 0x10, 0xF, 0x14, 0x113
WS_POPUP = 0x80000000
WS_EX = 0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000  # LAYERED|TRANSPARENT|TOPMOST|TOOLWINDOW|NOACTIVATE
KEY = 0x00FF00FF                     # magenta = transparente
RED, AMBER = 0x004444EF, 0x000B9EF5  # #EF4444 y #F59E0B en formato BGR
PAD, THICK, DASH, GAP = 3, 3, 14, 8


class BorderOverlay:
    def __init__(self, rect=None, target_hwnd=None):
        """rect = (izq, arriba, der, abajo) de un monitor, o target_hwnd de una ventana."""
        self._rect, self._target = rect, target_hwnd
        self._paused = False
        self._last = None
        self.hwnd = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # referencia viva mientras exista la ventana
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(3)

    # ------------------------------------------------------------ API pública
    def set_paused(self, paused):
        self._paused = paused
        if self.hwnd:
            user32.InvalidateRect(self.hwnd, None, True)

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ----------------------------------------------------------------- interno
    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls = f"TranscriptorBorder{id(self)}"
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc,
                         hInstance=hinst, lpszClassName=cls)
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(WS_EX, cls, "", WS_POPUP, 0, 0, 1, 1,
                                           None, None, hinst, None)
        user32.SetLayeredWindowAttributes(self.hwnd, KEY, 0, 1)  # LWA_COLORKEY
        winutil.exclude_from_capture(self.hwnd)
        self._place()
        user32.SetTimer(self.hwnd, 1, 200, None)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnregisterClassW(cls, hinst)

    def _place(self):
        if self._target:
            if not winutil.is_window(self._target) or winutil.is_minimized(self._target):
                user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
                self._last = None
                return
            left, top, right, bottom = winutil.window_rect(self._target)
            rect = (left - PAD, top - PAD, right + PAD, bottom + PAD)
        else:
            rect = self._rect
        if rect != self._last:
            self._last = rect
            left, top, right, bottom = rect
            winutil.move_topmost(self.hwnd, left, top, right - left, bottom - top)
            user32.InvalidateRect(self.hwnd, None, True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_TIMER:
            self._place()
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        key = gdi32.CreateSolidBrush(KEY)
        pen = gdi32.CreateSolidBrush(AMBER if self._paused else RED)
        user32.FillRect(hdc, ctypes.byref(rc), key)
        w, h = rc.right, rc.bottom

        def fill(left, top, right, bottom):
            user32.FillRect(hdc, ctypes.byref(wintypes.RECT(left, top, right, bottom)), pen)

        for x in range(0, w, DASH + GAP):  # arriba y abajo
            fill(x, 0, min(x + DASH, w), THICK)
            fill(x, h - THICK, min(x + DASH, w), h)
        for y in range(0, h, DASH + GAP):  # izquierda y derecha
            fill(0, y, THICK, min(y + DASH, h))
            fill(w - THICK, y, w, min(y + DASH, h))
        gdi32.DeleteObject(key)
        gdi32.DeleteObject(pen)
        user32.EndPaint(hwnd, ctypes.byref(ps))
