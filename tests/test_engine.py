"""
Lighting engine tests. Lamp packets are captured instead of sent, so these run
anywhere (no lamps or Spotify needed):

    cd ~/GoveeSpotifySync && /usr/bin/python3 -m unittest discover tests
"""
import base64
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
os.environ["GOVEE_CONFIG_FILE"] = os.path.join(tempfile.mkdtemp(), "config.json")

import colors  # noqa: E402
import engine  # noqa: E402
import players  # noqa: E402
import spotify  # noqa: E402
import tempo  # noqa: E402


def packet_colours(msg):
    """All RGB colours inside one captured lamp packet."""
    cmd = msg["msg"]["cmd"]
    if cmd == "colorwc":
        c = msg["msg"]["data"]["color"]
        return [(c["r"], c["g"], c["b"])]
    if cmd == "ptReal":
        return [tuple(base64.b64decode(x)[4:7]) for x in msg["msg"]["data"]["command"]]
    return []


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = engine.AppState()
        cls.S.save_config = lambda: None
        # Two pretend lamps (documentation-range addresses; nothing is really sent)
        g = cls.S.govee
        g.all_ips = ["192.0.2.1", "192.0.2.2"]
        g.left_ip, g.right_ip = g.all_ips
        g.sync_ordered_ips()
        cls.log = []
        cls.S.govee.send_cmd = lambda msg, ips=None: cls.log.append((time.time(), tuple(ips or cls.S.govee.ips), msg))
        cls.S.is_playing = True
        threading.Thread(target=cls.S.engine_loop, daemon=True).start()

    def setUp(self):
        S = self.S
        S.dark_boost = 0.0
        S.music_pulse_enabled = False
        S.dynamic_intensity_enabled = False
        S.locked_swatch_index = None
        S.is_inverted_tb = False
        S.is_powered_on = S.govee.is_powered_on = True
        S.current_lamp_palette = [(200, 30, 30), (30, 30, 200), (30, 200, 30)]

    def capture(self, sec):
        self.log.clear()
        time.sleep(sec)
        return list(self.log)

    def test_still_mode_sends_once_then_holds(self):
        S = self.S
        S.spatial_mode, S.motion_mode = "unified", "static"
        S.apply_lighting(0)
        sent = self.capture(1.5)
        self.assertTrue(1 <= len(sent) <= 3, len(sent))
        self.assertTrue(all(m["msg"]["cmd"] == "colorwc" for _, _, m in sent))

    def test_locked_swatch_holds_in_moving_mode(self):
        S = self.S
        S.spatial_mode, S.motion_mode = "segmented", "flow"
        S.locked_swatch_index = 1
        self.log.clear()
        S.request_update(0)
        time.sleep(1.2)
        colours = {c for _, _, m in self.log for c in packet_colours(m)}
        # Sent once as a held colour, then nothing else overwrites it
        self.assertEqual(colours, {(30, 30, 200)})

    def test_moving_mode_steady_frame_rate(self):
        S = self.S
        S.spatial_mode, S.motion_mode = "duo", "flow"
        S.request_update(0)
        per_ip = {}
        for t, ips, _ in self.capture(2.0):
            per_ip.setdefault(ips, []).append(t)
        self.assertEqual(len(per_ip), 2)
        for times in per_ip.values():
            rate = len(times) / 2.0
            self.assertTrue(engine.LAMP_FPS * 0.7 <= rate <= engine.LAMP_FPS * 1.1, rate)

    def test_song_change_fade_has_no_jumps_and_keeps_moving(self):
        S = self.S
        S.spatial_mode, S.motion_mode = "segmented", "flow"
        S.trans_speed = 2.0
        S.request_update(0)
        time.sleep(0.3)
        seen = []
        S.set_new_track_palette([(0, 0, 255), (255, 255, 0)], [(0, 0, 255), (255, 255, 0)])
        for _ in range(15):
            seen.append(tuple(S.out_frame[0][3]))
            time.sleep(0.12)
        steps = [max(abs(a[i] - b[i]) for i in range(3)) for a, b in zip(seen, seen[1:])]
        self.assertLess(max(steps), 90)
        self.assertGreater(len(set(seen)), 10)   # still moving during the fade

    def test_power_off_sends_nothing(self):
        S = self.S
        S.is_powered_on = S.govee.is_powered_on = False
        S.motion_mode = "flow"
        S.wake.set()
        self.assertEqual(len(self.capture(0.8)), 0)

    def test_invert_flips_7_zone_only(self):
        S = self.S
        S.spatial_mode, S.motion_mode = "duo", "static"
        a = S.compute_target(0)
        S.is_inverted_tb = True
        self.assertEqual(a, S.compute_target(0))
        S.spatial_mode = "segmented"
        flipped = S.compute_target(0)
        S.is_inverted_tb = False
        self.assertEqual(flipped[0], list(reversed(S.compute_target(0)[0])))

    def test_beat_pulse_follows_song_position(self):
        S = self.S
        S.music_pulse_enabled = True
        S.bpm_known = True
        S.current_bpm, S.pulse_depth, S.beat_offset = 120, 0.6, 0.0
        lead = engine.PULSE_LEAD                  # the pulse starts a little early to land on the beat
        S.current_pos, S.pos_sample_time = 10.0 - lead, time.time()
        on_beat = S.get_beat_envelope()
        S.current_pos, S.pos_sample_time = 10.25 - lead, time.time()
        between = S.get_beat_envelope()
        self.assertGreater(on_beat, 0.95)
        self.assertLess(between, 0.75)
        S.is_playing = False
        self.assertEqual(S.get_beat_envelope(), 1.0)
        S.is_playing = True


class ColourTest(unittest.TestCase):
    def test_dark_boost(self):
        self.assertEqual(colors.led_lift((107, 46, 0), 0.65), (166, 71, 0))
        self.assertEqual(colors.led_lift((255, 120, 20), 0.65), (255, 120, 20))
        self.assertEqual(colors.led_lift((0, 0, 0), 0.65), (0, 0, 0))

    def test_colour_flow_is_steady(self):
        # Related colours flow at a constant, even speed
        pal = [(220, 30, 30), (240, 140, 20), (230, 40, 140)]
        prev, steps = None, []
        for k in range(300):
            c = colors.sample_palette_continuous(pal, k / 300)
            if prev:
                steps.append(max(abs(c[i] - prev[i]) for i in range(3)))
            prev = c
        self.assertLessEqual(max(steps), 3)

    def test_clashing_crossover_has_no_jumps_at_real_frame_rate(self):
        # Red/green holds then crosses quickly; at 11 fps with a 5 s cycle
        # each frame must still be a small step, not a snap.
        pal = [(220, 30, 30), (30, 200, 60)]
        frames = int(5.0 * 11)
        prev, worst = None, 0
        for k in range(frames + 1):
            c = colors.sample_palette_continuous(pal, k / frames)
            if prev:
                worst = max(worst, max(abs(c[i] - prev[i]) for i in range(3)))
            prev = c
        self.assertLess(worst, 70)


