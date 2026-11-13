# UniMate motion: text-to-motion for any skeleton

The studio's **Animate** step has two routes: preset moves (SkinTokens + Kimodo clips,
humanoids only) and **UniMate motion** — one sentence, any skeleton. This page is about
the second.

## How to run it in the studio

**Animate a rig** (top bar) animates a rig you bring, whatever its skeleton:

- a **built-in example** (crab, dragon, eagle, shark, snake, human, Unitree Go2) — already
  adapted, goes straight to sampling;
- an **uploaded rigged GLB/glTF/FBX**, or a **path** on this machine — adapted on the fly.

**Import rig** is UniMate's own full workflow: upload a rig, review and fix the joint
labels and the facing pair, then build the asset (cond.npy + canonical GLB) and animate it.
Imported rigs show up in the Library as rigged characters, so they can be animated again
later from the Steps panel's Animate step.

The same UniMate motion runs on humanoid characters through the normal pipeline
(**Create → A character moved by text**, or the Animate step after the rig).

Every run returns the animated GLB + FBX, the rendered videos and T-pose stills.
**Motion expansion** (a checkbox in Animate a rig) chains several prompts, one per line,
into one long clip.

## What happens

One job, up to three subprocesses, all in UniMate's own environment (`.venv`, Python 3.10 —
the studio's `.venv-studio` cannot hold both numpy pins):

1. **Adapt** (skipped for an already-adapted rig) — `data_process.rig_preprocess` labels
   the joints with the offline rules (`--annotate rule --no_review`) and bakes `cond.npy` +
   the canonical GLB. No review step: the studio is a one-click flow; label quality follows
   the rule vocabulary.
2. **Sample** — `unimate.inference.sample` writes one motion per repetition
   (`cfg_scale`, `repetitions`, `seed`).
3. **Animate** — `scripts/animate_samples.py` drives the canonical mesh and exports
   GLB + FBX per repetition.

For a humanoid in the Library the animated GLB is copied into the rig's folder as
`<base>_<slug>.glb`, so it lists beside the rig like a preset clip. Imported rigs keep
their result in `output/motion/<stem>__motion__<stamp>/`.

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
