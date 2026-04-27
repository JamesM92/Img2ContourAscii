#!/usr/bin/env python3
"""
Generate example PNG renders and animated GIFs for the README.
Run from anywhere:  python scripts/make_examples.py
"""

import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from Img2ContourAscii import Renderer

EXAMPLES = ROOT / "examples"

# ─── brightness-only renderer ────────────────────────────────────────────────
_PAL = r'$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,"^`\'. '[::-1]

def brightness_render_arr(arr: np.ndarray, cols: int = 60,
                           invert: bool = True, autocontrast: bool = True,
                           color: bool = False) -> str:
    """Render a (H, W, 3) float32 RGB array as brightness-based ASCII."""
    h, w = arr.shape[:2]
    if autocontrast:
        lo, hi = float(arr.min()), float(arr.max())
        if hi > lo:
            arr = (arr - lo) / (hi - lo) * 255.0
    cell_w = w / cols
    cell_h = cell_w * 1.3333
    rows   = max(1, int(h / cell_h))
    lines  = []
    for row in range(rows):
        oy    = int(row * cell_h)
        parts = []
        for col in range(cols):
            ox       = int(col * cell_w)
            y1, y2   = oy, min(h, max(oy + 1, int(oy + cell_h)))
            x1, x2   = ox, min(w, max(ox + 1, int(ox + cell_w)))
            avg      = arr[y1:y2, x1:x2].mean(axis=(0, 1))
            lum      = float(avg.mean()) / 255.0
            if invert:
                lum = 1.0 - lum
            idx  = min(len(_PAL) - 1, int(lum * len(_PAL)))
            ch   = _PAL[idx]
            if color:
                r, g, b = (int(np.clip(v, 0, 255)) for v in avg)
                parts.append(f"\x1b[38;2;{r};{g};{b}m{ch}\x1b[0m")
            else:
                parts.append(ch)
        lines.append("".join(parts))
    return "\n".join(lines)

# ─── ANSI span parser ────────────────────────────────────────────────────────
_ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')

def _parse_spans(line: str):
    spans = []
    fg    = None
    pos   = 0
    for m in _ANSI_RE.finditer(line):
        if m.start() > pos:
            spans.append((fg, line[pos:m.start()]))
        raw   = m.group(1)
        codes = [int(c) for c in raw.split(';') if c.isdigit()] if raw else [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                fg = None
            elif c == 38 and i + 4 < len(codes) and codes[i + 1] == 2:
                fg = (codes[i + 2], codes[i + 3], codes[i + 4])
                i += 4
            i += 1
        pos = m.end()
    if pos < len(line):
        spans.append((fg, line[pos:]))
    return spans

# ─── font loading ────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
]

def _load_font(size: int):
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

# ─── ASCII text → PIL Image ───────────────────────────────────────────────────
_BG         = (8,  8, 12)
_DEFAULT_FG = (200, 200, 200)
_TITLE_FG   = (255, 215, 0)

# measure once at font_size=10
_FONT10     = _load_font(10)
_FONT14     = _load_font(14)
_probe      = Image.new("RGB", (200, 100))
_d          = ImageDraw.Draw(_probe)
_bb         = _d.textbbox((0, 0), "M",  font=_FONT10)
_CW         = _bb[2] - _bb[0]                              # char width
_bb2        = _d.textbbox((0, 0), "Mg", font=_FONT10)
_LH         = (_bb2[3] - _bb2[1]) + 2                      # line height

