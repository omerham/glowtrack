/* Glowtrack designs: Instrument (A), Dot (B), Poster (C), Stage (D).
   Runs next to the classic dashboard. Pick a design in Settings; "Classic" turns this off.
   Kept light on purpose: the page is built once per screen, only the lamp colours change on a
   timer (about 8 times a second while the lamps move, never while hidden or still), and
   the clock and lyrics tick once a second. */
(function () {
  'use strict';
  var THEMES = ['classic', 'a', 'b', 'c', 'd'];
  var MODES = [
    { id: 'solid', a: 'Solid', b: 'Still', long: 'Solid' },
    { id: 'wave', a: 'Wave', b: 'Moving', long: 'Ambient Wave' },
    { id: 'split', a: 'Split', b: 'Still', long: 'Two-Lamp Split' },
    { id: 'zones', a: '7-Zone', b: 'Moving', long: '7-Zone Fade' }
  ];
  var GROUPS = [
    ['Design', [['seg', 'theme', 'Look', [['classic', 'Classic'], ['a', 'A Instrument'], ['b', 'B Dot'], ['c', 'C Poster'], ['d', 'D Stage']]]]],
    ['Colours', [['sl', 'vib', 'Vibrancy', 70, 180], ['sl', 'dark', 'Dark colour boost', 0, 100], ['tg', 'white', 'White accents from the cover'], ['sw', 'swatch', 'Lock one colour']]],
    ['Motion', [['sl', 'cycle', 'Colour cycle', 3, 20], ['sl', 'fade', 'Song fade', 1, 8], ['seg', 'fsm', 'Full-screen motion', [['0', 'Off'], ['1', 'Slow'], ['3', 'Medium'], ['5', 'Fast']]]]],
    ['Beat pulse', [['sl', 'depth', 'Pulse depth', 10, 90], ['tempo']]],
    ['Playback', [['sl', 'vol', 'Volume', 0, 100], ['tg', 'shuffle', 'Shuffle'], ['tg', 'repeat', 'Repeat']]],
    ['Lamps', [['btns', 'lampbtns', [['swap', 'Swap left / right'], ['flip', 'Flip top / bottom'], ['rescan', 'Rescan'], ['blinkL', 'Blink left'], ['blinkR', 'Blink right']]], ['seg', 'preview', 'Lamp preview', [['smooth', 'Smooth'], ['low', 'Low power'], ['off', 'Off']]]]],
    ['Other lights', [['form']]],
    ['Phone and tablet', [['link']]],
    ['Server', [['danger', 'Shut down']]]
  ];
  var ICON = {
    prev: '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 2h2v12H3zM14 2v12L6 8z" fill="currentColor"/></svg>',
    next: '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M11 2h2v12h-2zM2 2v12l8-6z" fill="currentColor"/></svg>',
    play: '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M4 2v12l10-6z" fill="currentColor"/></svg>',
    pause: '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 2h4v12H3zM9 2h4v12H9z" fill="currentColor"/></svg>'
  };
  function aopt() { return 1; }
  function transportA() { return '<button class="key" data-step="-1" aria-label="Previous">' + ICON.prev + '</button><button class="key" data-play aria-label="Play or pause"><span data-b="playicon"></span></button><button class="key" data-step="1" aria-label="Next">' + ICON.next + '</button>'; }

  function cellsA(side) { var h = '', i; for (i = 0; i < 7; i++) h += '<div class="cell" data-z="' + (i + 1) + '" style="--c:var(--' + side + i + ')"></div>'; return h; }

  var HTML = {
    a: function () {
      var knob = '<svg viewBox="0 0 112 112"><circle cx="56" cy="56" r="50" fill="none" stroke="#181916" stroke-width="1"/><circle cx="56" cy="56" r="36" fill="#d3d5d0" stroke="#181916" stroke-width="1.4"/>' +
        Array.from({ length: 21 }, function (_, i) { var a = (-135 + i * 13.5) * Math.PI / 180; return '<line x1="' + (56 + 42 * Math.sin(a)).toFixed(1) + '" y1="' + (56 - 42 * Math.cos(a)).toFixed(1) + '" x2="' + (56 + 49 * Math.sin(a)).toFixed(1) + '" y2="' + (56 - 49 * Math.cos(a)).toFixed(1) + '" stroke="#181916" stroke-width="1"/>'; }).join('') +
        '<g data-b="knobneedle"><line x1="56" y1="56" x2="56" y2="26" stroke="#181916" stroke-width="3"/></g></svg>';
      return '<div class="design A">' +
        '<div class="hd"><div class="mark">GLOWTRACK</div><div class="meta"><span data-b="lampsline"></span> &nbsp;/&nbsp; 14 zones &nbsp;/&nbsp; <span data-b="src"></span></div><div class="hb"><button data-open="full">Full screen</button><button data-open="settings">Settings</button></div><button class="pwr" data-power><span class="led"></span>Power</button></div>' +
        '<section class="mod src"><div class="mt">Source</div><div class="cover"></div><h3 class="ttl" data-b="title"></h3><div class="art" data-b="artist"></div>' +
        '<div class="rule" data-seek><i></i></div><div style="display:flex;justify-content:space-between;margin-bottom:14px"><span data-b="pos"></span><span data-b="dur"></span></div><div class="keys">' + transportA() + '</div></section>' +
        '<section class="mod out"><div class="mt">Output</div><div class="lamps"><div><div class="lamp l">' + cellsA('L') + '</div><div class="lh">L</div></div><div><div class="lamp r">' + cellsA('R') + '</div><div class="lh">R</div></div></div>' +
        '<div class="follow"><span>Mode</span><span data-b="modelong"></span><span>Zone 1</span><span>base of lamp</span><span>Zone 7</span><span>top of lamp</span></div></section>' +
        '<section class="mod mode"><div class="mt">Mode</div><div class="kg">' + MODES.map(function (m) { return '<button class="mk" data-mode="' + m.id + '"><span class="led"></span><b>' + m.a + '</b><span>' + m.b + '</span></button>'; }).join('') + '</div>' +
        '<div class="row"><div class="knob" data-knob>' + knob + '</div><div><div class="bpm">Brightness<b data-b="bright"></b></div></div></div>' +
        '<div class="row" style="margin-top:14px;align-items:flex-start"><div class="bpm" style="flex:1">Tempo<b data-b="bpm"></b></div><div style="flex:1"><button class="sw" data-toggle="pulse"><span class="trk"></span>Pulse</button><button class="sw" data-toggle="energy"><span class="trk"></span>Energy</button></div></div></section></div>';
    },
    b: function () {
      return '<div class="design B">' +
        '<div class="top"><span>Glowtrack &nbsp;/&nbsp; <span data-b="src"></span></span><span class="tl"><button data-open="settings">Settings</button><button data-open="full">Full screen</button></span></div>' +
        '<div class="tt dot" data-b="titleU"></div><div class="ar" data-b="artistU"></div>' +
        '<div class="tm dot"><span data-b="pos"></span><small data-b="durlong"></small><span class="pn"><button data-play><span data-b="playword"></span></button><button data-step="1">Next</button></span></div><div class="pbar" data-seek><i></i></div>' +
        '<div class="menu">' + MODES.map(function (m) { return '<button class="opt" data-mode="' + m.id + '">' + m.long + '</button>'; }).join('') + '</div>' +
        '<div class="dim"><span>Brightness</span><span class="dots" data-b="dimdots"></span><span data-b="bright"></span></div>' +
        '<canvas width="880" height="1000" data-canvas></canvas>' +
        '<div class="cap"><span>Left</span><span data-b="bpmlong"></span><span>Right</span></div>' +
        '<div class="tog"><button class="opt" data-toggle="pulse">Pulse</button><button class="opt" data-toggle="energy">Energy</button></div></div>';
    },
    c: function () {
      var pil = function (side) { var h = '', i; for (i = 0; i < 7; i++) h += '<i style="--c:var(--' + side + i + ')"></i>'; return '<div class="pil ' + (side === 'L' ? 'l' : 'r') + '">' + h + '</div>'; };
      return '<div class="design C"><div class="b1"></div><div class="b2"></div><div class="b4"></div>' +
        '<div class="tl" data-b="title"></div><div class="ar" data-b="artistline"></div>' +
        '<div class="modes">' + MODES.map(function (m) { return '<button data-mode="' + m.id + '">' + m.a + '</button>'; }).join('') + '</div>' +
        '<div class="br2"><span>Brightness</span><div class="br" data-bar><i></i></div><span data-b="bright"></span></div><div class="ft"><button class="pill" data-toggle="pulse">Pulse</button><button class="pill" data-toggle="energy">Energy</button></div>' +
        '<div class="bpm"><small data-b="bpmlabel"></small><span data-b="bpm"></span></div>' +
        '<div class="tr"><button data-play><span data-b="playword"></span><span data-b="pos"></span></button><button data-step="1"><span>Next</span><span data-b="dur"></span></button><button data-open="full"><span>Full screen</span></button><button data-open="settings"><span>Settings</span></button></div>' +
        pil('L') + pil('R') + '</div>';
    },
    d: function () {
      var lamp = function (side) { var h = '', i; for (i = 0; i < 7; i++) h += '<i style="--c:var(--' + side + i + ')"></i>'; return '<div class="lampw ' + (side === 'L' ? 'l' : 'r') + '">' + h + '</div>'; };
      var pic = function (m) { return '<button class="m" data-mode="' + m.id + '">' + m.a + '</button>'; };
      return '<div class="design D"><div class="wall"></div><div class="floor"></div>' + lamp('L') + lamp('R') +
        '<div class="frame"><div></div></div>' +
        '<div class="credit"><div class="k">Now playing &nbsp;/&nbsp; <span data-b="src"></span></div><h3 data-b="title"></h3><p data-b="artistalbum"></p></div>' +
        '<div class="modes">' + MODES.map(pic).join('') + '</div>' +
        '<div class="dock"><div class="tp"><button data-step="-1" aria-label="Previous">' + ICON.prev + '</button><button data-play aria-label="Play or pause"><span data-b="playicon"></span></button><button data-step="1" aria-label="Next">' + ICON.next + '</button></div>' +
        '<div class="tl2"><span data-b="pos"></span><div class="tk" data-seek><i></i></div><span data-b="dur"></span></div>' +
        '<label style="display:flex;align-items:center;gap:10px">Brightness <input type="range" id="dBright" min="5" max="100" data-range aria-label="Brightness"></label>' +
        '<button class="t" data-toggle="pulse">Pulse</button><button class="t" data-toggle="energy">Energy</button><button class="t" data-open="settings">Settings</button><button class="t" data-open="full">Full screen</button></div></div>';
    }
  };


  /* ---------- full-screen builders ---------- */
  function pilC(side) { var h = '', i; for (i = 0; i < 7; i++) h += '<i style="--c:var(--' + side + i + ')"></i>'; return '<div class="pil ' + (side === 'L' ? 'l' : 'r') + '">' + h + '</div>'; }
  function lampD(side) { var h = '', i; for (i = 0; i < 7; i++) h += '<i style="--c:var(--' + side + i + ')"></i>'; return '<div class="lampw ' + (side === 'L' ? 'l' : 'r') + '">' + h + '</div>'; }
  var FS = {
    a: function (n) {
      return '<div class="design A fs o' + (n || aopt()) + '"><div class="hd"><div class="mark">GLOWTRACK</div><div class="meta">Full screen &nbsp;/&nbsp; <span data-b="src"></span></div><div class="hb"><button data-lyrics>Lyrics</button><button data-open="settings">Settings</button><button data-open="main">Exit</button></div></div>' +
        '<div class="cov2"></div><div class="info"><h2 class="big" data-b="title"></h2><div class="art2" data-b="artistalbum"></div><div class="tmr"><span data-b="pos"></span><small data-b="durlong"></small></div></div>' +
        '<div class="lyr" data-lyr></div>' +
        '<div class="foot"><div class="keys">' + transportA() + '</div><div class="rule" data-seek><i></i></div></div></div>';
    },
    b: function () {
      return '<div class="design B fs"><div class="top"><span>Glowtrack</span><span data-b="src"></span><button data-open="main" style="text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,.55)">Exit</button></div>' +
        '<div class="tt dot" data-b="titleU"></div><div class="ar a1" data-b="artistU"></div>' +
        '<div class="tm dot"><span data-b="pos"></span><small data-b="durlong"></small><span class="pn"><button data-play><span data-b="playword"></span></button><button data-step="1">Next</button></span></div>' +
        '<canvas width="880" height="1000" data-canvas></canvas><div class="lyr dot" data-lyr></div><div class="pbar" data-seek><i></i></div>' +
        '<div class="dim"><span>Brightness</span><span class="dots" data-b="dimdots"></span><span data-b="bright"></span></div>' +
        '<div class="tog"><button class="opt" data-lyrics>Lyrics</button><button class="opt" data-toggle="pulse">Pulse</button><button class="opt" data-toggle="energy">Energy</button></div></div>';
    },
    c: function () {
      return '<div class="design C fs"><div class="b1"></div><div class="b4"></div><div class="cv"></div><div class="ar" data-b="artistline"></div>' +
        '<div class="tl" data-b="title"></div><div class="tmr" data-b="pos"></div><div class="sub"><div data-b="src"></div><div data-b="bpmlong"></div><div data-b="modelong"></div></div><div class="lyr" data-lyr></div>' + pilC('L') + pilC('R') +
        '<div class="tr2"><button data-play><span data-b="playword"></span></button><button data-step="1">Next</button></div>' +
        '<div class="tr3"><button data-lyrics>Lyrics</button><button data-toggle="pulse">Pulse</button><button data-open="main">Exit</button></div></div>';
    },
    d: function () {
      return '<div class="design D fs"><div class="wall"></div><div class="floor"></div><div class="frame"><div></div></div>' +
        '<div class="credit"><div class="k">Now playing &nbsp;/&nbsp; <span data-b="src"></span></div><h3 data-b="title"></h3><p data-b="artistalbum"></p></div><div class="lyr" data-lyr></div>' +
        '<div class="mini"><button data-step="-1" aria-label="Previous">' + ICON.prev + '</button><button data-play aria-label="Play or pause"><span data-b="playicon"></span></button><button data-step="1" aria-label="Next">' + ICON.next + '</button>' +
        '<span data-b="pos"></span><span style="opacity:.5">/</span><span data-b="dur"></span><button class="lyb" data-lyrics aria-label="Show lyrics"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2 3.5h12M2 7h12M2 10.5h8M2 14h5"/></svg>Lyrics</button><button class="lyb" data-open="main" style="border-color:rgba(255,255,255,.4)">Exit</button></div></div>';
    }
  };

  /* ---------- settings builders ---------- */
  function dotsFor(key) { var r = RANGE[key], h = '', i; for (i = 0; i < 14; i++) h += '<button data-sdv="' + Math.round(r[0] + (r[1] - r[0]) * i / 13) + '" data-sdk="' + key + '" aria-label="' + key + ' ' + Math.round(r[0] + (r[1] - r[0]) * i / 13) + '"></button>'; return h; }
  var PRIM = {
    a: {
      head: function (t) { return '<div class="mt" style="margin-top:14px">' + t + '</div>'; },
      sl: function (r) { return '<div class="sr"><div class="top"><span>' + r[2] + '</span><span class="sv" data-sv="' + r[1] + '"></span></div><input type="range" data-sl="' + r[1] + '" min="' + r[3] + '" max="' + r[4] + '" aria-label="' + r[2] + '"></div>'; },
      tg: function (r) { return '<div class="sr t"><span>' + r[2] + '</span><button class="sw" data-st="' + r[1] + '" aria-label="' + r[2] + '"><span class="trk"></span></button></div>'; },
      info: function (r) { return '<div class="sr"><div class="top"><span>' + r[1] + '</span>' + (r[3] ? '<button class="act">' + r[3] + '</button>' : '') + '</div><div class="txt">' + r[2] + '</div></div>'; },
      danger: function (r) { return '<div class="sr t"><span>' + r[1] + '</span><button class="act danger" data-act="shutdown">' + r[1] + '</button></div>'; }
    },
    b: {
      head: function (t) { return '<div class="gh">' + t + '</div>'; },
      sl: function (r) { return '<div class="row"><span>' + r[2] + '</span><span class="sd">' + dotsFor(r[1]) + '</span><span class="sv" data-sv="' + r[1] + '"></span></div>'; },
      tg: function (r) { return '<div class="row tg"><span>' + r[2] + '</span><button class="btn" data-st="' + r[1] + '" data-tt></button></div>'; },
      info: function (r) { return '<div class="row tg"><span>' + r[1] + '<br><span style="opacity:.55;text-transform:none;letter-spacing:0">' + r[2] + '</span></span>' + (r[3] ? '<button class="btn">' + r[3] + '</button>' : '') + '</div>'; },
      danger: function (r) { return '<div class="row tg"><span>' + r[1] + '</span><button class="btn danger" data-act="shutdown">' + r[1] + '</button></div>'; }
    },
    c: {
      head: function (t) { return '<div class="gh">' + t + '</div>'; },
      sl: function (r) { return '<div class="row"><span class="lb">' + r[2] + '</span><div class="bar" data-sb="' + r[1] + '"><i></i></div><span class="sv" data-sv="' + r[1] + '"></span></div>'; },
      tg: function (r) { return '<div class="row tg"><span class="lb">' + r[2] + '</span><button class="pill" data-st="' + r[1] + '" data-tt></button></div>'; },
      info: function (r) { return '<div class="row tg"><span class="lb">' + r[1] + ' <small style="font:500 11px \'DM Mono\',monospace;opacity:.7;text-transform:none;letter-spacing:0">' + r[2] + '</small></span>' + (r[3] ? '<button class="pill">' + r[3] + '</button>' : '') + '</div>'; },
      danger: function () { return ''; }
    },
    d: {
      head: function (t) { return '<div class="gh">' + t + '</div>'; },
      sl: function (r) { return '<div class="row"><span>' + r[2] + '</span><input type="range" data-sl="' + r[1] + '" min="' + r[3] + '" max="' + r[4] + '" aria-label="' + r[2] + '"><span class="sv" data-sv="' + r[1] + '"></span></div>'; },
      tg: function (r) { return '<div class="row tg"><span>' + r[2] + '</span><button class="tgl" data-st="' + r[1] + '" data-tt></button></div>'; },
      info: function (r) { return '<div class="row tg"><span>' + r[1] + ' <span style="opacity:.55;font-size:12px;margin-left:8px">' + r[2] + '</span></span>' + (r[3] ? '<button class="btn">' + r[3] + '</button>' : '') + '</div>'; },
      danger: function () { return ''; }
    }
  };
  function groupHtml(d, gi) { var g = GROUPS[gi]; return PRIM[d].head(g[0]) + g[1].map(function (r) { return PRIM[d][r[0]](r); }).join(''); }
  var EXTRA = {
    seg: function (r) { return '<div class="xblk"><div class="xl">' + r[2] + '</div><div class="xrow">' + r[3].map(function (o) { return '<button class="xbtn" data-segk="' + r[1] + '" data-segv="' + o[0] + '">' + o[1] + '</button>'; }).join('') + '</div></div>'; },
    btns: function (r) { return '<div class="xblk"><div class="xrow">' + r[2].map(function (o) { return '<button class="xbtn" data-act="' + o[0] + '">' + o[1] + '</button>'; }).join('') + '</div></div>'; },
    sw: function (r) { return '<div class="xblk"><div class="xl">' + r[2] + '</div><div class="xrow" data-swatches></div></div>'; },
    tempo: function () { return '<div class="xblk"><div class="xl">Tempo <span class="xv" data-b="tempotext"></span></div><div class="xrow"><button class="xbtn" data-act="tap">Tap</button><button class="xbtn" data-act="auto">Auto</button></div></div>'; },
    form: function () { return '<div class="xblk"><div class="xl">WiZ, LIFX and WLED lights (experimental)</div><div class="xrow" data-devlist></div><div class="xrow"><select class="xin" id="tdKind"><option value="wiz">WiZ</option><option value="lifx">LIFX</option><option value="wled">WLED strip</option></select><input class="xin" id="tdIp" placeholder="192.168.1.x"><select class="xin" id="tdSide"><option value="left">Follows left</option><option value="right">Follows right</option></select><button class="xbtn" data-act="adddev">Add</button><button class="xbtn" data-act="scandev">Scan</button></div><div class="xmsg" data-b="devmsg"></div></div>'; },
    link: function () { return '<div class="xblk"><div class="xl">Open this link once on each phone or tablet (same Wi-Fi). Keep it private.</div><div class="xrow"><input class="xin xwide" readonly data-pairlink><button class="xbtn" data-act="copylink">Copy</button></div></div>'; }
  };
  ['a', 'b', 'c', 'd'].forEach(function (d) { Object.keys(EXTRA).forEach(function (k) { PRIM[d][k] = EXTRA[k]; }); });
  function allGroups(d, ids) { return ids.map(function (i) { return groupHtml(d, i); }).join(''); }
  var ALL = [0, 1, 2, 3, 4, 5, 6, 7, 8], NOSRV = [0, 1, 2, 3, 4, 5, 6, 7];
  var ST = {
    a: function () { return '<div class="design A st"><div class="hd"><div class="mark">GLOWTRACK</div><div class="meta">Settings &nbsp;/&nbsp; changes save automatically</div><button class="pwr" data-open="back">Done</button></div><div class="cols"><section class="mod">' + allGroups('a', [0, 1, 2]) + '</section><section class="mod">' + allGroups('a', [3, 4, 5]) + '</section><section class="mod">' + allGroups('a', [6, 7, 8]) + '</section></div></div>'; },
    b: function () { return '<div class="design B st"><div class="h1 dot">SETTINGS</div><button class="btn" data-open="back" style="position:absolute;right:36px;top:34px">Done</button><div class="col c1">' + allGroups('b', [0, 1, 2, 3]) + '</div><div class="col c2">' + allGroups('b', [4, 5, 6, 7, 8]) + '</div></div>'; },
    c: function () { return '<div class="design C st"><div class="b1"></div><div class="h1">Settings</div><div class="side"><button data-open="back">Done</button><button class="danger" data-act="shutdown">Shut down</button></div><div class="list">' + allGroups('c', NOSRV) + '</div></div>'; },
    d: function () { return '<div class="design D st"><div class="wall"></div><div class="floor"></div>' + lampD('L') + lampD('R') + '<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><h3>Settings</h3><span style="display:flex;gap:8px"><button class="btn danger" data-act="shutdown">Shut down</button><button class="btn" data-open="back">Done</button></span></div>' + allGroups('d', NOSRV) + '</div></div>'; }
  };
  var STPH = {
    a: function () { return '<div class="design A st stph"><div class="hd"><div class="mark">GLOWTRACK</div><div class="meta">Settings</div><button class="pwr" data-open="back">Done</button></div><section class="mod">' + allGroups('a', ALL) + '</section></div>'; },
    b: function () { return '<div class="design B st stph"><div class="h1 dot">SETTINGS</div><div class="nav"><button class="btn" data-open="back">Done</button></div><div class="col">' + allGroups('b', ALL) + '</div></div>'; },
    c: function () { return '<div class="design C st stph"><div class="h1">Settings</div><div class="side"><button data-open="back">Done</button><button class="danger" data-act="shutdown">Shut down</button></div><div class="list">' + allGroups('c', NOSRV) + '</div></div>'; },
    d: function () { return '<div class="design D st stph"><div class="panel"><div style="display:flex;justify-content:space-between;align-items:center"><h3>Settings</h3><span style="display:flex;gap:8px"><button class="btn danger" data-act="shutdown">Shut down</button><button class="btn" data-open="back">Done</button></span></div>' + allGroups('d', NOSRV) + '</div></div>'; }
  };
  function lyph(letter) { return function () { return '<div class="design ' + letter + ' lyph"><button class="lyback" data-open="back">Back</button><div class="lyt" data-b="title"></div><div class="lyr" data-lyr></div></div>'; }; }
  var LYPH = { a: lyph('A'), b: lyph('B'), c: lyph('C'), d: lyph('D') };


  /* ---------- phone builders (main screen only) ---------- */
  function knobSvg() {
    return '<svg viewBox="0 0 112 112"><circle cx="56" cy="56" r="50" fill="none" stroke="#181916" stroke-width="1"/><circle cx="56" cy="56" r="36" fill="#d3d5d0" stroke="#181916" stroke-width="1.4"/>' +
      Array.from({ length: 21 }, function (_, i) { var a = (-135 + i * 13.5) * Math.PI / 180; return '<line x1="' + (56 + 42 * Math.sin(a)).toFixed(1) + '" y1="' + (56 - 42 * Math.cos(a)).toFixed(1) + '" x2="' + (56 + 49 * Math.sin(a)).toFixed(1) + '" y2="' + (56 - 49 * Math.cos(a)).toFixed(1) + '" stroke="#181916" stroke-width="1"/>'; }).join('') +
      '<g data-b="knobneedle"><line x1="56" y1="56" x2="56" y2="26" stroke="#181916" stroke-width="3"/></g></svg>';
  }
  var PH = {
    a: function () {
      return '<div class="design A ph"><div class="hd"><div class="mark">GLOWTRACK</div><div class="hb"><button data-open="lyrics">Lyrics</button><button data-open="settings">Settings</button></div><button class="pwr" data-power><span class="led"></span>Power</button></div>' +
        '<div class="cover"></div><div class="lampsm"><div class="lamp l">' + cellsA('L') + '</div><div class="lamp r">' + cellsA('R') + '</div></div>' +
        '<h3 class="ttl" data-b="title"></h3><div class="art" data-b="artist"></div><div class="rule" data-seek><i></i></div><div class="tms"><span data-b="pos"></span><span data-b="dur"></span></div>' +
        '<div class="keys">' + transportA() + '</div><div class="kg">' + MODES.map(function (m) { return '<button class="mk" data-mode="' + m.id + '"><span class="led"></span><b>' + m.a + '</b><span>' + m.b + '</span></button>'; }).join('') + '</div>' +
        '<div class="bt"><div class="knob" data-knob>' + knobSvg() + '</div><div class="bpm">Brightness<b data-b="bright"></b></div><div class="tg2"><button class="sw" data-toggle="pulse"><span class="trk"></span>Pulse</button><button class="sw" data-toggle="energy"><span class="trk"></span>Energy</button></div></div></div>';
    },
    b: function () {
      return '<div class="design B ph"><div class="top"><span>Glowtrack &nbsp;/&nbsp; <span data-b="src"></span></span><span class="tl"><button data-open="lyrics">Lyrics</button><button data-open="settings">Settings</button></span></div>' +
        '<div class="tt dot" data-b="titleU"></div><div class="ar" data-b="artistU"></div>' +
        '<div class="tm dot"><span data-b="pos"></span><small data-b="durlong"></small><span class="pn"><button data-play><span data-b="playword"></span></button><button data-step="1">Next</button></span></div>' +
        '<canvas width="880" height="1000" data-canvas></canvas><div class="pbar" data-seek><i></i></div>' +
        '<div class="menu">' + MODES.map(function (m) { return '<button class="opt" data-mode="' + m.id + '">' + m.long + '</button>'; }).join('') + '</div>' +
        '<div class="dim"><span>Brightness</span><span class="dots" data-b="dimdots"></span><span data-b="bright"></span></div>' +
        '<div class="tog"><button class="opt" data-toggle="pulse">Pulse</button><button class="opt" data-toggle="energy">Energy</button></div></div>';
    },
    c: function () {
      return '<div class="design C ph"><div class="b1"></div><div class="b4"></div><div class="tl" data-b="title"></div><div class="ar" data-b="artistline"></div>' +
        '<div class="modes">' + MODES.map(function (m) { return '<button data-mode="' + m.id + '">' + m.a + '</button>'; }).join('') + '</div>' +
        '<div class="br2"><span>Brightness</span><div class="br" data-bar><i></i></div><span data-b="bright"></span></div><div class="ft"><button class="pill" data-toggle="pulse">Pulse</button><button class="pill" data-toggle="energy">Energy</button><span data-b="bpmlong"></span></div>' +
        '<div class="nav2"><button data-open="lyrics">Lyrics</button><button data-open="settings">Settings</button></div><div class="tr"><button data-play><span data-b="playword"></span><span data-b="pos"></span></button><button data-step="1"><span>Next</span><span data-b="dur"></span></button></div>' + pilC('L') + pilC('R') + '</div>';
    },
    d: function () {
      var pic = function (m) { return '<button class="m" data-mode="' + m.id + '">' + m.a + '</button>'; };
      return '<div class="design D ph"><div class="wall"></div><div class="floor"></div>' + lampD('L') + lampD('R') + '<div class="frame"><div></div></div>' +
        '<div class="credit"><div class="k">Now playing &nbsp;/&nbsp; <span data-b="src"></span></div><h3 data-b="title"></h3><p data-b="artistalbum"></p></div>' +
        '<div class="modes">' + MODES.map(pic).join('') + '</div>' +
        '<div class="dock"><div class="tp"><button data-step="-1" aria-label="Previous">' + ICON.prev + '</button><button data-play aria-label="Play or pause"><span data-b="playicon"></span></button><button data-step="1" aria-label="Next">' + ICON.next + '</button></div>' +
        '<div class="tl2"><span data-b="pos"></span><div class="tk" data-seek><i></i></div><span data-b="dur"></span></div>' +
        '<label style="display:flex;align-items:center;gap:10px">Brightness <input type="range" id="dBrightP" min="5" max="100" data-range aria-label="Brightness"></label><button class="t" data-toggle="pulse">Pulse</button><button class="t" data-toggle="energy">Energy</button></div><div class="nav3"><button class="m" data-open="lyrics">Lyrics</button><button class="m" data-open="settings">Settings</button></div></div>';
    }
  };


  /* ============================================================
     Runtime: live state in, API calls out, as little work as possible
     ============================================================ */
  var root = document.getElementById('themeRoot');
  var LS = null; try { LS = window.localStorage; } catch (e) { LS = null; }
  var DEF = { desk: [1000, 640], ph: [390, 800] };
  var OFF = [27, 27, 30];
  var T = { theme: null, screen: 'main', lyrics: false, s: null, tState: 0, basePos: 0, kind: 'desk', built: '', el: null, anim: null, animKey: '', sec: null,
            ov: {}, idleT: null, lines: [], lyTrack: null, lyStatus: '', lyReq: 0, lastLy: '', sig: {}, taps: [], pair: '', confirm: false, cache: { zones: '' } };

  function rgb(h) { if (Array.isArray(h)) return h; h = String(h || '#333333').replace('#', ''); if (h.length === 3) h = h.replace(/(.)/g, '$1$1'); var n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function mix(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }
  function css(c, k) { k = k == null ? 1 : k; return 'rgb(' + Math.round(c[0] * k) + ',' + Math.round(c[1] * k) + ',' + Math.round(c[2] * k) + ')'; }
  function lum(c) { return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255; }
  function fmt(s) { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function api(path, body) { return fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Govee-App': '1' }, body: JSON.stringify(body || {}) }).catch(function () {}); }
  function q(sel) { return root.querySelectorAll(sel); }

  var MODE_PRESET = { solid: 'solid', wave: 'wave', split: 'duo', zones: 'segmented' };
  function modeOf(s) { return s.spatial_mode === 'segmented' ? 'zones' : s.spatial_mode === 'duo' ? 'split' : (s.motion_mode === 'static' ? 'solid' : 'wave'); }
  function layoutKind() { return root.clientHeight > root.clientWidth * 1.05 ? 'ph' : 'desk'; }

  /* ---- clock: position is kept locally between server updates ---- */
  function pos() { var s = T.s; if (!s) return 0; var p = T.basePos + (s.is_playing ? (performance.now() - T.tState) / 1000 : 0); return Math.max(0, Math.min(s.track_dur || p, p)); }

  /* ---- palette: always four colours ---- */
  function palette(s) {
    var p = (s.palette_lamp && s.palette_lamp.length ? s.palette_lamp : ['#444444']).slice(0, 4), i = 0;
    while (p.length < 4) { var base = rgb(p[i % p.length]); p.push('#' + base.map(function (v) { return Math.round(v * (0.55 + 0.1 * p.length)).toString(16).padStart(2, '0'); }).join('')); i++; }
    return p;
  }

  /* ---- lamp colours: from the server's flow description, like the classic preview ---- */
  function parseStops(f) { var key = JSON.stringify(f.stops); if (T.stopsKey !== key) { T.stopsKey = key; T.stops = f.stops.map(function (a) { return [a[0], rgb(a[1])]; }); } return T.stops; }
  function sampleStops(stops, u) {
    u = ((u % 1) + 1) % 1;
    for (var i = 1; i < stops.length; i++) if (u <= stops[i][0]) { var a = stops[i - 1], b = stops[i]; return mix(a[1], b[1], (u - a[0]) / Math.max(1e-6, b[0] - a[0])); }
    return stops[stops.length - 1][1];
  }
  function lampZones(s, now) {
    var L = [], R = [], i;
    if (!s.is_powered_on) { for (i = 0; i < 7; i++) { L.push(OFF); R.push(OFF); } return { L: L, R: R, k: 1 }; }
    var mode = s.preview_mode || 'smooth', f = s.flow;
    if (f && mode !== 'off' && f.stops && f.stops.length > 1) {
      var st = parseStops(f), phase = f.phase + (now - T.tState) / 1000 / Math.max(2.5, f.cycle);
      for (i = 0; i < 7; i++) { L.push(sampleStops(st, phase + f.span * i / 6)); R.push(sampleStops(st, phase + f.right_offset + f.span * i / 6)); }
      if (f.inverted) { L.reverse(); R.reverse(); }
    } else {
      var a = (s.seg_colors && s.seg_colors.length === 7) ? s.seg_colors : Array(7).fill(s.hex1 || '#333333'), b = (s.seg_colors_right && s.seg_colors_right.length === 7) ? s.seg_colors_right : a;
      for (i = 0; i < 7; i++) { L.push(rgb(a[i])); R.push(rgb(b[i])); }
    }
    var br = T.ov.bright && T.ov.bright.until > now ? T.ov.bright.v : s.brightness;
    return { L: L, R: R, k: 0.35 + 0.65 * (br / 100) };
  }

  /* ---- B: dot-matrix lamp drawing ---- */
  function drawDots(canvas, z) {
    var c = canvas.getContext('2d'), W = canvas.width, H = canvas.height; c.clearRect(0, 0, W, H);
    var cols = 5, cell = 30, rowsPerZone = 4, rows = 28, gapX = 150, lampW = cols * cell, top = 70;
    [[z.L, 90], [z.R, 90 + lampW + gapX + 40]].forEach(function (side) {
      var x0 = side[1], zs = side[0];
      for (var r = 0; r < rows; r++) {
        var col = zs[6 - Math.floor(r / rowsPerZone)], edge = (r === 0 || r === rows - 1) ? 0.55 : 1;
        for (var k = 0; k < cols; k++) {
          var x = x0 + k * cell + cell / 2, y = top + r * 30 + 15;
          c.beginPath(); c.arc(x, y, 9.5 * (0.82 + 0.18 * edge), 0, 6.283); c.fillStyle = 'rgba(255,255,255,0.10)'; c.fill();
          c.beginPath(); c.arc(x, y, 9, 0, 6.283); c.fillStyle = css(col, Math.max(0.08, z.k)); c.fill();
        }
      }
      c.fillStyle = 'rgba(255,255,255,.45)';
      for (var zi = 0; zi < 7; zi++) { c.beginPath(); c.arc(x0 - 30, top + (6 - zi) * 120 + 60, 3, 0, 6.283); c.fill(); }
    });
  }

  /* ---- animation tick: only the lamp colours change here ---- */
  function tick() {
    var s = T.s; if (!s || !T.el || document.hidden) return;
    var now = performance.now(), z = lampZones(s, now), el = T.el, i, sig = '';
    var out = [];
    for (i = 0; i < 7; i++) { out.push(css(z.L[i], z.k)); }
    for (i = 0; i < 7; i++) { out.push(css(z.R[i], z.k)); }
    sig = out.join('|');
    if (sig === T.cache.zones) return;
    T.cache.zones = sig;
    for (i = 0; i < 7; i++) { el.style.setProperty('--L' + i, out[i]); el.style.setProperty('--R' + i, out[7 + i]); }
    var cv = el.querySelector('[data-canvas]'); if (cv) drawDots(cv, z);
  }
  function schedule() {
    var s = T.s, key = '';
    if (s && T.theme && T.theme !== 'classic' && !document.hidden && s.flow && s.is_powered_on && (s.preview_mode || 'smooth') !== 'off') key = (s.preview_mode || 'smooth');
    if (key === T.animKey) return;
    T.animKey = key; if (T.anim) { clearInterval(T.anim); T.anim = null; }
    if (key) T.anim = setInterval(tick, key === 'smooth' ? 125 : 500);
  }
  function secTick() {
    var s = T.s; if (!s || !T.el || document.hidden) return;
    var p = pos(), dur = s.track_dur || 0;
    T.el.style.setProperty('--prog', dur ? (p / dur).toFixed(4) : '0');
    setB('pos', fmt(p));
    if (showsLyrics()) paintLyrics();
  }

  /* ---- text and classes ---- */
  function setB(key, val) { q('[data-b="' + key + '"]').forEach(function (e) { if (e.textContent !== val) e.textContent = val; }); }
  function setBH(key, val) { q('[data-b="' + key + '"]').forEach(function (e) { if (e._h !== val) { e._h = val; e.innerHTML = val; } }); }
  function cur(key) {
    var s = T.s, o = T.ov[key]; if (o && o.until > performance.now()) return o.v;
    switch (key) {
      case 'vib': return Math.round((s.vibrancy || 1.15) * 100); case 'dark': return Math.round((s.dark_boost == null ? 0.65 : s.dark_boost) * 100);
      case 'cycle': return Math.round(s.flow_speed || 5); case 'fade': return Math.round(s.trans_speed || 3); case 'depth': return Math.round((s.pulse_depth || 0.6) * 100);
      case 'vol': return s.volume == null ? 50 : s.volume; case 'white': return !!s.white_accent; case 'shuffle': return !!s.shuffle; case 'repeat': return !!s.repeat;
      case 'theme': return T.theme; case 'fsm': return String(s.fs_motion == null ? 1 : s.fs_motion); case 'preview': return s.preview_mode || 'smooth';
    }
  }
  function showsLyrics() { return (T.screen === 'full' && T.lyrics) || T.screen === 'lyrics'; }

  function paint() {
    var s = T.s, el = T.el; if (!s || !el) return;
    var d = T.theme, pal = palette(s), palSig = pal.join(','), mode = modeOf(s);
    if (T.sig.pal !== palSig) {
      T.sig.pal = palSig;
      pal.forEach(function (c, i) { var r = rgb(c); el.style.setProperty('--p' + i, c); el.style.setProperty('--t' + i, lum(r) > 0.56 ? '#141311' : '#f6f3ec'); });
      if (d === 'c') root.style.background = pal[0]; else root.style.background = '';
      el.style.setProperty('--cov', 'radial-gradient(circle at 24% 22%, ' + pal[0] + ' 0 34%, transparent 62%), radial-gradient(circle at 78% 78%, ' + pal[1] + ' 0 30%, transparent 60%), linear-gradient(135deg, ' + pal[2] + ', ' + pal[3] + ')');
      T.sig.art = null;
    }
    var artSig = s.art_url || '';
    if (T.sig.art !== artSig) { T.sig.art = artSig; if (artSig) el.style.setProperty('--cov', 'url("' + artSig + '")'); }
    setB('lampsline', (s.online_count || 0) + ' of ' + (s.configured_count || 0) + ' lamps online');
    var src = s.source_name || 'Spotify', track = s.track || '', artist = s.artist || '', album = s.album || '';
    setB('title', track); setB('titleU', track.toUpperCase()); setB('artist', artist); setB('artistU', artist.toUpperCase());
    setB('artistline', album ? artist + '  /  ' + album : artist); setB('artistalbum', album ? artist + ', ' + album : artist);
    setB('src', src); setB('dur', fmt(s.track_dur)); setB('durlong', '/ ' + fmt(s.track_dur));
    var bpm = Math.round(s.current_bpm || 0); setB('bpm', String(bpm)); setB('bpmlong', bpm + ' bpm'); setB('bpmlabel', 'BPM');
    setB('tempotext', bpm + ' BPM, ' + (s.bpm_known === false ? 'not found: tap to set' : (s.bpm_source || '')));
    var mdef = MODES.filter(function (m) { return m.id === mode; })[0]; setB('modelong', mdef ? mdef.long : '');
    setBH('playicon', s.is_playing ? ICON.pause : ICON.play); setB('playword', s.is_playing ? 'Pause' : 'Play');
    var br = T.ov.bright && T.ov.bright.until > performance.now() ? T.ov.bright.v : s.brightness;
    setB('bright', br + '%'); el.style.setProperty('--bright', br);
    q('[data-mode]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-mode') === mode); });
    q('[data-toggle]').forEach(function (b) { var k = b.getAttribute('data-toggle'); b.classList.toggle('on', k === 'pulse' ? !!s.music_pulse : !!s.dynamic_intensity); });
    q('[data-power]').forEach(function (b) { b.classList.toggle('on', !!s.is_powered_on); });
    q('[data-lyrics]').forEach(function (b) { b.classList.toggle('on', T.lyrics); });
    q('[data-bright]').forEach(function (b) { b.classList.toggle('on', +b.getAttribute('data-bright') <= br); });
    var rg = el.querySelector('[data-range]'); if (rg && +rg.value !== br) rg.value = br;
    var nd = el.querySelector('[data-b="knobneedle"]'); if (nd) nd.setAttribute('transform', 'rotate(' + (-135 + (br - 5) / 95 * 270) + ' 56 56)');
    el.classList.toggle('ly', !!T.lyrics && el.classList.contains('fs'));
    // settings values
    ['vib', 'dark', 'cycle', 'fade', 'depth', 'vol'].forEach(function (k) {
      var v = cur(k); var txt = fmtSet(k, v);
      q('[data-sv="' + k + '"]').forEach(function (e) { if (e.textContent !== txt) e.textContent = txt; });
      q('[data-sl="' + k + '"]').forEach(function (e) { if (+e.value !== v && document.activeElement !== e) e.value = v; });
      q('[data-sdk="' + k + '"]').forEach(function (b) { b.classList.toggle('on', +b.getAttribute('data-sdv') <= v); });
      q('[data-sb="' + k + '"]').forEach(function (b) { var r2 = RANGE[k]; b.style.setProperty('--w', ((v - r2[0]) / (r2[1] - r2[0]) * 100) + '%'); });
    });
    ['white', 'shuffle', 'repeat'].forEach(function (k) {
      var v = cur(k);
      q('[data-st="' + k + '"]').forEach(function (b) {
        b.classList.toggle('on', v); if (b.hasAttribute('data-tt')) b.textContent = v ? 'On' : 'Off';
        if (k !== 'white') { var row = b.closest('.row,.sr'); if (row) row.style.display = s.can_shuffle_repeat === false ? 'none' : ''; }
      });
    });
    q('[data-segk]').forEach(function (b) { b.classList.toggle('on', String(cur(b.getAttribute('data-segk'))) === b.getAttribute('data-segv')); });
    q('[data-act="shutdown"]').forEach(function (b) { b.textContent = T.confirm ? 'Click again to confirm' : 'Shut down'; });
    paintSwatches(s, pal); paintDevices(s);
    fitTitles();
    schedule(); tick(); secTick();
    if (showsLyrics()) { loadLyrics(); paintLyrics(); }
  }
  function fmtSet(k, v) { return k === 'vib' ? (v / 100).toFixed(2) + 'x' : (k === 'cycle' || k === 'fade') ? v + 's' : v + '%'; }
  var RANGE = {}; GROUPS.forEach(function (g) { g[1].forEach(function (r) { if (r[0] === 'sl') RANGE[r[1]] = [r[3], r[4]]; }); });

  function paintSwatches(s, pal) {
    var idx = s.locked_swatch_index == null ? -1 : s.locked_swatch_index, sig = pal.join(',') + idx + (s.palette_lamp || []).length;
    q('[data-swatches]').forEach(function (h) {
      if (h._sig === sig) return; h._sig = sig;
      var raw = s.palette_lamp || [], html = '<button class="xbtn' + (idx < 0 ? ' on' : '') + '" data-swv="-1">Auto</button>';
      raw.forEach(function (c, i) { html += '<button class="xsw' + (idx === i ? ' on' : '') + '" data-swv="' + i + '" style="background:' + c + '" aria-label="Lock colour ' + (i + 1) + '"></button>'; });
      h.innerHTML = html;
    });
  }
  function paintDevices(s) {
    var sig = JSON.stringify([s.devices, s.discovered_devices, s.scanning_devices]);
    q('[data-devlist]').forEach(function (h) {
      if (h._sig === sig) return; h._sig = sig; var html = '';
      (s.devices || []).forEach(function (d) { html += '<div class="xdev"><i class="' + (d.online ? 'on' : '') + '"></i><span>' + d.label + ' ' + d.ip + ', follows ' + d.side + '</span><button class="xbtn" data-act="rmdev" data-ip="' + d.ip + '">Remove</button></div>'; });
      (s.discovered_devices || []).forEach(function (d) { html += '<div class="xdev"><i></i><span>Found ' + d.kind.toUpperCase() + ' ' + d.ip + '</span><button class="xbtn" data-act="adddisc" data-kind="' + d.kind + '" data-ip="' + d.ip + '">Add</button></div>'; });
      if (s.scanning_devices) html += '<div class="xmsg">Looking for lights on your network...</div>';
      h.innerHTML = html;
    });
  }

  /* ---- Poster title: shrink until the whole title fits its block ---- */
  function fitTitles() {
    q('.C .tl').forEach(function (el) {
      var des = el.closest('.design'), fs = des.classList.contains('fs'), ly = des.classList.contains('ly'), ph = des.classList.contains('ph');
      var key = el.textContent + '|' + fs + ly + ph; if (el._fit === key) return; el._fit = key;
      var size = ph ? 140 : !fs ? 128 : ly ? 56 : 120;
      while (size > 26) { el.style.fontSize = size + 'px'; if (el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1) break; size -= 3; }
    });
  }

  /* ---- lyrics ---- */
  function loadLyrics() {
    var s = T.s; if (!s || !s.track) return;
    if (T.lyTrack === s.track && T.lyStatus && T.lyStatus !== 'error') return;
    T.lyTrack = s.track; T.lyStatus = 'loading'; T.lines = []; T.lastLy = ''; var req = ++T.lyReq, track = s.track;
    fetch('/api/lyrics').then(function (r) { return r.json(); }).then(function (res) {
      if (req !== T.lyReq || res.track !== track) return;
      T.lyStatus = res.status || 'none';
      T.lines = res.status === 'synced' ? res.synced : (res.status === 'plain' ? (res.plain || []).map(function (w) { return [0, w]; }) : []);
      T.lastLy = ''; paintLyrics();
    }).catch(function () { if (req === T.lyReq) { T.lyStatus = 'error'; T.lastLy = ''; paintLyrics(); } });
  }
  function paintLyrics() {
    var holders = q('[data-lyr]'); if (!holders.length) return;
    var n = T.kind === 'ph' ? 14 : 7, html = '', st = T.lyStatus, lines = T.lines, idx = -1, i;
    if (st === 'synced') { var p = pos() + 0.12; for (i = 0; i < lines.length; i++) { if (lines[i][0] <= p) idx = i; else break; } }
    var key = st + '|' + idx + '|' + (T.s && T.s.track);
    if (key === T.lastLy) return; T.lastLy = key;
    if (st === 'synced') {
      var start = Math.max(0, idx - 1);
      for (i = start; i < Math.min(lines.length, start + n); i++) html += '<div class="l' + (i === idx ? ' cur' : '') + '" data-lt="' + lines[i][0] + '">' + esc(lines[i][1] || '...') + '</div>';
    } else if (st === 'plain') {
      for (i = 0; i < Math.min(lines.length, n + 2); i++) html += '<div class="l pl">' + esc(lines[i][1] || ' ') + '</div>';
    } else {
      html = '<div class="l cur msg">' + ({ loading: 'Loading lyrics...', instrumental: 'Instrumental', error: 'Could not load lyrics', none: 'No lyrics found for this song' }[st] || 'No lyrics') + '</div>';
    }
    holders.forEach(function (h) { h.innerHTML = html; });
  }
  function esc(t) { return String(t).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  /* ---- screens ---- */
  function builderFor(kind) {
    var d = T.theme;
    if (kind === 'ph') return T.screen === 'settings' ? STPH[d] : T.screen === 'lyrics' ? LYPH[d] : PH[d];
    return T.screen === 'settings' ? ST[d] : T.screen === 'full' ? FS[d] : HTML[d];
  }
  function render() {
    if (!T.theme || T.theme === 'classic' || !T.s) return;
    var kind = layoutKind();
    if (kind === 'ph' && T.screen === 'full') T.screen = 'main';
    if (kind === 'desk' && T.screen === 'lyrics') { T.screen = 'full'; T.lyrics = true; }
    var key = T.theme + '|' + T.screen + '|' + kind;
    if (key !== T.built) mount(key, kind);
    paint();
  }
  function mount(key, kind) {
    T.built = key; T.kind = kind; T.sig = {}; T.cache.zones = ''; T.stopsKey = null;
    var scroll = (kind === 'ph' && (T.screen === 'settings' || T.screen === 'lyrics')), html = builderFor(kind)();
    root.setAttribute('data-d', T.theme);
    root.classList.remove('idle');
    if (scroll) root.innerHTML = '<div class="tscroll">' + html + '</div>';
    else root.innerHTML = '<div class="tfit"><div class="tscale">' + html + '</div></div>';
    T.el = root.querySelector('.design');
    var dots = q('[data-b="dimdots"]');
    dots.forEach(function (h) { for (var i = 1; i <= 20; i++) { var b = document.createElement('button'); b.setAttribute('data-bright', i * 5); b.setAttribute('aria-label', 'Brightness ' + i * 5); h.appendChild(b); } });
    q('[data-knob]').forEach(bindKnob);
    if (T.screen === 'settings') loadPair();
    if (T.screen === 'full') wake();
    fit();
  }
  function fit() {
    var f = root.querySelector('.tfit'); if (!f) return;
    var sc = f.firstChild, dim = T.kind === 'ph' ? DEF.ph : DEF.desk;
    var cs = getComputedStyle(root), W = root.clientWidth, H = root.clientHeight - parseFloat(cs.paddingTop || 0);
    var s = Math.max(0.2, Math.min(W / dim[0], H / dim[1], 2.4));
    f.style.width = Math.round(dim[0] * s) + 'px'; f.style.height = Math.round(dim[1] * s) + 'px';
    sc.style.width = dim[0] + 'px'; sc.style.height = dim[1] + 'px'; sc.style.transform = 'scale(' + s + ')';
  }
  function setScreen(sc) {
    if (sc === 'full' && layoutKind() === 'ph') sc = 'main';
    var was = T.screen; T.screen = sc;
    if (sc === 'full' && was !== 'full') enterFs(); if (was === 'full' && sc !== 'full') exitFs();
    render();
  }
  function enterFs() { try { if (!document.fullscreenElement && root.requestFullscreen) root.requestFullscreen().catch(function () {}); } catch (e) {} }
  function exitFs() { try { if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {}); } catch (e) {} root.classList.remove('idle'); }
  function wake() { root.classList.remove('idle'); clearTimeout(T.idleT); if (T.screen === 'full') T.idleT = setTimeout(function () { if (T.screen === 'full') root.classList.add('idle'); }, 4500); }

  /* ---- controls ---- */
  function sendBright(v) { v = Math.max(1, Math.min(100, Math.round(v))); T.ov.bright = { v: v, until: performance.now() + 1500 }; clearTimeout(T.bT); T.bT = setTimeout(function () { api('/api/brightness', { value: v }); }, 90); paint(); }
  function bindKnob(kn) {
    var drag = false, y0 = 0, v0 = 0;
    kn.addEventListener('pointerdown', function (e) { drag = true; y0 = e.clientY; v0 = T.ov.bright ? T.ov.bright.v : T.s.brightness; kn.setPointerCapture(e.pointerId); });
    kn.addEventListener('pointermove', function (e) { if (drag) sendBright(Math.max(5, v0 + (y0 - e.clientY) * 0.8)); });
    kn.addEventListener('pointerup', function () { drag = false; });
  }
  var SETEP = { vib: function (v) { return ['/api/vibrancy', { value: v / 100 }]; }, dark: function (v) { return ['/api/dark_boost', { value: v / 100 }]; }, cycle: function (v) { return ['/api/flow_speed', { speed: v }]; },
    fade: function (v) { return ['/api/trans_speed', { speed: v }]; }, depth: function (v) { return ['/api/pulse_depth', { depth: v / 100 }]; }, vol: function (v) { return ['/api/playback/volume', { value: v }]; } };
  function setNum(k, v) {
    v = Math.round(v); T.ov[k] = { v: v, until: performance.now() + 1500 }; clearTimeout(T['t_' + k]);
    T['t_' + k] = setTimeout(function () { var e = SETEP[k](v); api(e[0], e[1]); }, 110); paint();
  }
  function setToggle(k) {
    var v = !cur(k); T.ov[k] = { v: v, until: performance.now() + 1500 };
    if (k === 'white') api('/api/white_accent', { enabled: v }); else if (k === 'shuffle') api('/api/playback/shuffle', { on: v }); else if (k === 'repeat') api('/api/playback/repeat', { on: v });
    paint();
  }
  function setSeg(k, v) {
    if (k === 'theme') { Themes.set(v); return; }
    T.ov[k] = { v: v, until: performance.now() + 1500 };
    if (k === 'fsm') api('/api/fs_motion', { value: +v }); else if (k === 'preview') api('/api/preview_mode', { mode: v });
    paint();
  }
  function seekTo(sec) { var s = T.s; if (!s) return; sec = Math.max(0, sec); T.basePos = sec; T.tState = performance.now(); api('/api/playback/seek', { pos: sec }); secTick(); }
  function loadPair() { fetch('/api/pairing').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { if (d) { T.pair = d.open ? '' : d.url; q('[data-pairlink]').forEach(function (i) { i.value = T.pair || 'Pairing is switched off on this Mac'; }); } }).catch(function () {}); }
  function msg(t) { q('[data-b="devmsg"]').forEach(function (e) { e.textContent = t || ''; }); }
  function act(name, el) {
    var s = T.s;
    switch (name) {
      case 'swap': api('/api/swap_lr'); break; case 'flip': api('/api/invert_tb'); break; case 'rescan': api('/api/rescan'); break;
      case 'blinkL': api('/api/lamps/identify', { side: 'left' }); break; case 'blinkR': api('/api/lamps/identify', { side: 'right' }); break;
      case 'auto': api('/api/bpm_auto'); break;
      case 'tap': {
        var now = performance.now(); if (T.taps.length && now - T.taps[T.taps.length - 1] > 2500) T.taps = [];
        T.taps.push(now); if (T.taps.length > 8) T.taps.shift();
        if (T.taps.length >= 2) { var sum = 0, i; for (i = 1; i < T.taps.length; i++) sum += T.taps[i] - T.taps[i - 1]; api('/api/bpm', { bpm: Math.round(60000 / (sum / (T.taps.length - 1)) * 10) / 10, tap: true }); }
        break; }
      case 'scandev': msg(''); api('/api/devices/scan'); break;
      case 'adddev': {
        msg(''); var kind = (document.getElementById('tdKind') || {}).value, ip = ((document.getElementById('tdIp') || {}).value || '').trim(), side = (document.getElementById('tdSide') || {}).value;
        fetch('/api/devices/add', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Govee-App': '1' }, body: JSON.stringify({ kind: kind, ip: ip, side: side }) })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).then(function (o) { if (!o.ok) msg(o.j.error || 'Could not add that light'); else document.getElementById('tdIp').value = ''; }).catch(function () { msg('Could not reach the server'); });
        break; }
      case 'adddisc': api('/api/devices/add', { kind: el.getAttribute('data-kind'), ip: el.getAttribute('data-ip'), side: 'left' }); break;
      case 'rmdev': api('/api/devices/remove', { ip: el.getAttribute('data-ip') }); break;
      case 'copylink': { var inp = root.querySelector('[data-pairlink]'); if (inp) { inp.select(); try { if (navigator.clipboard) navigator.clipboard.writeText(inp.value); else document.execCommand('copy'); } catch (e) { try { document.execCommand('copy'); } catch (e2) {} } } break; }
      case 'shutdown':
        if (!T.confirm) { T.confirm = true; paint(); setTimeout(function () { T.confirm = false; paint(); }, 4000); }
        else { api('/api/shutdown', { lamps_off: false }); T.confirm = false; }
        break;
    }
  }

  root.addEventListener('click', function (e) {
    var t = e.target.closest('[data-open],[data-mode],[data-toggle],[data-play],[data-step],[data-power],[data-bright],[data-bar],[data-lyrics],[data-st],[data-sdv],[data-sb],[data-segv],[data-act],[data-seek],[data-swv],[data-lt]');
    if (!t || !T.s) return;
    var s = T.s;
    if (t.hasAttribute('data-open')) { var o = t.getAttribute('data-open'); setScreen(o === 'back' || o === 'main' ? 'main' : o); return; }
    if (t.hasAttribute('data-mode')) api('/api/preset', { preset: MODE_PRESET[t.getAttribute('data-mode')] });
    else if (t.hasAttribute('data-toggle')) { var k = t.getAttribute('data-toggle'); if (k === 'pulse') api('/api/pulse', { enabled: !s.music_pulse }); else api('/api/dynamic_intensity', { enabled: !s.dynamic_intensity }); }
    else if (t.hasAttribute('data-play')) api('/api/playback/playpause');
    else if (t.hasAttribute('data-step')) api(+t.getAttribute('data-step') > 0 ? '/api/playback/next' : '/api/playback/prev');
    else if (t.hasAttribute('data-power')) api('/api/power', { on: !s.is_powered_on });
    else if (t.hasAttribute('data-bright')) sendBright(+t.getAttribute('data-bright'));
    else if (t.hasAttribute('data-bar')) { var rc = t.getBoundingClientRect(); sendBright(Math.max(5, ((e.clientX - rc.left) / rc.width) * 100)); }
    else if (t.hasAttribute('data-lyrics')) { T.lyrics = !T.lyrics; T.lastLy = ''; render(); wake(); }
    else if (t.hasAttribute('data-st')) setToggle(t.getAttribute('data-st'));
    else if (t.hasAttribute('data-sdv')) setNum(t.getAttribute('data-sdk'), +t.getAttribute('data-sdv'));
    else if (t.hasAttribute('data-sb')) { var key = t.getAttribute('data-sb'), rg = RANGE[key], r2 = t.getBoundingClientRect(); setNum(key, rg[0] + (rg[1] - rg[0]) * Math.max(0, Math.min(1, (e.clientX - r2.left) / r2.width))); }
    else if (t.hasAttribute('data-segv')) setSeg(t.getAttribute('data-segk'), t.getAttribute('data-segv'));
    else if (t.hasAttribute('data-act')) act(t.getAttribute('data-act'), t);
    else if (t.hasAttribute('data-seek')) { var r3 = t.getBoundingClientRect(); seekTo(Math.max(0, Math.min(1, (e.clientX - r3.left) / r3.width)) * (s.track_dur || 0)); }
    else if (t.hasAttribute('data-swv')) api('/api/swatch', { index: +t.getAttribute('data-swv') });
    else if (t.hasAttribute('data-lt')) seekTo(+t.getAttribute('data-lt') - 0.1);
  });
  root.addEventListener('input', function (e) {
    var t = e.target;
    if (t.hasAttribute('data-range')) sendBright(+t.value);
    else if (t.hasAttribute('data-sl')) setNum(t.getAttribute('data-sl'), +t.value);
  });
  ['pointermove', 'pointerdown', 'keydown', 'touchstart'].forEach(function (ev) { root.addEventListener(ev, function () { if (T.screen === 'full') wake(); }, { passive: true }); });
  document.addEventListener('keydown', function (e) {
    if (!T.theme || T.theme === 'classic' || root.hidden) return;
    var tag = (e.target && e.target.tagName) || '';
    if (/INPUT|SELECT|TEXTAREA/.test(tag)) return;
    if (e.key === 'Escape' && T.screen !== 'main') { setScreen('main'); e.preventDefault(); }
    else if ((e.key === 'l' || e.key === 'L') && T.screen === 'full') { T.lyrics = !T.lyrics; T.lastLy = ''; render(); }
  });
  document.addEventListener('fullscreenchange', function () { if (!document.fullscreenElement && T.screen === 'full') { T.screen = 'main'; render(); } });
  window.addEventListener('resize', function () { clearTimeout(T.rzT); T.rzT = setTimeout(function () { if (root.hidden) return; var k = layoutKind(); if (k !== T.kind) render(); else fit(); }, 80); });
  document.addEventListener('visibilitychange', function () {
    if (!T.theme || T.theme === 'classic') return;
    if (document.hidden) { if (T.anim) { clearInterval(T.anim); T.anim = null; T.animKey = ''; } if (T.sec) { clearInterval(T.sec); T.sec = null; } }
    else { startSec(); render(); }
  });
  function startSec() { if (!T.sec && T.theme && T.theme !== 'classic' && !document.hidden) T.sec = setInterval(secTick, 1000); }

  /* ---- public ---- */
  function applyClass() {
    var on = !!T.theme && T.theme !== 'classic';
    document.body.classList.toggle('theme-on', on); root.hidden = !on;
    if (!on) { if (T.anim) { clearInterval(T.anim); T.anim = null; T.animKey = ''; } if (T.sec) { clearInterval(T.sec); T.sec = null; } root.innerHTML = ''; T.built = ''; T.el = null; }
  }
  var Themes = {
    active: function () { return !!T.theme && T.theme !== 'classic'; },
    current: function () { return T.theme || 'classic'; },
    onState: function (s) {
      T.s = s; T.tState = performance.now(); T.basePos = s.player_pos || 0;
      if (T.theme == null) {
        var forced = null; try { forced = new URLSearchParams(location.search).get('theme'); } catch (e) {}
        T.theme = (forced && THEMES.indexOf(forced) >= 0) ? forced : ((LS && LS.getItem('glowtrack.theme')) || s.default_theme || 'classic');
        if (THEMES.indexOf(T.theme) < 0) T.theme = 'classic';
      }
      applyClass();
      if (!Themes.active()) return false;
      if (document.hidden) return true;
      startSec(); render(); return true;
    },
    set: function (name) {
      if (THEMES.indexOf(name) < 0) return;
      T.theme = name; try { if (LS) LS.setItem('glowtrack.theme', name); } catch (e) {}
      T.screen = 'main'; T.built = ''; exitFs(); applyClass();
      if (name === 'classic') { if (typeof updateUI === 'function' && T.s) updateUI(T.s); }
      else { startSec(); render(); }
    }
  };
  window.Themes = Themes;
})();
