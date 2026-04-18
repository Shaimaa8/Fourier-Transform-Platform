/**
 * app.js — Frontend FINAL v4
 *
 * [GAP-1] Output viewports: FT component dropdown + refreshOutputFT()
 * [GAP-2] True server-side B/C: on mouseup commits B/C to /api/bc, re-fetches PNG
 * [GAP-3] Hamming/Hanning params wired in getActionParams()
 * [GAP-4] updateEmphOrigSpatialComp() for the new spatial-orig comp selector
 */

// ── Global state ───────────────────────────────────────────────────────────────
let _pollInterval        = null;
let _emphB64             = null;
let _emphResults         = null;
let _selectedOutputPort  = 0;

// Per-output-port: store the last-rendered b64 image (to allow output FT re-fetch)
const _outputImages = { 0: null, 1: null };

// Per-panel brightness/contrast (CSS layer — instant visual feedback)
const _panelBC = {};
function getPanelBC(id) {
  if (!_panelBC[id]) _panelBC[id] = { brightness: 1.0, contrast: 1.0 };
  return _panelBC[id];
}

// Which slot & whether panel is FT (for server re-render on mouseup)
const _panelMeta = {};  // panelId → { slot, isFt, comp }

// ── Tab switching ──────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
//  PART A — MIXER
// ══════════════════════════════════════════════════════════════════════════════

function openFile(slot) { document.getElementById(`file-${slot}`).click(); }

async function handleFile(event, slot) {
  const file = event.target.files[0];
  if (!file) return;
  const b64  = await fileToBase64(file);
  const res  = await fetch('/api/upload', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot: String(slot), image: b64 })
  });
  const data = await res.json();
  setImage(`spatial-${slot}`, data.spatial);
  _panelMeta[`spatial-${slot}`] = { slot: String(slot), isFt: false };

  const comp = document.querySelector(`.comp-select[data-slot="${slot}"]`).value;
  setImage(`ft-${slot}`, data[comp] || data.magnitude);
  _panelMeta[`ft-${slot}`] = { slot: String(slot), isFt: true, comp };
  updateOverlayForSlot(slot);
  enableWeightCard(slot);
  scheduleAutoMix();
}

// ── Enable weight card when image is loaded ────────────────────────────────
function enableWeightCard(slot) {
  const card = document.getElementById(`weight-card-${slot}`);
  const hint = document.getElementById(`wcard-hint-${slot}`);
  if (card) {
    card.classList.remove('weight-card-disabled');
    card.classList.add('weight-card-active');
  }
  if (hint) hint.style.display = 'none';
  const wa = document.getElementById(`wa-${slot}`);
  const wb = document.getElementById(`wb-${slot}`);
  if (wa) wa.disabled = false;
  if (wb) wb.disabled = false;
}

// FT component dropdown change
document.querySelectorAll('.comp-select').forEach(sel => {
  sel.addEventListener('change', async () => {
    const slot = sel.dataset.slot;
    const comp = sel.value;
    const bc   = getPanelBC(`ft-${slot}`);
    const res  = await fetch('/api/component', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot, comp, brightness: bc.brightness, contrast: bc.contrast })
    });
    const data = await res.json();
    if (data.image) {
      setImage(`ft-${slot}`, data.image);
      _panelMeta[`ft-${slot}`] = { slot, isFt: true, comp };
    }
  });
});

// ── [GAP-2] Brightness/Contrast: CSS filter for instant feedback,
//            then server re-render on mouseup ────────────────────────────────
let _dragState = null;

document.addEventListener('mousedown', e => {
  const panel = e.target.closest('.img-panel');
  if (!panel || !panel.querySelector('img')) return;
  e.preventDefault();
  const bc = getPanelBC(panel.id);
  _dragState = {
    panelId: panel.id,
    x: e.clientX, y: e.clientY,
    startB: bc.brightness, startC: bc.contrast
  };
});

document.addEventListener('mousemove', e => {
  if (!_dragState) return;
  const dx =  (e.clientX - _dragState.x) / 200;
  const dy = -(e.clientY - _dragState.y) / 200;
  const bc = getPanelBC(_dragState.panelId);
  bc.brightness = Math.max(0.1, Math.min(3.0, _dragState.startB + dy));
  bc.contrast   = Math.max(0.1, Math.min(4.0, _dragState.startC + dx));
  // Instant CSS feedback
  const img = document.getElementById(_dragState.panelId)?.querySelector('img');
  if (img) img.style.filter =
    `brightness(${bc.brightness.toFixed(2)}) contrast(${bc.contrast.toFixed(2)})`;
});

