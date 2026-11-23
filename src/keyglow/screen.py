"""Low-rate, heavily downscaled capture of the primary monitor for the Screen Ambient effect."""
import threading
import time

import numpy as np


class ScreenSampler:
    def __init__(self):
        self.image = None          # float array (h, w, 3) 0..1
        self._want = 0.0
        self._thread = None
        self.error = None

    def get(self):
        self._want = time.perf_counter()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name='screen')
            self._thread.start()
        return self.image

    def _loop(self):
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                mon = sct.monitors[1]
                factor = max(1, int(mon['width'] / 64))
                while time.perf_counter() - self._want < 2.0:   # stops by itself when no layer uses it
                    t = time.perf_counter()
                    shot = sct.grab(mon)
                    img = Image.frombuffer('RGB', shot.size, shot.bgra, 'raw', 'BGRX').reduce(factor)
                    self.image = np.asarray(img, np.float32) / 255.0
                    time.sleep(max(0.0, 0.045 - (time.perf_counter() - t)))
        except Exception as e:
            self.error = str(e)
        self.image = None if self.error else self.image