class PreviewMatchesLampsTest(unittest.TestCase):
    """The dashboard animates flow_gradient() itself; it must follow exactly the
    same colours the lamps get from sample_palette_continuous()."""

    def _gradient_at(self, stops, x):
        for (p1, c1), (p2, c2) in zip(stops, stops[1:]):
            if p1 <= x <= p2:
                t = 0 if p2 == p1 else (x - p1) / (p2 - p1)
                return tuple(c1[i] + (c2[i] - c1[i]) * t for i in range(3))
        return stops[-1][1]

    def test_gradient_follows_lamp_colours(self):
        for pal in ([(126, 0, 184), (240, 205, 60), (58, 123, 213)],     # clashing (bridged)
                    [(220, 30, 30), (30, 200, 60)],                      # clashing (held)
                    [(220, 30, 30), (240, 140, 20), (230, 40, 140)]):    # related
            stops = colors.flow_gradient(pal)
            worst = 0
            for k in range(200):
                x = k / 200
                lamp = colors.sample_palette_continuous(pal, x)
                prev = self._gradient_at(stops, x)
                worst = max(worst, max(abs(lamp[i] - prev[i]) for i in range(3)))
            self.assertLess(worst, 40, (pal, worst))   # preview within a small shade of the lamp


class ColourAccuracyTest(unittest.TestCase):
    """The lamps should only show colours that are really on the album cover."""

    def test_clashing_pairs_detected(self):
        self.assertTrue(colors.colours_clash((240, 205, 60), (58, 123, 213)))    # yellow/blue -> green
        self.assertTrue(colors.colours_clash((220, 30, 30), (30, 200, 60)))      # red/green -> olive
        self.assertFalse(colors.colours_clash((220, 30, 30), (240, 140, 20)))    # red/orange
        self.assertFalse(colors.colours_clash((40, 60, 220), (140, 40, 200)))    # blue/purple

    def test_yellow_blue_album_never_shows_green(self):
        import colorsys
        pal = [(126, 0, 184), (240, 205, 60), (58, 123, 213)]
        self.assertEqual(colors.flow_stops(pal), [pal[0], pal[1], pal[0], pal[2]])
        for k in range(400):
            c = colors.sample_palette_continuous(pal, k / 400)
            h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
            self.assertFalse(80 <= h * 360 <= 160 and s > 0.12, c)

    def test_shadow_red_is_not_made_vivid(self):
        self.assertNotEqual(colors.calibrate_govee_gamut(45, 20, 24)[1:], (0, 0))   # near-black stays dark
        self.assertEqual(colors.calibrate_govee_gamut(200, 20, 30)[2], 0)            # real red still vivid


def _cover(regions):
    """Builds a small test cover: list of (fraction_of_height, rgb) bands."""
    import io
    from PIL import Image
    img = Image.new("RGB", (100, 100))
    y = 0
    for frac, rgb in regions:
        h = int(round(frac * 100))
        for yy in range(y, min(100, y + h)):
            for x in range(100):
                img.putpixel((x, yy), rgb)
        y += h
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class WhiteAreaTest(unittest.TestCase):
    def test_big_white_area_is_used(self):
        raw, _ = colors.extract_spotify_palette(_cover([(0.5, (100, 66, 41)), (0.5, (205, 205, 208))]))
        self.assertTrue(any(min(c) >= 180 for c in raw), raw)          # white is in
        self.assertEqual(raw[0][0] > raw[0][2], True)                   # brown stays the main colour

    def test_small_white_detail_is_an_accent_only(self):
        cover = _cover([(0.9, (30, 80, 200)), (0.1, (240, 240, 240))])
        off, _ = colors.extract_spotify_palette(cover, white_accent=False)
        self.assertFalse(any(min(c) >= 180 for c in off), off)        # not a main colour
        on, _ = colors.extract_spotify_palette(cover, white_accent=True)
        self.assertTrue(min(on[-1]) >= 180 and min(on[0]) < 180, on)   # added last, blue still leads


class ColourPickingTest(unittest.TestCase):
    def test_tiny_detail_is_not_a_lamp_colour(self):
        # Mostly black + navy with a 2% red detail: red must not be picked
        raw, lamp = colors.extract_spotify_palette(
            _cover([(0.70, (8, 8, 12)), (0.28, (20, 47, 78)), (0.02, (200, 30, 30))]))
        self.assertFalse(any(c[0] > c[2] + 60 for c in lamp), lamp)

    def test_near_duplicates_are_merged(self):
        raw, _ = colors.extract_spotify_palette(
            _cover([(0.5, (120, 70, 35)), (0.5, (128, 74, 40))]))
        self.assertEqual(len(raw), 1, raw)


class LampRedAndWhiteTest(unittest.TestCase):
    def test_raspberry_mixes_read_red_on_lamps(self):
        self.assertEqual(colors.led_finish((255, 0, 0), 0.0), (255, 0, 0))
        r, g, b = colors.led_finish((184, 0, 87), 1.0)     # red/purple midpoint
        self.assertLess(b / r, 0.35)                        # was 121/255 = hot pink
        self.assertEqual(colors.led_finish((200, 0, 200), 0.0), (200, 0, 200))   # true magenta untouched
        self.assertEqual(colors.led_finish((121, 0, 175), 0.0), (121, 0, 175))   # purple untouched
        self.assertGreater(colors.led_finish((212, 0, 132), 0.0)[2], 132 * 0.75)  # pinkish magenta mostly kept

    def test_no_snapping_through_pure_red(self):
        prev = None
        for k in range(21):                        # pastel pink -> pure red -> pastel orange
            out = colors.led_red_correct((255, 90, 140 - 5 * k))
            if prev:
                self.assertLessEqual(max(abs(out[i] - prev[i]) for i in range(3)), 8)
            prev = out

    def test_white_next_to_red_crosses_over_quickly(self):
        self.assertTrue(colors.colours_clash((240, 240, 238), (220, 30, 30)))
        self.assertFalse(colors.colours_clash((240, 240, 238), (40, 80, 200)))  # white/blue is fine

    def test_small_white_highlight_becomes_accent(self):
        raw, _ = colors.extract_spotify_palette(_cover([(0.6, (30, 50, 90)), (0.37, (110, 50, 45)), (0.03, (240, 240, 240))]))
        self.assertTrue(any(min(c) >= 200 for c in raw), raw)
        raw2, _ = colors.extract_spotify_palette(_cover([(0.6, (30, 50, 90)), (0.37, (110, 50, 45)), (0.03, (240, 240, 240))]),
                                                 white_accent=False)
        self.assertFalse(any(min(c) >= 200 for c in raw2), raw2)


