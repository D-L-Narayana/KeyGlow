"""Keyboard lighting access.

Two things are needed on Legion per-key keyboards:
  1. Lenovo's own mode switch (vendor HID report 07 AA 01 00 xx on the keyboard controller). It tells the
     firmware who drives the lights: 0 = the PC ('Dynamic Lighting'), 1 = the keyboard itself (its Legion
     Space profile). Without it the firmware ignores every colour the PC sends.
  2. The standard HID LampArray (usage page 0x59) interface, which carries the per-lamp colours.

Nothing is written to firmware storage and no Legion Space profile is touched: when we stop, the switch
is put back and the keyboard carries on with the profile it was showing.
"""
import ctypes
import struct
import threading
import time
from ctypes import POINTER, byref, c_long, c_ubyte, c_ulong, c_ushort, c_void_p, c_wchar_p, sizeof

import numpy as np

_setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
_hid = ctypes.WinDLL('hid', use_last_error=True)
_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_INVALID = c_void_p(-1).value


class _GUID(ctypes.Structure):
    _fields_ = [('a', c_ulong), ('b', c_ushort), ('c', c_ushort), ('d', c_ubyte * 8)]


class _SPDID(ctypes.Structure):
    _fields_ = [('cbSize', c_ulong), ('guid', _GUID), ('flags', c_ulong), ('res', c_void_p)]


class _CAPS(ctypes.Structure):
    _fields_ = [('Usage', c_ushort), ('UsagePage', c_ushort), ('InLen', c_ushort), ('OutLen', c_ushort),
                ('FeatLen', c_ushort), ('Reserved', c_ushort * 17), ('Counts', c_ushort * 10)]


_setupapi.SetupDiGetClassDevsW.restype = c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = [POINTER(_GUID), c_wchar_p, c_void_p, c_ulong]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [c_void_p, c_void_p, POINTER(_GUID), c_ulong, POINTER(_SPDID)]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [c_void_p, POINTER(_SPDID), c_void_p, c_ulong, POINTER(c_ulong), c_void_p]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
_k32.CreateFileW.restype = c_void_p
_k32.CreateFileW.argtypes = [c_wchar_p, c_ulong, c_ulong, c_void_p, c_ulong, c_ulong, c_void_p]
_k32.CloseHandle.argtypes = [c_void_p]
_hid.HidD_GetPreparsedData.argtypes = [c_void_p, POINTER(c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [c_void_p]
_hid.HidP_GetCaps.argtypes = [c_void_p, POINTER(_CAPS)]
_hid.HidD_GetFeature.argtypes = [c_void_p, c_void_p, c_ulong]
_hid.HidD_SetFeature.argtypes = [c_void_p, c_void_p, c_ulong]

R_ATTR, R_REQ, R_RESP, R_MULTI, R_RANGE, R_CONTROL = 1, 2, 3, 4, 5, 6
SLOTS = 8


class DeviceError(Exception):
    pass


def _hid_paths():
    g = _GUID()
    _hid.HidD_GetHidGuid(byref(g))
    hdev = _setupapi.SetupDiGetClassDevsW(byref(g), None, None, 0x12)
    out, i = [], 0
    while True:
        did = _SPDID()
        did.cbSize = sizeof(_SPDID)
        if not _setupapi.SetupDiEnumDeviceInterfaces(hdev, None, byref(g), i, byref(did)):
            break
        i += 1
        need = c_ulong(0)
        _setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, byref(did), None, 0, byref(need), None)
        if not need.value:
            continue
        buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(buf, POINTER(c_ulong))[0] = 8
        if _setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, byref(did), buf, need, None, None):
            out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    _setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def find_lamparrays():
    """Return [(path, feature_report_length)] of every HID LampArray on the system."""
    found = []
    for p in _hid_paths():
        h = _k32.CreateFileW(p, 0, 3, None, 3, 0, None)
        if not h or h == _INVALID:
            continue
        pp = c_void_p()
        try:
            if _hid.HidD_GetPreparsedData(h, byref(pp)):
                c = _CAPS()
                _hid.HidP_GetCaps(pp, byref(c))
                _hid.HidD_FreePreparsedData(pp)
                if c.UsagePage == 0x59 and c.Usage == 0x01 and c.FeatLen >= 3 + SLOTS * 6:
                    found.append((p, c.FeatLen))
        finally:
            _k32.CloseHandle(h)
    return found


