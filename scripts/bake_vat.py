"""Bake an animated GLB/FBX into an AnimationVAT-compatible Vertex Animation Texture.

Output (``<output_dir>/<name>_vat/``), matching AnimationVAT's "Standard (Position/
Normal), Packed normals, Single Row disabled" layout:

    <name>_vat.png          position rows (top) + packed normal rows (lower half)
    <name>-remap_info.json  os-remap Min/Max/Frames + animation metadata
    <name>.glb              static proxy mesh (frame 0) with a VAT_UV (UV2) layer

The engine shaders read the texture with ``UV2 + vec2(0, frame/height)`` and
reconstruct ``delta = Min + texel * (Max - Min)``; the proxy vertex is the
frame-0 pose, so ``vertex += delta`` reproduces the animation. Normals live at
``+0.5`` in V and are decoded as ``2*texel - 1``.

Usage:
    python scripts/bake_vat.py --input anim.glb --output_dir outputs/vat/foo \
        --name foo --fps 30 --format png16 --normals packed
"""

import argparse
import json
import math
import os

import bpy
from mathutils import Vector


def next_pow2(n):
    return 1 if n <= 1 else 2 ** math.ceil(math.log2(n))


def round_floor(v):
    return math.floor(v * 10) / 10


def round_ceil(v):
    return math.ceil(v * 10) / 10


