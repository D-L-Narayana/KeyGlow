"""All lighting effects. Each one is a function (ctx, params, state) -> float array (lamps, 3) in 0..1.

ctx.L  = Layout (lamp coordinates)      ctx.a = AudioFrame (bands, bass, mid, treble, level, beats)
ctx.t  = seconds since start             ctx.dt = seconds since last frame
"""
import numpy as np

from .audio import NB

rng = np.random.default_rng()

PALETTES = {
    'Neon': ['#00f0ff', '#2b6bff', '#a020ff', '#ff1fa8'],
    'Synthwave': ['#ff2bd6', '#8a2bff', '#2b5bff', '#00e5ff'],
    'Fire': ['#ff1a00', '#ff6a00', '#ffc400', '#fff3b0'],
    'Lava': ['#7a0000', '#ff0000', '#ff5a00', '#ffb000'],
    'Ocean': ['#001a8c', '#0066ff', '#00c8ff', '#7dffe6'],
    'Aurora': ['#00ff87', '#00d0ff', '#5a5aff', '#c04dff'],
    'Sunset': ['#ff3d3d', '#ff7a1a', '#ffc21a', '#ff4fa3', '#7a3cff'],
    'Rainbow': ['#ff0000', '#ffcc00', '#00ff40', '#00e5ff', '#2040ff', '#ff00d0'],
    'Ice': ['#1030ff', '#3aa0ff', '#9fe8ff', '#ffffff'],
    'Toxic': ['#00ffc8', '#00ff6a', '#b6ff00', '#fff200'],
    'Candy': ['#ff5fa2', '#ffd166', '#06d6a0', '#4cc9f0', '#b388ff'],
    'Blood Moon': ['#3a0000', '#b00020', '#ff2a2a', '#ff9a6a'],
    'White': ['#ffffff', '#ffffff'],
}


def hex_rgb(h):
    h = str(h).lstrip('#')
    try:
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except Exception:
        return [1.0, 1.0, 1.0]


_cache = {}


def stops_of(p):
    key = p if isinstance(p, str) else tuple(p)
    a = _cache.get(key)
    if a is None:
        lst = PALETTES.get(p, PALETTES['Neon']) if isinstance(p, str) else (list(p) or ['#ffffff'])
        a = np.array([hex_rgb(h) for h in lst], float)
        if len(a) == 1:
            a = np.vstack([a, a])
        if len(_cache) > 300:
            _cache.clear()
        _cache[key] = a
    return a


def pal(p, x):
    """Palette lookup, x clamped to 0..1."""
    a = stops_of(p)
    x = np.clip(np.asarray(x, float), 0, 1)
    pos = np.linspace(0, 1, len(a))
    return np.stack([np.interp(x, pos, a[:, c]) for c in range(3)], axis=-1)


def palc(p, x):
    """Palette lookup that wraps around (for scrolling colours)."""
    a = stops_of(p)
    a = np.vstack([a, a[:1]])
    x = np.mod(np.asarray(x, float), 1.0)
    pos = np.linspace(0, 1, len(a))
    return np.stack([np.interp(x, pos, a[:, c]) for c in range(3)], axis=-1)


_BANDPOS = np.linspace(0, 1, NB)


def _spectrum(c, p, s):
    """Band values with per-layer gain and fall speed."""
    b = np.clip(c.a.bands * p['gain'], 0, 1)
    sm = s.get('sm')
    if sm is None:
        sm = b.copy()
    sm = np.maximum(b, sm - p.get('fall', 2.0) * c.dt)
    s['sm'] = sm
    return sm


def _env(s, key, value, fall, dt):
    v = max(value, s.get(key, 0.0) - fall * dt)
    s[key] = v
    return v


# ---------------------------------------------------------------- audio effects
def fx_spectrum(c, p, s):
    L = c.L
    sm = _spectrum(c, p, s)
    pos = L.ku
    if p['layout'] == 'Bass in the middle':
        pos = np.abs(pos - 0.5) * 2
    elif p['layout'] == 'Bass on the right':
        pos = 1 - pos
    h = np.interp(pos, _BANDPOS, sm)
    lit = np.where(L.is_key, np.clip((h * 1.12 - L.kv) / 0.17, 0, 1), h)
    if p['color_by'] == 'Height':
        col = pal(p['palette'], np.where(L.is_key, L.kv, h))
    elif p['color_by'] == 'Frequency':
        col = pal(p['palette'], pos)
    else:
        col = pal(p['palette'], h)
    out = col * lit[:, None]
    if p['caps']:
        pk = s.get('pk')
        if pk is None:
            pk = sm.copy()
        pk = np.maximum(sm, pk - 0.9 * c.dt)
        s['pk'] = pk
        hp = np.interp(pos, _BANDPOS, pk) * 1.12
        cap = L.is_key & (np.abs(hp - L.kv - 0.085) < 0.09) & (hp > 0.12)
        out[cap] = np.maximum(out[cap], 0.85)
    if p['glow'] > 0:
        out = np.maximum(out, col * p['glow'])
    return out


