"""App state and the lighting engine - the only code that sends colours to the lamps."""
import glob
import json
import os
import threading
import time
import zlib

from colors import (blend_colours, build_7_zone_palette, extract_spotify_palette, flow_gradient,
                    get_dual_split_colors, led_finish, lift_frame, sample_palette_continuous)
from config import AD_WHITE, DEFAULT_THEME, STARTUP_PALETTE, TARGET_IPS, clamp, load_config, save_config
import devices
from lamps import GoveeController
import players
import spotify
from spotify import spotify_connect_and_play
from tempo import DEFAULT_BPM, UNKNOWN_SOURCES, calculate_dynamic_intensity, fetch_track_bpm


_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _web_version():
    """Changes whenever a dashboard file changes, so open pages reload themselves."""
    try:
        return int(max(os.path.getmtime(f) for f in glob.glob(os.path.join(_WEB_DIR, "*"))))
    except (OSError, ValueError):
        return 0


def _hex(c):
    return f"#{int(c[0]):02X}{int(c[1]):02X}{int(c[2]):02X}"


ATTENTION_ZONES = (4, 5, 6)   # top half of a 7-zone lamp (zone 0 = bottom)
ATTENTION_RGB = (255, 0, 0)
LAMP_FPS = 15        # colour updates per second sent to the lamps in moving modes
ZONE_SPAN = 0.5      # 7-Zone: each lamp shows half the colour loop, top to bottom
DUO_OFFSET = 0.38    # Two-Lamp moving: right lamp is this far ahead in the loop
WAVE_OFFSET = 0.0     # Colour Fade: both lamps show the same colour at the same time

# Ads from other players usually just have one of these as their title/artist
AD_TITLES = {"ad", "ads", "advert", "sponsored", "sponsored ad", "sponsored content"}

# The lamps show a colour a moment after we send it (network + the lamp itself + our 15 fps
# frames), so the pulse is started this much early to land on the beat. An estimate.
PULSE_LEAD = 0.08
# Moving colours are sent this far ahead: a lamp keeps showing a zone's colour until its next
# update (about 0.15 s later), so on average it should show where the colour will be by then.
LAMP_LEAD = 0.08

# Some colour crossings (e.g. yellow to blue) are deliberately quick. On the lamps, which show
# colours in steps, a fast edge looks like a pop. No zone is allowed to change faster than this
# (levels of 255 per second): the crossing still happens, just without the jolt.
SLEW_PER_SEC = 200.0

PREVIEW_MODES = ("smooth", "low", "off")
# Full dashboard refresh rate. In "smooth" the lamp preview gets its own tiny
# colour-only frames instead, so the big refresh can be rare.
PREVIEW_INTERVAL = {"smooth": None, "low": 2.0, "off": None}   # None = only on real changes


def blend_frames(a, b, t):
    """Blends two (left_segs, right_segs) frames. t is 0..1 (eased inside)."""
    return (
        [blend_colours(a[0][i], b[0][i], t) for i in range(7)],
        [blend_colours(a[1][i], b[1][i], t) for i in range(7)],
    )


SPATIAL_MODES = ("duo", "segmented", "unified")
MOTION_MODES = ("flow", "static")