def ascii_to_image(text: str, title: str = "") -> Image.Image:
    title_h = 0
    if title:
        tb      = _d.textbbox((0, 0), title, font=_FONT14)
        title_h = (tb[3] - tb[1]) + 10

    lines       = text.splitlines()
    plain_lines = [_ANSI_RE.sub("", l) for l in lines]
    max_cols    = max((len(l) for l in plain_lines), default=1)

    W   = max_cols * _CW + 8
    H   = len(lines) * _LH + 8 + title_h
    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    if title:
        tb = draw.textbbox((0, 0), title, font=_FONT14)
        tw = tb[2] - tb[0]
        draw.text(((W - tw) // 2, 4), title, font=_FONT14, fill=_TITLE_FG)

    for i, line in enumerate(lines):
        y = title_h + 4 + i * _LH
        x = 4
        for fg, seg in _parse_spans(line):
            color = fg if fg is not None else _DEFAULT_FG
            for ch in seg:
                draw.text((x, y), ch, font=_FONT10, fill=color)
                x += _CW
    return img

# ─── animated GIF helpers ─────────────────────────────────────────────────────
def _palettise(img: Image.Image) -> Image.Image:
    return img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=0)

def save_gif(frames: list[Image.Image], path: Path, duration: int):
    W = max(f.width  for f in frames)
    H = max(f.height for f in frames)
    pal = []
    for f in frames:
        canvas = Image.new("RGB", (W, H), _BG)
        canvas.paste(f, (0, 0))
        pal.append(_palettise(canvas))
    pal[0].save(path, save_all=True, append_images=pal[1:],
                duration=duration, loop=0, optimize=False)

# ─── load source GIF frames ────────────────────────────────────────────────────
def load_gif_frames(path: str) -> tuple[list[np.ndarray], list[int]]:
    """Return (rgb_arrays, frame_delays_ms)."""
    src = Image.open(path)
    arrs, delays = [], []
    try:
        while True:
            delays.append(src.info.get("duration", 100))
            arrs.append(np.array(src.convert("RGB"), dtype=np.float32))
            src.seek(src.tell() + 1)
    except EOFError:
        pass
    return arrs, delays

# ─── still image comparisons ─────────────────────────────────────────────────
def make_still_examples(name: str, img_path: str, cols: int = 60):
    print(f"\n== {name} ==========================")
    src = Image.open(img_path).convert("RGB")
    # resize so width ~ 360 to keep processing fast
    max_w = 360
    if src.width > max_w:
        scale = max_w / src.width
        src   = src.resize((max_w, int(src.height * scale)), Image.LANCZOS)
    arr = np.array(src, dtype=np.float32)

    r_plain = Renderer(cols=cols, invert=False, autocontrast=True, use_color=False)
    r_color = Renderer(cols=cols, invert=False, autocontrast=True, use_color=True)

    variants = [
        ("brightness",       lambda a: brightness_render_arr(a.copy(), cols, invert=False, color=False), "Brightness only"),
        ("brightness_color", lambda a: brightness_render_arr(a.copy(), cols, invert=False, color=True),  "Brightness + Colour"),
        ("contour",          lambda a: r_plain.render_frame(a),                                          "Contour  (this tool)"),
        ("contour_color",    lambda a: r_color.render_frame(a),                                          "Contour + Colour"),
    ]

    gif_frames = []
    for suffix, render_fn, label in variants:
        png_path = EXAMPLES / f"{name}_{suffix}.png"
        txt_path = EXAMPLES / f"{name}_{suffix}.txt"
        print(f"  {label} ...", end=" ", flush=True)
        text = render_fn(arr)
        txt_path.write_text(text, encoding="utf-8")
        frame = ascii_to_image(text, title=label)
        frame.save(png_path)
        print(f"{frame.width}x{frame.height}")
        gif_frames.append(frame)

    gif_path = EXAMPLES / f"{name}_comparison.gif"
    print(f"  saving {gif_path.name} ...", end=" ", flush=True)
    save_gif(gif_frames, gif_path, duration=2500)
    print("done")

# ─── animated GIF examples ───────────────────────────────────────────────────
def make_gif_examples(name: str, gif_path: str, cols: int = 50,
                       invert: bool = False, autocontrast: bool = True):
    print(f"\n== {name} (animated) ==========================")
    frames_arr, delays = load_gif_frames(gif_path)
    print(f"  source: {len(frames_arr)} frames")
    avg_delay = int(sum(delays) / len(delays))

    r_plain = Renderer(cols=cols, invert=invert, autocontrast=autocontrast, use_color=False)
    r_color = Renderer(cols=cols, invert=invert, autocontrast=autocontrast, use_color=True)

    variants = [
        ("brightness",       lambda a: brightness_render_arr(a.copy(), cols, invert=invert, autocontrast=autocontrast, color=False), "Brightness only"),
        ("brightness_color", lambda a: brightness_render_arr(a.copy(), cols, invert=invert, autocontrast=autocontrast, color=True),  "Brightness + Colour"),
        ("contour",          lambda a: r_plain.render_frame(a),                                                                      "Contour  (this tool)"),
        ("contour_color",    lambda a: r_color.render_frame(a),                                                                      "Contour + Colour"),
    ]

    for suffix, render_fn, label in variants:
        out_path = EXAMPLES / f"{name}_{suffix}.gif"
        print(f"  {label} ...", end=" ", flush=True)
        png_frames = []
        for i, arr in enumerate(frames_arr):
            text  = render_fn(arr)
            frame = ascii_to_image(text, title=label)
            png_frames.append(frame)
            print(f"\r  {label} ... frame {i+1}/{len(frames_arr)}", end="", flush=True)
        print(f"\r  {label} ... saving {out_path.name}", end=" ", flush=True)
        save_gif(png_frames, out_path, duration=avg_delay)
        print(f"({out_path.stat().st_size//1024} KB)")

# ─── main ─────────────────────────────────────────────────────────────────────
def main():
    make_still_examples("apple", "examples/apple.jpg",  cols=60)
    make_still_examples("cat",   "examples/cat.jpg",    cols=60)
    make_gif_examples(  "globe", "examples/globe.gif",  cols=50)  # invert=False: space=dark, globe=bright
    print("\nAll assets generated.")

if __name__ == "__main__":
    main()
