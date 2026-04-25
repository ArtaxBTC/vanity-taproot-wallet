/* app.js — Vanity Wallet UI */
'use strict';

// Vanity Wallet always runs on port 5003 — use absolute URL so API calls
// work both standalone and when embedded as an iframe in inscribator.
const API = 'http://localhost:5003';

// ── Helpers ───────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }
function el(tag, attrs, text) {
  const e = document.createElement(tag);
  if (attrs) Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else e.setAttribute(k, v);
  });
  if (text !== undefined) e.textContent = text;
  return e;
}

function fmtNum(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

function fmtTime(s) {
  if (s < 120)    return `~${Math.round(s)}s`;
  if (s < 7200)   return `~${Math.round(s / 60)} min`;
  if (s < 172800) return `~${(s / 3600).toFixed(1)}h`;
  return `~${(s / 86400).toFixed(1)} days`;
}

// ── Pattern builder ───────────────────────────────────────────────────────

const BECH32M = new Set('qpzry9x8gf2tvdw0s3jn54khce6mua7l');
const PAT_PAGE_SIZE = 10;
let _patterns = [];   // source of truth: [{leading, trailing, or_mode}]
let _patPage  = 1;
let _patPages = 1;

function _flushPage() {
  const start = (_patPage - 1) * PAT_PAGE_SIZE;
  $('patternList').querySelectorAll('.pattern-block').forEach((block, i) => {
    if (start + i >= _patterns.length) return;
    _patterns[start + i] = {
      leading:  block.querySelector('input[id^="lead_"]').value.trim(),
      trailing: block.querySelector('input[id^="trail_"]').value.trim(),
      or_mode:  block.querySelector('input[type=checkbox]').checked,
    };
  });
}

function _renderPatterns(page) {
  _flushPage();
  _patPages = Math.max(1, Math.ceil(_patterns.length / PAT_PAGE_SIZE));
  _patPage  = Math.max(1, Math.min(page, _patPages));
  const start = (_patPage - 1) * PAT_PAGE_SIZE;
  const slice = _patterns.slice(start, start + PAT_PAGE_SIZE);
  $('patternList').innerHTML = '';
  slice.forEach((pat, i) => _buildPatternBlock(pat, start + i));
  // pager
  const pager = $('patternPager');
  pager.style.display = _patterns.length > PAT_PAGE_SIZE ? 'flex' : 'none';
  $('patPgInput').value = _patPage;
  $('patPgTotal').textContent = `/ ${_patPages}`;
  $('patPgFirst').disabled = $('patPgPrev').disabled = _patPage <= 1;
  $('patPgLast').disabled  = $('patPgNext').disabled  = _patPage >= _patPages;
}

function _buildPatternBlock(data, globalIndex) {
  data = data || {};
  const block = el('div', { class: 'pattern-block', 'data-idx': globalIndex });
  const row   = el('div', { class: 'pattern-block-row' });

  // Leading
  const fldLead = el('div', { class: 'field' });
  const lblLead = el('label'); lblLead.htmlFor = `lead_${globalIndex}`; lblLead.textContent = 'Leading';
  const inpLead = el('input', { type: 'text', id: `lead_${globalIndex}`, placeholder: 'e.g. dead', maxlength: '12', autocomplete: 'off' });
  inpLead.value = data.leading || '';
  inpLead.addEventListener('input', () => sanitizeInput(inpLead));
  fldLead.append(lblLead, inpLead);

  // Trailing
  const fldTrail = el('div', { class: 'field' });
  const lblTrail = el('label'); lblTrail.htmlFor = `trail_${globalIndex}`; lblTrail.textContent = 'Trailing';
  const inpTrail = el('input', { type: 'text', id: `trail_${globalIndex}`, placeholder: 'e.g. cafe', maxlength: '12', autocomplete: 'off' });
  inpTrail.value = data.trailing || '';
  inpTrail.addEventListener('input', () => sanitizeInput(inpTrail));
  fldTrail.append(lblTrail, inpTrail);

  // Remove button — hidden on the first row (index 0), always
  const rmBtn = el('button', { class: 'pattern-remove', title: 'Remove' }, '✕');
  if (globalIndex === 0) rmBtn.style.visibility = 'hidden';
  rmBtn.addEventListener('click', () => {
    _flushPage();
    _patterns.splice(globalIndex, 1);
    if (_patterns.length === 0) _patterns.push({ leading: '', trailing: '', or_mode: false });
    _renderPatterns(_patPage);
  });

  row.append(fldLead, fldTrail, rmBtn);

  // Footer: OR mode checkbox + ETA
  const footer  = el('div', { class: 'pattern-footer' });
  const orLabel = el('label', { class: 'checkbox-row' });
  const orChk   = el('input', { type: 'checkbox' });
  orChk.checked = data.or_mode || false;
  orLabel.append(orChk, document.createTextNode(' OR mode (either end — halves search time)'));
  const etaSpan = el('span', { style: 'font-size:.75rem;color:var(--text-dim)' });
  footer.append(orLabel, etaSpan);

  function _updateEta() {
    const lead  = inpLead.value.trim();
    const trail = inpTrail.value.trim();
    const or    = orChk.checked;
    if (!lead && !trail) { etaSpan.textContent = ''; return; }
    let p = 0;
    if (lead && trail && !or) {
      p = (1 / Math.pow(32, lead.length)) * (1 / Math.pow(32, trail.length));
    } else if (lead && trail && or) {
      p = 1/Math.pow(32, lead.length) + 1/Math.pow(32, trail.length);
    } else if (lead && or) {
      p = 2 / Math.pow(32, lead.length);
    } else if (lead) {
      p = 1 / Math.pow(32, lead.length);
    } else if (trail) {
      p = 1 / Math.pow(32, trail.length);
    }
    if (p <= 0) { etaSpan.textContent = ''; return; }
    const exp  = Math.round(1 / p);
    const rate = Number($('benchmarkInfo')?.dataset.rate || 600);
    etaSpan.textContent = `~${fmtNum(exp)} attempts · ${fmtTime(exp / rate)}`;
  }
  inpLead.addEventListener('input', _updateEta);
  inpTrail.addEventListener('input', _updateEta);
  orChk.addEventListener('change', _updateEta);
  _updateEta();

  block.append(row, footer);
  $('patternList').appendChild(block);
}

function addPatternBlock(data) {
  _flushPage();
  _patterns.push({
    leading:  (data && data.leading)  || '',
    trailing: (data && data.trailing) || '',
    or_mode:  !!(data && data.or_mode),
  });
  _renderPatterns(Math.ceil(_patterns.length / PAT_PAGE_SIZE));
}

function sanitizeInput(inp) {
  const v = inp.value.toLowerCase().replace(/[^qpzry9x8gf2tvdw0s3jn54khce6mua7l]/g, '');
  if (inp.value !== v) inp.value = v;
}

// Pager wiring
$('patPgFirst').addEventListener('click',  () => _renderPatterns(1));
$('patPgPrev').addEventListener('click',   () => _renderPatterns(_patPage - 1));
$('patPgNext').addEventListener('click',   () => _renderPatterns(_patPage + 1));
$('patPgLast').addEventListener('click',   () => _renderPatterns(_patPages));
$('patPgInput').addEventListener('change', () => {
  const v = parseInt($('patPgInput').value, 10);
  if (!isNaN(v)) _renderPatterns(v);
});

$('btnAddPattern').addEventListener('click', e => { e.preventDefault(); addPatternBlock(); });

// Start with one empty pattern row
_patterns.push({ leading: '', trailing: '', or_mode: false });
_renderPatterns(1);

// ── Collect patterns ──────────────────────────────────────────────────────

function getPatterns() {
  _flushPage();
  return _patterns.filter(p => p.leading || p.trailing);
}

// ── Import / Export patterns ──────────────────────────────────────────────

$('btnExportPatterns').addEventListener('click', () => {
  const patterns = getPatterns();
  if (!patterns.length) { alert('No patterns to export.'); return; }
  const blob = new Blob([JSON.stringify(patterns, null, 2)], { type: 'application/json' });
  const a = el('a', { href: URL.createObjectURL(blob), download: 'vanity_patterns.json' });
  a.click();
});

$('btnImportPatterns').addEventListener('click', () => $('importFile').click());
$('importFile').addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    try {
      const arr = JSON.parse(ev.target.result);
      if (!Array.isArray(arr)) throw new Error('Expected array');
      const imported = arr.map(p => ({
        leading:  ((p.leading  || '').toLowerCase().replace(/[^qpzry9x8gf2tvdw0s3jn54khce6mua7l]/g, '')),
        trailing: ((p.trailing || '').toLowerCase().replace(/[^qpzry9x8gf2tvdw0s3jn54khce6mua7l]/g, '')),
        or_mode:  !!p.or_mode,
      })).filter(p => p.leading || p.trailing);
      if (!imported.length) throw new Error('No valid patterns');
      _patterns = imported;
      $('patternList').innerHTML = '';
      _renderPatterns(1);
    } catch {
      alert('Invalid patterns file.');
    }
    $('importFile').value = '';
  };
  reader.readAsText(file);
});

