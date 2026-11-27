// Glowtrack dashboard
// Every command carries this header; the server rejects commands without it,
// which stops other websites from controlling the lamps.
const _rawFetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => {
  opts.headers = Object.assign({ 'Content-Type': 'application/json', 'X-Govee-App': '1' }, opts.headers || {});
  return _rawFetch(url, opts);
};

let currentState = {};
let bDebounce = null;
let lastSwatchSig = '';
const settingTimers = {};
const settingHoldUntil = {};
let isUserScrubbing = false;
let baseServerPos = 0.0;
let lastSyncPerfTime = performance.now() / 1000;
let lastTrackSig = '';

function hexToRgba(hex, alpha = 1) {
  if (!hex || hex[0] !== '#') return `rgba(99, 102, 241, ${alpha})`;
  let c = hex.substring(1);
  if (c.length === 3) c = c.split('').map(x => x + x).join('');
  const num = parseInt(c, 16);
  if (isNaN(num)) return `rgba(99, 102, 241, ${alpha})`;
  return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
}

function getContrastColor(hex) {
  if (!hex || hex[0] !== '#') return '#000000';
  let c = hex.substring(1);
  if (c.length === 3) c = c.split('').map(x => x + x).join('');
  const num = parseInt(c, 16);
  if (isNaN(num)) return '#000000';
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  const yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
  return (yiq >= 140) ? '#000000' : '#FFFFFF';
}

function toggleSettingsModal(show) {
  const modal = document.getElementById('settingsModal');
  const card = document.getElementById('settingsModalCard');
  if (!modal || !card) return;
  if (show) {
    modal.classList.remove('pointer-events-none', 'opacity-0');
    modal.classList.add('opacity-100');
    card.classList.remove('scale-95');
    card.classList.add('scale-100');
  } else {
    modal.classList.add('opacity-0', 'pointer-events-none');
    modal.classList.remove('opacity-100');
    card.classList.remove('scale-100');
    card.classList.add('scale-95');
  }
}

window.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const m = document.getElementById('settingsModal');
  if (m && !m.classList.contains('pointer-events-none')) {
    // Esc closes Settings only - full screen stays open underneath
    toggleSettingsModal(false);
    e.stopImmediatePropagation();
  }
});

let isDocVisible = !document.hidden;
document.addEventListener('visibilitychange', () => {
  isDocVisible = !document.hidden;
  // Hidden (minimised, covered, other tab): disconnect completely so neither
  // this page nor the server does any work for it. Reconnect when visible.
  if (isDocVisible) {
    if (!window._serverStopped) connectEvents();
  } else if (evtSource) {
    evtSource.close();
    evtSource = null;
  }
});


// Live updates from the server (full state ~1/sec + tiny lamp-colour frames)
let evtSource = null;
function connectEvents() {
  if (evtSource) return;
  evtSource = new EventSource('/api/events');
  evtSource.onmessage = (e) => {
    const state = JSON.parse(e.data);
    // Dashboard files were updated: reload to pick up the new version
    if (window._webVersion && state.web_version && state.web_version !== window._webVersion) {
      location.reload();
      return;
    }
    window._webVersion = window._webVersion || state.web_version;
    currentState = state;
    const themed = window.Themes && Themes.onState(state);
    if (!themed && isDocVisible) updateUI(state);
    if (!window._fittedOnce) { window._fittedOnce = true; scheduleFit(); }
  };
}

// Only touches the DOM when a value actually changes (keeps CPU low)
function setIf(el, prop, val) {
  if (!el) return;
  el._c = el._c || {};
  if (el._c[prop] === val) return;
  el._c[prop] = val;
  el.style[prop] = val;
}
function textIf(el, val) {
  if (el && el.textContent !== val) el.textContent = val;
}
function htmlIf(el, val) {
  if (!el) return;
  if (el._html === val) return;
  el._html = val;
  el.innerHTML = val;
}

let lastAccent = '';
let lastPlaying = false;
let lastDur = 0;

// The progress bar is handed to the browser as one long, linear animation to
// the end of the song - perfectly smooth, and almost free for the CPU.
function anchorProgress() {
  if (isUserScrubbing) return;
  const dur = currentState.track_dur || 0;
  const pos = Math.max(0, Math.min(dur, baseServerPos + (lastPlaying ? (performance.now() / 1000 - lastSyncPerfTime) : 0)));
  // Same animation drives the dashboard bar and the full-screen bar
  for (const bar of [document.getElementById('trackProgressBar'), document.getElementById('fsProgressBar')]) {
    if (!bar) continue;
    if (dur <= 0) { bar.style.transition = 'none'; bar.style.transform = 'scaleX(0)'; continue; }
    bar.style.transition = 'none';
    bar.style.transform = `scaleX(${(pos / dur).toFixed(5)})`;
    if (lastPlaying && pos < dur) {
      void bar.offsetWidth;   // commit the start point before animating
      bar.style.transition = `transform ${(dur - pos).toFixed(2)}s linear`;
      bar.style.transform = 'scaleX(1)';
    }
  }
}
let lastArtSig = '';

