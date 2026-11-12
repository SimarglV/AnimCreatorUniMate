# Use the UniMate studio from your agent

Claude Code, Codex, Kimi and other agents can drive the studio through **MCP** (Model
Context Protocol, the standard way agents plug in tools). Your agent can make pictures, 3D
models and animated characters, look at the results, and open them in the studio for you.
Everything still runs on your own machine.

Install first ([the studio section](../README.md#-the-studio)). The examples below assume
the repo is checked out at `~/UniMate`. Change the path if yours is somewhere else.

## Let your agent install it

No studio yet? Ask your agent: *"Install the UniMate studio and connect it to yourself."*
These are the steps it should follow (agents: run them as written):

1. `bash install.sh` for UniMate's own environment and checkpoint (it asks before the ~6 GB
   download), then `bash install_studio.sh --dry-run` and tell the user what it will do:
   Python 3.11 and the studio's packages, **no model weights**.
2. After the user says yes: `bash install_studio.sh --yes`.
3. Connect, using the matching line below (for Claude Code:
   `claude mcp add unimate -- ~/UniMate/lab mcp`).
4. Tell the user to start a new session so the tools load. Then `status` and `list_engines`
   show what to set up next, and `install_backend` asks before downloading any weights.

## Connect your agent

**Claude Code**
```bash
claude mcp add unimate -- ~/UniMate/lab mcp
```

**Codex**
```bash
codex mcp add unimate -- ~/UniMate/lab mcp
```
or in `~/.codex/config.toml`:
```toml
[mcp_servers.unimate]
command = "/Users/you/UniMate/lab"
args = ["mcp"]
```

**Kimi Code CLI**
```bash
kimi mcp add --transport stdio unimate -- ~/UniMate/lab mcp
```

**Anything else** that reads the common JSON config (Claude Desktop, Cursor and many more):
```json
{ "mcpServers": { "unimate": { "command": "/Users/you/UniMate/lab", "args": ["mcp"] } } }
```

**Clients that want a web address** (for example Muse Code): run
`~/UniMate/lab mcp --http` and point the client at `http://127.0.0.1:8779/mcp`. It only
listens on this machine.

The studio does not need to be open: the first tool call starts it in the background.

## What your agent can do

| Tool | What it does |
|---|---|
| `status` | What's installed, and what's running now |
| `list_engines` | Every engine, whether it's ready, its licence and download size |
| `list_moves` | The preset animation moves (idle, walk, run, wave, ...) |
| `create` | Make something new: a picture, one prop, nine props, an animated character, or a character moved by text (want="motion", motion_prompt=... — UniMate animates any skeleton), from an idea, a picture or a GLB |
| `continue_asset` | Take an existing asset further (picture to 3D, rig it, another move, one more text motion), or make a step again as a new version, such as a full-detail Finish |
| `make_motion` | UniMate text-to-motion on a rigged asset: one sentence, any skeleton, 1-4 samples |
| `run_status` | How a run is going (it waits, so the agent isn't spamming) |
| `cancel_run` | Stop a run |
| `list_assets` | Your Library |
| `options` | Every knob, as the studio's Advanced panels show them: what each does, its default and when to try it |
| `list_versions` | Every version of one character: its 3D models, Finishes and rigs, raw model included |
| `preview` | A picture of the asset from four sides, or four moments of one of its moves, so the agent can see it and show you |
| `open_in_studio` | Opens the asset in your browser, so you can spin it and play its moves |
| `model_info` | A model's numbers (triangles, vertices, textures and their sizes, bones, moves, file size) and its full path on your computer |
| `show_in_folder` | Opens the folder holding a model in Finder or Explorer, with the file selected |
| `make_skin` | A new skin for a finished Pixal3D model: say what to change ("make the skirt gold"), and the same model gets new paint. Its rig and moves still fit |
| `skin_status` / `skin_picture` | Where a skin is, and its new pictures, so the agent can show you each one before anything is built |
| `approve_skin_picture` / `redo_skin_picture` | Your verdict on a picture: approve it, or ask again with a correction. Front first, then back |
| `build_skin` / `cancel_skin` | Paint the model from the approved pictures and finish it (a few minutes), or stop that |
| `report_bug` | Drafts a bug report (your words, plus version, machine and the last error) and gives you the links to send it. It never sends anything itself |
| `install_backend` | Sets up an engine, but **only after you say yes**: it first tells the agent what it would download, the size and the licence |

When a result looks off, ask your agent to try a knob: it can call `options`, then redo just
that step as a new version, for example *"redo the Finish with Pixel Match's nudge off"*
becomes `continue_asset(asset_id, up_to="finished", again=True, advanced={"nudge": false})`.

Your agent can't delete, hide or rename assets, or paste your Hugging Face token. Those stay
with you, in the studio.

## Try it

> Make me a knight walking forward, then show me what it looks like.

A character takes a while (roughly 15-25 minutes start to finish on our test Mac; yours may differ). Your
agent will check on it and show you the preview when it's done.

## For contributors

The MCP server (`image_to_3dlab/mcp_server.py`) is a thin client of the studio's own API, so
new engines, moves and prompt wording reach agents on their own. Two tests keep it that way:
`tests/test_agent_plan.py` checks the agent's step rules against the studio's `plan.js`, and
`tests/test_mcp_server.py` fails when the studio gains an action that agents can't reach and
that isn't listed as studio-only.

## Blender helpers

Beyond the studio, the repo has about 40 Blender scripts (stage, render, bake, remesh, rig,
animate). Ask your agent to call `blender_helpers`: it lists each one, what it does and how to
run it. *Live* helpers work in your open Blender and need the
[BlenderMCP](https://github.com/ahujasid/blender-mcp) add-on running (port 9876); they change
that scene, so your agent should ask first. *Headless* ones start their own background Blender.
