"""Windows-friendly batch mesh animation for a sampler output directory.

Replicates the manifest mode of ``scripts/run_animate_motion.sh`` without bash:
for every motion in ``<samples_dir>/manifest.json``, drive its canonical GLB
with the motion and export GLB + FBX.

    python scripts/animate_samples.py <samples_dir> [output_dir] [--include_gt] [--skip_invalid]

Each motion is animated in its own Blender (pip ``bpy``) process, mirroring the
bash wrapper's one-``blender``-process-per-motion isolation.
"""

import argparse
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from data_process.mesh_animation.sample_manifest import build_jobs  # noqa: E402

ANIMATE_MOTION = os.path.join(
    PROJECT_ROOT, "data_process", "mesh_animation", "animate_motion.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Animate every motion in a sampler "
                                             "run's manifest.json (GLB + FBX).")
    ap.add_argument("samples_dir", help="Samples directory holding manifest.json "
                                        "(or the manifest itself).")
    ap.add_argument("output_dir", nargs="?", default=None,
                    help="Directory for .glb/.fbx (default: <samples_dir>/animated).")
    ap.add_argument("--include_gt", action="store_true",
                    help="Also drive saved ground truth of in-betweening / editing.")
    ap.add_argument("--skip_invalid", action="store_true",
                    help="Report motions that cannot be driven and animate the rest.")
    ap.add_argument("--anim_mode", default="fk", choices=["fk", "ik"],
                    help="Recovery mode for .npy model-feature input (default fk).")
    ap.add_argument("--loop", action="store_true",
                    help="Crossfade each clip's tail into its head for a seamless loop.")
    args = ap.parse_args(argv)

    try:
        jobs, problems = build_jobs(args.samples_dir, include_gt=args.include_gt)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    if problems and not args.skip_invalid:
        return 1
    if not jobs:
        print("error: no motions to drive", file=sys.stderr)
        return 1

    output_dir = args.output_dir or os.path.join(args.samples_dir, "animated")
    os.makedirs(output_dir, exist_ok=True)

    total = len(jobs)
    print(f"{total} motion(s) -> {output_dir}")
    for i, (anim, char, cond, dtype) in enumerate(jobs, 1):
        stem = os.path.splitext(os.path.basename(anim))[0]
        print(f"[{i}/{total}] {stem}  (dataset_type={dtype})")
        cmd = [
            sys.executable, ANIMATE_MOTION,
            "--dataset_type", dtype,
            "--anim_path", anim,
            "--char_path", char,
            "--cond_path", cond,
            "--output_dir", output_dir,
            "--anim_mode", args.anim_mode,
        ]
        if args.loop:
            cmd.append("--loop")
        rc = subprocess.call(cmd, cwd=PROJECT_ROOT)
        fbx = os.path.join(output_dir, stem + ".fbx")
        if rc != 0 or not os.path.isfile(fbx):
            print(f"error: did not produce {fbx}", file=sys.stderr)
            return 1
    print(f"DONE - {total} motion(s) animated into {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