function updateUI(s) {
  // Page accent comes from the album palette (not the moving lamp frame),
  // so the whole page isn't repainted 3x a second while colours flow.
  const pal = s.palette_lamp || [];
  const lockIdx = (s.locked_swatch_index === null || s.locked_swatch_index === undefined) ? 0 : s.locked_swatch_index;
  const mainColor = ((pal[lockIdx] || pal[0] || s.hex1 || '#6366F1') + '').toUpperCase();
  const contrastText = getContrastColor(mainColor);
  if (mainColor !== lastAccent) {
    lastAccent = mainColor;
    const root = document.documentElement.style;
    root.setProperty('--theme-accent', mainColor);
    root.setProperty('--theme-accent-glow', hexToRgba(mainColor, 0.45));
    root.setProperty('--theme-accent-bg', hexToRgba(mainColor, 0.16));
    root.setProperty('--theme-accent-border', hexToRgba(mainColor, 0.42));
    root.setProperty('--theme-accent-text', contrastText);
    const bloom = document.getElementById('ambientBloom');
    if (bloom) bloom.style.backgroundColor = mainColor;
    const artHexBadge = document.getElementById('artHexBadge');
    if (artHexBadge) {
      artHexBadge.innerHTML = `<span class="w-2 h-2 rounded-full" style="background-color: ${mainColor}"></span><span>${mainColor}</span>`;
    }
  }

  // Header status
  const badgeText = document.getElementById('statusBadgeText');
  const total = s.configured_count || 0;
  let badgeHtml, badgeCls, badgeTitle = '';
  if (!s.status_known) {
    badgeHtml = s.status_error
      ? `<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"></span> Lamp status unavailable`
      : `<span class="inline-block w-1.5 h-1.5 rounded-full bg-slate-400"></span> Checking lamps…`;
    badgeTitle = s.status_error || '';
    badgeCls = 'text-xs text-amber-300 mt-0.5 font-medium flex items-center gap-1.5';
  } else if (s.online_count > 0) {
    const label = (s.online_count === total) ? `${total} Govee Lamps Online` : `${s.online_count} of ${total} Lamps Online`;
    badgeHtml = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400"></span> ${label}`;
    badgeCls = 'text-xs text-slate-400 mt-0.5 font-medium flex items-center gap-1.5';
  } else {
    badgeHtml = `<span class="inline-block w-1.5 h-1.5 rounded-full bg-red-500"></span> Lamps Not Responding`;
    badgeTitle = 'No reply from the lamps. Are you on the same Wi-Fi?';
    badgeCls = 'text-xs text-red-400 mt-0.5 font-medium flex items-center gap-1.5';
  }
  htmlIf(badgeText, badgeHtml);
  if (badgeText.className !== badgeCls) badgeText.className = badgeCls;
  badgeText.title = badgeTitle;

  // Track metadata
  const titleEl = document.getElementById('trackTitle');
  textIf(titleEl, s.track || 'Waiting for Spotify...');
  titleEl.title = s.track || 'Waiting for Spotify...';
  textIf(document.getElementById('trackArtist'), s.artist || '');
  textIf(document.getElementById('trackBpmText'), `${Math.round(parseFloat(s.current_bpm || 120.0))} BPM`);

  // Music Playback Controls & Timeline State
  updatePlayPauseButton(!!s.is_playing);
  currentState.is_playing = !!s.is_playing;
  currentState.track_dur = s.track_dur || 0;
  textIf(document.getElementById('trackTimeTotal'), formatTime(s.track_dur || 0));

  if (!isUserScrubbing) {
    const trackSig = (s.track || '') + (s.artist || '');
    const nowSec = performance.now() / 1000;
    const currentEst = baseServerPos + (lastPlaying ? (nowSec - lastSyncPerfTime) : 0);
    const drift = Math.abs(currentEst - (s.player_pos || 0));
    const changed = (lastTrackSig !== trackSig) || (lastPlaying !== !!s.is_playing) || (lastDur !== (s.track_dur || 0));
    // Small differences are just timing noise - re-anchoring on them made the bar stutter
    if (changed || drift > 0.4) {
      lastTrackSig = trackSig;
      lastPlaying = !!s.is_playing;
      lastDur = s.track_dur || 0;
      baseServerPos = s.player_pos || 0;
      lastSyncPerfTime = nowSec;
      anchorProgress();
    }
  }

  // Album art card (only redrawn when the song / art / accent changes)
  const artSig = [s.art_url, s.is_ad, mainColor, pal.join(',')].join('|');
  if (artSig !== lastArtSig) {
    lastArtSig = artSig;
    const artCard = document.getElementById('artCoverCard');
    const artAura = document.getElementById('artAmbientAura');
    const artPlaceholderText = document.getElementById('artCoverPlaceholderText');
    const artPlaceholderSub = document.getElementById('artCoverPlaceholderSub');
    const img = document.getElementById('artImg');
    const c2 = (pal[1] || mainColor).toUpperCase();
    if (artCard) {
      artCard.style.background = `linear-gradient(135deg, ${mainColor} 0%, ${c2} 100%)`;
      artCard.style.boxShadow = `0 16px 40px ${hexToRgba(mainColor, 0.45)}, 0 0 0 1px rgba(255,255,255,0.15)`;
    }
    if (s.art_url && !s.is_ad) {
      img.onload = () => { img.style.opacity = '1'; if (artAura) artAura.style.opacity = '0'; };
      img.onerror = () => { img.style.opacity = '0'; if (artAura) artAura.style.opacity = '1'; };
      if (img.src !== s.art_url) img.src = s.art_url;
      if (img.complete && img.naturalHeight > 0) { img.style.opacity = '1'; if (artAura) artAura.style.opacity = '0'; }
    } else {
      img.style.opacity = '0';
      if (artAura) artAura.style.opacity = '1';
      if (artPlaceholderText) artPlaceholderText.textContent = s.is_ad ? 'Sponsored Ad Break' : 'Room Light Sync';
      if (artPlaceholderSub) artPlaceholderSub.textContent = s.is_ad ? 'Lamps are white during the ad' : `${mainColor} • ${c2}`;
    }
  }


  // Swap L/R and Invert T/B button states (toolbar and settings)
  const btnInvert = document.getElementById('btnInvertTB');
  const btnModalInvert = document.getElementById('btnModalInvertTB');
  [document.getElementById('btnSwapLR'), document.getElementById('btnModalSwapLR')].forEach(btn => {
    setIf(btn, 'backgroundColor', s.is_swapped_lr ? '#FFFFFF' : '');
    setIf(btn, 'color', s.is_swapped_lr ? '#0B0E14' : '');
  });
  [btnInvert, btnModalInvert].forEach(btn => {
    setIf(btn, 'backgroundColor', s.is_inverted_tb ? '#FFFFFF' : '');
    setIf(btn, 'color', s.is_inverted_tb ? '#0B0E14' : '');
  });

  renderLamps(s);

  // Populate and sync Floor Lamp Side assignment dropdowns
  const allIps = (s.available_ips && s.available_ips.length > 0) ? s.available_ips : (s.lamp_ips || []);
  const selLeft = document.getElementById('selectLampLeft');
  const selRight = document.getElementById('selectLampRight');

  function syncSelect(sel, currentIp) {
    if (!sel) return;
    if (document.activeElement === sel) return;   // don't fight the user while the menu is open
    const online = s.lamp_online || {};
    const labelFor = ip => s.status_known ? `${ip}${online[ip] ? '' : '  (offline)'}` : ip;
    const currentOpts = Array.from(sel.options).map(o => o.value + '|' + o.textContent).join(',');
    const targetOpts = allIps.map(ip => ip + '|' + labelFor(ip)).join(',');
    if (currentOpts !== targetOpts) {
      sel.innerHTML = '';
      allIps.forEach(ip => {
        const opt = document.createElement('option');
        opt.value = ip;
        opt.textContent = labelFor(ip);
        sel.appendChild(opt);
      });
    }
    if (currentIp) sel.value = currentIp;
  }

  syncSelect(selLeft, s.left_ip || (allIps[0] || ''));
  syncSelect(selRight, s.right_ip || (allIps[1] || ''));
  renderDevices(s);

  // Presets button active states
  const isSolid = (s.spatial_mode === 'unified' && s.motion_mode === 'static');
  const isWave = (s.spatial_mode === 'unified' && s.motion_mode === 'flow');
  const isDuo = (s.spatial_mode === 'duo');
  const isSeg = (s.spatial_mode === 'segmented');

  setModeBtnState('btnPresetSolid', isSolid);
  setModeBtnState('btnPresetWave', isWave);
  setModeBtnState('btnPresetDuo', isDuo);
  setModeBtnState('btnPresetSeg', isSeg);

  // Palette Swatches with Auto pill & Lock indicator.
  // Only rebuilt when the palette or lock changes - rebuilding 3x a second ate clicks.
  const isAuto = (s.locked_swatch_index === null || s.locked_swatch_index === undefined);
  const swatchSig = JSON.stringify([s.palette_lamp || [], isAuto ? -1 : s.locked_swatch_index]);
  if (swatchSig !== lastSwatchSig) {
    lastSwatchSig = swatchSig;
    const swContainer = document.getElementById('swatchesContainer');
    swContainer.innerHTML = '';

    const autoPill = document.createElement('div');
    autoPill.className = `text-[11px] font-mono px-2.5 py-1 rounded-full cursor-pointer transition select-none flex items-center gap-1.5`;
    if (isAuto) {
      autoPill.style.backgroundColor = 'var(--ctl)';
      autoPill.style.color = 'var(--ctl-text)';
      autoPill.style.border = '1px solid var(--ctl)';
      autoPill.classList.add('font-bold');
    } else {
      autoPill.className += ' bg-white/[0.05] text-slate-400 hover:text-white border border-white/[0.08]';
    }
    autoPill.textContent = isAuto ? '● Auto' : '↺ Auto';
    autoPill.title = isAuto ? 'Automatic: colours follow the album art' : 'Click to unlock and go back to Auto';
    autoPill.onclick = () => setSwatch(-1);
    swContainer.appendChild(autoPill);

    (s.palette_lamp || []).forEach((c, idx) => {
      const dot = document.createElement('div');
      const isSelected = (s.locked_swatch_index === idx);
      dot.className = `swatch-dot ${isSelected ? 'ring-2 ring-white ring-offset-2 ring-offset-[#12151B] scale-125 shadow-xl' : ''}`;
      dot.style.backgroundColor = c;
      dot.title = isSelected ? `Locked to ${c} (click Auto to unlock)` : `Click to lock both lamps to ${c}`;
      dot.onclick = () => setSwatch(idx);
      swContainer.appendChild(dot);
    });
  }

  // Brightness slider
  document.getElementById('bVal').textContent = `${s.brightness}%`;
  setSliderFromServer('bSlider', s.brightness);


  // Fine-tune sliders (skip any the user is dragging right now)
  if (setSliderFromServer('flowSlider', s.flow_speed)) document.getElementById('flowVal').textContent = `${s.flow_speed}s`;
  if (setSliderFromServer('transSlider', s.trans_speed)) document.getElementById('transVal').textContent = `${s.trans_speed}s`;
  if (setSliderFromServer('vibSlider', s.vibrancy)) document.getElementById('vibVal').textContent = `${parseFloat(s.vibrancy).toFixed(2)}×`;
  const depthPct = Math.round((s.pulse_depth || 0.6) * 100);
  if (setSliderFromServer('depthSlider', depthPct)) document.getElementById('depthVal').textContent = `${depthPct}%`;
  const bpmRounded = Math.round(parseFloat(s.current_bpm || 120));
  if (setSliderFromServer('bpmSlider', bpmRounded)) document.getElementById('bpmVal').textContent = `${bpmRounded}`;
  const srcEl = document.getElementById('bpmSourceText');
  if (srcEl) {
    const detected = Math.round(parseFloat(s.detected_bpm || 120));
    srcEl.textContent = s.bpm_manual
      ? `Tempo source: ${s.bpm_source} (song's own tempo: ${detected} BPM, click Auto to use it)`
      : (s.bpm_known === false ? 'No tempo found for this song: the pulse is paused. Tap along to set one.' : `Tempo source: ${s.bpm_source || 'Default'}`);
  }

  // White accents switch (Settings)
  const wa = document.getElementById('whiteAccentCheck');
  if (wa && document.activeElement !== wa) wa.checked = s.white_accent !== false;

  // Full-screen background motion (Settings)
  const fsm = (s.fs_motion === undefined) ? 1 : s.fs_motion;
  if (setSliderFromServer('fsMotionSlider', fsm)) textIf(document.getElementById('fsMotionVal'), FS_MOTION_NAMES[fsm]);
  applyFsMotion(fsm);

  // Dark colour boost + preview mode (Settings)
  const darkPct = Math.round((s.dark_boost === undefined ? 0.65 : s.dark_boost) * 100);
  if (setSliderFromServer('darkSlider', darkPct)) textIf(document.getElementById('darkVal'), `${darkPct}%`);
  [['btnPrevSmooth', 'smooth'], ['btnPrevLow', 'low'], ['btnPrevOff', 'off']].forEach(([id, mode]) => {
    const b = document.getElementById(id);
    const active = ((s.preview_mode || 'smooth') === mode);
    setIf(b, 'backgroundColor', active ? '#FFFFFF' : '');
    setIf(b, 'color', active ? '#0B0E14' : '');
  });

  // Invert only means something for the 7-zone gradient
  [btnInvert, btnModalInvert].forEach(btn => {
    if (!btn) return;
    const usable = (s.spatial_mode === 'segmented');
    btn.style.opacity = usable ? '' : '0.45';
    btn.title = usable ? 'Flip the 7-zone gradient upside down' : 'Only affects 7-Zone mode';
  });

  // Pulse & Dynamic Intensity checkboxes
  document.getElementById('pulseCheck').checked = !!s.music_pulse;
  document.getElementById('intensityCheck').checked = !!s.dynamic_intensity;
  const intBadge = document.getElementById('intensityBadge');
  if (s.dynamic_intensity && s.intensity_section) {
    intBadge.textContent = `${s.intensity_section} • ${Math.round(s.intensity_factor * 100)}%`;
    intBadge.classList.remove('hidden');
  } else {
    intBadge.classList.add('hidden');
  }

  // Power buttons with dynamic color
  const btnOn = document.getElementById('btnPowerOn');
  const btnOff = document.getElementById('btnPowerOff');
  if (s.is_powered_on) {
    btnOn.className = 'px-3 py-1 text-xs font-bold rounded-lg transition shadow-sm hover:brightness-110 active:scale-95';
    btnOn.style.backgroundColor = '#FFFFFF';
    btnOn.style.color = '#0B0E14';
    btnOff.className = 'px-3 py-1 text-xs font-medium rounded-lg text-slate-400 hover:text-white transition active:scale-95';
    btnOff.style.backgroundColor = '';
    btnOff.style.color = '';
  } else {
    btnOn.className = 'px-3 py-1 text-xs font-medium rounded-lg text-slate-400 hover:text-white transition active:scale-95';
    btnOn.style.backgroundColor = '';
    btnOn.style.color = '';
    btnOff.className = 'px-3 py-1 text-xs font-bold rounded-lg bg-red-600 text-white transition shadow-sm hover:bg-red-500 active:scale-95';
    btnOff.style.backgroundColor = '';
    btnOff.style.color = '';
  }

  // Play/Pause button dynamic styling
  const btnPP = document.getElementById('btnPlayPause');
  if (btnPP) {
    btnPP.style.backgroundColor = '#FFFFFF';
    btnPP.style.color = '#0B0E14';
    btnPP.style.boxShadow = '0 8px 24px rgba(0, 0, 0, 0.45)';
  }
}