def fx_shockwave(c, p, s):
    L, a = c.L, c.a
    rings = s.setdefault('rings', [])
    if a.beat_count != s.get('bc', a.beat_count):
        if p['origin'] == 'Random key':
            i = int(rng.choice(L.key_ids))
            ox, oy = L.px[i], L.py[i]
        elif p['origin'] == 'Bottom centre':
            ox, oy = L.cx, L.aspect
        else:
            ox, oy = L.cx, L.cy
        s['ci'] = (s.get('ci', rng.random()) + 0.19) % 1.0
        rings.append([0.0, 1.0, s['ci'], ox, oy])
        del rings[:-8]
    s['bc'] = a.beat_count
    out = np.zeros((L.n, 3))
    keep = []
    width = max(0.01, p['width'])
    for r in rings:
        r[0] += p['speed'] * c.dt
        r[1] *= float(np.exp(-c.dt * p['fade']))
        if r[1] < 0.03 or r[0] > 1.6:
            continue
        keep.append(r)
        d = np.hypot(L.px - r[3], L.py - r[4])
        g = np.exp(-((d - r[0]) / width) ** 2) * r[1]
        if p['fill'] > 0:
            g = g + (d < r[0]) * r[1] * p['fill']
        out += palc(p['palette'], r[2])[None, :] * g[:, None]
    s['rings'] = keep
    return out


def fx_pulse(c, p, s):
    L, a = c.L, c.a
    src = {'Bass': a.bass, 'Mids': a.mid, 'Treble': a.treble, 'Overall': a.level}[p['source']]
    env = _env(s, 'env', min(1.0, src * p['gain']), p['fall'], c.dt)
    s['ph'] = s.get('ph', 0.0) + c.dt * p['drift'] * 0.1
    col = palc(p['palette'], s['ph'] + L.px * p['spread'])
    out = col * (p['floor'] + (1 - p['floor']) * env ** 1.5)
    if p['sparkle'] > 0:
        sp = s.get('sp')
        if sp is None:
            sp = np.zeros(L.n)
        sp *= float(np.exp(-c.dt * 7.0))
        k = rng.poisson(min(40.0, a.treble * p['gain'] * p['sparkle'] * 90.0 * c.dt))
        if k:
            sp[rng.integers(0, L.n, k)] = 1.0
        s['sp'] = sp
        out = out + sp[:, None] * 0.9
    return out


def fx_waterfall(c, p, s):
    L = c.L
    sm = _spectrum(c, p, s)
    depth = 22
    hist = s.get('hist')
    if hist is None:
        hist = np.zeros((depth, NB))
        s['acc'] = 0.0
    s['acc'] += c.dt * p['speed']
    while s['acc'] >= 1.0:
        s['acc'] -= 1.0
        hist = np.roll(hist, 1, axis=0)
    hist[0] = sm
    s['hist'] = hist
    d = p['direction']
    if d in ('Down', 'Up'):
        along = (1 - L.kv) if d == 'Down' else L.kv
        across, span = L.ku, 6.5
    else:
        along = L.ku if d == 'Right' else 1 - L.ku
        across, span = 1 - L.kv, 19.0
    along = np.where(L.is_key, along, 0.0)
    across = np.where(L.is_key, across, L.ku)
    f = along * span + s['acc']
    i0 = np.clip(f.astype(int), 0, depth - 2)
    fr = np.clip(f - i0, 0, 1)
    bi = np.clip(np.round(across * (NB - 1)).astype(int), 0, NB - 1)
    val = hist[i0, bi] * (1 - fr) + hist[i0 + 1, bi] * fr
    return pal(p['palette'], val) * (val ** 1.3)[:, None]


def fx_beatwipe(c, p, s):
    L, a = c.L, c.a
    if 'cur' not in s:
        s.update(cur=rng.random(), prev=rng.random(), dir=0, prog=2.0, fl=0.0)
    if a.beat_count != s.get('bc', a.beat_count):
        s['prev'] = s['cur']
        s['cur'] = (s['cur'] + 0.23 + 0.25 * rng.random()) % 1.0
        s['dir'] = int(rng.integers(0, 6)) if p['direction'] == 'Random' else \
            ['Left to right', 'Right to left', 'Top to bottom', 'Bottom to top', 'Centre out', 'Edges in'].index(p['direction'])
        s['prog'] = 0.0
        s['fl'] = 1.0
    s['bc'] = a.beat_count
    s['prog'] += c.dt * p['speed']
    s['fl'] *= float(np.exp(-c.dt * p['fade']))
    span = max(L.pymax - L.pymin, 1e-6)
    rad = np.hypot(L.px - L.cx, L.py - L.cy) / 0.62
    coord = [L.px, 1 - L.px, (L.py - L.pymin) / span, 1 - (L.py - L.pymin) / span, rad, 1 - rad][s['dir']]
    front = s['prog'] * 1.35
    m = np.clip((front - coord) / 0.14, 0, 1)[:, None]
    col = palc(p['palette'], s['prev'])[None, :] * (1 - m) + palc(p['palette'], s['cur'])[None, :] * m
    out = col * (p['floor'] + (1 - p['floor']) * s['fl'])
    if p['edge'] > 0 and s['prog'] < 1.3:
        e = np.exp(-((front - coord - 0.07) / 0.07) ** 2)
        out = out + e[:, None] * p['edge']
    return out


