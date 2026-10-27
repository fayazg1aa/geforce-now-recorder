# GeForce NOW Recorder — Windows-only, small two-control macro recorder.
# Uses Windows low-level hooks plus Raw Input for Pointer Lock mouse movement.

import ctypes
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

if sys.platform != "win32":
    raise SystemExit("GeForce NOW Recorder is designed for Windows 10/11.")

APP_TITLE = "GeForce NOW Recorder"
APP_VERSION = "1.3"
COUNTDOWN_SECONDS = 10
TRIM_LAST_SECONDS = 5.0
HOTKEY_RECORD = 0x77  # F8: start/stop recording
HOTKEY_RUN = 0x78     # F9: start/stop playback

# Request physical pixel coordinates on high-DPI Windows displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Windows constants
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_MARKER = 0x47464E32
VK_F8 = HOTKEY_RECORD
VK_F9 = HOTKEY_RUN
WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
MOUSE_MOVE_ABSOLUTE = 0x0001
WM_QUIT = 0x0012

LRESULT = ctypes.c_ssize_t
ULONG_PTR = wintypes.WPARAM

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]

class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]

class RAWMOUSEBUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.WORD), ("usButtonData", wintypes.WORD)]

class RAWMOUSEBUTTONUNION(ctypes.Union):
    _fields_ = [("ulButtons", wintypes.DWORD), ("button", RAWMOUSEBUTTONS)]

class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("buttons",)
    _fields_ = [
        ("usFlags", wintypes.WORD),
        ("buttons", RAWMOUSEBUTTONUNION),
        ("ulRawButtons", wintypes.DWORD),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.DWORD),
    ]

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWINPUTDATA(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE)]

class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWINPUTDATA)]

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.WORD), ("usUsage", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]

RawInputWndProc = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
LowLevelKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
LowLevelMouseProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class RAW_WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", RawInputWndProc),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

# Explicit signatures protect pointer-sized Win32 APIs on 64-bit Python.
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
try:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
except AttributeError:
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
user32.mouse_event.restype = None
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]
user32.keybd_event.restype = None
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CreateWaitableTimerExW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
kernel32.CreateWaitableTimerExW.restype = wintypes.HANDLE
kernel32.SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL]
kernel32.SetWaitableTimer.restype = wintypes.BOOL
kernel32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
user32.GetMessageTime.restype = wintypes.LONG
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL


def send_mouse(flags, dx=0, dy=0, data=0):
    packet = INPUT(type=INPUT_MOUSE)
    packet.mi = MOUSEINPUT(int(dx), int(dy), int(data) & 0xFFFFFFFF,
                          flags, 0, INPUT_MARKER)
    if user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT)) != 1:
        raise OSError("Windows rejected mouse input. Run recorder and game at the same privilege level.")


def send_key(vk, scan, extended, down):
    # Pause has an E1 sequence and is sent using its virtual key.
    use_scan = bool(scan) and vk != 0x13
    flags = (KEYEVENTF_SCANCODE if use_scan else 0)
    flags |= KEYEVENTF_EXTENDEDKEY if extended else 0
    flags |= 0 if down else KEYEVENTF_KEYUP
    packet = INPUT(type=INPUT_KEYBOARD)
    packet.ki = KEYBDINPUT(0 if use_scan else vk, scan if use_scan else 0,
                          flags, 0, INPUT_MARKER)
    if user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT)) != 1:
        raise OSError("Windows rejected keyboard input. Run recorder and game at the same privilege level.")