class CoverAfterAdTest(unittest.TestCase):
    """In "Match Song" ad mode, the cover must come back after an ad even when
    the next song has the same cover (same album continuing)."""

    def test_cover_returns_after_ad(self):
        S = engine.AppState()
        S.save_config = lambda: None
        S.ad_color_mode = "match_last"
        engine.fetch_track_bpm = lambda t, a: (120.0, "x")
        art = "https://art/same-album"
        feed = iter([
            (True, "Song A", "Artist", art, 1.0, 200.0, "spotify:track:a"),
            (True, "Advertisement", "", "", 1.0, 30.0, "spotify:ad:1"),
            (True, "Song B", "Artist", art, 0.5, 200.0, "spotify:track:b"),
        ])
        saved = (players.get_track_info, players.fetch_art)
        self.addCleanup(lambda: (setattr(players, "get_track_info", saved[0]),
                                 setattr(players, "fetch_art", saved[1])))
        players.get_track_info = lambda: next(feed)
        players.fetch_art = lambda url: b"x"
        engine.extract_spotify_palette = lambda data, **k: ([(200, 0, 0)], [(200, 0, 0)])
        S.poll_spotify_step()
        self.assertEqual(S.current_art_url, art)
        S.poll_spotify_step()
        self.assertEqual(S.current_art_url, "")      # ad: no cover
        S.poll_spotify_step()
        self.assertEqual(S.current_art_url, art)     # back after the ad


class AdWhiteTest(unittest.TestCase):
    def test_ads_turn_lamps_white_then_back(self):
        S = engine.AppState()
        S.save_config = lambda: None
        S.current_lamp_palette = [(200, 30, 30), (30, 30, 200)]
        S.spatial_mode, S.motion_mode = "segmented", "flow"
        S.is_ad = True
        left, right = S.compute_target(0.3)
        self.assertEqual(set(left + right), {engine.AD_WHITE})
        self.assertIsNone(S._flow_info())             # no moving preview during the ad
        S.is_ad = False
        left, _ = S.compute_target(0.3)
        self.assertNotIn(engine.AD_WHITE, left)       # song colours come back


class PlayersTest(unittest.TestCase):
    """Which player is shown: Spotify when it plays, otherwise macOS Now Playing."""
    SP_PLAYING = (True, "Sp Song", "Sp Artist", "https://x/y.jpg", 5.0, 200.0, "spotify:track:1")
    SP_PAUSED = (False, "Sp Song", "Sp Artist", "https://x/y.jpg", 5.0, 200.0, "spotify:track:1")
    SP_NONE = (False, None, None, None, 0.0, 0.0, "")
    OTHER = {"title": "Web Song", "artist": "Web Artist", "album": "Alb", "duration": 180.0,
             "pos": 12.0, "playing": True, "id": "x", "art_id": "a1", "has_art": True}

    def setUp(self):
        self._orig = (spotify.get_spotify_track_info, players._system_info)

    def tearDown(self):
        spotify.get_spotify_track_info, players._system_info = self._orig

    def use(self, sp, other):
        spotify.get_spotify_track_info = lambda: sp
        players._system_info = lambda with_art=False: other

    def test_spotify_playing_wins(self):
        self.use(self.SP_PLAYING, self.OTHER)
        self.assertEqual(players.get_track_info(), self.SP_PLAYING)
        self.assertEqual(players.active_source(), "spotify")

    def test_other_app_used_when_spotify_idle(self):
        self.use(self.SP_PAUSED, self.OTHER)
        playing, track, artist, art, pos, dur, _ = players.get_track_info()
        self.assertEqual((playing, track, artist, dur), (True, "Web Song", "Web Artist", 180.0))
        self.assertTrue(art.startswith("nowplaying:"))
        self.assertEqual(players.active_source(), "system")
        self.assertEqual(players.current_album(), "Alb")

    def test_apple_music_gets_full_controls(self):
        calls = []
        orig = players._osa
        players._osa = lambda script, timeout=2: (calls.append(script) or "70|true|all") if "sound volume as string" in script else calls.append(script) or ""
        try:
            self.use(self.SP_NONE, dict(self.OTHER, bundle="com.apple.Music"))
            self.assertTrue(players.get_track_info()[0])
            self.assertEqual(players.active_source(), "music")
            self.assertTrue(players.can_shuffle_repeat())
            self.assertEqual((spotify.EXTRAS["volume"], spotify.EXTRAS["shuffle"], spotify.EXTRAS["repeat"]), (70, True, True))
            calls.clear()
            players.set_shuffle(True); players.set_repeat(False); players.set_volume(30); players.seek(12)
            players.play_pause(); players.next_track(); players.prev_track()
            joined = "\n".join(calls)
            for expect in ("shuffle enabled to true", "song repeat to off", "sound volume to 30",
                           "player position to 12.0", "playpause", "next track", "previous track"):
                self.assertIn(expect, joined)
            self.assertTrue(all('tell application "Music"' in c for c in calls))
        finally:
            players._osa = orig

    def test_browser_player_has_no_shuffle_repeat(self):
        orig = players._osa
        players._osa = lambda script, timeout=2: "55"
        players._sysvol_read_at = 0.0
        try:
            self.use(self.SP_NONE, dict(self.OTHER, bundle="com.google.Chrome"))
            players.get_track_info()
            self.assertEqual(players.active_source(), "system")
            self.assertFalse(players.can_shuffle_repeat())
            self.assertEqual(spotify.EXTRAS["volume"], 55)         # Mac's output volume
        finally:
            players._osa = orig

    def test_system_player_commands_use_now_playing(self):
        sent = []
        orig = players._run
        players._run = lambda func, **env: sent.append((func, env))
        players._active = "system"
        try:
            players.play_pause(); players.next_track(); players.prev_track(); players.seek(30)
        finally:
            players._run = orig
        self.assertEqual([e["MR_CMD"] for _, e in sent], [2, 4, 5, 24])
        self.assertEqual(sent[-1][1]["MR_POS"], 30.0)

    def test_paused_spotify_beats_paused_other(self):
        self.use(self.SP_PAUSED, dict(self.OTHER, playing=False))
        self.assertEqual(players.get_track_info(), self.SP_PAUSED)

    def test_nothing_on_spotify_shows_paused_other(self):
        self.use(self.SP_NONE, dict(self.OTHER, playing=False, has_art=False))
        playing, track, _, art, *_ = players.get_track_info()
        self.assertEqual((playing, track, art), (False, "Web Song", None))

    def test_nothing_playing_anywhere(self):
        self.use(self.SP_NONE, {})
        self.assertEqual(players.get_track_info(), self.SP_NONE)


class AdDetectionTest(unittest.TestCase):
    def poll(self, track, artist, tid=""):
        S = engine.AppState()
        S.save_config = lambda: None
        saved = players.get_track_info
        players.get_track_info = lambda: (True, track, artist, None, 1.0, 30.0, tid)
        try:
            S.poll_spotify_step()
        finally:
            players.get_track_info = saved
        return S.is_ad

    def test_ads_from_any_player(self):
        self.assertTrue(self.poll("Advertisement", ""))                # YouTube-style
        self.assertTrue(self.poll("Ad", "Some Brand"))
        self.assertTrue(self.poll("Sponsored", ""))
        self.assertTrue(self.poll("Whatever", "Spotify", "spotify:ad:123"))

    def test_songs_are_not_ads(self):
        self.assertFalse(self.poll("Adore", "Smashing Pumpkins"))
        self.assertFalse(self.poll("Ad Astra", "Someone"))
        self.assertFalse(self.poll("Song", "Artist"))


