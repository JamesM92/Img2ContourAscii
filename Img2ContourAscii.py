#!/usr/bin/env python3
"""Backwards-compatible shim - the implementation lives in the
img2contourascii package now (so it can be installed via pip).

After `pip install img2contourascii` (or `pip install
git+https://github.com/JamesM92/Img2contourascii`), prefer the
console entry point `img2contourascii` over running this file
directly.
"""

from img2contourascii import main

if __name__ == "__main__":
    main()