document.addEventListener('mouseup', async () => {
  if (!_dragState) return;
  const { panelId } = _dragState;
  _dragState = null;
  // [GAP-2] Commit B/C to server and get re-rendered image (true window/level)
  const meta = _panelMeta[panelId];
  if (!meta) return;
  const bc = getPanelBC(panelId);
  try {
    const res  = await fetch('/api/bc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        slot: meta.slot, brightness: bc.brightness, contrast: bc.contrast,
        is_ft: meta.isFt, comp: meta.comp || 'magnitude'
      })
    });
    const data = await res.json();
    if (data.image) {
      setImageNoResetBC(panelId, data.image, bc);
    }
  } catch(e) { /* keep CSS filter as fallback */ }
});

// ── Output Port ────────────────────────────────────────────────────────────────
function selectOutputPort(port) {
  _selectedOutputPort = port;
  document.getElementById('out-btn-0').classList.toggle('active', port === 0);
  document.getElementById('out-btn-1').classList.toggle('active', port === 1);
  document.getElementById('out-vp-0').classList.toggle('output-active', port === 0);
  document.getElementById('out-vp-1').classList.toggle('output-active', port === 1);
  // clear stale badge from newly selected
  document.getElementById(`out-vp-${port}`)?.querySelector('.stale-badge')?.remove();
}
selectOutputPort(0);

// ── Resize ─────────────────────────────────────────────────────────────────────
async function applyResize() {
  const policy   = document.getElementById('resize-policy').value;
  const aspect   = document.getElementById('keep-aspect').checked;
  const custom_w = parseInt(document.getElementById('custom-w')?.value) || 256;
  const custom_h = parseInt(document.getElementById('custom-h')?.value) || 256;
  const res  = await fetch('/api/resize', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ policy, aspect, custom_w, custom_h })
  });
  const data = await res.json();
  for (const [slot, info] of Object.entries(data)) {
    setImage(`spatial-${slot}`, info.spatial);
    _panelMeta[`spatial-${slot}`] = { slot, isFt: false };
    const comp  = document.querySelector(`.comp-select[data-slot="${slot}"]`)?.value || 'magnitude';
    const ftImg = info[comp] || info.magnitude;
    if (ftImg) { setImage(`ft-${slot}`, ftImg);
                 _panelMeta[`ft-${slot}`] = { slot, isFt: true, comp }; }
    updateOverlayForSlot(parseInt(slot));
  }
  scheduleAutoMix();
}

// ── Region overlay ─────────────────────────────────────────────────────────────
function updateOverlays() {
  for (let i = 0; i < 4; i++) updateOverlayForSlot(i);
}
async function updateOverlayForSlot(slot) {
  const overlayDiv = document.getElementById(`overlay-${slot}`);
  if (!overlayDiv) return;
  const region = document.getElementById('region-type').value;
  const ratio  = parseFloat(document.getElementById('region-ratio').value) / 100;
  try {
    const res  = await fetch('/api/region_overlay', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot: String(slot), region, ratio })
    });
    const data = await res.json();
    if (data.overlay)
      overlayDiv.innerHTML =
        `<img src="${data.overlay}" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none">`;
  } catch(e) {}
}