def fx_rain(c, p, s):
    L, a = c.L, c.a
    d = s.get('d')
    if d is None:
        d = np.zeros((0, 4))
    react = p['react']
    rate = p['rate'] * ((1 - react) + react * 3.0 * min(1.0, a.treble * p['gain'] + 0.5 * a.mid * p['gain']))
    k = min(12, int(rng.poisson(max(0.0, rate * c.dt))))
    if k:
        new = np.column_stack([rng.random(k), np.full(k, L.pymin - 0.03), p['speed'] * (0.7 + 0.6 * rng.random(k)), rng.random(k)])
        d = np.vstack([d, new])
    d[:, 1] += d[:, 2] * c.dt
    tail = max(0.03, p['tail'])
    d = d[d[:, 1] - tail < L.pymax + 0.05][-70:]
    s['d'] = d
    out = np.zeros((L.n, 3))
    if len(d):
        dx = np.abs(L.px[None, :] - d[:, 0:1])
        dy = d[:, 1:2] - L.py[None, :]
        colw = np.exp(-(dx / 0.032) ** 2)
        trail = np.where((dy >= 0) & (dy < tail), (1 - dy / tail) ** 2, 0.0)
        out = (colw * trail).T @ palc(p['palette'], d[:, 3])
        head = (colw * np.exp(-(dy / 0.03) ** 2)).sum(axis=0)
        out += head[:, None] * 0.5
    if p['flash'] > 0:
        out += pal(p['palette'], 0.0)[None, :] * (a.beat_pulse * p['flash'])
    return out


# ---------------------------------------------------------------- ambient effects (can also react)
def fx_plasma(c, p, s):
    L, a = c.L, c.a
    react = p['react']
    env = _env(s, 'env', a.level, 1.8, c.dt)
    s['t'] = s.get('t', rng.random() * 50) + c.dt * p['speed'] * (1 + react * 2.5 * a.bass)
    t, sc = s['t'], p['scale']
    f = (np.sin(L.px * sc * 6 + t) + np.sin(L.py * sc * 8 - t * 0.8) + np.sin((L.px + L.py) * sc * 5 + t * 1.3)
         + np.sin(np.hypot(L.px - 0.5, L.py - 0.15) * sc * 9 - t * 1.1))
    col = palc(p['palette'], f * 0.125 + 0.5 + t * 0.02)
    return col * ((1 - react) + react * (0.12 + 0.88 * env))


def fx_gradient(c, p, s):
    L, a = c.L, c.a
    d = p['direction']
    span = max(L.pymax - L.pymin, 1e-6)
    if d == 'Horizontal':
        coord = L.px
    elif d == 'Vertical':
        coord = (L.py - L.pymin) / span
    elif d == 'Diagonal':
        coord = (L.px + L.py) * 0.7
    else:
        coord = np.hypot(L.px - L.cx, L.py - L.cy) * 1.6
    s['ph'] = s.get('ph', 0.0) + c.dt * p['speed'] * 0.25
    col = palc(p['palette'], coord * p['scale'] - s['ph'])
    env = _env(s, 'env', min(1.0, a.bass * 1.2), 2.5, c.dt)
    return col * ((1 - p['pulse']) + p['pulse'] * env ** 1.5)


def fx_solid(c, p, s):
    col = np.array(hex_rgb(p['color']))
    env = _env(s, 'env', min(1.0, c.a.bass * 1.2), 2.5, c.dt)
    return np.tile(col * ((1 - p['pulse']) + p['pulse'] * env ** 1.5), (c.L.n, 1))


def fx_screen(c, p, s):
    L = c.L
    img = c.screen()
    if img is None:
        return s.get('prev', np.zeros((L.n, 3)))
    h, w = img.shape[:2]
    span = max(L.pymax - L.pymin, 1e-6)
    ix = np.clip((L.px * (w - 1)).astype(int), 0, w - 1)
    iy = np.clip(((L.py - L.pymin) / span * (h - 1)).astype(int), 0, h - 1)
    col = img[iy, ix].astype(float)
    m = col.mean(axis=1, keepdims=True)
    col = np.clip(m + (col - m) * p['saturation'], 0, 1) * p['boost']
    prev = s.get('prev')
    if prev is not None:
        k = min(1.0, c.dt * p['response'])
        col = prev + (col - prev) * k
    s['prev'] = col
    return col


def fx_ripple(c, p, s):
    L = c.L
    rings = s.setdefault('rings', [])
    for i in c.pressed:
        s['ci'] = (s.get('ci', 0.0) + 0.13) % 1.0
        rings.append([0.0, 1.0, s['ci'], L.px[i], L.py[i]])
    del rings[:-14]
    out = np.zeros((L.n, 3))
    keep = []
    for r in rings:
        r[0] += p['speed'] * c.dt
        r[1] *= float(np.exp(-c.dt * p['fade']))
        if r[1] < 0.03:
            continue
        keep.append(r)
        d = np.hypot(L.px - r[3], L.py - r[4])
        g = np.exp(-((d - r[0]) / max(0.01, p['width'])) ** 2) * r[1]
        out += palc(p['palette'], r[2])[None, :] * g[:, None]
    s['rings'] = keep
    return out