class PulseAndEnergyTest(unittest.TestCase):
    def state(self):
        S = engine.AppState()
        S.save_config = lambda: None
        S.is_playing = True
        S.current_dur = 200.0
        return S

    def test_no_pulse_until_a_real_tempo_is_known(self):
        S = self.state()
        S.music_pulse_enabled, S.current_bpm, S.pulse_depth = True, 120, 0.9
        S.current_pos, S.pos_sample_time = 10.13, time.time()          # mid-beat: would be dim if pulsing
        S.bpm_known = False
        self.assertEqual(S.get_beat_envelope(), 1.0)                   # steady light
        S.bpm_known = True
        self.assertLess(S.get_beat_envelope(), 0.9)

    def test_manual_tempo_counts_as_known_and_new_song_resets(self):
        S = self.state()
        S.set_manual_bpm(128, tap=True)
        self.assertTrue(S.bpm_known)
        saved = players.get_track_info
        players.get_track_info = lambda: (True, "New Song", "Artist", None, 1.0, 200.0, "id")
        orig_fetch, engine.fetch_track_bpm = engine.fetch_track_bpm, lambda t, a: (120.0, "Not found (default)")
        try:
            S.poll_spotify_step()
            time.sleep(0.2)
        finally:
            players.get_track_info, engine.fetch_track_bpm = saved, orig_fetch
        self.assertFalse(S.bpm_known)                                   # lookup found nothing: no fake 120

    def test_slow_position_reading_is_compensated(self):
        S = self.state()
        saved = (players.get_track_info, players.last_sample_time)
        read_at = time.time() - 0.3                                     # the reading took 0.3 s to come back
        players.get_track_info = lambda: (True, "Song", "Artist", None, 50.0, 200.0, "id")
        players.last_sample_time = lambda: read_at
        try:
            S.poll_spotify_step()
        finally:
            players.get_track_info, players.last_sample_time = saved
        self.assertAlmostEqual(S.song_time(), 50.3, delta=0.05)

    def test_small_reading_jitter_does_not_jump_the_clock(self):
        S = self.state()
        saved = (players.get_track_info, players.last_sample_time)
        now = time.time()
        feed = {"pos": 50.0, "t": now}
        players.get_track_info = lambda: (True, "Song", "Artist", None, feed["pos"], 200.0, "id")
        players.last_sample_time = lambda: feed["t"]
        try:
            S.poll_spotify_step()
            feed["pos"], feed["t"] = 52.05, now + 2.0                   # 50 ms ahead of where the clock expects
            S.poll_spotify_step()
            self.assertAlmostEqual(S.current_pos, 52.0175, delta=0.001)  # eased 35% of the way, no jump
            feed["pos"], feed["t"] = 90.0, now + 4.0                    # a real seek is followed at once
            S.poll_spotify_step()
            self.assertAlmostEqual(S.current_pos, 90.0, delta=0.001)
        finally:
            players.get_track_info, players.last_sample_time = saved

    def test_dynamic_energy_follows_the_position_every_frame(self):
        S = self.state()
        S.dynamic_intensity_enabled = True
        S.current_pos, S.pos_sample_time, S.is_playing = 5.0, time.time(), False       # intro
        intro = S._intensity_goal()
        S.current_pos = 100.0                                                          # seek to the middle
        self.assertGreater(S._intensity_goal(), intro)
        self.assertEqual(S.current_section, "Chorus Drop")
        S.current_pos = 199.0                                                          # last seconds
        self.assertLess(S._intensity_goal(), 0.8)


class ArtUrlTest(unittest.TestCase):
    def test_other_players_cover_served_by_dashboard_once_loaded(self):
        S = engine.AppState()
        S.current_art_url = "nowplaying:Song|Artist|Alb|1"
        self.assertEqual(S._art_url_for_dashboard(), "")           # not downloaded yet
        S.current_art_bytes, S.palette_art_url = b"img", S.current_art_url
        self.assertTrue(S._art_url_for_dashboard().startswith("/api/art?v="))
        S.current_art_url = "https://i.scdn.co/image/abc"
        self.assertEqual(S._art_url_for_dashboard(), "https://i.scdn.co/image/abc")


class InputTest(unittest.TestCase):
    def test_non_finite_numbers_rejected(self):
        import web
        for bad in ("inf", "nan", float("inf")):
            with self.assertRaises(web.BadRequest):
                web._num({"pos": bad}, "pos", 0)
        self.assertEqual(web._num({"pos": "12.5"}, "pos", 0), 12.5)

    def test_lamp_ip_filter(self):
        import lamps
        self.assertTrue(lamps._is_local_ip("192.168.1.20"))
        for bad in ("8.8.8.8", "not-an-ip", "", "::1"):
            self.assertFalse(lamps._is_local_ip(bad))


class SmoothMotionTest(unittest.TestCase):
    """The lamps take only a few zone commands per frame: they must be shared out evenly,
    not left to lag and then pop (flicker)."""
    def run_flow(self, cycle=5.0, seconds=12.0, fps=15):
        import lamps
        from colors import lift_frame
        S = engine.AppState()
        S.save_config = lambda: None
        S.spatial_mode, S.motion_mode = "segmented", "flow"
        S.current_lamp_palette = [(230, 40, 40), (40, 60, 230), (240, 200, 40), (40, 200, 120)]
        g = lamps.GoveeController([])
        frames = []
        g.send_cmd = lambda msg, ips=None: frames.append(msg)
        shown, events, lag = [(0, 0, 0)] * 7, {z: [] for z in range(7)}, []
        for k in range(int(seconds * fps)):
            t = k / fps
            def target(at):
                return [tuple(int(round(v)) for v in c) for c in lift_frame(S.compute_target((at / cycle) % 1.0), S.dark_boost)[0]]
            frames.clear()
            g._send_lamp_segs("192.0.2.1", target(t + engine.LAMP_LEAD), False, now=t)
            for msg in frames:
                cmds = msg["msg"]["data"]["command"]
                if k > 0:      # (the first frame sets every zone)
                    self.assertLessEqual(len(cmds), g.SEG_BUDGET)
                zones_in_frame = set()
                for b64 in cmds:
                    raw = base64.b64decode(b64)
                    rgb, mask = tuple(raw[4:7]), raw[12] | (raw[13] << 8)
                    for z in range(7):
                        if mask & (1 << z):
                            shown[z] = rgb
                            events[z].append(t)
                            zones_in_frame.add(z)
                if t > 1.0:
                    self.assertLess(len(zones_in_frame), 7, "all zones re-sent at once (they would all pop together)")
            if t >= 3.0:
                tr = target(t)
                lag.extend(max(abs(a - b) for a, b in zip(shown[z], tr[z])) for z in range(7))
        return events, lag

    def test_zones_are_updated_steadily(self):
        events, lag = self.run_flow(cycle=5.0)
        for z, times in events.items():
            waits = [b - a for a, b in zip(times[3:], times[4:])]
            self.assertLess(max(waits), 0.75, f"zone {z} waited {max(waits):.2f}s between updates")
        self.assertLess(sum(lag) / len(lag), 9.0)          # (was ~11.5 before)

    def test_slow_flow_stays_close_to_the_colour(self):
        _, lag = self.run_flow(cycle=12.0)
        self.assertLess(sum(lag) / len(lag), 4.0)           # (was ~4.9 before)


