#!/usr/bin/env python3
"""
Live video / webcam ASCII renderer built on top of Img2ContourAscii.

Dependencies (install only what you need):
  pip install imageio                  # GIF and basic video support
  pip install imageio[ffmpeg]          # MP4, AVI, MKV, etc.
  pip install picamera2                # Raspberry Pi Camera Module

Usage:
  python ContourAscii_Video.py video.mp4
  python ContourAscii_Video.py animation.gif --loop
  python ContourAscii_Video.py --webcam
  python ContourAscii_Video.py --picam
"""

import argparse
import shutil
import sys
import time

import numpy as np

from Img2ContourAscii import CELL_ASPECT, Renderer

# ANSI helpers
_CLEAR = "\033[2J\033[H"   # clear screen + move to top-left (first frame)
_HOME  = "\033[H"          # move to top-left without clearing (subsequent frames)


_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"


def _render_loop(renderer: Renderer, frames, fps: float, loop: bool):
    """
    Core display loop shared by all sources.
    `frames` is any iterable of (H, W, 3) uint8 numpy arrays.
    """
    frame_time = 1.0 / fps if fps > 0 else 0.0
    first      = True

    sys.stdout.write(_HIDE_CURSOR)
    sys.stdout.flush()

    while True:
        for frame in frames:
            t0     = time.monotonic()
            output = renderer.render_frame(frame)

            sys.stdout.write((_CLEAR if first else _HOME) + output)
            sys.stdout.flush()
            first = False

            elapsed = time.monotonic() - t0
            wait    = frame_time - elapsed
            if wait > 0:
                time.sleep(wait)

        if not loop:
            break


# ─────────────────────────────────────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────────────────────────────────────

def _frames_from_file(path: str):
    """Yield frames from a video file or animated GIF using imageio."""
    try:
        import imageio.v3 as iio
    except ImportError:
        sys.exit(
            "imageio is required for video files.\n"
            "  pip install imageio\n"
            "  pip install imageio[ffmpeg]   # for MP4/AVI/MKV"
        )

    reader   = iio.imopen(path, "r")
    metadata = reader.metadata()
    fps      = metadata.get("fps") or metadata.get("FPS") or 24.0

    def gen():
        try:
            for frame in reader:
                if frame.ndim == 2:              # greyscale → RGB
                    frame = np.stack([frame] * 3, axis=2)
                elif frame.shape[2] == 4:        # RGBA → RGB
                    frame = frame[:, :, :3]
                yield frame.astype(np.uint8)
        finally:
            reader.close()

    return gen(), float(fps)


def _frames_from_webcam(device: int = 0):
    """Yield frames from a USB webcam using imageio."""
    try:
        import imageio.v3 as iio
    except ImportError:
        sys.exit("imageio is required for webcam input.\n  pip install imageio")

    # imageio uses '<video0>' style device strings on Linux
    source = f"<video{device}>"

    def gen():
        for frame in iio.imopen(source, "r"):
            yield frame[:, :, :3].astype(np.uint8)

    return gen(), 30.0


def _frames_from_picam(width: int = 640, height: int = 480, fps: float = 30.0):
    """Yield frames from a Raspberry Pi Camera Module using picamera2."""
    try:
        from picamera2 import Picamera2
    except ImportError:
        sys.exit(
            "picamera2 is required for Pi Camera input.\n"
            "  pip install picamera2\n"
            "  (or: sudo apt install python3-picamera2)"
        )

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"}
    ))
    cam.start()

    def gen():
        try:
            while True:
                yield cam.capture_array("main").astype(np.uint8)
        finally:
            cam.stop()

    return gen(), fps


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Live video / webcam ASCII renderer (uses Img2ContourAscii)",
    )

    # ── Source ──────────────────────────────────────────────────────────────
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("file",    nargs="?",            help="video file or animated GIF")
    source.add_argument("--webcam", action="store_true", help="USB webcam (device 0)")
    source.add_argument("--picam",  action="store_true", help="Raspberry Pi Camera Module")

    parser.add_argument("--device", type=int, default=0,
                        help="webcam device index (default: 0)")
    parser.add_argument("--fps",    type=float, default=None,
                        help="override source FPS (default: read from file / 30 for live)")
    parser.add_argument("--loop",   action="store_true",
                        help="loop video/GIF continuously")
    parser.add_argument("--cam-width",  type=int, default=640,
                        help="Pi Camera / webcam capture width  (default: 640)")
    parser.add_argument("--cam-height", type=int, default=480,
                        help="Pi Camera / webcam capture height (default: 480)")

    # ── Renderer ─────────────────────────────────────────────────────────────
    parser.add_argument("--cols",   type=int,   default=None,
                        help="output columns (default: terminal width)")
    parser.add_argument("--global-crunch",      dest="global_exp",
                        type=float, default=2.2)
    parser.add_argument("--directional-crunch", dest="directional_exp",
                        type=float, default=2.8)
    parser.add_argument("--color",        action="store_true")
    parser.add_argument("--invert",       action="store_true")
    parser.add_argument("--autocontrast", action="store_true")
    parser.add_argument("--char-ratio",   dest="char_aspect",
                        type=float, default=CELL_ASPECT)
    parser.add_argument("--exclude",      default="")

    args = parser.parse_args()

    renderer = Renderer(
        cols            = args.cols,
        global_exp      = args.global_exp,
        directional_exp = args.directional_exp,
        use_color       = args.color,
        invert          = args.invert,
        char_aspect     = args.char_aspect,
        exclude         = args.exclude,
        autocontrast    = args.autocontrast,
    )

    if args.picam:
        frames, src_fps = _frames_from_picam(
            args.cam_width, args.cam_height,
            args.fps or 30.0,
        )
        loop = True   # live feed always loops
    elif args.webcam:
        frames, src_fps = _frames_from_webcam(args.device)
        loop = True
    else:
        frames, src_fps = _frames_from_file(args.file)
        loop = args.loop

    fps = args.fps if args.fps is not None else src_fps

    try:
        _render_loop(renderer, frames, fps, loop)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