class AppState:
    def __init__(self):
        self.govee = GoveeController(TARGET_IPS)
        self.govee.get_envelope = self.get_beat_envelope
        self.govee.on_lamps_changed = self.broadcast
        self.identifying_ip = None

        cfg = load_config()

        # Persisted lamp side assignments
        saved_left = cfg.get("left_ip")
        saved_right = cfg.get("right_ip")
        if saved_left:
            self.govee.left_ip = saved_left
            if saved_left not in self.govee.all_ips:
                self.govee.all_ips.append(saved_left)
        if saved_right:
            self.govee.right_ip = saved_right
            if saved_right not in self.govee.all_ips:
                self.govee.all_ips.append(saved_right)
        self.govee.sync_ordered_ips()

        # Other brands (WiZ / LIFX / WLED) saved from earlier runs
        for d in cfg.get("devices") or []:
            try:
                self.govee.devices.append(devices.make_device(d.get("kind"), d.get("ip"), d.get("side", "left")))
            except (ValueError, AttributeError):
                pass
        self.discovered = []       # lights found by the last scan, not added yet
        self.scanning = False

        def _f(key, default, lo, hi):
            try:
                return clamp(float(cfg.get(key, default)), lo, hi)
            except (TypeError, ValueError):
                return default

        # Persisted user settings (all survive a restart now)
        self.spatial_mode = cfg.get("spatial_mode") if cfg.get("spatial_mode") in SPATIAL_MODES else "segmented"
        self.motion_mode = cfg.get("motion_mode") if cfg.get("motion_mode") in MOTION_MODES else "flow"
        # Each mode has fixed motion: Solid & Split are still, Wave & 7-Zone move
        if self.spatial_mode == "duo":
            self.motion_mode = "static"
        elif self.spatial_mode == "segmented":
            self.motion_mode = "flow"
        self.flow_speed = _f("flow_speed", 5.0, 2.5, 20.0)     # seconds per colour cycle
        self.trans_speed = _f("trans_speed", 3.0, 1.0, 8.0)    # seconds for song-change fade
        self.vibrancy = _f("vibrancy", 1.15, 0.7, 1.8)
        self.brightness = int(_f("brightness", 100, 1, 100))
        self.pulse_depth = _f("pulse_depth", 0.60, 0.1, 0.9)
        self.is_swapped_lr = bool(cfg.get("is_swapped_lr", False))
        self.is_inverted_tb = bool(cfg.get("is_inverted_tb", False))
        self.music_pulse_enabled = bool(cfg.get("music_pulse", False))
        self.dynamic_intensity_enabled = bool(cfg.get("dynamic_intensity", False))
        self.dark_boost = _f("dark_boost", 0.65, 0.0, 1.0)     # lift for colours LEDs can't show
        self.preview_mode = cfg.get("preview_mode") if cfg.get("preview_mode") in PREVIEW_MODES else "smooth"
        self.fs_motion = int(_f("fs_motion", 1, 0, 5))   # full-screen background: 0 off, 1 very slow ... 5 fast
        self.white_accent = bool(cfg.get("white_accent", True))  # add white highlights from the cover
        # Spotify volume / shuffle / repeat. After you change one, Spotify's own
        # (older) answer is ignored briefly so the control doesn't jump back.
        self.sp_volume = None
        self.sp_shuffle = False
        self.sp_repeat = False
        self.sp_hold_until = {}

        self.is_powered_on = True
        self.govee.is_powered_on = True
        self.spotify_wake = threading.Event()
        self.last_nudge = 0.0

        # Tempo / beat pulse
        self.current_bpm = DEFAULT_BPM
        self.detected_bpm = DEFAULT_BPM
        self.bpm_source = "Default"
        self.detected_bpm_source = "Default"
        self.bpm_manual = False
        self.bpm_known = False          # False until a real tempo is found (or set by hand): no pulse before then
        self.detected_bpm_known = False
        # Beats are placed on a grid measured from the start of the song,
        # shifted by this offset (set by Tap Tempo) - so the pulse follows
        # the song position instead of a random start time.
        self.beat_offset = 0.0

        # Playback
        self.current_pos = 0.0
        self.current_dur = 0.0
        self.pos_sample_time = time.time()
        self.is_playing = False
        self.current_intensity = 1.0
        self.current_section = "Normal"
        self.locked_swatch_index = None
        self.is_ad = False

        self.current_track = "Waiting for Spotify..."
        self.current_artist = ""
        self.current_art_url = ""
        self.current_art_bytes = None
        self.current_lamp_palette = list(STARTUP_PALETTE)
        self.current_raw_palette = list(STARTUP_PALETTE)

        self.last_track_sig = None
        self.palette_art_url = None    # which album art the current colours came from
        self.art_wait_polls = 0        # polls we've waited for Spotify to update the art link
        self.fade_prev_pal = None      # previous song's palette, kept moving during a song fade
        self.poll_lock = threading.Lock()

        # Lighting engine state - ONLY engine_loop sends colours to the lamps
        self.wake = threading.Event()
        self.fade_from = None      # frame we are fading away from
        self.fade_start = 0.0
        self.fade_dur = 0.0
        self.out_frame = None      # last frame actually sent: (left_segs, right_segs)
        self.needs_send = True
        self.hold_pending = False
        self.last_motion = 0.0
        self.intensity_target = 1.0
        self.engine_paused = False
        self.lamp_test_step = None
        self.is_running = True
        self.last_broadcast = 0.0
        self.attention = False                 # "Claude needs you" signal on the right lamp
        self.attention_turned_on_lamps = False
        self._slew_prev = None         # last frame after the speed limit (moving modes only)
        self._slew_t = 0.0
        self.phase = 0.0               # where the moving modes are in the colour loop
        self.phase_time = time.time()

        self.subscribers = []
        self.sub_lock = threading.Lock()

    # ------------------------------------------------------------------
    # UI live updates
    # ------------------------------------------------------------------
    def add_subscriber(self, q):
        with self.sub_lock:
            self.subscribers.append(q)

    def remove_subscriber(self, q):
        with self.sub_lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def broadcast(self):
        self.last_broadcast = time.time()
        with self.sub_lock:
            if not self.subscribers:
                return
            data = f"data: {json.dumps(self.to_dict())}\n\n"
            for q in list(self.subscribers):
                try:
                    q.put_nowait(data)
                except Exception:
                    pass

    def _maybe_broadcast(self, now):
        """Live preview updates while colours move. Rate depends on the
        Lamp Preview setting; 'off' only sends updates on real changes."""
        interval = PREVIEW_INTERVAL.get(self.preview_mode, 0.3)
        if interval is not None and now - self.last_broadcast >= interval:
            self.broadcast()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def set_playback_extra(self, key, value):
        """Volume / shuffle / repeat changed from the dashboard."""
        setattr(self, "sp_" + key, value)
        self.sp_hold_until[key] = time.time() + 2.5
        self.broadcast()

    def _read_playback_extras(self):
        now = time.time()
        for key in ("volume", "shuffle", "repeat"):
            if now >= self.sp_hold_until.get(key, 0.0) and spotify.EXTRAS.get(key) is not None:
                setattr(self, "sp_" + key, spotify.EXTRAS[key])

    def save_config(self):
        cfg = load_config()
        cfg.update({
            "left_ip": self.govee.left_ip,
            "right_ip": self.govee.right_ip,
            "spatial_mode": self.spatial_mode,
            "motion_mode": self.motion_mode,
            "flow_speed": self.flow_speed,
            "trans_speed": self.trans_speed,
            "vibrancy": self.vibrancy,
            "brightness": self.brightness,
            "pulse_depth": self.pulse_depth,
            "is_swapped_lr": self.is_swapped_lr,
            "is_inverted_tb": self.is_inverted_tb,
            "music_pulse": self.music_pulse_enabled,
            "dynamic_intensity": self.dynamic_intensity_enabled,
            "dark_boost": self.dark_boost,
            "preview_mode": self.preview_mode,
            "fs_motion": self.fs_motion,
            "white_accent": self.white_accent,
            "devices": [d.to_config() for d in self.govee.devices],
        })
        save_config(cfg)

    # ------------------------------------------------------------------
    # Lighting requests (called from anywhere; the engine does the sending)
    # ------------------------------------------------------------------
    def request_update(self, fade_sec=1.2):
        """Ask the engine to move to the current target. Fades from whatever
        the lamps are showing right now, even if another fade is mid-way."""
        self.fade_prev_pal = None
        if fade_sec and fade_sec > 0 and self.out_frame is not None:
            self.fade_from = self.out_frame
            self.fade_start = time.time()
            self.fade_dur = float(fade_sec)
        else:
            self.fade_from = None
        self.needs_send = True
        self.wake.set()

    def apply_lighting(self, fade_sec=1.2):
        self.request_update(fade_sec)
        self.broadcast()

    def set_new_track_palette(self, raw_pal, lamp_pal):
        """Crossfades the lamps to a new song's colours. The old song's colours
        keep moving while they fade out, so the motion never freezes."""
        if not lamp_pal:
            return
        old_pal = list(self.current_lamp_palette) if self.current_lamp_palette else None
        now = time.time()
        mid_fade = self.fade_from is not None and (now - self.fade_start) < self.fade_dur
        self.current_raw_palette = list(raw_pal)
        self.current_lamp_palette = list(lamp_pal)
        if old_pal and not mid_fade and self.out_frame is not None and self.locked_swatch_index is None:
            self.fade_prev_pal = old_pal
            self.fade_from = "palette"
            self.fade_start = now
            self.fade_dur = float(self.trans_speed)
            self.needs_send = True
            self.wake.set()
        else:
            # Already mid-fade (fast skipping): fade from exactly what's showing now
            self.request_update(self.trans_speed)
        self.broadcast()

    def set_power(self, on):
        self.is_powered_on = bool(on)
        self.govee.set_power(self.is_powered_on)
        if self.is_powered_on:
            self.out_frame = None   # lamps may have reset; send fresh
            self.request_update(0)
        self.broadcast()

    def set_brightness(self, val):
        self.brightness = int(clamp(int(val), 1, 100))
        self.govee.set_brightness(self.brightness)
        self.save_config()
        self.broadcast()

    def assign_lamp_side(self, side, ip):
        if not ip:
            return
        if side == "left":
            old_left = self.govee.left_ip
            self.govee.left_ip = ip
            if self.govee.right_ip == ip:
                self.govee.right_ip = old_left
        elif side == "right":
            old_right = self.govee.right_ip
            self.govee.right_ip = ip
            if self.govee.left_ip == ip:
                self.govee.left_ip = old_right
        self.govee.sync_ordered_ips()
        self.save_config()
        self.out_frame = None
        self.request_update(0)
        self.broadcast()

    # ------------------------------------------------------------------
    # Other lights (WiZ / LIFX / WLED)
    # ------------------------------------------------------------------
    def add_device(self, kind, ip, side):
        ip = str(ip or "").strip()
        if any(d.ip == ip for d in self.govee.devices):
            raise ValueError("that light is already added")
        dev = devices.make_device(kind, ip, side)
        self.govee.devices.append(dev)
        self.discovered = [f for f in self.discovered if f["ip"] != ip]
        threading.Thread(target=dev.ping, daemon=True).start()
        self.save_config()
        self.out_frame = None
        self.request_update(0)
        self.broadcast()

    def remove_device(self, ip):
        self.govee.devices = [d for d in self.govee.devices if d.ip != ip]
        self.save_config()
        self.broadcast()

    def scan_devices(self):
        if self.scanning:
            return
        self.scanning = True
        self.broadcast()
        try:
            have = {d.ip for d in self.govee.devices}
            self.discovered = [f for f in devices.discover_all() if f["ip"] not in have]
        finally:
            self.scanning = False
            self.broadcast()

    def swap_lr(self):
        """Swaps which physical lamp is treated as left/right. The preview always
        shows exactly what each side is sent, so it stays correct after restarts."""
        self.is_swapped_lr = not self.is_swapped_lr
        self.govee.left_ip, self.govee.right_ip = self.govee.right_ip, self.govee.left_ip
        self.govee.sync_ordered_ips()
        self.save_config()
        self.out_frame = None
        self.request_update(0)
        self.broadcast()

    def invert_tb(self):
        """Flips the 7-zone gradient upside down (only affects 7-Zone mode)."""
        self.is_inverted_tb = not self.is_inverted_tb
        self.save_config()
        self.request_update(0.8)
        self.broadcast()

    def identify(self, ip):
        def _start(target):
            self.engine_paused = True
            self.identifying_ip = target
            self.broadcast()
            time.sleep(0.12)   # let any in-flight frame finish first

        def _done(target):
            self.identifying_ip = None
            self.engine_paused = False
            self.out_frame = None
            self.request_update(0)
            self.broadcast()

        self.govee.identify_lamp(ip, on_start=_start, on_done=_done)

    def set_attention(self, on):
        """Top half of the right lamp turns red (and stays) until cleared -
        used by a Claude Code hook to say "I need your input"."""
        on = bool(on)
        if on == self.attention:
            return
        self.attention = on
        if on and not self.is_powered_on:
            # Lamps are off: show just the signal, nothing else
            self.govee.set_power(True)
            self.is_powered_on = True
            self.attention_turned_on_lamps = True
        elif not on and self.attention_turned_on_lamps:
            self.attention_turned_on_lamps = False
            self.set_power(False)
            return
        self.request_update(0)
        self.broadcast()

    def flash(self, rgb=(255, 0, 0), times=3):
        """Attention flash on both lamps, then back to whatever they were doing."""
        if self.engine_paused:
            return   # already blinking (identify or another flash)
        was_on = self.is_powered_on

        def _start():
            self.engine_paused = True
            if not was_on:
                self.govee.set_power(True)
                time.sleep(0.4)
            time.sleep(0.12)   # let any in-flight frame finish first

        def _done():
            self.engine_paused = False
            if was_on:
                self.out_frame = None
                self.request_update(0)
            else:
                self.govee.set_power(False)

        self.govee.flash(rgb, times, on_start=_start, on_done=_done)

    def connect_and_start(self):
        self.set_power(True)
        spotify_connect_and_play()
        time.sleep(0.4)
        self.poll_spotify_step()
        self.broadcast()

    # ------------------------------------------------------------------
    # Beat pulse
    # ------------------------------------------------------------------
    def _smoothed_intensity(self):
        """Energy level glides continuously (about 3 s to settle) instead of
        stepping each time Spotify is checked, which looked like little jumps."""
        now = time.time()
        # Capped step: after a quiet spell it must not jump in one go
        dt = min(0.1, now - getattr(self, "_intensity_t", now))
        self._intensity_t = now
        target = self._intensity_goal()
        self.current_intensity += (target - self.current_intensity) * min(1.0, dt / 1.5)
        return self.current_intensity

    def _intensity_goal(self):
        """Where the energy level is heading, worked out from the song position every frame,
        so it follows seeks and pauses exactly instead of stepping at each Spotify check."""
        if self.is_ad:
            return 1.0   # ads are plain white at full brightness
        if self.dynamic_intensity_enabled and self.current_dur > 0:
            inte, sec = calculate_dynamic_intensity(self.song_time(), self.current_dur)
            self.intensity_target, self.current_section = inte, sec
            return inte
        return self.intensity_target

    def _energy_moving(self):
        return (self.dynamic_intensity_enabled
                and abs(self._intensity_goal() - self.current_intensity) > 0.004)

    def song_time(self):
        if self.is_playing:
            return self.current_pos + (time.time() - self.pos_sample_time)
        return self.current_pos

    def get_beat_envelope(self):
        """Brightness multiplier for the current instant: kick-drum style hit on
        each beat that decays to (1 - depth). Also applies Dynamic Energy."""
        if not self.is_powered_on:
            return 1.0
        base = self._smoothed_intensity() if self.dynamic_intensity_enabled else 1.0
        if not self.music_pulse_enabled or not self.is_playing or not self.bpm_known:
            return base      # no real tempo (yet): a steady light beats a pulse at a made-up speed
        bpm = clamp(self.current_bpm, 40.0, 240.0)
        period = 60.0 / bpm
        progress = ((self.song_time() + PULSE_LEAD - self.beat_offset) % period) / period
        depth = clamp(self.pulse_depth, 0.1, 0.9)
        decay = (1.0 - progress) ** 2.2
        return base * ((1.0 - depth) + depth * decay)

    def set_manual_bpm(self, bpm, tap=False):
        self.current_bpm = clamp(float(bpm), 40.0, 240.0)
        self.bpm_manual = True
        self.bpm_known = True
        self.bpm_source = "Tap Tempo" if tap else "Manual"
        if tap:
            # The last tap was on a beat - line the grid up with it
            self.beat_offset = self.song_time() % (60.0 / self.current_bpm)
        self.wake.set()
        self.broadcast()

    def set_auto_bpm(self):
        self.current_bpm = self.detected_bpm
        self.bpm_manual = False
        self.bpm_known = self.detected_bpm_known
        self.beat_offset = 0.0
        self.bpm_source = self.detected_bpm_source
        self.wake.set()
        self.broadcast()

    # ------------------------------------------------------------------
    # What the lamps should show right now
    # ------------------------------------------------------------------
    def compute_target(self, phase, pal=None):
        """Returns (left_segs, right_segs): 7 colours per lamp, index 0 = base, 6 = top."""
        use_lock = pal is None
        if use_lock and self.is_ad:
            return [AD_WHITE] * 7, [AD_WHITE] * 7
        pal = pal or self.current_lamp_palette or [(29, 185, 84)]
        idx = self.locked_swatch_index if use_lock else None
        if idx is not None and 0 <= idx < len(pal):
            c = pal[idx]
            return [c] * 7, [c] * 7

        flowing = (self.motion_mode == "flow")

        if self.spatial_mode == "segmented":
            if flowing:
                # Neighbouring zones are close in colour (half the loop per lamp)
                zones = [sample_palette_continuous(pal, phase + ZONE_SPAN * i / 6.0) for i in range(7)]
            else:
                zones = build_7_zone_palette(pal)
            if self.is_inverted_tb:
                zones = list(reversed(zones))   # flip the lamp top-to-bottom
            return list(zones), list(zones)

        if self.spatial_mode == "duo":
            if flowing:
                c_left = sample_palette_continuous(pal, phase)
                c_right = sample_palette_continuous(pal, phase + DUO_OFFSET)
            else:
                c_left, c_right = get_dual_split_colors(pal)
            return [c_left] * 7, [c_right] * 7

        # unified
        if flowing:
            c_left = sample_palette_continuous(pal, phase)
            c_right = sample_palette_continuous(pal, phase + WAVE_OFFSET)
        else:
            c_left, _ = get_dual_split_colors(pal)
            c_right = c_left
        return [c_left] * 7, [c_right] * 7

    def _limit_slew(self, frame, now):
        """Moving modes: keeps every zone's colour from changing faster than SLEW_PER_SEC."""
        prev, t_prev = self._slew_prev, self._slew_t
        self._slew_t = now
        if prev is None or now - t_prev > 0.5:
            self._slew_prev = frame
            return frame
        step = SLEW_PER_SEC * (now - t_prev)

        def lim(new, old):
            return tuple(int(round(o + max(-step, min(step, n - o)))) for n, o in zip(new, old))

        out = ([lim(n, o) for n, o in zip(frame[0], prev[0])],
               [lim(n, o) for n, o in zip(frame[1], prev[1])])
        self._slew_prev = out
        return out

    def engine_loop(self):
        """The ONLY place that sends colours to the lamps. Handles flowing
        modes, fades between songs/modes, beat pulse and holding still."""
        phase = 0.0
        dt = 1.0 / LAMP_FPS
        last_tick = time.time()

        while self.is_running:
            try:
                now = time.time()
                if not self.is_powered_on or self.engine_paused:
                    self.wake.wait(0.3)
                    self.wake.clear()
                    last_tick = time.time()
                    continue

                animating = (self.motion_mode == "flow" and self.locked_swatch_index is None and not self.is_ad)
                fade_src = self.fade_from
                fading = fade_src is not None and (now - self.fade_start) < self.fade_dur
                pulsing = self.music_pulse_enabled and self.is_playing

                if animating:
                    phase = (phase + (now - last_tick) / max(2.5, self.flow_speed)) % 1.0
                self.phase, self.phase_time = phase, now
                last_tick = now

                send_phase = (phase + LAMP_LEAD / max(2.5, self.flow_speed)) % 1.0 if animating else phase
                target = lift_frame(self.compute_target(send_phase), self.dark_boost)
                if fading:
                    if fade_src == "palette" and self.fade_prev_pal:
                        fade_src = lift_frame(self.compute_target(send_phase, pal=self.fade_prev_pal), self.dark_boost)
                    elif fade_src == "palette":
                        fade_src = target
                    frame = blend_frames(fade_src, target, (now - self.fade_start) / self.fade_dur)
                else:
                    self.fade_from = None
                    frame = target

                if self.attention:
                    # "Claude needs you": top half of the right lamp held red
                    right = list(frame[1])
                    for i in ATTENTION_ZONES:
                        right[i] = ATTENTION_RGB
                    frame = (frame[0], right)

                # Dynamic energy changes are glided at full frame rate too, so
                # Solid mode doesn't step its brightness once a second
                if animating:
                    frame = self._limit_slew(frame, now)
                else:
                    self._slew_prev = None          # still modes jump straight to their colour

                if animating or fading or pulsing or self._energy_moving():
                    self.govee.send_frame(frame[0], frame[1], persistent=False)
                    self.out_frame = frame
                    self.hold_pending = True   # send a final "hold" frame when motion stops
                    self.last_motion = now
                    self._maybe_broadcast(now)
                    time.sleep(dt)
                else:
                    # The hold command waits until things have been still for 2 s:
                    # Dynamic energy nudges every couple of seconds, and a
                    # colorwc each time made the lamps visibly re-apply the colour
                    settled = now - self.last_motion >= 2.0
                    if self.needs_send or (self.hold_pending and settled):
                        self.hold_pending = False
                        # colorwc for solid lamps never times out back to white
                        self.govee.send_frame(frame[0], frame[1], persistent=True)
                        self.out_frame = frame
                        self.needs_send = False
                        self.broadcast()
                    self.wake.wait(0.25 if self.hold_pending else 1.0)
                    self.wake.clear()
            except Exception as e:
                print(f"[!] Lighting engine error: {e}")
                time.sleep(0.5)

    # ------------------------------------------------------------------
    # State for the dashboard
    # ------------------------------------------------------------------
    FLOW_STEPS = 96

    def _flow_stops(self):
        """The colour loop sampled finely, exactly as it reaches the lamps (same blending and the same
        lamp colour finishing), so a dashboard that slides along it shows what the lamps show. Cached:
        it only changes with the palette or the dark-colour boost."""
        key = (tuple(tuple(c) for c in self.current_lamp_palette), round(self.dark_boost, 3))
        cached = getattr(self, "_flow_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        n = self.FLOW_STEPS
        stops = [[round(i / n, 4), _hex(led_finish(sample_palette_continuous(self.current_lamp_palette, i / n), self.dark_boost))]
                 for i in range(n)]
        stops.append([1.0, stops[0][1]])
        self._flow_cache = (key, stops)
        return stops

    def _flow_info(self):
        """What the moving modes are doing, so the dashboard can animate the
        lamp preview itself (smooth, and nearly free) instead of being sent
        every frame. None when the lamps are still."""
        if self.motion_mode != "flow" or self.locked_swatch_index is not None or not self.is_powered_on or self.is_ad:
            return None
        cycle = max(2.5, self.flow_speed)
        now = time.time()
        phase = (self.phase + (now - self.phase_time) / cycle) % 1.0
        stops = self._flow_stops()
        if self.spatial_mode == "segmented":
            span, right = ZONE_SPAN, 0.0
        elif self.spatial_mode == "duo":
            span, right = 0.0, DUO_OFFSET
        else:
            span, right = 0.0, WAVE_OFFSET
        return {"stops": stops, "cycle": cycle, "phase": round(phase, 4), "span": span,
                "right_offset": right, "inverted": self.spatial_mode == "segmented" and self.is_inverted_tb,
                "fade": self.trans_speed}

    def _art_url_for_dashboard(self):
        """Spotify covers are web links. Covers from other players only exist as image data,
        so the dashboard gets them from /api/art - but only once the image has loaded."""
        url = self.current_art_url
        if not url.startswith("nowplaying:"):
            return url
        if self.current_art_bytes and self.palette_art_url == url:
            return f"/api/art?v={zlib.crc32(url.encode('utf-8')):08x}"
        return ""

    def to_dict(self):
        frame = self.out_frame or lift_frame(self.compute_target(0.0), self.dark_boost)
        left, right = frame
        if self.spatial_mode == "segmented" and self.locked_swatch_index is None:
            hex1, hex2 = _hex(left[-1]), _hex(left[0])     # top, base
        else:
            hex1, hex2 = _hex(left[0]), _hex(right[0])     # left lamp, right lamp

        g = self.govee
        sides = [ip for ip in (g.left_ip, g.right_ip) if ip]
        return {
            "track": self.current_track,
            "artist": self.current_artist,
            "art_url": self._art_url_for_dashboard(),
            "hex1": hex1,
            "hex2": hex2,
            "seg_colors": [_hex(c) for c in left],
            "seg_colors_right": [_hex(c) for c in right],
            "palette_raw": [_hex(c).lower() for c in self.current_raw_palette],
            "palette_lamp": [_hex(c).lower() for c in self.current_lamp_palette],
            "spatial_mode": self.spatial_mode,
            "motion_mode": self.motion_mode,
            "flow_speed": self.flow_speed,
            "trans_speed": self.trans_speed,
            "vibrancy": self.vibrancy,
            "music_pulse": self.music_pulse_enabled,
            "current_bpm": self.current_bpm,
            "detected_bpm": self.detected_bpm,
            "bpm_source": self.bpm_source,
            "bpm_manual": self.bpm_manual,
            "bpm_known": self.bpm_known,
            "pulse_depth": self.pulse_depth,
            "brightness": self.brightness,
            "is_powered_on": self.is_powered_on,
            "lamp_ips": g.ips,
            "available_ips": g.all_ips,
            "left_ip": g.left_ip,
            "right_ip": g.right_ip,
            "lamp_online": {ip: g.is_online(ip) for ip in g.all_ips},
            "identifying_ip": self.identifying_ip,
            "online_count": sum(1 for ip in sides if g.is_online(ip)),
            "configured_count": len(sides),
            # Not "known" until the first check has had time to get answers,
            # so the app doesn't flash "Lamps Not Responding" right after starting
            "status_known": g.listener_ok and g.first_check_done_at is not None and time.time() >= g.first_check_done_at,
            "status_error": g.listener_error,
            "is_swapped_lr": self.is_swapped_lr,
            "is_inverted_tb": self.is_inverted_tb,
            "dynamic_intensity": self.dynamic_intensity_enabled,
            "dark_boost": self.dark_boost,
            "preview_mode": self.preview_mode,
            "fs_motion": self.fs_motion,
            "white_accent": self.white_accent,
            "volume": self.sp_volume,
            "shuffle": self.sp_shuffle,
            "repeat": self.sp_repeat,
            "spotify_instant": (time.time() - self.last_nudge) < 15 * 60,
            "web_version": _web_version(),
            "flow": self._flow_info(),
            "intensity_factor": round(self.current_intensity, 2),
            "intensity_section": self.current_section,
            "player_pos": round(self.song_time(), 2),
            "track_dur": round(self.current_dur, 1),
            "is_playing": self.is_playing,
            "locked_swatch_index": self.locked_swatch_index,
            "is_ad": self.is_ad,
            "devices": [d.to_dict() for d in self.govee.devices],
            "discovered_devices": self.discovered,
            "scanning_devices": self.scanning,
            "player": players.active_source(),
            "source_name": players.source_name(),
            "album": players.album(),
            "default_theme": DEFAULT_THEME,
            "can_shuffle_repeat": players.can_shuffle_repeat(),
        }

    # ------------------------------------------------------------------
    # Spotify polling
    # ------------------------------------------------------------------
    def poll_spotify_step(self):
        # Only one poll at a time (the 1.8s loop and next/prev can overlap)
        with self.poll_lock:
            self._poll_spotify_locked()

    def _poll_spotify_locked(self):
        is_playing, track, artist, art_url, pos, dur, track_id = players.get_track_info()
        sample_t = players.last_sample_time()
        if not sample_t or abs(time.time() - sample_t) > 3.0:
            sample_t = time.time()       # (a stand-in player that didn't say when it read the position)
        self._read_playback_extras()
        # Same song still playing: nudge the running clock towards the reading instead of
        # replacing it. Reading jitter would otherwise shift the beat pulse at every check.
        if is_playing and self.is_playing and (track, artist) == self.last_track_sig:
            predicted = self.current_pos + (sample_t - self.pos_sample_time)
            err = pos - predicted
            if abs(err) < 0.3:
                pos = predicted + 0.35 * err
        self.is_playing = is_playing
        self.current_pos = pos
        self.pos_sample_time = sample_t
        self.current_dur = dur

        if not self.dynamic_intensity_enabled:
            self.intensity_target = 1.0
            self.current_intensity = 1.0
            self.current_section = "Normal"

        t_str = (track or "").strip()
        a_str = (artist or "").strip()
        t_low = t_str.lower()
        a_low = a_str.lower()
        tid = (track_id or "").lower()
        has_art = bool(art_url and art_url != "missing value")

        # Spotify gives ads an id like "spotify:ad:..." - that's the reliable signal.
        # Local files ("spotify:local:...") have no art but are NOT ads.
        is_ad_track = (
            tid.startswith("spotify:ad:")
            or "advertisement" in t_low
            or "advertisement" in a_low
            or t_low in AD_TITLES                 # e.g. YouTube / other players label ads "Ad" or "Sponsored"
            or a_low in AD_TITLES
            or (t_low == "spotify" and not a_str)
        )

        if is_ad_track:
            sig = ("AD_BREAK", t_str)
            if sig != self.last_track_sig:
                self.last_track_sig = sig
                self.is_ad = True
                self.current_track = t_str if (t_str and t_low != "spotify") else "Advertisement"
                self.current_artist = "Sponsored Commercial"
                self.current_art_url = ""
                self.locked_swatch_index = None
                # Ad: fade both lamps to plain white. The song's colours are kept
                # and come back when the music does.
                self.request_update(self.trans_speed)
                self.broadcast()
            else:
                self.broadcast()
            return

        if not track:
            self.broadcast()
            return

        if self.is_ad:
            # Ad finished: fade from white back to the song's colours
            self.is_ad = False
            self.request_update(self.trans_speed)
        meta_sig = (track, artist)
        new_song = (meta_sig != self.last_track_sig)
        if new_song:
            self.last_track_sig = meta_sig
            self.current_track = track
            self.current_artist = artist
            self.locked_swatch_index = None
            self.art_wait_polls = 0
            # New song: tempo goes back to automatic and the beat grid restarts
            self.bpm_manual = False
            self.bpm_known = False          # the last song's tempo means nothing for this one
            self.detected_bpm_known = False
            self.beat_offset = 0.0

            def _fetch_bpm(t=track, a=artist, s=meta_sig):
                bpm, source = fetch_track_bpm(t, a)
                if self.last_track_sig != s:
                    return   # song changed while we were looking it up
                self.detected_bpm = bpm
                self.detected_bpm_source = source
                self.detected_bpm_known = source not in UNKNOWN_SOURCES
                if not self.bpm_manual:
                    self.current_bpm = bpm
                    self.bpm_source = source
                    self.bpm_known = self.detected_bpm_known
                self.broadcast()

            threading.Thread(target=_fetch_bpm, daemon=True).start()

        # Colours follow the album ART, not the song name. Spotify often updates
        # the art link a moment after the song changes - reacting to the song
        # name made the lamps fade twice (or flash the no-cover colours first).
        if has_art and self.current_art_url != art_url:
            # Always show the cover, even when the colours don't need to change
            # (e.g. the same album continuing after an ad).
            self.current_art_url = art_url
            self.broadcast()
        if has_art and art_url != self.palette_art_url:
            raw_pal = lamp_pal = None
            try:
                data = players.fetch_art(art_url)
                raw_pal, lamp_pal = extract_spotify_palette(data, max_colors=5, vibrancy_mult=self.vibrancy,
                                                            white_accent=self.white_accent)
                self.current_art_bytes = data
                self.palette_art_url = art_url   # only remember it on success, so a failed download is retried
            except Exception as e:
                print(f"[!] Error processing art: {e}")
            self.current_art_url = art_url
            if raw_pal and lamp_pal:
                self.set_new_track_palette(raw_pal, lamp_pal)
                return
            self._use_no_cover_colours()
            return

        if not has_art and self.palette_art_url != ("NO_ART", meta_sig):
            # Local files never get art; for streamed songs give Spotify ~3s first
            self.art_wait_polls += 1
            if tid.startswith("spotify:local:") or self.art_wait_polls >= 2:
                self.palette_art_url = ("NO_ART", meta_sig)
                self.current_art_url = ""
                self.current_art_bytes = None
                self._use_no_cover_colours()
                return

        self.broadcast()

    def _use_no_cover_colours(self):
        """Song without a cover (e.g. a local file): keep the current colours."""
        self.broadcast()

    def spotify_nudge(self):
        """Spotify just announced a change (song, play/pause). Read it right away."""
        self.last_nudge = time.time()
        self.spotify_wake.set()

    def spotify_sync_loop(self):
        """Reads Spotify's state. Changes arrive instantly through spotify_nudge()
        (from the menu-bar app); the timed poll is only a safety net and keeps
        the song position fresh. It polls less often while nudges are arriving."""
        while self.is_running:
            nudged = self.spotify_wake.wait(timeout=self._poll_interval())
            self.spotify_wake.clear()
            try:
                self.poll_spotify_step()
                if nudged:
                    # Spotify sometimes updates the album art a moment later
                    time.sleep(0.7)
                    self.poll_spotify_step()
            except Exception as e:
                print(f"[!] Spotify poll error: {e}")

    def _poll_interval(self):
        # Spotify and Apple Music announce changes; other players are polled
        if players.active_source() not in ("spotify", "music"):
            return 1.8
        nudges_working = (time.time() - self.last_nudge) < 15 * 60
        return 4.0 if nudges_working else 1.8