def png_chunk(tag, data):
    import struct
    import zlib
    chunk = struct.pack('>I', len(data)) + tag + data
    return chunk + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path, pixels, bit_depth):
    """Write an RGB PNG from a (H, W, 3) array of uint values.

    ``bit_depth`` 8 -> uint8, 16 -> uint16 (big-endian scanlines).
    """
    import struct
    import zlib
    import numpy as np

    arr = np.asarray(pixels)
    h, w = arr.shape[0], arr.shape[1]
    dtype = '>u2' if bit_depth == 16 else 'u1'
    maxv = 65535 if bit_depth == 16 else 255
    arr = np.clip(arr, 0, maxv).astype(dtype)
    raw = b''.join(b'\x00' + arr[y].tobytes() for y in range(h))
    ihdr = struct.pack('>IIBBBBB', w, h, bit_depth, 2, 0, 0, 0)  # 2 = truecolor
    png = (b'\x89PNG\r\n\x1a\n'
           + png_chunk(b'IHDR', ihdr)
           + png_chunk(b'IDAT', zlib.compress(raw, 6))
           + png_chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def find_mesh():
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError("No mesh found in the imported asset.")
    return max(meshes, key=lambda o: len(o.data.vertices))


def animation_range(mesh):
    actions = [a for a in bpy.data.actions if a.frame_range[1] > a.frame_range[0]]
    if actions:
        action = max(actions, key=lambda a: (a.frame_range[1] - a.frame_range[0]))
        start, end = action.frame_range
        return int(math.ceil(start)), int(math.floor(end))
    scene = bpy.context.scene
    return int(scene.frame_start), int(scene.frame_end)


def evaluated(mesh, frame):
    bpy.context.scene.frame_set(frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = mesh.evaluated_get(depsgraph)
    me = obj_eval.to_mesh()
    co = [v.co.copy() for v in me.vertices]
    try:
        nrm = [me.vertex_normals[i].vector.copy() for i in range(len(me.vertices))]
    except Exception:
        nrm = [v.normal.copy() for v in me.vertices]
    obj_eval.to_mesh_clear()
    return co, nrm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output_dir', required=True)
    ap.add_argument('--name', default=None)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--format', choices=['png16', 'png8'], default='png16')
    ap.add_argument('--normals', choices=['packed', 'none'], default='packed')
    ap.add_argument('--max_width', type=int, default=8192)
    args = ap.parse_args()

    name = args.name or os.path.splitext(os.path.basename(args.input))[0]
    out_dir = os.path.join(args.output_dir, f'{name}_vat')
    os.makedirs(out_dir, exist_ok=True)

    bpy.context.scene.render.fps = args.fps
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = args.fps
    bpy.ops.import_scene.gltf(filepath=args.input)

    mesh = find_mesh()
    f0, f1 = animation_range(mesh)
    frames = f1 - f0 + 1
    print(f'[vat] mesh={mesh.name} verts={len(mesh.data.vertices)} frames={frames} ({f0}..{f1}) fps={args.fps}')

    proxy_co, _ = evaluated(mesh, f0)
    num_verts = len(proxy_co)

    # Sample all frames (object-space positions + normals).
    all_co, all_nrm = [], []
    for f in range(f0, f1 + 1):
        co, nrm = evaluated(mesh, f)
        all_co.append(co)
        all_nrm.append(nrm)
        if (f - f0) % 10 == 0 or f == f1:
            print(f'[vat] sampled {f - f0 + 1}/{frames}')

    # Deltas relative to the proxy (frame 0).
    mins = [float('inf')] * 3
    maxs = [float('-inf')] * 3
    for fi in range(frames):
        for vi in range(num_verts):
            d = all_co[fi][vi] - proxy_co[vi]
            for c in range(3):
                if d[c] < mins[c]:
                    mins[c] = d[c]
                if d[c] > maxs[c]:
                    maxs[c] = d[c]
    mins = [round_floor(v) for v in mins]
    maxs = [round_ceil(v) for v in maxs]
    span = [maxs[c] - mins[c] or 1.0 for c in range(3)]
    print(f'[vat] os-remap min={mins} max={maxs}')

    # Texture layout: vertices wrapped over rows, frames advance down.
    width = min(next_pow2(num_verts), args.max_width)
    wraps = math.ceil(num_verts / width)
    pos_rows = wraps * frames
    packed = args.normals == 'packed'
    height = next_pow2(2 * pos_rows) if packed else next_pow2(pos_rows)
    normal_offset = height // 2 if packed else None
    print(f'[vat] texture {width}x{height} (wraps={wraps}, packed={packed})')

    import numpy as np
    maxv = 65535 if args.format == 'png16' else 255
    tex = np.zeros((height, width, 3), dtype=np.float64)

    # Positions.
    for fi in range(frames):
        for vi in range(num_verts):
            d = all_co[fi][vi] - proxy_co[vi]
            col = vi % width
            row = (vi // width) * frames + fi
            for c in range(3):
                tex[row, col, c] = (d[c] - mins[c]) / span[c]

    # Packed normals in the lower half.
    if packed:
        for fi in range(frames):
            for vi in range(num_verts):
                n = all_nrm[fi][vi]
                col = vi % width
                row = (vi // width) * frames + fi + normal_offset
                for c in range(3):
                    tex[row, col, c] = n[c] * 0.5 + 0.5

    png_path = os.path.join(out_dir, f'{name}_vat.png')
    write_png(png_path, tex * maxv, 16 if args.format == 'png16' else 8)
    print(f'[vat] wrote {png_path}')

    remap = {
        'os-remap': {'Min': mins, 'Max': maxs, 'Frames': frames},
        'animations': [{'name': name, 'startFrame': 0, 'endFrame': frames - 1,
                        'framerate': args.fps, 'looping': True}],
    }
    remap_path = os.path.join(out_dir, f'{name}-remap_info.json')
    with open(remap_path, 'w') as f:
        json.dump(remap, f, indent=4)
    print(f'[vat] wrote {remap_path}')

    # Proxy mesh: the frame-0 evaluated mesh, static, with VAT_UV as UV2.
    bpy.context.scene.frame_set(f0)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = mesh.evaluated_get(depsgraph)
    proxy_me = bpy.data.meshes.new_from_object(obj_eval)

    bpy.ops.object.select_all(action='DESELECT')
    proxy_obj = bpy.data.objects.new(f'{name}_vat', proxy_me)
    bpy.context.scene.collection.objects.link(proxy_obj)
    proxy_obj.matrix_world = mesh.matrix_world.copy()

    # Second UV layer (VAT_UV) -> glTF TEXCOORD_1 -> engine UV2.
    if len(proxy_me.uv_layers) == 0:
        proxy_me.uv_layers.new(name='UVMap')
    vat_uv = proxy_me.uv_layers.new(name='VAT_UV')
    for loop in proxy_me.loops:
        vi = loop.vertex_index
        col = vi % width
        block = vi // width
        u = (col + 0.5) / width
        v_top = (block * frames + 0.5) / height          # glTF-style V (top-down)
        vat_uv.data[loop.index].uv = (u, 1.0 - v_top)     # Blender V (bottom-up)
    proxy_me.uv_layers.active_index = len(proxy_me.uv_layers) - 1

    bpy.ops.object.select_all(action='DESELECT')
    proxy_obj.select_set(True)
    bpy.context.view_layer.objects.active = proxy_obj

    glb_path = os.path.join(out_dir, f'{name}.glb')
    bpy.ops.export_scene.gltf(
        filepath=glb_path, export_format='GLB', use_selection=True,
        export_apply=True, export_texcoords=True, export_normals=True,
        export_tangents=False, export_materials='EXPORT', export_yup=True,
        export_cameras=False, export_lights=False, export_animations=False,
    )
    print(f'[vat] wrote {glb_path}')
    print(f'[vat] DONE verts={num_verts} frames={frames} texture={width}x{height}')


if __name__ == '__main__':
    main()
