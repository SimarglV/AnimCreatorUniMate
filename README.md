<h1 align="center">UniMate Studio</h1>

<p align="center"><b>One sentence or picture in, a rigged, animated character out. On your own machine.</b></p>

<p align="center">
  <a href="https://linzhanmou.com/unimate/"><img alt="UniMate project" src="https://img.shields.io/badge/UniMate-6D28D9?style=for-the-badge&logo=githubpages&logoColor=white"></a>
  <a href="https://arxiv.org/abs/2609.05415"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2609.05415-B31B1B?style=for-the-badge&logo=arxiv&logoColor=white"></a>
  <a href="https://huggingface.co/Linzhan/UniMate"><img alt="Checkpoints" src="https://img.shields.io/badge/Checkpoints-FF9D00?style=for-the-badge&logo=huggingface&logoColor=000000"></a>
  <img alt="Runs on NVIDIA (Windows / Linux)" src="https://img.shields.io/badge/runs_on-NVIDIA_·_Windows_·_Linux-444">
</p>

<p align="center">
  This repository joins <a href="https://linzhanmou.com/unimate/">UniMate</a> (one unified model that
  animates any skeleton from text) with the open <b>AssetFurnace</b> studio
  (<a href="https://github.com/Bingeljell/image-to-3dlab">Apache-2.0, by Bingeljell</a>) — the pipeline that
  makes the picture, the 3D model and the skeleton that UniMate then moves.
</p>

---

## What it does

```text
sentence / picture → 3D model → finish → rig → UniMate motion → animated GLB
```

- **One flow, start to finish.** Type a sentence or drop a picture. The studio draws the
  picture (FLUX.2 / Qwen-Image), builds the 3D model (Pixal3D / TRELLIS.2 / Hunyuan3D),
  cleans it up for games (**Finish**: retopology, Pixel Match, texture compression), adds a
  skeleton (**Rig**, SkinTokens) and animates it. Close the tab and the run carries on.
- **UniMate motion — any skeleton.** Preset moves are humanoid-only; UniMate reads one
  sentence ("An object walks forward.") and animates people, animals and machines alike.
  The clip lands in your Library beside the rig. See
  [`docs/unimate-motion.md`](docs/unimate-motion.md).
- **The studio.** Your Library, one 3D viewer and a Steps panel. Every step is a button too,
  so you can stop after any of them.
- **Low poly, high quality.** Pixel Match puts your picture's real pixels back on the model,
  so text, logos and faces stay sharp even at ~5k faces.
- **One prompt, nine props.** Prop sheets turn one picture into separate, game-ready props
  with LODs.
- **Your pick of models, all local.** Pixal3D, TRELLIS.2 and Hunyuan3D behind one studio and
  one CLI. Nothing is uploaded anywhere.
- **Game-size files.** The animated GLB opens in Godot, Unity, Unreal, Blender or three.js.
- **Agents can drive it.** Claude Code, Codex and other MCP clients make, check and tweak
  assets for you (`docs/agents.md`).
- **Know what you can ship.** Every file carries a `.provenance.json` record of the licences
  behind it.

## Install & run

Two environments, because they pin conflicting numpy versions. Full step-by-step for a
fresh computer: [`INSTALL.md`](INSTALL.md) (Russian).

| Env | Python | What runs in it | Installer |
|---|---|---|---|
| `.venv` | 3.10 | UniMate: motion sampling, `rig_preprocess`, mesh animation | `install.bat` (Windows) / `bash install.sh` (Linux) — downloads the checkpoint (~6 GB, asks first) |
| `.venv-studio` | 3.11 | The studio server, engines, rigging, MCP | `install_studio.ps1` (Windows) / `bash install_studio.sh` (macOS / Linux) — packages only |

```powershell
# Windows
install.bat              # UniMate's environment + checkpoint
powershell -ExecutionPolicy ByPass -File install_studio.ps1   # the studio's packages
.\lab                    # the studio opens in your browser (run.bat does the same)
```

```bash
# Linux
bash install.sh
bash install_studio.sh
./lab
```

Then, in the studio:

1. **Setup & Status** → **Set up** an engine. **Pixal3D** is the one that runs on
   Windows + NVIDIA and the best default; TRELLIS.2 and Hunyuan3D-2.1 are Linux + NVIDIA.
   Each button states the size and licence and asks first.
2. Install **Blender 4.2+** yourself if you want Finish (the low-poly clean-up). The Setup
   page shows whether it was found.
3. **+ Create** → *An idea* → *A character moved by text* → describe it, write a motion
   prompt → **Make it**.

