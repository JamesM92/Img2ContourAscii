#!/usr/bin/env python3
"""
Python port of Alex Harri's sub-character ASCII rendering.
Reference: https://alexharri.com/blog/ascii-rendering

Algorithm (faithful to the original):
  - Six internal sampling circles per cell → 6D shape vector
  - Ten external circles just outside cell boundaries → directional crunch
  - Global crunch (normalize-power-restore) on top of directional crunch
  - KD-tree nearest-neighbor lookup against pre-computed character vectors

Extras beyond Alex's original design:
  - ANSI 24-bit colour output  (--color)
  - Write to file              (-o)
"""

import argparse
import json
import os
import numpy as np
from PIL import Image
from scipy.spatial import KDTree


# ─────────────────────────────────────────────────────────────────────────────
# Sampling geometry  —  values taken directly from default.json metadata
# ─────────────────────────────────────────────────────────────────────────────

# Internal circle centres as (x, y) fractions of (cell_w, cell_h)
INTERNAL_CIRCLES = [
    (0.30, 0.23), (0.70, 0.18),   # top row    (staggered for better coverage)
    (0.30, 0.50), (0.70, 0.50),   # middle row
    (0.30, 0.82), (0.70, 0.77),   # bottom row (staggered)
]

# Circle radius as a fraction of cell_w
# default.json: circleRadius=0.28125, width=1.0  →  radius = 0.28125 * cell_w
CIRCLE_RADIUS = 0.28125

# External circles placed just outside the cell for directional crunch
# Positions taken from default.json externalPoints
EXTERNAL_CIRCLES = [
    ( 0.07, -0.21), ( 0.93, -0.21),   # 0, 1 : above
    (-0.25,  0.07), ( 1.25,  0.07),   # 2, 3 : upper left / right
    (-0.25,  0.50), ( 1.25,  0.50),   # 4, 5 : mid   left / right
    (-0.25,  0.93), ( 1.25,  0.93),   # 6, 7 : lower left / right
    ( 0.07,  1.21), ( 0.93,  1.21),   # 8, 9 : below
]

# Which external circles affect each internal circle (from default.json affectsMapping)
AFFECTING_EXTERNAL = [
    [0, 1, 2, 4],   # internal 0  top-left
    [0, 1, 3, 5],   # internal 1  top-right
    [2, 4, 6],      # internal 2  mid-left
    [3, 5, 7],      # internal 3  mid-right
    [4, 6, 8, 9],   # internal 4  bot-left
    [5, 7, 8, 9],   # internal 5  bot-right
]

# Cell height-to-width ratio  (default.json: height=4/3, width=1.0)
CELL_ASPECT = 4 / 3


# ─────────────────────────────────────────────────────────────────────────────
# Character vectors
# ─────────────────────────────────────────────────────────────────────────────

def load_char_vectors():
    path = os.path.join(os.path.dirname(__file__), "default.json")
    with open(path) as f:
        data = json.load(f)
    chars = [e["char"] for e in data["characters"]]
    vecs  = np.array([e["vector"] for e in data["characters"]], dtype=np.float64)

    # Normalise each dimension by its column maximum so the space spans [0, 1]
    col_max = vecs.max(axis=0)
    col_max[col_max == 0] = 1.0
    vecs /= col_max
    return chars, vecs


# ─────────────────────────────────────────────────────────────────────────────
# Pixel masks
# ─────────────────────────────────────────────────────────────────────────────

def build_masks(cell_w, cell_h):
    """
    Pre-compute integer (dx, dy) pixel offsets relative to cell origin for
    every internal and external circle.  Circles are physically round in
    pixel space; the radius scales only with cell_w.
    """
    radius  = CIRCLE_RADIUS * cell_w
    r_ceil  = int(np.ceil(radius))
    r_sq    = radius * radius

    def make_mask(cx_frac, cy_frac):
        cx = round(cx_frac * cell_w)
        cy = round(cy_frac * cell_h)
        pts = [
            (cx + dx, cy + dy)
            for dy in range(-r_ceil, r_ceil + 1)
            for dx in range(-r_ceil, r_ceil + 1)
            if dx * dx + dy * dy < r_sq
        ]
        return pts or [(cx, cy)]   # at least one point (very small cells)

    internal = [make_mask(cx, cy) for cx, cy in INTERNAL_CIRCLES]
    external = [make_mask(cx, cy) for cx, cy in EXTERNAL_CIRCLES]
    return internal, external


# ─────────────────────────────────────────────────────────────────────────────
# Lightness
# ─────────────────────────────────────────────────────────────────────────────

def luminance(rgb):
    """Relative luminance (ITU-R BT.709).  Input shape (..., 3), output [0,1]."""
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0