// ---------------------------------------------------------------
// Lamp preview.
// Still modes: the 7 zone blocks are coloured from the server's state.
// Moving modes: the server describes the colour loop once (colours, speed,
// position) and each lamp shows a colour strip sliding through it as a single
// CSS animation. That runs on the graphics chip at full frame rate - perfectly
// smooth, and almost no CPU - and stays in step with the real lamps.
// ---------------------------------------------------------------
const OFF_SEG = '#15171C';
let isLampIdentifying = false;
const flowState = { 1: null, 2: null };   // current strip per lamp (+ its settings key)

function flowGradient(stops, space) {
  return `linear-gradient(to top${space}, ${stops.map(([p, c]) => `${c} ${(p * 100).toFixed(2)}%`).join(', ')})`;
}

// Builds (or keeps) the sliding strip inside `host` for one lamp.
function setFlowStrip(n, host, flow, phaseOffset, kind) {
  const H = host.clientHeight || 216;
  // span = how much of the loop the lamp shows top-to-bottom (0 = one solid colour)
  const C = flow.span > 0 ? H / flow.span : H * 40;     // pixels per full loop
  const key = JSON.stringify([flow.stops, flow.cycle, flow.span, flow.inverted, phaseOffset, H, kind]);
  const slot = `${kind}${n}`;
  const current = flowState[slot];
  if (current && current.key === key) return;            // already running

  const phase = (((flow.phase + phaseOffset) % 1) + 1) % 1;
  const wrap = document.createElement('div');
  wrap.className = 'flow-wrap';
  if (flow.inverted) wrap.style.transform = 'scaleY(-1)';
  const strip = document.createElement('div');
  strip.className = 'flow-strip';
  strip.style.height = `${H + C + 2}px`;
  strip.style.backgroundImage = flowGradient(flow.stops, '');            // works everywhere
  strip.style.backgroundImage = flowGradient(flow.stops, ' in oklab');   // nicer blends where supported
  strip.style.backgroundSize = `100% ${C}px`;
  strip.style.setProperty('--loop', `${C}px`);
  strip.style.animationDuration = `${flow.cycle}s`;
  strip.style.animationDelay = `${(-phase * flow.cycle).toFixed(3)}s`;
  wrap.appendChild(strip);

  // Fade in over the old strip (song change), then drop the old one
  const fadeSec = current ? Math.max(0.3, flow.fade || 1) : 0;
  wrap.style.opacity = current ? '0' : '1';
  host.appendChild(wrap);
  if (current) {
    void wrap.offsetWidth;
    wrap.style.transition = `opacity ${fadeSec}s linear`;
    wrap.style.opacity = '1';
    const old = current.el;
    setTimeout(() => old.remove(), fadeSec * 1000 + 50);
  }
  flowState[slot] = { key, el: wrap };
}

function clearFlowStrips() {
  for (const slot of Object.keys(flowState)) {
    if (flowState[slot]) { flowState[slot].el.remove(); flowState[slot] = null; }
  }
}

// Still glow behind a lamp: its 7 zones, bottom to top.
function setGlow(n, segs) {
  const glow = document.getElementById(`glow${n}`);
  setIf(glow, 'backgroundImage', segs ? `linear-gradient(to top, ${segs.join(', ')})` : 'none');
  setIf(document.getElementById(`puddle${n}`), 'backgroundColor', segs ? segs[0] : 'transparent');
}

