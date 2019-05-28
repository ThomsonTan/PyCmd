from __future__ import print_function
import time,ctypes

GVim_hwnd = 0

CF_TEXT = 1
GMEM_MOVEABLE = 0x2
GMEM_ZEROINIT = 0x40
GHND = (GMEM_MOVEABLE | GMEM_ZEROINIT)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GlobalLock = ctypes.windll.kernel32.GlobalLock
GlobalLock.argtypes = (ctypes.c_void_p,)
GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
GlobalUnlock.argtypes = (ctypes.c_void_p,)

GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
GlobalAlloc.restype = ctypes.c_void_p

memcpy = ctypes.cdll.msvcrt.memcpy
memcpy.argtypes = (
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t
    )

user32.SetClipboardData.argtypes = (ctypes.c_uint32, ctypes.c_void_p)
user32.GetClipboardData.restype = ctypes.c_void_p

def ConnectWithGVim():
    global GVim_hwnd
    curr_hwnd = kernel32.GetConsoleWindow()
    gvim_cmd = b"let g:conhwnd=" + str(curr_hwnd).encode()
    print("\nSwitch to GVim and run below command (already in clipboard) ...")
    print("--------------")
    print(gvim_cmd.decode('utf-8'))
    print("--------------")

    # set gvim_cmd to clipboard
    buf = ctypes.c_buffer(gvim_cmd)
    buf_size = ctypes.sizeof(buf)
    hGlobalMem = GlobalAlloc(GHND, buf_size)
    GlobalLock.restype = ctypes.c_void_p
    lpGlobalMem = GlobalLock(hGlobalMem)
    memcpy(lpGlobalMem, ctypes.addressof(buf), buf_size)
    GlobalUnlock(hGlobalMem)

    hwnd = ctypes.wintypes.HWND(0)
    user32.OpenClipboard(hwnd);
    user32.EmptyClipboard();
    user32.SetClipboardData(1, hGlobalMem) # 1 is CF_TEXT
    user32.CloseClipboard();

    buf_len = 1000
    title_text = ctypes.create_unicode_buffer(buf_len)
    for i in range(50):
        time.sleep(0.2)
        f_hwnd = user32.GetForegroundWindow()
        ret_len = user32.GetWindowTextW(f_hwnd, ctypes.byref(title_text), buf_len)
        if ret_len > 0 and (u' - GVIM' in title_text.value) and GVim_hwnd != f_hwnd:
            print("Captured GVim hwnd ", f_hwnd, "\n")
            GVim_hwnd = f_hwnd
            break

def SwitchToGVim():
    if GVim_hwnd != 0:
        SwitchToHwnd(GVim_hwnd)

def SwitchToHwnd(hwnd):
    user32.ShowWindow(hwnd, 5) # SW_SHOW
    user32.SetForegroundWindow(hwnd)

def GetClipboardText():
    text = ''

    hwnd = ctypes.wintypes.HWND(0)
    user32.OpenClipboard(hwnd);
    if user32.IsClipboardFormatAvailable(1): # 1 is CF_TEXT
        data_handle = user32.GetClipboardData(1) # 1 is CF_TEXT
        GlobalLock.restype = ctypes.c_char_p
        text = GlobalLock(ctypes.c_void_p(data_handle))
        GlobalUnlock(data_handle)
    user32.CloseClipboard()

    return text
