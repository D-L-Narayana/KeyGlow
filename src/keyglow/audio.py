"""Captures whatever the PC is playing (WASAPI loopback) and turns it into bands / bass / beats."""
import threading
import time
from collections import deque

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover
    pyaudio = None

NB = 32          # number of frequency bands handed to the effects
FFT = 2048


class _DefaultEndpoint:
    """Asks Windows which playback device is the default one (to notice when it changes)."""

    def __init__(self):
        self._enum = None
        try:
            import ctypes
            import comtypes
            from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

            class IMMDevice(IUnknown):
                _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
                _methods_ = [COMMETHOD([], HRESULT, 'Activate'), COMMETHOD([], HRESULT, 'OpenPropertyStore'),
                             COMMETHOD([], HRESULT, 'GetId', (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppstrId'))]

            class IMMDeviceEnumerator(IUnknown):
                _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
                _methods_ = [COMMETHOD([], HRESULT, 'EnumAudioEndpoints'),
                             COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint', (['in'], ctypes.c_int, 'dataFlow'),
                                       (['in'], ctypes.c_int, 'role'),
                                       (['out'], ctypes.POINTER(ctypes.POINTER(IMMDevice)), 'ppDevice'))]

            comtypes.CoInitialize()
            self._ct = ctypes
            self._enum = comtypes.CoCreateInstance(GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}'),
                                                   IMMDeviceEnumerator, comtypes.CLSCTX_ALL)
        except Exception:
            self._enum = None

    def current_id(self):
        if self._enum is None:
            return 'unknown'
        try:
            dev = self._enum.GetDefaultAudioEndpoint(0, 0)
            p = dev.GetId()
            ct = self._ct
            p = p.value if hasattr(p, 'value') else p
            s = ct.wstring_at(p)
            ct.windll.ole32.CoTaskMemFree(ct.c_void_p(p))
            return s
        except Exception:
            return 'none'


class AudioFrame:
    def __init__(self):
        self.bands = np.zeros(NB)
        self.bass = self.mid = self.treble = self.level = 0.0
        self.beat = False
        self.beat_count = 0
        self.beat_pulse = 0.0


class AudioAnalyzer:
    def __init__(self):
        self.frame = AudioFrame()
        self.device_name = 'no audio'
        self.error = None
        self._ring = np.zeros(16384, np.float32)
        self._w = 0
        self._lock = threading.Lock()
        self._last_cb = 0.0
        self._rate = 48000
        self._pa = None
        self._stream = None
        self._run = False
        self._win = np.hanning(FFT).astype(np.float32)
        self._peak_db = -50.0
        self._lvl_peak = -50.0
        self._sm = np.zeros(NB)
        self._ehist = deque(maxlen=40)
        self._last_beat = 0.0
        self._prev_e = 0.0
        self._setup_bands()

    def _setup_bands(self):
        f = np.geomspace(40, 16000, NB + 1)
        bins = np.round(f * FFT / self._rate).astype(int)
        bins[0] = max(bins[0], 1)
        for i in range(1, len(bins)):
            bins[i] = max(bins[i], bins[i - 1] + 1)
        self._edges = np.minimum(bins, FFT // 2)
        centers = np.sqrt(f[:-1] * f[1:])
        self._tilt = np.sqrt(centers / 100.0)
        self.centers = centers
        self._lo = centers < 160
        self._mid = (centers >= 160) & (centers < 2200)
        self._hi = centers >= 2200
        self._bass_bins = (max(1, int(40 * FFT / self._rate)), max(3, int(160 * FFT / self._rate) + 1))

    # ---- capture -----------------------------------------------------
    def start(self):
        self._run = True
        threading.Thread(target=self._monitor, daemon=True, name='audio-monitor').start()

    def stop(self):
        self._run = False
        self._close()

    def _close(self):
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        try:
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None

    def _default_loopback(self, pa):
        try:
            return pa.get_default_wasapi_loopback()
        except Exception:
            pass
        api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        out = pa.get_device_info_by_index(api['defaultOutputDevice'])
        if out.get('isLoopbackDevice'):
            return out
        for lb in pa.get_loopback_device_info_generator():
            if out['name'] in lb['name']:
                return lb
        raise RuntimeError('no loopback device for ' + out['name'])

    def _open(self):
        self._close()
        pa = pyaudio.PyAudio()
        dev = self._default_loopback(pa)
        ch = max(1, int(dev['maxInputChannels']))
        rate = int(dev['defaultSampleRate'])

        def cb(data, frames, tinfo, status):
            x = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            n = x.size
            ring = self._ring
            with self._lock:
                w = self._w
                end = w + n
                if end <= ring.size:
                    ring[w:end] = x
                else:
                    k = ring.size - w
                    ring[w:] = x[:k]
                    ring[:n - k] = x[k:]
                self._w = end % ring.size
                self._last_cb = time.perf_counter()
            return (None, pyaudio.paContinue)

        self._stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
                               input_device_index=dev['index'], frames_per_buffer=512, stream_callback=cb)
        self._pa = pa
        if rate != self._rate:
            self._rate = rate
            self._setup_bands()
        self.device_name = dev['name'].replace(' [Loopback]', '')
        self._dev_name_raw = dev['name']
        self.error = None

    def _monitor(self):
        if pyaudio is None:
            self.error = 'PyAudioWPatch missing'
            return
        endpoint = _DefaultEndpoint()
        opened_for = None
        while self._run:
            try:
                cur = endpoint.current_id()
                # follow the default playback device (headphones plugged in, etc.)
                if self._stream is None or cur != opened_for or not self._stream.is_active():
                    self._open()
                    opened_for = cur
            except Exception as e:
                self.error = str(e)
                self.device_name = 'no audio'
                self._close()
            for _ in range(30):
                if not self._run:
                    return
                time.sleep(0.1)

    # ---- analysis ----------------------------------------------------
    def analyze(self, dt):
        fr = self.frame
        now = time.perf_counter()
        with self._lock:
            if now - self._last_cb > 0.25:
                x = np.zeros(FFT, np.float32)   # nothing playing: WASAPI loopback goes quiet
            else:
                w = self._w
                idx = np.arange(w - FFT, w) % self._ring.size
                x = self._ring[idx]
        spec = np.abs(np.fft.rfft(x * self._win)) / (FFT / 4)
        e = self._edges
        band = np.maximum.reduceat(spec[:e[-1]], e[:-1]) * self._tilt
        db = 20 * np.log10(band + 1e-9)
        top = float(db.max())
        self._peak_db = max(self._peak_db - 5.0 * dt, top, -52.0)
        rng = 38.0
        norm = np.clip((db - (self._peak_db - rng)) / rng, 0, 1) ** 1.5
        self._sm = np.maximum(norm, self._sm - 3.2 * dt)
        fr.bands = self._sm
        fr.bass = float(self._sm[self._lo].mean())
        fr.mid = float(self._sm[self._mid].mean())
        fr.treble = float(self._sm[self._hi].mean())
        rms_db = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
        self._lvl_peak = max(self._lvl_peak - 4.0 * dt, rms_db, -55.0)
        lvl = float(np.clip((rms_db - (self._lvl_peak - 30.0)) / 30.0, 0, 1))
        fr.level = max(lvl, fr.level - 2.5 * dt)
        # beat = sudden jump of low-frequency energy against its recent average
        b0, b1 = self._bass_bins
        en = float(np.sum(spec[b0:b1] ** 2))
        avg = (sum(self._ehist) / len(self._ehist)) if self._ehist else 0.0
        beat = (len(self._ehist) > 8 and en > 1e-7 and en > avg * 1.4 and en > self._prev_e * 1.05
                and now - self._last_beat > 0.16)
        self._ehist.append(en)
        self._prev_e = en
        fr.beat = beat
        if beat:
            self._last_beat = now
            fr.beat_count += 1
            fr.beat_pulse = 1.0
        else:
            fr.beat_pulse *= float(np.exp(-dt * 5.0))
        return fr
