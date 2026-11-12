# UniMate motion: text-to-motion for any skeleton

The studio's **Animate** step has two routes: preset moves (SkinTokens + Kimodo clips,
humanoids only) and **UniMate motion** — one sentence, any skeleton. This page is about
the second.

## What happens

One job, three subprocesses, all in UniMate's own environment (`.venv`, Python 3.10 —
the studio's `.venv-studio` cannot hold both numpy pins):

1. **Adapt** — `data_process.rig_preprocess` labels the joints with the offline rules
   (`--annotate rule --no_review`) and bakes `cond.npy` + the canonical GLB. No review
   step: the studio is a one-click flow; label quality follows the rule vocabulary.
2. **Sample** — `unimate.inference.sample` writes one motion per repetition
   (`cfg_scale`, `repetitions`, `seed`).
3. **Animate** — `scripts/animate_samples.py` drives the canonical mesh and exports
   GLB + FBX per repetition.

The animated GLB is copied into the rig's folder as `<base>_<slug>.glb`, so the Library
lists it beside the rig like a preset clip. Working files stay in
`output/motion/<stem>__motion__<stamp>/`.

## Writing prompts

UniMate was trained on short captions that start with **"An object"** and name one
motion, not the character:

- "An object walks forward." — good
- "A golden eagle flaps its wings in the sky." — the model follows this less well

Shipped prompts are in `image_to_3dlab/unimate_prompts.json` (the studio and the MCP read
that one list). Generate several samples (`repetitions`) and try a few phrasings; left /
right in a prompt is followed unreliably.

## Licensing

UniMate's code is MIT, but the released checkpoint (`Linzhan/UniMate`) is **CC BY-NC
4.0**: motion generated with it is not for commercial use. Every run writes a
`.provenance.json` beside the animated GLB with `classification: "research-only"` and the
checkpoint's licence, alongside the source model's own licence record.

## Setup

- `.venv` with the checkpoint: `install.bat` (Windows) / `bash install.sh` (Linux) —
  the installer asks before downloading (~6 GB).
- The studio itself: `install_studio.ps1` / `install_studio.sh` (packages only).
- The **Setup & Status** page shows which piece is missing, and the Motion step refuses
  with the same message until it is in place.

## Agents

MCP clients reach the step two ways:

- `create(want="motion", description=..., motion_prompt="An object walks forward.")`
  — the whole flow from an idea or picture.
- `make_motion(asset_id, prompt, repetitions)` — one more clip on a rigged asset.

## CLI

The research CLI is unchanged and works on any `rig_preprocess` directory:

```bash
.venv/bin/python -m unimate.inference.sample \
    --exp_dir outputs/unimate_uniml3d_f60_v3 --asset <dir> --prompt "An object walks forward."
.venv/bin/python scripts/animate_samples.py <samples_dir>
```
