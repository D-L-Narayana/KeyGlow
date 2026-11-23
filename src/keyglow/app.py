"""KeyGlow window (tkinter)."""
import os
import sys
import tkinter as tk
import winreg
from tkinter import colorchooser, messagebox, simpledialog, ttk

import numpy as np

from . import APP_NAME, VERSION
from .effects import BLENDS, EFFECTS, PALETTES, stops_of
from .layout import ZONE_LABEL, ZONES
from .store import builtin_presets, layer as new_layer

BG, PANEL, CARD, LINE = '#0e1014', '#161920', '#1f232d', '#2a2f3b'
FG, MUTED, ACC, HOT, WARN = '#e8ebf1', '#8a92a3', '#00c8ff', '#ff3b6b', '#ffb020'


def resource(name):
    return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), name)


def windows_lighting_on():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Lighting') as k:
            return int(winreg.QueryValueEx(k, 'AmbientLightingEnabled')[0]) == 1
    except Exception:
        return False


class Slider(tk.Canvas):
    """Flat slider: grey track, coloured fill, round white handle."""

    def __init__(self, parent, lo, hi, value, command, bg, sf=1.0, length=120):
        super().__init__(parent, height=int(24 * sf), width=int(length * sf), bg=bg, highlightthickness=0, cursor='hand2')
        self.lo, self.hi, self.value, self.command, self.sf = lo, hi, value, command, sf
        self.r = int(7 * sf)
        self.bind('<Configure>', self.draw)
        self.bind('<Button-1>', self._drag)
        self.bind('<B1-Motion>', self._drag)

    def draw(self, _=None):
        self.delete('all')
        w, y, r = self.winfo_width(), self.winfo_height() // 2, self.r
        frac = (self.value - self.lo) / (self.hi - self.lo) if self.hi != self.lo else 0
        x = r + (w - 2 * r) * min(1.0, max(0.0, frac))
        lw = max(3, int(4 * self.sf))
        self.create_line(r, y, w - r, y, fill='#343a48', width=lw, capstyle='round')
        if x > r + 1:
            self.create_line(r, y, x, y, fill=ACC, width=lw, capstyle='round')
        self.create_oval(x - r, y - r, x + r, y + r, fill='#ffffff', outline='')

    def _drag(self, e):
        w, r = self.winfo_width(), self.r
        frac = min(1.0, max(0.0, (e.x - r) / max(1, w - 2 * r)))
        self.value = self.lo + frac * (self.hi - self.lo)
        self.draw()
        self.command(self.value)


