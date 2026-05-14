// ─── bg-bech32.js  |  seedcraft / vanity wallet background ───────────────────
// A full-screen grid of bech32m characters, each independently cycling through
// the charset at a random speed, symbolising the vanity-address mining loop.
// Periodically a random cell "locks in" — it freezes and glows orange — to
// simulate the miner matching a target character.
//
// Fully responsive: the grid rebuilds on every window resize.
// Pauses automatically when the browser tab is hidden (zero CPU cost).
// Toggle: set ENABLED = false to disable entirely.

const ENABLED        = true;

const CHARSET        = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';  // 32 bech32m chars
const FONT_PX        = 13;     // character font size (px)
const CELL_W         = 16;     // column width  (px) — matches monospace char width at FONT_PX
const CELL_H         = 21;     // row height    (px)

// Regular cycling characters
const OPACITY_DIM    = 0.38;
// Locked (matched) character — random red or green flash
const OPACITY_LOCK   = 0.82;

// #f7931a = bitcoin orange (regular chars)
const CR = 247, CG = 147, CB = 26;

const DIM_CLR  = `rgba(${CR},${CG},${CB},${OPACITY_DIM})`;

// Lock-in color pairs: [char color, bg color]
const LOCK_COLORS = [
  [`rgba(239,68,68,${OPACITY_LOCK})`,  'rgba(239,68,68,0.12)'],   // red
  [`rgba(34,197,94,${OPACITY_LOCK})`,  'rgba(34,197,94,0.12)'],   // green
];

const LOCK_INTERVAL  = 380;   // ms between new lock-in spawns
const LOCK_HOLD      = 720;   // ms each cell stays locked
const MAX_LOCKS      = 6;     // max simultaneous locked cells

// ─────────────────────────────────────────────────────────────────────────────

if (ENABLED) (function () {

  // ── Canvas setup ────────────────────────────────────────────────────────────
  const canvas = document.createElement('canvas');
  Object.assign(canvas.style, {
    position:      'fixed',
    top:           '0',
    left:          '0',
    width:         '100%',
    height:        '100%',
    zIndex:        '-1',
    pointerEvents: 'none',
  });
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');

  // ── State ────────────────────────────────────────────────────────────────────
  let W = 0, H = 0, nCols = 0, nRows = 0;

  // Flat array [row * nCols + col] of cell objects:
  //   { offset: number, speed: number, frame: number, locked: boolean }
  let cells = [];

  // Active lock-in events: [{ idx, until }]
  let locks       = [];
  let lastLockTs  = 0;
  let paused      = false;  let frozen      = false;  // true = animation halted, static frame visible  let rafId       = null;

  // ── Helpers ──────────────────────────────────────────────────────────────────
  // Speed = frames between char steps (1 = fastest ≈ 60 steps/s, 7 = slowest ≈ 9/s)
  const SPEEDS = [1, 1, 2, 2, 2, 3, 3, 4, 5, 6, 7];  // weighted toward mid-range
  function randSpeed() { return SPEEDS[Math.floor(Math.random() * SPEEDS.length)]; }
  function randOff()   { return Math.floor(Math.random() * CHARSET.length); }

  // ── Grid (re)build ───────────────────────────────────────────────────────────
  function buildGrid(w, h) {
    W = canvas.width  = w;
    H = canvas.height = h;
    nCols = Math.ceil(w / CELL_W);
    nRows = Math.ceil(h / CELL_H);

    const total = nCols * nRows;
    cells = new Array(total);
    for (let i = 0; i < total; i++) {
      cells[i] = {
        offset: randOff(),
        speed:  randSpeed(),
        frame:  Math.floor(Math.random() * 7),   // stagger so all cells don't step together
        locked: false,
      };
    }
    locks = [];
  }

  // ── Resize handler ───────────────────────────────────────────────────────────
  // Throttle to once per 150 ms so rapid resize events don't thrash.
  let resizeTimer = null;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      buildGrid(window.innerWidth, window.innerHeight);
    }, 150);
  }

  // ── Lock-in spawner ──────────────────────────────────────────────────────────
  function maybeSpawnLock(ts) {
    if (ts - lastLockTs < LOCK_INTERVAL) return;
    if (locks.length >= MAX_LOCKS)       return;
    lastLockTs = ts;

    // Pick a free (unlocked) cell at random — up to 30 attempts
    for (let attempt = 0; attempt < 30; attempt++) {
      const idx = Math.floor(Math.random() * cells.length);
      if (cells[idx] && !cells[idx].locked) {
        const [clr, bg] = LOCK_COLORS[Math.random() < 0.5 ? 0 : 1];
        cells[idx].locked  = true;
        cells[idx].lockClr = clr;
        cells[idx].lockBg  = bg;
        locks.push({ idx, until: ts + LOCK_HOLD });
        break;
      }
    }
  }

  // ── Main draw loop ───────────────────────────────────────────────────────────
  function draw(ts) {
    if (paused) return;

    if (frozen) {
      // Render the current static frame once, then stop the loop.
      rafId = null;
      _renderFrame(ts);
      return;
    }

    rafId = requestAnimationFrame(draw);
    _renderFrame(ts);
  }

  function _renderFrame(ts) {

    // Expire old locks
    for (let i = locks.length - 1; i >= 0; i--) {
      if (ts > locks[i].until) {
        cells[locks[i].idx].locked = false;
        locks.splice(i, 1);
      }
    }

    maybeSpawnLock(ts);

    ctx.clearRect(0, 0, W, H);
    // Paint base background so the canvas itself is never transparent
    ctx.fillStyle = '#0f0f0f';
    ctx.fillRect(0, 0, W, H);
    ctx.font = `${FONT_PX}px 'Consolas','Cascadia Code',monospace`;

    for (let r = 0; r < nRows; r++) {
      const y = r * CELL_H + FONT_PX;   // text baseline

      for (let c = 0; c < nCols; c++) {
        const cell = cells[r * nCols + c];

        // Advance cycling (frozen while locked)
        if (!cell.locked) {
          cell.frame++;
          if (cell.frame >= cell.speed) {
            cell.frame  = 0;
            cell.offset = (cell.offset + 1) % CHARSET.length;
          }
        }

        const x  = c * CELL_W;
        const ch = CHARSET[cell.offset];

        if (cell.locked) {
          // Highlight rectangle + bright character (color assigned at spawn)
          ctx.fillStyle = cell.lockBg;
          ctx.fillRect(x, r * CELL_H, CELL_W, CELL_H);
          ctx.fillStyle = cell.lockClr;
        } else {
          ctx.fillStyle = DIM_CLR;
        }

        ctx.fillText(ch, x, y);
      }
    }
  }

  // ── Tab visibility — pause/resume ————————————————————————————————————
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      paused = true;
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    } else if (!frozen) {
      paused = false;
      rafId = requestAnimationFrame(draw);
    }
  });

  // ── External API — called by app.js when mining starts / stops ——————————
  window.Bech32Bg = {
    start() {
      frozen = false;
      if (!rafId && !document.hidden) {
        paused = false;
        rafId  = requestAnimationFrame(draw);
      }
    },
    stop() {
      frozen = true;   // keep current frame visible, do not advance
    },
  };

  // ── Init ───────────────────────────────────────────────────────────────────────
  window.addEventListener('resize', onResize);
  buildGrid(window.innerWidth, window.innerHeight);
  // Draw one static frame so the grid is visible immediately, then freeze.
  frozen = true;
  rafId  = requestAnimationFrame(draw);

})();
