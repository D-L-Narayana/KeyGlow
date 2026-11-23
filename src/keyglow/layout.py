"""Turns the lamp list reported by the keyboard into coordinates the effects can use."""
import numpy as np

ZONES = ['keys', 'rear', 'front', 'logo']
ZONE_LABEL = {'keys': 'Keys', 'rear': 'Rear lights', 'front': 'Front bar', 'logo': 'Logo'}

# HID keyboard usage -> Windows virtual key (for the typing effect)
HID_TO_VK = {}
for _i in range(26):
    HID_TO_VK[0x04 + _i] = 0x41 + _i
for _i in range(9):
    HID_TO_VK[0x1E + _i] = 0x31 + _i
HID_TO_VK.update({0x27: 0x30, 0x28: 0x0D, 0x29: 0x1B, 0x2A: 0x08, 0x2B: 0x09, 0x2C: 0x20, 0x2D: 0xBD, 0x2E: 0xBB,
                  0x2F: 0xDB, 0x30: 0xDD, 0x31: 0xDC, 0x33: 0xBA, 0x34: 0xDE, 0x35: 0xC0, 0x36: 0xBC, 0x37: 0xBE,
                  0x38: 0xBF, 0x39: 0x14, 0x46: 0x2C, 0x49: 0x2D, 0x4A: 0x24, 0x4B: 0x21, 0x4C: 0x2E, 0x4D: 0x23,
                  0x4E: 0x22, 0x4F: 0x27, 0x50: 0x25, 0x51: 0x28, 0x52: 0x26, 0x53: 0x90, 0x54: 0x6F, 0x55: 0x6A,
                  0x56: 0x6D, 0x57: 0x6B, 0x62: 0x60, 0x63: 0x6E, 0xE0: 0xA2, 0xE1: 0xA0, 0xE2: 0xA4, 0xE3: 0x5B,
                  0xE4: 0xA3, 0xE5: 0xA1, 0xE6: 0xA5})
for _i in range(12):
    HID_TO_VK[0x3A + _i] = 0x70 + _i
for _i in range(9):
    HID_TO_VK[0x59 + _i] = 0x61 + _i


class Layout:
    def __init__(self, lamps):
        a = np.array([(l[0], l[1], l[2]) for l in lamps], float)
        self.n = len(lamps)
        self.x, self.y, self.z = a[:, 0], a[:, 1], a[:, 2]
        purp = np.array([l[3] for l in lamps])
        self.bind = [l[4] for l in lamps]
        is_key = (purp & 1) > 0
        if not is_key.any():
            is_key = np.ones(self.n, bool)
        self.is_key = is_key
        ky = self.y[is_key]
        kx = self.x[is_key]
        ymid = (ky.min() + ky.max()) / 2
        zone = np.zeros(self.n, int)
        zone[~is_key & ((purp & 4) > 0)] = 3
        other = ~is_key & ((purp & 4) == 0)
        zone[other & (self.y < ymid)] = 1
        zone[other & (self.y >= ymid)] = 2
        self.zone = zone
        self.zone_mask = {name: zone == i for i, name in enumerate(ZONES)}

        x0, x1 = kx.min(), kx.max()
        y0, y1 = ky.min(), ky.max()
        w = max(x1 - x0, 1e-6)
        hgt = max(y1 - y0, 1e-6)
        self.aspect = hgt / w
        # ku: 0 left .. 1 right, kv: 0 bottom row .. 1 top row (strips get their own position along the strip)
        ku = np.clip((self.x - x0) / w, 0, 1)
        kv = np.clip(1 - (self.y - y0) / hgt, 0, 1)
        for zi in (1, 2, 3):
            m = zone == zi
            if m.any():
                zx = self.x[m]
                ku[m] = (zx - zx.min()) / max(zx.max() - zx.min(), 1e-6)
                kv[m] = 1.0 if zi != 2 else 0.0
        self.ku, self.kv = ku, kv
        # physical coordinates in keyboard widths (for rings, plasma, wipes)
        self.px = (self.x - x0) / w
        self.py = (self.y - y0) / w
        m = zone == 3  # the logo is not on the deck: treat it as sitting above the keyboard centre
        if m.any():
            self.px[m] = 0.3 + 0.4 * ku[m]
            self.py[m] = -0.12
        self.cx, self.cy = 0.5, self.aspect / 2
        self.pymin, self.pymax = float(self.py.min()), float(self.py.max())
        self.key_ids = np.nonzero(is_key)[0]
        self.vk_to_lamp = {}
        for i, b in enumerate(self.bind):
            vk = HID_TO_VK.get(b)
            if vk and is_key[i]:
                self.vk_to_lamp.setdefault(vk, i)

    def preview_rects(self):
        """(rectangles, total_height): x0, y0, x1, y1 in keyboard-width units, for the on-screen preview."""
        rects = [None] * self.n
        kid = self.key_ids
        xs, ys = self.px, self.py
        sc, pad, top = 0.94, 0.03, 0.085
        rows = {}
        for i in kid:
            rows.setdefault(round(ys[i] / 0.012), []).append(i)
        pitch = 0.0585
        for r in rows.values():
            r.sort(key=lambda i: xs[i])
            for j, i in enumerate(r):
                left = (xs[i] + xs[r[j - 1]]) / 2 if j > 0 else xs[i] - pitch / 2
                right = (xs[i] + xs[r[j + 1]]) / 2 if j < len(r) - 1 else xs[i] + pitch / 2
                left = max(left, xs[i] - pitch * 1.9)
                right = min(right, xs[i] + pitch * 1.9)
                g = 0.004
                rects[i] = (pad + (left + g) * sc, top + (ys[i] + g) * sc,
                            pad + (right - g) * sc, top + (ys[i] + pitch - g) * sc)
        kbot = top + (self.aspect + pitch) * sc
        total = kbot + 0.05
        for zi, (ya, yb) in ((1, (0.006, 0.044)), (2, (kbot + 0.014, kbot + 0.032))):
            ids = np.nonzero(self.zone == zi)[0]
            if not ids.size:
                continue
            zz = self.z[ids]
            zr = max(zz.max() - zz.min(), 1e-6)
            xx = np.clip(xs[ids], -0.03, 1.03)
            for i, u, zv in zip(ids, xx, zz):
                cx = pad + u * sc
                cy = ya + (yb - ya) * (1 - (zv - zz.min()) / zr) if zi == 1 else (ya + yb) / 2
                hw = 0.005 if zi == 1 else 0.0075
                hh = 0.005 if zi == 1 else (yb - ya) / 2
                rects[i] = (cx - hw, cy - hh, cx + hw, cy + hh)
        ids = np.nonzero(self.zone == 3)[0]
        for j, i in enumerate(ids):
            u = self.ku[i]
            cx = 0.5 + (u - 0.5) * 0.14
            rects[i] = (cx - 0.003, 0.054, cx + 0.003, 0.07)
        return rects, total