try:
    user32.RegisterClassW.argtypes = [ctypes.POINTER(RAW_WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL
    user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    user32.GetRawInputData.restype = wintypes.UINT
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
except Exception:
    pass

# App data lives outside the extracted ZIP, so a rebuild won't delete a macro.
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GeForceNOWRecorder"
RECORDING_FILE = APP_DATA_DIR / "recording.json"


def current_cursor_pos():
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def screen_size():
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def screen_rect():
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return (left, top, left + max(1, width), top + max(1, height))


def foreground_client_rect():
    """Return the foreground window's client viewport in physical desktop pixels.

    For this app the foreground window should be the fullscreen GeForce NOW
    browser. Coordinates are relative to that viewport rather than assuming
    the Windows desktop resolution is the cloud stream resolution.
    """
    fallback = screen_rect()
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return fallback
        client = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(client)):
            return fallback
        top_left = POINT(int(client.left), int(client.top))
        bottom_right = POINT(int(client.right), int(client.bottom))
        if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
            return fallback
        if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
            return fallback
        rect = (int(top_left.x), int(top_left.y), int(bottom_right.x), int(bottom_right.y))
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        # During a countdown the intended target is a fullscreen browser/game
        # window. Avoid accidentally calibrating to a tiny popup or taskbar.
        sw, sh = screen_size()
        if width < max(320, int(sw * 0.40)) or height < max(240, int(sh * 0.40)):
            return fallback
        return rect
    except Exception:
        return fallback


def clamp01(value):
    return max(0.0, min(1.0, float(value)))


def normalize_to_rect(x, y, rect):
    left, top, right, bottom = rect
    width = max(1, right - left - 1)
    height = max(1, bottom - top - 1)
    return clamp01((float(x) - left) / width), clamp01((float(y) - top) / height)


def position_in_rect(nx, ny, rect):
    left, top, right, bottom = rect
    width = max(1, right - left - 1)
    height = max(1, bottom - top - 1)
    return left + round(clamp01(nx) * width), top + round(clamp01(ny) * height)


def signed_word(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def mouse_settings():
    """Read only. Never change the user's Windows pointer settings."""
    params = (ctypes.c_int * 3)()
    speed = ctypes.c_int()
    if (user32.SystemParametersInfoW(0x0003, 0, params, 0) and
            user32.SystemParametersInfoW(0x0070, 0, ctypes.byref(speed), 0)):
        return {"threshold1": params[0], "threshold2": params[1],
                "acceleration": params[2], "speed": speed.value}
    return None


NEUTRAL_MOUSE = {"threshold1": 0, "threshold2": 0, "acceleration": 0, "speed": 10}


def apply_mouse_settings(settings):
    # Session-only: no SPIF_UPDATEINIFILE, so this does not save a new default.
    params = (ctypes.c_int * 3)(settings["threshold1"], settings["threshold2"], settings["acceleration"])
    if not user32.SystemParametersInfoW(0x0004, 0, params, 0):
        raise OSError("Cannot set temporary 1:1 mouse input.")
    if not user32.SystemParametersInfoW(0x0071, 0, ctypes.c_void_p(settings["speed"]), 0):
        raise OSError("Cannot set temporary 1:1 mouse speed.")


def restore_mouse_journal(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    # Respect a manual settings change made while the recorder was active.
    if mouse_settings() == NEUTRAL_MOUSE:
        apply_mouse_settings(payload["original"])
    path.unlink(missing_ok=True)


def mouse_guard_watchdog(owner_pid):
    path = APP_DATA_DIR / f"mouse_restore_{owner_pid}.json"
    handle = kernel32.OpenProcess(0x00100000, False, owner_pid)  # SYNCHRONIZE
    try:
        while path.exists():
            if not handle or kernel32.WaitForSingleObject(handle, 500) == 0:
                restore_mouse_journal(path)
                break
    finally:
        if handle:
            kernel32.CloseHandle(handle)


class MouseInputGuard:
    """Neutral pointer ballistics while recording/replaying raw counts; restore on stop."""
    def __init__(self):
        self.original = None
        self.journal = APP_DATA_DIR / f"mouse_restore_{os.getpid()}.json"

    def acquire(self):
        if self.original is not None:
            return
        original = mouse_settings()
        if original is None:
            raise OSError("Cannot read Windows mouse settings.")
        if original == NEUTRAL_MOUSE:
            return
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = self.journal.with_suffix(".tmp")
        temp.write_text(json.dumps({"original": original}), encoding="utf-8")
        os.replace(temp, self.journal)
        self.original = original
        try:
            args = [sys.executable]
            if not getattr(sys, "frozen", False):
                args.append(str(Path(__file__).resolve()))
            args += ["--mouse-guard-watchdog", str(os.getpid())]
            env = dict(os.environ)
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen(args, creationflags=0x08000000, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            apply_mouse_settings(NEUTRAL_MOUSE)
        except Exception:
            apply_mouse_settings(original)
            self.original = None
            self.journal.unlink(missing_ok=True)
            raise

    def release(self):
        if self.original is None:
            return
        # Restore exactly the prior settings if our temporary settings remain.
        if mouse_settings() == NEUTRAL_MOUSE:
            apply_mouse_settings(self.original)
        self.original = None
        self.journal.unlink(missing_ok=True)


class PrecisePlaybackWaiter:
    """Interruptible high-resolution waitable timer driven by QPC deadlines."""
    def __init__(self):
        self.timer = kernel32.CreateWaitableTimerExW(None, None, 0x2, 0x1F0003)
        if not self.timer:
            self.timer = kernel32.CreateWaitableTimerExW(None, None, 0, 0x1F0003)
        self.stop = kernel32.CreateEventW(None, True, False, None)
        if not self.timer or not self.stop:
            self.close()
            raise OSError("Cannot create the playback timing events.")
        self.handles = (wintypes.HANDLE * 2)(self.stop, self.timer)

    def wait_until(self, deadline, stop_event, target_active):
        while not stop_event.is_set():
            if not target_active():
                raise RuntimeError("Target window lost focus. Playback stopped.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            due = ctypes.c_longlong(-max(1, round(remaining * 10_000_000)))
            if not kernel32.SetWaitableTimer(self.timer, ctypes.byref(due), 0, None, None, False):
                raise OSError("Playback timer could not be armed.")
            result = kernel32.WaitForMultipleObjects(2, self.handles, False, 10)
            if result == 0:
                return False
            if result == 0xFFFFFFFF:
                raise OSError("Playback timer wait failed.")
        return False

    def cancel(self):
        if self.stop:
            kernel32.SetEvent(self.stop)

    def close(self):
        for name in ("timer", "stop"):
            handle = getattr(self, name, None)
            if handle:
                kernel32.CloseHandle(handle)
                setattr(self, name, None)


def validate_macro(macro):
    if not isinstance(macro, dict) or not isinstance(macro.get("meta"), dict):
        raise ValueError("missing metadata")
    events = macro.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("no recorded events")
    valid_kinds = {"move", "relative_move", "key", "mouse_button", "wheel", "hwheel", "idle_wait"}
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in valid_kinds:
            raise ValueError("unknown event type")
        t = float(event.get("t", -1))
        if not math.isfinite(t) or t < 0:
            raise ValueError("invalid timestamp")
        kind = event["type"]
        if kind == "relative_move":
            if any(not isinstance(event.get(axis), int) or not -2147483648 <= event[axis] <= 2147483647 for axis in ("dx", "dy")):
                raise ValueError("invalid relative movement")
        elif kind == "key":
            if not isinstance(event.get("vk"), int) or not 1 <= event["vk"] <= 254 or event["vk"] in (VK_F8, VK_F9):
                raise ValueError("invalid/reserved key")
            if not isinstance(event.get("scan", 0), int) or not 0 <= event.get("scan", 0) <= 255:
                raise ValueError("invalid scan code")
            if not isinstance(event.get("down"), bool):
                raise ValueError("invalid key state")
        elif kind == "mouse_button":
            if event.get("button") not in ("left", "right", "middle", "x1", "x2") or not isinstance(event.get("down"), bool):
                raise ValueError("invalid mouse button")
        elif kind in ("wheel", "hwheel"):
            if not isinstance(event.get("delta"), int) or not -32768 <= event["delta"] <= 32767:
                raise ValueError("invalid wheel delta")
        if kind in ("move", "mouse_button", "wheel", "hwheel") and not event.get("relative_mouse_mode"):
            for axis in ("nx", "ny") if event.get("coord_space") == "gfn_viewport" else ("x", "y"):
                value = float(event.get(axis, float("nan")))
                if not math.isfinite(value):
                    raise ValueError("invalid cursor position")
    # Python's stable sort keeps press/release ordering at an equal timestamp.
    events = sorted((dict(e) for e in events), key=lambda e: float(e["t"]))
    duration = float(macro["meta"].get("recorded_seconds", events[-1]["t"]))
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("invalid duration")
    return events, max(0.01, duration, float(events[-1]["t"]))


def format_time(seconds):
    seconds = max(0, int(seconds))
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


class RawInputMouseCapture:
    """Captures raw relative mouse packets, required by browser Pointer Lock."""
    def __init__(self, callback):
        self.callback = callback
        self.thread = None
        self.thread_id = 0
        self.hwnd = None
        self.class_name = None
        self.instance = None
        self.ready = threading.Event()
        self.stop_event = threading.Event()
        self.active = False
        self._wndproc_ref = RawInputWndProc(self._window_proc)

    def start(self):
        self.thread = threading.Thread(target=self._run, name="RawInputCapture", daemon=True)
        self.thread.start()
        self.ready.wait(2.0)
        return self.active

    def stop(self):
        self.stop_event.set()
        if self.thread_id:
            try:
                user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if int(msg) == WM_INPUT:
            try:
                self._read_raw_input(lparam)
            except Exception:
                pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _read_raw_input(self, raw_handle):
        timestamp_ns = time.perf_counter_ns()
        size = wintypes.UINT(0)
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        handle = wintypes.HANDLE(raw_handle)
        result = user32.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header_size)
        if result == 0xFFFFFFFF or size.value < ctypes.sizeof(RAWINPUT):
            return
        buffer = ctypes.create_string_buffer(size.value)
        copied = user32.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size), header_size)
        if copied == 0xFFFFFFFF or copied < ctypes.sizeof(RAWINPUT):
            return
        raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
        if int(raw.header.dwType) != RIM_TYPEMOUSE:
            return
        mouse = raw.data.mouse
        if int(mouse.ulExtraInformation) == INPUT_MARKER:
            return
        if int(mouse.usFlags) & MOUSE_MOVE_ABSOLUTE:
            return
        dx, dy = int(mouse.lLastX), int(mouse.lLastY)
        if dx or dy:
            x, y = current_cursor_pos()
            self.callback(dx, dy, x, y, timestamp_ns=timestamp_ns)

    def _run(self):
        self.thread_id = int(kernel32.GetCurrentThreadId())
        self.instance = kernel32.GetModuleHandleW(None)
        self.class_name = f"GFNRawInput_{os.getpid()}_{id(self)}"
        wc = RAW_WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = self.instance
        wc.lpszClassName = self.class_name
        registered = False
        try:
            registered = bool(user32.RegisterClassW(ctypes.byref(wc)))
            if not registered:
                self.ready.set()
                return
            hwnd_message = ctypes.c_void_p(-3)  # HWND_MESSAGE
            self.hwnd = user32.CreateWindowExW(
                0, self.class_name, self.class_name, 0,
                0, 0, 0, 0, hwnd_message, None, self.instance, None
            )
            if not self.hwnd:
                self.ready.set()
                return
            device = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self.hwnd)
            self.active = bool(user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)))
            self.ready.set()
            if not self.active:
                return
            msg = wintypes.MSG()
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.active = False
            self.ready.set()
        finally:
            try:
                if self.hwnd:
                    user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            try:
                if registered and self.class_name:
                    user32.UnregisterClassW(self.class_name, self.instance)
            except Exception:
                pass


