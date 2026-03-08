#!/usr/bin/env python3

import argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.spatial import KDTree
from scipy.ndimage import gaussian_filter
import sys
import os

ASCII_START = 32
ASCII_END = 126

CIRCLES = [
    (0.25, 0.2),
    (0.75, 0.25),
    (0.25, 0.5),
    (0.75, 0.55),
    (0.25, 0.8),
    (0.75, 0.85)
]
RADIUS = 0.3

CHAR_VECTORS_FILE = os.path.join(os.path.dirname(__file__), "char_vectors.npz")

# External points for sampling (10 points, left-to-right, top-to-bottom)
EXTERNAL_POINTS = [
    (0.0, 0.0), (0.5, 0.0), (1.0, 0.0),
    (0.0, 0.5), (0.5, 0.5), (1.0, 0.5),
    (0.0, 1.0), (0.5, 1.0), (1.0, 1.0),
    (0.5, 0.75)
]

# Which external points affect which character 6D index
AFFECTING_EXTERNAL_INDICES = [
    [0,1,2,4],
    [0,1,3,5],
    [2,4,6],
    [3,5,7],
    [4,6,8,9],
    [5,7,8,9],
]

# -------------------------------------------------
# Build sampling masks for 6D character vectors
# -------------------------------------------------
def build_circle_masks(cell_w, cell_h):
    masks = []
    for cx, cy in CIRCLES:
        px = cx * cell_w
        py = cy * cell_h
        r = RADIUS * cell_w
        coords = []
        for y in range(cell_h):
            for x in range(cell_w):
                dx = x - px
                dy = y - py
                if dx*dx + dy*dy < r*r:
                    coords.append((y,x))
        masks.append(coords)
    return masks

