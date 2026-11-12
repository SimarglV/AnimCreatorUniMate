"""Local Gradio WebUI for UniMate text-to-motion inference.

Picks an asset (a ``rig_preprocess`` output directory) + a text prompt, runs
``unimate.inference.sample`` in a subprocess, optionally animates the mesh
(GLB/FBX via ``scripts/animate_samples.py``), and shows the result in the
browser: an interactive 3D preview of the animated GLB, the rendered videos,
and the generated files for download.

Motion expansion chains several prompts into one long motion
(``--motion_expand``): N segments -> 60 + (60 - overlap) * (N - 1) frames.

Run:  python webui.py   (then open http://127.0.0.1:7860)
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import gradio as gr
from gradio.processing_utils import save_file_to_cache
from gradio.route_utils import API_PREFIX
from gradio.utils import get_upload_folder
from gradio_client import utils as client_utils

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
EXP_DIR = os.path.join("outputs", "unimate_uniml3d_f60_v3")

BUILTIN_EXAMPLES_DIR = os.path.join(ROOT, "assets", "examples")
OWN_RIG_DIR = os.path.join(ROOT, "outputs", "rig")

# Friendly display names for the shipped examples, keyed by directory name.
# Directories not listed here still show up, with a title-cased name.
_EXAMPLE_LABELS = {
    "crab": "Crab",
    "human": "Human",
    "dragon": "Dragon",
    "snake": "Snake",
    "eagle": "Eagle",
    "shark": "Shark",
    "unitree_go2": "Unitree Go2",
}


def _nice_label(dirname):
    if dirname in _EXAMPLE_LABELS:
        return _EXAMPLE_LABELS[dirname]
    return dirname.replace("_", " ").title()


def _asset_dirs(root):
    """Subdirectories of *root* that contain a ``cond.npy``, keyed by dir name.

    Values are paths relative to ``ROOT``, since that is the working directory
    the sampler subprocess runs in."""
    out = {}
    if not os.path.isdir(root):
        return out
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "cond.npy")):
            out[entry] = os.path.relpath(path, ROOT)
    return out


def _discover_examples():
    """Built-in examples (``assets/examples``) plus any locally imported rigs
    (``outputs/rig``), as ``{label: path}``. A local rig never shadows a
    shipped example with the same directory name."""
    builtin = _asset_dirs(BUILTIN_EXAMPLES_DIR)
    own = _asset_dirs(OWN_RIG_DIR)
    examples = {}
    for name, path in builtin.items():
        examples[f"{_nice_label(name)} (built-in)"] = path
    for name, path in own.items():
        if name in builtin:
            continue
        examples[f"{_nice_label(name)} (own rig)"] = path
    return examples


EXAMPLES = _discover_examples()

SAMPLE_PROMPTS = [
    "An object trots forward.",
    "An object rears up on its hind legs.",
    "An object flaps its wings.",
    "An object swims and turns around.",
    "An object jumps in place.",
    "An object runs forward.",
]

EXPAND_PROMPTS = [
    "An object trots forward.\nAn object turns around in place.\nAn object sits down.",
    "An object walks forward.\nAn object runs forward.\nAn object jumps in place.",
]


# ─────────────────────────────────────────────────────────────────────────────
# Theme — a dark "graphite + cyan/violet" look inspired by the Kimodo demo.
# ─────────────────────────────────────────────────────────────────────────────

CSS = r"""
:root {
  --um-bg:#080b0f; --um-panel:#10151b; --um-panel2:#151c23; --um-line:#25313b;
  --um-text:#f3f6f4; --um-muted:#8b9aa5; --um-cyan:#3bd3d0; --um-cyan2:#5ee6be;
  --um-violet:#9f7aea; --um-red:#ff8f9b;

  --body-background-fill: var(--um-bg);
  --body-text-color: var(--um-text);
  --body-text-color-subdued: var(--um-muted);
  --background-fill-primary: var(--um-panel);
  --background-fill-secondary: var(--um-panel2);
  --border-color-primary: var(--um-line);
  --border-color-accent: var(--um-cyan);
  --color-accent: var(--um-cyan);
  --link-text-color: var(--um-cyan);
  --link-text-color-hover: var(--um-cyan2);
  --loader-color: var(--um-cyan);

  --panel-background-fill: #131a26;
  --panel-border-color: var(--um-line);
  --panel-border-width: 1px;
  --container-radius: 16px;

  --block-background-fill: transparent;
  --block-border-width: 0px;
  --block-shadow: none;
  --block-label-text-color: var(--um-muted);
  --block-info-text-color: var(--um-muted);

  --input-background-fill: #0b1015;
  --input-background-fill-focus: #0d1319;
  --input-border-color: var(--um-line);
  --input-border-color-focus: var(--um-cyan);
  --input-placeholder-color: #55637a;
  --input-shadow: none;
  --input-shadow-focus: 0 0 0 1px var(--um-cyan);

  --button-primary-background-fill: linear-gradient(135deg, var(--um-cyan), var(--um-cyan2));
  --button-primary-background-fill-hover: linear-gradient(135deg, var(--um-cyan2), var(--um-cyan));
  --button-primary-text-color: #051013;
  --button-primary-text-color-hover: #051013;
  --button-primary-border-color: transparent;
  --button-primary-border-color-hover: transparent;
  --button-primary-shadow: 0 8px 22px rgba(59,211,208,.18);
  --button-primary-shadow-hover: 0 10px 28px rgba(59,211,208,.30);
  --button-secondary-background-fill: #1d2833;
  --button-secondary-background-fill-hover: #26333f;
  --button-secondary-text-color: #dce9e8;
  --button-secondary-text-color-hover: #ffffff;
  --button-secondary-border-color: #2c3750;
  --button-secondary-border-color-hover: #3a4860;

  --slider-color: var(--um-cyan);
  --neutral-200: #2b354b;
  --code-background-fill: #0b1015;
  --table-odd-background-fill: var(--um-panel2);
  --checkbox-background-color: var(--um-cyan);
}

html, body { background: var(--um-bg); }

