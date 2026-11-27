/* Demo mode: open the dashboard with  ?demo=1  to see it with a made-up song, generated cover art and
   pretend lamps. Used for the README screenshots and to look around without any lamps or music.

     /?demo=1&theme=b                      a design (a, b, c, d or classic)
     /?demo=1&theme=c&screen=full          screens: main, full, settings, lyrics (lyrics is the phone one)
     /?demo=1&theme=d&screen=full&lyrics=1 full screen with the synced lyrics
     &pos=71                               where in the song it is, in seconds
     &pal=cool|pale   &title=long|one   &art=none   &playing=0   &power=0   &ly=long     other situations to check a design against

   Nothing is read from or sent to the real server while it is on: state comes from here, and every
   command is swallowed, so clicking around cannot touch your lamps. Loaded only when ?demo=1 is in the address. */
(function () {
  'use strict';
  var Q = new URLSearchParams(location.search);
  var START = +Q.get('pos') || 71, T0 = Date.now();

  // palettes to check the designs against: warm (the default), cool (blue and navy) and pale (pastel, near white)
  var PALS = {
    warm: { sky: ['#16505a', '#1e6f78', '#f39b3d', '#e8452f'], sun: '#f6e7c8', a: '#e8452f', b: '#f39b3d', sea: '#10343a',
      left: ['#e8452f', '#ee5f31', '#f37c38', '#f6a24a', '#f6c776', '#f6dfa6', '#fff3dc'], right: ['#1e6f78', '#2b8587', '#58a07f', '#b9b45c', '#f39b3d', '#ef6a33', '#e8452f'],
      raw: ['#e8452f', '#f39b3d', '#1e6f78', '#f6e7c8', '#7a2e3a'], lamp: ['#ee5f31', '#f6a24a', '#2b8587', '#f6dfa6', '#9a3f4c'] },
    cool: { sky: ['#0b1d4a', '#1d3f8f', '#4f86d6', '#a9d3f0'], sun: '#e8f3ff', a: '#2c5db8', b: '#6fa6e8', sea: '#08142e',
      left: ['#0b1d4a', '#14307a', '#1d4aa8', '#2f6bd0', '#4f8ce0', '#86b6ee', '#d6e8fb'], right: ['#d6e8fb', '#86b6ee', '#4f8ce0', '#2f6bd0', '#1d4aa8', '#14307a', '#0b1d4a'],
      raw: ['#0b1d4a', '#1d4aa8', '#4f8ce0', '#d6e8fb', '#27406e'], lamp: ['#14307a', '#2f6bd0', '#86b6ee', '#d6e8fb', '#27406e'] },
    pale: { sky: ['#f4e9ef', '#f0dcdf', '#f7e6cf', '#e5eef0'], sun: '#fffaf0', a: '#e9c5cf', b: '#f2d9b8', sea: '#d9e6ea',
      left: ['#e9c5cf', '#eccdd0', '#efd5d0', '#f2dcc8', '#f5e3c8', '#f8ecd8', '#fffaf0'], right: ['#d9e6ea', '#dfe9e6', '#e5ecdf', '#ebeed7', '#f1ecd1', '#f5e8d0', '#f7e1d4'],
      raw: ['#e9c5cf', '#f2d9b8', '#d9e6ea', '#fffaf0', '#cdb8c2'], lamp: ['#eccdd0', '#f2dcc8', '#dfe9e6', '#fffaf0', '#d6c4cc'] }
  };
  var P = PALS[Q.get('pal')] || PALS.warm;
  function cover() {                     // abstract sunset cover, drawn here so no real album art is needed
    var c = document.createElement('canvas'); c.width = c.height = 640;
    var g = c.getContext('2d'), sky = g.createLinearGradient(0, 0, 0, 640);
    sky.addColorStop(0, P.sky[0]); sky.addColorStop(0.45, P.sky[1]); sky.addColorStop(0.62, P.sky[2]); sky.addColorStop(1, P.sky[3]);
    g.fillStyle = sky; g.fillRect(0, 0, 640, 640);
    g.fillStyle = P.sun; g.beginPath(); g.arc(320, 330, 150, 0, 6.2832); g.fill();
    for (var i = 0; i < 7; i++) { g.fillStyle = i % 2 ? P.a : P.b; g.fillRect(150, 372 + i * 22, 340, 9 + i * 2); }   // sun stripes over the water
    g.fillStyle = P.sea; g.fillRect(0, 520, 640, 120);
    return c.toDataURL('image/jpeg', 0.92);
  }
  var ART = Q.get('art') === 'none' ? '' : cover();
  var LEFT = P.left, RIGHT = P.right;
  var DUR = 218;

  function state() {
    var pos = Math.min(DUR - 1, START + (Date.now() - T0) / 1000);
    return {
      track: Q.get('title') === 'long' ? 'The Ballad of Someone With A Very Long Name (Remastered 2011)' : Q.get('title') === 'one' ? 'Go' : 'Golden Hour Drive',
      artist: Q.get('title') === 'long' ? 'An Artist With A Rather Long Name And Friends' : 'The Demo Tapes', album: 'Slow Light', art_url: ART,
      hex1: LEFT[3], hex2: RIGHT[3], seg_colors: LEFT, seg_colors_right: RIGHT,
      palette_raw: P.raw, palette_lamp: P.lamp,
      spatial_mode: 'segmented', motion_mode: 'static', flow_speed: 12, trans_speed: 3, vibrancy: 1.15,
      version: '3.2.1', update_available: false, update_version: '3.2.1', update_url: 'https://github.com/omerham/glowtrack/releases/latest',
      update_checked_at: 1, check_updates: true,
      music_pulse: true, current_bpm: 118, detected_bpm: 118, bpm_source: 'Deezer', bpm_manual: false, bpm_known: true, pulse_depth: 0.6,
      brightness: 85, is_powered_on: Q.get('power') !== '0', lamp_ips: ['192.168.1.21', '192.168.1.22'], available_ips: ['192.168.1.21', '192.168.1.22'],
      left_ip: '192.168.1.21', right_ip: '192.168.1.22', lamp_online: { '192.168.1.21': true, '192.168.1.22': true },
      identifying_ip: null, online_count: 2, configured_count: 2, status_known: true, status_error: '',
      is_swapped_lr: false, is_inverted_tb: false, dynamic_intensity: false, dark_boost: 0.65, preview_mode: 'smooth', fs_motion: 3,
      white_accent: true, volume: 60, shuffle: false, repeat: false, flow: null, intensity_factor: 1, intensity_section: 'Normal',
      player_pos: pos, track_dur: DUR, is_playing: Q.get('playing') !== '0', locked_swatch_index: null, is_ad: false,
      devices: [], discovered_devices: [], scanning_devices: false, player: 'spotify', source_name: 'Spotify', default_theme: 'classic',
      can_shuffle_repeat: true
    };
  }

  var LYRICS = [
    'Windows down on the coast road', 'The sky is turning amber', 'Every light is leaning slow', 'Humming to the radio',
    'Hold the wheel and let it ride', 'Colours spilling over the tide', 'We were always going home', 'Chasing what the evening shows',
    'Golden hour, golden hour', 'Everything is glowing', 'Golden hour, golden hour', 'Nowhere left to be going'
  ].map(function (w, i) { return [Math.round((12 + i * 6.5) * 100) / 100, w]; });

  if (Q.get('ly') === 'long') {         // long lines wrap onto several rows: a check that the lyrics column never cuts them off
    LYRICS = ['Windows down on the coast road while the whole sky turns to amber and the radio hums along',
      'Every light along the harbour is leaning slowly over toward the water and the waiting tide',
      'We were always going home the long way round, counting all the colours on the wet and shining street',
      'Hold the wheel and let it ride, there is nowhere left to be and nothing left to prove tonight',
      'Golden hour, golden hour, everything is glowing and the evening shows us what we came here for',
      'Chasing what the evening shows us, every window every wave a little lighter than before',
      'Nowhere left to be going when the light is falling like this over the edge of everything we know',
      'And we keep on driving into the colours until the colours have all gone'].map(function (w, i) { return [Math.round((12 + i * 6.5) * 100) / 100, w]; });
  }

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
    var st = document.createElement('style'); st.textContent = (Q.get('notext') === '1' ? '#themeRoot *, #themeRoot *::before { color: transparent !important; text-shadow: none !important; } ' : '') + '*:not(#trackProgressBar):not(#fsProgressBar), *::before, *::after { transition: none !important; } #themeRoot { padding: 0 !important; }'; document.head.appendChild(st);
  }
  window.addEventListener('load', function () {         // where the design sits in the window, so a screenshot can be cropped to it
    setTimeout(function () {
      var d = document.querySelector('#themeRoot:not([hidden]) .design'), r = (d || document.getElementById('appShell') || document.body).getBoundingClientRect();
      var boxes = {}; ['.credit .k', '.credit h3', '.credit p', '.modes .m:not(.on)', '.dock .t', '.dock .tl2 span'].forEach(function (sel) {   // where the text sits, for contrast checks
        var e = document.querySelector('#themeRoot .design ' + sel); if (e) { var b = e.getBoundingClientRect(), cs = getComputedStyle(e); boxes[sel] = [b.left, b.top, b.width, b.height, cs.color, cs.opacity]; }
      });
      document.documentElement.setAttribute('data-boxes', JSON.stringify(boxes));
      if (r) document.documentElement.setAttribute('data-rect', JSON.stringify([r.left, r.top, r.width, r.height, window.devicePixelRatio, window.innerWidth, window.innerHeight]));
    }, 2500);
  });
  document.documentElement.setAttribute('data-demo', '1');
})();