function renderLamps(s) {
  const mode = s.preview_mode || 'smooth';
  const arena = document.getElementById('lampsArena');
  const statusText = document.getElementById('lampStatusText');
  isLampIdentifying = !!s.identifying_ip;
  arena.classList.toggle('preview-lite', mode !== 'smooth');
  const segMs = 350;
  if (arena._segMs !== segMs) { arena._segMs = segMs; arena.style.setProperty('--seg-ms', `${segMs}ms`); }

  let left, right;
  if (!s.is_powered_on) {
    left = right = Array(7).fill(OFF_SEG);
  } else {
    left = (s.seg_colors && s.seg_colors.length === 7) ? s.seg_colors : Array(7).fill(s.hex1 || OFF_SEG);
    right = (s.seg_colors_right && s.seg_colors_right.length === 7) ? s.seg_colors_right : left;
  }

  const animate = s.flow && mode !== 'off' && !s.identifying_ip;
  arena.classList.toggle('flow-live', !!animate);
  if (animate) {
    setFlowStrip(1, document.getElementById('pole1'), s.flow, 0, 'pole');
    setFlowStrip(2, document.getElementById('pole2'), s.flow, s.flow.right_offset, 'pole');
    if (mode === 'smooth') {
      setIf(document.getElementById('glow1'), 'backgroundImage', 'none');
      setIf(document.getElementById('glow2'), 'backgroundImage', 'none');
      setFlowStrip(1, document.getElementById('glow1'), s.flow, 0, 'glow');
      setFlowStrip(2, document.getElementById('glow2'), s.flow, s.flow.right_offset, 'glow');
    }
    setIf(document.getElementById('puddle1'), 'backgroundColor', left[0]);
    setIf(document.getElementById('puddle2'), 'backgroundColor', right[0]);
  } else {
    clearFlowStrips();
    for (let i = 0; i < 7; i++) {
      setIf(document.getElementById(`p1-s${i}`), 'backgroundColor', left[i]);
      setIf(document.getElementById(`p2-s${i}`), 'backgroundColor', right[i]);
    }
    setGlow(1, s.is_powered_on ? left : null);
    setGlow(2, s.is_powered_on ? right : null);
  }

  // Identify blink feedback
  if (s.identifying_ip) {
    if (s.identifying_ip === s.left_ip) setGlow(1, Array(7).fill('#00FFFF'));
    if (s.identifying_ip === s.right_ip) setGlow(2, Array(7).fill('#00FFFF'));
  }

  // Beat pulse animation (transform only - no filters)
  const pulseOn = s.is_powered_on && s.music_pulse && mode === 'smooth';
  arena.classList.toggle('pulse-active', !!pulseOn);
  if (pulseOn) {
    const bpm = Math.max(40.0, Math.min(240.0, parseFloat(s.current_bpm || 120.0)));
    arena.style.setProperty('--beat-duration', `${(60.0 / bpm).toFixed(3)}s`);
  }

  // Labels
  const b1 = document.getElementById('badgeHex1');
  const b2 = document.getElementById('badgeHex2');
  const dot = c => `<span class="inline-block w-2 h-2 rounded-full mr-1 align-middle" style="background:${c}"></span>`;
  let status;
  if (!s.is_powered_on) {
    status = 'POWERED OFF';
    htmlIf(b1, 'Off'); htmlIf(b2, 'Off');
  } else if (s.spatial_mode === 'segmented') {
    status = `7-Zone Pole Gradient • ${s.brightness}%`;
    htmlIf(b1, `${dot(left[6])}Top: ${left[6]}`);
    htmlIf(b2, `${dot(right[0])}Base: ${right[0]}`);
  } else if (s.spatial_mode === 'duo') {
    status = `Two-Lamp Split • ${s.brightness}%`;
    htmlIf(b1, `${dot(left[0])}${left[0]}`);
    htmlIf(b2, `${dot(right[0])}${right[0]}`);
  } else {
    status = (s.motion_mode === 'static' ? 'Solid' : 'Colour Fade') + ` • ${s.brightness}%`;
    htmlIf(b1, `${dot(left[0])}${left[0]}`);
    htmlIf(b2, `${dot(right[0])}${right[0]}`);
  }
  if (mode === 'off' && s.is_powered_on) status += ' • preview paused';
  textIf(statusText, status);
}

function setModeBtnState(btnId, isActive) {
  const el = document.getElementById(btnId);
  if (!el) return;
  if (isActive) {
    el.className = 'p-3.5 rounded-2xl border flex flex-col items-start gap-1.5 cursor-pointer transition select-none mode-card mode-btn-active';
  } else {
    el.className = 'p-3.5 rounded-2xl border flex flex-col items-start gap-1.5 cursor-pointer transition select-none mode-card mode-btn-inactive';
  }
}

function applyPreset(p) {
  fetch('/api/preset', { method: 'POST', body: JSON.stringify({ preset: p }) });
}

// Updates a slider from the server unless the user touched it in the last moment.
// Returns true if it was updated (so the caller can refresh its label).
function setSliderFromServer(id, value) {
  const el = document.getElementById(id);
  if (!el || value === undefined || value === null) return false;
  if (document.activeElement === el) return false;
  if ((settingHoldUntil[id] || 0) > performance.now()) return false;
  el.value = value;
  return true;
}

function onSetting(labelId, text) {
  const el = document.getElementById(labelId);
  if (el) el.textContent = text;
}

// Debounced POST for sliders, so dragging doesn't flood the server
function sendSetting(path, body, delay = 80) {
  const slider = document.activeElement;
  if (slider && slider.id) settingHoldUntil[slider.id] = performance.now() + 1200;
  clearTimeout(settingTimers[path]);
  settingTimers[path] = setTimeout(() => {
    fetch(path, { method: 'POST', body: JSON.stringify(body) });
  }, delay);
}

function setPreviewMode(mode) {
  fetch('/api/preview_mode', { method: 'POST', body: JSON.stringify({ mode: mode }) });
}


function sendBpmAuto() {
  tapTimes = [];
  fetch('/api/bpm_auto', { method: 'POST' });
}

// Tap Tempo: tap 4+ times along with the beat
let tapTimes = [];
function tapTempo() {
  const now = performance.now();
  if (tapTimes.length && now - tapTimes[tapTimes.length - 1] > 2000) tapTimes = [];
  tapTimes.push(now);
  if (tapTimes.length > 8) tapTimes.shift();
  const btn = document.getElementById('btnTap');
  if (tapTimes.length < 4) {
    if (btn) btn.textContent = `Tap ${tapTimes.length}/4`;
    return;
  }
  const gaps = [];
  for (let i = 1; i < tapTimes.length; i++) gaps.push(tapTimes[i] - tapTimes[i - 1]);
  const avg = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const bpm = Math.max(40, Math.min(240, Math.round(60000 / avg)));
  if (btn) btn.textContent = `${bpm}`;
  settingHoldUntil['bpmSlider'] = performance.now() + 1500;
  const sl = document.getElementById('bpmSlider');
  if (sl) sl.value = bpm;
  onSetting('bpmVal', bpm);
  fetch('/api/bpm', { method: 'POST', body: JSON.stringify({ bpm: bpm, tap: true }) });
  clearTimeout(window._tapResetTimer);
  window._tapResetTimer = setTimeout(() => { if (btn) btn.textContent = 'Tap'; }, 2500);
}

function sendSwapLR() {
  fetch('/api/swap_lr', { method: 'POST' });
}

function sendInvertTB() {
  fetch('/api/invert_tb', { method: 'POST' });
}

function sendBrightness(val) {
  document.getElementById('bVal').textContent = `${val}%`;
  settingHoldUntil['bSlider'] = performance.now() + 1200;
  clearTimeout(bDebounce);
  bDebounce = setTimeout(() => {
    fetch('/api/brightness', { method: 'POST', body: JSON.stringify({ value: parseInt(val) }) });
  }, 40);
}

function togglePulse(checked) {
  fetch('/api/pulse', { method: 'POST', body: JSON.stringify({ enabled: checked }) });
}

function toggleIntensity(checked) {
  fetch('/api/dynamic_intensity', { method: 'POST', body: JSON.stringify({ enabled: checked }) });
}

function sendPower(on) {
  fetch('/api/power', { method: 'POST', body: JSON.stringify({ on: on }) });
}

function sendRescan() {
  fetch('/api/rescan', { method: 'POST' });
}

function setSwatch(idx) {
  fetch('/api/swatch', { method: 'POST', body: JSON.stringify({ index: idx }) });
}

function sendPlayback(action) {
  if (action === 'playpause') {
    const nextState = !currentState.is_playing;
    baseServerPos = baseServerPos + (lastPlaying ? (performance.now() / 1000 - lastSyncPerfTime) : 0);
    lastSyncPerfTime = performance.now() / 1000;
    currentState.is_playing = nextState;
    lastPlaying = nextState;
    anchorProgress();
    updatePlayPauseButton(nextState);
    fetch('/api/playback/playpause', { method: 'POST' });
  } else if (action === 'next') {
    fetch('/api/playback/next', { method: 'POST' });
  } else if (action === 'prev') {
    fetch('/api/playback/prev', { method: 'POST' });
  }
}

function onAssignLamp(side, ip) {
  fetch('/api/lamps/assign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ side: side, ip: ip })
  }).then(() => {
    if (side === 'left') currentState.left_ip = ip;
    if (side === 'right') currentState.right_ip = ip;
  });
}

function onIdentifyLamp(side) {
  const btn = event.currentTarget;
  if (btn) {
    btn.classList.add('ring-2', 'ring-cyan-400', 'text-cyan-300', 'border-cyan-400');
    setTimeout(() => btn.classList.remove('ring-2', 'ring-cyan-400', 'text-cyan-300', 'border-cyan-400'), 1500);
  }
  fetch('/api/lamps/identify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ side: side })
  });
}