class SlewLimitTest(unittest.TestCase):
    def test_fast_crossings_are_slowed_not_skipped(self):
        S = engine.AppState()
        S.save_config = lambda: None
        dark, bright = [(10, 10, 10)] * 7, [(250, 240, 230)] * 7
        t = 100.0
        out = S._limit_slew((dark, dark), t)                      # first frame passes straight through
        self.assertEqual(out[0][0], (10, 10, 10))
        prev, steps = out[0][0], []
        for _ in range(40):                                       # target jumps to bright and stays
            t += 1 / 15
            out = S._limit_slew((bright, bright), t)
            steps.append(max(abs(a - b) for a, b in zip(out[0][0], prev)))
            prev = out[0][0]
        self.assertLessEqual(max(steps), engine.SLEW_PER_SEC / 15 + 1)   # never faster than the limit
        self.assertEqual(prev, (250, 240, 230))                          # but it does get there (~1.2 s)
        self.assertGreater(sum(1 for s_ in steps if s_ > 0), 10)         # over many frames, not one jump

    def test_slow_motion_is_untouched_and_gaps_reset(self):
        S = engine.AppState()
        S.save_config = lambda: None
        a, b = [(100, 100, 100)] * 7, [(103, 99, 100)] * 7
        S._limit_slew((a, a), 10.0)
        self.assertEqual(S._limit_slew((b, b), 10.07)[0][0], (103, 99, 100))
        far = [(250, 0, 0)] * 7
        self.assertEqual(S._limit_slew((far, far), 20.0)[0][0], (250, 0, 0))   # after a long pause: no lag


class ThemeSupportTest(unittest.TestCase):
    def test_state_carries_what_the_designs_show(self):
        S = engine.AppState()
        S.save_config = lambda: None
        d = S.to_dict()
        for key in ("album", "source_name", "default_theme", "can_shuffle_repeat", "art_url", "palette_lamp", "flow", "player_pos"):
            self.assertIn(key, d)
        self.assertIn(d["default_theme"], ("classic", "a", "b", "c", "d"))

    def test_source_names(self):
        saved = (players._active, players._bundle)
        try:
            players._active, players._bundle = "spotify", ""
            self.assertEqual(players.source_name(), "Spotify")
            players._active = "music"
            self.assertEqual(players.source_name(), "Apple Music")
            players._active, players._bundle = "system", "com.google.Chrome"
            self.assertEqual(players.source_name(), "Chrome")
            players._bundle = "org.example.coolplayer"
            self.assertEqual(players.source_name(), "Coolplayer")
        finally:
            players._active, players._bundle = saved

    def test_theme_files_are_served_and_linked(self):
        import web
        for f in ("/themes.js", "/themes.css"):
            self.assertIn(f, web.STATIC_FILES)
            self.assertTrue(os.path.exists(os.path.join(web.WEB_DIR, f.lstrip("/"))))
        html = open(os.path.join(web.WEB_DIR, "index.html")).read()
        self.assertIn('src="/themes.js"', html)
        self.assertIn('id="themeRoot"', html)


class IconTest(unittest.TestCase):
    def test_every_icon_is_served_and_present(self):
        import json
        import web
        man = json.load(open(os.path.join(web.WEB_DIR, "manifest.webmanifest")))
        paths = {i["src"] for i in man["icons"]} | {"/favicon.ico", "/favicon-32.png", "/favicon.svg", "/icon-180.png"}
        for p in paths:
            self.assertIn(p, web.STATIC_FILES, p)
            self.assertTrue(os.path.exists(os.path.join(web.WEB_DIR, p.lstrip("/"))), p)
        self.assertTrue(any(i.get("purpose") == "maskable" for i in man["icons"]))
        html = open(os.path.join(web.WEB_DIR, "index.html")).read()
        for needle in ('href="/favicon.svg"', 'href="/favicon.ico"', 'href="/icon-180.png"'):
            self.assertIn(needle, html)


class FakeRequest:
    """Just enough of an HTTP handler to test the access checks."""
    def __init__(self, handler_cls, client_ip="192.168.1.50", headers=None):
        self.h = handler_cls.__new__(handler_cls)
        self.h.client_address = (client_ip, 5555)
        self.h.headers = headers or {}
        self.h.path = "/"


class WebSecurityTest(unittest.TestCase):
    def setUp(self):
        import web
        self.web = web
        self.H = web.GoveeHttpHandler
        self.token = web.pair_token()

    def req(self, ip="192.168.1.50", **headers):
        return FakeRequest(self.H, ip, headers).h

    def test_host_header_rebinding_blocked(self):
        self.assertTrue(self.req(Host="127.0.0.1:8765")._host_ok())
        self.assertTrue(self.req(Host="192.168.1.5:8765")._host_ok())
        self.assertTrue(self.req(Host="my-mac.local:8765")._host_ok())
        self.assertFalse(self.req(Host="evil.example.com:8765")._host_ok())
        self.assertFalse(self.req(Host="evil.example.com")._host_ok())

    def test_commands_need_our_header_and_matching_origin(self):
        self.assertFalse(self.req(Host="127.0.0.1:8765")._command_ok())
        self.assertTrue(self.req(Host="127.0.0.1:8765", **{"X-Govee-App": "1"})._command_ok())
        self.assertFalse(self.req(Host="127.0.0.1:8765", Origin="http://evil.com", **{"X-Govee-App": "1"})._command_ok())
        self.assertTrue(self.req(Host="127.0.0.1:8765", Origin="http://127.0.0.1:8765", **{"X-Govee-App": "1"})._command_ok())

    def test_other_devices_must_be_paired(self):
        self.assertTrue(self.req("127.0.0.1")._paired())               # this Mac
        self.assertFalse(self.req("192.168.1.50")._paired())            # stranger on the Wi-Fi
        self.assertFalse(self.req("192.168.1.50", Cookie="glowtrack=wrong")._paired())
        self.assertTrue(self.req("192.168.1.50", Cookie=f"glowtrack={self.token}")._paired())

    def test_local_client_detection(self):
        self.assertTrue(self.req("::1")._is_local_client())
        self.assertFalse(self.req("192.168.1.50")._is_local_client())