.gradio-container {
  font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at 12% -12%, #16233a 0, transparent 42rem),
    radial-gradient(circle at 100% 0%, #121a2c 0, transparent 34rem),
    var(--um-bg);
  color: var(--um-text);
  min-height: 100vh;
}
.gradio-container .app, .gradio-container .main { padding: 0 !important; max-width: none !important; }
.gradio-container footer { display: none; }
.gradio-container input[type="checkbox"], .gradio-container input[type="radio"] { accent-color: var(--um-cyan); }
.gradio-container input, .gradio-container textarea, .gradio-container select { border-radius: 10px; }
.gradio-container textarea { line-height: 1.5; }
.gradio-container ::selection { background: rgba(59,211,208,.28); }

/* ── Header ─────────────────────────────────────────────────────────────── */
.um-header {
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  padding: 22px 30px; flex-wrap: wrap;
  border-bottom: 1px solid var(--um-line);
  background: radial-gradient(circle at 0 0, #293b62, transparent 34rem), #141a27;
}
.um-product { display: flex; align-items: center; gap: 14px; }
.um-mark {
  display: grid; place-items: center; width: 46px; height: 46px; border-radius: 13px;
  background: linear-gradient(135deg, var(--um-cyan), #218eac 55%, var(--um-violet));
  color: #051013; font-size: 24px; font-weight: 900;
  box-shadow: 0 0 30px rgba(59,211,208,.25);
}
.um-titles { display: flex; flex-direction: column; gap: 3px; }
.um-eyebrow {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .72rem; text-transform: uppercase; letter-spacing: .14em; color: var(--um-cyan);
}
.um-titles h1 { margin: 0; font-size: 2rem; letter-spacing: -.05em; font-weight: 800; line-height: 1; }
.um-sub { margin: 0; color: var(--um-muted); font-size: .9rem; }
.um-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.um-badge {
  font-size: .74rem; color: var(--um-muted); border: 1px solid var(--um-line);
  padding: 5px 11px; border-radius: 999px; background: #0d121d;
}

/* ── Layout ─────────────────────────────────────────────────────────────── */
.um-main {
  max-width: 1500px; margin: 0 auto; padding: 22px 28px 48px;
  align-items: flex-start !important;
}
.um-sidebar, .um-stage { gap: 16px !important; }

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.um-tabs { max-width: 1600px; margin: 0 auto; padding: 0 6px; }
.um-tabs [role="tablist"] {
  gap: 6px; padding: 14px 22px 0 !important;
  border-bottom: 1px solid var(--um-line);
}
.um-tabs [role="tablist"] button {
  color: var(--um-muted); font-weight: 700; font-size: .95rem;
  padding: 9px 16px !important; border-radius: 10px 10px 0 0;
  background: transparent; border: none;
}
.um-tabs [role="tablist"] button:hover { color: var(--um-text); }
.um-tabs [role="tablist"] button[aria-selected="true"] {
  color: var(--um-text); background: #141a27;
  box-shadow: inset 0 -2px 0 var(--um-cyan);
}

/* ── Cards ──────────────────────────────────────────────────────────────── */
.um-card { gap: 13px !important; }
.um-card:hover { border-color: #2e3a50; }
.um-card-head { display: flex; flex-direction: column; gap: 3px; }
.um-card-head .kicker {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .66rem; text-transform: uppercase; letter-spacing: .13em; color: var(--um-cyan);
}
.um-card-head h3 { margin: 0; font-size: 1.02rem; font-weight: 700; }
.um-hint { margin: 0; color: var(--um-muted); font-size: .8rem; line-height: 1.45; }

/* ── Field labels ───────────────────────────────────────────────────────── */
.um-label {
  display: block; margin-bottom: 6px; font-size: .78rem; font-weight: 500;
  color: var(--um-text); letter-spacing: .01em;
}
.um-label .um-muted { color: var(--um-muted); font-weight: 400; }
.um-tip {
  display: inline-grid; place-items: center; width: 15px; height: 15px;
  margin-left: 5px; border-radius: 50%; font-size: 10px; font-weight: 800;
  color: #051013; background: var(--um-muted); cursor: help; position: relative;
  vertical-align: middle; line-height: 1;
}
.um-tip:hover { background: var(--um-cyan); }
.um-tip::after {
  content: attr(data-tip); position: absolute; left: 50%; bottom: 140%;
  transform: translateX(-50%); width: max-content; max-width: 280px;
  padding: 7px 10px; border-radius: 8px; background: #0d121d;
  border: 1px solid var(--um-line); color: var(--um-text);
  font-size: .76rem; font-weight: 400; line-height: 1.45; text-align: left;
  white-space: normal; opacity: 0; pointer-events: none;
  transition: opacity .12s; z-index: 60; box-shadow: 0 10px 28px #0009;
}
.um-tip:hover::after { opacity: 1; }

/* ── Generate button ────────────────────────────────────────────────────── */
.um-generate {
  font-weight: 800 !important; font-size: 1.02rem !important; letter-spacing: -.01em;
  padding: 14px 18px !important; border-radius: 12px !important; width: 100%;
}

/* ── Status pill ────────────────────────────────────────────────────────── */
.um-status { display: inline-flex; align-items: center; gap: 8px; padding: 7px 13px;
  border: 1px solid var(--um-line); border-radius: 999px; background: #0d121d; font-size: .84rem; }
.um-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--um-muted); }
.um-dot.pulse { animation: um-pulse 1.4s ease-in-out infinite; }
@keyframes um-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
.um-status-text { color: var(--um-muted); }
.um-status--done .um-status-text { color: var(--um-cyan2); }
.um-status--error .um-status-text { color: var(--um-red); }
.um-status--busy .um-status-text { color: var(--um-cyan); }

/* ── 3D preview ─────────────────────────────────────────────────────────── */
.um-viewer { width: 100%; }
.um-model { display: block; width: 100%; border-radius: 14px; }
.um-stage-empty {
  display: grid; place-items: center; min-height: 520px; padding: 24px;
  text-align: center; color: var(--um-muted); font-size: .92rem;
  border: 1px dashed var(--um-line); border-radius: 14px; background: #0b1015;
}

/* ── Footer line ────────────────────────────────────────────────────────── */
.um-foot { text-align: center; color: var(--um-muted); font-size: .78rem; padding: 18px 0 28px; }
.um-foot a { color: var(--um-cyan); text-decoration: none; }

@media (max-width: 900px) {
  .um-main { padding: 16px 14px 40px; }
  .um-header { padding: 18px 16px; }
  .um-titles h1 { font-size: 1.6rem; }
}
"""

HEADER = """
<div class="um-header">
  <div class="um-product">
    <span class="um-mark">U</span>
    <div class="um-titles">
      <div class="um-eyebrow">UniMate · UniML3D-F60-v3 · flow matching</div>
      <h1>Text&nbsp;→&nbsp;motion</h1>
      <p class="um-sub">Generate articulated motion for any rigged skeleton from a short text prompt.</p>
    </div>
  </div>
  <div class="um-badges">
    <span class="um-badge">SIGGRAPH Asia 2026</span>
    <span class="um-badge">GLB · FBX · NPY</span>
    <span class="um-badge">One model, any skeleton</span>
  </div>
</div>
"""

ENGINE_SETUP_MD = """
**Unity** — import `assets/vendor/animationvat/unity/AnimationVAT_Unity.unitypackage`
(Assets → Import Package → Custom Package), then open its setup window under **Tools**.
Import the whole `*_vat` folder into `Assets/`, set the folder path, and click **Process**.

**Unreal Engine 5** — copy the contents of `assets/vendor/animationvat/unreal5/`
(or extract `AnimationVAT_Unreal.zip`) into your project's `Content`, import the
`_vat.png` and set its compression to **RGB16** (forward rendering recommended).

**Godot** — attach `assets/vendor/animationvat/godot/VertexAnimationPBR-GLSL.gdshader`
to a ShaderMaterial, assign the texture, and copy `Min` / `Max` and the frame count
from `-remap_info.json`.

The proxy `.glb` already carries the `VAT_UV` (UV2) layer the shaders sample.
Engine tools are upstream MIT examples — see `assets/vendor/animationvat/LICENSE`.
"""


def _card(kicker, title, hint=""):
    hint_html = f'<p class="um-hint">{hint}</p>' if hint else ""
    return gr.HTML(
        f'<div class="um-card-head"><span class="kicker">{kicker}</span>'
        f"<h3>{title}</h3>{hint_html}</div>"
    )


def _label(text, muted="", tip=""):
    muted_html = f'<span class="um-muted">{muted}</span>' if muted else ""
    tip_html = f'<span class="um-tip" data-tip="{tip}">?</span>' if tip else ""
    return gr.HTML(f'<label class="um-label">{text} {muted_html}{tip_html}</label>')


def _env_error():
    ckpt = os.path.join(EXP_DIR, "checkpoints", "checkpoint_step_150000.pt")
    if not os.path.isfile(ckpt):
        return f"Checkpoint not found at {ckpt}. Download it first."
    return ""


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Datasets whose object types can be named as ``<dataset>:<object_type>``.
ASSET_DATASETS = ("truebones", "mixamo", "objaverse", "general")


def _valid_asset_ref(asset):
    """True for anything ``unimate.inference.sample --asset`` accepts: a
    rig_preprocess directory, a one-entry cond file, ``<dataset>:<object_type>``
    or a bare object-type name (resolved by the sampler against the datasets)."""
    if not asset:
        return False
    if os.path.isdir(asset):
        return True
    if asset.lower().endswith(".npy") and os.path.isfile(asset):
        return True
    head, sep, tail = asset.partition(":")
    if sep:
        return head in ASSET_DATASETS and bool(tail.strip())
    return "/" not in asset and "\\" not in asset and " " not in asset


def _pill(state, text):
    return (
        f'<div class="um-status um-status--{state}">'
        f'<span class="um-dot{" pulse" if state == "busy" else ""}"></span>'
        f'<span class="um-status-text">{text}</span></div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3D preview — a self-contained <model-viewer> (WebGL, auto-framed + lit), which
# is far more reliable for skinned animated GLBs than Gradio's Babylon-based
# Model3D. The viewer script is vendored locally and served through Gradio's
# file cache, so the preview works offline too.
# ─────────────────────────────────────────────────────────────────────────────

MV_JS = os.path.join(ROOT, "assets", "vendor", "model-viewer.min.js")


def _served_url(path):
    """Copy a local file into Gradio's cache and return a URL it can serve."""
    try:
        cached = save_file_to_cache(path, get_upload_folder())
        return f"{API_PREFIX}/file={client_utils.encode_file_path(cached)}"
    except Exception:
        return None


def _static_url(path):
    """URL for a file under a directory registered in ``allowed_paths``.

    Unlike :func:`_served_url`, this keeps the original path, so Gradio serves
    it with its real MIME type (needed for a ``<script type="module">``).
    """
    return f"{API_PREFIX}/file={client_utils.encode_file_path(path)}"


def _viewer_html(glb):
    """Markup for the 3D preview: the animated GLB, or an empty-state box."""
    if not glb or not os.path.isfile(glb):
        return ('<div class="um-stage-empty">No animation yet — generate to see the '
                'animated mesh here.</div>')
    url = _served_url(glb)
    if not url:
        return '<div class="um-stage-empty">Could not serve the GLB file.</div>'
    return (
        f'<model-viewer class="um-model" src="{url}" alt="Animated mesh" '
        'camera-controls autoplay auto-rotate shadow-intensity="1" exposure="1.1" '
        'environment-image="neutral" interaction-prompt="none" '
        'style="width:100%;height:520px;background:#0b1015;border-radius:14px;'
        '--poster-color:transparent;">'
        '</model-viewer>'
    )


def _viewer_head():
    """Load the vendored model-viewer script from the allowed vendor folder."""
    if not os.path.isfile(MV_JS):
        return ""
    return f'<script type="module" src="{_static_url(MV_JS)}"></script>'


MV_HEAD = _viewer_head()


# ─────────────────────────────────────────────────────────────────────────────
# History — a persistent, Kimodo-style gallery of past generations. Each record
# stores the settings and outputs of a finished run so it can be restored.
# ─────────────────────────────────────────────────────────────────────────────

HISTORY_FILE = os.path.join("outputs", "webui", "history.json")
HISTORY = {}  # run_id -> record (insertion-ordered)


def _load_history():
    global HISTORY
    HISTORY = {}
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for rec in data if isinstance(data, list) else []:
            if isinstance(rec, dict) and rec.get("id"):
                HISTORY[rec["id"]] = rec
    except (OSError, ValueError):
        HISTORY = {}


def _save_history():
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(HISTORY.values()), f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _history_choices():
    """``(label, run_id)`` pairs, newest first."""
    choices = []
    for rid in reversed(list(HISTORY.keys())):
        rec = HISTORY[rid]
        label = f"{rec.get('time', '')} · {str(rec.get('prompt', ''))[:52]}"
        choices.append((label, rid))
    return choices


def _existing(paths):
    return [p for p in (paths or []) if isinstance(p, str) and os.path.isfile(p)]


def generate(asset_key, custom_asset, prompt, num_reps, cfg_scale, seed,
             animate_mesh, motion_expand, expand_overlap, loop_anim=False):
    started = time.time()
    elapsed = lambda: int(time.time() - started)
    noop_hist = gr.update()

    yield gr.skip(), [], [], "", _pill("idle", "Ready"), noop_hist
    err = _env_error()
    if err:
        yield gr.skip(), [], [], err, _pill("error", "Checkpoint missing"), noop_hist
        return

    prompt = (prompt or "").strip()
    if not prompt:
        yield gr.skip(), [], [], "Please enter a prompt.", _pill("error", "No prompt"), noop_hist
        return

    asset = (custom_asset or "").strip() or EXAMPLES.get(asset_key, "")
    if not asset:
        yield gr.skip(), [], [], "Please choose an asset or enter a path.", \
            _pill("error", "No asset"), noop_hist
        return
    if not _valid_asset_ref(asset):
        yield gr.skip(), [], [], (
            f"Asset not found: {asset}\n\nUse a rig_preprocess directory, a cond.npy, "
            "or a dataset reference like 'truebones:Dragon', 'objaverse:<uid>' or 'mixamo'."
        ), _pill("error", "Asset not found"), noop_hist
        return

    run_id = uuid.uuid4().hex[:10]
    out_dir = os.path.abspath(os.path.join("outputs", "webui", run_id))
    os.makedirs(out_dir, exist_ok=True)
    # sampling writes to out_dir directly, except motion_expand -> out_dir/motion_expand
    samples_dir = os.path.join(out_dir, "motion_expand") if motion_expand else out_dir

    cmd = [
        PY, "-m", "unimate.inference.sample",
        "--exp_dir", EXP_DIR,
        "--asset", asset,
    ]
    if motion_expand:
        segments = [s.strip() for s in prompt.splitlines() if s.strip()]
        if len(segments) < 2:
            yield gr.skip(), [], [], "Motion expansion needs at least 2 prompts (one per line).", \
                _pill("error", "Needs ≥2 prompts"), noop_hist
            return
        cmd += ["--prompt"] + segments
        cmd += ["--motion_expand", "--expand_overlap", str(int(expand_overlap))]
    else:
        cmd += ["--prompt", prompt]

    cmd += [
        "--num_repetitions", str(int(num_reps)),
        "--cfg_scale", str(float(cfg_scale)),
        "--output_dir", out_dir,
    ]
    seed = _int_or_none(seed)
    if seed is not None:
        cmd += ["--seed", str(seed)]

    mode = "expansion" if motion_expand else "text"
    yield gr.skip(), [], [], f"[{mode}] {prompt!r} on {asset}\n\nStarting (model load ~30-60s)...\n", \
        _pill("busy", f"Loading model… {elapsed()}s"), noop_hist

    tail = []
    proc = subprocess.Popen(
        cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        tail.append(line.rstrip())
        tail = tail[-40:]
        yield gr.skip(), [], [], "Sampling...\n\n" + "\n".join(tail), \
            _pill("busy", f"Sampling… {elapsed()}s"), noop_hist
    rc = proc.wait()
    if rc != 0:
        yield gr.skip(), [], [], "Sampling FAILED (exit {})\n\n".format(rc) + "\n".join(tail), \
            _pill("error", "Sampling failed"), noop_hist
        return

    glbs, fbxs = [], []
    if animate_mesh:
        tail.append("--- animating mesh (GLB + FBX) ---")
        yield gr.skip(), [], [], "\n".join(tail), _pill("busy", f"Animating mesh… {elapsed()}s"), noop_hist
        a = subprocess.Popen(
            [PY, "scripts/animate_samples.py", samples_dir] + (["--loop"] if loop_anim else []),
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in a.stdout:
            tail.append(line.rstrip())
            tail = tail[-40:]
            yield gr.skip(), [], [], "\n".join(tail), _pill("busy", f"Animating mesh… {elapsed()}s"), noop_hist
        arc = a.wait()
        if arc != 0:
            tail.append("Mesh animation FAILED (exit {})".format(arc))
        glbs = sorted(glob.glob(os.path.join(samples_dir, "animated", "*.glb")))
        fbxs = sorted(glob.glob(os.path.join(samples_dir, "animated", "*.fbx")))

    videos = sorted(glob.glob(os.path.join(samples_dir, "animations", "*.mp4")))
    images = sorted(glob.glob(os.path.join(samples_dir, "animations", "*_tpos.png")))
    npys = sorted(glob.glob(os.path.join(samples_dir, "motions", "*.npy")))

    gallery = videos + images
    files = glbs + fbxs + npys
    glb_path = glbs[0] if glbs else None
    model3d = _viewer_html(glb_path)

    status = "\n".join(tail)
    status += "\n\nOutput: " + out_dir
    if not gallery:
        status += "\n\n[WARNING] No rendered videos found."

    HISTORY[run_id] = {
        "id": run_id,
        "time": time.strftime("%H:%M:%S"),
        "prompt": prompt,
        "asset_key": asset_key,
        "custom_asset": (custom_asset or "").strip(),
        "motion_expand": bool(motion_expand),
        "expand_overlap": int(expand_overlap),
        "loop": bool(loop_anim),
        "num_reps": int(num_reps),
        "cfg_scale": float(cfg_scale),
        "seed": seed,
        "animate_mesh": bool(animate_mesh),
        "model3d": glb_path,
        "gallery": gallery,
        "files": files,
        "log": status,
    }
    _save_history()

    done_text = f"Done in {elapsed()}s · {len(videos)} clips · {len(glbs)} GLB"
    yield model3d, gallery, files, status, _pill("done", done_text), \
        gr.update(choices=_history_choices(), value=run_id)


def restore(run_id):
    """Restore a past generation's settings and outputs."""
    rec = HISTORY.get(run_id)
    if not rec:
        return [gr.update()] * 15
    model3d = _viewer_html(rec.get("model3d"))
    return (
        rec.get("asset_key"),
        rec.get("custom_asset", ""),
        rec.get("prompt", ""),
        rec.get("num_reps", 1),
        rec.get("cfg_scale", 3.0),
        rec.get("seed"),
        rec.get("animate_mesh", True),
        rec.get("motion_expand", False),
        rec.get("expand_overlap", 10),
        rec.get("loop", False),
        model3d,
        _existing(rec.get("gallery")),
        _existing(rec.get("files")),
        rec.get("log", ""),
        _pill("done", f"Restored {run_id[:8]}"),
    )


CLIP_FRAMES = 60
CLIP_FPS = 30


def _seg_hint(prompt, expand, overlap):
    lines = [s for s in (prompt or "").splitlines() if s.strip()]
    n = max(1, len(lines))
    if expand:
        frames = CLIP_FRAMES + max(0, CLIP_FRAMES - int(overlap or 0)) * (n - 1)
        mode = "expansion"
    else:
        frames = CLIP_FRAMES
        mode = "single clip"
    return (f'<p class="um-hint">{n} segment{"s" if n != 1 else ""} · {mode} · '
            f'≈{frames} frames · {frames / CLIP_FPS:.1f} s</p>')


# ─────────────────────────────────────────────────────────────────────────────
# Import & Adaptation — drive data_process.rig_preprocess from the browser:
# upload a rigged GLB/glTF/FBX, review the automatic joint labels + facing pair,
# then build the asset (cond.npy + canonical GLB) the generator uses.
# ─────────────────────────────────────────────────────────────────────────────

RIG_ROOT = os.path.join("outputs", "rig")
IMPORT_HEADERS = ["index", "raw", "parent", "label", "flags"]


def _safe_name(text):
    text = re.sub(r'[-/\\\[\]\*\?\s]+', "_", (text or "").strip())
    return text.strip("_") or "asset"


def _rows_to_lists(rows):
    """Normalise a gr.Dataframe value (pandas / numpy / list) to a list of rows."""
    if rows is None:
        return []
    if hasattr(rows, "values"):          # pandas DataFrame / numpy array
        rows = rows.values.tolist()
    else:
        rows = list(rows)
    return [list(r) if not isinstance(r, list) else r for r in rows]


def _rig_cmd(*args):
    return [PY, "-m", "data_process.rig_preprocess", *args]


def _run_logged(cmd, started, status_prefix):
    """Stream a subprocess' output; yields ``(log_text, status_html)``."""
    tail = []
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    for line in proc.stdout:
        tail.append(line.rstrip())
        tail = tail[-60:]
        yield "\n".join(tail), _pill("busy", f"{status_prefix}… {int(time.time() - started)}s")
    proc.wait()
    yield "\n".join(tail), _pill("busy", f"{status_prefix}… {int(time.time() - started)}s")


def analyse_asset(upload, server_path, name, profile, annotate, face_r, face_l,
                  body_axis, rest_rotation, save_clips, overwrite):
    started = time.time()

    def out(log, preview, review, rows, fr, fl, ba, outdir, ann, inp, status):
        return (log, preview, review, rows, fr, fl, ba, outdir, ann, inp, status)

    if isinstance(upload, dict):
        upload = upload.get("path")
    inp = (upload or "").strip() or (server_path or "").strip()
    if not inp:
        yield out("Upload a GLB/glTF/FBX or enter a server path.", None, "", [], "", "", False,
                  None, None, None, _pill("error", "No file"))
        return
    if not os.path.isfile(inp):
        yield out(f"File not found: {inp}", None, "", [], "", "", False,
                  None, None, None, _pill("error", "File not found"))
        return

    asset_name = _safe_name(name) if (name or "").strip() else _safe_name(Path(inp).stem)
    outdir = os.path.abspath(os.path.join(RIG_ROOT, asset_name))

    cmd = _rig_cmd("run", "--input", inp, "--output_dir", outdir, "--profile", profile)
    if annotate and annotate != "auto":
        cmd += ["--annotate", annotate]
    if (face_r or "").strip() and (face_l or "").strip():
        cmd += ["--face_r", face_r.strip(), "--face_l", face_l.strip()]
    if body_axis:
        cmd += ["--body_axis"]
    if (rest_rotation or "").strip():
        cmd += ["--rest_rotation", rest_rotation.strip()]
    if save_clips:
        cmd += ["--save_clips"]
    if overwrite:
        cmd += ["--overwrite"]

    yield out("Analysing (export → annotate)…\n", None, "", [], "", "", False,
              outdir, None, inp, _pill("busy", "Analysing…"))
    log = ""
    for log, status in _run_logged(cmd, started, "Analysing"):
        yield out(log, None, "", [], "", "", False, outdir, None, inp, status)

    ann_path = os.path.join(outdir, "annotation.json")
    if not os.path.isfile(ann_path):
        yield out(log + "\n\nNo annotation.json was produced — see the log.", None, "", [], "",
                  "", False, outdir, None, inp, _pill("error", "Analysis failed"))
        return
    with open(ann_path, encoding="utf-8") as f:
        ann = json.load(f)
    rows = [
        [j.get("index", i), j.get("raw", ""), j.get("parent") or "", j.get("label", ""),
         "; ".join(j.get("reasons") or [])]
        for i, j in enumerate(ann.get("joints", []))
    ]
    review = ""
    review_path = os.path.join(outdir, "REVIEW.md")
    if os.path.isfile(review_path):
        with open(review_path, encoding="utf-8") as f:
            review = f.read()
    preview_path = os.path.join(outdir, "annotation_preview.png")
    fp = ann.get("face_pair", {})
    yield out(
        log + f"\n\nReview ready: {outdir}",
        preview_path if os.path.isfile(preview_path) else None,
        review, rows, fp.get("right", ""), fp.get("left", ""), bool(fp.get("body_axis")),
        outdir, ann, inp, _pill("done", "Analysed — check labels & facing"),
    )


def build_asset(rows, face_r, face_l, body_axis, outdir, ann, inp, profile,
                rest_rotation, save_clips):
    started = time.time()

    def out(log, preview, model, summary, status):
        return (log, preview, model, summary, status)

    if not outdir or not ann or not inp:
        yield out("Run “1) Analyse & label” first.", None, _viewer_html(None), {},
                  _pill("error", "Analyse first"))
        return

    joints = ann.get("joints", [])
    rows = _rows_to_lists(rows)
    for i, row in enumerate(rows):
        if i >= len(joints):
            break
        try:
            label = str(row[3]).strip()
        except (IndexError, TypeError):
            continue
        if label:
            joints[i]["label"] = label
            joints[i]["source"] = "manual"
            joints[i]["check"] = False
            joints[i].pop("reasons", None)
    ann["face_pair"] = {"right": (face_r or "").strip(), "left": (face_l or "").strip(),
                        "body_axis": bool(body_axis), "source": "manual"}
    ann["n_flagged"] = 0

    os.makedirs(outdir, exist_ok=True)
    ann_path = os.path.join(outdir, "annotation.json")
    with open(ann_path, "w", encoding="utf-8") as f:
        json.dump(ann, f, indent=1, ensure_ascii=False)

    cmd = _rig_cmd("run", "--input", inp, "--output_dir", outdir, "--profile", profile,
                   "--annotation", ann_path, "--overwrite")
    if (rest_rotation or "").strip():
        cmd += ["--rest_rotation", rest_rotation.strip()]
    if save_clips:
        cmd += ["--save_clips"]

    yield out("Building (features → cond → canonical GLB)…\n", None, _viewer_html(None), {},
              _pill("busy", "Building…"))
    log = ""
    for log, status in _run_logged(cmd, started, "Building"):
        yield out(log, None, gr.skip(), gr.skip(), status)

    cond = os.path.join(outdir, "cond.npy")
    summary = {}
    summary_path = os.path.join(outdir, "summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    glb = summary.get("canonical_glb")
    if not glb or not os.path.isfile(glb):
        cands = sorted(glob.glob(os.path.join(outdir, "*.glb")))
        glb = cands[0] if cands else None
    preview_path = os.path.join(outdir, "preview.png")
    if not os.path.isfile(cond) or not glb:
        yield out(log + "\n\nBuild did not produce cond.npy / a canonical GLB — see the log.",
                  None, _viewer_html(None), summary, _pill("error", "Build failed"))
        return
    yield out(
        log + f"\n\nBuilt: {outdir}\nGLB: {glb}",
        preview_path if os.path.isfile(preview_path) else None,
        _viewer_html(glb), summary, _pill("done", "Asset ready — use it in Generate"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export — VAT baking (AnimationVAT-compatible) + listing the run's existing exports.
# ─────────────────────────────────────────────────────────────────────────────

VAT_ROOT = os.path.join("outputs", "vat")


def _engine_tool_files():
    base = os.path.join("assets", "vendor", "animationvat")
    names = [
        os.path.join(base, "unity", "AnimationVAT_Unity.unitypackage"),
        os.path.join(base, "unreal5", "AnimationVAT_Unreal.zip"),
        os.path.join(base, "godot", "VertexAnimationPBR-GLSL.gdshader"),
        os.path.join(base, "LICENSE"),
        os.path.join(base, "README.md"),
    ]
    return [p for p in names if os.path.isfile(p)]


def _vat_name_from(path):
    stem = Path(path).stem
    stem = re.sub(r'-rep_\d+-\d+$', '', stem)
    return _safe_name(stem)


def _recent_animated():
    paths = (glob.glob(os.path.join("outputs", "webui", "*", "animated", "*.glb"))
             + glob.glob(os.path.join("outputs", "samples", "*", "animated", "*.glb")))
    paths = [p for p in paths if os.path.isfile(p)]
    paths.sort(key=os.path.getmtime, reverse=True)
    return paths[:60]


def _vat_choices():
    return [(os.path.relpath(p, ROOT), p) for p in _recent_animated()]


def show_exports(glb):
    """The selected run's existing exports beside the animated GLB."""
    if not glb or not os.path.isfile(glb):
        return []
    run_dir = os.path.dirname(os.path.dirname(glb))
    files = []
    for sub in ("animated", "motions", "animations", "motion_expand"):
        files += sorted(glob.glob(os.path.join(run_dir, sub, "*")))
    return files


def bake_vat(source, upload, path, name, fps, fmt, normals):
    started = time.time()
    if isinstance(upload, dict):
        upload = upload.get("path")
    inp = (upload or "").strip() or (path or "").strip() or (source or "").strip()
    if not inp or not os.path.isfile(inp):
        yield ("Pick an animated GLB or enter a path.", _pill("error", "No input"), [],
               _viewer_html(None))
        return
    name = _safe_name(name) if (name or "").strip() else _vat_name_from(inp)
    cmd = [PY, "scripts/bake_vat.py", "--input", inp, "--output_dir", VAT_ROOT,
           "--name", name, "--fps", str(int(fps)), "--format", fmt, "--normals", normals]
    yield (f"Baking VAT for {inp}…\n", _pill("busy", "Baking…"), [], _viewer_html(None))
    log = ""
    for log, status in _run_logged(cmd, started, "Baking"):
        yield (log, status, gr.skip(), gr.skip())
    out_dir = os.path.join(VAT_ROOT, f"{name}_vat")
    files = sorted(glob.glob(os.path.join(out_dir, "*")))
    glb = next((p for p in files if p.endswith(".glb")), None)
    png = next((p for p in files if p.endswith(".png")), None)
    js = next((p for p in files if p.endswith(".json")), None)
    if not (png and js and glb):
        yield (log + "\n\nVAT bake failed — see the log.", _pill("error", "Bake failed"), files,
               _viewer_html(None))
        return
    yield (log + f"\n\nVAT ready: {out_dir}", _pill("done", "VAT ready"), files, _viewer_html(glb))


theme = gr.themes.Base(primary_hue="cyan", neutral_hue="slate")
_load_history()

with gr.Blocks(title="UniMate — text → motion", fill_width=True) as demo:
    gr.HTML(HEADER)

    with gr.Tabs(elem_classes="um-tabs"):
        with gr.Tab("Generate", id="generate"):
            with gr.Row(elem_classes="um-main"):
                # ── Sidebar: controls ────────────────────────────────────────
                with gr.Column(scale=4, min_width=320, elem_classes="um-sidebar"):
                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("01 · Asset", "Choose a skeleton",
                              "A built-in example, a rig_preprocess directory, or a dataset object type.")
                        _label("Built-in example",
                               tip="Ready-made rigs that ship with the repo (assets/examples) plus any you imported under outputs/rig.")
                        _example_keys = list(EXAMPLES.keys())
                        asset_key = gr.Dropdown(
                            choices=_example_keys, value=_example_keys[0] if _example_keys else None,
                            container=False, show_label=False,
                        )
                        _label("Custom asset", "dir · cond.npy · dataset:type",
                               tip="A rig_preprocess directory, a cond.npy file, or a dataset object type like truebones:Dragon or mixamo.")
                        custom_asset = gr.Textbox(
                            placeholder="e.g. truebones:Dragon · objaverse:<uid> · mixamo · outputs/rig/dragon",
                            container=False, show_label=False,
                        )

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("02 · Prompt", "Describe the motion",
                              "Short caption in training style — start with “An object”, describe one motion.")
                        _label("Prompt", "one motion per line",
                               tip="Describe one motion, starting with An object. For a longer animation enable Motion expansion and put one prompt per line.")
                        prompt = gr.Textbox(
                            lines=3, placeholder="An object trots forward.",
                            container=False, show_label=False,
                        )
                        seg_hint = gr.HTML(_seg_hint("", False, 10), container=False)
                        gr.Examples(SAMPLE_PROMPTS, inputs=prompt, label="Try a prompt", examples_per_page=6)
                        gr.Examples(EXPAND_PROMPTS, inputs=prompt, label="Expansion examples", examples_per_page=3)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("03 · Motion expansion", "Make it longer",
                              "Enable it and write one prompt per line. N lines → 60 + (60 − overlap) × (N − 1) frames.")
                        motion_expand = gr.Checkbox(
                            value=False, label="Enable motion expansion",
                        )
                        _label("Expansion overlap (frames)", "lower = longer, less smooth",
                               tip="How many frames consecutive segments share. Lower overlap makes the result longer but can look less smooth.")
                        expand_overlap = gr.Slider(
                            1, 40, value=10, step=1, container=False, show_label=False,
                        )

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("04 · Sampling", "Tune generation")
                        with gr.Row():
                            with gr.Column(min_width=0):
                                _label("Repetitions",
                                       tip="How many independent samples to generate for the same prompt.")
                                num_reps = gr.Slider(1, 4, value=1, step=1, container=False, show_label=False)
                            with gr.Column(min_width=0):
                                _label("CFG scale",
                                       tip="How strongly the prompt is followed. Higher = closer to the text, lower = smoother and calmer.")
                                cfg_scale = gr.Slider(1.0, 8.0, value=3.0, step=0.5, container=False, show_label=False)
                        _label("Seed", "blank = random",
                               tip="Fix the random seed for reproducible samples. Blank picks a random one.")
                        seed = gr.Number(value=None, precision=0, container=False, show_label=False)
                        animate_mesh = gr.Checkbox(value=True, label="Animate mesh (GLB + FBX)")
                        loop_anim = gr.Checkbox(value=False, label="Loop (seamless cycle)")
                        gr.HTML('<p class="um-hint">Crossfades the clip tail into its head '
                                'so it repeats without a jump.</p>', container=False)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("05 · History", "Past generations",
                              "Pick a generation to restore its prompt and settings.")
                        history = gr.Dropdown(
                            choices=_history_choices(), value=None, interactive=True,
                            container=False, show_label=False,
                        )

                    run_btn = gr.Button("Generate motion", variant="primary", size="lg",
                                        elem_classes="um-generate")

                # ── Stage: outputs ───────────────────────────────────────────
                with gr.Column(scale=7, min_width=420, elem_classes="um-stage"):
                    status = gr.HTML(_pill("idle", "Idle"))

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Animated mesh", "3D preview",
                              "Drag to rotate · scroll to zoom · the latest generated GLB plays here.")
                        model3d = gr.HTML(_viewer_html(None), elem_classes="um-viewer")

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Rendered motions", "Videos & rest poses")
                        gallery = gr.Gallery(
                            label=None, show_label=False, container=False,
                            columns=2, height=320, object_fit="contain",
                        )

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Downloads", "GLB · FBX · NPY")
                        files = gr.Files(label=None, show_label=False, container=False)

                    with gr.Accordion("Log", open=False):
                        log = gr.Textbox(label=None, show_label=False, lines=18,
                                         interactive=False, autoscroll=True)

        with gr.Tab("Import & Adaptation", id="import"):
            with gr.Row(elem_classes="um-main"):
                # ── Sidebar: import controls ─────────────────────────────────
                with gr.Column(scale=4, min_width=320, elem_classes="um-sidebar"):
                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("01 · Source", "Import a rigged model",
                              "Upload a GLB / glTF / FBX with one armature (a skinned mesh gives a 3D preview).")
                        _label("Upload")
                        import_file = gr.File(file_types=[".glb", ".gltf", ".fbx"],
                                              type="filepath", container=False, show_label=False)
                        _label("…or a server path", "assets/sources/Eagle.fbx")
                        import_path = gr.Textbox(placeholder="assets/sources/Eagle.fbx",
                                                 container=False, show_label=False)
                        _label("Asset name", "blank = from the file")
                        import_name = gr.Textbox(placeholder="eagle",
                                                 container=False, show_label=False)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("02 · Processing", "Profile & annotation")
                        _label("Profile",
                               tip="auto picks general for most inputs, truebones for a species' clips, objaverse for single-mesh GLBs.")
                        import_profile = gr.Dropdown(
                            choices=["auto", "general", "objaverse", "truebones"],
                            value="auto", container=False, show_label=False,
                        )
                        _label("Joint labels", "rule = offline · llm = needs an API key",
                               tip="rule labels offline with a learned vocabulary; llm needs an API key and handles unusual rigs better.")
                        import_annotate = gr.Dropdown(
                            choices=["auto", "rule", "llm"], value="auto",
                            container=False, show_label=False,
                        )
                        _label("Rest rotation", "stand up a lying / upside-down rig, e.g. x180",
                               tip="Axis turns applied to the rest pose, e.g. x180 or x90,y180. Leave blank for most rigs.")
                        import_rest = gr.Textbox(placeholder="",
                                                 container=False, show_label=False)
                        import_clips = gr.Checkbox(
                            value=False, label="Keep the asset's clips (in-betweening / editing)")
                        import_overwrite = gr.Checkbox(
                            value=False, label="Overwrite an existing output")

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("03 · Facing pair", "Two joints that define forward",
                              "Right/Left limbs, or head/tail for a limbless body. Filled from the analysis.")
                        _label("Right (or head) — raw joint",
                               tip="Raw bone name of the asset's right joint (or the head end for a limbless body).")
                        face_r = gr.Textbox(container=False, show_label=False)
                        _label("Left (or tail) — raw joint",
                               tip="Raw bone name of the asset's left joint (or the tail end for a limbless body).")
                        face_l = gr.Textbox(container=False, show_label=False)
                        body_axis = gr.Checkbox(value=False, label="Head / tail axis (limbless body)")

                    analyse_btn = gr.Button("1) Analyse & label", variant="primary", size="lg",
                                            elem_classes="um-generate")

                # ── Main: review & build ─────────────────────────────────────
                with gr.Column(scale=7, min_width=420, elem_classes="um-stage"):
                    import_status = gr.HTML(_pill("idle", "Idle"))

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Review", "Labels & facing",
                              "Edit the label column, fix the facing pair, then build.")
                        import_preview = gr.Image(label=None, show_label=False, container=False,
                                                  height=300, interactive=False)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Joints", "Editable labels",
                              "Only the label column is editable; flags show what to check.")
                        joints_df = gr.Dataframe(
                            headers=IMPORT_HEADERS,
                            datatype=["number", "str", "str", "str", "str"],
                            interactive=True, static_columns=[0, 1, 2, 4],
                            max_height=380, label=None, show_label=False, wrap=True,
                        )

                    with gr.Accordion("Review notes (REVIEW.md)", open=False):
                        import_review = gr.Markdown("")

                    build_btn = gr.Button("2) Build asset", variant="primary", size="lg",
                                          elem_classes="um-generate")

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Result", "Canonical asset",
                              "cond.npy + the canonical GLB; the last step's summary below.")
                        import_model = gr.HTML(_viewer_html(None), elem_classes="um-viewer")
                        import_summary = gr.JSON(label=None, show_label=False, container=False)

                    use_btn = gr.Button("Use in Generate →", variant="secondary", size="lg",
                                        elem_classes="um-generate")

                    with gr.Accordion("Log", open=False):
                        import_log = gr.Textbox(label=None, show_label=False, lines=18,
                                                interactive=False, autoscroll=True)

            import_outdir = gr.State(None)
            import_ann = gr.State(None)
            import_input = gr.State(None)

        with gr.Tab("Export", id="export"):
            with gr.Row(elem_classes="um-main"):
                # ── Sidebar: VAT settings ────────────────────────────────────
                with gr.Column(scale=4, min_width=320, elem_classes="um-sidebar"):
                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("01 · Source", "Animated mesh",
                              "Pick a generated animation (or upload a GLB) to bake into a VAT.")
                        _label("Recent generated GLBs",
                               tip="Animations produced by the Generate tab; pick one to bake.")
                        vat_source = gr.Dropdown(choices=_vat_choices(), value=None,
                                                 container=False, show_label=False)
                        _label("Upload an animated GLB")
                        vat_upload = gr.File(file_types=[".glb", ".gltf"], type="filepath",
                                             container=False, show_label=False)
                        _label("…or a server path")
                        vat_path = gr.Textbox(placeholder="outputs/samples/.../animated/*.glb",
                                              container=False, show_label=False)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("02 · Bake", "VAT settings")
                        _label("Name", "blank = from the file",
                               tip="Output folder name: outputs/vat/<name>_vat/.")
                        vat_name = gr.Textbox(placeholder="human_walk",
                                              container=False, show_label=False)
                        with gr.Row():
                            with gr.Column(min_width=0):
                                _label("FPS",
                                       tip="Source animation frame rate; keep 30 for UniMate clips.")
                                vat_fps = gr.Number(value=30, precision=0,
                                                    container=False, show_label=False)
                            with gr.Column(min_width=0):
                                _label("Texture",
                                       tip="png16 is best quality (Unreal needs RGB16); png8 is smaller and widely compatible.")
                                vat_format = gr.Dropdown(choices=["png16", "png8"], value="png16",
                                                         container=False, show_label=False)
                        _label("Normals",
                               tip="packed stores normals in the lower half of the same texture; none bakes positions only.")
                        vat_normals = gr.Dropdown(choices=["packed", "none"], value="packed",
                                                  container=False, show_label=False)
                    bake_btn = gr.Button("Bake VAT", variant="primary", size="lg",
                                         elem_classes="um-generate")

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Existing exports", "This run's files",
                              "GLB / FBX / NPY / video already produced by the generation.")
                        existing_files = gr.Files(label=None, show_label=False, container=False)

                # ── Main: VAT outputs ────────────────────────────────────────
                with gr.Column(scale=7, min_width=420, elem_classes="um-stage"):
                    vat_status = gr.HTML(_pill("idle", "Idle"))

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Result", "VAT files",
                              "Position (+ packed normals) texture, remap JSON and the proxy mesh.")
                        vat_files = gr.Files(label=None, show_label=False, container=False)

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Proxy mesh", "3D preview",
                              "The static proxy the engine shader displaces with the VAT.")
                        vat_model = gr.HTML(_viewer_html(None), elem_classes="um-viewer")

                    with gr.Column(variant="panel", elem_classes="um-card"):
                        _card("Engine setup", "Unity · Unreal 5 · Godot")
                        gr.Markdown(ENGINE_SETUP_MD)
                        engine_tools = gr.Files(value=_engine_tool_files(), label=None,
                                                show_label=False, container=False)

                    with gr.Accordion("Log", open=False):
                        vat_log = gr.Textbox(label=None, show_label=False, lines=18,
                                             interactive=False, autoscroll=True)

    gr.HTML(
        '<div class="um-foot">UniMate · '
        '<a href="https://linzhanmou.com/unimate/" target="_blank" rel="noreferrer">project page</a>'
        ' · <a href="https://arxiv.org/abs/2609.05415" target="_blank" rel="noreferrer">arXiv</a>'
        "</div>"
    )

    run_btn.click(
        generate,
        inputs=[asset_key, custom_asset, prompt, num_reps, cfg_scale, seed,
                animate_mesh, motion_expand, expand_overlap, loop_anim],
        outputs=[model3d, gallery, files, log, status, history],
    )

    for comp in (prompt, motion_expand, expand_overlap):
        comp.change(_seg_hint, inputs=[prompt, motion_expand, expand_overlap], outputs=seg_hint)

    history.input(
        restore,
        inputs=history,
        outputs=[asset_key, custom_asset, prompt, num_reps, cfg_scale, seed,
                 animate_mesh, motion_expand, expand_overlap, loop_anim,
                 model3d, gallery, files, log, status],
    )

    analyse_btn.click(
        analyse_asset,
        inputs=[import_file, import_path, import_name, import_profile, import_annotate,
                face_r, face_l, body_axis, import_rest, import_clips, import_overwrite],
        outputs=[import_log, import_preview, import_review, joints_df, face_r, face_l,
                 body_axis, import_outdir, import_ann, import_input, import_status],
    )

    build_btn.click(
        build_asset,
        inputs=[joints_df, face_r, face_l, body_axis, import_outdir, import_ann,
                import_input, import_profile, import_rest, import_clips],
        outputs=[import_log, import_preview, import_model, import_summary, import_status],
    )

    use_btn.click(
        lambda d: gr.update(value=d or ""),
        inputs=import_outdir,
        outputs=custom_asset,
    )

    vat_source.input(show_exports, inputs=vat_source, outputs=existing_files)

    bake_btn.click(
        bake_vat,
        inputs=[vat_source, vat_upload, vat_path, vat_name, vat_fps, vat_format, vat_normals],
        outputs=[vat_log, vat_status, vat_files, vat_model],
    )


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                theme=theme, css=CSS, footer_links=[],
                head=MV_HEAD, allowed_paths=[os.path.join(ROOT, "assets", "vendor")])