class Check(tk.Frame):
    """Tick box with a label; calls command(new_value)."""

    def __init__(self, parent, text, value, command, bg, sf=1.0):
        super().__init__(parent, bg=bg, cursor='hand2')
        self.value, self.command = bool(value), command
        self.s = int(17 * sf)
        self.box = tk.Canvas(self, width=self.s, height=self.s, bg=bg, highlightthickness=0)
        self.box.pack(side='left')
        widgets = [self, self.box]
        if text:
            lab = tk.Label(self, text=text, bg=bg, fg=FG, font=('Segoe UI', 10))
            lab.pack(side='left', padx=(int(6 * sf), 0))
            widgets.append(lab)
        for w in widgets:
            w.bind('<Button-1>', self._click)
        self.draw()

    def draw(self):
        c, s = self.box, self.s
        c.delete('all')
        if self.value:
            c.create_rectangle(1, 1, s - 1, s - 1, fill=ACC, outline=ACC)
            c.create_line(s * 0.24, s * 0.52, s * 0.44, s * 0.72, s * 0.78, s * 0.3, fill='#001018',
                          width=max(2, s // 8), capstyle='round', joinstyle='round')
        else:
            c.create_rectangle(1, 1, s - 1, s - 1, fill='#262b36', outline='#4a5263')

    def _click(self, _=None):
        self.value = not self.value
        self.draw()
        self.command(self.value)


class App:
    def __init__(self, root, store, engine):
        self.root, self.store, self.engine = root, store, engine
        self.sf = max(1.0, root.winfo_fpixels('1i') / 96.0)
        self.preset = None
        self.layer = None
        self._items, self._pc = [], []
        self._save_job = None
        self._ticks = 0
        root.title('%s %s – keyboard lighting' % (APP_NAME, VERSION))
        root.configure(bg=BG)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(self.px(1240), sw - 80), min(self.px(840), sh - 140)
        root.geometry('%dx%d+%d+%d' % (w, h, (sw - w) // 2, max(10, (sh - h) // 2 - 30)))
        root.minsize(min(self.px(1040), w), min(self.px(680), h))
        try:
            root.iconbitmap(resource('keyglow.ico'))
        except Exception:
            pass
        self._style()
        self._build()
        self.fill_presets()
        self.select_preset(store.current()['name'])
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.protocol('WM_SAVE_YOURSELF', self.session_end)      # Windows log-off / shutdown
        if store.data.get('auto_output'):
            self.set_output(True)
        self.tick()

    def px(self, n):
        return int(n * self.sf)

    # ------------------------------------------------------------ look
    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use('clam')
        f, fb = ('Segoe UI', 10), ('Segoe UI Semibold', 10)
        st.configure('.', background=BG, foreground=FG, font=f, bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL,
                     troughcolor=CARD, focuscolor=BG)
        st.configure('P.TFrame', background=PANEL)
        st.configure('TLabel', background=BG, foreground=FG)
        st.configure('P.TLabel', background=PANEL, foreground=FG)
        st.configure('M.TLabel', background=PANEL, foreground=MUTED, font=('Segoe UI', 9))
        st.configure('H.TLabel', background=PANEL, foreground=FG, font=('Segoe UI Semibold', 11))
        st.configure('BM.TLabel', background=BG, foreground=MUTED, font=('Segoe UI', 9))
        st.configure('TButton', background=CARD, foreground=FG, padding=(10, 5), borderwidth=0, font=f)
        st.map('TButton', background=[('active', LINE), ('disabled', PANEL)], foreground=[('disabled', MUTED)])
        st.configure('TMenubutton', background=CARD, foreground=FG, padding=(10, 5), borderwidth=0, arrowcolor=FG)
        st.map('TMenubutton', background=[('active', LINE)])
        st.configure('TCheckbutton', background=PANEL, foreground=FG, indicatorbackground='#343a48',
                     indicatorforeground='#343a48', indicatorsize=self.px(15), indicatormargin=(2, 2, 6, 2),
                     upperbordercolor='#4a5263', lowerbordercolor='#4a5263')
        st.map('TCheckbutton', background=[('active', PANEL)], foreground=[('disabled', MUTED)],
               indicatorbackground=[('selected', ACC)], indicatorforeground=[('selected', '#001018')],
               upperbordercolor=[('selected', ACC)], lowerbordercolor=[('selected', ACC)])
        st.configure('B.TCheckbutton', background=BG)
        st.map('B.TCheckbutton', background=[('active', BG)])
        st.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=FG, arrowcolor=FG,
                     selectbackground=CARD, selectforeground=FG, padding=4)
        st.map('TCombobox', fieldbackground=[('readonly', CARD)], foreground=[('readonly', FG)],
               selectbackground=[('readonly', CARD)], selectforeground=[('readonly', FG)])
        st.configure('Horizontal.TScale', background=PANEL, troughcolor=CARD)
        st.configure('B.Horizontal.TScale', background=BG, troughcolor=CARD)
        st.configure('Vertical.TScrollbar', background='#343a48', troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0,
                     bordercolor=PANEL, lightcolor='#343a48', darkcolor='#343a48')
        st.map('Vertical.TScrollbar', background=[('disabled', PANEL), ('active', '#4a5263')],
               lightcolor=[('disabled', PANEL)], darkcolor=[('disabled', PANEL)], arrowcolor=[('disabled', PANEL)])
        self.root.option_add('*TCombobox*Listbox.background', CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', FG)
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#0b6f8c')
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
        self.root.option_add('*TCombobox*Listbox.font', f)
        self.fb = fb

    def _listbox(self, parent, height):
        return tk.Listbox(parent, height=height, bg=CARD, fg=FG, selectbackground='#0b6f8c', selectforeground='#ffffff',
                          highlightthickness=0, borderwidth=0, activestyle='none', exportselection=False,
                          font=('Segoe UI', 10))

    # ------------------------------------------------------------ layout
    def _build(self):
        p = self.px
        top = ttk.Frame(self.root)
        top.pack(fill='x', padx=p(16), pady=(p(12), p(6)))
        ttk.Label(top, text=APP_NAME, font=('Segoe UI Semibold', 18)).pack(side='left')
        self.dot = tk.Canvas(top, width=p(12), height=p(12), bg=BG, highlightthickness=0)
        self.dot.pack(side='left', padx=(p(16), p(6)))
        self.dot_id = self.dot.create_oval(1, 1, p(11), p(11), fill=MUTED, outline='')
        self.status = ttk.Label(top, text='', style='BM.TLabel')
        self.go = tk.Button(top, text='', command=lambda: self.set_output(not self.engine.output), relief='flat', bd=0,
                            font=('Segoe UI Semibold', 11), padx=p(18), pady=p(7), cursor='hand2')
        self.go.pack(side='right')
        self.bright_s = Slider(top, 0.05, 1.0, float(self.store.data.get('brightness', 1.0)), self._bright, BG, self.sf,
                               length=105)
        self.bright_s.pack(side='right', padx=(p(6), p(16)))
        ttk.Label(top, text='Brightness', style='BM.TLabel').pack(side='right')
        self.glow_s = Slider(top, 0.0, 1.0, float(self.store.data.get('glow', 0.6)), self._glow, BG, self.sf, length=105)
        self.glow_s.pack(side='right', padx=(p(6), p(14)))
        ttk.Label(top, text='Glow', style='BM.TLabel').pack(side='right')
        ttk.Button(top, text='Reset to original', command=self.reset_original).pack(side='right', padx=(0, p(16)))
        self.status.pack(side='left')

        self.warn = tk.Frame(self.root, bg='#3a2a08')
        tk.Label(self.warn, bg='#3a2a08', fg=WARN, font=('Segoe UI', 9), anchor='w', justify='left',
                 text='Windows Dynamic Lighting is switched on, so Windows is also driving these lights and the two '
                      'can flicker against each other. Turn it off while you use KeyGlow.').pack(side='left', padx=p(12), pady=p(6))
        tk.Button(self.warn, text='Open Windows setting', relief='flat', bd=0, bg='#5a4210', fg='#ffffff',
                  activebackground='#6a5218', activeforeground='#ffffff', cursor='hand2', padx=p(10),
                  command=lambda: os.startfile('ms-settings:personalization-lighting')).pack(side='right', padx=p(10), pady=p(4))

        self.canvas = tk.Canvas(self.root, bg='#07080a', highlightthickness=1, highlightbackground=LINE, height=p(285))
        self.canvas.pack(fill='x', padx=p(16), pady=(p(4), p(10)))
        self.canvas.bind('<Configure>', lambda e: self._build_preview())

        foot = ttk.Frame(self.root)
        foot.pack(side='bottom', fill='x', padx=p(16), pady=(p(4), p(10)))
        Check(foot, 'Start lighting as soon as KeyGlow opens', self.store.data.get('auto_output'), self._auto, BG,
              self.sf).pack(side='left')
        self.meter = tk.Canvas(foot, width=p(150), height=p(10), bg=CARD, highlightthickness=0)
        self.meter.pack(side='right')
        self.meter_id = self.meter.create_rectangle(0, 0, 0, p(10), fill=ACC, outline='')
        self.audio_lbl = ttk.Label(foot, text='', style='BM.TLabel')
        self.audio_lbl.pack(side='right', padx=(0, p(10)))

        body = ttk.Frame(self.root)
        body.pack(fill='both', expand=True, padx=p(16))
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        # presets
        a = ttk.Frame(body, style='P.TFrame', padding=p(12))
        a.grid(row=0, column=0, sticky='nsew', padx=(0, p(10)))
        ttk.Label(a, text='Presets', style='H.TLabel').pack(anchor='w')
        ttk.Label(a, text='Changes are saved automatically', style='M.TLabel').pack(anchor='w', pady=(0, p(6)))
        self.plist = self._listbox(a, 12)
        self.plist.pack(fill='both', expand=True)
        self.plist.bind('<<ListboxSelect>>', self._preset_pick)
        r = ttk.Frame(a, style='P.TFrame')
        r.pack(fill='x', pady=(p(8), 0))
        for i, (txt, cmd) in enumerate((('New', self.preset_new), ('Duplicate', self.preset_dup),
                                        ('Rename', self.preset_rename), ('Delete', self.preset_del))):
            ttk.Button(r, text=txt, command=cmd).grid(row=i // 2, column=i % 2, sticky='ew', padx=2, pady=2)
        r.columnconfigure(0, weight=1)
        r.columnconfigure(1, weight=1)
        ttk.Button(a, text='Reset this preset', command=self.preset_reset_one).pack(fill='x', pady=(p(4), 0), padx=2)

        # layers
        b = ttk.Frame(body, style='P.TFrame', padding=p(12))
        b.grid(row=0, column=1, sticky='nsew', padx=(0, p(10)))
        ttk.Label(b, text='Layers', style='H.TLabel').pack(anchor='w')
        ttk.Label(b, text='Stacked from top to bottom of this list', style='M.TLabel').pack(anchor='w', pady=(0, p(6)))
        self.llist = self._listbox(b, 10)
        self.llist.configure(width=30)
        self.llist.pack(fill='both', expand=True)
        self.llist.bind('<<ListboxSelect>>', self._layer_pick)
        add = ttk.Menubutton(b, text='+  Add layer')
        m = tk.Menu(add, tearoff=0, bg=CARD, fg=FG, activebackground='#0b6f8c', activeforeground='#ffffff', bd=0)
        m.add_command(label='Reacts to music', state='disabled')
        for k, e in EFFECTS.items():
            if e['audio']:
                m.add_command(label='   ' + e['label'], command=lambda k=k: self.layer_add(k))
        m.add_separator()
        m.add_command(label='Ambient', state='disabled')
        for k, e in EFFECTS.items():
            if not e['audio']:
                m.add_command(label='   ' + e['label'], command=lambda k=k: self.layer_add(k))
        add['menu'] = m
        add.pack(fill='x', pady=(p(8), 2))
        r = ttk.Frame(b, style='P.TFrame')
        r.pack(fill='x')
        for i, (txt, cmd) in enumerate((('Remove', self.layer_del), ('Move up', lambda: self.layer_move(-1)),
                                        ('Move down', lambda: self.layer_move(1)))):
            ttk.Button(r, text=txt, command=cmd).grid(row=0, column=i, sticky='ew', padx=2, pady=2)
            r.columnconfigure(i, weight=1)

        # settings (scrollable)
        c = ttk.Frame(body, style='P.TFrame', padding=(p(12), p(12), p(4), p(12)))
        c.grid(row=0, column=2, sticky='nsew')
        self.sc = tk.Canvas(c, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(c, orient='vertical', command=self.sc.yview)
        self.sc.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.sc.pack(side='left', fill='both', expand=True)
        self.panel = ttk.Frame(self.sc, style='P.TFrame')
        self.panel_id = self.sc.create_window(0, 0, anchor='nw', window=self.panel)
        self.panel.bind('<Configure>', lambda e: self.sc.configure(scrollregion=self.sc.bbox('all')))
        self.sc.bind('<Configure>', lambda e: self.sc.itemconfigure(self.panel_id, width=e.width - 4))
        self.sc.bind('<Enter>', lambda e: self.sc.bind_all('<MouseWheel>', self._wheel))
        self.sc.bind('<Leave>', lambda e: self.sc.unbind_all('<MouseWheel>'))
        self._go_look()

    def _wheel(self, e):
        if self.panel.winfo_height() > self.sc.winfo_height():
            self.sc.yview_scroll(-1 if e.delta > 0 else 1, 'units')

    # ------------------------------------------------------------ preview
    def _build_preview(self):
        L = self.engine.layout
        cv = self.canvas
        cv.delete('all')
        self._items, self._pc = [], []
        w, h = cv.winfo_width(), cv.winfo_height()
        if L is None:
            cv.create_text(w // 2, h // 2, text=self.engine.device_status, fill=MUTED, font=('Segoe UI', 11))
            return
        rects, total = L.preview_rects()
        s = min(w / 1.0, (h - 8) / total)
        ox, oy = (w - s) / 2, (h - total * s) / 2
        for r in rects:
            self._items.append(cv.create_rectangle(ox + r[0] * s, oy + r[1] * s, ox + r[2] * s, oy + r[3] * s,
                                                   fill='#16181d', outline=''))
        self._pc = [-1] * len(rects)
        self._layout_seen = L

    def _paint(self):
        f = self.engine.latest
        if f is None or len(self._items) != len(f):
            return
        v = np.clip(f * float(self.store.data.get('brightness', 1.0)), 0, 1) ** 0.85
        v = (22 + v * 233).astype(np.int32)
        keys = ((v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]).tolist()
        cv, items, pc = self.canvas, self._items, self._pc
        for i, k in enumerate(keys):
            if k != pc[i]:
                pc[i] = k
                cv.itemconfigure(items[i], fill='#%06x' % k)

    # ------------------------------------------------------------ top bar
    def _go_look(self):
        if self.engine.output:
            self.go.configure(text='■   Stop  –  give lights back', bg=HOT, fg='#ffffff', activebackground='#ff5c84',
                              activeforeground='#ffffff')
        else:
            self.go.configure(text='▶   Start on keyboard', bg=ACC, fg='#001018', activebackground='#5cdcff',
                              activeforeground='#001018')

    def set_output(self, on):
        self.engine.output = bool(on)
        self._go_look()

    def _bright(self, v):
        self.store.data['brightness'] = round(float(v), 3)
        self.save_soon()

    def _glow(self, v):
        self.store.data['glow'] = round(float(v), 3)
        self.save_soon()

    def reset_original(self):
        if not messagebox.askyesno(APP_NAME, 'Reset KeyGlow to its original settings?\n\n'
                                   '\u2022  Every built-in preset goes back to how it came.\n'
                                   '\u2022  Brightness and Glow go back to their defaults.\n\n'
                                   'Presets you made yourself are kept.', parent=self.root):
            return
        name = self.preset['name'] if self.preset else None
        self.store.reset_originals()
        for sl, key in ((self.bright_s, 'brightness'), (self.glow_s, 'glow')):
            sl.value = float(self.store.data[key])
            sl.draw()
        self.fill_presets()
        self.select_preset(name if self.store.preset(name) else self.store.data['presets'][0]['name'])
        self.store.save()

    def preset_reset_one(self):
        for pr in builtin_presets():
            if pr['name'] == self.preset['name']:
                self.preset['layers'] = pr['layers']
                self.select_preset(self.preset['name'])
                return
        messagebox.showinfo(APP_NAME, 'This preset is one of your own, so there is no original to go back to.',
                            parent=self.root)

    def _auto(self, v):
        self.store.data['auto_output'] = bool(v)
        self.save_soon()

    def save_soon(self):
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(700, self._save)

    def _save(self):
        self._save_job = None
        self.store.save()

    # ------------------------------------------------------------ presets
    def fill_presets(self):
        self.plist.delete(0, 'end')
        for n in self.store.names():
            self.plist.insert('end', '  ' + n)

    def select_preset(self, name):
        pr = self.store.preset(name) or self.store.data['presets'][0]
        self.preset = pr
        self.store.data['current'] = pr['name']
        self.engine.set_layers(pr['layers'])
        i = self.store.names().index(pr['name'])
        self.plist.selection_clear(0, 'end')
        self.plist.selection_set(i)
        self.plist.see(i)
        self.fill_layers(0)
        self.save_soon()

    def _preset_pick(self, _):
        sel = self.plist.curselection()
        if sel:
            name = self.store.names()[sel[0]]
            if self.preset is None or name != self.preset['name']:
                self.select_preset(name)

    def preset_new(self):
        pr = self.store.add('My preset')
        self.fill_presets()
        self.select_preset(pr['name'])

    def preset_dup(self):
        pr = self.store.duplicate(self.preset)
        self.fill_presets()
        self.select_preset(pr['name'])

    def preset_rename(self):
        name = simpledialog.askstring(APP_NAME, 'New name for this preset:', initialvalue=self.preset['name'], parent=self.root)
        if name and name.strip() and name.strip() != self.preset['name']:
            self.preset['name'] = self.store.unique(name.strip()[:40])
            self.fill_presets()
            self.select_preset(self.preset['name'])

    def preset_del(self):
        if len(self.store.data['presets']) <= 1:
            messagebox.showinfo(APP_NAME, 'Keep at least one preset.', parent=self.root)
            return
        if messagebox.askyesno(APP_NAME, 'Delete the preset "%s"?' % self.preset['name'], parent=self.root):
            self.store.data['presets'].remove(self.preset)
            self.fill_presets()
            self.select_preset(self.store.data['presets'][0]['name'])

    def preset_restore(self):
        have = set(self.store.names())
        added = 0
        for pr in builtin_presets():
            if pr['name'] not in have:
                self.store.data['presets'].append(pr)
                added += 1
        if added:
            self.fill_presets()
            self.select_preset(self.preset['name'])
            messagebox.showinfo(APP_NAME, '%d built-in preset(s) were added back. Your own presets were not changed.' % added,
                                parent=self.root)
        elif messagebox.askyesno(APP_NAME, 'All built-in presets are still in the list.\n\nReset "%s" to its original '
                                 'settings?' % self.preset['name'], parent=self.root):
            for pr in builtin_presets():
                if pr['name'] == self.preset['name']:
                    self.preset['layers'] = pr['layers']
                    self.select_preset(self.preset['name'])
                    return
            messagebox.showinfo(APP_NAME, 'This preset is one of your own, so there is nothing to reset.', parent=self.root)

    # ------------------------------------------------------------ layers
    def _layer_text(self, l):
        return '  %s %s   · %s' % ('●' if l.get('on', True) else '○', EFFECTS[l['effect']]['label'], l.get('blend', 'Add'))

    def fill_layers(self, select=None):
        self.llist.delete(0, 'end')
        layers = self.preset['layers']
        for l in layers:
            self.llist.insert('end', self._layer_text(l))
        if layers:
            i = max(0, min(len(layers) - 1, select or 0))
            self.llist.selection_set(i)
            self.layer = layers[i]
        else:
            self.layer = None
        self.build_panel()

    def _layer_pick(self, _):
        sel = self.llist.curselection()
        if sel and self.preset['layers'][sel[0]] is not self.layer:
            self.layer = self.preset['layers'][sel[0]]
            self.build_panel()

    def _layers_changed(self, select):
        self.engine.set_layers(self.preset['layers'])
        self.fill_layers(select)
        self.save_soon()

    def layer_add(self, effect):
        first = not self.preset['layers']
        self.preset['layers'].append(new_layer(effect, blend='Replace' if effect == 'screen' and first else 'Add'))
        self._layers_changed(len(self.preset['layers']) - 1)

    def layer_del(self):
        if self.layer in self.preset['layers']:
            i = self.preset['layers'].index(self.layer)
            self.preset['layers'].pop(i)
            self._layers_changed(i)

    def layer_move(self, d):
        ls = self.preset['layers']
        if self.layer in ls:
            i = ls.index(self.layer)
            j = i + d
            if 0 <= j < len(ls):
                ls[i], ls[j] = ls[j], ls[i]
                self._layers_changed(j)

    def _relabel(self):
        ls = self.preset['layers']
        if self.layer in ls:
            i = ls.index(self.layer)
            self.llist.delete(i)
            self.llist.insert(i, self._layer_text(self.layer))
            self.llist.selection_set(i)

    # ------------------------------------------------------------ settings panel
    def _row(self, label):
        f = ttk.Frame(self.panel, style='P.TFrame')
        f.pack(fill='x', pady=self.px(3))
        ttk.Label(f, text=label, style='P.TLabel', width=17).pack(side='left')
        return f

    def _slider(self, label, lo, hi, value, setter):
        f = self._row(label)
        val = ttk.Label(f, text='%.2f' % value, style='M.TLabel', width=6, anchor='e')

        def changed(v):
            v = round(float(v), 3)
            val.configure(text='%.2f' % v)
            setter(v)
            self.save_soon()

        val.pack(side='right', padx=(0, self.px(8)))
        Slider(f, lo, hi, value, changed, PANEL, self.sf).pack(side='left', fill='x', expand=True, padx=(0, 6))

    def _choice(self, label, choices, value, setter):
        f = self._row(label)
        var = tk.StringVar(value=value)
        cb = ttk.Combobox(f, values=choices, textvariable=var, state='readonly', width=22)

        def changed(_=None):
            cb.selection_clear()
            setter(var.get())
            self.save_soon()

        cb.bind('<<ComboboxSelected>>', changed)
        cb.pack(side='left')
        return f

    def _swatch(self, parent, color, command):
        b = tk.Button(parent, bg=color, activebackground=color, width=3, relief='flat', bd=0, cursor='hand2', command=command)
        b.pack(side='left', padx=2)
        return b

    def _palette(self, spec, params):
        key = spec['key']
        cur = params[key]
        names = list(PALETTES) + ['Custom…']
        f = self._row(spec['label'])
        var = tk.StringVar(value=cur if isinstance(cur, str) else 'Custom…')
        cb = ttk.Combobox(f, values=names, textvariable=var, state='readonly', width=14)
        cb.pack(side='left')
        strip = tk.Canvas(f, height=self.px(18), width=self.px(170), bg=PANEL, highlightthickness=0)
        strip.pack(side='left', padx=(self.px(8), 0))
        custom = ttk.Frame(self.panel, style='P.TFrame')
        custom.pack(fill='x')

        def draw():
            strip.delete('all')
            a = stops_of(params[key])
            w, n = self.px(170), 48
            pos = np.linspace(0, 1, len(a))
            for i in range(n):
                x = i / (n - 1)
                c = [int(np.interp(x, pos, a[:, ch]) * 255) for ch in range(3)]
                strip.create_rectangle(i * w / n, 0, (i + 1) * w / n + 1, self.px(18), fill='#%02x%02x%02x' % tuple(c), outline='')

        def rebuild():
            for wdg in custom.winfo_children():
                wdg.destroy()
            v = params[key]
            if isinstance(v, str):
                custom.configure(height=1)
                return
            ttk.Label(custom, text='', style='P.TLabel', width=17).pack(side='left')
            for i, col in enumerate(v):
                self._swatch(custom, col, lambda i=i: pick(i))
            if len(v) < 6:
                ttk.Button(custom, text='+', width=2, command=add).pack(side='left', padx=(6, 2))
            if len(v) > 1:
                ttk.Button(custom, text='−', width=2, command=drop).pack(side='left', padx=2)
            ttk.Label(custom, text='click a colour to change it', style='M.TLabel').pack(side='left', padx=8)

        def pick(i):
            c = colorchooser.askcolor(color=params[key][i], parent=self.root, title='Pick a colour')[1]
            if c:
                params[key] = params[key][:i] + [c] + params[key][i + 1:]
                after()

        def add():
            params[key] = list(params[key]) + [params[key][-1]]
            after()
            pick(len(params[key]) - 1)

        def drop():
            params[key] = list(params[key])[:-1]
            after()

        def after():
            draw()
            rebuild()
            self.save_soon()

        def changed(_=None):
            cb.selection_clear()
            n = var.get()
            if n in PALETTES:
                params[key] = n
            elif isinstance(params[key], str):
                params[key] = list(PALETTES.get(params[key], PALETTES['Neon']))
            after()

        cb.bind('<<ComboboxSelected>>', changed)
        draw()
        rebuild()

    def build_panel(self):
        for w in self.panel.winfo_children():
            w.destroy()
        self.sc.yview_moveto(0)
        l = self.layer
        if l is None:
            ttk.Label(self.panel, text='This preset is empty', style='H.TLabel').pack(anchor='w')
            ttk.Label(self.panel, text='Use “+ Add layer” to put an effect on the keyboard.', style='M.TLabel').pack(anchor='w', pady=4)
            return
        fx = EFFECTS[l['effect']]
        head = ttk.Frame(self.panel, style='P.TFrame')
        head.pack(fill='x', pady=(0, self.px(6)))
        ttk.Label(head, text=fx['label'], style='H.TLabel').pack(side='left')

        def toggle(v):
            l['on'] = bool(v)
            self._relabel()
            self.save_soon()

        Check(head, 'Enabled', l.get('on', True), toggle, PANEL, self.sf).pack(side='right', padx=self.px(14))

        def set_blend(v):
            l['blend'] = v
            self._relabel()

        self._choice('Blend', BLENDS, l.get('blend', 'Add'), set_blend)
        self._slider('Strength', 0.0, 1.0, float(l.get('opacity', 1.0)), lambda v: l.__setitem__('opacity', v))
        f = self._row('Lights')
        for z in ZONES:
            def zc(v, z=z):
                l['zones'] = [q for q in ZONES if (q in l['zones'] and q != z) or (q == z and v)]
                self.save_soon()

            Check(f, ZONE_LABEL[z], z in l['zones'], zc, PANEL, self.sf).pack(side='left', padx=(0, self.px(14)))
        tk.Frame(self.panel, bg=LINE, height=1).pack(fill='x', pady=self.px(8))
        prm = l['params']
        for spec in fx['params']:
            k, t = spec['key'], spec['type']
            if t == 'float':
                self._slider(spec['label'], spec['lo'], spec['hi'], float(prm[k]), lambda v, k=k: prm.__setitem__(k, v))
            elif t == 'choice':
                self._choice(spec['label'], spec['choices'], prm[k], lambda v, k=k: prm.__setitem__(k, v))
            elif t == 'bool':
                f = self._row(spec['label'])

                def bc(v, k=k):
                    prm[k] = bool(v)
                    self.save_soon()

                Check(f, '', prm[k], bc, PANEL, self.sf).pack(side='left')
            elif t == 'palette':
                self._palette(spec, prm)
            elif t == 'color':
                f = self._row(spec['label'])

                def cc(k=k):
                    c = colorchooser.askcolor(color=prm[k], parent=self.root, title='Pick a colour')[1]
                    if c:
                        prm[k] = c
                        sw.configure(bg=c, activebackground=c)
                        self.save_soon()

                sw = self._swatch(f, prm[k], cc)
                sw.configure(width=8)
        if l['effect'] == 'ripple':
            ttk.Label(self.panel, text='Lights up where you type. Key presses are only used for this light effect and are never stored.',
                      style='M.TLabel', wraplength=self.px(420), justify='left').pack(anchor='w', pady=(self.px(8), 0))
        if l['effect'] == 'screen':
            ttk.Label(self.panel, text='Copies the colours of your main screen onto the keyboard.',
                      style='M.TLabel', wraplength=self.px(420), justify='left').pack(anchor='w', pady=(self.px(8), 0))

    # ------------------------------------------------------------ periodic
    def tick(self):
        e = self.engine
        self._ticks += 1
        if e.layout is not None and getattr(self, '_layout_seen', None) is not e.layout:
            self._build_preview()
        self._paint()
        if self._ticks % 3 == 0:
            w = int(self.meter.winfo_width() * min(1.0, e.audio.frame.level))
            self.meter.coords(self.meter_id, 0, 0, w, self.meter.winfo_height())
        if self._ticks % 12 == 1:
            if not e.device_ok:
                col, txt = WARN, e.device_status
            elif e.output and e.confirmed is False:
                col, txt = WARN, 'The keyboard is not showing KeyGlow’s colours – press Stop, then Start again'
            elif e.output and e.confirmed:
                col, txt = '#35e07a', 'On the keyboard · confirmed'
            elif e.output:
                col, txt = '#35e07a', 'KeyGlow is driving the keyboard'
            else:
                col, txt = MUTED, 'Preview only – press Start'
            self.dot.itemconfigure(self.dot_id, fill=col)
            self.status.configure(text=txt)
            a = e.audio
            self.audio_lbl.configure(text=('Listening to: ' + a.device_name) if not a.error else 'Audio problem: ' + str(a.error)[:60])
            if e.layout is None and not self._items:
                self._build_preview()
        if self._ticks % 50 == 2:
            if windows_lighting_on():
                if not self.warn.winfo_ismapped():
                    self.warn.pack(fill='x', padx=self.px(16), pady=(0, self.px(4)), before=self.canvas)
            elif self.warn.winfo_ismapped():
                self.warn.pack_forget()
        self.root.after(40, self.tick)

    def session_end(self):
        self.engine.session_end()
        self.store.save()

    def close(self):
        try:
            self.engine.stop()
            self.store.save()
        finally:
            self.root.destroy()