class LampPacketTest(unittest.TestCase):
    def test_checksum_and_layout(self):
        import lamps
        pkt = base64.b64decode(lamps.GoveeController.make_mask_b64(10, 20, 30, 0b0000101))
        self.assertEqual(len(pkt), 20)
        self.assertEqual(pkt[:4], b"\x33\x05\x15\x01")
        self.assertEqual(tuple(pkt[4:7]), (10, 20, 30))
        self.assertEqual(pkt[12], 0b101)
        chk = 0
        for b in pkt[:19]:
            chk ^= b
        self.assertEqual(pkt[19], chk)

    def test_colours_are_clamped(self):
        import lamps
        pkt = base64.b64decode(lamps.GoveeController.make_all_b64(-5, 300, 12.7))
        self.assertEqual(tuple(pkt[4:7]), (0, 255, 12))
        self.assertEqual(pkt[12], 0x7F)


class SpotifyParseTest(unittest.TestCase):
    def run_with(self, out):
        import subprocess
        orig = subprocess.run
        subprocess.run = lambda *a, **k: type("R", (), {"stdout": out})()
        try:
            return spotify.get_spotify_track_info()
        finally:
            subprocess.run = orig

    def test_parses_a_playing_track(self):
        r = self.run_with("playing ||| Song ||| Artist ||| https://img ||| 12,5 ||| 200.25 ||| spotify:track:1 ||| 40 ||| true ||| false")
        self.assertEqual(r, (True, "Song", "Artist", "https://img", 12.5, 200.25, "spotify:track:1"))
        self.assertEqual((spotify.EXTRAS["volume"], spotify.EXTRAS["shuffle"], spotify.EXTRAS["repeat"]), (40, True, False))

    def test_not_running_or_garbage(self):
        empty = (False, None, None, None, 0.0, 0.0, "")
        self.assertEqual(self.run_with("NOT_RUNNING"), empty)
        self.assertEqual(self.run_with(""), empty)
        self.assertEqual(self.run_with("paused ||| only two"), empty)


class FakeUdp:
    """A pretend light: listens on a local UDP port and keeps every packet it gets."""
    def __init__(self):
        import socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]

    def packets(self, n=1):
        out = []
        for _ in range(n):
            try:
                out.append(self.sock.recvfrom(65535)[0])
            except Exception:
                break
        return out

    def close(self):
        self.sock.close()


class OtherDevicesTest(unittest.TestCase):
    def setUp(self):
        import devices
        self.devices = devices
        self.fake = FakeUdp()
        self.addCleanup(self.fake.close)

    def red_blue(self):
        return [(255, 0, 0)] * 7, [(0, 0, 255)] * 7

    def test_make_device_validation(self):
        d = self.devices
        self.assertIsInstance(d.make_device("wiz", "192.168.1.9", "right"), d.WizLight)
        self.assertEqual(d.make_device("lifx", "10.0.0.4", "bogus").side, "left")
        for kind, ip in (("hue", "192.168.1.9"), ("wiz", "8.8.8.8"), ("wiz", "not-an-ip")):
            with self.assertRaises(ValueError):
                d.make_device(kind, ip)

    def test_wiz_message(self):
        import json
        w = self.devices.WizLight("127.0.0.1")
        w.PORT = self.fake.port
        w.send_frame([(200, 100, 50)] * 7, True, 50)
        msg = json.loads(self.fake.packets()[0])
        self.assertEqual(msg["method"], "setPilot")
        self.assertEqual((msg["params"]["r"], msg["params"]["g"], msg["params"]["b"]), (100, 50, 25))   # 50% brightness
        self.assertTrue(msg["params"]["state"])

    def test_lifx_packet_layout(self):
        import struct
        d = self.devices
        pkt = d.lifx_set_color((255, 0, 0), 60)
        size, proto, source = struct.unpack_from("<HHI", pkt, 0)
        self.assertEqual(size, len(pkt))
        self.assertEqual(proto & 0xFFF, 1024)             # protocol
        self.assertTrue(proto & (1 << 12))                # addressable
        self.assertFalse(proto & (1 << 13))               # not tagged (sent to one device)
        self.assertEqual(struct.unpack_from("<H", pkt, 32)[0], 102)           # SetColor
        _, hue, sat, bri, kelvin, dur = struct.unpack_from("<BHHHHI", pkt, 36)
        self.assertEqual((hue, sat, bri, dur), (0, 65535, 65535, 60))          # pure red
        _, hue, sat, bri, _, _ = struct.unpack_from("<BHHHHI", d.lifx_set_color((0, 255, 0)), 36)
        self.assertAlmostEqual(hue / 65535, 1 / 3, places=3)                   # pure green
        disc = d.lifx_packet(2, tagged=True, res_required=True)
        self.assertTrue(struct.unpack_from("<H", disc, 2)[0] & (1 << 13))
        self.assertEqual(disc[22] & 1, 1)                                      # response required

    def test_lifx_sends_to_device(self):
        import struct
        l = self.devices.LifxLight("127.0.0.1")
        l.PORT = self.fake.port
        l.send_frame([(0, 255, 0)] * 7, True, 100)
        pkt = self.fake.packets()[0]
        self.assertEqual(struct.unpack_from("<H", pkt, 32)[0], 102)

    def test_wled_spreads_zones_along_the_strip(self):
        w = self.devices.WledStrip("127.0.0.1")
        w.UDP_PORT = self.fake.port
        w.led_count = 13
        zones = [(0, 0, 0), (60, 0, 0), (120, 0, 0), (180, 0, 0), (240, 0, 0), (255, 0, 0), (255, 255, 255)]
        w.send_frame(zones, False, 100)
        pkt = self.fake.packets()[0]
        self.assertEqual(pkt[0], 2)                         # DRGB
        self.assertEqual(pkt[1], 2)                         # moving frame: short timeout
        self.assertEqual(len(pkt), 2 + 13 * 3)
        self.assertEqual(tuple(pkt[2:5]), (0, 0, 0))        # first LED = base zone
        self.assertEqual(tuple(pkt[-3:]), (255, 255, 255))  # last LED = top zone
        w.send_frame(zones, True, 100)
        self.assertEqual(self.fake.packets()[0][1], 255)    # held colour stays until changed

    def test_unchanged_colours_are_not_resent(self):
        w = self.devices.WizLight("127.0.0.1")
        w.PORT = self.fake.port
        w.min_interval = 0
        frame = [(10, 20, 30)] * 7
        w.send_frame(frame, False, 100)
        w.send_frame(frame, False, 100)
        w.send_frame([(11, 20, 30)] * 7, False, 100)         # a change of 1 is below the threshold
        self.assertEqual(len(self.fake.packets(5)), 1)
        w.send_frame([(90, 20, 30)] * 7, False, 100)
        self.assertEqual(len(self.fake.packets(5)), 1)

    def test_lamp_controller_feeds_devices_and_follows_side(self):
        import json
        import lamps
        right_fake = FakeUdp()
        self.addCleanup(right_fake.close)
        g = lamps.GoveeController([])
        g.send_cmd = lambda *a, **k: None                    # no real Govee lamps
        left_dev, right_dev = self.devices.WizLight("127.0.0.1", "left"), self.devices.WizLight("127.0.0.1", "right")
        left_dev.PORT, right_dev.PORT = self.fake.port, right_fake.port
        g.devices = [left_dev, right_dev]
        left, right = self.red_blue()
        g.send_frame(left, right, persistent=True)
        l = json.loads(self.fake.packets()[0])["params"]
        r = json.loads(right_fake.packets()[0])["params"]
        self.assertEqual((l["r"], l["b"]), (255, 0))
        self.assertEqual((r["r"], r["b"]), (0, 255))

    def test_other_govee_models_get_one_colour(self):
        import lamps
        g = lamps.GoveeController(["192.168.1.2", "192.168.1.3"])
        sent = []
        g.send_cmd = lambda msg, ips=None: sent.append(msg)
        g.skus["192.168.1.2"] = "H6199"                      # a model we don't know the zone packets of
        zones = [(255, 0, 0)] * 3 + [(0, 0, 255)] * 4
        g._send_lamp_segs("192.168.1.2", zones, True)
        self.assertEqual(sent[-1]["msg"]["cmd"], "colorwc")                    # one averaged colour
        g._send_lamp_segs("192.168.1.3", zones, True)                          # unknown model: zone packets as before
        self.assertEqual(sent[-1]["msg"]["cmd"], "ptReal")

    def test_state_lists_devices(self):
        S = engine.AppState()
        S.save_config = lambda: None
        S.add_device("wled", "192.168.1.77", "right")
        d = S.to_dict()["devices"]
        self.assertEqual([(x["kind"], x["ip"], x["side"]) for x in d], [("wled", "192.168.1.77", "right")])
        with self.assertRaises(ValueError):
            S.add_device("wled", "192.168.1.77", "left")      # duplicate
        S.remove_device("192.168.1.77")
        self.assertEqual(S.to_dict()["devices"], [])


    def test_lights_can_be_named_and_moved(self):
        import devices
        S = engine.AppState()
        saved = []
        S.save_config = lambda: saved.append(1)
        S.add_device("wiz", "192.168.1.60", "left", "  Desk   lamp  ")
        self.assertEqual(S.to_dict()["devices"][0]["name"], "Desk lamp")        # tidied
        S.update_device("192.168.1.60", name="Reading nook", side="right")
        d = S.to_dict()["devices"][0]
        self.assertEqual((d["name"], d["side"]), ("Reading nook", "right"))
        self.assertEqual(S.govee.devices[0].to_config()["name"], "Reading nook")  # saved to the config
        self.assertTrue(saved)
        S.update_device("192.168.1.60", name="")                                   # clearing goes back to "WiZ <ip>"
        self.assertEqual(S.to_dict()["devices"][0]["name"], "")
        self.assertEqual(devices.clean_name("x" * 60), "x" * 24)
        self.assertEqual(devices.clean_name("a\x00b\nc"), "abc")
        with self.assertRaises(ValueError):
            S.update_device("192.168.1.99", name="nope")
        S.remove_device("192.168.1.60")

    def test_names_survive_a_restart(self):
        import devices
        dev = devices.make_device("lifx", "192.168.1.61", "right", "Beam")
        again = devices.make_device(dev.to_config()["kind"], dev.to_config()["ip"], dev.to_config()["side"], dev.to_config()["name"])
        self.assertEqual((again.name, again.side), ("Beam", "right"))