// ── Benchmark ─────────────────────────────────────────────────────────────

async function loadBenchmark() {
  try {
    const words = $('selWords').value;
    const r = await fetch(`${API}/api/benchmark?words=${words}`);
    const d = await r.json();
    const el = $('benchmarkInfo');
    el.textContent = `CPU: ${d.cores} cores · ${d.rate_per_core.toLocaleString()} addr/s/core · ${d.rate_total.toLocaleString()} addr/s total`;
    el.dataset.rate = d.rate_total;
    // update all pattern ETAs
    $('patternList').querySelectorAll('input[id^="lead_"]').forEach(inp => inp.dispatchEvent(new Event('input')));
  } catch {
    $('benchmarkInfo').textContent = 'Benchmark unavailable.';
  }
}

$('selWords').addEventListener('change', loadBenchmark);
loadBenchmark();

// ── Checkpoint banner ─────────────────────────────────────────────────────

let _ckptData = null;

async function checkCheckpoint() {
  try {
    const r = await fetch(`${API}/api/checkpoint`);
    const d = await r.json();
    if (!d || d.found) return;
    _ckptData = d;
    const banner = $('checkpointBanner');
    const pct = d.total_attempts && d.expected
      ? ` (${(d.total_attempts / d.expected * 100).toFixed(1)}%)`
      : '';
    $('ckptInfo').textContent =
      `Previous session: ${(d.total_attempts || 0).toLocaleString()} attempts${pct} — resume or discard?`;
    banner.style.display = 'flex';
  } catch { /* ignore */ }
}