class VendorSwitch:
    """Lenovo vendor channel of the keyboard controller (usage page 0xFF89, 960-byte feature reports)."""
    N = 960

    def __init__(self, path, handle):
        self.path, self.h = path, handle

    @classmethod
    def find(cls):
        for p in _hid_paths():
            if 'vid_048d' not in p.lower():
                continue
            h = _k32.CreateFileW(p, 0xC0000000, 3, None, 3, 0, None)
            if not h or h == _INVALID:
                continue
            ok = False
            pp = c_void_p()
            if _hid.HidD_GetPreparsedData(h, byref(pp)):
                c = _CAPS()
                _hid.HidP_GetCaps(pp, byref(c))
                _hid.HidD_FreePreparsedData(pp)
                ok = c.UsagePage == 0xFF89 and c.FeatLen == cls.N
            if ok:
                sw = cls(p, h)
                if sw._get() is not None:        # only the real keyboard controller answers this
                    return sw
            _k32.CloseHandle(h)
        return None

    def _get(self):
        buf = (c_ubyte * self.N)()
        buf[0] = 7
        return bytes(buf) if _hid.HidD_GetFeature(self.h, buf, self.N) else None

    def host(self, on):
        """on=True: the PC drives the lights. on=False: the keyboard runs its own profile again."""
        buf = (c_ubyte * self.N)(7, 0xAA, 1, 0, 0 if on else 1)
        return bool(_hid.HidD_SetFeature(self.h, buf, self.N))

    def state(self):
        """What the firmware is really showing: {zone code: (r, g, b)} or None."""
        b = self._get()
        if b is None:
            return None
        out = {}
        for i in range(4, self.N - 4, 5):
            k = b[i] | (b[i + 1] << 8)
            if k:
                out[k] = (b[i + 2], b[i + 3], b[i + 4])
        return out

    def close(self):
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None