// ── Mix ────────────────────────────────────────────────────────────────────────
async function doMix() {
  // ── Validation: at least one image must be loaded ─────────────────────────
  const loadedCount = ['0','1','2','3'].filter(i =>
    document.getElementById(`spatial-${i}`)?.querySelector('img')).length;
  if (loadedCount === 0) {
    setProgress(0, 'Load at least one image first');
    setTimeout(() => setProgress(0, '—'), 2500);
    return;
  }

  const slots    = ['0','1','2','3'];
  const wa       = slots.map(i => parseFloat(document.getElementById(`wa-${i}`).value) / 100);
  const wb       = slots.map(i => parseFloat(document.getElementById(`wb-${i}`).value) / 100);
  const mode     = document.getElementById('mix-mode').value;
  const region   = document.getElementById('region-type').value;
  const ratio    = parseFloat(document.getElementById('region-ratio').value) / 100;
  const outPort  = _selectedOutputPort;
  const simulate = document.getElementById('sim-lag').checked;

  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
  setProgress(5, 'Sending…');

  try {
    const res  = await fetch('/api/mix', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slots, weights_a: wa, weights_b: wb, mode, region, ratio, simulate })
    });
    const data = await res.json();
    const thisJobId = data.job_id;
    let prog = 10;
    _pollInterval = setInterval(async () => {
      prog = Math.min(prog + 4, 95);
      setProgress(prog, 'Processing…');
      try {
        const r       = await fetch(`/api/mix_result/${thisJobId}`);
        const resData = await r.json();
        if (resData.ready) {
          clearInterval(_pollInterval); _pollInterval = null;
          if (resData.error) {
            setProgress(0, 'Error ✗');
          } else {
            setProgress(100, 'Done ✓');
            // Store image b64 and show it
            _outputImages[outPort] = resData.image;
            setImage(`output-${outPort}`, resData.image);
            _panelMeta[`output-${outPort}`] = { slot: `_out_${outPort}`, isFt: false };

            // [GAP-1] Enable FT dropdown and refresh if a comp was already selected
            const compSel = document.getElementById(`out-comp-${outPort}`);
            if (compSel) {
              compSel.disabled = false;
              if (compSel.value !== 'off') refreshOutputFT(outPort);
            }

            // Enable save button for this port
            const saveBtn = document.getElementById(`save-btn-${outPort}`);
            if (saveBtn) saveBtn.disabled = false;

            // Mark other port stale
            const other = outPort === 0 ? 1 : 0;
            markOutputStale(other);
            setTimeout(() => setProgress(0, '—'), 2000);
          }
        }
      } catch(err) {
        clearInterval(_pollInterval); _pollInterval = null;
        setProgress(0, 'Network error');
      }
    }, 700);
  } catch(e) { setProgress(0, 'Error!'); }
}

// [GAP-1] Fetch FT component of the output image from server
async function refreshOutputFT(port) {
  const b64  = _outputImages[port];
  const comp = document.getElementById(`out-comp-${port}`)?.value;
  const ftEl = document.getElementById(`out-ft-${port}`);
  if (!b64 || !ftEl || comp === 'off') {
    if (ftEl) ftEl.style.display = 'none';
    return;
  }
  ftEl.style.display = '';
  const bc = getPanelBC(`out-ft-${port}`);
  try {
    const res  = await fetch('/api/output_ft', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64, comp, brightness: bc.brightness, contrast: bc.contrast })
    });
    const data = await res.json();
    if (data.image) {
      setImage(`out-ft-${port}`, data.image);
      _panelMeta[`out-ft-${port}`] = { slot: `_out_${port}`, isFt: true, comp,
                                        _b64: b64 };  // store for bc re-render
    }
  } catch(e) {}
}

function markOutputStale(port) {
  const vp = document.getElementById(`out-vp-${port}`);
  if (!vp || !document.getElementById(`output-${port}`)?.querySelector('img')) return;
  vp.querySelector('.stale-badge')?.remove();
  const badge = document.createElement('div');
  badge.className = 'stale-badge';
  badge.textContent = 'outdated';
  badge.style.cssText = `position:absolute;top:6px;right:8px;z-index:10;
    font-family:var(--mono);font-size:9px;letter-spacing:1px;
    background:rgba(246,173,85,.2);color:#f6ad55;
    border:1px solid rgba(246,173,85,.4);padding:2px 7px;border-radius:4px;pointer-events:none;`;
  vp.style.position = 'relative';
  vp.appendChild(badge);
}

function setProgress(pct, lbl) {
  const bar = document.getElementById('progress-bar');
  const txt = document.getElementById('progress-lbl');
  if (bar) bar.style.width = pct + '%';
  if (txt) txt.textContent = lbl;
}

// ── Auto-mix (debounced) ───────────────────────────────────────────────────────
let _autoMixTimer = null;
function scheduleAutoMix() {
  const loaded = ['0','1','2','3'].filter(i =>
    document.getElementById(`spatial-${i}`)?.querySelector('img')).length;
  if (loaded < 1) return;
  if (_autoMixTimer) clearTimeout(_autoMixTimer);
  _autoMixTimer = setTimeout(() => { doMix(); _autoMixTimer = null; }, 400);
}
for (let i = 0; i < 4; i++) {
  document.getElementById(`wa-${i}`)?.addEventListener('input', scheduleAutoMix);
  document.getElementById(`wb-${i}`)?.addEventListener('input', scheduleAutoMix);
}
document.getElementById('mix-mode')?.addEventListener('change', scheduleAutoMix);
document.getElementById('region-type')?.addEventListener('change', scheduleAutoMix);
document.getElementById('region-ratio')?.addEventListener('input', scheduleAutoMix);

// ══════════════════════════════════════════════════════════════════════════════
//  PART B — EMPHASIZER
// ══════════════════════════════════════════════════════════════════════════════