$('btnCkptResume').addEventListener('click', () => {
  $('checkpointBanner').style.display = 'none';
  if (!_ckptData) return;

  // Reconstruct pattern list from checkpoint
  const restored = [];
  (_ckptData.prefixes || []).forEach(p  => restored.push({ leading: p,    trailing: '',    or_mode: false }));
  (_ckptData.suffixes || []).forEach(s  => restored.push({ leading: '',    trailing: s,     or_mode: false }));
  (_ckptData.nopref   || []).forEach(n  => restored.push({ leading: n,    trailing: '',    or_mode: true  }));
  (_ckptData.pairs    || []).forEach(pr => restored.push({ leading: pr[0], trailing: pr[1], or_mode: false }));

  if (restored.length) {
    _patterns = restored;
    $('patternList').innerHTML = '';
    _renderPatterns(1);
  }

  // Start mining immediately — checkpoint file still on disk so vw.run() will resume from it
  startMining();
});

$('btnCkptClear').addEventListener('click', async () => {
  await fetch(`${API}/api/checkpoint/clear`, { method: 'POST' });
  $('checkpointBanner').style.display = 'none';
});

checkCheckpoint();

// ── SSE & mining control ──────────────────────────────────────────────────

let _sse = null;
let _running = false;

$('btnStart').addEventListener('click', startMining);
$('btnStop').addEventListener('click',  stopMining);

async function startMining() {
  const patterns = getPatterns();
  const only_digits  = $('chkOnlyDigits').checked;
  const only_letters = $('chkOnlyLetters').checked;

  if (!patterns.length && !only_digits && !only_letters) {
    alert('Add at least one search pattern.');
    return;
  }

  const body = {
    patterns,
    only_digits,
    only_letters,
    words_count:  parseInt($('selWords').value),
    wallet_index: 0,
    workers:      parseInt($('inpWorkers').value) || null,
    passphrase:   '',
  };

  const r = await fetch(`${API}/api/start`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    alert(d.error || 'Failed to start.');
    return;
  }

  _running = true;
  setRunningUI(true);
  openSSE();
}

async function stopMining() {
  await fetch(`${API}/api/stop`, { method: 'POST' });
}

let _startTime = null;
let _elapsedTimer = null;

function setRunningUI(running) {
  $('btnStart').disabled  = running;
  $('btnStop').disabled   = !running;
  $('progressSection').style.display = running ? 'block' : 'none';
  if (running) {
    _startTime = Date.now();
    $('mineStatusLabel').textContent = '⛏ Mining…';
    $('mineStatusLabel').style.color = 'var(--accent)';
    $('statAttempts').textContent = '—';
    $('statRate').textContent     = '—';
    $('statEta').textContent      = '—';
    $('progressBar').style.width  = '0%';
    clearInterval(_elapsedTimer);
    _elapsedTimer = setInterval(() => {
      const s = Math.floor((Date.now() - _startTime) / 1000);
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      $('mineElapsed').textContent = h
        ? `${h}h ${m}m ${sec}s`
        : m ? `${m}m ${sec}s` : `${sec}s`;
    }, 1000);
  } else {
    clearInterval(_elapsedTimer);
    _elapsedTimer = null;
  }
}

function openSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource(`${API}/api/stream`);

  _sse.onmessage = e => {
    const d = JSON.parse(e.data);

    if (d.type === 'progress') {
      const total = d.total || 0;
      const rate  = d.rate  || 0;
      const pct   = Math.min(d.pct || 0, 100);
      $('statAttempts').textContent = total.toLocaleString();
      $('statRate').textContent     = rate >= 1000
        ? (rate / 1000).toFixed(1) + 'K/s'
        : rate + '/s';
      if (d.eta_sec != null && d.eta_sec > 0) {
        $('statEta').textContent = fmtTime(d.eta_sec);
      } else if (rate > 0 && d.expected > 0) {
        const remaining = Math.max(0, (d.expected - total) / rate);
        $('statEta').textContent = fmtTime(remaining);
      }
      $('progressBar').style.width = pct + '%';
    }

    if (d.type === 'found') {
      _sse.close(); _sse = null;
      _running = false;
      setRunningUI(false);
      fetchAndShowResult();
    }

    if (d.type === 'stopped') {
      _sse.close(); _sse = null;
      _running = false;
      setRunningUI(false);
      $('mineStatusLabel').textContent = 'Stopped';
      $('mineStatusLabel').style.color = 'var(--text-dim)';
      $('progressSection').style.display = 'block';
    }
  };

  _sse.onerror = () => {
    if (_running) {
      // reconnect
      setTimeout(openSSE, 2000);
    }
  };
}

// ── Display result ────────────────────────────────────────────────────────

async function fetchAndShowResult() {
  const r = await fetch(`${API}/api/result`);
  const d = await r.json();
  if (!d) return;

  $('mineStatusLabel').textContent = `✓ Found in ${fmtNum(d.attempts || 0)} attempts`;
  $('mineStatusLabel').style.color = 'var(--green)';
  $('progressSection').style.display = 'block';

  // Highlight matched prefix/suffix in address
  const addr = d.bc1p || '';
  const mp   = d.matched_prefix || '';
  const ms   = d.matched_suffix || '';
  const addrEl = $('resAddress');
  addrEl.innerHTML = '';
  if (mp && addr.startsWith('bc1p' + mp)) {
    addrEl.appendChild(document.createTextNode('bc1p'));
    addrEl.appendChild(Object.assign(el('span', { class: 'highlight' }), { textContent: mp }));
    const rest = addr.slice(4 + mp.length);
    if (ms && rest.endsWith(ms)) {
      addrEl.appendChild(document.createTextNode(rest.slice(0, -ms.length)));
      addrEl.appendChild(Object.assign(el('span', { class: 'highlight' }), { textContent: ms }));
    } else {
      addrEl.appendChild(document.createTextNode(rest));
    }
  } else {
    addrEl.textContent = addr;
  }

  $('resAddressQ').textContent = d.bc1q || '';

  // Mnemonic grid
  const grid = $('resMnemonic');
  grid.innerHTML = '';
  const words = (d.mnemonic || '').split(' ');
  words.forEach((w, i) => {
    const cell = el('div', { class: 'mnemonic-word' });
    const num  = el('span', { class: 'num' }, `${i + 1}.`);
    cell.append(num, document.createTextNode(w));
    grid.appendChild(cell);
  });

  $('resultSection').style.display = 'block';
  $('resultSection').scrollIntoView({ behavior: 'smooth' });

}

// ── New search ────────────────────────────────────────────────────────────

$('btnPurgeRAM').addEventListener('click', async () => {
  // wipe in-memory result from server RAM
  await fetch(`${API}/api/result/clear`, { method: 'POST' }).catch(() => {});
  $('resultSection').style.display = 'none';
  $('progressSection').style.display = 'none';
  $('progressBar').style.width = '0%';
  $('statAttempts').textContent = '—';
  $('statRate').textContent     = '—';
  $('statEta').textContent      = '—';
  $('mineStatusLabel').textContent = '⛏ Mining…';
  $('mineStatusLabel').style.color = 'var(--accent)';
  $('mineElapsed').textContent  = '';
  _patterns = [{ leading: '', trailing: '', or_mode: false }];
  $('patternList').innerHTML = '';
  _renderPatterns(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

// ── On load: check if mining is already running ───────────────────────────

(async () => {
  try {
    const r = await fetch(`${API}/api/status`);
    const d = await r.json();
    if (d.running) {
      _running = true;
      setRunningUI(true);
      openSSE();
    } else if (d.has_result) {
      fetchAndShowResult();
    }
  } catch { /* ignore */ }
})();