function updatePlayPauseButton(isPlaying) {
  document.body.classList.toggle('is-playing', !!isPlaying);
  const iconPlay = document.getElementById('iconPlay');
  const iconPause = document.getElementById('iconPause');
  if (iconPlay && iconPause) {
    if (isPlaying) {
      iconPlay.classList.add('hidden');
      iconPause.classList.remove('hidden');
    } else {
      iconPlay.classList.remove('hidden');
      iconPause.classList.add('hidden');
    }
  }
}

function formatTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

function getScrubPosFromEvent(e) {
  const container = document.getElementById('trackProgressContainer');
  if (!container || !currentState.track_dur) return 0;
  const rect = container.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  return pct * currentState.track_dur;
}

function updateScrubDisplay(sec) {
  const elBar = document.getElementById('trackProgressBar');
  const elPos = document.getElementById('trackTimeElapsed');
  if (currentState.track_dur > 0) {
    const pct = Math.max(0, Math.min(100, (sec / currentState.track_dur) * 100));
    if (elBar) { elBar.style.transition = 'none'; elBar.style.transform = `scaleX(${(pct / 100).toFixed(5)})`; }
  }
  if (elPos) elPos.textContent = formatTime(sec);
}

function startScrub(e) {
  if (!currentState.track_dur) return;
  isUserScrubbing = true;
  const targetPos = getScrubPosFromEvent(e);
  updateScrubDisplay(targetPos);

  function onMouseMove(ev) {
    if (isUserScrubbing) {
      const p = getScrubPosFromEvent(ev);
      updateScrubDisplay(p);
    }
  }

  function onMouseUp(ev) {
    if (isUserScrubbing) {
      isUserScrubbing = false;
      const finalPos = getScrubPosFromEvent(ev);
      baseServerPos = finalPos;
      lastSyncPerfTime = performance.now() / 1000;
      updateScrubDisplay(finalPos);
      anchorProgress();
      fetch('/api/playback/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pos: finalPos })
      });
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

function getScrubPosFromTouch(e) {
  const container = document.getElementById('trackProgressContainer');
  if (!container || !currentState.track_dur) return 0;
  const rect = container.getBoundingClientRect();
  const touch = e.touches[0] || e.changedTouches[0];
  const clickX = touch.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  return pct * currentState.track_dur;
}

function startTouchScrub(e) {
  if (!currentState.track_dur) return;
  isUserScrubbing = true;
  const targetPos = getScrubPosFromTouch(e);
  updateScrubDisplay(targetPos);

  function onTouchMove(ev) {
    if (isUserScrubbing) {
      const p = getScrubPosFromTouch(ev);
      updateScrubDisplay(p);
    }
  }

  function onTouchEnd(ev) {
    if (isUserScrubbing) {
      isUserScrubbing = false;
      const finalPos = getScrubPosFromTouch(ev);
      baseServerPos = finalPos;
      lastSyncPerfTime = performance.now() / 1000;
      updateScrubDisplay(finalPos);
      anchorProgress();
      fetch('/api/playback/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pos: finalPos })
      });
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onTouchEnd);
    }
  }

  window.addEventListener('touchmove', onTouchMove, { passive: false });
  window.addEventListener('touchend', onTouchEnd, { passive: false });
}


// Progress bar: 4 updates a second, with a CSS slide in between (was 60/sec).
function renderTimelineStep() {
  if (isDocVisible && !isUserScrubbing && currentState.track_dur > 0) {
    let currentSec = baseServerPos;
    if (lastPlaying) {
      currentSec += (performance.now() / 1000) - lastSyncPerfTime;
    }
    currentSec = Math.min(currentState.track_dur, Math.max(0, currentSec));
    textIf(document.getElementById('trackTimeElapsed'), formatTime(currentSec));
  }
}
setInterval(renderTimelineStep, 250);

// Fit the whole app to the window/screen it opens on: scale it up on big
// screens and down on small ones so everything shows without scrolling.
// Adapts to whatever device opens the dashboard:
// - Phones: normal-size text and controls, stacked layout, scroll like any phone page
//   (shrinking everything to fit a phone screen makes it unreadable).
// - Tablets, laptops, desktops, the Mac app window: scale the whole dashboard
//   to fill the screen without scrolling.
function isPhone() {
  const small = Math.min(window.innerWidth, window.innerHeight) < 600;
  const touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  const phoneName = /iPhone|iPod|Android.+Mobile|Windows Phone/i.test(navigator.userAgent);
  // Sideways small screens (Echo Show, phone turned sideways) get the Mac layout,
  // scaled to fit; the phone layout is for upright screens
  return window.innerWidth < 700 || ((touch || phoneName) && small && window.innerHeight > window.innerWidth);
}
function fitToWindow() {
  const el = document.getElementById('appShell');
  if (!el) return;
  el.style.zoom = 1;
  document.body.classList.toggle('is-phone', isPhone());
  // full-screen layout goes by shape: narrow or upright screens only
  document.body.classList.toggle('fs-narrow', window.innerWidth < 700 || window.innerHeight > window.innerWidth);
  if (isPhone()) return;
  const margin = 24;
  const w = el.offsetWidth, h = el.offsetHeight;
  if (!w || !h) return;
  let z = Math.min((window.innerWidth - margin) / w, (window.innerHeight - margin) / h);
  z = Math.max(0.6, Math.min(1.4, z));
  el.style.zoom = z.toFixed(3);
}
let fitTimer = null;
function scheduleFit() {
  clearTimeout(fitTimer);
  fitTimer = setTimeout(fitToWindow, 60);
}
window.addEventListener('resize', scheduleFit);
window.addEventListener('orientationchange', scheduleFit);
window.addEventListener('load', scheduleFit);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(scheduleFit);

connectEvents();

// Shut down the server from any device (e.g. a phone). The menu-bar app on the
// Mac quits too, so it isn't restarted automatically.
// ---- Other lights (WiZ / LIFX / WLED) ----
let lastDevSig = '';
function post(path, body) { return fetch(path, { method: 'POST', body: JSON.stringify(body || {}) }); }
function devMsg(t) { const m = document.getElementById('devMsg'); if (m) m.textContent = t || ''; }
function renderDevices(s) {
  const list = document.getElementById('devList');
  if (!list) return;
  const sig = JSON.stringify([s.devices, s.discovered_devices, s.scanning_devices]);
  if (sig === lastDevSig) return;
  lastDevSig = sig;
  list.innerHTML = '';
  const scanBtn = document.getElementById('devScanBtn');
  if (scanBtn) scanBtn.textContent = s.scanning_devices ? 'Scanning…' : 'Scan';
  const row = (text, dot, btnText, onclick) => {
    const d = document.createElement('div');
    d.className = 'flex items-center gap-2 text-[11px] text-slate-300';
    const dotEl = document.createElement('span');
    dotEl.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + dot;
    const t = document.createElement('span');
    t.className = 'font-mono flex-1';
    t.textContent = text;
    const b = document.createElement('button');
    b.className = 'st-btn';
    b.textContent = btnText;
    b.onclick = onclick;
    d.append(dotEl, t, b);
    list.appendChild(d);
  };
  (s.devices || []).forEach(d => row(`${d.label} ${d.ip} · follows ${d.side}`, d.online ? '#34d399' : '#64748b',
    'Remove', () => post('/api/devices/remove', { ip: d.ip })));
  (s.discovered_devices || []).forEach(d => row(`Found: ${d.kind.toUpperCase()} ${d.ip}`, '#fbbf24', 'Add',
    () => addDevice(d.kind, d.ip)));
  if (s.scanning_devices) devMsg('Looking for lights on your network…');
}
function addDevice(kind, ip) {
  kind = kind || document.getElementById('devKind').value;
  ip = ip || document.getElementById('devIp').value.trim();
  const side = document.getElementById('devSide').value;
  devMsg('');
  fetch('/api/devices/add', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Govee-App': '1' },
    body: JSON.stringify({ kind, ip, side }) })
    .then(r => r.json().then(j => ({ ok: r.ok, j })))
    .then(({ ok, j }) => { if (!ok) devMsg(j.error || 'Could not add that light'); else document.getElementById('devIp').value = ''; })
    .catch(() => devMsg('Could not reach the server'));
}
function scanDevices() { devMsg(''); post('/api/devices/scan', {}); }

