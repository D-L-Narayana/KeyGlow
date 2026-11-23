"""Presets and settings, saved as JSON in %APPDATA%\\KeyGlow."""
import copy
import json
import os
import uuid

from .effects import EFFECTS, defaults
from .layout import ZONES

DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'KeyGlow')
PATH = os.path.join(DIR, 'config.json')
LOG = os.path.join(DIR, 'keyglow.log')


def layer(effect, blend='Add', opacity=1.0, zones=None, **params):
    p = defaults(effect)
    p.update(params)
    return dict(id=uuid.uuid4().hex[:8], effect=effect, on=True, blend=blend, opacity=opacity,
                zones=list(zones or ZONES), params=p)


def builtin_presets():
    return [
        dict(name='Spectrum Neon', layers=[layer('spectrum')]),
        dict(name='Bass Shockwave', layers=[
            layer('gradient', palette='Synthwave', speed=0.3, pulse=0.6, opacity=0.25),
            layer('shockwave')]),
        dict(name='Aurora Pulse', layers=[layer('plasma', react=0.75), layer('pulse', opacity=0.6, floor=0.0)]),
        dict(name='Fire Waterfall', layers=[layer('waterfall')]),
        dict(name='Beat Wipe', layers=[layer('beatwipe')]),
        dict(name='Treble Rain', layers=[layer('rain')]),
        dict(name='Club Mix', layers=[
            layer('spectrum', palette='Synthwave', color_by='Frequency', caps=False, zones=['keys']),
            layer('shockwave', palette='White', opacity=0.5, fill=0.0, zones=['keys']),
            layer('pulse', palette='Synthwave', sparkle=0.0, zones=['rear', 'front', 'logo'])]),
        dict(name='Screen Ambient', layers=[layer('screen', blend='Replace')]),
        dict(name='Typing Ripples', layers=[
            layer('gradient', palette='Ocean', speed=0.2, opacity=0.2), layer('ripple')]),
        dict(name='Rainbow Wave', layers=[layer('gradient')]),
        dict(name='Zig Zag Hyper', layers=[layer('zigzag')]),
        dict(name='Sound Zig Zag', layers=[layer('soundzig')]),
        dict(name='Disco Floor', layers=[layer('disco')]),
        dict(name='Strobe Flash', layers=[layer('strobe')]),
        dict(name='Line by Line', layers=[layer('rows')]),
        dict(name='Diagonal Bounce', layers=[layer('diagonal')]),
        dict(name='Rave Max', layers=[
            layer('disco', zones=['keys'], floor=0.25),
            layer('zigzag', palette='White', zones=['keys'], opacity=0.9, glow=0.0, flash=0.3),
            layer('strobe', zones=['rear', 'front', 'logo'], mode='Left / right')]),
        dict(name='Neon Glow Max', layers=[
            layer('gradient', palette='Neon', speed=1.2, scale=0.8, pulse=0.3),
            layer('diagonal', palette='White', opacity=0.7, glow=0.0, floor=0.5)]),
        dict(name='Screen Exact', layers=[layer('screen', blend='Replace', saturation=1.0, boost=1.0, response=30.0)]),
        dict(name='Screen + Sound', layers=[layer('screenbeat', blend='Replace')]),
        dict(name='Screen + Sound Bars', layers=[layer('screenbeat', blend='Replace', style='Bars', floor=0.05)]),
    ]


class Store:
    def __init__(self):
        self.data = dict(presets=builtin_presets(), current='Spectrum Neon', brightness=1.0, gamma=1.6,
                         fps=30, auto_output=False, glow=0.6)
        try:
            with open(PATH, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d.get('presets'), list) and d['presets']:
                self.data.update(d)
        except Exception:
            pass
        self._clean()

    def _clean(self):
        good = []
        for pr in self.data['presets']:
            layers = []
            for l in pr.get('layers', []):
                if l.get('effect') not in EFFECTS:
                    continue
                p = defaults(l['effect'])
                p.update({k: v for k, v in (l.get('params') or {}).items() if k in p})
                l['params'] = p
                l.setdefault('id', uuid.uuid4().hex[:8])
                l.setdefault('on', True)
                l.setdefault('blend', 'Add')
                l.setdefault('opacity', 1.0)
                l['zones'] = [z for z in l.get('zones', ZONES) if z in ZONES]
                layers.append(l)
            if pr.get('name'):
                pr['layers'] = layers
                good.append(pr)
        self.data['presets'] = good or builtin_presets()
        if not self.preset(self.data.get('current')):
            self.data['current'] = self.data['presets'][0]['name']

    def save(self):
        try:
            os.makedirs(DIR, exist_ok=True)
            tmp = PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, PATH)
        except Exception:
            pass

    def reset_originals(self):
        """Every built-in preset and the global settings go back to how the app came. Own presets are kept."""
        fresh = builtin_presets()
        names = {p['name'] for p in fresh}
        own = [p for p in self.data['presets'] if p['name'] not in names]
        self.data['presets'] = fresh + own
        self.data.update(brightness=1.0, glow=0.6, gamma=1.6, fps=30)
        if not self.preset(self.data.get('current')):
            self.data['current'] = fresh[0]['name']

    def names(self):
        return [p['name'] for p in self.data['presets']]

    def preset(self, name):
        for p in self.data['presets']:
            if p['name'] == name:
                return p
        return None

    def current(self):
        return self.preset(self.data['current']) or self.data['presets'][0]

    def unique(self, base):
        names, n, name = set(self.names()), 2, base
        while name in names:
            name = '%s %d' % (base, n)
            n += 1
        return name

    def add(self, name, layers=None):
        p = dict(name=self.unique(name), layers=layers if layers is not None else [layer('spectrum')])
        self.data['presets'].append(p)
        return p

    def duplicate(self, src):
        layers = copy.deepcopy(src['layers'])
        for l in layers:
            l['id'] = uuid.uuid4().hex[:8]
        return self.add(src['name'] + ' copy', layers)
