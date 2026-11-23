"""Render loop: audio -> layers -> keyboard. Runs in its own thread."""
import ctypes
import threading
import time
import traceback

import numpy as np

from .audio import AudioAnalyzer
from .device import DeviceError, open_keyboard
from .effects import EFFECTS, blend
from .layout import Layout
from .screen import ScreenSampler

_user32 = ctypes.WinDLL('user32')

# Measured on the Legion per-key keyboard: the firmware shows about 12 frames a second on this route and
# collapses to 2-6 a second when the PC sends full frames faster than ~20 a second. So the keyboard gets
# 15 frames a second; analysis and the on-screen preview still run at the full rate.
DEVICE_FPS = 15.0


def tone(frame, data):
    """Effect colours -> what is sent to the LEDs. 'glow' makes everything brighter and punchier."""
    g = float(data.get('glow', 0.6))
    v = np.clip(frame, 0, 1)
    if g > 0:
        m = v.max(axis=1, keepdims=True)
        v = v * np.minimum(1.0 + 0.8 * g, 1.0 / np.maximum(m, 1e-3))      # brighter, same hue
    v = np.clip(v * float(data.get('brightness', 1.0)), 0, 1)
    return v ** max(0.5, float(data.get('gamma', 1.6)) - 0.7 * g)


class Ctx:
    pass


class Engine:
    def __init__(self, store, log=lambda m: None):
        self.store = store
        self.log = log
        self.audio = AudioAnalyzer()
        self.screen = ScreenSampler()
        self.dev = None
        self.layout = None
        self.layers = []
        self.output = False
        self.latest = None
        self.fps = 0.0
        self.device_status = 'Looking for keyboard…'
        self.device_ok = False
        self.confirmed = None        # True: the keyboard reports it is showing our colours
        self._states = {}
        self._run = False
        self._thread = None
        self._keys_down = set()
        self._handback_lock = threading.Lock()
        self.frozen = False          # set when Windows is shutting down: never take the lights again

    # ---- lifecycle ---------------------------------------------------
    def start(self):
        self._run = True
        self.audio.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='engine')
        self._thread.start()

    def stop(self):
        """Stop rendering and give the lights back to the keyboard firmware / Legion Space."""
        self._run = False
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        self.hand_back()
        self.audio.stop()

    def session_end(self):
        """Windows is logging off / shutting down: give the lights back now and keep them given back."""
        self.frozen = True
        self.output = False
        self.hand_back()

    def hand_back(self):
        with self._handback_lock:
            dev = self.dev
            if dev is not None:
                try:
                    dev.set_autonomous(True)
                except Exception:
                    pass

    def set_layers(self, layers):
        self.layers = layers
        ids = {l['id'] for l in layers}
        for k in list(self._states):
            if k not in ids:
                del self._states[k]

    def _open(self):
        try:
            dev = open_keyboard()
            dev.set_autonomous(True)     # known state; also recovers from a previous crash
            lamps = dev.read_lamps()
            self.layout = Layout(lamps)
            self.dev = dev
            self.device_ok = True
            self.device_status = 'Keyboard connected · %d lights' % dev.count
        except Exception as e:
            self.device_ok = False
            self.device_status = 'Keyboard not available: %s' % e

    def _pressed(self):
        L = self.layout
        down = set()
        for vk, lamp in L.vk_to_lamp.items():
            if _user32.GetAsyncKeyState(vk) & 0x8000:
                down.add(lamp)
        new = down - self._keys_down
        self._keys_down = down
        return list(new)

    # ---- rendering ---------------------------------------------------
    def compose(self, ctx):
        L = self.layout
        out = np.zeros((L.n, 3))
        for l in self.layers:
            if not l.get('on', True):
                continue
            fx = EFFECTS.get(l['effect'])
            if fx is None:
                continue
            zones = l.get('zones') or []
            if not zones:
                continue
            mask = np.zeros(L.n, bool)
            for z in zones:
                mask |= L.zone_mask[z]
            st = self._states.setdefault(l['id'], {})
            try:
                col = fx['func'](ctx, l['params'], st)
            except Exception:
                st.clear()
                self.log(traceback.format_exc())
                continue
            blend(out, col, l.get('blend', 'Add'), float(l.get('opacity', 1.0)), mask)
        return np.clip(out, 0, 1)

    def _loop(self):
        ctx = Ctx()
        ctx.screen = self.screen.get
        t0 = last = time.perf_counter()
        retry = 0.0
        alive = 0.0
        sent_at = 0.0
        frames, ftime = 0, t0
        while self._run:
            now = time.perf_counter()
            gap = now - last
            dt = min(0.1, gap)
            last = now
            if self.dev is None and now >= retry:
                self._open()
                retry = now + 2.5
            if self.layout is None:
                time.sleep(0.2)
                continue
            data = self.store.data
            ctx.L, ctx.t, ctx.dt = self.layout, now - t0, dt
            ctx.a = self.audio.analyze(dt)
            ctx.pressed = self._pressed() if any(l['effect'] == 'ripple' and l.get('on', True) for l in self.layers) else []
            frame = self.compose(ctx)
            self.latest = frame
            dev = self.dev
            if dev is not None:
                try:
                    if self.output and not self.frozen:
                        if not dev.host_mode or gap > 1.5:      # first frame, or the PC just woke up
                            dev.set_autonomous(False)
                            self.confirmed = dev.verify()
                            alive = time.perf_counter()
                        elif now - alive > 2.0:
                            dev.keepalive()
                            alive = now
                        if now - sent_at >= max(1.0 / DEVICE_FPS, dev.min_interval_us / 1e6) - 0.004:
                            sent_at = now
                            v = tone(frame, data)
                            dev.send((v * 255 + 0.5).astype(np.uint8))
                    elif dev.host_mode:
                        dev.set_autonomous(True)
                        self.confirmed = None
                except DeviceError as e:
                    self.log('device: %s' % e)
                    self.device_ok = False
                    self.device_status = 'Keyboard connection lost – retrying…'
                    try:
                        dev.close(hand_back=False)
                    except Exception:
                        pass
                    self.dev = None
                    retry = time.perf_counter() + 1.5
            frames += 1
            if now - ftime >= 1.0:
                self.fps = frames / (now - ftime)
                frames, ftime = 0, now
            interval = 1.0 / max(10, min(60, int(data.get('fps', 30))))
            if dev is not None:
                interval = max(interval, dev.min_interval_us / 1e6)
            rest = interval - (time.perf_counter() - now)
            if rest > 0:
                time.sleep(rest)