// Pairing link for phones/tablets (only the Mac itself is allowed to see it)
function loadPairLink() {
  fetch('/api/pairing').then(r => r.ok ? r.json() : null).then(d => {
    if (!d || d.open) return;
    document.getElementById('pairLink').value = d.url;
    document.getElementById('pairSection').style.display = '';
  }).catch(() => {});
}
function copyPairLink() {
  const el = document.getElementById('pairLink');
  el.select();
  const done = () => { const b = document.getElementById('pairCopy'); b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1500); };
  if (navigator.clipboard) navigator.clipboard.writeText(el.value).then(done, () => { document.execCommand('copy'); done(); });
  else { document.execCommand('copy'); done(); }
}
loadPairLink();

function shutdownServer() {
  if (!confirm('Shut down the lighting server?\n\nThe lamps stop syncing. To start again, open Glowtrack on your Mac.')) return;
  const lampsOff = confirm('Turn the lamps off too?\n\nOK = turn lamps off\nCancel = leave them on their current colour');
  fetch('/api/shutdown', { method: 'POST', body: JSON.stringify({ lamps_off: lampsOff }) })
    .catch(() => {})
    .finally(() => {
      if (evtSource) { evtSource.close(); evtSource = null; }
      window._serverStopped = true;
      toggleSettingsModal(false);
      const o = document.createElement('div');
      o.style.cssText = 'position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;' +
        'background:rgba(9,11,14,0.94);color:#fff;font:600 15px/1.5 var(--app-font);text-align:center;padding:24px;';
      o.innerHTML = '<div><div style="font-size:20px;font-weight:800;margin-bottom:8px">Server stopped</div>' +
        '<div style="color:#94A3B8">To start it again, open <b style="color:#fff">Glowtrack</b> on your Mac.<br>' +
        'This page reconnects by itself when it\'s back.</div></div>';
      document.body.appendChild(o);
      // Reconnect automatically once the server is running again
      const timer = setInterval(() => {
        fetch('/api/state', { cache: 'no-store' }).then(r => { if (r.ok) { clearInterval(timer); location.reload(); } }).catch(() => {});
      }, 5000);
    });
}


// =====================================================================
// Album-colour gradient backgrounds + full-screen "now playing" view.
// Gradients only change when the song changes (cross-faded with opacity),
// so they cost nothing while music plays.
// =====================================================================
if (new URLSearchParams(location.search).get('app') === 'mac') document.body.classList.add('in-mac-app');

function _rgb(hex) {
  const n = parseInt((hex || '#222222').replace('#', ''), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function _mix(hex, k, base) {      // darken toward the page background
  const [r, g, b] = _rgb(hex);
  base = base || [9, 11, 14];
  return `rgb(${Math.round(base[0] + (r - base[0]) * k)}, ${Math.round(base[1] + (g - base[1]) * k)}, ${Math.round(base[2] + (b - base[2]) * k)})`;
}
// Background colours: dark but colourful album colours (deep orange, wine red,
// navy) are brightened first, keeping their hue, so after the darkening shade
// they still read as dark orange etc. instead of muddy brown. Greys stay as they are.
function screenColour(hex) {
  const [r, g, b] = _rgb(hex);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  if (mx === 0) return hex;
  const sat = (mx - mn) / mx;
  if (sat < 0.35) return hex;
  const want = 200 + 30 * Math.min(1, (sat - 0.35) / 0.4);   // brighter the more colourful
  if (mx >= want) return hex;
  const k = want / mx;
  const h2 = v => Math.min(255, Math.round(v * k)).toString(16).padStart(2, '0');
  return '#' + h2(r) + h2(g) + h2(b);
}
function screenPalette(pal) { return (pal || []).map(screenColour); }

// opts.cool: the dashboard's own page background: a deep blue-violet base instead of
// near-black, richer album colours, and soft cool glows (blue and cyan) in the corners.
function albumGradient(pal, strength, opts) {
  const c = (pal && pal.length) ? pal : ['#333333'];
  const c1 = c[0], c2 = c[1] || c[0], c3 = c[2] || c2;
  const cool = !!(opts && opts.cool);
  const base = cool ? [6, 9, 26] : null;
  const edge = cool ? '#060A1A' : '#090B0E';
  const layers = [
    `radial-gradient(ellipse 80% 70% at 15% 10%, ${_mix(c1, 0.75 * strength, base)} 0%, transparent 65%)`,
    `radial-gradient(ellipse 75% 70% at 90% 90%, ${_mix(c2, 0.65 * strength, base)} 0%, transparent 65%)`,
    `radial-gradient(ellipse 60% 60% at 80% 15%, ${_mix(c3, 0.45 * strength, base)} 0%, transparent 70%)`,
  ];
  if (cool) {
    layers.push('radial-gradient(ellipse 70% 50% at 50% 105%, rgba(60, 110, 255, 0.20) 0%, transparent 70%)',
                'radial-gradient(ellipse 45% 40% at 0% 85%, rgba(0, 210, 255, 0.11) 0%, transparent 70%)',
                'radial-gradient(ellipse 50% 40% at 100% 0%, rgba(150, 90, 255, 0.12) 0%, transparent 70%)');
  }
  layers.push(`linear-gradient(160deg, ${_mix(c1, 0.30 * strength, base)} 0%, ${edge} 70%)`);
  return layers.join(',');
}
// Cross-fade between two stacked layers
function setLayeredBg(idA, idB, grad) {
  const a = document.getElementById(idA), b = document.getElementById(idB);
  if (!a || !b) return;
  const front = parseFloat(a.style.opacity || '1') >= 0.5 ? a : b;
  const back = front === a ? b : a;
  if (front._grad === grad) return;
  back.style.backgroundImage = grad;
  back._grad = grad;
  back.style.opacity = '1';
  front.style.opacity = '0';
}

let lastBgSig = '';
function updateBackgrounds(s) {
  const pal = screenPalette(s.palette_lamp);
  const sig = pal.join(',');
  if (sig === lastBgSig) return;
  lastBgSig = sig;
  setLayeredBg('pageBgA', 'pageBgB', albumGradient(pal, 0.85, { cool: true }));
  setLayeredBg('fsBgA', 'fsBgB', albumGradient(pal, 1.0));
}

// Drifting blobs behind the full-screen view. Their colours change only when the
// song changes; the movement is a CSS transform animation the graphics chip runs.
const FS_MOTION_NAMES = ['Off', 'Very slow', 'Slow', 'Medium', 'Lively', 'Fast'];
const FS_MOTION_SECS = [0, 40, 28, 18, 11, 7];
let lastFsMotion = null;
function applyFsMotion(level) {
  if (level === lastFsMotion) return;
  lastFsMotion = level;
  const blobs = document.getElementById('fsBlobs');
  if (!blobs) return;
  blobs.classList.toggle('fs-still', level === 0);
  if (level > 0) blobs.style.setProperty('--blob-s', `${FS_MOTION_SECS[level]}s`);
}
let lastBlobSig = '';
function updateBlobColours(pal) {
  const c = (pal && pal.length) ? pal : ['#333333'];
  const sig = c.join(',');
  if (sig === lastBlobSig) return;
  lastBlobSig = sig;
  const cols = [c[0], c[1] || c[0], c[2] || c[1] || c[0]];
  document.querySelectorAll('#fsBlobs .fs-blob').forEach((b, i) => { b.style.backgroundColor = cols[i]; });
}

function updateFullscreenView(s) {
  updateBlobColours(screenPalette(s.palette_lamp));
  setMarquee(document.getElementById('fsTitle'), s.track || 'Waiting for Spotify...');
  setMarquee(document.getElementById('fsArtist'), s.artist || '');
  textIf(document.getElementById('fsTotal'), formatTime(s.track_dur || 0));
  const art = document.getElementById('fsArt');
  const wanted = (s.art_url && !s.is_ad) ? s.art_url : '';
  if (art && art._src !== wanted) {
    art._src = wanted;
    if (wanted) { art.src = wanted; art.style.visibility = 'visible'; }
    else { art.removeAttribute('src'); art.style.visibility = 'hidden'; }
  }
}

// Keep both views in sync with every state update
const _baseUpdateUI = updateUI;
updateUI = function (s) {
  _baseUpdateUI(s);
  updateBackgrounds(s);
  updateFullscreenView(s);
};

// Full-screen elapsed time (same clock as the dashboard)
setInterval(() => {
  if (!document.body.classList.contains('fs-open') || !currentState.track_dur) return;
  let t = baseServerPos + (lastPlaying ? (performance.now() / 1000 - lastSyncPerfTime) : 0);
  t = Math.min(currentState.track_dur, Math.max(0, t));
  if (isUserScrubbing) return;
  textIf(document.getElementById('fsElapsed'), formatTime(t));
  if (document.body.classList.contains('fs-controls-on')) placeFsThumb(t);
}, 500);

let fsHideTimer = null;
function fsShowControls() {
  document.body.classList.add('fs-controls-on');
  clearTimeout(fsHideTimer);
  fsHideTimer = setTimeout(() => document.body.classList.remove('fs-controls-on'), 3500);
}
function fsTap(e) {
  // Tap toggles the controls (tap again to hide them right away)
  if (document.body.classList.contains('fs-controls-on')) {
    clearTimeout(fsHideTimer);
    document.body.classList.remove('fs-controls-on');
  } else {
    fsShowControls();
  }
}
function enterFullscreen() {
  if (currentState) updateFullscreenView(currentState);
  document.body.classList.add('fs-open');
  document.getElementById('fsView').setAttribute('aria-hidden', 'false');
  anchorProgress();
  fsShowControls();
  // Real full screen where the device allows it (Mac app, desktop browsers, iPad);
  // phones simply get the full-window view.
  const el = document.documentElement;
  const req = el.requestFullscreen || el.webkitRequestFullscreen;
  if (req && !document.fullscreenElement && !document.webkitFullscreenElement) {
    try { const p = req.call(el); if (p && p.catch) p.catch(() => {}); } catch (e) {}
  }
}
function exitFullscreen() {
  document.body.classList.remove('fs-open', 'fs-controls-on');
  document.getElementById('fsView').setAttribute('aria-hidden', 'true');
  const exit = document.exitFullscreen || document.webkitExitFullscreen;
  if ((document.fullscreenElement || document.webkitFullscreenElement) && exit) {
    try { const p = exit.call(document); if (p && p.catch) p.catch(() => {}); } catch (e) {}
  }
}
// Leaving the system full screen (Esc, green button) also closes the view
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && document.body.classList.contains('fs-open')) exitFullscreen();
});
document.addEventListener('webkitfullscreenchange', () => {
  if (!document.webkitFullscreenElement && document.body.classList.contains('fs-open')) exitFullscreen();
});
window.addEventListener('keydown', (e) => {
  // With Settings open over full screen, keys belong to Settings (Esc just closes it)
  if (!document.body.classList.contains('fs-open') || settingsOpen()) return;
  if (e.key === 'Escape') exitFullscreen();
  else if (e.key === ' ') { e.preventDefault(); sendPlayback('playpause'); fsShowControls(); }
  else if (e.key === 'ArrowRight') { sendPlayback('next'); fsShowControls(); }
  else if (e.key === 'ArrowLeft') { sendPlayback('prev'); fsShowControls(); }
});
// Moving the mouse shows the controls too (desktop)
document.getElementById('fsView').addEventListener('mousemove', () => {
  if (document.body.classList.contains('fs-open')) fsShowControls();
});

