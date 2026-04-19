
from flask import Flask, request, jsonify, render_template
import numpy as np
from PIL import Image
import base64, io, threading, time, uuid
from scipy.ndimage import rotate as scipy_rotate

app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  FTImage Class — ALL math lives here (OOP, no repetition)
# ══════════════════════════════════════════════════════════════════════════════
class FTImage:
    def __init__(self):
        self.original = None      # float64 grayscale [0,1]
        self.resized  = None      # working array (may be complex)
        self.ft       = None      # fftshift(fft2(resized))
        self.rows = self.cols = 0

    # ── Load ──────────────────────────────────────────────────────────────────
    def load_from_base64(self, b64: str):
        data = base64.b64decode(b64.split(',')[-1])
        img  = Image.open(io.BytesIO(data)).convert('L')
        self.original = np.array(img, dtype=np.float64) / 255.0
        self.rows, self.cols = self.original.shape
        self.resized = self.original.copy()
        self._compute_ft()

    # ── Resize ────────────────────────────────────────────────────────────────
    def resize(self, target_w: int, target_h: int, keep_aspect: bool = False):
        if self.original is None:
            return
        orig_h, orig_w = self.original.shape
        tw, th = target_w, target_h
        if keep_aspect:
            ratio = min(tw / orig_w, th / orig_h)
            tw = max(1, int(orig_w * ratio))
            th = max(1, int(orig_h * ratio))
        pil = Image.fromarray((self.original * 255).astype(np.uint8))
        pil = pil.resize((tw, th), Image.LANCZOS)
        self.resized = np.array(pil, dtype=np.float64) / 255.0
        self.rows, self.cols = self.resized.shape
        self._compute_ft()

    # ── FT ────────────────────────────────────────────────────────────────────
    def _compute_ft(self):
        if self.resized is not None:
            arr = np.real(self.resized) if np.iscomplexobj(self.resized) else self.resized
            self.ft = np.fft.fftshift(np.fft.fft2(arr))

    # ── Component helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _component_of(arr: np.ndarray, comp: str) -> np.ndarray:
        return {
            'magnitude': lambda: np.log1p(np.abs(arr)),
            'phase':     lambda: np.angle(arr),
            'real':      lambda: np.real(arr),
            'imaginary': lambda: np.imag(arr),
        }.get(comp, lambda: np.log1p(np.abs(arr)))()

    def get_component(self, comp: str) -> np.ndarray:
        if self.ft is None:
            return np.zeros((max(self.rows, 1), max(self.cols, 1)))
        return self._component_of(self.ft, comp)

    def get_spatial_component(self, comp: str) -> np.ndarray:
        if self.resized is None:
            return np.zeros((1, 1))
        is_cpx = np.iscomplexobj(self.resized)
        if comp in ('spatial', 'real'):
            return np.real(self.resized)
        if comp == 'magnitude':
            return np.abs(self.resized)
        if comp == 'phase':
            return np.angle(self.resized) if is_cpx else np.zeros_like(np.real(self.resized))
        if comp == 'imaginary':
            return np.imag(self.resized) if is_cpx else np.zeros_like(np.real(self.resized))
        return np.real(self.resized)

    def get_masked_ft(self, region: str, ratio: float) -> np.ndarray:
        h, w   = self.ft.shape
        cr, cc = h // 2, w // 2
        rh     = max(1, int(h * ratio / 2))
        rw     = max(1, int(w * ratio / 2))
        mask   = np.zeros((h, w), dtype=bool)
        mask[cr - rh:cr + rh, cc - rw:cc + rw] = True
        if region == 'outer':
            mask = ~mask
        result = self.ft.copy()
        result[~mask] = 0
        return result

    # ── Display helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _normalize_display(arr: np.ndarray,
                           brightness: float = 1.0,
                           contrast:   float = 1.0) -> np.ndarray:
        arr  = np.real(arr).astype(np.float64)
        p_lo = np.percentile(arr, 2)
        p_hi = np.percentile(arr, 98)
        if p_hi > p_lo:
            norm = np.clip((arr - p_lo) / (p_hi - p_lo), 0, 1)
        else:
            mn, mx = arr.min(), arr.max()
            norm = (arr - mn) / (mx - mn + 1e-8) if mx > mn else np.zeros_like(arr)
        # window/level: contrast scales around centre, brightness shifts
        norm = np.clip((norm - 0.5) * contrast + 0.5 + (brightness - 1.0), 0, 1)
        return norm

    @staticmethod
    def to_display_b64(arr: np.ndarray,
                       brightness: float = 1.0,
                       contrast:   float = 1.0) -> str:
        norm = (FTImage._normalize_display(arr, brightness, contrast) * 255).astype(np.uint8)
        buf  = io.BytesIO()
        Image.fromarray(norm).save(buf, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    def spatial_b64(self, brightness: float = 1.0, contrast: float = 1.0) -> str:
        return FTImage.to_display_b64(np.real(self.resized), brightness, contrast)

    def component_b64(self, comp: str,
                      brightness: float = 1.0,
                      contrast:   float = 1.0) -> str:
        return FTImage.to_display_b64(self.get_component(comp), brightness, contrast)

    def all_ft_components_b64(self) -> dict:
        return {c: self.component_b64(c) for c in ('magnitude', 'phase', 'real', 'imaginary')}

    def region_overlay_b64(self, region: str, ratio: float) -> str:
        if self.ft is None:
            return ''
        h, w   = self.ft.shape
        cr, cc = h // 2, w // 2
        rh     = max(1, int(h * ratio / 2))
        rw     = max(1, int(w * ratio / 2))
        rgba   = np.zeros((h, w, 4), dtype=np.uint8)
        mask   = np.zeros((h, w), dtype=bool)
        mask[cr - rh:cr + rh, cc - rw:cc + rw] = True
        if region == 'outer':
            mask = ~mask
        rgba[mask] = [0, 160, 255, 120]
        buf = io.BytesIO()
        Image.fromarray(rgba, 'RGBA').save(buf, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    # ══════════════════════════════════════════════════════════════════════════
    #  Weighted mix — class method (OOP, no module-level math)
    # ══════════════════════════════════════════════════════════════════════════
    @staticmethod
    def mix(ft_list: list, weights_a: list, weights_b: list,
            mode: str, region: str, ratio: float,
            cancel_evt: threading.Event = None) -> np.ndarray:
        valid = []
        for img, wa, wb in zip(ft_list, weights_a, weights_b):
            if img is not None and img.ft is not None:
                valid.append((img.get_masked_ft(region, ratio), wa, wb))
        if not valid:
            return None
        if cancel_evt and cancel_evt.is_set():
            return None

        h, w = valid[0][0].shape

        def _resize_ft(ft_arr, th, tw):
            if ft_arr.shape == (th, tw):
                return ft_arr
            def _ch(c):
                mn, mx = c.min(), c.max()
                n = ((c - mn) / (mx - mn + 1e-8) * 255).astype(np.uint8)
                return (np.array(Image.fromarray(n).resize((tw, th), Image.LANCZOS),
                                 np.float64) / 255.0) * (mx - mn) + mn
            return _ch(np.real(ft_arr)) + 1j * _ch(np.imag(ft_arr))

        combined = np.zeros((h, w), dtype=complex)
        for mft, wa_i, wb_i in valid:
            if cancel_evt and cancel_evt.is_set():
                return None
            mft = _resize_ft(mft, h, w)
            if mode == 'mag_phase':
                combined += np.abs(mft) * wa_i * np.exp(1j * np.angle(mft) * wb_i)
            else:
                combined += np.real(mft) * wa_i + 1j * np.imag(mft) * wb_i

        if cancel_evt and cancel_evt.is_set():
            return None

        result = np.abs(np.fft.ifft2(np.fft.ifftshift(combined)))
        p_lo, p_hi = np.percentile(result, 2), np.percentile(result, 98)
        result = np.clip((result - p_lo) / (p_hi - p_lo + 1e-8), 0, 1) if p_hi > p_lo else result
        return result

    # ══════════════════════════════════════════════════════════════════════════
    #  Part B — action dispatcher (NO repetition between spatial & freq)
    # ══════════════════════════════════════════════════════════════════════════

    def apply_spatial_action(self, action: str, p: dict) -> 'FTImage':
        arr = np.real(self.resized).copy()
        # _dispatch_action with is_freq=False works on raw array, returns array
        result_arr = self._dispatch_action(arr, action, p, is_freq=False)
        out = FTImage()
        out.resized = result_arr
        out.rows, out.cols = np.real(result_arr).shape[:2]
        out._compute_ft()
        return out

    def apply_frequency_action(self, action: str, p: dict) -> 'FTImage':
        proc_ft = self._dispatch_action(self.ft.copy(), action, p, is_freq=True)
        proc_spatial = np.fft.ifft2(np.fft.ifftshift(proc_ft))
        out = FTImage()
        out.resized = proc_spatial
        out.ft = proc_ft
        out.rows, out.cols = np.real(proc_spatial).shape
        return out

    # ── [OOP-2] Single dispatcher eliminates dual-method repetition ───────────
    def _dispatch_action(self, data: np.ndarray, action: str,
                         p: dict, is_freq: bool) -> np.ndarray:
        """
        Unified action dispatcher for both spatial and frequency domains.
        `data`    — 2D array (real for spatial, complex for freq)
        `is_freq` — True ↔ frequency domain; False ↔ spatial domain
        Operations that differ between domains are handled via `is_freq` branches.
        Shared operations (shift, stretch, rotate, window, fourier_n) are coded once.
        """

        # ── SHIFT ─────────────────────────────────────────────────────────────
        if action == 'shift':
            return np.roll(np.roll(data, int(p.get('dy', 0)), axis=0),
                           int(p.get('dx', 0)), axis=1)

        # ── COMPLEX EXPONENTIAL ───────────────────────────────────────────────
        if action == 'complex_exp':
            h, w   = data.shape
            u0, v0 = float(p.get('u0', 1)), float(p.get('v0', 1))
            xx, yy = np.meshgrid(np.arange(w), np.arange(h))
            return data * np.exp(1j * 2 * np.pi * (u0 * xx / w + v0 * yy / h))

        # ── STRETCH ───────────────────────────────────────────────────────────
        if action == 'stretch':
            sx, sy = max(0.1, float(p.get('sx', 1))), max(0.1, float(p.get('sy', 1)))
            h, w   = data.shape
            if is_freq:
                new_h, new_w = max(1, int(h / sy)), max(1, int(w / sx))
            else:
                new_h, new_w = max(1, int(h * sy)), max(1, int(w * sx))

            def _rescale_channel(ch, nh, nw):
                mn, mx = ch.min(), ch.max()
                if mx == mn:
                    return np.zeros((nh, nw))
                norm = ((ch - mn) / (mx - mn) * 255).astype(np.uint8)
                pil  = Image.fromarray(norm).resize((nw, nh), Image.LANCZOS)
                return np.array(pil, np.float64) / 255.0 * (mx - mn) + mn

            if is_freq:
                r_r = _rescale_channel(np.real(data), new_h, new_w)
                i_r = _rescale_channel(np.imag(data), new_h, new_w)
                res = np.zeros((h, w), dtype=complex)
                ch, cw = min(new_h, h), min(new_w, w)
                res[:ch, :cw] = r_r[:ch, :cw] + 1j * i_r[:ch, :cw]
                return res
            else:
                pil    = Image.fromarray((np.clip(data, 0, 1) * 255).astype(np.uint8))
                pil    = pil.resize((new_w, new_h), Image.LANCZOS)
                result = np.zeros((h, w), dtype=np.float64)
                ch, cw = min(new_h, h), min(new_w, w)
                result[:ch, :cw] = np.array(pil, np.float64)[:ch, :cw] / 255.0
                return result

        # ── MIRROR ────────────────────────────────────────────────────────────
        if action == 'mirror':
            axis = p.get('axis', 'horizontal')
            def _mirror(a):
                if axis == 'horizontal': return np.concatenate([a, np.fliplr(a)], axis=1)
                if axis == 'vertical':   return np.concatenate([a, np.flipud(a)], axis=0)
                tmp = np.concatenate([a, np.fliplr(a)], axis=1)
                return np.concatenate([tmp, np.flipud(tmp)], axis=0)
            if is_freq:
                return _mirror(np.real(data)) + 1j * _mirror(np.imag(data))
            return _mirror(data)

        # ── MAKE EVEN / ODD — rot90(k=2) = true 180° center flip ─────────────
        if action == 'make_even':
            if is_freq:
                r = (np.real(data) + np.rot90(np.real(data), 2)) / 2.0
                i = (np.imag(data) + np.rot90(np.imag(data), 2)) / 2.0
                return r + 1j * i
            return (data + np.rot90(data, 2)) / 2.0

        if action == 'make_odd':
            if is_freq:
                r = (np.real(data) - np.rot90(np.real(data), 2)) / 2.0
                i = (np.imag(data) - np.rot90(np.imag(data), 2)) / 2.0
                return r + 1j * i
            return (data - np.rot90(data, 2)) / 2.0

        # ── ROTATE ────────────────────────────────────────────────────────────
        if action == 'rotate':
            angle = float(p.get('angle', 0))
            if is_freq:
                r = scipy_rotate(np.real(data), angle, reshape=True, mode='constant', cval=0.0)
                i = scipy_rotate(np.imag(data), angle, reshape=True, mode='constant', cval=0.0)
                return r + 1j * i
            return scipy_rotate(data, angle, reshape=True, mode='constant', cval=0.0)

        # ── DIFFERENTIATE ─────────────────────────────────────────────────────
        if action == 'differentiate':
            ax    = 1 if p.get('axis', 'x') == 'x' else 0
            h, w  = data.shape
            freqs = np.fft.fftfreq(w if ax == 1 else h)
            filt  = 1j * 2 * np.pi * (freqs[np.newaxis, :] if ax == 1 else freqs[:, np.newaxis])
            if is_freq:
                return data * filt
            ft = np.fft.fft2(data)
            return np.real(np.fft.ifft2(ft * filt))

        # ── INTEGRATE ─────────────────────────────────────────────────────────
        if action == 'integrate':
            ax    = 1 if p.get('axis', 'x') == 'x' else 0
            h, w  = data.shape
            freqs = np.fft.fftfreq(w if ax == 1 else h).copy()
            freqs[0] = 1e-10
            filt  = 1.0 / (1j * 2 * np.pi * (freqs[np.newaxis, :] if ax == 1 else freqs[:, np.newaxis]))
            if is_freq:
                return data * filt
            ft = np.fft.fft2(data)
            return np.real(np.fft.ifft2(ft * filt))

        # ── WINDOW ────────────────────────────────────────────────────────────
        if action == 'window':
            h, w = data.shape
            win  = self._make_window(p.get('type', 'hanning'), h, w, p)
            return data * win

        # ── FOURIER N TIMES ───────────────────────────────────────────────────
        if action == 'fourier_n':
            result = data.copy()
            n = int(p.get('n', 1))
            for _ in range(n):
                result = np.fft.fftshift(np.fft.fft2(result))
                if not is_freq:
                    result = np.abs(result)
            mx = np.abs(result).max()
            if mx > 0:
                result = result / mx
            return result

        return data

    # ── [GAP-3] Window factory — Hamming alpha + Hanning alpha exposed ────────
    @staticmethod
    def _make_window(win_type: str, h: int, w: int, p: dict) -> np.ndarray:
        if win_type == 'gaussian':
            sx, sy = float(p.get('sigma_x', 0.3)), float(p.get('sigma_y', 0.3))
            xx, yy = np.meshgrid(np.linspace(-1, 1, w), np.linspace(-1, 1, h))
            return np.exp(-(xx**2 / (2*sx**2) + yy**2 / (2*sy**2)))

        if win_type == 'hamming':
            # [GAP-3] Generalized Hamming: w(n) = alpha - (1-alpha)*cos(2πn/(N-1))
            # Standard Hamming: alpha=0.54  |  Hann: alpha=0.5
            alpha = float(p.get('hamming_alpha', 0.54))
            h_win = alpha - (1 - alpha) * np.cos(2 * np.pi * np.arange(h) / (h - 1))
            w_win = alpha - (1 - alpha) * np.cos(2 * np.pi * np.arange(w) / (w - 1))
            return np.outer(h_win, w_win)

        if win_type == 'hanning':
            # [GAP-3] Generalized Hanning with raised cosine beta parameter
            # beta=1 → standard Hanning; beta>1 → flatter top; 0<beta<1 → more tapered
            beta = float(p.get('hanning_beta', 1.0))
            h_win = 0.5 * (1 - np.cos(beta * np.pi * np.arange(h) / (h - 1)))
            w_win = 0.5 * (1 - np.cos(beta * np.pi * np.arange(w) / (w - 1)))
            # clamp to [0,1]
            h_win = np.clip(h_win, 0, 1)
            w_win = np.clip(w_win, 0, 1)
            return np.outer(h_win, w_win)

        if win_type == 'rectangular':
            rw_frac = float(p.get('rect_w', 1.0))
            rh_frac = float(p.get('rect_h', 1.0))
            win = np.zeros((h, w))
            rh2 = max(1, int(h * rh_frac))
            rw2 = max(1, int(w * rw_frac))
            r0  = (h - rh2) // 2
            c0  = (w - rw2) // 2
            win[r0:r0+rh2, c0:c0+rw2] = 1.0
            return win

        return np.ones((h, w))


# ══════════════════════════════════════════════════════════════════════════════
#  [OOP-1] Mixer class — encapsulates ALL thread orchestration
# ══════════════════════════════════════════════════════════════════════════════
class Mixer:
    def __init__(self):
        self._lock    = threading.Lock()
        self._thread  = None
        self._cancel  = threading.Event()
        self._results = {}

    def submit(self, cfg: dict) -> str:
        """Cancel any running job, start a new one, return job_id."""
        with self._lock:
            self._cancel.set()
            self._results.clear()          # discard stale results
            self._cancel = threading.Event()
            job_id       = str(uuid.uuid4())
            self._thread = threading.Thread(
                target=self._worker,
                args=(job_id, cfg, self._cancel),
                daemon=True)
            self._thread.start()
        return job_id

    def poll(self, job_id: str) -> dict | None:
        """Return result dict if ready, else None."""
        return self._results.pop(job_id, None)

    def _worker(self, job_id: str, cfg: dict, cancel_evt: threading.Event):
        try:
            if cfg.get('simulate'):
                for _ in range(10):
                    if cancel_evt.is_set():
                        return
                    time.sleep(1)

            slots, wa, wb = cfg['slots'], cfg['weights_a'], cfg['weights_b']
            mode, region, ratio = cfg['mode'], cfg['region'], cfg['ratio']

            with _store_lock:
                ft_list = [_images.get(s) for s in slots]

            if cancel_evt.is_set():
                return

            result = FTImage.mix(ft_list, wa, wb, mode, region, ratio, cancel_evt)

            if cancel_evt.is_set():
                return

            if result is None:
                self._results[job_id] = {'error': 'No images loaded or cancelled'}
            else:
                self._results[job_id] = {'image': FTImage.to_display_b64(result)}

        except Exception as e:
            import traceback; traceback.print_exc()
            self._results[job_id] = {'error': str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  In-memory store
# ══════════════════════════════════════════════════════════════════════════════
_store_lock = threading.Lock()
_images: dict = {}
_mixer  = Mixer()

# Per-slot brightness/contrast state (server-side window/level)
# slot → {'brightness': float, 'contrast': float, 'ft_comp': str}
_slot_bc: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
#  Routes
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def home_page():
    return render_template("home.html")

@app.route('/app')
def index():
    return render_template('index.html')

@app.route('/home')
def home():
    return render_template('home.html')


@app.route('/api/upload', methods=['POST'])
def upload():
    data   = request.json
    slot   = data['slot']
    ft_img = FTImage()
    ft_img.load_from_base64(data['image'])
    with _store_lock:
        _images[slot] = ft_img
        _slot_bc[slot] = {'brightness': 1.0, 'contrast': 1.0, 'ft_comp': 'magnitude'}
    return jsonify({'spatial': ft_img.spatial_b64(),
                    **ft_img.all_ft_components_b64(),
                    'rows': ft_img.rows, 'cols': ft_img.cols})


@app.route('/api/component', methods=['POST'])
def component():
    data = request.json
    slot = data['slot']
    b    = float(data.get('brightness', 1.0))
    c    = float(data.get('contrast',   1.0))
    comp = data['comp']
    with _store_lock:
        if slot not in _images:
            return jsonify({'error': 'no image'}), 400
        img = _images[slot]
        if slot in _slot_bc:
            _slot_bc[slot].update({'brightness': b, 'contrast': c, 'ft_comp': comp})
    return jsonify({'image': img.component_b64(comp, b, c)})


@app.route('/api/spatial', methods=['POST'])
def spatial_image():
    data = request.json
    slot = data['slot']
    b    = float(data.get('brightness', 1.0))
    c    = float(data.get('contrast',   1.0))
    with _store_lock:
        if slot not in _images:
            return jsonify({'error': 'no image'}), 400
        img = _images[slot]
        if slot in _slot_bc:
            _slot_bc[slot].update({'brightness': b, 'contrast': c})
    return jsonify({'image': img.spatial_b64(b, c)})


# [GAP-2] True server-side window/level — re-renders at given B/C
@app.route('/api/bc', methods=['POST'])
def brightness_contrast():
    """
    Re-render ANY panel (spatial or FT component) at given brightness/contrast.
    Called from JS after drag ends to commit the new window/level.
    """
    data    = request.json
    slot    = data['slot']
    b       = float(data.get('brightness', 1.0))
    c       = float(data.get('contrast',   1.0))
    is_ft   = bool(data.get('is_ft', False))
    comp    = data.get('comp', 'magnitude')
    with _store_lock:
        if slot not in _images:
            return jsonify({'error': 'no image'}), 400
        img = _images[slot]
        if slot in _slot_bc:
            _slot_bc[slot].update({'brightness': b, 'contrast': c})
    if is_ft:
        return jsonify({'image': img.component_b64(comp, b, c)})
    return jsonify({'image': img.spatial_b64(b, c)})


@app.route('/api/resize', methods=['POST'])
def resize():
    data     = request.json
    policy   = data['policy']
    aspect   = data['aspect']
    custom_w = int(data.get('custom_w', 256))
    custom_h = int(data.get('custom_h', 256))
    with _store_lock:
        orig_sizes = [(img.original.shape[0], img.original.shape[1])
                      for k, img in _images.items()
                      if img.original is not None and k != 'emph']
        if not orig_sizes:
            return jsonify({})
        if policy == 'smallest':
            th, tw = min(s[0] for s in orig_sizes), min(s[1] for s in orig_sizes)
        elif policy == 'largest':
            th, tw = max(s[0] for s in orig_sizes), max(s[1] for s in orig_sizes)
        else:
            tw, th = custom_w, custom_h
        result = {}
        for slot, img in _images.items():
            if slot == 'emph': continue
            img.resize(tw, th, keep_aspect=aspect)
            result[slot] = {'spatial': img.spatial_b64(),
                            **img.all_ft_components_b64(),
                            'rows': img.rows, 'cols': img.cols}
    return jsonify(result)


@app.route('/api/region_overlay', methods=['POST'])
def region_overlay():
    data = request.json
    with _store_lock:
        if data['slot'] not in _images:
            return jsonify({'error': 'no image'}), 400
        img = _images[data['slot']]
    return jsonify({'overlay': img.region_overlay_b64(data['region'], float(data['ratio']))})


@app.route('/api/mix', methods=['POST'])
def mix():
    job_id = _mixer.submit(request.json)
    return jsonify({'job_id': job_id})


@app.route('/api/mix_result/<job_id>')
def mix_result(job_id):
    result = _mixer.poll(job_id)
    if result is not None:
        return jsonify({'ready': True, **result})
    return jsonify({'ready': False})


# [GAP-1] Output viewport FT component — compute FT of the mix result on demand
@app.route('/api/output_ft', methods=['POST'])
def output_ft():
    """
    Given a base64 output image (mix result), compute and return its FT component.
    This makes each output viewport "exactly similar" to input viewports.
    """
    data  = request.json
    comp  = data.get('comp', 'magnitude')
    b     = float(data.get('brightness', 1.0))
    c     = float(data.get('contrast',   1.0))
    tmp   = FTImage()
    tmp.load_from_base64(data['image'])
    return jsonify({'image': tmp.component_b64(comp, b, c)})


# ── Part B: Emphasizer ────────────────────────────────────────────────────────
@app.route('/api/emphasize', methods=['POST'])
def emphasize():
    data   = request.json
    action = data['action']
    params = data.get('params', {})
    n_ft   = int(data.get('n_fourier', 0))
    domain = data.get('domain', 'spatial')

    orig = FTImage()
    orig.load_from_base64(data['image'])

    proc = (orig.apply_spatial_action(action, params)
            if domain == 'spatial'
            else orig.apply_frequency_action(action, params))

    # Extra N Fourier — normalize once at end
    if n_ft > 0:
        arr = np.real(proc.resized).copy()
        for _ in range(n_ft):
            arr = np.abs(np.fft.fftshift(np.fft.fft2(arr)))
        mx = arr.max()
        if mx > 0:
            arr /= mx
        proc = FTImage()
        proc.resized = arr
        proc.rows, proc.cols = arr.shape
        proc._compute_ft()

    is_cpx = np.iscomplexobj(proc.resized)

    return jsonify({
        # spatial
        'spatial_orig':       FTImage.to_display_b64(np.real(orig.resized)),
        'spatial_proc_real':  FTImage.to_display_b64(np.real(proc.resized)),
        'spatial_proc_mag':   FTImage.to_display_b64(np.abs(proc.resized)),
        'spatial_proc_phase': FTImage.to_display_b64(
            np.angle(proc.resized) if is_cpx else np.zeros_like(np.real(proc.resized))),
        'spatial_proc_imag':  FTImage.to_display_b64(
            np.imag(proc.resized) if is_cpx else np.zeros_like(np.real(proc.resized))),
        'spatial_is_complex': bool(is_cpx),
        # FT original
        'ft_orig_mag':   FTImage.to_display_b64(np.log1p(np.abs(orig.ft))),
        'ft_orig_phase': FTImage.to_display_b64(np.angle(orig.ft)),
        'ft_orig_real':  FTImage.to_display_b64(np.real(orig.ft)),
        'ft_orig_imag':  FTImage.to_display_b64(np.imag(orig.ft)),
        # FT processed
        'ft_proc_mag':   FTImage.to_display_b64(np.log1p(np.abs(proc.ft))),
        'ft_proc_phase': FTImage.to_display_b64(np.angle(proc.ft)),
        'ft_proc_real':  FTImage.to_display_b64(np.real(proc.ft)),
        'ft_proc_imag':  FTImage.to_display_b64(np.imag(proc.ft)),
        # output dimensions (for rotate info)
        'proc_rows': int(proc.rows),
        'proc_cols': int(proc.cols),
    })


if __name__ == '__main__':
    app.run(debug=True, port=8000)