class LampArray:
    def __init__(self, path, feat_len):
        self.path, self.fl = path, feat_len
        self.switch = None
        self._lock = threading.Lock()
        self.h = _k32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)
        if not self.h or self.h == _INVALID:
            raise DeviceError('cannot open LampArray (error %d)' % ctypes.get_last_error())
        d = self._get(R_ATTR)
        (_, self.count, self.width, self.height, self.depth, self.kind, self.min_interval_us) = struct.unpack_from('<BHiiiii', d, 0)
        if not 0 < self.count <= 4096:
            raise DeviceError('unexpected lamp count %r' % self.count)
        self.intensity = 255     # full scale; the reported 'level count' is not a value to send
        self._last = np.full((self.count, 3), -1000, np.int16)
        self._rot = 0
        self.host_mode = False

    # ---- raw reports -------------------------------------------------
    def _set(self, data):
        buf = (c_ubyte * self.fl)(*bytes(data).ljust(self.fl, b'\0')[:self.fl])
        if not _hid.HidD_SetFeature(self.h, buf, self.fl):
            raise DeviceError('SetFeature %d failed (error %d)' % (data[0], ctypes.get_last_error()))

    def _get(self, rid):
        buf = (c_ubyte * self.fl)()
        buf[0] = rid
        if not _hid.HidD_GetFeature(self.h, buf, self.fl):
            raise DeviceError('GetFeature %d failed (error %d)' % (rid, ctypes.get_last_error()))
        return bytes(buf)

    # ---- layout ------------------------------------------------------
    def read_lamps(self):
        """[(x_m, y_m, z_m, purposes, input_binding)] for every lamp (read only)."""
        lamps = [None] * self.count
        with self._lock:
            self._set(bytes([R_REQ]) + struct.pack('<H', 0))
            want = 0
            guard = 0
            while want < self.count and guard < self.count * 3:
                guard += 1
                d = self._get(R_RESP)
                (_, lid, x, y, z, _lat, purp, _r, _g, _b, inten, _prog, bind) = struct.unpack_from('<BHiiiiiBBBBBB', d, 0)
                if lid != want:
                    self._set(bytes([R_REQ]) + struct.pack('<H', want))
                    continue
                lamps[lid] = (x / 1e6, y / 1e6, z / 1e6, purp, bind)
                want += 1
        if any(l is None for l in lamps):
            raise DeviceError('could not read lamp layout')
        return lamps

    # ---- control -----------------------------------------------------
    def set_autonomous(self, on):
        """on=True gives the lights back to the keyboard firmware / Legion Space."""
        with self._lock:
            if on:
                try:
                    self._set(bytes([R_CONTROL, 1]))
                finally:
                    self.host_mode = False
                    self._last[:] = -1000
                    if self.switch:
                        self.switch.host(False)
            else:
                if self.switch:
                    self.switch.host(True)
                    time.sleep(0.05)
                self._set(bytes([R_CONTROL, 0]))
                self.host_mode = True

    def keepalive(self):
        """Re-assert control (harmless while we already have it; recovers after sleep or a Legion hotkey)."""
        with self._lock:
            if self.switch:
                self.switch.host(True)
            self._set(bytes([R_CONTROL, 0]))

    def verify(self):
        """Ask the keyboard what it is showing. True = it shows what we sent, False = it does not,
        None = this keyboard cannot be asked. Uses a near-black test frame (about 0.15 s)."""
        if not self.switch:
            return None
        n = self.count
        idx = np.arange(n)
        rgb = np.empty((n, 3), np.uint8)
        rgb[:, 0] = idx % 16 + 2
        rgb[:, 1] = idx // 16 + 2
        rgb[:, 2] = 9
        result = None
        for attempt in range(4):
            self._last[:] = -1000
            self.send(rgb, threshold=0)
            time.sleep(0.07 + 0.08 * attempt)
            st = self.switch.state()
            if st is None:
                break
            keys = [c for k, c in st.items() if k < 500] or list(st.values())
            good = sum(1 for r, g, b in keys if b == 9 and r >= 2 and g >= 2 and (r - 2) + (g - 2) * 16 < n)
            result = good >= 0.8 * len(keys)
            if result:
                break
            self.keepalive()
        self._last[:] = -1000
        return result

    def send(self, rgb, threshold=2):
        """Send a frame (uint8 Nx3). Only lamps that changed are transmitted. Returns report count."""
        n = self.count
        diff = np.abs(rgb.astype(np.int16) - self._last).max(axis=1)
        mask = diff > threshold
        # slowly re-send everything so the keyboard recovers after sleep / Fn shortcuts
        mask[self._rot:self._rot + SLOTS] = True
        self._rot = (self._rot + SLOTS) % n
        ids = np.nonzero(mask)[0]
        if not ids.size:
            return 0
        inten = self.intensity
        with self._lock:
            if ids.size == n and not (rgb != rgb[0]).any():
                c = rgb[0]
                self._set(bytes([R_RANGE, 1]) + struct.pack('<HH', 0, n - 1) + bytes([int(c[0]), int(c[1]), int(c[2]), inten]))
                sent = 1
            else:
                sent = 0
                buf = bytearray(self.fl)
                cbuf = (c_ubyte * self.fl).from_buffer(buf)
                total = ids.size
                for s in range(0, total, SLOTS):
                    chunk = ids[s:s + SLOTS]
                    k = chunk.size
                    buf[:] = bytes(self.fl)
                    buf[0], buf[1], buf[2] = R_MULTI, k, 1 if s + SLOTS >= total else 0
                    struct.pack_into('<%dH' % k, buf, 3, *chunk.tolist())
                    col = np.empty((k, 4), np.uint8)
                    col[:, :3] = rgb[chunk]
                    col[:, 3] = inten
                    buf[3 + SLOTS * 2:3 + SLOTS * 2 + k * 4] = col.tobytes()
                    if not _hid.HidD_SetFeature(self.h, cbuf, self.fl):
                        raise DeviceError('frame write failed (error %d)' % ctypes.get_last_error())
                    sent += 1
            self._last[ids] = rgb[ids]
        return sent

    def close(self, hand_back=True):
        if self.h:
            if hand_back:
                try:
                    self.set_autonomous(True)
                except DeviceError:
                    pass
            _k32.CloseHandle(self.h)
            self.h = None
        if self.switch:
            self.switch.close()
            self.switch = None


def open_keyboard():
    arrays = find_lamparrays()
    if not arrays:
        raise DeviceError('No HID LampArray keyboard found')
    # prefer the ITE (048D) controller used by Legion keyboards
    arrays.sort(key=lambda a: 0 if 'vid_048d' in a[0].lower() else 1)
    last = None
    for path, fl in arrays:
        try:
            la = LampArray(path, fl)
        except DeviceError as e:
            last = e
            continue
        if 'vid_048d' in path.lower():
            la.switch = VendorSwitch.find()
        return la
    raise last
