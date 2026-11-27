/* Layout checker for the Glowtrack designs: the checks a senior UI designer would do by eye.
 *
 * Load the dashboard, then paste this file into the browser console (or run it with the
 * browser tool). It visits every design and screen and reports, in design pixels:
 *   overlap     two pieces of text or graphics sitting on top of each other
 *   outside     something past the edge of the 1000x640 (or 390x800) canvas
 *   clipped     text cut off inside its box
 *   tiny        text that ends up under 9 px on screen
 *   tap         a button smaller than 28 px on a phone layout
 *   near-miss   edges that are almost, but not quite, on the same line (36 vs 38). Left edges of anything,
 *               right edges of buttons and graphics, tops of same-height items. Ragged text is not flagged.
 *   contrast    text that falls under WCAG 4.5:1 (3:1 for text 24px and up) against its nearest solid background
 *
 * Usage:  glowtrackLint()                 every design, current layout (computer or phone, by window size)
 *         glowtrackLint(['b'], ['main'])  only some
 */
(function () {
  var TEXT_SKIP = '.dbg, .dbg *, [data-lyr] *, .tscroll .lyr *';
  var GRAPHIC = 'canvas, input, select, .cov2, .cv, .frame, .lampw, .pil, .lamp, .knob, .pbar, .rule, .pgs, .pgc .bar, .dots, .ctl, .cap span, .lb, .mk, .tk';

  function lintOne() {
    var root = document.getElementById('themeRoot'), des = root.querySelector('.design');
    if (!des) return { error: 'no design on screen' };
    var scaler = des.closest('.tscale'), dr = des.getBoundingClientRect();
    var W = des.offsetWidth, H = des.offsetHeight, sc = scaler ? dr.width / W : 1;
    var els = [], issues = [];

    function name(el) {
      var t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 16);
      return (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()) + (t ? ' "' + t + '"' : '');
    }
    function boxOf(el, textOnly) {
      var r;
      if (textOnly) { var rg = document.createRange(); rg.selectNodeContents(el); r = rg.getBoundingClientRect(); } else r = el.getBoundingClientRect();
      var b = { x: (r.left - dr.left) / sc, y: (r.top - dr.top) / sc, w: r.width / sc, h: r.height / sc };
      if (textOnly) { b.y += b.h * 0.12; b.h *= 0.76; }   // the letters are shorter than the font's box
      if (textOnly && getComputedStyle(el).overflow === 'hidden') {   // cut-off text only counts where it is visible
        var cr = el.getBoundingClientRect(), cx0 = (cr.left - dr.left) / sc, cx1 = (cr.right - dr.left) / sc;
        b.w = Math.max(0, Math.min(b.x + b.w, cx1) - Math.max(b.x, cx0)); b.x = Math.max(b.x, cx0);
      }
      return b;
    }
    function hasOwnText(el) { return Array.prototype.some.call(el.childNodes, function (n) { return n.nodeType === 3 && n.textContent.trim(); }); }

    des.querySelectorAll('*').forEach(function (el) {
      if (el.matches(TEXT_SKIP)) return;
      var cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
      var isText = hasOwnText(el), isGraphic = el.matches(GRAPHIC);
      if (!isText && !isGraphic) return;
      var b = boxOf(el, isText && !isGraphic && el.tagName !== 'BUTTON');
      if (b.w < 1 || b.h < 1) return;
      els.push({ el: el, b: b, text: isText, fs: parseFloat(cs.fontSize) });
    });

    function inScroller(el, stop) {
      for (var p = el.parentElement; p && p !== stop; p = p.parentElement) { var o = getComputedStyle(p).overflowY; if (o === 'auto' || o === 'scroll') return true; }
      return false;
    }
    // overlaps
    for (var i = 0; i < els.length; i++) for (var j = i + 1; j < els.length; j++) {
      var a = els[i], c = els[j];
      if (a.el.contains(c.el) || c.el.contains(a.el)) continue;
      var ox = Math.min(a.b.x + a.b.w, c.b.x + c.b.w) - Math.max(a.b.x, c.b.x);
      var oy = Math.min(a.b.y + a.b.h, c.b.y + c.b.h) - Math.max(a.b.y, c.b.y);
      if (ox > 3 && oy > 3) issues.push({ kind: 'overlap', a: name(a.el), b: name(c.el), px: Math.round(ox) + 'x' + Math.round(oy) });
    }
    // outside canvas, clipped text, tiny text, tap targets
    els.forEach(function (e) {
      var b = e.b;
      if (inScroller(e.el, des)) return;
      if (b.x < -1 || b.y < -1 || b.x + b.w > W + 1 || b.y + b.h > H + 1) issues.push({ kind: 'outside', el: name(e.el), box: [b.x, b.y, b.x + b.w, b.y + b.h].map(Math.round).join(',') });
      if (e.text && e.fs * sc < 9) issues.push({ kind: 'tiny', el: name(e.el), onScreenPx: +(e.fs * sc).toFixed(1) });
      if (e.el.tagName === 'BUTTON' && des.classList.contains('ph') && (b.w * sc < 28 || b.h * sc < 28)) issues.push({ kind: 'tap', el: name(e.el), size: Math.round(b.w * sc) + 'x' + Math.round(b.h * sc) });
    });
    des.querySelectorAll('*').forEach(function (el) {
      if (el.matches(TEXT_SKIP) || el === des) return;
      var cs = getComputedStyle(el);
      if (cs.textOverflow === 'ellipsis') return;   // meant to be cut with an ellipsis
      if ((cs.overflow === 'hidden' || cs.overflowX === 'hidden') && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) && hasOwnText(el))
        issues.push({ kind: 'clipped', el: name(el), scroll: el.scrollWidth + 'x' + el.scrollHeight, box: el.clientWidth + 'x' + el.clientHeight });
    });
    // near-miss alignment of left, right and top edges
    function near(edge, label, only) {
      var vals = els.filter(function (e) { return e.b.w * e.b.h > 300 && (!only || only(e)); }).map(function (e) { return { v: Math.round(edge(e.b)), el: e.el, h: e.b.h }; }).sort(function (p, q) { return p.v - q.v; });
      for (var k = 1; k < vals.length; k++) {
        var d = vals[k].v - vals[k - 1].v;
        if (d >= 1 && d <= 5 && !vals[k].el.contains(vals[k - 1].el) && !vals[k - 1].el.contains(vals[k].el) && (label !== 'top' || Math.abs(vals[k].h - vals[k - 1].h) <= 2))
          issues.push({ kind: 'near-miss', edge: label, a: name(vals[k - 1].el) + ' @' + vals[k - 1].v, b: name(vals[k].el) + ' @' + vals[k].v });
      }
    }
    var block = function (e) { return !e.text || e.el.tagName === 'BUTTON'; };
    near(function (b) { return b.x; }, 'left'); near(function (b) { return b.x + b.w; }, 'right', block); near(function (b) { return b.y; }, 'top', block);
    // contrast
    function rgba(c) { var m = c.match(/[\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; }
    function lin(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
    function L(c) { return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]); }
    function bgOf(el) {
      var r = el.getBoundingClientRect(), stack = document.elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2), seen = false;
      for (var k = 0; k < stack.length; k++) {
        var n = stack[k];
        if (n === el || el.contains(n)) seen = true;
        if (!seen) continue;
        var c = rgba(getComputedStyle(n).backgroundColor); if (c[3] > 0.9) return c;
      }
      return rgba(getComputedStyle(root).backgroundColor);
    }
    els.forEach(function (e) {
      if (!e.text) return;
      var rr = e.el.getBoundingClientRect();
      if (rr.bottom < 0 || rr.top > innerHeight || rr.right < 0 || rr.left > innerWidth) return;   // scrolled out of view
      var cs = getComputedStyle(e.el), fg = rgba(cs.color), bg = bgOf(e.el), op = 1;
      for (var p = e.el; p && p !== root; p = p.parentElement) op *= +getComputedStyle(p).opacity;
      var a = fg[3] * op, eff = [0, 1, 2].map(function (i) { return fg[i] * a + bg[i] * (1 - a); });
      var l1 = L(eff), l2 = L(bg), ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      var need = e.fs >= 24 ? 3 : 4.5;
      if (ratio < need) issues.push({ kind: 'contrast', el: name(e.el), ratio: +ratio.toFixed(2), needs: need });
    });
    return { canvas: W + 'x' + H, scale: +sc.toFixed(2), issues: issues };
  }

  window.glowtrackLint = async function (themes, screens) {
    themes = themes || ['a', 'b', 'c', 'd'];
    var phone = document.getElementById('themeRoot').clientHeight > document.getElementById('themeRoot').clientWidth * 1.05;
    screens = screens || (phone ? ['main', 'settings', 'lyrics'] : ['main', 'full', 'full+lyrics', 'settings']);
    var kill = document.createElement('style'); kill.textContent = '#themeRoot *, #themeRoot { transition: none !important; }'; document.head.appendChild(kill);
    var out = {};
    for (var t of themes) for (var s of screens) {
      Themes.view(t, s.split('+')[0], s.indexOf('lyrics') >= 0 && s !== 'lyrics');
      await new Promise(function (r) { setTimeout(r, 800); });
      var res = lintOne();
      var summary = {};
      (res.issues || []).forEach(function (i) { summary[i.kind] = (summary[i.kind] || 0) + 1; });
      out[t + ':' + s + (phone ? ':phone' : '')] = { counts: summary, details: (res.issues || []).filter(function (i) { return i.kind !== 'near-miss'; }).slice(0, 8), nearMisses: (res.issues || []).filter(function (i) { return i.kind === 'near-miss'; }).slice(0, 6) };
    }
    kill.remove();
    Themes.set(Themes.current());
    return out;
  };
})();
