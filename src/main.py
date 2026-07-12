#!/usr/bin/env python3
"""
IPTV Player - GTK + MPV
CachyOS / Linux / Steam Deck
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, GdkPixbuf, Gio

import mpv
import json
import os
import sys
import threading
import urllib.request
import urllib.error
import re
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
APP_ID   = 'com.iptv.player'
APP_NAME = 'IPTV Player'
DATA_DIR = Path(GLib.get_user_data_dir()) / 'iptv-player'
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLAYLISTS_FILE = DATA_DIR / 'playlists.json'

# ── Colours ───────────────────────────────────────────────────────────────────
CSS = b"""
window, .main-box { background-color: #0a0a0f; }
.topbar { background-color: #12121a; border-bottom: 1px solid #1e1e30; padding: 8px 16px; }
.screen-header { background-color: #12121a; border-bottom: 1px solid #1e1e30; padding: 12px 20px; }
.sidebar { background-color: #12121a; border-right: 1px solid #1e1e30; }
.accent { color: #818cf8; }
.muted { color: #50506a; }
.card { background-color: #12121a; border: 1px solid #1e1e30; border-radius: 12px; padding: 16px; }
.card:hover { border-color: #6c63ff; background-color: #1a1a26; }
.ch-card { background-color: #12121a; border: 1px solid #1e1e30; border-radius: 10px; padding: 12px; }
.ch-card:hover { border-color: #6c63ff; background-color: #1a1a26; }
.ch-card.playing { border-color: #22c55e; }
.back-btn { background-color: transparent; border: 1px solid #1e1e30; color: #9090b0; border-radius: 8px; padding: 6px 14px; }
.back-btn:hover { border-color: #6c63ff; color: #818cf8; }
.play-btn { background-color: #4f46e5; color: white; border-radius: 10px; padding: 12px 24px; font-weight: bold; font-size: 15px; }
.play-btn:hover { background-color: #6c63ff; }
.search-entry { background-color: #1a1a26; border: 1px solid #1e1e30; border-radius: 8px; color: #f1f1f5; padding: 6px 12px; }
.bq-card { background-color: #12121a; border: 1px solid #1e1e30; border-radius: 12px; padding: 20px; }
.bq-card:hover { border-color: #6c63ff; background-color: #1a1a26; }
.now-bar { background-color: #12121a; border-top: 1px solid #1e1e30; padding: 10px 20px; }
.ctrl-btn { background-color: #1a1a26; border: 1px solid #1e1e30; color: #9090b0; border-radius: 8px; padding: 6px 14px; }
.ctrl-btn:hover { border-color: #6c63ff; color: #818cf8; }
label { color: #f1f1f5; }
.title-large { font-size: 22px; font-weight: bold; }
.title-medium { font-size: 16px; font-weight: bold; }
.body-small { font-size: 12px; color: #9090b0; }
.np-label { font-size: 13px; color: #9090b0; }
.success { color: #22c55e; }
"""

# ── M3U Parser ────────────────────────────────────────────────────────────────
def parse_m3u(text):
    lines  = [l.strip() for l in text.split('\n') if l.strip()]
    result = []
    for i, line in enumerate(lines):
        if not line.startswith('#EXTINF'):
            continue
        if i + 1 >= len(lines):
            continue
        url = lines[i + 1]
        if url.startswith('#'):
            continue
        name  = line.split(',')[-1].strip() if ',' in line else 'Unknown'
        logo  = re.search(r'tvg-logo="([^"]*)"', line)
        group = re.search(r'group-title="([^"]*)"', line)
        result.append({
            'name':  name,
            'logo':  logo.group(1) if logo else '',
            'group': group.group(1) if group else 'Other',
            'url':   url,
        })
    return result

def fetch_url(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8', errors='replace')

# ── Playlist storage ──────────────────────────────────────────────────────────
def load_playlists():
    try:
        if PLAYLISTS_FILE.exists():
            return json.loads(PLAYLISTS_FILE.read_text())
    except Exception:
        pass
    return []

def save_playlists(data):
    PLAYLISTS_FILE.write_text(json.dumps(data, indent=2))

# ── Gamepad ───────────────────────────────────────────────────────────────────
GAMEPAD_MAP = {
    0:  'confirm',   # A
    1:  'back',      # B
    2:  'search',    # X
    3:  'y',         # Y
    4:  'lb',        # LB
    5:  'rb',        # RB
    6:  'lt',        # LT
    7:  'rt',        # RT
    8:  'select',
    9:  'start',
    10: 'ls',
    11: 'rs',
    12: 'up',
    13: 'down',
    14: 'left',
    15: 'right',
}

# ── Main Window ───────────────────────────────────────────────────────────────
class IPTVApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=self)
        self.win.present()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1280, 720)

        # State
        self.playlists      = load_playlists()
        self.all_channels   = []
        self.bouquets       = []
        self.bq_channels    = []
        self.filtered_bq    = []
        self.filtered_ch    = []
        self.active_pl      = None
        self.active_bq      = None
        self.playing_ch     = None
        self.active_bq_idx  = 0
        self.active_ch_idx  = 0
        self.mpv_player     = None
        self.screen         = 'playlists'  # playlists | bouquets | channels

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Build UI
        self._build_ui()
        self._setup_gamepad()
        self._show_screen('playlists')

    def _build_ui(self):
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.add_css_class('main-box')
        self.set_content(self.main_box)

        # Topbar
        self._build_topbar()

        # Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)
        self.stack.set_vexpand(True)
        self.main_box.append(self.stack)

        self._build_playlists_screen()
        self._build_bouquets_screen()
        self._build_channels_screen()

    def _build_topbar(self):
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tb.add_css_class('topbar')

        logo = Gtk.Label(label='📺 IPTV')
        logo.add_css_class('accent')
        logo.add_css_class('title-medium')
        tb.append(logo)

        self.np_label = Gtk.Label(label='Nothing playing')
        self.np_label.add_css_class('np-label')
        self.np_label.set_hexpand(True)
        self.np_label.set_xalign(0.0)
        tb.append(self.np_label)

        self.main_box.prepend(tb)

    # ── Playlists screen ──────────────────────────────────────────────────────
    def _build_playlists_screen(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hdr.add_css_class('screen-header')
        title = Gtk.Label(label='Your Playlists')
        title.add_css_class('title-large')
        title.set_hexpand(True)
        title.set_xalign(0.0)
        hdr.append(title)

        btn_url  = Gtk.Button(label='＋ Add URL')
        btn_url.add_css_class('play-btn')
        btn_url.connect('clicked', self._on_add_url)
        hdr.append(btn_url)

        btn_file = Gtk.Button(label='＋ Add File')
        btn_file.add_css_class('ctrl-btn')
        btn_file.connect('clicked', self._on_add_file)
        hdr.append(btn_file)

        box.append(hdr)

        # Scrollable playlist grid
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.pl_flowbox = Gtk.FlowBox()
        self.pl_flowbox.set_valign(Gtk.Align.START)
        self.pl_flowbox.set_max_children_per_line(4)
        self.pl_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.pl_flowbox.set_margin_top(20)
        self.pl_flowbox.set_margin_bottom(20)
        self.pl_flowbox.set_margin_start(20)
        self.pl_flowbox.set_margin_end(20)
        self.pl_flowbox.set_row_spacing(12)
        self.pl_flowbox.set_column_spacing(12)
        scroll.set_child(self.pl_flowbox)
        box.append(scroll)

        self.stack.add_named(box, 'playlists')
        self._render_playlists()

    def _render_playlists(self):
        while child := self.pl_flowbox.get_first_child():
            self.pl_flowbox.remove(child)

        if not self.playlists:
            lbl = Gtk.Label(label='No playlists yet — add one above!')
            lbl.add_css_class('muted')
            self.pl_flowbox.append(lbl)
            return

        for pl in self.playlists:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class('card')
            card.set_size_request(200, -1)

            icon = Gtk.Label(label='📋')
            icon.set_xalign(0.0)
            card.append(icon)

            name_lbl = Gtk.Label(label=pl['name'])
            name_lbl.add_css_class('title-medium')
            name_lbl.set_xalign(0.0)
            name_lbl.set_ellipsize(3)
            card.append(name_lbl)

            meta = Gtk.Label(label=f"{pl.get('count','?')} channels · {'URL' if pl['type']=='url' else 'File'}")
            meta.add_css_class('body-small')
            meta.set_xalign(0.0)
            card.append(meta)

            btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            open_btn = Gtk.Button(label='Open')
            open_btn.add_css_class('play-btn')
            open_btn.connect('clicked', lambda b, p=pl: self._open_playlist(p))
            btn_row.append(open_btn)

            del_btn = Gtk.Button(label='✕')
            del_btn.add_css_class('ctrl-btn')
            del_btn.connect('clicked', lambda b, p=pl: self._delete_playlist(p))
            btn_row.append(del_btn)

            card.append(btn_row)

            gesture = Gtk.GestureClick()
            gesture.connect('released', lambda g, n, x, y, p=pl: self._open_playlist(p))
            card.add_controller(gesture)

            self.pl_flowbox.append(card)

    def _delete_playlist(self, pl):
        self.playlists = [p for p in self.playlists if p['id'] != pl['id']]
        save_playlists(self.playlists)
        self._render_playlists()

    def _open_playlist(self, pl):
        self.active_pl = pl
        self._show_screen('bouquets')
        self.bq_title.set_label(pl['name'])
        self.bq_subtitle.set_label('Loading…')
        self._render_bouquets([])

        def fetch():
            try:
                if pl['type'] == 'url':
                    text = fetch_url(pl['url'])
                else:
                    text = pl['m3u']
                channels = parse_m3u(text)
                GLib.idle_add(self._on_channels_loaded, channels)
            except Exception as e:
                GLib.idle_add(self.bq_subtitle.set_label, f'Error: {e}')

        threading.Thread(target=fetch, daemon=True).start()

    def _on_channels_loaded(self, channels):
        self.all_channels = channels
        bq_map = {}
        for ch in channels:
            g = ch['group']
            if g not in bq_map:
                bq_map[g] = []
            bq_map[g].append(ch)
        self.bouquets      = [{'name': k, 'channels': v} for k, v in bq_map.items()]
        self.filtered_bq   = self.bouquets[:]
        self.active_bq_idx = 0
        self.bq_subtitle.set_label(f'{len(self.bouquets)} bouquets · {len(channels)} channels')
        self._render_bouquets(self.filtered_bq)

    # ── Bouquets screen ───────────────────────────────────────────────────────
    def _build_bouquets_screen(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hdr.add_css_class('screen-header')

        back = Gtk.Button(label='← Back')
        back.add_css_class('back-btn')
        back.connect('clicked', lambda b: self._show_screen('playlists'))
        hdr.append(back)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        self.bq_title    = Gtk.Label(label='Playlist')
        self.bq_title.add_css_class('title-large')
        self.bq_title.set_xalign(0.0)
        self.bq_subtitle = Gtk.Label(label='')
        self.bq_subtitle.add_css_class('body-small')
        self.bq_subtitle.set_xalign(0.0)
        info.append(self.bq_title)
        info.append(self.bq_subtitle)
        hdr.append(info)

        self.bq_search = Gtk.SearchEntry()
        self.bq_search.set_placeholder_text('Search bouquets…')
        self.bq_search.add_css_class('search-entry')
        self.bq_search.connect('search-changed', self._on_bq_search)
        hdr.append(self.bq_search)

        box.append(hdr)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self.bq_flowbox = Gtk.FlowBox()
        self.bq_flowbox.set_valign(Gtk.Align.START)
        self.bq_flowbox.set_max_children_per_line(5)
        self.bq_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.bq_flowbox.set_margin_top(20)
        self.bq_flowbox.set_margin_bottom(20)
        self.bq_flowbox.set_margin_start(20)
        self.bq_flowbox.set_margin_end(20)
        self.bq_flowbox.set_row_spacing(12)
        self.bq_flowbox.set_column_spacing(12)
        scroll.set_child(self.bq_flowbox)
        box.append(scroll)

        self.stack.add_named(box, 'bouquets')

    def _get_bq_icon(self, name):
        n = name.lower()
        if any(x in n for x in ['sport','football','soccer','nba','nfl']): return '⚽'
        if any(x in n for x in ['movie','film','cinema','vod']): return '🎬'
        if 'news' in n: return '📰'
        if any(x in n for x in ['kids','child','cartoon']): return '🧸'
        if 'music' in n: return '🎵'
        if 'docu' in n: return '🎥'
        if any(x in n for x in ['series','show']): return '📺'
        if 'radio' in n: return '📻'
        return '📡'

    def _render_bouquets(self, bouquets):
        while child := self.bq_flowbox.get_first_child():
            self.bq_flowbox.remove(child)

        if not bouquets:
            lbl = Gtk.Label(label='No bouquets found')
            lbl.add_css_class('muted')
            self.bq_flowbox.append(lbl)
            return

        for bq in bouquets:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class('bq-card')
            card.set_size_request(160, -1)

            icon = Gtk.Label(label=self._get_bq_icon(bq['name']))
            icon.set_markup(f"<span size='xx-large'>{self._get_bq_icon(bq['name'])}</span>")
            icon.set_xalign(0.0)
            card.append(icon)

            name_lbl = Gtk.Label(label=bq['name'])
            name_lbl.add_css_class('title-medium')
            name_lbl.set_xalign(0.0)
            name_lbl.set_wrap(True)
            name_lbl.set_max_width_chars(20)
            card.append(name_lbl)

            count_lbl = Gtk.Label(label=f"{len(bq['channels'])} channels")
            count_lbl.add_css_class('body-small')
            count_lbl.set_xalign(0.0)
            card.append(count_lbl)

            gesture = Gtk.GestureClick()
            gesture.connect('released', lambda g, n, x, y, b=bq: self._open_bouquet(b))
            card.add_controller(gesture)

            self.bq_flowbox.append(card)

    def _on_bq_search(self, entry):
        q = entry.get_text().lower()
        self.filtered_bq = [b for b in self.bouquets if q in b['name'].lower()]
        self._render_bouquets(self.filtered_bq)

    def _open_bouquet(self, bq):
        self.active_bq      = bq
        self.bq_channels    = bq['channels']
        self.filtered_ch    = bq['channels'][:]
        self.active_ch_idx  = 0
        self.ch_title.set_label(bq['name'])
        self.ch_subtitle.set_label(f"{len(bq['channels'])} channels")
        self.ch_search.set_text('')
        self._render_channels(self.filtered_ch)
        self._show_screen('channels')

    # ── Channels screen ───────────────────────────────────────────────────────
    def _build_channels_screen(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hdr.add_css_class('screen-header')

        back = Gtk.Button(label='← Back')
        back.add_css_class('back-btn')
        back.connect('clicked', lambda b: self._show_screen('bouquets'))
        hdr.append(back)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        self.ch_title    = Gtk.Label(label='Bouquet')
        self.ch_title.add_css_class('title-large')
        self.ch_title.set_xalign(0.0)
        self.ch_subtitle = Gtk.Label(label='')
        self.ch_subtitle.add_css_class('body-small')
        self.ch_subtitle.set_xalign(0.0)
        info.append(self.ch_title)
        info.append(self.ch_subtitle)
        hdr.append(info)

        self.ch_search = Gtk.SearchEntry()
        self.ch_search.set_placeholder_text('Search channels…')
        self.ch_search.add_css_class('search-entry')
        self.ch_search.connect('search-changed', self._on_ch_search)
        hdr.append(self.ch_search)

        box.append(hdr)

        # Main content: channel grid + video panel
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.set_vexpand(True)

        # Channel grid
        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        self.ch_flowbox = Gtk.FlowBox()
        self.ch_flowbox.set_valign(Gtk.Align.START)
        self.ch_flowbox.set_max_children_per_line(6)
        self.ch_flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ch_flowbox.set_margin_top(16)
        self.ch_flowbox.set_margin_bottom(16)
        self.ch_flowbox.set_margin_start(16)
        self.ch_flowbox.set_margin_end(16)
        self.ch_flowbox.set_row_spacing(10)
        self.ch_flowbox.set_column_spacing(10)
        scroll.set_child(self.ch_flowbox)
        content.append(scroll)

        # Video panel
        self.video_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.video_panel.set_size_request(400, -1)
        self.video_panel.add_css_class('sidebar')

        # MPV widget
        self.video_area = Gtk.DrawingArea()
        self.video_area.set_vexpand(True)
        self.video_area.set_content_width(400)
        self.video_area.set_size_request(400, 225)
        self.video_panel.append(self.video_area)

        # Now playing info
        np_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        np_box.set_margin_top(12)
        np_box.set_margin_bottom(12)
        np_box.set_margin_start(16)
        np_box.set_margin_end(16)

        self.np_ch_name = Gtk.Label(label='Select a channel')
        self.np_ch_name.add_css_class('title-medium')
        self.np_ch_name.set_xalign(0.0)
        self.np_ch_name.set_ellipsize(3)
        np_box.append(self.np_ch_name)

        self.np_ch_group = Gtk.Label(label='')
        self.np_ch_group.add_css_class('body-small')
        self.np_ch_group.set_xalign(0.0)
        np_box.append(self.np_ch_group)

        self.video_panel.append(np_box)

        # Controls
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctrl_box.set_margin_start(16)
        ctrl_box.set_margin_end(16)
        ctrl_box.set_margin_bottom(12)

        self.pause_btn = Gtk.Button(label='⏸ Pause')
        self.pause_btn.add_css_class('ctrl-btn')
        self.pause_btn.connect('clicked', self._on_pause)
        ctrl_box.append(self.pause_btn)

        stop_btn = Gtk.Button(label='⏹ Stop')
        stop_btn.add_css_class('ctrl-btn')
        stop_btn.connect('clicked', self._on_stop)
        ctrl_box.append(stop_btn)

        self.video_panel.append(ctrl_box)

        # Volume
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vol_box.set_margin_start(16)
        vol_box.set_margin_end(16)
        vol_box.set_margin_bottom(16)
        vol_lbl = Gtk.Label(label='Vol')
        vol_lbl.add_css_class('body-small')
        vol_box.append(vol_lbl)
        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 5)
        self.vol_scale.set_value(100)
        self.vol_scale.set_hexpand(True)
        self.vol_scale.connect('value-changed', self._on_volume)
        vol_box.append(self.vol_scale)
        self.video_panel.append(vol_box)

        content.append(self.video_panel)
        box.append(content)

        self.stack.add_named(box, 'channels')

    def _render_channels(self, channels):
        while child := self.ch_flowbox.get_first_child():
            self.ch_flowbox.remove(child)

        if not channels:
            lbl = Gtk.Label(label='No channels found')
            lbl.add_css_class('muted')
            self.ch_flowbox.append(lbl)
            return

        for i, ch in enumerate(channels):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class('ch-card')
            card.set_size_request(130, -1)

            if self.playing_ch and self.playing_ch['url'] == ch['url']:
                card.add_css_class('playing')

            init = Gtk.Label(label=ch['name'][:2].upper())
            init.set_markup(f"<span size='x-large' weight='bold' color='#50506a'>{ch['name'][:2].upper()}</span>")
            card.append(init)

            name_lbl = Gtk.Label(label=ch['name'])
            name_lbl.add_css_class('body-small')
            name_lbl.set_xalign(0.5)
            name_lbl.set_ellipsize(3)
            name_lbl.set_max_width_chars(14)
            card.append(name_lbl)

            gesture = Gtk.GestureClick()
            gesture.connect('released', lambda g, n, x, y, c=ch: self._play_channel(c))
            card.add_controller(gesture)

            self.ch_flowbox.append(card)

    def _on_ch_search(self, entry):
        q = entry.get_text().lower()
        self.filtered_ch = [c for c in self.bq_channels if q in c['name'].lower()]
        self._render_channels(self.filtered_ch)

    # ── MPV Playback ──────────────────────────────────────────────────────────
    def _init_mpv(self):
        if self.mpv_player:
            return
        wid = self.video_area.get_native().get_surface().get_xid()
        self.mpv_player = mpv.MPV(
            wid=str(wid),
            vo='x11',
            hwdec='auto',
            cache=True,
            network_timeout=10,
        )

    def _play_channel(self, ch):
        self.playing_ch = ch
        self.np_label.set_label(f'▶ {ch["name"]}')
        self.np_ch_name.set_label(ch['name'])
        self.np_ch_group.set_label(ch.get('group', ''))
        self.pause_btn.set_label('⏸ Pause')

        try:
            if not self.mpv_player:
                wid = self.video_area.get_native().get_surface().get_xid()
                self.mpv_player = mpv.MPV(
                    wid=str(wid),
                    vo='x11',
                    hwdec='auto',
                    cache=True,
                )
            self.mpv_player.play(ch['url'])
        except Exception as e:
            print(f'MPV error: {e}')

        self._render_channels(self.filtered_ch)

    def _on_pause(self, btn):
        if self.mpv_player:
            self.mpv_player.pause = not self.mpv_player.pause
            self.pause_btn.set_label('▶ Resume' if self.mpv_player.pause else '⏸ Pause')

    def _on_stop(self, btn):
        if self.mpv_player:
            self.mpv_player.stop()
        self.playing_ch = None
        self.np_label.set_label('Nothing playing')
        self.np_ch_name.set_label('Select a channel')
        self.np_ch_group.set_label('')
        self.pause_btn.set_label('⏸ Pause')
        self._render_channels(self.filtered_ch)

    def _on_volume(self, scale):
        if self.mpv_player:
            self.mpv_player.volume = scale.get_value()

    # ── Screen navigation ─────────────────────────────────────────────────────
    def _show_screen(self, name):
        self.screen = name
        self.stack.set_visible_child_name(name)

    # ── Add playlist dialogs ──────────────────────────────────────────────────
    def _on_add_url(self, btn):
        dialog = Adw.MessageDialog(transient_for=self, title='Add Playlist from URL')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('ok', 'Add')
        dialog.set_response_appearance('ok', Adw.ResponseAppearance.SUGGESTED)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)

        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text('Playlist name')
        box.append(name_entry)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text('M3U URL')
        box.append(url_entry)

        status_lbl = Gtk.Label(label='')
        status_lbl.add_css_class('body-small')
        box.append(status_lbl)

        dialog.set_extra_child(box)

        def on_response(d, response):
            if response != 'ok':
                d.destroy()
                return
            name = name_entry.get_text().strip() or 'Playlist'
            url  = url_entry.get_text().strip()
            if not url:
                status_lbl.set_label('Please enter a URL')
                return
            status_lbl.set_label('Fetching…')

            def fetch():
                try:
                    text = fetch_url(url)
                    chs  = parse_m3u(text)
                    pl   = {'id': str(GLib.get_real_time()), 'name': name, 'url': url, 'type': 'url', 'count': len(chs)}
                    self.playlists.append(pl)
                    save_playlists(self.playlists)
                    GLib.idle_add(self._render_playlists)
                    GLib.idle_add(d.destroy)
                except Exception as e:
                    GLib.idle_add(status_lbl.set_label, f'Error: {e}')

            threading.Thread(target=fetch, daemon=True).start()

        dialog.connect('response', on_response)
        dialog.present()

    def _on_add_file(self, btn):
        dialog = Gtk.FileDialog()
        f = Gtk.FileFilter()
        f.set_name('M3U Playlist')
        f.add_pattern('*.m3u')
        f.add_pattern('*.m3u8')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)

        def on_open(d, result):
            try:
                file = d.open_finish(result)
                path = file.get_path()
                text = open(path, 'r', errors='replace').read()
                chs  = parse_m3u(text)
                name = os.path.splitext(os.path.basename(path))[0]
                pl   = {'id': str(GLib.get_real_time()), 'name': name, 'm3u': text, 'type': 'file', 'count': len(chs)}
                self.playlists.append(pl)
                save_playlists(self.playlists)
                self._render_playlists()
            except Exception as e:
                print(f'File error: {e}')

        dialog.open(self, None, on_open)

    # ── Gamepad ───────────────────────────────────────────────────────────────
    def _setup_gamepad(self):
        # Poll gamepad every 33ms
        self._gp_prev = {}
        GLib.timeout_add(33, self._poll_gamepad)

    def _poll_gamepad(self):
        try:
            import glob, struct
            js_files = glob.glob('/dev/input/js*')
            if not js_files:
                return True
            # Non-blocking read via select
            import select
            js = js_files[0]
            if not hasattr(self, '_js_fd'):
                self._js_fd = open(js, 'rb')
            r, _, _ = select.select([self._js_fd], [], [], 0)
            if not r:
                return True
            data = self._js_fd.read(8)
            if len(data) < 8:
                return True
            _, value, type_, number = struct.unpack('IhBB', data)
            if type_ & 0x01:  # button
                key = GAMEPAD_MAP.get(number)
                if key:
                    pressed   = value == 1
                    was       = self._gp_prev.get(number, False)
                    self._gp_prev[number] = pressed
                    if pressed and not was:
                        GLib.idle_add(self._on_gamepad_button, key)
            elif type_ & 0x02:  # axis
                if number == 1:   # left stick Y
                    if value < -16000:
                        GLib.idle_add(self._on_gamepad_button, 'up')
                    elif value > 16000:
                        GLib.idle_add(self._on_gamepad_button, 'down')
                elif number == 0:  # left stick X
                    if value < -16000:
                        GLib.idle_add(self._on_gamepad_button, 'left')
                    elif value > 16000:
                        GLib.idle_add(self._on_gamepad_button, 'right')
        except Exception:
            pass
        return True

    def _on_gamepad_button(self, key):
        if key == 'back':
            if self.screen == 'channels':
                self._show_screen('bouquets')
            elif self.screen == 'bouquets':
                self._show_screen('playlists')
        elif key == 'confirm':
            if self.screen == 'channels' and self.filtered_ch:
                self._play_channel(self.filtered_ch[self.active_ch_idx])
        elif key == 'down':
            if self.screen == 'channels' and self.filtered_ch:
                self.active_ch_idx = min(self.active_ch_idx + 1, len(self.filtered_ch) - 1)
        elif key == 'up':
            if self.screen == 'channels' and self.filtered_ch:
                self.active_ch_idx = max(self.active_ch_idx - 1, 0)
        elif key == 'y':
            if self.screen == 'channels':
                self.ch_search.grab_focus()
            elif self.screen == 'bouquets':
                self.bq_search.grab_focus()
        elif key == 'start':
            if self.mpv_player:
                self._on_pause(None)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = IPTVApp()
    app.run(sys.argv)

if __name__ == '__main__':
    main()