// ---------------------------------------------------------------------------
// Lyrics mode (full screen): the cover slides left and time-synced lyrics
// scroll on the right. The highlighted line only changes when the song reaches
// the next line (one timer per line), so it costs almost nothing.
// ---------------------------------------------------------------------------
const LYRIC_LEAD = 0.25;   // show each line a touch early, like Spotify
let lyricsOn = false;
try { lyricsOn = localStorage.getItem('fsLyrics') === '1'; } catch (e) {}
let lyricsTrack = null;     // song the shown lyrics belong to
let lyricsLines = [];       // [[seconds, words], ...] when synced
let lyricsIdx = -2;
let lyricsTimer = null;
let lyricsReq = 0;

function songNow() {
  return baseServerPos + (lastPlaying ? (performance.now() / 1000 - lastSyncPerfTime) : 0);
}

function toggleLyrics(force) {
  lyricsOn = (typeof force === 'boolean') ? force : !lyricsOn;
  try { localStorage.setItem('fsLyrics', lyricsOn ? '1' : '0'); } catch (e) {}
  document.body.classList.toggle('fs-lyrics-on', lyricsOn);
  if (lyricsOn) refreshLyrics(currentState || {});
  else clearTimeout(lyricsTimer);
}

function setLyricsMessage(msg) {
  textIf(document.getElementById('fsLyricsMsg'), msg);
}

function refreshLyrics(s) {
  if (!lyricsOn || !document.body.classList.contains('fs-open')) return;
  const track = s.is_ad ? '' : (s.track || '');
  if (track === lyricsTrack) { lyricsTick(); return; }
  lyricsTrack = track;
  lyricsLines = [];
  lyricsIdx = -2;
  clearTimeout(lyricsTimer);
  const panel = document.getElementById('fsLyrics');
  const list = document.getElementById('fsLyricsList');
  list.innerHTML = '';
  list.style.transform = 'translateY(0)';
  panel.classList.remove('ly-plain');
  if (!track || s.is_ad) { setLyricsMessage(s.is_ad ? '' : 'Nothing playing'); return; }
  setLyricsMessage('Loading lyrics…');
  const req = ++lyricsReq;
  fetch('/api/lyrics').then(r => r.json()).then(res => {
    if (req !== lyricsReq || res.track !== lyricsTrack) return;   // song changed meanwhile
    if (res.status === 'synced') {
      lyricsLines = res.synced;
      list.innerHTML = '';
      lyricsLines.forEach(([t, words], i) => {
        const div = document.createElement('div');
        div.className = 'fs-ly-line';
        div.textContent = words || '♪';
        div.onclick = (e) => { e.stopPropagation(); seekTo(t); };
        list.appendChild(div);
      });
      setLyricsMessage('');
      lyricsTick();
    } else if (res.status === 'plain') {
      panel.classList.add('ly-plain');
      res.plain.forEach(words => {
        const div = document.createElement('div');
        div.className = 'fs-ly-line';
        div.textContent = words || ' ';
        list.appendChild(div);
      });
      setLyricsMessage('');
    } else if (res.status === 'instrumental') {
      setLyricsMessage('♪ Instrumental');
    } else if (res.status === 'error') {
      lyricsTrack = null;   // try again on the next update
      setLyricsMessage("Couldn't load lyrics");
    } else {
      setLyricsMessage('No lyrics found for this song');
    }
  }).catch(() => { if (req === lyricsReq) { lyricsTrack = null; setLyricsMessage("Couldn't load lyrics"); } });
}

// Tapping a lyric starts the song right at that line
function seekTo(t) { commitSeek(Math.max(0, t - 0.1)); }

function commitSeek(pos) {
  pos = Math.max(0, Math.min(currentState.track_dur || pos, pos));
  fetch('/api/playback/seek', { method: 'POST', body: JSON.stringify({ pos: pos }) });
  baseServerPos = pos;
  lastSyncPerfTime = performance.now() / 1000;
  anchorProgress();
  placeFsThumb(pos);
  lyricsTick();
}

// Full-screen progress bar: press, drag, let go (mouse, finger or pen)
function placeFsThumb(pos) {
  const thumb = document.getElementById('fsThumb');
  const dur = currentState.track_dur || 0;
  if (thumb && dur) thumb.style.left = `${(Math.max(0, Math.min(1, pos / dur)) * 100).toFixed(3)}%`;
}
(function setupFsScrub() {
  const scrub = document.getElementById('fsScrub');
  if (!scrub) return;
  let dragging = false;
  const posFrom = (e) => {
    const r = scrub.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (currentState.track_dur || 0);
  };
  const show = (pos) => {
    const bar = document.getElementById('fsProgressBar');
    bar.style.transition = 'none';
    bar.style.transform = `scaleX(${(pos / currentState.track_dur).toFixed(5)})`;
    placeFsThumb(pos);
    textIf(document.getElementById('fsElapsed'), formatTime(pos));
  };
  scrub.addEventListener('pointerdown', (e) => {
    if (!currentState.track_dur) return;
    e.preventDefault();
    e.stopPropagation();
    dragging = true;
    isUserScrubbing = true;      // stops the playing animation fighting the drag
    scrub.classList.add('dragging');
    scrub.setPointerCapture(e.pointerId);
    show(posFrom(e));
    fsShowControls();
  });
  scrub.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    show(posFrom(e));
    fsShowControls();
  });
  const finish = (e, cancelled) => {
    if (!dragging) return;
    dragging = false;
    isUserScrubbing = false;
    scrub.classList.remove('dragging');
    if (cancelled) anchorProgress();
    else commitSeek(posFrom(e));
  };
  scrub.addEventListener('pointerup', (e) => finish(e, false));
  scrub.addEventListener('pointercancel', (e) => finish(e, true));
  scrub.addEventListener('click', (e) => e.stopPropagation());
})();