# ---------------------------------------------------------------- registry
# ---------------------------------------------------------------- hyper effects
def _beat(c, s):
    """True once for every detected beat."""
    b = c.a.beat_count
    hit = b != s.get('bc', b)
    s['bc'] = b
    return hit


def _drive(c, p):
    """How hard the music is hitting right now, 0..1."""
    a = c.a
    return float(min(1.0, max(a.bass, a.level * 0.75, a.mid * 0.9) * p.get('gain', 1.0)))


def fx_zigzag(c, p, s):
    L = c.L
    if 'ph' not in s:
        s.update(ph=0.0, dir=1.0, hue=float(rng.random()), fl=0.0)
    if _beat(c, s):
        s['dir'] = -s['dir']
        s['hue'] = (s['hue'] + 0.23) % 1.0
        s['fl'] = 1.0
    s['fl'] *= float(np.exp(-c.dt * 6.0))
    drv = _drive(c, p)
    hot = max(drv, s['fl'])
    s['ph'] += c.dt * p['speed'] * s['dir'] * (0.3 + 1.9 * drv)
    lines = max(1, int(round(p['lines'])))
    tri = np.abs(((L.ku * p['teeth'] + s['ph']) % 1.0) * 2 - 1)
    zig = 0.5 + (tri - 0.5) * (0.35 + 0.65 * hot)          # the zigzag gets taller with the music
    d = np.abs(((L.kv - zig) * lines + 0.5) % 1.0 - 0.5) / lines
    width = max(0.01, p['width'] * (0.7 + 0.8 * hot))
    g = np.clip(1 - d / width, 0, 1) ** 1.3
    col = palc(p['palette'], s['hue'] + L.ku * 0.4 + tri * 0.15)
    power = p['floor'] + (1 - p['floor']) * hot
    return col * (g * power + p['glow'] + s['fl'] * p['flash'] * 0.5)[:, None]


def fx_soundzig(c, p, s):
    """One zigzag line through the middle of the keyboard whose height follows the music. Nothing else lights."""
    L = c.L
    if 'ph' not in s:
        s.update(ph=0.0, hue=float(rng.random()))
    drv = _drive(c, p)
    env = _env(s, 'env', drv, p['fall'], c.dt)
    if _beat(c, s) and p['beat_colour']:
        s['hue'] = (s['hue'] + 0.17) % 1.0
    smooth = p['shape'] == 'Smooth flow'
    spd = s.get('spd', 0.3)                       # speed eases up and down instead of jumping
    spd += ((0.25 + 1.75 * drv) - spd) * min(1.0, c.dt * (3.0 if smooth else 30.0))
    s['spd'] = spd
    s['ph'] += c.dt * p['speed'] * spd
    if smooth:
        s['hue'] = (s['hue'] + c.dt * 0.03) % 1.0
    xx = L.ku * p['teeth'] + s['ph']
    tri = np.abs((xx % 1.0) * 2 - 1) * 2 - 1
    if smooth:                                    # a rounded wave with a slow second sway on top
        tri = 0.82 * np.sin(2 * np.pi * xx) + 0.18 * np.sin(2 * np.pi * (xx * 0.43 - s['ph'] * 0.7))
    tri = tri * 1.0          # -1 .. 1
    local = np.interp(L.ku, _BANDPOS, _spectrum(c, p, s))
    sm = s.get('e2', 0.0)
    sm += (env - sm) * min(1.0, c.dt * (9.0 if smooth else 60.0))
    s['e2'] = sm
    amp = (1 - p['bands']) * sm + p['bands'] * local
    amp = p['idle'] + (1 - p['idle']) * amp
    centre = 0.5 + tri * amp * 0.5 * p['height']                               # flat middle line when quiet
    w = max(0.03, p['width'])
    if smooth:                                    # soft edge so the line glides between rows
        g = np.exp(-((L.kv - centre) / w) ** 2)
        g = np.where(g < 0.06, 0.0, g)
    else:
        g = np.clip((w - np.abs(L.kv - centre)) / (w * 0.45), 0, 1)
    # edge lights continue the wave: rear lights + logo glow where the wave swings up, the front bar where it swings down
    edge = np.clip(np.where(L.zone == 2, -tri, tri), 0, 1) ** 1.5 * (0.35 + 0.65 * amp)
    g = np.where(L.is_key, g, edge)
    col = palc(p['palette'], s['hue'] + L.ku * p['spread'])
    return col * (g * (p['floor'] + (1 - p['floor']) * (sm if smooth else env)))[:, None]


