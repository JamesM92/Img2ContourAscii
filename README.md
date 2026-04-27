# Img2ContourAscii

A command-line image-to-ASCII converter that picks characters based on **shape**, not just brightness. Edges and contours are followed accurately because each character is matched against the actual visual structure of the image region it occupies.

---

## Credit

This is a Python port of an idea and algorithm created entirely by **Alex Harri**. The approach is documented in detail in his blog post:

> [ASCII characters are not pixels: a deep dive into ASCII rendering](https://alexharri.com/blog/ascii-rendering)

The original TypeScript implementation is part of his website's open source repository:

> [github.com/alexharri/website](https://github.com/alexharri/website)

Alex was not involved in this project. All credit for the core algorithm belongs to him.

---

## AI Generated

This implementation was written by **Claude (Anthropic)** based on Alex Harri's blog post and reference TypeScript source. No code was written by hand.

---

## How it works

### The problem with brightness-only rendering

Traditional ASCII renderers assign a character to each grid cell based on average brightness alone — effectively treating characters as square pixels. This produces blurry edges because the *shape* of the character is ignored.

### Shape vectors

Each ASCII character occupies a cell differently. `T` is dense at the top, `L` is dense along the left and bottom, `/` is dense diagonally. Alex Harri's approach captures this by defining **six sampling circles** arranged across each cell:

```
  (●)   (●)    ← top row    (staggered for better coverage)
  (●)   (●)    ← middle row
  (●)   (●)    ← bottom row
```

For each character in the alphabet, the fraction of ink inside each circle is measured and stored as a **6-dimensional shape vector**. These vectors are pre-computed and stored in `default.json` (taken directly from Alex's repository).

### Matching image cells to characters

When rendering an image, the same six circles are sampled at each grid cell to produce a 6D **sampling vector** for that region. A KD-tree nearest-neighbour search finds the character whose shape vector is closest — the character that best *fits* the image region's structure.

### Contrast enhancement

Two contrast passes sharpen boundaries between regions:

1. **Directional crunch** — Ten additional circles sample just *outside* the current cell's boundary. If a neighbouring region is brighter, the corresponding internal component is pushed down, exaggerating the boundary shape and preventing staircase artefacts.

2. **Global crunch** — The sampling vector is normalised by its own maximum, raised to a power, then rescaled. This increases contrast between the lighter and darker components of the vector without affecting uniform regions.

### Colour (extra)

The `--color` flag adds ANSI 24-bit colour codes to each character using the average colour of the corresponding image region. This is an addition beyond Alex's original design.

---

## Usage

```
python Img2ContourAscii.py <image> [options]
```

| Option | Default | Description |
|---|---|---|
| `--cols N` | `80` | Output width in characters |
| `--global-crunch F` | `2.2` | Global contrast exponent |
| `--directional-crunch F` | `2.8` | Directional contrast exponent |
| `--color` | off | Enable ANSI 24-bit colour |
| `-o [FILE]` | stdout | Write to file; omit filename to auto-generate |

### Examples

```bash
# Basic render
python Img2ContourAscii.py photo.jpg

# Wider output saved to file
python Img2ContourAscii.py photo.jpg --cols 120 -o

# Colour output
python Img2ContourAscii.py photo.jpg --color

# Higher contrast
python Img2ContourAscii.py photo.jpg --global-crunch 3.0 --directional-crunch 3.5
```

### Dependencies

```
pip install pillow numpy scipy
```
