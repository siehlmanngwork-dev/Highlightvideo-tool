(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const $$ = sel => Array.from(document.querySelectorAll(sel));
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const media = p => '/media?p=' + encodeURIComponent(p);

  let S = { folder: null, job: {}, prep: {}, ffmpeg: true };   // letzter Zustand vom Server
  let current = 1;
  let wasRunning = false;

  // Kann dieser PC die Originalvideos (GoPro: 4K HEVC) direkt abspielen? Dann braucht es keine Sichtkopien.
  const HEVC = { ok: null, testing: false, preparedFor: null };
  const playSrc = v => (HEVC.ok ? v.file : v.sicht);          // Video zum Ansehen/Markieren (oder null)
  function testHevc(file) {
    return new Promise(res => {
      const t = document.createElement('video');
      let done = false;
      const fin = ok => { if (done) return; done = true; t.pause(); t.removeAttribute('src'); t.load(); res(ok); };
      t.muted = true; t.preload = 'auto';
      t.addEventListener('loadeddata', () => {
        if (!t.videoWidth) return fin(false);
        t.play().then(() => setTimeout(() => {
          const q = t.getVideoPlaybackQuality ? t.getVideoPlaybackQuality() : null;
          fin((q ? q.totalVideoFrames - q.droppedVideoFrames > 0 : true) && t.currentTime > 0);
        }, 1200)).catch(() => fin(false));
      });
      t.addEventListener('error', () => fin(false));
      setTimeout(() => fin(false), 10000);
      t.src = media(file);
    });
  }
  async function ensurePrepared() {
    const f = S.folder;
    if (!f || !f.videos.length || f.results.length || S.job.running) return;
    if (HEVC.ok === null) {
      if (HEVC.testing) return;
      HEVC.testing = true;
      const cached = localStorage.getItem('spielschnitt:hevc');
      HEVC.ok = cached === '1' ? true : await testHevc(f.videos[0].file);
      localStorage.setItem('spielschnitt:hevc', HEVC.ok ? '1' : '0');
      HEVC.testing = false;
    }
    if (HEVC.preparedFor === f.path || (S.prep.running && S.prep.folder === f.path)) return;
    HEVC.preparedFor = f.path;
    api('/api/prepare', { need_sicht: !HEVC.ok });
  }

  // ------------------------------------------------------------ Server
  async function api(path, body) {
    const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    return r.json();
  }
  async function refresh() {
    try { S = await api('/api/state'); } catch (e) { return; }
    render();
  }

  // ------------------------------------------------------------ Dialog
  function ask(text, yes = 'Ja') {
    return new Promise(res => {
      $('modaltext').innerHTML = text; $('modalyes').textContent = yes; $('modal').hidden = false;
      const done = v => { $('modal').hidden = true; $('modalyes').onclick = $('modalno').onclick = null; res(v); };
      $('modalyes').onclick = () => done(true); $('modalno').onclick = () => done(false);
    });
  }
  function tell(text) { return ask(text, 'OK').then(() => {}); }

  // ------------------------------------------------------------ Schritte
  const vids = () => (S.folder ? S.folder.videos : []);
  function stepDone(n) {
    const v = vids(), f = S.folder;
    if (!f) return false;
    if (n === 1) return v.length > 0 || f.results.length > 0;
    if (n === 2) return !!f.bild_gesetzt;
    if (n === 3) return v.some(x => x.marker && (x.marker.wechsel || x.marker.hl));
    if (n === 4) return v.some(x => x.vorschau);
    if (n === 5) return f.results.length > 0;
  }
  function stepAllowed(n) {
    if (n === 1) return true;
    if (!S.folder) return false;
    return true;
  }
  function go(n) {
    if (!stepAllowed(n)) return;
    if (current === 3 && n !== 3) { mk.flush(); mk.pause(); }
    if (current === 4 && n !== 4) $('pv').pause();
    if (n === 2) bild.open();
    current = n;
    $$('.view').forEach(v => v.classList.toggle('show', +v.dataset.view === n));
    render();
  }
  $$('.step').forEach(b => b.onclick = () => go(+b.dataset.step));
  $$('[data-goto]').forEach(b => b.onclick = () => go(+b.dataset.goto));

  // ------------------------------------------------------------ Ordner
  async function choose() {
    if (S.job.running) return tell('Bitte warte, bis der Computer fertig ist. 🙂');
    mk.flush();
    const r = await api('/api/choose', {});
    if (r.error) return tell('😕 ' + esc(r.error));
    if (r.chosen) { mk.reset(); bild.reset(); HEVC.preparedFor = null; await refresh(); go(2); }
  }
  $('choose').onclick = choose;
  $('folderchip').onclick = choose;

  const gb = n => (n / 1e9).toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' GB';
  function badgesFor(v) {
    let b = playSrc(v) ? '<span class="badge ok">✓ bereit</span>' : '<span class="badge wait">⏳ wird vorbereitet</span>';
    if (v.marker && (v.marker.wechsel || v.marker.hl)) {
      b += '<span class="badge ok">✓ markiert</span>';
      if (v.marker.hl) b += `<span class="badge hl">⭐ ${v.marker.hl}</span>`;
    } else b += '<span class="badge">nicht markiert</span>';
    if (v.vorschau) b += '<span class="badge wait">👀 Vorschau</span>';
    return b;
  }
  function resultCards(list) {
    return '<div class="results">' + list.map(r => {
      const hl = /_highlights\.mp4$/i.test(r);
      return `<div class="rcard"><div class="t">${hl ? '⭐ Highlights' : '🏀 Ganze Spielzeit'}</div>
        <div class="s">${esc(r)}</div>
        <div class="row"><button class="big primary small" data-open="${esc(r)}">▶ Ansehen</button></div></div>`;
    }).join('') + '</div>';
  }

  let lastFolderHtml = '';
  function renderFolder() {
    const f = S.folder;
    $('foldername').textContent = f ? f.name : 'Noch kein Spiel ausgewählt';
    let h;
    if (!f) {
      h = '<div class="emptybig"><span class="e">🏀</span>Noch kein Spiel ausgewählt.<br>Klick oben auf „Spielordner auswählen“.</div>';
    } else {
      h = `<div class="box"><h3>📁 ${esc(f.name)}</h3><div class="path">${esc(f.path)}</div></div>`;
      if (f.videos.length) {
        h += `<h3 style="margin:4px 0 0">🎥 ${f.videos.length} ${f.videos.length === 1 ? 'Video' : 'Videos'} gefunden</h3>
          <div class="cards">` + f.videos.map((v, i) => `<div class="vcard"><div class="t">🎥 ${esc(v.name)}</div>
          <div class="s">Teil ${i + 1} · ${gb(v.size)}</div><div class="badges">${badgesFor(v)}</div></div>`).join('') + '</div>';
      } else if (!f.results.length) {
        h += '<div class="emptybig"><span class="e">🤔</span>In diesem Ordner sind keine Videos (.MP4).<br>Wähle einen anderen Ordner.</div>';
      }
      if (f.results.length) h += '<h3 style="margin:4px 0 0">🏆 Fertige Videos</h3>' + resultCards(f.results);
      h += '<div class="row"><button class="big ghost small" data-open="">📂 Ordner öffnen</button></div>';
    }
    if (h !== lastFolderHtml) { $('folderinfo').innerHTML = h; lastFolderHtml = h; }
    $('next1').disabled = !f || !f.videos.length;

    const rs = f && f.results.length ? '<h2 style="margin:6px 0 0">🎉 Deine fertigen Videos</h2>' + resultCards(f.results)
      + '<div class="row"><button class="big ghost small" data-open="">📂 Ordner öffnen</button></div>' : '';
    if ($('results').dataset.h !== rs) { $('results').innerHTML = rs; $('results').dataset.h = rs; }

    const unmarked = f ? f.videos.filter(v => !(v.marker && (v.marker.wechsel || v.marker.hl))) : [];
    const um = unmarked.length && stepDone(3) ? `<div class="note warnnote">⚠️ Nicht markiert und darum <b>nicht</b> im fertigen Video:
      ${unmarked.map(v => esc(v.name)).join(', ')}</div>` : '';
    if ($('unmarked').dataset.h !== um) { $('unmarked').innerHTML = um; $('unmarked').dataset.h = um; }
  }
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-open]');
    if (!b) return;
    const r = await api('/api/open', { p: b.dataset.open });
    if (r.error) tell('😕 ' + esc(r.error));
  });

  // ------------------------------------------------------------ Arbeitsschritte
  const JOBNAME = { sichtkopien: 'Sichtkopien', vorschau: 'Vorschau', videos: 'Videos' };
  const JOBDONE = { sichtkopien: 'Die Sichtkopien sind fertig.',
                    vorschau: 'Die Vorschau ist fertig. Schau sie dir unten an.',
                    videos: 'Deine Videos sind fertig!' };
  const JOBSTEP = { sichtkopien: 3, vorschau: 4, videos: 5 };
  const CHEER = ['🏀', '⛹️', '🎬', '🍿', '💪', '🔥', '🏆'];

  $$('[data-run]').forEach(b => b.onclick = async () => {
    const kind = b.dataset.run;
    mk.flush();
    if (kind === 'videos' && !await ask('<b>Fertige Videos erstellen?</b><br><br>Das dauert lange (30–60 Minuten pro Video). '
      + 'Danach werden Markierungen, Korrekturen und Vorschauen gelöscht. Die Originalvideos bleiben.', 'Ja, los!')) return;
    const r = await api('/api/run', { kind });
    if (r.error) return tell('😕 ' + esc(r.error));
    await refresh();
  });

  const prepPct = pr => Math.max(0, Math.min(100, Math.round(((pr.i || 0) + (pr.frac || 0)) / (pr.n || 1) * 100)));
  const prepLabel = pr => (pr.label || 'Vorbereitung') + ' · ' + prepPct(pr) + '%';
  function fmtDur(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return m ? `${m} Min ${s % 60} s` : `${s} s`; }
  function pct(j) { return Math.max(0, Math.min(100, Math.round(((j.i || 0) + (j.frac || 0)) / (j.n || 1) * 100))); }
  function labelOf(j) {
    let l = (j.label || '').replace(/ueber/g, 'über').replace(/fuegen/g, 'fügen');
    if (j.n > 1) l += ` · ${j.i + 1} von ${j.n}`;
    return l;
  }

  function renderJob() {
    const j = S.job || {};
    $$('[data-run]').forEach(b => b.disabled = !!j.running || !S.folder || !vids().length || !S.ffmpeg);
    $('runvideos').disabled = $('runvideos').disabled || !stepDone(3);
    const pr = S.prep || {};
    const prepNote = pr.running && S.folder && pr.folder === S.folder.path
      ? `⚙️ Im Hintergrund wird noch vorbereitet (${esc(prepLabel(pr))}). Das wird automatisch mit erledigt.` : '';
    if ($('prepnote').dataset.h !== prepNote) { $('prepnote').innerHTML = prepNote; $('prepnote').dataset.h = prepNote; }
    $('prepchip').hidden = !(pr.running && S.folder && pr.folder === S.folder.path) || !!j.running;
    if (!$('prepchip').hidden) { $('preplabel').textContent = prepLabel(pr); $('prepfill').style.width = prepPct(pr) + '%'; }
    $$('.jobbox').forEach(box => {
      if (box.dataset.job !== j.kind) { box.innerHTML = ''; return; }
      let h;
      if (j.running) {
        const p = pct(j), emo = CHEER[Math.floor(Date.now() / 4000) % CHEER.length];
        h = `<div class="job"><div class="head"><span class="emo">${emo}</span><span>Der Computer arbeitet …<br>
          <span class="muted">${esc(labelOf(j))}</span></span><span class="pct">${p}%</span></div>
          <div class="bar"><div style="width:${p}%"></div></div>
          <div class="sub">⏱️ läuft seit ${fmtDur(Date.now() / 1000 - j.started)}
            <span class="gap"></span><button class="big danger small" id="stopjob">⏹ Stopp</button></div>
          <details><summary>Was passiert gerade? (für Erwachsene)</summary><pre>${esc((j.log || []).join('\n'))}</pre></details></div>`;
      } else if (j.result === 'ok') {
        h = `<div class="job ok"><div class="head"><span class="emo">🎉</span><span>Super! ${esc(JOBDONE[j.kind])}</span></div>
          <div class="sub">Gedauert: ${fmtDur(j.ended - j.started)}</div></div>`;
      } else if (j.result === 'abgebrochen') {
        h = `<div class="job stop"><div class="head"><span class="emo">⏸️</span><span>Gestoppt. Du kannst jederzeit weitermachen –
          fertige Teile bleiben erhalten.</span></div></div>`;
      } else if (j.result === 'fehler') {
        h = `<div class="job err"><div class="head"><span class="emo">😕</span><span>Hoppla, da ist etwas schiefgegangen.</span></div>
          <div>${esc(j.error || '')}</div>
          <details><summary>Details (für Erwachsene)</summary><pre>${esc((j.log || []).join('\n'))}</pre></details></div>`;
      } else h = '';
      if (box.dataset.h !== h || j.running) {
        const det = box.querySelector('details'), open = det && det.open, pre = box.querySelector('pre');
        const atBottom = pre && pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
        box.innerHTML = h; box.dataset.h = h;
        const d2 = box.querySelector('details'); if (d2 && open) d2.open = true;
        const p2 = box.querySelector('pre'); if (p2 && (atBottom || !pre)) p2.scrollTop = p2.scrollHeight;
      }
    });
    const stop = $('stopjob');
    if (stop) stop.onclick = async () => { if (await ask('Wirklich stoppen? Fertige Teile bleiben erhalten.', 'Stoppen')) api('/api/cancel', {}); };

    $('minijob').hidden = !(j.running && JOBSTEP[j.kind] !== current);
    if (j.running) { $('minilabel').textContent = JOBNAME[j.kind] + ' ' + pct(j) + '%'; $('minifill').style.width = pct(j) + '%'; }
    if (wasRunning && !j.running) { mk.reloadMarks(); loadSchnitt(); }
    wasRunning = !!j.running;
  }

  function renderSteps() {
    $$('.step').forEach(b => {
      const n = +b.dataset.step, j = S.job || {};
      b.classList.toggle('active', n === current);
      b.classList.toggle('done', stepDone(n) && n !== current);
      b.classList.toggle('busy', !!j.running && JOBSTEP[j.kind] === n);
      b.disabled = !stepAllowed(n);
    });
  }

  // ------------------------------------------------------------ Vorschau + Korrekturen
  const pv = $('pv');
  const FIX = { schneiden: '✂ Rausschneiden', behalten: '✚ Wieder rein', kamera: '🎥 Kamera fest', weit: '🔭 Ganzes Feld' };
  const fx = { name: null, t: 0, data: null, fixes: [], bild: { crop_w: 0.5625, crop_y: 0.0972, x_min: 0, x_max: 1 },
               stale: false, sel: null, mode: 'vorschau' };
  const mmss = s => { s = Math.max(0, s); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(Math.floor(s % 60)).padStart(2, '0'); };
  const segsOf = () => (fx.data ? fx.data.segs : []);
  const curVid = () => vids().find(v => v.name === fx.name);

  function toOrig(tp) {                        // Zeit in der Vorschau -> Zeit im Originalvideo
    let acc = 0;
    for (const [a, b] of segsOf()) { if (tp < acc + (b - a)) return a + (tp - acc); acc += b - a; }
    const s = segsOf(); return s.length ? s[s.length - 1][1] : 0;
  }
  function toPrev(to) {                        // Zeit im Original -> Zeit in der Vorschau (oder null)
    let acc = 0;
    for (const [a, b] of segsOf()) { if (to >= a && to < b) return acc + (to - a); acc += b - a; }
    return null;
  }
  const origNow = () => (fx.mode === 'sicht' ? pv.currentTime : toOrig(pv.currentTime));
  function span() {
    const d = fx.data, ab = d ? d.abs : [];
    if (!ab.length) return [0, (d && d.dur) || 1];
    return [Math.min(...ab.map(x => x[0])), Math.max(...ab.map(x => x[1]))];
  }
  function gaps() {                            // rausgeschnittene Stellen innerhalb der Einsaetze
    const res = [];
    for (const [s, e] of (fx.data ? fx.data.abs : [])) {
      let t = s;
      for (const [a, b] of segsOf().filter(x => x[0] >= s - 0.01 && x[1] <= e + 0.01).sort((x, y) => x[0] - y[0])) {
        if (a - t > 0.2) res.push([t, a]);
        t = b;
      }
      if (e - t > 0.2) res.push([t, e]);
    }
    return res;
  }

  function setPlayer(mode, t) {
    const v = curVid();
    fx.mode = mode;
    const want = mode === 'sicht' ? media(playSrc(v)) : media(v.vorschau) + '&t=' + v.vorschau_t;
    if (pv.dataset.src !== want) { pv.dataset.src = want; pv.src = want; }
    if (t != null) {
      const go = () => { pv.currentTime = t; };
      pv.readyState >= 1 ? go() : pv.addEventListener('loadedmetadata', go, { once: true });
    }
    $('pvmode').hidden = mode !== 'sicht';
  }
  $('pvback').onclick = () => { const p = toPrev(origNow()); setPlayer('vorschau', p == null ? 0 : p); };

  async function selectVid(name) {
    fx.name = name; fx.sel = null; fx.data = null; $('campick').hidden = true;
    const v = curVid(); fx.t = v ? v.vorschau_t : 0;
    if (v && v.vorschau) setPlayer('vorschau', 0);
    await loadSchnitt();
  }
  async function loadSchnitt() {
    if (!fx.name) return;
    const r = await api('/api/schnitt?name=' + encodeURIComponent(fx.name));
    fx.data = r.schnitt; fx.fixes = r.fixes || []; if (r.bild) fx.bild = r.bild; fx.stale = r.stale;
    drawFix();
  }
  async function saveFixes() {
    const r = await api('/api/korrekturen', { name: fx.name, fixes: fx.fixes.map(f => ({ what: f.what, a: f.a, b: f.b, pos: f.pos })) });
    if (r.error) return tell('😕 ' + esc(r.error));
    fx.fixes = r.fixes; fx.stale = r.stale; drawFix();
  }
  function addFix(what, pos = 0.5) {
    if (S.job.running) return tell('Bitte warte, bis der Computer fertig ist. 🙂');
    const s = fx.sel;
    if (!s || s.b == null || s.b - s.a < 0.5)
      return tell('Wähle zuerst eine Stelle aus:<br>• <b>Start hier</b> und <b>Ende hier</b> drücken, oder<br>• auf ein <b>graues</b> Stück in der Leiste klicken.');
    fx.fixes.push({ what, a: s.a, b: s.b, pos });
    fx.sel = null; $('campick').hidden = true;
    saveFixes();
  }

  function drawFix() {
    const has = !!(fx.name && fx.data);
    $('fixpanel').hidden = !has;
    $('stalenote').hidden = !(has && fx.stale);
    if (!has) return;
    const [lo, hi] = span(), W = hi - lo || 1, X = t => ((t - lo) / W * 100) + '%', Wd = (a, b) => ((b - a) / W * 100) + '%';
    const B = $('cutbar'); B.innerHTML = '';
    const add = (cls, a, b, extra) => { const e = document.createElement('div'); e.className = cls;
      e.style.left = X(a); e.style.width = Wd(a, b); if (extra) extra(e); B.append(e); return e; };
    for (const [s, e] of fx.data.abs) add('cut', s, e);
    for (const [a, b] of segsOf()) add('in', a, b);
    for (const f of fx.fixes) add('fx ' + f.what, Math.max(lo, f.a), Math.min(hi, f.b));
    for (const t of fx.data.hl || []) if (t >= lo && t <= hi) { const e = document.createElement('div'); e.className = 'star';
      e.textContent = '⭐'; e.style.left = X(t); B.append(e); }
    if (fx.sel) add('selr', fx.sel.a, fx.sel.b == null ? fx.sel.a + W * 0.003 : fx.sel.b);
    const ph = document.createElement('div'); ph.className = 'ph'; ph.id = 'fxph'; B.append(ph);
    movePh();

    const s = fx.sel;
    $('seltext').innerHTML = !s ? 'Wähle eine Stelle: <b>Start</b> und <b>Ende</b> setzen oder ein graues Stück anklicken.'
      : s.b == null ? `Start: <b>${mmss(s.a)}</b> – jetzt bis zum Ende abspielen und <b>Ende hier</b> drücken.`
      : `Ausgewählt: <b>${mmss(s.a)} – ${mmss(s.b)}</b> (${Math.round(s.b - s.a)} s). Was soll damit passieren?`;
    const L = $('fixlist');
    L.innerHTML = fx.fixes.length ? '' : '<li class="muted" style="cursor:default">Noch keine Korrekturen.</li>';
    fx.fixes.forEach((f, i) => {
      const li = document.createElement('li');
      li.innerHTML = `<span>${FIX[f.what]}</span><span class="tt">${mmss(f.a)} – ${mmss(f.b)}</span>`
        + (f.what === 'kamera' ? `<span class="muted">${f.pos < 0.45 ? 'links' : f.pos > 0.55 ? 'rechts' : 'Mitte'}</span>` : '')
        + '<button class="x" title="Korrektur löschen">✕</button>';
      li.onclick = e => {
        if (e.target.closest('.x')) { fx.fixes.splice(i, 1); saveFixes(); return; }
        fx.sel = { a: f.a, b: f.b }; jumpTo(f.a); drawFix();
      };
      L.append(li);
    });
    const rp = $('runprev');
    if (!S.job.running) rp.textContent = fx.stale ? '🔄 Vorschau neu machen' : '▶ Vorschau machen';
  }
  function movePh() {
    const p = $('fxph'); if (!p || !fx.data) return;
    const [lo, hi] = span(), t = origNow();
    p.style.left = ((t - lo) / ((hi - lo) || 1) * 100) + '%';
    $('otime').textContent = mmss(t);
  }
  function jumpTo(t) {
    const p = toPrev(t);
    if (p != null) setPlayer('vorschau', p);
    else if (curVid() && playSrc(curVid())) setPlayer('sicht', t);
  }
  pv.addEventListener('timeupdate', movePh);

  $('cutbar').addEventListener('click', e => {
    if (!fx.data) return;
    const r = e.currentTarget.getBoundingClientRect(), [lo, hi] = span();
    const t = lo + (e.clientX - r.left) / r.width * (hi - lo);
    if (toPrev(t) != null) { setPlayer('vorschau', toPrev(t)); return; }
    const g = gaps().find(([a, b]) => t >= a && t <= b);
    if (g) {
      fx.sel = { a: g[0], b: g[1] };
      if (playSrc(curVid())) setPlayer('sicht', g[0]);
      drawFix();
      return;
    }
    tell('🪑 Hier sitzt er auf der Bank. Das kommt nicht ins Video.<br><span class="muted">Ändern kannst du das bei Schritt 3 (Markieren).</span>');
  });
  $('selstart').onclick = () => { fx.sel = { a: origNow(), b: null }; drawFix(); };
  $('selend').onclick = () => {
    const t = origNow();
    if (!fx.sel) return tell('Drück zuerst <b>Start hier</b>.');
    fx.sel = { a: Math.min(fx.sel.a, t), b: Math.max(fx.sel.a, t) }; drawFix();
  };
  $$('[data-fix]').forEach(b => b.onclick = () => addFix(b.dataset.fix));

  // Kamera-Position waehlen: gelber Rahmen = Bildausschnitt
  const camT = () => +$('campos').value / 1000;
  const camLeft = () => { const b = fx.bild; return b.x_min + camT() * Math.max(0, b.x_max - b.x_min - b.crop_w); };
  function drawCam() {
    const w = $('camwin'), b = fx.bild;
    w.style.left = (camLeft() * 100) + '%'; w.style.width = (b.crop_w * 100) + '%';
    w.style.top = (b.crop_y * 100) + '%'; w.style.height = (b.crop_w * 100) + '%';
  }
  $('camopen').onclick = () => {
    const s = fx.sel;
    if (!s || s.b == null) return addFix('kamera');          // zeigt den Hinweis
    $('camv').src = '/api/frame?name=' + encodeURIComponent(fx.name) + '&t=' + ((s.a + s.b) / 2).toFixed(1);
    $('campos').value = 500; drawCam(); $('campick').hidden = false;
  };
  $('campos').oninput = drawCam;
  $('camok').onclick = () => addFix('kamera', camLeft() + fx.bild.crop_w / 2);
  $('camcancel').onclick = () => { $('campick').hidden = true; };

  function renderPreview() {
    const list = vids().filter(v => v.vorschau);
    if (!list.some(v => v.name === fx.name)) {
      if (list.length) selectVid(list[0].name);
      else if (fx.name) { fx.name = null; fx.data = null; pv.removeAttribute('src'); pv.dataset.src = ''; drawFix(); }
    } else {
      const v = curVid();
      if (v.vorschau_t !== fx.t) {               // neue Vorschau fertig -> neu laden
        fx.t = v.vorschau_t; fx.sel = null;
        pv.dataset.src = ''; setPlayer('vorschau', 0); loadSchnitt();
      }
    }
    const h = list.map(v => `<button class="prevbtn ${v.name === fx.name ? 'sel' : ''}" data-prev="${esc(v.name)}">👀 ${esc(v.name)}
      <small>Vorschau ansehen & korrigieren</small></button>`).join('') || '<div class="muted">Klick auf „Vorschau machen“.</div>';
    if ($('prevlist').dataset.h !== h) { $('prevlist').innerHTML = h; $('prevlist').dataset.h = h; }
    $('pvempty').hidden = !!fx.name;
  }
  $('prevlist').addEventListener('click', e => { const b = e.target.closest('[data-prev]'); if (b && b.dataset.prev !== fx.name) selectVid(b.dataset.prev).then(renderPreview); });

  // ------------------------------------------------------------ Markieren
  const mk = (() => {
    const v = $('mv');
    const TYPES = { IN: { label: 'REIN', name: '🟢 Rein', color: '#86efac' },
                    OUT: { label: 'RAUS', name: '🔴 Raus', color: '#fca5a5' },
                    HL: { label: 'HL', name: '⭐ Highlight', color: '#fde047' } };
    let name = null, marks = [], hadFile = false, dirty = false, saveTimer = null, flashTimer = null;
    let rate = 1;                                   // gewaehltes Tempo, gilt auch fuer jedes neu geladene Video
    // Highlight-Sekunden merken (gelten fuer neue Videos ohne eigene Markierungen, 24 Stunden lang)
    const CLIPKEY = 'spielschnitt:clip';
    function rememberClip() {
      localStorage.setItem(CLIPKEY, JSON.stringify({ pre: +$('pre').value || 0, post: +$('post').value || 0, t: Date.now() }));
    }
    function lastClip() {
      try {
        const c = JSON.parse(localStorage.getItem(CLIPKEY) || 'null');
        if (c && Date.now() - c.t < 24 * 3600 * 1000) return c;
      } catch (e) { /* ignorieren */ }
      return { pre: 8, post: 3 };
    }
    const applyRate = () => { v.defaultPlaybackRate = rate; v.playbackRate = rate; };

    const fmt = s => {
      if (!isFinite(s)) return '--:--:--.--';
      const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
      return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + x.toFixed(2).padStart(5, '0');
    };
    const fmtShort = s => fmt(s).slice(0, 8);

    // gleiche Logik wie resolve_stints() in spielschnitt.py
    function stints() {
      const dur = v.duration || 0, res = [];
      const ev = marks.filter(m => m.type !== 'HL').sort((a, b) => a.t - b.t);
      let on = ev.length > 0 && ev[0].type === 'OUT', start = 0;
      for (const m of ev) {
        if (m.type === 'IN' && !on) { on = true; start = m.t; }
        else if (m.type === 'OUT' && on) { on = false; res.push([start, m.t]); }
      }
      if (on && dur) res.push([start, dur]);
      return res;
    }
    const onCourt = t => stints().some(([a, b]) => t >= a && t < b);

    function parse(text) {
      const out = { marks: [], pre: 8, post: 3 };
      for (const raw of (text || '').split(/\r?\n/)) {
        const line = raw.trim();
        let m = line.match(/^#\s*Clip:\s*([\d.]+)\s*s davor,\s*([\d.]+)\s*s danach/);
        if (m) { out.pre = +m[1]; out.post = +m[2]; continue; }
        m = line.match(/^(REIN|RAUS|HL)\s+([\d:.]+)(?:\s*\|\s*(.*))?$/i);
        if (m) {
          const t = m[2].split(':').reduce((a, x) => a * 60 + parseFloat(x), 0);
          out.marks.push({ type: { REIN: 'IN', RAUS: 'OUT', HL: 'HL' }[m[1].toUpperCase()], t, note: m[3] || '' });
        }
      }
      return out;
    }
    function exportText() {
      const L = ['# Spielschnitt-Marker', '# Video: ' + name,
        '# Clip: ' + (+$('pre').value || 0) + ' s davor, ' + (+$('post').value || 0) + ' s danach',
        '# Typ  Zeit (hh:mm:ss.ss im Video) | Notiz'];
      for (const m of marks.slice().sort((a, b) => a.t - b.t))
        L.push(TYPES[m.type].label.padEnd(5) + fmt(m.t) + (m.note ? ' | ' + m.note.replace(/[\r\n]/g, ' ') : ''));
      return L.join('\r\n') + '\r\n';
    }

    function changed() {
      dirty = true; draw();
      $('saved').textContent = '… wird gespeichert';
      clearTimeout(saveTimer); saveTimer = setTimeout(save, 600);
    }
    async function save() {
      clearTimeout(saveTimer);
      if (!name || !dirty) return;
      if (!marks.length && !hadFile) { dirty = false; $('saved').textContent = ''; return; }
      dirty = false;
      try {
        const r = await api('/api/marker', { name, text: exportText() });
        if (r.error) throw new Error(r.error);
        hadFile = true;
        $('saved').textContent = '✓ Automatisch gespeichert';
        refresh();
      } catch (e) { dirty = true; $('saved').textContent = '⚠️ Speichern hat nicht geklappt – versuche es gleich nochmal'; }
    }

    async function load(vid) {
      await save();
      name = vid.name; marks = []; hadFile = false; dirty = false;
      $('saved').textContent = '';
      const r = await api('/api/marker?name=' + encodeURIComponent(name));
      if (r.text != null) {
        const p = parse(r.text); marks = p.marks; $('pre').value = p.pre; $('post').value = p.post; hadFile = true;
      } else { const c = lastClip(); $('pre').value = c.pre; $('post').value = c.post; }
      v.src = media(playSrc(vid));
      applyRate();
      $('mempty').hidden = true;
      v.addEventListener('loadedmetadata', draw, { once: true });
      draw(); renderPicker();
    }
    async function reloadMarks() {           // nach "Videos erstellen" sind Marker evtl. geloescht
      if (!name) return;
      const vid = vids().find(x => x.name === name);
      if (!vid || !playSrc(vid)) reset();
    }
    function reset() {
      name = null; marks = []; hadFile = false; dirty = false;
      v.pause(); v.removeAttribute('src'); v.load();
      $('mempty').hidden = false; $('saved').textContent = ''; draw(); renderPicker();
    }

    function add(type) {
      if (!name || !v.src) return;
      const t = v.currentTime;
      if (marks.some(m => m.type === type && Math.abs(m.t - t) < 0.5)) return;
      marks.push({ type, t, note: '' });
      flash(TYPES[type].name + ' bei ' + fmtShort(t), TYPES[type].color);
      changed();
    }
    function undoNearest() {
      if (!marks.length) return;
      let i = 0, best = 1e9;
      marks.forEach((m, j) => { const d = Math.abs(m.t - v.currentTime); if (d < best) { best = d; i = j; } });
      const m = marks.splice(i, 1)[0];
      flash('Gelöscht: ' + TYPES[m.type].name, '#e9d5ff');
      changed();
    }
    function flash(text, color) {
      const f = $('flash'); f.textContent = text; f.style.background = color; f.classList.add('on');
      clearTimeout(flashTimer); flashTimer = setTimeout(() => f.classList.remove('on'), 1000);
    }

    function draw() {
      marks.sort((a, b) => a.t - b.t);
      const L = $('marks'); L.innerHTML = '';
      if (!marks.length) L.innerHTML = `<li class="none">${name ? 'Noch keine Markierungen. Drück E, A oder H!' : 'Wähle ein Video aus.'}</li>`;
      marks.forEach((m, i) => {
        const li = document.createElement('li');
        li.innerHTML = `<span class="ty">${TYPES[m.type].name}</span><span class="tt">${fmtShort(m.t)}</span><button class="x" title="Löschen">✕</button>`;
        li.querySelector('.tt').onclick = () => { v.currentTime = Math.max(0, m.t - (m.type === 'HL' ? (+$('pre').value || 0) : 2)); v.play(); };
        li.querySelector('.x').onclick = () => { marks.splice(i, 1); changed(); };
        L.append(li);
      });
      const st = stints(), tot = st.reduce((s, [a, b]) => s + b - a, 0), nh = marks.filter(m => m.type === 'HL').length;
      $('msum').innerHTML = name ? `🏀 Auf dem Feld: <b>${Math.floor(tot / 60)}:${String(Math.round(tot % 60)).padStart(2, '0')} Min</b>
        &nbsp; ⭐ Highlights: <b>${nh}</b>` + (nh && marks.some(m => m.type === 'HL' && !onCourt(m.t))
        ? '<span class="warn">Achtung: ein Highlight ist, während er auf der Bank sitzt.</span>' : '') : '';
      drawBar(); status();
    }
    function drawBar() {
      const B = $('tl'); B.innerHTML = ''; const d = v.duration;
      if (d && name) {
        for (const [a, b] of stints()) { const e = document.createElement('div'); e.className = 'on';
          e.style.left = (a / d * 100) + '%'; e.style.width = ((b - a) / d * 100) + '%'; B.append(e); }
        for (const m of marks.filter(m => m.type === 'HL')) { const e = document.createElement('div'); e.className = 'star';
          e.textContent = '⭐'; e.style.left = (m.t / d * 100) + '%'; B.append(e); }
      }
      const ph = document.createElement('div'); ph.className = 'ph'; ph.id = 'ph'; B.append(ph); movePh();
    }
    function movePh() { const p = $('ph'); if (p) p.style.left = (v.duration ? v.currentTime / v.duration * 100 : 0) + '%'; }
    function status() {
      const s = $('courtstatus');
      if (!name) { s.textContent = ''; return; }
      const on = onCourt(v.currentTime);
      s.textContent = on ? '🏀 AUF DEM FELD' : '🪑 BANK';
      s.style.background = on ? '#22c55e' : '#e5e7eb'; s.style.color = on ? '#fff' : '#374151';
    }
    function renderPicker() {
      const list = vids();
      const h = list.map(x => {
        const done = x.marker && (x.marker.wechsel || x.marker.hl);
        const ok = !!playSrc(x);
        return `<button class="vchip ${x.name === name ? 'sel' : ''}" data-vid="${esc(x.name)}" ${ok ? '' : 'disabled title="Wird gerade vorbereitet"'}>
          ${done ? '✅' : '🎥'} ${esc(x.name)} ${ok ? '' : '<span class="d">(wird vorbereitet …)</span>'}</button>`;
      }).join('');
      if ($('vidpick').dataset.h !== h) { $('vidpick').innerHTML = h; $('vidpick').dataset.h = h; }
    }
    $('vidpick').addEventListener('click', e => {
      const b = e.target.closest('[data-vid]'); if (!b || b.disabled) return;
      const vid = vids().find(x => x.name === b.dataset.vid); if (vid && vid.name !== name) load(vid);
    });

    $('tl').onclick = e => { if (v.duration) { const r = e.currentTarget.getBoundingClientRect(); v.currentTime = (e.clientX - r.left) / r.width * v.duration; } };
    v.addEventListener('timeupdate', () => { $('now').textContent = fmtShort(v.currentTime); movePh(); status(); });
    // Tempo nach jedem Laden und Start erneut setzen (Browser setzen es beim Laden zurueck)
    v.addEventListener('loadedmetadata', applyRate);
    v.addEventListener('play', () => { if (v.playbackRate !== rate) applyRate(); $('playbtn').textContent = '⏸ Pause'; });
    v.addEventListener('pause', () => $('playbtn').textContent = '▶ Abspielen');
    v.onclick = () => togglePlay();
    const togglePlay = () => { if (!name) return; v.paused ? v.play() : v.pause(); };
    $('playbtn').onclick = togglePlay;
    $$('[data-seek]').forEach(b => b.onclick = () => { v.currentTime = Math.max(0, v.currentTime + +b.dataset.seek); });
    $$('[data-rate]').forEach(b => b.onclick = () => {
      rate = +b.dataset.rate; applyRate(); $$('[data-rate]').forEach(x => x.classList.toggle('sel', x === b));
    });
    document.querySelector('[data-rate="1"]').classList.add('sel');
    $$('[data-mark]').forEach(b => b.onclick = () => add(b.dataset.mark));
    $('undo').onclick = undoNearest;
    $('pre').onchange = $('post').onchange = () => { rememberClip(); if (name) changed(); };

    document.addEventListener('keydown', e => {
      if (current !== 3 || !$('modal').hidden || !name) return;
      if (e.target.tagName === 'INPUT' || e.ctrlKey || e.altKey || e.metaKey) return;
      const k = e.key.toLowerCase();
      if (k === 'e') add('IN'); else if (k === 'a') add('OUT'); else if (k === 'h') add('HL');
      else if (k === 'z') undoNearest();
      else if (k === ' ') togglePlay();
      else if (k === 'arrowleft') v.currentTime = Math.max(0, v.currentTime - 5);
      else if (k === 'arrowright') v.currentTime += 5;
      else if (k === 'j') v.currentTime = Math.max(0, v.currentTime - 1);
      else if (k === 'l') v.currentTime += 1;
      else if (k === ',') { v.pause(); v.currentTime = Math.max(0, v.currentTime - 1 / 29.97); }
      else if (k === '.') { v.pause(); v.currentTime += 1 / 29.97; }
      else return;
      e.preventDefault();
    });

    draw();
    return { flush: save, pause: () => v.pause(), reset, reloadMarks, renderPicker, get name() { return name; } };
  })();

  // ------------------------------------------------------------ Bildausschnitt pro Spiel
  // Gelber Rahmen = was im fertigen Video zu sehen ist (Groesse + Hoehe frei waehlbar, immer 16:9).
  // Graue Griffe links/rechts = so weit darf die Kamera schwenken; dahinter wird nie etwas gezeigt.
  const bild = (() => {
    const st = { videos: [], b: null, std: null, loadedFor: null, vid: null, t: 0, x: null, dirty: false };
    const img = $('bimg'), stage = $('bstage');
    const chf = () => st.b.crop_w;                     // Fensterhoehe relativ (16:9-Video)

    async function open() {
      if (!S.folder) return;
      if (st.loadedFor === S.folder.path && st.b) { draw(); return; }
      const r = await api('/api/bild');
      if (r.error) return;
      st.videos = r.videos; st.b = r.bild; st.std = r.standard; st.loadedFor = S.folder.path; st.dirty = false;
      st.vid = st.videos.length ? st.videos[0].name : null;
      st.t = st.videos.length ? Math.round(st.videos[0].dur * 0.3) : 0;
      st.x = null;
      $('bvid').innerHTML = st.videos.map(v => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join('');
      const v0 = st.videos[0];
      $('btime').max = v0 ? Math.floor(v0.dur) : 0; $('btime').value = st.t; $('btimetxt').textContent = mmss(st.t);
      loadFrame(); draw();
    }
    function reset() { st.loadedFor = null; st.b = null; }
    function loadFrame() {
      if (!st.vid) return;
      $('bload').hidden = false;
      img.onload = () => { $('bload').hidden = true; };
      img.src = '/api/frame?name=' + encodeURIComponent(st.vid) + '&t=' + st.t;
    }
    function clamp(b) {
      b.crop_w = Math.min(1, Math.max(0.3, b.crop_w));
      b.crop_y = Math.min(1 - chf(), Math.max(0, b.crop_y));
      b.x_min = Math.min(1, Math.max(0, b.x_min)); b.x_max = Math.min(1, Math.max(0, b.x_max));
      if (b.x_max - b.x_min < b.crop_w) {
        const m = Math.min(1 - b.crop_w / 2, Math.max(b.crop_w / 2, (b.x_min + b.x_max) / 2));
        b.x_min = m - b.crop_w / 2; b.x_max = m + b.crop_w / 2;
      }
    }
    function winX() {                                  // linke Kante des gelben Rahmens (Vorschau-Position)
      const b = st.b, lo = b.x_min, hi = b.x_max - b.crop_w;
      if (st.x == null) st.x = (lo + hi) / 2;
      st.x = Math.min(hi, Math.max(lo, st.x));
      return st.x;
    }
    function draw() {
      if (!st.b) return;
      const b = st.b, P = v => (v * 100) + '%';
      Object.assign($('bwin').style, { left: P(winX()), width: P(b.crop_w), top: P(b.crop_y), height: P(chf()) });
      Object.assign($('bshadeL').style, { width: P(b.x_min) });
      Object.assign($('bshadeR').style, { width: P(1 - b.x_max) });
      $('bhandleL').style.left = P(b.x_min); $('bhandleR').style.left = P(b.x_max);
      $('bzoom').value = Math.round(b.crop_w * 100);
      const full = b.crop_w >= 0.999;
      $('binfo').innerHTML = full ? 'Ganzes Bild: kein Zoom, keine Kamerabewegung.'
        : `Zoom: <b>${Math.round(100 / b.crop_w) / 100}×</b> · Die Kamera schwenkt zwischen den grauen Griffen.`;
      $('bsave').disabled = !st.dirty;
      $('bsaved').textContent = st.dirty ? '' : (S.folder && S.folder.bild_gesetzt ? '✓ Für dieses Spiel gespeichert' : '');
    }
    function changed() { clamp(st.b); st.dirty = true; draw(); }

    // Ziehen: Rahmen verschieben (hoch/runter = Bildausschnitt, links/rechts = nur Probe), Griffe = Schwenkbereich
    let drag = null;
    function rel(e) { const r = stage.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; }
    stage.addEventListener('pointerdown', e => {
      if (!st.b) return;
      const [x, y] = rel(e), t = e.target;
      if (t.id === 'bhandleL' || t.id === 'bhandleR') drag = { kind: t.id, x0: x };
      else if (t.id === 'bcorner') drag = { kind: 'zoom', x0: x, w0: st.b.crop_w, left: winX() };
      else if (t.closest('#bwin')) drag = { kind: 'move', x0: x, y0: y, wx: winX(), cy: st.b.crop_y };
      else return;
      stage.setPointerCapture(e.pointerId); e.preventDefault();
    });
    stage.addEventListener('pointermove', e => {
      if (!drag) return;
      const [x, y] = rel(e), b = st.b;
      if (drag.kind === 'move') { b.crop_y = drag.cy + (y - drag.y0); st.x = drag.wx + (x - drag.x0); }
      else if (drag.kind === 'bhandleL') b.x_min = Math.min(x, b.x_max - b.crop_w);
      else if (drag.kind === 'bhandleR') b.x_max = Math.max(x, b.x_min + b.crop_w);
      else if (drag.kind === 'zoom') { b.crop_w = Math.max(0.3, Math.min(1, x - drag.left)); st.x = drag.left; }
      changed();
    });
    const end = () => { drag = null; };
    stage.addEventListener('pointerup', end); stage.addEventListener('pointercancel', end);

    $('bzoom').oninput = () => { const b = st.b, c = winX() + b.crop_w / 2; b.crop_w = +$('bzoom').value / 100;
      st.x = c - b.crop_w / 2; changed(); };
    $('bvid').onchange = () => { st.vid = $('bvid').value; const v = st.videos.find(x => x.name === st.vid);
      $('btime').max = Math.floor(v.dur); st.t = Math.min(st.t, Math.floor(v.dur)); $('btime').value = st.t; loadFrame(); };
    let tt = null;
    $('btime').oninput = () => { st.t = +$('btime').value; $('btimetxt').textContent = mmss(st.t);
      clearTimeout(tt); tt = setTimeout(loadFrame, 250); };
    $('bfull').onclick = () => { Object.assign(st.b, { crop_w: 1, crop_y: 0, x_min: 0, x_max: 1 }); st.x = 0; changed(); };
    $('bstd').onclick = () => { st.b = Object.assign({}, st.std); st.x = null; changed(); };
    $('bsave').onclick = async () => {
      const r = await api('/api/bild', { bild: st.b });
      if (r.error) return tell('😕 ' + esc(r.error));
      st.b = r.bild; st.dirty = false; await refresh(); draw();
    };
    $('bnext').onclick = async () => {
      if (st.dirty && await ask('Den Bildausschnitt für dieses Spiel speichern?', 'Ja, speichern')) $('bsave').onclick();
      else if (!S.folder.bild_gesetzt && !st.dirty) api('/api/bild', { bild: st.b }).then(refresh);   // Standard bestaetigen
      go(3);
    };
    function render() { if (current === 2 && st.b) draw(); }
    return { open, reset, render };
  })();

  // ------------------------------------------------------------ Gesamt
  function render() {
    $('noffmpeg').hidden = S.ffmpeg !== false;
    $('ver').textContent = S.version ? 'v' + S.version : '';
    renderSteps(); renderFolder(); renderJob(); renderPreview(); mk.renderPicker(); bild.render();
    ensurePrepared();
  }

  window.addEventListener('beforeunload', e => {
    mk.flush();
    if (S.job && S.job.running) { e.preventDefault(); e.returnValue = ''; }
  });

  (async () => {
    await refresh();
    const j = S.job || {};
    go(j.running ? JOBSTEP[j.kind] : (S.folder && S.folder.videos.length && !S.folder.results.length ? (stepDone(2) ? 3 : 2) : 1));
    setInterval(refresh, 1000);
  })();
})();