class ReleaseLampsTest(unittest.TestCase):
    def _controller(self, powered=True):
        import lamps
        c = lamps.GoveeController(["192.168.1.2"])
        c.is_powered_on = powered
        sent = []
        c.send_cmd = lambda msg, ips=None: sent.append(msg["msg"])
        return c, sent

    def test_release_hands_lamps_back_with_a_plain_colour_command(self):
        c, sent = self._controller(powered=True)
        c.release()
        self.assertTrue(sent)
        for m in sent:
            self.assertEqual(m["cmd"], "colorwc")                       # ends zone-by-zone control
            self.assertEqual(m["data"]["colorTemInKelvin"], 3500)       # an ordinary warm white
            self.assertNotEqual(m["cmd"], "ptReal")

    def test_lamps_that_were_turned_off_stay_off(self):
        c, sent = self._controller(powered=False)
        c.release()
        self.assertEqual(sent, [])

    def test_release_stops_the_engine_and_is_safe_twice(self):
        S = engine.AppState()
        calls = []
        S.govee.release = lambda: calls.append(1)
        S.release_lamps()
        S.release_lamps()
        self.assertTrue(S.engine_paused)
        self.assertEqual(len(calls), 2)

    def test_release_command_only_from_this_mac(self):
        import web
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "web.py")).read()
        i = src.index('if path == "/api/release":')
        self.assertIn("_is_local_client()", src[i:i + 200])

    def test_app_releases_the_lamps_before_it_quits(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        swift = open(os.path.join(root, "mac", "main.swift")).read()
        i = swift.index("func applicationWillTerminate")
        body = swift[i:i + 300]
        self.assertLess(body.index("releaseLamps()"), body.index("server?.terminate()"))   # before the server is stopped
        self.assertIn("api/release", swift)


class WebFilesTest(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_static_files_are_compressed_and_revalidated(self):
        import gzip
        import tempfile
        import web
        d = tempfile.mkdtemp()
        old_dir, old_files = web.WEB_DIR, dict(web.STATIC_FILES)
        try:
            web.WEB_DIR = d
            web.STATIC_FILES["/t.js"] = "application/javascript; charset=utf-8"
            web.STATIC_FILES["/t.png"] = "image/png"
            body = b"function hello() { return 'hello world'; }\n" * 100
            open(os.path.join(d, "t.js"), "wb").write(body)
            open(os.path.join(d, "t.png"), "wb").write(b"\x89PNG" + b"\x00" * 2000)
            version, raw, gz, etag = web._static_entry("/t.js")
            self.assertEqual(raw, body)
            self.assertEqual(gzip.decompress(gz), body)
            self.assertLess(len(gz), len(body) / 5)
            self.assertEqual(web._static_entry("/t.js")[3], etag)           # unchanged file: same ETag
            self.assertIsNone(web._static_entry("/t.png")[2])                # pictures are not recompressed
            time.sleep(0.01)
            open(os.path.join(d, "t.js"), "wb").write(body + b"// edited\n")   # an edit shows on the next request
            self.assertNotEqual(web._static_entry("/t.js")[3], etag)
            self.assertIn(b"// edited", web._static_entry("/t.js")[1])
        finally:
            web.WEB_DIR = old_dir
            web.STATIC_FILES.clear()
            web.STATIC_FILES.update(old_files)
            web._STATIC_CACHE.clear()

    def test_fonts_are_bundled_and_the_page_asks_no_other_website(self):
        import re
        import web
        css = open(os.path.join(web.WEB_DIR, "fonts.css")).read()
        urls = re.findall(r"url\((/fonts/[^)]+)\)", css)
        self.assertGreaterEqual(len(urls), 9)
        for u in urls:
            self.assertIn(u, web.STATIC_FILES, u)                            # served
            self.assertTrue(os.path.exists(os.path.join(web.WEB_DIR, u.lstrip("/"))), u)
        self.assertIn("/fonts.css", web.STATIC_FILES)
        self.assertFalse([k for k in web.STATIC_FILES if "licenses" in k])    # licence texts are not served
        for name in ("index.html", "app.js", "themes.js", "themes.css", "app.css"):
            text = open(os.path.join(web.WEB_DIR, name)).read()
            self.assertNotIn("fonts.googleapis", text, name)
            self.assertNotIn("fonts.gstatic", text, name)
        self.assertIn('href="/fonts.css"', open(os.path.join(web.WEB_DIR, "index.html")).read())
        for fam in os.listdir(os.path.join(web.WEB_DIR, "fonts", "licenses")):
            self.assertIn("SIL OPEN FONT LICENSE", open(os.path.join(web.WEB_DIR, "fonts", "licenses", fam)).read())

    def test_shipped_app_does_not_watch_its_own_files(self):
        app = open(os.path.join(self.ROOT, "server", "app.py")).read()
        self.assertIn('os.environ.get("GOVEE_RELOAD", "1") != "0"', app)
        swift = open(os.path.join(self.ROOT, "mac", "main.swift")).read()
        i = swift.index('env["PYTHONPATH"]')
        self.assertIn('env["GOVEE_RELOAD"] = "0"', swift[i:i + 400])         # only the self-contained app (it has vendor/)


class ConfigSaveTest(unittest.TestCase):
    def test_many_threads_saving_at_once_never_lose_the_file(self):
        import json
        import tempfile
        import threading
        import config
        old = config.CONFIG_FILE
        d = tempfile.mkdtemp()
        config.CONFIG_FILE = os.path.join(d, "cfg.json")
        try:
            errors = []
            def run(n):
                for i in range(60):
                    config.save_config({"n": n, "i": i})
            threads = [threading.Thread(target=run, args=(n,)) for n in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            data = json.load(open(config.CONFIG_FILE))          # a whole, valid file
            self.assertEqual(sorted(data), ["i", "n"])
            self.assertFalse(os.path.exists(config.CONFIG_FILE + ".tmp"))
        finally:
            config.CONFIG_FILE = old


class UpdateNoticeTest(unittest.TestCase):
    def test_version_compare(self):
        import updates
        self.assertEqual(updates.parse_version("v3.1.4"), (3, 1, 4))
        self.assertEqual(updates.parse_version("3.2"), (3, 2, 0))
        self.assertIsNone(updates.parse_version("latest"))
        self.assertTrue(updates.is_newer("3.1.10", "3.1.9"))        # numbers, not text
        self.assertFalse(updates.is_newer("3.1.4", "3.1.4"))
        self.assertFalse(updates.is_newer("3.0.9", "3.1.0"))
        self.assertFalse(updates.is_newer("garbage", "3.1.0"))

    def test_state_reports_a_newer_release(self):
        import config
        import updates
        S = engine.AppState()
        S.save_config = lambda: None
        self.assertFalse(S.to_dict()["update_available"])
        real = updates.fetch_latest
        try:
            updates.fetch_latest = lambda: ("99.0.0", "https://github.com/omerham/glowtrack/releases/tag/v99.0.0")
            self.assertTrue(S.check_for_update(force=True))
            d = S.to_dict()
            self.assertTrue(d["update_available"])
            self.assertEqual(d["update_version"], "99.0.0")
            updates.fetch_latest = lambda: (config.VERSION, updates.RELEASES_PAGE)
            S.check_for_update(force=True)
            self.assertFalse(S.to_dict()["update_available"])
        finally:
            updates.fetch_latest = real

    def test_turning_checks_off_means_no_request(self):
        import updates
        S = engine.AppState()
        S.save_config = lambda: None
        calls = []
        real = updates.fetch_latest
        try:
            updates.fetch_latest = lambda: calls.append(1) or ("99.0.0", updates.RELEASES_PAGE)
            S.check_updates = False
            self.assertFalse(S.check_for_update())
            self.assertEqual(calls, [])                  # nothing was sent
            self.assertEqual(S.to_dict()["check_updates"], False)
        finally:
            updates.fetch_latest = real

    def test_a_failed_check_is_quiet(self):
        import updates
        real = urllib_open = updates.urllib.request.urlopen
        try:
            def boom(*a, **k):
                raise OSError("offline")
            updates.urllib.request.urlopen = boom
            self.assertIsNone(updates.fetch_latest())
        finally:
            updates.urllib.request.urlopen = real


class ReportProblemTest(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_version_is_one_number_everywhere(self):
        import config
        plist = open(os.path.join(self.ROOT, "mac", "Info.plist")).read()
        self.assertIn("<key>CFBundleShortVersionString</key><string>%s</string>" % config.VERSION, plist)
        self.assertIn("<key>CFBundleVersion</key><string>%s</string>" % config.VERSION, plist)
        S = engine.AppState()
        self.assertEqual(S.to_dict()["version"], config.VERSION)

    def test_issue_forms_exist_and_are_complete(self):
        d = os.path.join(self.ROOT, ".github", "ISSUE_TEMPLATE")
        for name in ("bug_report.yml", "other_lights_test.yml", "idea.yml", "config.yml"):
            self.assertTrue(os.path.exists(os.path.join(d, name)), name)
        bug = open(os.path.join(d, "bug_report.yml")).read()
        for field_id in ("version", "macos", "what", "log"):        # the report link pre-fills "version"
            self.assertIn("id: " + field_id, bug)
        self.assertIn("blank_issues_enabled: false", open(os.path.join(d, "config.yml")).read())

    def test_report_links_name_the_form_and_send_no_lamp_details(self):
        web_dir = os.path.join(self.ROOT, "server", "web")
        js = open(os.path.join(web_dir, "app.js")).read()
        i = js.index("function reportProblem")
        body = js[i:js.index("function shutdownServer")]
        self.assertIn("template=bug_report.yml", body)
        for secret in ("ip", "token", "paired", "cookie"):
            self.assertNotIn(secret + "=", body.lower())
        self.assertIn("reportProblem()", open(os.path.join(web_dir, "index.html")).read())
        self.assertIn("data-act=\"' + o[0]", open(os.path.join(web_dir, "themes.js")).read())
        self.assertIn("'report'", open(os.path.join(web_dir, "themes.js")).read())


class TempoTest(unittest.TestCase):
    def test_title_cleaning(self):
        self.assertEqual(tempo.clean_track_title("Anti-Hero"), "Anti-Hero")
        self.assertEqual(tempo.clean_track_title("Bohemian Rhapsody - Remastered 2011"), "Bohemian Rhapsody")
        self.assertEqual(tempo.clean_track_title("Song (feat. Someone)"), "Song")


if __name__ == "__main__":
    unittest.main()