function lyricsTick() {
  clearTimeout(lyricsTimer);
  if (!lyricsOn || !lyricsLines.length || !document.body.classList.contains('fs-open')) return;
  const now = songNow() + LYRIC_LEAD;
  let idx = -1;
  for (let i = 0; i < lyricsLines.length && lyricsLines[i][0] <= now; i++) idx = i;
  if (idx !== lyricsIdx) {
    const list = document.getElementById('fsLyricsList');
    const lines = list.children;
    if (lyricsIdx >= 0 && lines[lyricsIdx]) lines[lyricsIdx].classList.remove('on');
    for (let i = 0; i < lines.length; i++) lines[i].classList.toggle('past', i < idx);
    if (idx >= 0 && lines[idx]) {
      lines[idx].classList.add('on');
      list.style.transform = `translateY(${-(lines[idx].offsetTop + lines[idx].offsetHeight / 2)}px)`;
    } else {
      list.style.transform = 'translateY(0)';
    }
    lyricsIdx = idx;
  }
  scheduleLyricTick();
}

function scheduleLyricTick() {
  clearTimeout(lyricsTimer);
  if (!lastPlaying || !lyricsLines.length) return;
  const next = lyricsLines[lyricsIdx + 1];
  if (!next) return;
  const wait = (next[0] - (songNow() + LYRIC_LEAD)) * 1000;
  lyricsTimer = setTimeout(lyricsTick, Math.max(40, Math.min(wait + 15, 5000)));
}

// White lyrics on dark backgrounds, black lyrics on light ones
function _lum(hex) {
  const h = (hex || '#000').replace('#', '');
  const ch = [0, 2, 4].map(i => parseInt(h.substr(i, 2), 16) / 255)
    .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}
let lastLyricTone = '';
function updateLyricTone(pal) {
  const c = (pal && pal.length) ? pal : ['#333333'];
  const sig = c.join(',');
  if (sig === lastLyricTone) return;
  lastLyricTone = sig;
  // What the lyrics sit on: the drifting album colours under a 28% dark shade
  const w = [0.45, 0.35, 0.2];
  let rgb = [0, 0, 0];
  [c[0], c[1] || c[0], c[2] || c[1] || c[0]].forEach((hex, i) => {
    const h = hex.replace('#', '');
    for (let k = 0; k < 3; k++) rgb[k] += parseInt(h.substr(k * 2, 2), 16) * w[i];
  });
  const shade = [9, 11, 14];
  rgb = rgb.map((v, k) => v * 0.72 + shade[k] * 0.28);
  const bg = _lum('#' + rgb.map(v => Math.round(v).toString(16).padStart(2, '0')).join(''));
  // Pick whichever text colour has more contrast
  const vsWhite = 1.05 / (bg + 0.05), vsBlack = (bg + 0.05) / 0.05;
  document.getElementById('fsLyrics').classList.toggle('ly-dark-text', vsBlack > vsWhite);
  document.querySelector('.fs-meta').classList.toggle('tone-dark', vsBlack > vsWhite);
}

const _updateUIBeforeLyrics = updateUI;
updateUI = function (s) {
  _updateUIBeforeLyrics(s);
  updateLyricTone(screenPalette(s.palette_lamp));
  if (lyricsOn) refreshLyrics(s);
};
const _enterFsBeforeLyrics = enterFullscreen;
enterFullscreen = function () {
  _enterFsBeforeLyrics();
  document.body.classList.toggle('fs-lyrics-on', lyricsOn);
  lyricsTrack = null;
  if (lyricsOn) refreshLyrics(currentState || {});
};
window.addEventListener('keydown', (e) => {
  if (document.body.classList.contains('fs-open') && !settingsOpen() && (e.key === 'l' || e.key === 'L')) toggleLyrics();
});

// ---------------------------------------------------------------------------
// Shuffle, repeat and volume (Spotify on this Mac)
// ---------------------------------------------------------------------------
let volBeforeMute = 50;
function toggleShuffle() {
  const on = !currentState.shuffle;
  currentState.shuffle = on;
  paintPlaybackExtras(currentState);
  fetch('/api/playback/shuffle', { method: 'POST', body: JSON.stringify({ on: on }) });
}
function toggleRepeat() {
  const on = !currentState.repeat;
  currentState.repeat = on;
  paintPlaybackExtras(currentState);
  fetch('/api/playback/repeat', { method: 'POST', body: JSON.stringify({ on: on }) });
}
function onVolume(el) {
  const v = parseInt(el.value, 10);
  currentState.volume = v;
  document.querySelectorAll('.js-vol').forEach(s => {
    if (s !== el) s.value = v;
    settingHoldUntil[s.id] = performance.now() + 1500;
  });
  paintVolumeIcon(v);
  textIf(document.getElementById('volVal'), String(v));
  clearTimeout(settingTimers['vol']);
  settingTimers['vol'] = setTimeout(() => {
    fetch('/api/playback/volume', { method: 'POST', body: JSON.stringify({ value: v }) });
  }, 60);
}
function toggleMute() {
  const cur = currentState.volume == null ? 50 : currentState.volume;
  let v;
  if (cur > 0) { volBeforeMute = cur; v = 0; } else { v = volBeforeMute || 50; }
  const el = document.getElementById('volSlider');
  el.value = v;
  onVolume(el);
}
function paintVolumeIcon(v) {
  document.querySelectorAll('.vol-icon').forEach(b => b.classList.toggle('vol-muted', v === 0));
}
function paintPlaybackExtras(s) {
  document.body.classList.toggle('no-sr', s.can_shuffle_repeat === false);   // players without shuffle/repeat we can reach
  document.querySelectorAll('.js-shuffle').forEach(b => b.classList.toggle('on', !!s.shuffle));
  document.querySelectorAll('.js-repeat').forEach(b => b.classList.toggle('on', !!s.repeat));
  if (s.volume !== null && s.volume !== undefined) {
    let changed = false;
    document.querySelectorAll('.js-vol').forEach(sl => { if (setSliderFromServer(sl.id, s.volume)) changed = true; });
    if (changed) { textIf(document.getElementById('volVal'), String(s.volume)); paintVolumeIcon(s.volume); }
  }
}

function settingsOpen() {
  const m = document.getElementById('settingsModal');
  return !!m && !m.classList.contains('pointer-events-none');
}

const _updateUIBeforeExtras = updateUI;
updateUI = function (s) {
  _updateUIBeforeExtras(s);
  paintPlaybackExtras(s);
};

// ---------------------------------------------------------------------------
// Long titles scroll sideways (like Spotify) instead of being cut off or
// running under the lyrics. One CSS animation on the graphics chip.
// ---------------------------------------------------------------------------
function setMarquee(el, text) {
  if (!el) return;
  if (el._mqText === text) return;
  el._mqText = text;
  layoutMarquee(el);
}
function layoutMarquee(el) {
  if (!el || el._mqText === undefined) return;
  const text = el._mqText;
  el.classList.remove('mq-on');
  el.innerHTML = '';
  const inner = document.createElement('span');
  inner.className = 'mq-inner';
  inner.textContent = text;
  el.appendChild(inner);
  const room = el.clientWidth;
  const need = inner.scrollWidth;
  if (!room || need <= room + 1) return;
  // two copies with a gap, so the loop has no jump
  const gap = document.createElement('span');
  gap.className = 'mq-gap';
  const copy = document.createElement('span');
  copy.textContent = text;
  inner.appendChild(gap);
  inner.appendChild(copy);
  const dist = need + gap.offsetWidth;
  const secs = dist / 60;                      // about 60 px a second
  el.style.setProperty('--mq-dist', dist + 'px');
  el.style.setProperty('--mq-dur', (secs / 0.82).toFixed(2) + 's');   // the first 18% is the pause
  el.classList.add('mq-on');
}
function relayoutMarquees() {
  layoutMarquee(document.getElementById('fsTitle'));
  layoutMarquee(document.getElementById('fsArtist'));
}
window.addEventListener('resize', () => { if (document.body.classList.contains('fs-open')) relayoutMarquees(); });
const _toggleLyricsBeforeMq = toggleLyrics;
toggleLyrics = function (force) {
  _toggleLyricsBeforeMq(force);
  relayoutMarquees();
};
const _enterFsBeforeMq = enterFullscreen;
enterFullscreen = function () {
  _enterFsBeforeMq();
  requestAnimationFrame(relayoutMarquees);
};
