/* Demo mode: open the dashboard with  ?demo=1  to see it with a made-up song, generated cover art and
   pretend lamps. Used for the README screenshots and to look around without any lamps or music.

     /?demo=1&theme=b                      a design (a, b, c, d or classic)
     /?demo=1&theme=c&screen=full          screens: main, full, settings, lyrics (lyrics is the phone one)
     /?demo=1&theme=d&screen=full&lyrics=1 full screen with the synced lyrics
     &pos=71                               where in the song it is, in seconds

   Nothing is read from or sent to the real server while it is on: state comes from here, and every
   command is swallowed, so clicking around cannot touch your lamps. Loaded only when ?demo=1 is in the address. */
(function () {
  'use strict';
  var Q = new URLSearchParams(location.search);
  var START = +Q.get('pos') || 71, T0 = Date.now();

  function cover() {                     // abstract sunset cover, drawn here so no real album art is needed
    var c = document.createElement('canvas'); c.width = c.height = 640;
    var g = c.getContext('2d'), sky = g.createLinearGradient(0, 0, 0, 640);
    sky.addColorStop(0, '#16505a'); sky.addColorStop(0.45, '#1e6f78'); sky.addColorStop(0.62, '#f39b3d'); sky.addColorStop(1, '#e8452f');
    g.fillStyle = sky; g.fillRect(0, 0, 640, 640);
    g.fillStyle = '#f6e7c8'; g.beginPath(); g.arc(320, 330, 150, 0, 6.2832); g.fill();
    for (var i = 0; i < 7; i++) { g.fillStyle = i % 2 ? '#e8452f' : '#f39b3d'; g.fillRect(150, 372 + i * 22, 340, 9 + i * 2); }   // sun stripes over the water
    g.fillStyle = '#10343a'; g.fillRect(0, 520, 640, 120);
    return c.toDataURL('image/jpeg', 0.92);
  }
  var ART = cover();
  var LEFT = ['#e8452f', '#ee5f31', '#f37c38', '#f6a24a', '#f6c776', '#f6dfa6', '#fff3dc'];
  var RIGHT = ['#1e6f78', '#2b8587', '#58a07f', '#b9b45c', '#f39b3d', '#ef6a33', '#e8452f'];
  var DUR = 218;

  function state() {
    var pos = Math.min(DUR - 1, START + (Date.now() - T0) / 1000);
    return {
      track: 'Golden Hour Drive', artist: 'The Demo Tapes', album: 'Slow Light', art_url: ART,
      hex1: LEFT[3], hex2: RIGHT[3], seg_colors: LEFT, seg_colors_right: RIGHT,
      palette_raw: ['#e8452f', '#f39b3d', '#1e6f78', '#f6e7c8', '#7a2e3a'], palette_lamp: ['#ee5f31', '#f6a24a', '#2b8587', '#f6dfa6', '#9a3f4c'],
      spatial_mode: 'segmented', motion_mode: 'static', flow_speed: 12, trans_speed: 3, vibrancy: 1.15,
      version: '3.2.1', update_available: false, update_version: '3.2.1', update_url: 'https://github.com/omerham/glowtrack/releases/latest',
      update_checked_at: 1, check_updates: true,
      music_pulse: true, current_bpm: 118, detected_bpm: 118, bpm_source: 'Deezer', bpm_manual: false, bpm_known: true, pulse_depth: 0.6,
      brightness: 85, is_powered_on: true, lamp_ips: ['192.168.1.21', '192.168.1.22'], available_ips: ['192.168.1.21', '192.168.1.22'],
      left_ip: '192.168.1.21', right_ip: '192.168.1.22', lamp_online: { '192.168.1.21': true, '192.168.1.22': true },
      identifying_ip: null, online_count: 2, configured_count: 2, status_known: true, status_error: '',
      is_swapped_lr: false, is_inverted_tb: false, dynamic_intensity: false, dark_boost: 0.65, preview_mode: 'smooth', fs_motion: 3,
      white_accent: true, volume: 60, shuffle: false, repeat: false, flow: null, intensity_factor: 1, intensity_section: 'Normal',
      player_pos: pos, track_dur: DUR, is_playing: true, locked_swatch_index: null, is_ad: false,
      devices: [], discovered_devices: [], scanning_devices: false, player: 'spotify', source_name: 'Spotify', default_theme: 'classic',
      can_shuffle_repeat: true
    };
  }

  var LYRICS = [
    'Windows down on the coast road', 'The sky is turning amber', 'Every light is leaning slow', 'Humming to the radio',
    'Hold the wheel and let it ride', 'Colours spilling over the tide', 'We were always going home', 'Chasing what the evening shows',
    'Golden hour, golden hour', 'Everything is glowing', 'Golden hour, golden hour', 'Nowhere left to be going'
  ].map(function (w, i) { return [Math.round((12 + i * 6.5) * 100) / 100, w]; });

  function json(obj) { return Promise.resolve(new Response(JSON.stringify(obj), { status: 200, headers: { 'Content-Type': 'application/json' } })); }
  var realFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    var u = String(url), post = opts && opts.method && opts.method.toUpperCase() === 'POST';
    if (post) return json({ status: 'ok' });                                    // commands go nowhere
    if (u.indexOf('/api/state') >= 0) return json(state());
    if (u.indexOf('/api/lyrics') >= 0) return json({ status: 'synced', synced: LYRICS, plain: [], track: 'Golden Hour Drive' });
    if (u.indexOf('/api/pairing') >= 0) return json({ open: false, url: 'http://192.168.1.20:8765/?token=demo-only' });
    return realFetch(url, opts);
  };

  function FakeEvents() {              // the live-update stream, fed from here
    var self = this;
    self.onmessage = null; self.onerror = null;
    function push() { if (self.onmessage) self.onmessage({ data: JSON.stringify(state()) }); }
    setTimeout(push, 400);
    self._t = setInterval(push, 1000);
  }
  FakeEvents.prototype.close = function () { clearInterval(this._t); };
  window.EventSource = FakeEvents;

  var screen = Q.get('screen');
  if (screen && screen !== 'main') {
    window.addEventListener('load', function () {
      setTimeout(function () { if (window.Themes && Themes.view) Themes.view(Themes.current(), screen === 'lyrics' ? 'lyrics' : screen, Q.get('lyrics') === '1'); }, 900);
    });
  }
  window.addEventListener('load', function () { setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 700); });   // fit the layout once fonts and sizes have settled
  if (Q.get('shot') === '1') {           // for screenshots: nothing mid-fade, so the picture is the finished state
    var st = document.createElement('style'); st.textContent = '*:not(#trackProgressBar):not(#fsProgressBar), *::before, *::after { transition: none !important; } #themeRoot { padding: 0 !important; }'; document.head.appendChild(st);
  }
  window.addEventListener('load', function () {         // where the design sits in the window, so a screenshot can be cropped to it
    setTimeout(function () {
      var d = document.querySelector('#themeRoot:not([hidden]) .design'), r = (d || document.getElementById('appShell') || document.body).getBoundingClientRect();
      if (r) document.documentElement.setAttribute('data-rect', JSON.stringify([r.left, r.top, r.width, r.height, window.devicePixelRatio, window.innerWidth, window.innerHeight]));
    }, 2500);
  });
  document.documentElement.setAttribute('data-demo', '1');
})();