function openEmphFile() { document.getElementById('emph-file').click(); }

async function handleEmphFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  _emphB64 = await fileToBase64(file);
  const res  = await fetch('/api/upload', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot: 'emph', image: _emphB64 })
  });
  const data = await res.json();
  setImage('e-spatial-orig', data.spatial);
  _panelMeta['e-spatial-orig'] = { slot: 'emph', isFt: false };
  updateEmphOrigComp();
  _emphResults = null;
  clearPanel('e-spatial-proc');
  clearPanel('e-ft-proc');
}

// [GAP-4] Comp selector on the original spatial panel
function updateEmphOrigSpatialComp() {
  if (!_emphResults) return;
  const comp = document.getElementById('e-spatial-orig-comp').value;
  const keyMap = {
    'spatial': 'spatial_orig', 'magnitude': 'spatial_orig_mag',
    'phase': 'spatial_orig_phase', 'imaginary': 'spatial_orig_imag'
  };
  // spatial_orig is always real; mag/phase/imag need the orig complex FT → IFFT
  // We use the already-returned spatial_orig (real) for 'spatial' comp.
  // For other comps on the original, we use the ft_orig_* keys as proxy display.
  if (comp === 'spatial') {
    if (_emphResults.spatial_orig) setImage('e-spatial-orig', _emphResults.spatial_orig);
  } else {
    // Show the FT component of the original as a meaningful "what phase/mag looks like"
    const ftKeyMap = { 'magnitude': 'ft_orig_mag', 'phase': 'ft_orig_phase',
                       'imaginary': 'ft_orig_imag' };
    const key = ftKeyMap[comp];
    if (key && _emphResults[key]) setImage('e-spatial-orig', _emphResults[key]);
  }
}

function updateEmphOrigComp() {
  if (!_emphB64) return;
  const comp = document.getElementById('e-orig-comp').value;
  fetch('/api/component', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot: 'emph', comp })
  }).then(r => r.json()).then(d => { if (d.image) setImage('e-ft-orig', d.image); });
}

function updateEmphProcDisplay() {
  if (!_emphResults) return;
  const spComp = document.getElementById('e-spatial-proc-comp').value;
  const ftComp = document.getElementById('e-ft-proc-comp').value;

  const spKeyMap = { 'spatial': 'spatial_proc_real', 'real': 'spatial_proc_real',
                     'magnitude': 'spatial_proc_mag', 'phase': 'spatial_proc_phase',
                     'imaginary': 'spatial_proc_imag' };
  const spKey = spKeyMap[spComp] || 'spatial_proc_real';
  if (_emphResults[spKey]) setImage('e-spatial-proc', _emphResults[spKey]);

  const badge = document.getElementById('complex-badge');
  if (badge) badge.style.display = _emphResults.spatial_is_complex ? 'inline' : 'none';

  const ftKeyMap = { 'mag': 'ft_proc_mag', 'phase': 'ft_proc_phase',
                     'real': 'ft_proc_real', 'imag': 'ft_proc_imag' };
  const ftKey = ftKeyMap[ftComp] || 'ft_proc_mag';
  if (_emphResults[ftKey]) setImage('e-ft-proc', _emphResults[ftKey]);
}

function showActionParams(action) {
  document.querySelectorAll('.param-panel').forEach(p => p.classList.add('hidden'));
  document.getElementById(`params-${action}`)?.classList.remove('hidden');
}
showActionParams('shift');

async function applyEmph() {
  if (!_emphB64) { alert('Load an image first!'); return; }
  const action   = document.getElementById('emph-action').value;
  const domain   = document.getElementById('emph-domain').value;
  const nFourier = parseInt(document.getElementById('e-n-fourier').value) || 0;
  const params   = getActionParams(action);

  clearPanel('e-spatial-proc', '⟳ Processing…');
  clearPanel('e-ft-proc', '⟳ Processing…');

  try {
    const res  = await fetch('/api/emphasize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: _emphB64, action, params, n_fourier: nFourier, domain })
    });
    _emphResults = await res.json();
    updateEmphProcDisplay();

    // Update FT original display
    const origComp = document.getElementById('e-orig-comp').value;
    const origKey  = `ft_orig_${origComp === 'imaginary' ? 'imag' : origComp}`;
    if (_emphResults[origKey]) setImage('e-ft-orig', _emphResults[origKey]);

    // Refresh spatial-orig comp display (now we have fresh results)
    updateEmphOrigSpatialComp();

    // [GAP-4] Show rotate dimensions info
    if (action === 'rotate' && _emphResults.proc_rows) {
      const info = document.getElementById('rotate-size-info');
      if (info) info.textContent =
        `Output size: ${_emphResults.proc_cols} × ${_emphResults.proc_rows} px`;
    }

  } catch(e) {
    clearPanel('e-spatial-proc', 'Error ✗');
    clearPanel('e-ft-proc', 'Error ✗');
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setImage(panelId, src) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.innerHTML = `<img src="${src}" draggable="false"
    style="width:100%;height:100%;object-fit:contain">`;
  const bc  = getPanelBC(panelId);
  const img = panel.querySelector('img');
  if (img) img.style.filter =
    `brightness(${bc.brightness.toFixed(2)}) contrast(${bc.contrast.toFixed(2)})`;
}