def fx_disco(c, p, s):
    L, a = c.L, c.a
    cols = max(2, int(round(p['tiles'])))
    rows = 3
    n = cols * rows + 4 * cols * 2
    if s.get('n') != n:
        cell = np.minimum((L.ku * cols).astype(int), cols - 1) + cols * np.minimum((L.kv * rows).astype(int), rows - 1)
        strip = cols * rows + L.zone * cols * 2 + np.minimum((L.ku * cols * 2).astype(int), cols * 2 - 1)
        s.update(n=n, cell=np.where(L.is_key, cell, strip), hue=rng.random(n), lv=np.ones(n), sp=np.zeros(L.n))
    drv = _drive(c, p)
    hue, lv = s['hue'], s['lv']
    lv *= float(np.exp(-c.dt * p['fade']))
    if _beat(c, s):
        hue[:] = rng.random(n)
        lv[:] = 1.0
    k = int(min(n, rng.poisson(p['speed'] * (0.1 + 1.4 * drv) * 0.25 * n * c.dt)))
    if k:
        i = rng.integers(0, n, k)
        hue[i] = rng.random(k)
        lv[i] = 1.0
    cell = s['cell']
    out = palc(p['palette'], hue[cell]) * (p['floor'] + (1 - p['floor']) * lv[cell])[:, None]
    if p['sparkle'] > 0:
        sp = s['sp']
        sp *= float(np.exp(-c.dt * 9.0))
        k = int(rng.poisson(min(30.0, a.treble * p['gain'] * p['sparkle'] * 120.0 * c.dt)))
        if k:
            sp[rng.integers(0, L.n, k)] = 1.0
        out = out + sp[:, None]
    return out


def fx_strobe(c, p, s):
    L = c.L
    if 'fl' not in s:
        s.update(fl=0.0, hue=float(rng.random()), acc=0.0, idx=0)
    drv = _drive(c, p)
    hit = _beat(c, s)
    s['acc'] += c.dt * p['rate'] * drv
    if s['acc'] >= 1.0:
        s['acc'] = 0.0
        hit = True
    if hit:
        s['fl'] = 1.0
        s['hue'] = (s['hue'] + 0.17 + 0.2 * float(rng.random())) % 1.0
        s['idx'] += 1
    else:
        s['fl'] *= float(np.exp(-c.dt * p['fade']))
    mode = p['mode']
    if mode == 'Left / right':
        m = (L.ku < 0.5) == (s['idx'] % 2 == 0)
    elif mode == 'Three blocks':
        m = np.minimum((L.ku * 3).astype(int), 2) == s['idx'] % 3
    elif mode == 'Keys / edge lights':
        m = L.is_key == (s['idx'] % 2 == 0)
    else:
        m = np.ones(L.n, bool)
    lv = np.where(m, s['fl'], 0.0)[:, None]
    col = palc(p['palette'], s['hue'])[None, :]
    col = col * (1 - p['white'] * lv) + p['white'] * lv
    return col * (p['floor'] + (1 - p['floor']) * lv)


def fx_rows(c, p, s):
    L = c.L
    if 'q' not in s:
        s.update(q=0.0, hue=float(rng.random()), tr=np.zeros(L.n), fl=0.0)
    columns = p['orient'] == 'Columns'
    if columns:
        rc, lo, hi = L.ku * 15.0, 0.0, 15.0
    else:                                     # rear lights -> key rows top to bottom -> front bar
        rc = np.where(L.is_key, (1 - L.kv) * 5.6, np.where(L.zone == 2, 6.8, -1.2))
        lo, hi = -1.2, 6.8
    span = hi - lo
    drv = _drive(c, p)
    s['fl'] *= float(np.exp(-c.dt * 6.0))
    s['q'] += c.dt * p['speed'] * (2.0 if columns else 1.0) * (0.15 + 1.85 * drv)
    if _beat(c, s):
        s['q'] += 1.2
        s['hue'] = (s['hue'] + 0.19) % 1.0
        s['fl'] = 1.0
    q = s['q']
    if p['motion'] == 'Bounce':
        t = q % (2 * span)
        pos = lo + (t if t < span else 2 * span - t)
    elif p['motion'] == 'Up / left':
        pos = hi - q % span
    else:
        pos = lo + q % span
    width = max(0.2, p['width'] * (2.0 if columns else 1.0))
    hit = np.clip(1 - np.abs(rc - pos) / width, 0, 1)
    tr = np.maximum(s['tr'] * float(np.exp(-c.dt * p['fade'])), hit)
    s['tr'] = tr
    col = palc(p['palette'], s['hue'] + (rc - lo) / span * p['spread'])
    power = p['floor'] + (1 - p['floor']) * max(drv, s['fl'])
    return col * (tr * power + p['glow'])[:, None]


