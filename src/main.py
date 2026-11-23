"""KeyGlow entry point."""
import atexit
import ctypes
import os
import sys
import time
import traceback


def guard(pid):
    """Tiny helper process: waits until KeyGlow (pid) is gone - closed, crashed or killed - and then gives
    the lights back to the keyboard, so it can never be left stuck on KeyGlow's last frame."""
    k32 = ctypes.WinDLL('kernel32')
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    h = k32.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(h, 0xFFFFFFFF)
    from keyglow.device import open_keyboard
    for _ in range(3):
        try:
            dev = open_keyboard()
            dev.close(hand_back=True)
            return
        except Exception:
            time.sleep(0.5)


def start_guard():
    import subprocess
    args = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, os.path.abspath(__file__)]
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    try:
        subprocess.Popen(args + ['--guard', str(os.getpid())], env=env, close_fds=True,
                         creationflags=0x00000008 | 0x08000000 | 0x00000200)   # detached, no window, own group
    except Exception:
        pass


def main():
    if '--guard' in sys.argv:
        try:
            guard(int(sys.argv[sys.argv.index('--guard') + 1]))
        except Exception:
            pass
        return
    from keyglow import APP_NAME
    from keyglow.store import DIR, LOG, Store

    os.makedirs(DIR, exist_ok=True)

    def log(msg):
        try:
            if os.path.exists(LOG) and os.path.getsize(LOG) > 512000:
                os.remove(LOG)
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write('%s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
        except Exception:
            pass

    sys.excepthook = lambda t, v, tb: log(''.join(traceback.format_exception(t, v, tb)))

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # one copy only: two copies would both try to drive the keyboard
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\KeyGlow_single_instance')
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, 'KeyGlow is already running.', APP_NAME, 0x40)
        return

    import tkinter as tk

    from keyglow.app import App
    from keyglow.engine import Engine

    store = Store()
    engine = Engine(store, log=log)
    atexit.register(engine.hand_back)      # always give the lights back, even on an unexpected exit
    start_guard()                          # ...and also if this process is killed outright
    engine.start()
    root = tk.Tk()
    root.report_callback_exception = lambda t, v, tb: log(''.join(traceback.format_exception(t, v, tb)))
    App(root, store, engine)
    try:
        root.mainloop()
    finally:
        engine.stop()
        store.save()
    del mutex


if __name__ == '__main__':
    main()