# ─────────────────────────────────────────────────────────────────────────────
# Sampling
# ─────────────────────────────────────────────────────────────────────────────

def sample_circle(light, h, w, ox, oy, pts):
    total = 0.0
    for dx, dy in pts:
        total += light[min(max(oy + dy, 0), h - 1), min(max(ox + dx, 0), w - 1)]
    return total / len(pts)


def sample_cell(light, h, w, ox, oy, masks):
    return np.array([sample_circle(light, h, w, ox, oy, m) for m in masks])


# ─────────────────────────────────────────────────────────────────────────────
# Contrast enhancement
# ─────────────────────────────────────────────────────────────────────────────

def global_crunch(vec, exp):
    """
    Normalize the vector by its own maximum, raise every component to `exp`,
    then restore the original scale.  Darkens low values while keeping the
    brightest component intact — increases contrast without clipping.
    """
    m = float(vec.max())
    if m == 0.0:
        return vec.copy()
    return (vec / m) ** exp * m


def directional_crunch(sv, ev, exp):
    """
    Per-component contrast driven by external neighbours.
    For each internal component i, find the maximum value among the external
    circles that "see" the same region (AFFECTING_EXTERNAL[i]).  If that
    context value exceeds the internal value, use it as the normalisation
    denominator — this pushes the component down relative to the brighter
    neighbour, sharpening boundaries without creating staircase artefacts.
    """
    out = sv.copy()
    for i, idxs in enumerate(AFFECTING_EXTERNAL):
        ctx = max(ev[j] for j in idxs)
        if ctx <= sv[i]:
            continue
        out[i] = (sv[i] / ctx) ** exp * ctx
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Conversion
# ─────────────────────────────────────────────────────────────────────────────

def convert(image_path, cols, global_exp, directional_exp, use_color):
    chars, char_vecs = load_char_vectors()
    tree = KDTree(char_vecs)

    img     = Image.open(image_path).convert("RGB")
    img_arr = np.array(img, dtype=np.float32)
    h, w    = img_arr.shape[:2]
    light   = luminance(img_arr)

    cell_w = w / cols
    cell_h = cell_w * CELL_ASPECT
    rows   = max(1, round(h / cell_h))

    int_masks, ext_masks = build_masks(cell_w, cell_h)

    lines = []
    for r in range(rows):
        line = ""
        for c in range(cols):
            ox = int(c * cell_w)
            oy = int(r * cell_h)

            sv = sample_cell(light, h, w, ox, oy, int_masks)
            ev = sample_cell(light, h, w, ox, oy, ext_masks)

            sv = directional_crunch(sv, ev, directional_exp)
            sv = global_crunch(sv, global_exp)

            _, idx = tree.query(sv)
            char = chars[idx]

            if use_color and char != " ":
                cw  = min(int(cell_w), w - ox)
                ch  = min(int(cell_h), h - oy)
                rgb = np.mean(img_arr[oy:oy + ch, ox:ox + cw], axis=(0, 1))
                rgb_q = (rgb // 16) * 16
                mx = rgb_q.max()
                if mx > 0:
                    rgb_q = np.clip(rgb_q * (255.0 / mx), 0, 255)
                char = (
                    f"\033[38;2;{int(rgb_q[0])};{int(rgb_q[1])};{int(rgb_q[2])}m"
                    f"{char}\033[0m"
                )

            line += char

        lines.append(line)
        print(f"\rRendering row {r + 1}/{rows}", end="", flush=True)

    print("\r" + " " * 30 + "\r", end="", flush=True)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ASCII renderer — faithful Python port of Alex Harri's design",
    )
    parser.add_argument("image", help="input image file")
    parser.add_argument(
        "-o", "--output", nargs="?", const="",
        help="write to file; omit filename to auto-generate from input name",
    )
    parser.add_argument("--cols", type=int, default=80,
                        help="output columns (default: 80)")
    parser.add_argument("--global-crunch", dest="global_exp",
                        type=float, default=2.2,
                        help="global contrast exponent (default: 2.2)")
    parser.add_argument("--directional-crunch", dest="directional_exp",
                        type=float, default=2.8,
                        help="directional contrast exponent (default: 2.8)")
    parser.add_argument("--color", action="store_true",
                        help="enable ANSI 24-bit colour output")
    args = parser.parse_args()

    result = convert(
        args.image, args.cols,
        args.global_exp, args.directional_exp,
        args.color,
    )

    if args.output is not None:
        path = args.output or (
            os.path.splitext(os.path.basename(args.image))[0] + ".txt"
        )
        with open(path, "w") as f:
            f.write(result)
        print(f"Saved to {path}")
    else:
        print(result)


if __name__ == "__main__":
    main()