def fx_diagonal(c, p, s):
    L = c.L
    if 'q' not in s:
        s.update(q=0.0, fl=0.0)
    drv = _drive(c, p)
    s['fl'] *= float(np.exp(-c.dt * 6.0))
    s['q'] += c.dt * p['speed'] * (0.2 + 1.8 * drv)
    if _beat(c, s):
        s['q'] = float(np.floor(s['q']) + 1.0)     # every beat starts a pass in the next direction
        s['fl'] = 1.0
    n = int(s['q'])
    frac = s['q'] - n
    v = (L.py - L.pymin) / max(L.pymax - L.pymin, 1e-6)
    coord = (L.px + (v if n % 2 == 0 else 1 - v)) * 0.5      # one diagonal, then the other
    if (n // 2) % 2 == 1:                                    # ...then both again, backwards
        coord = 1 - coord
    stripes = max(1, int(round(p['stripes'])))
    pos = -0.1 + frac * 1.2
    sd = (((pos - coord) * stripes + 0.5) % 1.0 - 0.5) / stripes
    g = np.where(sd >= 0, np.exp(-np.maximum(sd, 0) / max(p['tail'], 0.01)), np.exp(-(sd / max(p['width'], 0.005)) ** 2))
    col = palc(p['palette'], n * 0.19 + coord * 0.35)
    power = p['floor'] + (1 - p['floor']) * max(drv, s['fl'])
    return col * (g * power + p['glow'] + s['fl'] * p['flash'] * 0.4)[:, None]


def _screen_cols(c, p, s):
    """Colour of the screen area that lies 'behind' each lamp (top of screen = rear lights, bottom = front bar)."""
    L = c.L
    img = c.screen()
    if img is None:
        return s.get('raw')
    h, w = img.shape[:2]
    span = max(L.pymax - L.pymin, 1e-6)
    ix = np.clip((L.px * (w - 1)).astype(int), 0, w - 1)
    iy = np.clip(((L.py - L.pymin) / span * (h - 1)).astype(int), 0, h - 1)
    col = img[iy, ix].astype(float)
    m = col.mean(axis=1, keepdims=True)
    col = np.clip(m + (col - m) * p['saturation'], 0, 1)
    viv = p.get('vivid', 0.0)
    if viv > 0:                                  # push dim colours up to full strength, same hue
        mx = col.max(axis=1, keepdims=True)
        col = col / np.maximum(mx, 0.03) * mx ** (1 - viv)
    col = col * p['boost']
    s['raw'] = col
    return col


def fx_screen2(c, p, s):
    col = _screen_cols(c, p, s)
    if col is None:
        return s.get('prev', np.zeros((c.L.n, 3)))
    prev = s.get('prev')
    if prev is not None:
        col = prev + (col - prev) * min(1.0, c.dt * p['response'])
    s['prev'] = col
    return col


def fx_screenbeat(c, p, s):
    L = c.L
    col = _screen_cols(c, p, s)
    if col is None:
        col = palc('Neon', L.px + c.t * 0.1)
    prev = s.get('prev')
    if prev is not None:
        col = prev + (col - prev) * min(1.0, c.dt * 22.0)
    s['prev'] = col
    if 'fl' not in s:
        s.update(fl=0.0, rings=[])
    drv = _drive(c, p)
    env = _env(s, 'env', drv, p['fall'], c.dt)
    hit = _beat(c, s)
    s['fl'] = 1.0 if hit else s['fl'] * float(np.exp(-c.dt * 7.0))
    style = p['style']
    if style == 'Bars':
        h = np.interp(L.ku, _BANDPOS, _spectrum(c, p, s))
        lv = np.where(L.is_key, np.clip((h * 1.12 - L.kv) / 0.17, 0, 1), h)
    elif style == 'Shockwave':
        rings = s['rings']
        if hit:
            rings.append([0.0, 1.0])
            del rings[:-6]
        lv = np.zeros(L.n)
        keep = []
        d = np.hypot(L.px - L.cx, L.py - L.cy)
        for r in rings:
            r[0] += 1.6 * c.dt
            r[1] *= float(np.exp(-c.dt * 2.5))
            if r[1] < 0.04 or r[0] > 1.5:
                continue
            keep.append(r)
            lv += np.exp(-((d - r[0]) / 0.1) ** 2) * r[1] + (d < r[0]) * r[1] * 0.3
        s['rings'] = keep
        lv = np.clip(lv + env * 0.3, 0, 1)
    else:
        lv = np.full(L.n, env ** 1.3)
    out = col * (p['floor'] + (1 - p['floor']) * lv)[:, None]
    return out + (col * 0.6 + 0.4) * (s['fl'] * p['flash'])


def F(key, label, default, lo, hi):
    return dict(key=key, label=label, type='float', default=default, lo=lo, hi=hi)


def C(key, label, default, choices):
    return dict(key=key, label=label, type='choice', default=default, choices=choices)


def B(key, label, default):
    return dict(key=key, label=label, type='bool', default=default)


def P(default='Neon'):
    return dict(key='palette', label='Colours', type='palette', default=default)


GAIN = F('gain', 'Sensitivity', 1.0, 0.3, 3.0)

EFFECTS = {
    'spectrum': dict(label='Spectrum Bars', audio=True, func=fx_spectrum, params=[
        P('Neon'), GAIN, F('fall', 'Fall speed', 2.2, 0.5, 6.0),
        C('layout', 'Layout', 'Bass on the left', ['Bass on the left', 'Bass on the right', 'Bass in the middle']),
        C('color_by', 'Colour by', 'Height', ['Height', 'Frequency', 'Loudness']),
        B('caps', 'Peak caps', True), F('glow', 'Background glow', 0.0, 0.0, 0.5)]),
    'shockwave': dict(label='Bass Shockwave', audio=True, func=fx_shockwave, params=[
        P('Synthwave'), C('origin', 'Starts from', 'Centre', ['Centre', 'Bottom centre', 'Random key']),
        F('speed', 'Ring speed', 1.3, 0.3, 4.0), F('width', 'Ring width', 0.09, 0.03, 0.4),
        F('fade', 'Fade', 2.2, 0.5, 8.0), F('fill', 'Fill inside', 0.15, 0.0, 1.0)]),
    'pulse': dict(label='Pulse Glow', audio=True, func=fx_pulse, params=[
        P('Aurora'), C('source', 'Reacts to', 'Bass', ['Bass', 'Mids', 'Treble', 'Overall']), GAIN,
        F('fall', 'Fall speed', 3.0, 0.5, 10.0), F('floor', 'Minimum glow', 0.06, 0.0, 1.0),
        F('spread', 'Colour spread', 0.5, 0.0, 2.0), F('drift', 'Colour drift', 1.0, 0.0, 6.0),
        F('sparkle', 'Treble sparkle', 0.5, 0.0, 2.0)]),
    'waterfall': dict(label='Waterfall', audio=True, func=fx_waterfall, params=[
        P('Fire'), GAIN, F('fall', 'Fall speed', 3.0, 0.5, 8.0), F('speed', 'Scroll speed', 14.0, 3.0, 40.0),
        C('direction', 'Direction', 'Down', ['Down', 'Up', 'Right', 'Left'])]),
    'beatwipe': dict(label='Beat Wipe', audio=True, func=fx_beatwipe, params=[
        P('Sunset'), C('direction', 'Direction', 'Random', ['Random', 'Left to right', 'Right to left', 'Top to bottom',
                                                           'Bottom to top', 'Centre out', 'Edges in']),
        F('speed', 'Wipe speed', 3.5, 0.8, 10.0), F('floor', 'Minimum glow', 0.35, 0.0, 1.0),
        F('fade', 'Flash fade', 3.0, 0.5, 10.0), F('edge', 'Bright edge', 0.5, 0.0, 1.0)]),
    'rain': dict(label='Treble Rain', audio=True, func=fx_rain, params=[
        P('Ice'), GAIN, F('rate', 'Drops', 14.0, 1.0, 50.0), F('speed', 'Fall speed', 0.9, 0.2, 3.0),
        F('tail', 'Tail length', 0.22, 0.04, 0.6), F('react', 'React to music', 0.9, 0.0, 1.0),
        F('flash', 'Beat flash', 0.25, 0.0, 1.0)]),
    'zigzag': dict(label='Zig Zag', audio=True, func=fx_zigzag, params=[
        P('Neon'), GAIN, F('speed', 'Speed', 1.6, 0.2, 5.0), F('teeth', 'Zigzags across', 2.5, 1.0, 8.0),
        F('lines', 'Lines', 1.0, 1.0, 4.0), F('width', 'Line thickness', 0.11, 0.04, 0.5),
        F('floor', 'Minimum power', 0.3, 0.0, 1.0), F('flash', 'Beat flash', 0.6, 0.0, 1.0),
        F('glow', 'Background glow', 0.05, 0.0, 0.5)]),
    'soundzig': dict(label='Sound Zig Zag', audio=True, func=fx_soundzig, params=[
        P('Neon'), C('shape', 'Shape', 'Smooth flow', ['Smooth flow', 'Sharp zigzag']), GAIN,
        F('height', 'Wave height', 1.0, 0.2, 1.0), F('teeth', 'Waves across', 2.0, 1.0, 8.0),
        F('speed', 'Flow speed', 0.9, 0.0, 5.0), F('width', 'Line thickness', 0.16, 0.04, 0.4),
        F('idle', 'Movement when quiet', 0.25, 0.0, 1.0),
        F('fall', 'Fall speed', 3.5, 0.5, 10.0), F('bands', 'Follow bass-to-treble', 0.2, 0.0, 1.0),
        F('floor', 'Brightness when quiet', 0.3, 0.0, 1.0), F('spread', 'Colour spread', 0.5, 0.0, 2.0),
        B('beat_colour', 'New colour on each beat', False)]),
    'disco': dict(label='Disco Tiles', audio=True, func=fx_disco, params=[
        P('Rainbow'), GAIN, F('tiles', 'Tiles across', 7.0, 3.0, 14.0), F('speed', 'Tile changes', 4.0, 0.0, 12.0),
        F('fade', 'Fade', 2.5, 0.5, 8.0), F('floor', 'Minimum glow', 0.4, 0.0, 1.0),
        F('sparkle', 'White sparkle', 0.6, 0.0, 2.0)]),
    'strobe': dict(label='Strobe Flash', audio=True, func=fx_strobe, params=[
        P('Rainbow'), GAIN, C('mode', 'Flashes', 'Whole keyboard', ['Whole keyboard', 'Left / right', 'Three blocks',
                                                                   'Keys / edge lights']),
        F('rate', 'Extra flashes', 4.0, 0.0, 12.0), F('fade', 'Fade', 9.0, 2.0, 20.0),
        F('floor', 'Minimum glow', 0.04, 0.0, 1.0), F('white', 'White punch', 0.3, 0.0, 1.0)]),
    'rows': dict(label='Line by Line', audio=True, func=fx_rows, params=[
        P('Neon'), GAIN, C('orient', 'Lines are', 'Rows', ['Rows', 'Columns']),
        C('motion', 'Movement', 'Down / right', ['Down / right', 'Up / left', 'Bounce']),
        F('speed', 'Speed', 7.0, 0.5, 25.0), F('width', 'Line thickness', 0.9, 0.3, 3.0), F('fade', 'Trail fade', 5.0, 1.0, 15.0),
        F('floor', 'Minimum power', 0.35, 0.0, 1.0), F('spread', 'Colour spread', 0.6, 0.0, 2.0),
        F('glow', 'Background glow', 0.08, 0.0, 0.5)]),
    'diagonal': dict(label='Diagonal Bounce', audio=True, func=fx_diagonal, params=[
        P('Synthwave'), GAIN, F('speed', 'Speed', 1.4, 0.2, 5.0), F('stripes', 'Stripes', 2.0, 1.0, 5.0),
        F('width', 'Edge sharpness', 0.05, 0.01, 0.2), F('tail', 'Tail length', 0.18, 0.03, 0.5),
        F('floor', 'Minimum power', 0.35, 0.0, 1.0), F('flash', 'Beat flash', 0.5, 0.0, 1.0),
        F('glow', 'Background glow', 0.05, 0.0, 0.5)]),
    'screenbeat': dict(label='Screen + Sound', audio=True, func=fx_screenbeat, params=[
        C('style', 'Music moves it as', 'Pulse', ['Pulse', 'Bars', 'Shockwave']), GAIN,
        F('fall', 'Fall speed', 4.0, 1.0, 12.0), F('floor', 'Minimum glow', 0.12, 0.0, 1.0),
        F('flash', 'Beat flash', 0.5, 0.0, 1.0), F('saturation', 'Saturation', 1.5, 0.5, 3.0),
        F('boost', 'Brightness', 1.3, 0.3, 2.5), F('vivid', 'Vivid boost', 0.7, 0.0, 1.0)]),
    'plasma': dict(label='Plasma', audio=False, func=fx_plasma, params=[
        P('Aurora'), F('speed', 'Speed', 0.8, 0.0, 4.0), F('scale', 'Detail', 1.0, 0.3, 3.0),
        F('react', 'React to music', 0.6, 0.0, 1.0)]),
    'gradient': dict(label='Gradient / Wave', audio=False, func=fx_gradient, params=[
        P('Rainbow'), C('direction', 'Direction', 'Horizontal', ['Horizontal', 'Vertical', 'Diagonal', 'Radial']),
        F('speed', 'Scroll speed', 0.6, -4.0, 4.0), F('scale', 'Stretch', 1.0, 0.1, 4.0),
        F('pulse', 'Pulse with bass', 0.0, 0.0, 1.0)]),
    'solid': dict(label='Solid Colour', audio=False, func=fx_solid, params=[
        dict(key='color', label='Colour', type='color', default='#00c8ff'), F('pulse', 'Pulse with bass', 0.0, 0.0, 1.0)]),
    'screen': dict(label='Screen Mirror', audio=False, func=fx_screen2, params=[
        F('saturation', 'Saturation', 1.6, 0.5, 3.0), F('boost', 'Brightness', 1.2, 0.3, 2.5),
        F('response', 'Response', 10.0, 1.0, 30.0), F('vivid', 'Vivid boost', 0.0, 0.0, 1.0)]),
    'ripple': dict(label='Typing Ripples', audio=False, func=fx_ripple, params=[
        P('Candy'), F('speed', 'Ring speed', 1.0, 0.2, 4.0), F('width', 'Ring width', 0.06, 0.02, 0.3),
        F('fade', 'Fade', 2.5, 0.5, 8.0)]),
}

BLENDS = ['Add', 'Lighten', 'Replace', 'Multiply', 'Screen']


def defaults(effect):
    return {p['key']: p['default'] for p in EFFECTS[effect]['params']}


def blend(out, col, mode, op, mask):
    if mode == 'Add':
        out[mask] += col[mask] * op
    elif mode == 'Lighten':
        out[mask] = np.maximum(out[mask], col[mask] * op)
    elif mode == 'Multiply':
        out[mask] *= (1 - op) + col[mask] * op
    elif mode == 'Screen':
        out[mask] = 1 - (1 - np.clip(out[mask], 0, 1)) * (1 - np.clip(col[mask] * op, 0, 1))
    else:
        out[mask] = out[mask] * (1 - op) + col[mask] * op
    return out