# -------------------------------------------------
# Character vectors (6D)
# -------------------------------------------------
def build_character_vectors(cell_w, cell_h, masks):
    if os.path.exists(CHAR_VECTORS_FILE):
        npz = np.load(CHAR_VECTORS_FILE)
        chars = npz['chars'].tolist()
        vectors = npz['vectors']
        print("Loaded character vectors from cache.")
        return chars, vectors

    print("Building character vectors...")
    font = ImageFont.load_default()
    chars = []
    vectors = []

    for code in range(ASCII_START, ASCII_END+1):
        char = chr(code)
        img = Image.new("L",(cell_w,cell_h),255)
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0,0),char,font=font)
        w = bbox[2]-bbox[0]
        h = bbox[3]-bbox[1]
        draw.text(
            ((cell_w-w)//2,(cell_h-h)//2),
            char,
            fill=0,
            font=font
        )
        arr = np.array(img)
        vec = []
        for mask in masks:
            values = [arr[y,x] for y,x in mask]
            dark = np.sum(np.array(values)<128)
            vec.append(dark/len(mask))
        chars.append(char)
        vectors.append(vec)

    vectors = np.array(vectors)
    col_max = np.max(vectors,axis=0)
    col_max[col_max==0] = 1.0
    vectors /= col_max

    np.savez(CHAR_VECTORS_FILE, chars=chars, vectors=vectors)
    print(f"Saved character vectors to {CHAR_VECTORS_FILE}")
    return chars, vectors

# -------------------------------------------------
# Sobel edges
# -------------------------------------------------
def sobel_edges(img):
    gx = np.array([[-1,0,1],[-2,0,2],[-1,0,1]])
    gy = np.array([[-1,-2,-1],[0,0,0],[1,2,1]])
    grad_x = convolve(img,gx)
    grad_y = convolve(img,gy)
    mag = np.sqrt(grad_x**2 + grad_y**2)
    mag /= np.max(mag) if np.max(mag)!=0 else 1
    return mag

def convolve(img,kernel):
    kh,kw = kernel.shape
    h,w = img.shape
    out = np.zeros_like(img)
    for y in range(1,h-1):
        for x in range(1,w-1):
            region = img[y-1:y+2,x-1:x+2]
            out[y,x] = np.sum(region*kernel)
    return out

# -------------------------------------------------
# Sample cell with 10D vector for character selection
# -------------------------------------------------
def sample_cell_10d(img, edges, x, y, cell_w, cell_h, edge_factor):
    ext_vals = []
    h,w = img.shape
    for px,py in EXTERNAL_POINTS:
        ix = min(int(x+px*cell_w), w-1)
        iy = min(int(y+py*cell_h), h-1)
        val = img[iy,ix]*(1+edges[iy,ix]*edge_factor)
        ext_vals.append(val/255.0)
    return np.array(ext_vals)

# -------------------------------------------------
# Sample cell for 6D vector (for character building)
# -------------------------------------------------
def sample_cell_6d(img, edges, x, y, cell_w, cell_h, masks, edge_factor):
    vec = []
    for mask in masks:
        vals = []
        for dy,dx in mask:
            iy = min(y+dy, img.shape[0]-1)
            ix = min(x+dx, img.shape[1]-1)
            vals.append(img[iy,ix]*(1+edges[iy,ix]*edge_factor))
        vec.append(np.mean(vals)/255.0)
    return np.clip(np.array(vec),0,1)

# -------------------------------------------------
# Contrast enhancement
# -------------------------------------------------
def contrast(vec, power):
    return vec**power

# -------------------------------------------------
# ASCII conversion
# -------------------------------------------------
def convert(image_path, cols, cell_w, cell_h, power, bg_spread, base_edge_factor, edge_smooth, use_color):
    masks = build_circle_masks(cell_w, cell_h)
    chars, vectors = build_character_vectors(cell_w, cell_h, masks)
    tree = KDTree(vectors)

    img_pil = Image.open(image_path).convert("RGB")
    img_arr = np.array(img_pil, dtype=np.float32)

    # grayscale for edge detection and sampling
    gray_arr = np.mean(img_arr, axis=2)
    gray_arr_min = np.min(gray_arr)
    gray_arr_max = np.max(gray_arr)
    gray_arr = (gray_arr - gray_arr_min)/(gray_arr_max - gray_arr_min + 1e-8) * 255

    edges = sobel_edges(gray_arr)
    edges = gaussian_filter(edges.astype(np.float32), sigma=edge_smooth)

    img_contrast = gray_arr.max() - gray_arr.min()
    edge_factor = base_edge_factor * (1 + 0.5 * (img_contrast/255.0))

    h,w = gray_arr.shape
    char_aspect = (cell_h/cell_w)*0.55
    rows = max(1, round((h/w)*cols*char_aspect))
    scale_x = w / cols
    scale_y = h / rows

    output = []
    for r in range(rows):
        line = ""
        for c in range(cols):
            x = int(c*scale_x)
            y = int(r*scale_y)
            cw = int(scale_x)
            ch = int(scale_y)
            if x+cw > w: cw = w-x
            if y+ch > h: ch = h-y

            vec_10d = sample_cell_10d(gray_arr, edges, x, y, cw, ch, edge_factor)
            vec_6d = np.zeros(6)
            # Map 10D vector to 6D using affecting indices
            for i, ext_idxs in enumerate(AFFECTING_EXTERNAL_INDICES):
                vec_6d[i] = np.mean([vec_10d[j] for j in ext_idxs])
            vec_6d = contrast(vec_6d, power)

            _,idx = tree.query(vec_6d)
            char = chars[idx % len(chars)]

            if use_color and char != " ":
                cell_color = np.mean(img_arr[y:y+ch, x:x+cw, :], axis=(0,1))
                cell_color_quant = (cell_color // 16)*16
                max_val = np.max(cell_color_quant)
                if max_val>0:
                    factor = 255.0/max_val
                    cell_color_quant = np.clip(cell_color_quant*factor,0,255)
                char = f"\033[38;2;{int(cell_color_quant[0])};{int(cell_color_quant[1])};{int(cell_color_quant[2])}m{char}\033[0m"

            line += char
        output.append(line)
        print(f"\rProcessing row {r+1}/{rows}", end="", flush=True)
    print("\r" + " "*30 + "\r", end="", flush=True)
    return "\n".join(output)

# -------------------------------------------------
# CLI
# -------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Edge-aware ASCII renderer with caching and optional color")
    parser.add_argument("image", help="input image")
    parser.add_argument("-o","--output", nargs="?", const="", help="output file (optional)")
    parser.add_argument("--cols", type=int, default=80, help="number of columns in output")
    parser.add_argument("--cellw", type=int, default=12, help="sampling cell width (pixels)")
    parser.add_argument("--cellh", type=int, default=18, help="sampling cell height (pixels)")
    parser.add_argument("--contrast", type=float, default=2.2, help="contrast power")
    parser.add_argument("--bgspread", type=int, default=0, help="background detection spread (0 disables spaces)")
    parser.add_argument("--edgefactor", type=float, default=0.7, help="base edge weighting factor")
    parser.add_argument("--edgesmooth", type=float, default=1.0, help="Gaussian smoothing sigma for edges")
    parser.add_argument("--color", action="store_true", help="enable 16-level RGB color")
    args = parser.parse_args()

    ascii_art = convert(
        args.image,
        args.cols,
        args.cellw,
        args.cellh,
        args.contrast,
        args.bgspread,
        args.edgefactor,
        args.edgesmooth,
        args.color
    )

    output_file = args.output
    if args.output is not None:
        # if -o is given without filename, generate .txt based on image
        if args.output == "":
            base_name = os.path.splitext(os.path.basename(args.image))[0]
            output_file = f"{base_name}.txt"

    if output_file:
        with open(output_file,"w") as f:
            f.write(ascii_art)
        print(f"Saved ASCII art to {output_file}")
    else:
        print(ascii_art)

if __name__ == "__main__":
    main()