function setImageNoResetBC(panelId, src, bc) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.innerHTML = `<img src="${src}" draggable="false"
    style="width:100%;height:100%;object-fit:contain">`;
  const img = panel.querySelector('img');
  if (img) img.style.filter =
    `brightness(${bc.brightness.toFixed(2)}) contrast(${bc.contrast.toFixed(2)})`;
}

function clearPanel(panelId, msg = '') {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.innerHTML = msg
    ? `<div class="drop-hint muted">${msg}</div>`
    : `<div class="drop-hint muted">—</div>`;
}

// ── Save output image ─────────────────────────────────────────────────────────
function saveOutputImage(port) {
  const b64 = _outputImages[port];
  if (!b64) return;
  // b64 is "data:image/png;base64,..."
  const link = document.createElement('a');
  link.href = b64;
  link.download = `ft_mix_output_${port + 1}.png`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = e => resolve(e.target.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ── Part B real-time auto-apply ────────────────────────────────────────────────
let _emphTimer = null;
function scheduleAutoEmph() {
  if (!_emphB64) return;
  if (_emphTimer) clearTimeout(_emphTimer);
  _emphTimer = setTimeout(() => { applyEmph(); _emphTimer = null; }, 400);
}

document.querySelectorAll(
  '#params-shift input, #params-complex_exp input, #params-stretch input, ' +
  '#params-mirror select, #params-rotate input, #params-differentiate select, ' +
  '#params-integrate select, #params-window select, #params-window input, ' +
  '#params-fourier_n input').forEach(el => {
  el.addEventListener('input',  scheduleAutoEmph);
  el.addEventListener('change', scheduleAutoEmph);
});
document.getElementById('emph-action')?.addEventListener('change', () => {
  showActionParams(document.getElementById('emph-action').value);
  scheduleAutoEmph();
});
document.getElementById('e-n-fourier')?.addEventListener('input', scheduleAutoEmph);

// ── getActionParams — [GAP-3] Hamming alpha + Hanning beta wired ──────────────
function getActionParams(action) {
  const p = {};
  const g = id => { const el = document.getElementById(id); return el ? el.value : null; };
  switch (action) {
    case 'shift':
      p.dx = parseFloat(g('p-dx')) || 0;
      p.dy = parseFloat(g('p-dy')) || 0;
      break;
    case 'complex_exp':
      p.u0 = parseFloat(g('p-u0')) || 1;
      p.v0 = parseFloat(g('p-v0')) || 1;
      break;
    case 'stretch':
      p.sx = parseFloat(g('p-sx')) || 1;
      p.sy = parseFloat(g('p-sy')) || 1;
      break;
    case 'mirror':
      p.axis = g('p-axis-mirror') || 'horizontal';
      break;
    case 'rotate':
      p.angle = parseFloat(g('p-angle')) || 0;
      break;
    case 'differentiate':
      p.axis = g('p-axis-diff') || 'x';
      break;
    case 'integrate':
      p.axis = g('p-axis-int') || 'x';
      break;
    case 'window':
      p.type         = g('p-win-type') || 'hanning';
      p.sigma_x      = parseFloat(g('p-sigma-x'))      || 0.3;
      p.sigma_y      = parseFloat(g('p-sigma-y'))      || 0.3;
      p.hamming_alpha= parseFloat(g('p-hamming-alpha')) || 0.54;  // [GAP-3]
      p.hanning_beta = parseFloat(g('p-hanning-beta'))  || 1.0;   // [GAP-3]
      p.rect_w       = parseFloat(g('p-rect-w')) / 100  || 1.0;
      p.rect_h       = parseFloat(g('p-rect-h')) / 100  || 1.0;
      break;
    case 'fourier_n':
      p.n = parseInt(g('p-n')) || 1;
      break;
  }
  return p;
}