class InputEngine:
    """Low-level input recorder and macro playback for desktop + browser Pointer Lock."""
    def __init__(self, commands):
        self.commands = commands
        self.recording = False
        self.record_start = 0.0
        self.record_start_ns = 0
        self.record_stop_time = None
        self.events = []
        self.raw_samples = []
        self.events_lock = threading.RLock()
        self.raw_lock = threading.RLock()
        self.record_tick = 0
        self.sequence = 0
        self.mouse_mode = "gfn_raw"
        self.trim_seconds = 0.0
        self.initial_keys = []
        self.initial_mouse = []
        self.recorded_keys_down = set()
        self.recorded_mouse_down = set()
        self.last_move_pos = None
        self.hook_thread = None
        self.hook_thread_id = 0
        self.keyboard_hook = None
        self.mouse_hook = None
        self.hook_ready = threading.Event()
        self.hook_error = ""
        self.shutdown_event = threading.Event()
        self.play_stop = threading.Event()
        self.play_thread = None
        self.playing = False
        self.playback_pressed_keys = set()
        self.playback_pressed_mouse = set()
        self.playback_lock = threading.RLock()
        self.record_rect = screen_rect()
        self.playback_rect = screen_rect()
        self.playback_hwnd = None
        self.playback_macro = None
        self.completed_loops = 0
        self.last_playback_error = ""
        self.mouse_guard = MouseInputGuard()
        self.neutral_input = True
        self.play_waiter = None
        self.record_timer = None
        self.max_lateness_ms = 0.0
        self.recorded_screen_size = screen_size()
        self.raw_capture = RawInputMouseCapture(self.on_raw_delta)
        self.raw_input_available = self.raw_capture.start()
        self._keyboard_proc_ref = LowLevelKeyboardProc(self._keyboard_proc)
        self._mouse_proc_ref = LowLevelMouseProc(self._mouse_proc)
        self.hotkey_down = set()
        self.hook_thread = threading.Thread(target=self._hook_loop, name="InputHooks", daemon=True)
        self.hook_thread.start()
        self.hook_ready.wait(2.0)

    def elapsed_record_time(self):
        return max(0.0, (time.perf_counter_ns() - self.record_start_ns) / 1_000_000_000)

    def start_recording(self, mouse_mode="gfn_raw", trim_seconds=0.0, neutral_input=True):
        try:
            self._start_recording_impl(mouse_mode, trim_seconds, neutral_input)
        except Exception:
            self.recording = False
            if self.record_timer:
                self.record_timer.timeEndPeriod(1)
                self.record_timer = None
            self.mouse_guard.release()
            raise

    def _start_recording_impl(self, mouse_mode="gfn_raw", trim_seconds=0.0, neutral_input=True):
        # Called after the visible 10-second countdown, when the browser game
        # should be the foreground app. Record the actual viewport bounds.
        self.record_rect = foreground_client_rect()
        self.recorded_screen_size = screen_size()
        if mouse_mode == "gfn_raw" and not self.raw_input_available:
            raise RuntimeError("Raw Input unavailable. Restart the recorder before recording GeForce NOW.")
        self.neutral_input = bool(neutral_input) and mouse_mode == "gfn_raw"
        self.record_mouse_settings = mouse_settings()
        if self.neutral_input:
            self.mouse_guard.acquire()
        self.record_timer = ctypes.WinDLL("winmm")
        self.record_timer.timeBeginPeriod(1)
        with self.events_lock:
            self.mouse_mode = mouse_mode
            self.trim_seconds = max(0.0, float(trim_seconds))
            self.events = []
            self.recorded_keys_down.clear()
            self.recorded_mouse_down.clear()
            self.last_move_pos = current_cursor_pos()
            self.record_start_pos = self.last_move_pos
            self.initial_keys = []
            # Include keys already held when the countdown ends. Skip generic
            # modifiers (left/right versions below), mouse keys and our hotkeys.
            for vk in range(8, 255):
                if vk in (0x10, 0x11, 0x12, VK_F8, VK_F9):
                    continue
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    mapped = int(user32.MapVirtualKeyW(vk, 4))
                    scan, extended = mapped & 0xFF, (mapped >> 8) == 0xE0
                    self.initial_keys.append({"type": "key", "vk": vk, "scan": scan,
                                              "extended": extended, "down": True, "t": 0.0})
                    self.recorded_keys_down.add(vk)
            self.initial_mouse = []
            for vk, button in ((1, "left"), (2, "right"), (4, "middle"), (5, "x1"), (6, "x2")):
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    self.initial_mouse.append({"type": "mouse_button", "button": button,
                                               "down": True, "t": 0.0,
                                               "x": self.last_move_pos[0], "y": self.last_move_pos[1]})
            self.sequence = 0
            self.record_stop_time = None
            self.record_start = time.monotonic()
            self.record_start_ns = time.perf_counter_ns()
            self.record_tick = int(kernel32.GetTickCount64()) & 0xFFFFFFFF
            with self.raw_lock:
                self.raw_samples = []
            self.recording = True

    def _event_time(self, tick=None, timestamp_ns=None):
        # Hook.time and GetMessageTime are coarse (15/16ms on the user's PC).
        # QPC on receipt preserves sub-millisecond spacing across BOTH threads.
        now = time.perf_counter_ns() if timestamp_ns is None else timestamp_ns
        return (now - self.record_start_ns) / 1_000_000_000

    def _record_event(self, event, tick=None, timestamp_ns=None):
        if not self.recording:
            return
        with self.events_lock:
            if self.recording:
                event["t"] = self._event_time(timestamp_ns=timestamp_ns)
                if event["t"] < 0:
                    return
                if self.record_stop_time is not None and event["t"] > self.record_stop_time:
                    return
                event["seq"] = self.sequence
                self.sequence += 1
                self.events.append(event)

    def on_raw_delta(self, dx, dy, x, y, tick=None, timestamp_ns=None):
        if not self.recording or self.mouse_mode != "gfn_raw":
            return
        # Keep EVERY packet. Cursor position is meaningless under Pointer Lock;
        # browser recentering must never be mixed into the recorded motion.
        self._record_event({"type": "relative_move", "dx": int(dx), "dy": int(dy),
                            "relative_mouse_mode": True}, timestamp_ns=timestamp_ns)

    def _is_over_main_window(self, x, y):
        try:
            hwnd = self.app_hwnd_getter() if hasattr(self, "app_hwnd_getter") else None
            if not hwnd or not user32.IsWindowVisible(hwnd):
                return False
            rect = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return False
            # A minimized top-level window can have an off-screen rectangle.
            if rect.left < -10000 or rect.top < -10000:
                return False
            return rect.left <= x < rect.right and rect.top <= y < rect.bottom
        except Exception:
            return False

    def _keyboard_proc(self, n_code, w_param, l_param):
        timestamp_ns = time.perf_counter_ns()
        try:
            if n_code == HC_ACTION:
                data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                msg = int(w_param)
                vk = int(data.vkCode)
                injected = bool(int(data.flags) & LLKHF_INJECTED)
                is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
                is_up = msg in (WM_KEYUP, WM_SYSKEYUP)
                # F8 and F9 are dedicated start/stop hotkeys. Swallow physical events
                # so they never enter the macro or reach the game.
                if vk in (VK_F8, VK_F9) and not injected:
                    if is_down and vk not in self.hotkey_down:
                        self.hotkey_down.add(vk)
                        if vk == VK_F8 and self.recording:
                            self.record_stop_time = max(0.0, self._event_time(timestamp_ns=timestamp_ns))
                        if vk == VK_F9 and self.playing:
                            self.stop_playback()
                        self.commands.put("hotkey_record" if vk == VK_F8 else "hotkey_run")
                    elif is_up:
                        self.hotkey_down.discard(vk)
                    return 1
                if not injected and self.recording and (is_down or is_up):
                    with self.events_lock:
                        if self.recording:
                            if is_down:
                                self.recorded_keys_down.add(vk)
                                self._record_event({
                                    "type": "key", "vk": vk, "scan": int(data.scanCode),
                                    "extended": bool(int(data.flags) & LLKHF_EXTENDED),
                                    "down": True,
                                }, timestamp_ns=timestamp_ns)
                            elif is_up and vk in self.recorded_keys_down:
                                self.recorded_keys_down.discard(vk)
                                self._record_event({
                                    "type": "key", "vk": vk, "scan": int(data.scanCode),
                                    "extended": bool(int(data.flags) & LLKHF_EXTENDED),
                                    "down": False,
                                }, timestamp_ns=timestamp_ns)
        except Exception:
            pass
        return user32.CallNextHookEx(self.keyboard_hook, n_code, w_param, l_param)

    def _mouse_proc(self, n_code, w_param, l_param):
        timestamp_ns = time.perf_counter_ns()
        try:
            if n_code == HC_ACTION:
                data = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                msg = int(w_param)
                injected = bool(int(data.flags) & LLMHF_INJECTED)
                x, y = int(data.pt.x), int(data.pt.y)
                if not injected and self.recording and not self._is_over_main_window(x, y):
                    if msg == WM_MOUSEMOVE:
                        pos = (x, y)
                        if self.mouse_mode == "cursor" and pos != self.last_move_pos:
                            self.last_move_pos = pos
                            self._record_event({"type": "move", "x": x, "y": y}, timestamp_ns=timestamp_ns)
                    else:
                        buttons = {
                            WM_LBUTTONDOWN: ("left", True), WM_LBUTTONUP: ("left", False),
                            WM_RBUTTONDOWN: ("right", True), WM_RBUTTONUP: ("right", False),
                            WM_MBUTTONDOWN: ("middle", True), WM_MBUTTONUP: ("middle", False),
                        }
                        if msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                            xb = (int(data.mouseData) >> 16) & 0xFFFF
                            if xb in (1, 2):
                                buttons[msg] = ("x1" if xb == 1 else "x2", msg == WM_XBUTTONDOWN)
                        if msg in buttons:
                            button, down = buttons[msg]
                            self._record_event({"type": "mouse_button", "button": button, "down": bool(down), "x": x, "y": y}, timestamp_ns=timestamp_ns)
                        elif msg in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                            delta = signed_word((int(data.mouseData) >> 16) & 0xFFFF)
                            self._record_event({"type": "wheel" if msg == WM_MOUSEWHEEL else "hwheel", "delta": delta, "x": x, "y": y}, timestamp_ns=timestamp_ns)
        except Exception:
            pass
        return user32.CallNextHookEx(self.mouse_hook, n_code, w_param, l_param)

    def _hook_loop(self):
        self.hook_thread_id = int(kernel32.GetCurrentThreadId())
        module = kernel32.GetModuleHandleW(None)
        try:
            self.keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, ctypes.cast(self._keyboard_proc_ref, ctypes.c_void_p), module, 0)
            self.mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, ctypes.cast(self._mouse_proc_ref, ctypes.c_void_p), module, 0)
            if not self.keyboard_hook or not self.mouse_hook:
                self.hook_error = "Windows input hooks could not be installed. Try running the app normally, not inside a protected folder."
            self.hook_ready.set()
            msg = wintypes.MSG()
            while not self.shutdown_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.hook_error = str(exc)
            self.hook_ready.set()
        finally:
            for hook in (self.keyboard_hook, self.mouse_hook):
                if hook:
                    try:
                        user32.UnhookWindowsHookEx(hook)
                    except Exception:
                        pass
            self.keyboard_hook = self.mouse_hook = None

    def stop_recording_and_trim(self):
        if not self.recording:
            return None
        with self.events_lock:
            self.recording = False
            elapsed = self.record_stop_time if self.record_stop_time is not None else self.elapsed_record_time()
            cutoff = max(0.0, elapsed - self.trim_seconds)
            events = [dict(e) for e in self.initial_keys + self.initial_mouse + self.events
                      if 0.0 <= float(e.get("t", 0.0)) <= cutoff]
            self.events = []
            self.recorded_keys_down.clear()
        if self.record_timer:
            self.record_timer.timeEndPeriod(1)
            self.record_timer = None
        self.mouse_guard.release()
        if cutoff < 0.01 or not events:
            return {"error": "No input captured. Record some input, then press F8 again."}
        for event in events:
            kind = event.get("type")
            if kind in ("move", "mouse_button", "wheel", "hwheel"):
                if self.mouse_mode == "gfn_raw":
                    event["relative_mouse_mode"] = True
                    event.pop("x", None)
                    event.pop("y", None)
                else:
                    nx, ny = normalize_to_rect(event["x"], event["y"], self.record_rect)
                    event.update(nx=nx, ny=ny, coord_space="gfn_viewport")
                    event.pop("x", None)
                    event.pop("y", None)
        events.sort(key=lambda e: (float(e["t"]), int(e.get("seq", -1))))
        for event in events:
            event.pop("seq", None)
        # Preserve the real ending delay, even if there was no input near F8.
        # Never merge adjacent movement packets: the old sliding 4ms window
        # could collapse a whole mouse stroke into a single late jump.
        events.append({"type": "idle_wait", "t": cutoff, "final": True})
        width, height = self.recorded_screen_size
        left, top, right, bottom = self.record_rect
        nx, ny = normalize_to_rect(*self.record_start_pos, self.record_rect)
        return {
            "meta": {
                "app": APP_TITLE, "version": APP_VERSION, "format_version": 3,
                "timestamp_clock": "perf_counter_ns",
                "neutral_mouse_input": self.neutral_input,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "recorded_seconds": cutoff, "trimmed_last_seconds": self.trim_seconds,
                "mouse_mode": self.mouse_mode, "repeat": True,
                "screen_width": width, "screen_height": height,
                "capture_viewport": {"left": left, "top": top, "width": right-left,
                                     "height": bottom-top, "coordinate_mode": "normalized_client_viewport"},
                "start_cursor": {"nx": nx, "ny": ny},
                "raw_input_available": self.raw_input_available,
                "pointer_lock_samples": sum(e["type"] == "relative_move" for e in events),
                "raw_dx_total": sum(e.get("dx", 0) for e in events if e["type"] == "relative_move"),
                "raw_dy_total": sum(e.get("dy", 0) for e in events if e["type"] == "relative_move"),
                "windows_mouse_settings": self.record_mouse_settings,
            },
            "events": events,
        }

    def start_playback(self, macro):
        if self.playing or (self.play_thread and self.play_thread.is_alive()):
            return False, "Playback is already running."
        try:
            events, duration = validate_macro(macro)
        except (ValueError, TypeError, OverflowError) as exc:
            return False, f"Invalid recording: {exc}"
        meta = macro.get("meta", {})
        if meta.get("format_version") != 3:
            return False, "Old recording has coarse/merged mouse timing. Press F8 to record again with v1.3."
        saved_settings = meta.get("windows_mouse_settings")
        self.neutral_input = bool(meta.get("neutral_mouse_input")) and meta.get("mouse_mode") == "gfn_raw"
        if not self.neutral_input and meta.get("mouse_mode") == "gfn_raw" and saved_settings and saved_settings != mouse_settings():
            return False, "Windows mouse speed/acceleration changed. Restore it or make a new recording."
        self.playback_rect = foreground_client_rect()
        self.playback_hwnd = user32.GetForegroundWindow()
        self.recorded_screen_size = (
            max(1, int(meta.get("screen_width", screen_size()[0]))),
            max(1, int(meta.get("screen_height", screen_size()[1]))),
        )
        self.playback_macro = macro
        self.completed_loops = 0
        self.last_playback_error = ""
        self.max_lateness_ms = 0.0
        if self.neutral_input:
            try:
                self.mouse_guard.acquire()
            except Exception as exc:
                return False, str(exc)
        self.playing = True
        self.play_stop.clear()
        self.playback_pressed_keys.clear()
        self.playback_pressed_mouse.clear()
        self.play_thread = threading.Thread(target=self._play_worker, args=(events, duration), name="MacroPlayback", daemon=True)
        try:
            self.play_thread.start()
        except Exception as exc:
            self.playing = False
            self.mouse_guard.release()
            return False, str(exc)
        return True, "Repeating until F9."

    def stop_playback(self):
        self.play_stop.set()
        if self.play_waiter:
            self.play_waiter.cancel()

    def _target_active(self):
        return (not self.playback_hwnd or
                (user32.IsWindow(self.playback_hwnd) and
                 user32.GetForegroundWindow() == self.playback_hwnd))

    def _wait_until(self, target):
        if self.play_waiter:
            return self.play_waiter.wait_until(target, self.play_stop, self._target_active)
        while not self.play_stop.is_set():
            if not self._target_active():
                raise RuntimeError("Target window lost focus. Playback stopped; refocus GeForce NOW and press F9.")
            remaining = target - time.monotonic()
            if remaining <= 0:
                return True
            self.play_stop.wait(min(remaining, 0.001))
        return False

    def _play_worker(self, events, duration):
        timer = ctypes.WinDLL("winmm")
        timer.timeBeginPeriod.argtypes = [wintypes.UINT]
        timer.timeEndPeriod.argtypes = [wintypes.UINT]
        timer_active = timer.timeBeginPeriod(1) == 0
        try:
            self.play_waiter = PrecisePlaybackWaiter()
            while not self.play_stop.is_set():
                if not self._target_active():
                    raise RuntimeError("Target window lost focus. Playback stopped.")
                meta = self.playback_macro.get("meta", {})
                # In raw mode NEVER warp the cursor, including loop boundaries.
                # In cursor mode the initial anchor makes each loop independent.
                if meta.get("mouse_mode") == "cursor" and meta.get("start_cursor"):
                    pos = meta["start_cursor"]
                    self._set_cursor(*position_in_rect(pos["nx"], pos["ny"], self.playback_rect))
                start = time.monotonic()
                for event in events:
                    if not self._wait_until(start + float(event["t"])):
                        break
                    if self.play_stop.is_set():
                        break
                    self.max_lateness_ms = max(self.max_lateness_ms,
                        (time.monotonic() - start - float(event["t"])) * 1000)
                    self._execute_event(event)
                if self.play_stop.is_set() or not self._wait_until(start + duration):
                    break
                self._release_all_inputs()
                self.completed_loops += 1
        except Exception as exc:
            self.last_playback_error = str(exc)
            self.commands.put(("playback_error", str(exc)))
        finally:
            try:
                self._release_all_inputs()
            except Exception as exc:
                self.last_playback_error = self.last_playback_error or str(exc)
            if timer_active:
                timer.timeEndPeriod(1)
            if self.play_waiter:
                self.play_waiter.close()
                self.play_waiter = None
            try:
                self.mouse_guard.release()
            except Exception as exc:
                self.last_playback_error = self.last_playback_error or str(exc)
            self.playing = False
            self.commands.put("playback_finished")

    def _set_cursor(self, x, y):
        left, top, right, bottom = screen_rect()
        width, height = right-left, bottom-top
        # Half-pixel centres map back to exactly the requested desktop pixel,
        # including negative coordinates on a secondary monitor.
        nx = min(65535, max(0, int((int(x)-left+0.5) * 65536 / width)))
        ny = min(65535, max(0, int((int(y)-top+0.5) * 65536 / height)))
        send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MOVE_NOCOALESCE, nx, ny)

    def _set_cursor_for_event(self, event):
        if event.get("coord_space") == "gfn_viewport" and "nx" in event and "ny" in event:
            x, y = position_in_rect(event["nx"], event["ny"], self.playback_rect)
            self._set_cursor(x, y)
            return
        # Backward-compatible fallback for a macro recorded by an earlier build.
        old_w, old_h = self.recorded_screen_size
        new_w, new_h = screen_size()
        x = round(float(event.get("x", 0)) * new_w / max(1, old_w))
        y = round(float(event.get("y", 0)) * new_h / max(1, old_h))
        self._set_cursor(x, y)

    def _execute_event(self, event):
        kind = event.get("type")
        if kind == "idle_wait":
            return
        if kind == "move":
            self._set_cursor_for_event(event)
            return
        if kind == "relative_move":
            dx, dy = int(event.get("dx", 0)), int(event.get("dy", 0))
            if dx or dy:
                send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE, dx, dy)
            return
        if kind == "key":
            vk = int(event.get("vk", 0)) & 0xFF
            scan = int(event.get("scan", 0)) & 0xFF
            down = bool(event.get("down"))
            if scan == 0:
                scan = int(user32.MapVirtualKeyW(vk, 0)) & 0xFF
            send_key(vk, scan, bool(event.get("extended")), down)
            with self.playback_lock:
                if down:
                    self.playback_pressed_keys.add((vk, scan, bool(event.get("extended"))))
                else:
                    self.playback_pressed_keys = {k for k in self.playback_pressed_keys if k[0] != vk}
            return
        if kind == "mouse_button":
            if not event.get("relative_mouse_mode"):
                self._set_cursor_for_event(event)
            button, down = event.get("button", "left"), bool(event.get("down"))
            flag_map = {
                ("left", True): MOUSEEVENTF_LEFTDOWN, ("left", False): MOUSEEVENTF_LEFTUP,
                ("right", True): MOUSEEVENTF_RIGHTDOWN, ("right", False): MOUSEEVENTF_RIGHTUP,
                ("middle", True): MOUSEEVENTF_MIDDLEDOWN, ("middle", False): MOUSEEVENTF_MIDDLEUP,
                ("x1", True): MOUSEEVENTF_XDOWN, ("x1", False): MOUSEEVENTF_XUP,
                ("x2", True): MOUSEEVENTF_XDOWN, ("x2", False): MOUSEEVENTF_XUP,
            }
            flag = flag_map.get((button, down))
            if flag is not None:
                data = 1 if button == "x1" else (2 if button == "x2" else 0)
                send_mouse(flag, data=data)
                with self.playback_lock:
                    if down:
                        self.playback_pressed_mouse.add(button)
                    else:
                        self.playback_pressed_mouse.discard(button)
            return
        if kind in ("wheel", "hwheel"):
            if not event.get("relative_mouse_mode"):
                self._set_cursor_for_event(event)
            delta = int(event.get("delta", 0)) & 0xFFFFFFFF
            flag = MOUSEEVENTF_WHEEL if kind == "wheel" else MOUSEEVENTF_HWHEEL
            send_mouse(flag, data=delta)

    def _release_all_inputs(self):
        with self.playback_lock:
            keys = list(self.playback_pressed_keys)
            buttons = list(self.playback_pressed_mouse)
            self.playback_pressed_keys.clear()
            self.playback_pressed_mouse.clear()
        for vk, scan, extended in keys:
            send_key(vk, scan, extended, False)
        flag_map = {"left": MOUSEEVENTF_LEFTUP, "right": MOUSEEVENTF_RIGHTUP, "middle": MOUSEEVENTF_MIDDLEUP, "x1": MOUSEEVENTF_XUP, "x2": MOUSEEVENTF_XUP}
        for button in buttons:
            data = 1 if button == "x1" else (2 if button == "x2" else 0)
            send_mouse(flag_map[button], data=data)

    def shutdown(self):
        self.stop_playback()
        self.recording = False
        self.shutdown_event.set()
        if self.hook_thread_id:
            try:
                user32.PostThreadMessageW(self.hook_thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        self.raw_capture.stop()
        if self.play_thread and self.play_thread is not threading.current_thread():
            self.play_thread.join(timeout=2.0)
        if self.hook_thread:
            self.hook_thread.join(timeout=1.0)
        if self.record_timer:
            self.record_timer.timeEndPeriod(1)
            self.record_timer = None
        self.mouse_guard.release()


class ClickThroughOverlay:
    """Topmost on-screen countdown/timer that does not steal game mouse input."""
    def __init__(self, root):
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.title("GFN Status")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#121826")
        self.label = tk.Label(
            self.window, text="", font=("Segoe UI", 17, "bold"),
            fg="#F8FAFC", bg="#121826", padx=18, pady=12,
        )
        self.label.pack(fill="both", expand=True)
        self.window.geometry("560x60+26+28")
        self.window.withdraw()
        self.window.update_idletasks()
        self.hwnd = user32.GetAncestor(self.window.winfo_id(), 2) or self.window.winfo_id()
        try:
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            style = int(get_style(self.hwnd, GWL_EXSTYLE))
            set_style(self.hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            user32.SetLayeredWindowAttributes(self.hwnd, 0, 238, 0x00000002)  # LWA_ALPHA
            user32.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), 26, 28, 560, 60, 0x0010)  # no activation
        except Exception:
            pass

    def show(self, text):
        self.label.configure(text=text)
        self.window.deiconify()
        self.window.attributes("-topmost", True)
        self.window.geometry("560x60+26+28")
        try:
            user32.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), 26, 28, 560, 60, 0x0010 | 0x0040)
        except Exception:
            pass

    def set_text(self, text):
        try:
            self.label.configure(text=text)
        except tk.TclError:
            pass

    def hide(self):
        try:
            self.window.withdraw()
        except tk.TclError:
            pass


class GeForceNowRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("510x510")
        self.root.resizable(False, False)
        self.root.configure(bg="#0B1220")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.commands = queue.Queue()
        self.root_hwnd = user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
        self.engine = InputEngine(self.commands)
        self.engine.app_hwnd_getter = lambda: self.root_hwnd
        self.overlay = ClickThroughOverlay(root)
        self.mode = "idle"
        self.mode_started = 0.0
        self.countdown_deadline = 0.0
        self.countdown_kind = None
        self.countdown_after_id = None
        self.timer_after_id = None
        self.message_after_id = None
        self.macro = self.load_macro()
        self._build_ui()
        self.refresh_ui()
        if self.engine.hook_error:
            self.status_var.set(self.engine.hook_error)
        elif not self.engine.raw_input_available:
            self.status_var.set("Ready — Raw Input unavailable; Pointer Lock recording may be limited.")
        self.root.after(50, self.poll_commands)

    def _build_ui(self):
        tk.Label(self.root, text="GEFORCE NOW", font=("Segoe UI", 10, "bold"), fg="#60A5FA", bg="#0B1220").pack(pady=(18, 0))
        tk.Label(self.root, text="RECORDER", font=("Segoe UI", 22, "bold"), fg="#F8FAFC", bg="#0B1220").pack(pady=(0, 4))
        tk.Label(self.root, text="Timed mouse + keyboard recording • continuous repeat", font=("Segoe UI", 9), fg="#94A3B8", bg="#0B1220").pack(pady=(0, 10))
        self.mouse_mode_var = tk.StringVar(value="GeForce NOW (raw movement)")
        self.mouse_mode_menu = tk.OptionMenu(self.root, self.mouse_mode_var,
                                            "GeForce NOW (raw movement)", "Cursor positions (desktop/menu)")
        self.mouse_mode_menu.configure(font=("Segoe UI", 10), bg="#1E293B", fg="white",
                                       activebackground="#334155", activeforeground="white", highlightthickness=0)
        self.mouse_mode_menu.pack(fill="x", padx=22, pady=(0, 6))
        self.trim_var = tk.BooleanVar(value=False)
        self.trim_check = tk.Checkbutton(self.root, text="Remove last 5 seconds (old v1.1 behavior)",
                                         variable=self.trim_var, bg="#0B1220", fg="#94A3B8",
                                         selectcolor="#1E293B", activebackground="#0B1220",
                                         activeforeground="white", font=("Segoe UI", 9))
        self.trim_check.pack(pady=(0, 10))
        self.neutral_var = tk.BooleanVar(value=True)
        self.neutral_check = tk.Checkbutton(self.root, text="1:1 input - temporary Windows pointer settings",
                                            variable=self.neutral_var, bg="#0B1220", fg="#CBD5E1",
                                            selectcolor="#1E293B", activebackground="#0B1220",
                                            activeforeground="white", font=("Segoe UI", 9))
        self.neutral_check.pack()
        tk.Label(self.root, text="During Record/Run: acceleration off, speed 6/11.\nPrevious pointer settings return when recording/playback stops.",
                 font=("Segoe UI", 9), fg="#94A3B8", bg="#0B1220").pack(pady=(0, 10))
        row = tk.Frame(self.root, bg="#0B1220")
        row.pack(fill="x", padx=22)
        self.record_button = tk.Button(row, text="Record", command=self.toggle_record, font=("Segoe UI", 12, "bold"), fg="white", bg="#2563EB", activebackground="#1D4ED8", activeforeground="white", relief="flat", width=15, height=3, cursor="hand2", bd=0)
        self.record_button.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.run_button = tk.Button(row, text="Run", command=self.toggle_run, font=("Segoe UI", 12, "bold"), fg="white", bg="#059669", activebackground="#047857", activeforeground="white", relief="flat", width=15, height=3, cursor="hand2", bd=0)
        self.run_button.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, wraplength=430, justify="center", font=("Segoe UI", 9), fg="#CBD5E1", bg="#0B1220", height=3).pack(fill="x", padx=20, pady=(10, 3))
        tk.Label(self.root, text="F8  Record / Stop Record     •     F9  Run / Stop", font=("Segoe UI", 9, "bold"), fg="#64748B", bg="#0B1220").pack(pady=(1, 8))
        tk.Label(self.root, text="Before F9: restore the same game/camera starting point.\nGeForce NOW: keep mouse captured and sensitivity unchanged.",
                 font=("Segoe UI", 9), fg="#94A3B8", bg="#0B1220").pack()

    def load_macro(self):
        try:
            if RECORDING_FILE.exists():
                with RECORDING_FILE.open("r", encoding="utf-8") as file:
                    macro = json.load(file)
                if isinstance(macro, dict) and isinstance(macro.get("events"), list):
                    return macro
        except Exception:
            pass
        return None

    def save_macro(self, macro):
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if RECORDING_FILE.exists():
            backup = RECORDING_FILE.with_name("recording.previous.json")
            backup_temp = backup.with_suffix(".tmp")
            backup_temp.write_bytes(RECORDING_FILE.read_bytes())
            os.replace(backup_temp, backup)
        temp_file = RECORDING_FILE.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as file:
            json.dump(macro, file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_file, RECORDING_FILE)

    def refresh_ui(self):
        state = "normal" if self.mode == "idle" else "disabled"
        self.mouse_mode_menu.configure(state=state)
        self.trim_check.configure(state=state)
        self.neutral_check.configure(state=state)
        if self.mode == "countdown_record":
            self.record_button.configure(text="Cancel Record", bg="#B45309")
        elif self.mode == "recording":
            self.record_button.configure(text="Stop Record", bg="#DC2626")
        else:
            self.record_button.configure(text="Record", bg="#2563EB")
        if self.mode == "countdown_run":
            self.run_button.configure(text="Cancel Run", bg="#B45309")
        elif self.mode in ("playing", "stopping_playback"):
            self.run_button.configure(text="Stop", bg="#DC2626")
        else:
            self.run_button.configure(text="Run / Repeat", bg="#059669")
        if self.mode == "idle":
            if self.macro and self.macro.get("events"):
                n = len(self.macro["events"])
                secs = self.macro.get("meta", {}).get("recorded_seconds", 0)
                self.status_var.set(f"Saved recording ready • {n:,} events • {format_time(secs)}")
                if self.macro.get("meta", {}).get("format_version") != 3:
                    self.status_var.set("Old recording found. Make a new F8 recording with v1.3 precision timing.")
            else:
                self.status_var.set("Ready — record an action first")

    def hide_main_for_game(self):
        try:
            self.root.iconify()
        except tk.TclError:
            pass

    def toggle_record(self, from_hotkey=False):
        if self.mode == "countdown_record":
            self.cancel_countdown("Record countdown cancelled", show_overlay=True)
            return
        if self.mode == "recording":
            self.finish_recording(from_hotkey=from_hotkey)
            return
        if self.mode != "idle":
            if from_hotkey:
                self.overlay.show("BUSY — stop the current action first")
                self.schedule_overlay_hide(2.0)
            else:
                self.status_var.set("Stop the current Run action before recording.")
            return
        self.begin_countdown("record")

    def toggle_run(self, from_hotkey=False):
        if self.mode == "countdown_run":
            self.cancel_countdown("Run countdown cancelled", show_overlay=True)
            return
        if self.mode == "playing":
            self.stop_playback(from_hotkey=from_hotkey)
            return
        if self.mode == "stopping_playback":
            return
        if self.mode != "idle":
            if from_hotkey:
                self.overlay.show("BUSY — stop recording first")
                self.schedule_overlay_hide(2.0)
            else:
                self.status_var.set("Stop recording before Run.")
            return
        self.macro = self.load_macro()
        if not self.macro or not self.macro.get("events"):
            self.status_var.set("No saved recording yet — press Record first.")
            if from_hotkey:
                self.overlay.show("NO RECORDING — press Record first")
                self.schedule_overlay_hide(2.2)
            return
        self.begin_countdown("run")

    def begin_countdown(self, kind):
        self.countdown_kind = kind
        self.mode = "countdown_record" if kind == "record" else "countdown_run"
        self.countdown_deadline = time.monotonic() + COUNTDOWN_SECONDS
        self.hide_main_for_game()
        self.overlay.show(self.countdown_text(COUNTDOWN_SECONDS))
        self.refresh_ui()
        self.tick_countdown()

    def countdown_text(self, remaining):
        action = "RECORDING STARTS" if self.countdown_kind == "record" else "PLAYBACK STARTS"
        return f"{action} IN  {max(1, int(remaining)):02d}  SEC"

    def tick_countdown(self):
        if self.mode not in ("countdown_record", "countdown_run"):
            return
        remaining = math.ceil(self.countdown_deadline - time.monotonic())
        if remaining <= 0:
            kind = self.countdown_kind
            self.countdown_kind = None
            if kind == "record":
                try:
                    mode = "gfn_raw" if self.mouse_mode_var.get().startswith("GeForce NOW") else "cursor"
                    self.engine.start_recording(mode, TRIM_LAST_SECONDS if self.trim_var.get() else 0.0,
                                                self.neutral_var.get())
                except Exception as exc:
                    self.mode = "idle"
                    self.refresh_ui()
                    self.status_var.set(str(exc))
                    self.overlay.show("RECORDING FAILED — CHECK APP STATUS")
                    self.schedule_overlay_hide(3.0)
                    return
                self.mode = "recording"
                self.mode_started = time.monotonic()
                self.overlay.show("●  RECORDING  00:00:00     F8  STOP")
            else:
                ok, message = self.engine.start_playback(self.macro)
                if not ok:
                    self.mode = "idle"
                    self.overlay.show(message.upper())
                    self.status_var.set(message)
                    self.schedule_overlay_hide(2.5)
                else:
                    self.mode = "playing"
                    self.mode_started = time.monotonic()
                    self.overlay.show("▶  REPEAT  00:00:00     F9  STOP")
            self.refresh_ui()
            if kind == "run" and not ok:
                self.status_var.set(message)
            if self.mode in ("recording", "playing"):
                self.schedule_timer_tick()
            return
        self.overlay.set_text(self.countdown_text(remaining))
        self.countdown_after_id = self.root.after(80, self.tick_countdown)

    def cancel_countdown(self, message, show_overlay=False):
        if self.countdown_after_id is not None:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except tk.TclError:
                pass
        self.countdown_after_id = None
        self.countdown_kind = None
        self.mode = "idle"
        self.refresh_ui()
        self.status_var.set(message)
        if show_overlay:
            self.overlay.show(message.upper())
            self.schedule_overlay_hide(2.0)
        else:
            self.overlay.hide()

    def schedule_timer_tick(self):
        if self.timer_after_id is not None:
            try:
                self.root.after_cancel(self.timer_after_id)
            except tk.TclError:
                pass
        self.timer_after_id = self.root.after(160, self.timer_tick)

    def timer_tick(self):
        self.timer_after_id = None
        if self.mode == "recording":
            elapsed = self.engine.elapsed_record_time()
            self.overlay.set_text(f"●  RECORDING  {format_time(elapsed)}     F8  STOP")
            self.timer_after_id = self.root.after(160, self.timer_tick)
        elif self.mode == "playing":
            elapsed = time.monotonic() - self.mode_started
            self.overlay.set_text(f"▶  LOOP {self.engine.completed_loops + 1}  {format_time(elapsed)}   F9 STOP")
            self.timer_after_id = self.root.after(160, self.timer_tick)

    def finish_recording(self, from_hotkey=False):
        if self.mode != "recording":
            return
        self.mode = "idle"
        result = self.engine.stop_recording_and_trim()
        if self.timer_after_id is not None:
            try:
                self.root.after_cancel(self.timer_after_id)
            except tk.TclError:
                pass
            self.timer_after_id = None
        if not result or result.get("error"):
            message = result.get("error", "Recording could not be saved.") if result else "Recording could not be saved."
            self.status_var.set(message)
            self.overlay.show("RECORDING TOO SHORT — NOTHING SAVED")
            self.schedule_overlay_hide(3.0)
        else:
            try:
                self.save_macro(result)
                self.macro = result
                meta = result.get("meta", {})
                rel = int(meta.get("pointer_lock_samples", 0))
                total = len(result.get("events", []))
                viewport = meta.get("capture_viewport", {})
                vw = int(viewport.get("width", meta.get("screen_width", 0)))
                vh = int(viewport.get("height", meta.get("screen_height", 0)))
                trim = meta.get("trimmed_last_seconds", 0)
                ending = f"last {trim:g}s removed" if trim else "full recording kept"
                message = f"Saved {total:,} events • {ending} • viewport {vw}×{vh}"
                self.status_var.set(message)
                if rel:
                    overlay_text = f"SAVED  •  {rel:,} RAW MOVES  •  F9 REPEAT"
                elif not self.engine.raw_input_available:
                    overlay_text = "SAVED  •  RAW INPUT UNAVAILABLE — GFN AIM MAY NOT REPLAY"
                else:
                    overlay_text = f"SAVED  •  {total:,} EVENTS  •  F9 REPEAT"
                self.overlay.show(overlay_text)
                self.schedule_overlay_hide(3.5)
            except Exception as exc:
                message = f"Could not save recording: {exc}"
                self.status_var.set(message)
                self.overlay.show("SAVE FAILED — CHECK LOCAL APP DATA PERMISSIONS")
                self.schedule_overlay_hide(3.5)
        self.refresh_ui()
        self.status_var.set(message)
        if not from_hotkey:
            try:
                self.root.deiconify()
                self.root.lift()
            except tk.TclError:
                pass

    def stop_playback(self, from_hotkey=False):
        if self.mode not in ("playing", "stopping_playback"):
            return
        self.mode = "stopping_playback"
        self.engine.stop_playback()
        self.overlay.set_text("STOPPING PLAYBACK…")
        self.refresh_ui()
        if not from_hotkey:
            try:
                self.root.deiconify()
                self.root.lift()
            except tk.TclError:
                pass

    def schedule_overlay_hide(self, seconds):
        if self.message_after_id is not None:
            try:
                self.root.after_cancel(self.message_after_id)
            except tk.TclError:
                pass
        self.message_after_id = self.root.after(int(seconds * 1000), self.overlay.hide)

    def poll_commands(self):
        try:
            while True:
                command = self.commands.get_nowait()
                if command == "hotkey_record":
                    self.toggle_record(from_hotkey=True)
                elif command == "hotkey_run":
                    self.toggle_run(from_hotkey=True)
                elif command == "playback_finished":
                    if self.mode in ("playing", "stopping_playback"):
                        self.mode = "idle"
                        self.refresh_ui()
                        if self.engine.last_playback_error:
                            self.status_var.set(self.engine.last_playback_error)
                            self.overlay.show("PLAYBACK STOPPED — CHECK APP STATUS")
                            self.schedule_overlay_hide(3.0)
                            continue
                        if self.engine.play_stop.is_set():
                            self.overlay.show("PLAYBACK STOPPED")
                        else:
                            self.overlay.show("PLAYBACK COMPLETE")
                        self.schedule_overlay_hide(2.0)
                elif isinstance(command, tuple) and command[0] == "playback_error":
                    self.mode = "idle"
                    self.refresh_ui()
                    self.status_var.set(f"Playback error: {command[1]}")
                    self.overlay.show("PLAYBACK ERROR")
                    self.schedule_overlay_hide(3.0)
        except queue.Empty:
            pass
        self.root.after(50, self.poll_commands)

    def on_close(self):
        if self.mode == "recording":
            result = self.engine.stop_recording_and_trim()
            if result and not result.get("error"):
                try:
                    self.save_macro(result)
                except Exception:
                    pass
        elif self.mode == "countdown_record":
            self.cancel_countdown("Closing", show_overlay=False)
        elif self.mode == "playing":
            self.engine.stop_playback()
        self.engine.shutdown()
        try:
            self.overlay.window.destroy()
        except Exception:
            pass
        self.root.destroy()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--mouse-guard-watchdog":
        mouse_guard_watchdog(int(sys.argv[2]))
        return
    root = tk.Tk()
    smoke_test = len(sys.argv) == 3 and sys.argv[1] == "--self-test"
    if smoke_test:
        root.withdraw()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    app = GeForceNowRecorderApp(root)
    if smoke_test:
        root.update_idletasks()
        report = {
            "version": APP_VERSION,
            "raw_input_available": app.engine.raw_input_available,
            "keyboard_hook": bool(app.engine.keyboard_hook),
            "mouse_hook": bool(app.engine.mouse_hook),
            "hook_error": app.engine.hook_error,
            "mouse_mode": app.mouse_mode_var.get(),
            "trim_default": app.trim_var.get(),
            "neutral_input_default": app.neutral_var.get(),
            "required_size": [root.winfo_reqwidth(), root.winfo_reqheight()],
            "input_struct_size": ctypes.sizeof(INPUT),
        }
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.on_close()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