### Where the models live

Nothing downloads model weights without your yes: each **Set up** button and `install.bat`
name the size and licence first. The studio asks before fetching anything. Everything
downloads into the project's own `models/` folder by default (`models/huggingface`,
`models/u2net`, `models/<engine>`), so nothing leaves the repo unless you ask it to. Pick
another drive on the Setup page's **Models folder** (or `ASSETFURNACE_MODELS=<path>`). The
UniMate checkpoint lives in `outputs/unimate_uniml3d_f60_v3/`.

## UniMate: one model, any skeleton

The motion side is [UniMate](https://linzhanmou.com/unimate/)
(SIGGRAPH Asia 2026) — a single model that generates articulated motion for **arbitrary
skeletons** from text, with no per-skeleton retraining. The studio runs it on the rig it
just made, or on any rigged GLB/glTF/FBX you bring
([`rig_preprocess`](data_process/rig_preprocess/) turns it into an asset, with a review step
for joint labels and facing).

The research CLI is unchanged and works on any `rig_preprocess` directory:

```bash
.venv/bin/python -m unimate.inference.sample \
    --exp_dir outputs/unimate_uniml3d_f60_v3 --asset <rig_dir> --prompt "An object walks forward."
.venv/bin/python scripts/animate_samples.py <samples_dir>
```

Prompts follow the training style: start with "An object", name one motion, not the
character. Generate several samples and try a few phrasings.

## System requirements

| Requirement | Detail |
|---|---|
| OS | Windows or Linux (macOS is **not** supported — UniMate needs NVIDIA) |
| GPU | NVIDIA with CUDA; driver 575+ for Pixal3D's ready-made build |
| Disk | ~30 GB for the environment, checkpoint and one engine |
| Internet | First run fetches the text encoder (`google/flan-t5-base`); nothing else downloads silently |

## Training & dataset

UniMate is trained on **UniML3D**, a dataset of 13,769 text-paired motion clips on 7,430
skeletons (bipedal, quadrupedal, avian, marine, insectoid, serpentine and articulated
objects). The dataset and the full data-processing pipeline are documented in
[`data_process/README.md`](data_process/README.md) and released on
[Hugging Face](https://huggingface.co/datasets/Linzhan/UniML3D).

Launch training with Accelerate (configs in `configs/`):

```bash
accelerate launch -m unimate.training.train --config configs/uniml3d_60frames_graph_adaln.json
```

## Development

The studio's tests cover `image_to_3dlab/` and `viewer/` (see `AGENTS.md` for conventions):

```bash
.venv-studio/bin/python -m pytest -q
.venv-studio/bin/python -m pytest -q --cov-config=pyproject.toml --cov --cov-report=term-missing --cov-report=html
.venv-studio/bin/ruff check .
```

Commit checks live in `.pre-commit-config.yaml`; install them with
`uv tool install pre-commit --with pre-commit-uv`, then `pre-commit install`. On Windows,
set `$env:PYTHONUTF8 = '1'` before pytest (some tests read files with emoji and typographic
marks).

## Citation

```bibtex
@article{mou2026unimate,
  title   = {UniMate: One Unified Model to Animate Diverse Skeletons},
  author  = {Mou, Linzhan and Lei, Jiahui and Dou, Zhiyang and Cai, Chenyue and Song, Chaoyue and Finkelstein, Adam and Rusinkiewicz, Szymon},
  journal = {arXiv preprint arXiv:2609.05415},
  year    = {2026}
}
```

## License

- **UniMate** code is [MIT](LICENSE); the released checkpoint is
  [CC BY-NC 4.0](https://huggingface.co/Linzhan/UniMate/blob/main/LICENSE), so text-motion
  output is marked non-commercial in its `.provenance.json`.
- **The studio** (the `image_to_3dlab/` package, `viewer/`, `pipeline.py` and their
  scripts) is Apache-2.0 — see [`LICENSE-ASSETFURNACE-APACHE`](LICENSE-ASSETFURNACE-APACHE)
  and the [`NOTICE`](NOTICE) file.
- **Model weights** used by the studio keep their own licences, recorded per run.
- **The datasets** stay governed by their original sources (Mixamo, Objaverse-XL, Truebones).

## Acknowledgement

We thank the authors of [AnyTop](https://github.com/Anytop2025/Anytop) for open-sourcing
their codebase, on which parts of this repository build, and
[Bingeljell](https://github.com/Bingeljell) for the open AssetFurnace studio this project
merges — the full list of models and credits is in
[`docs/info_and_credits.md`](docs/info_and_credits.md).
