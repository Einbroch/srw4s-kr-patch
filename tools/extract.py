#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract ISO files (Mode2 Form1 user data) from a raw MODE2/2352 PS1 track."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isotool import Disc

def main():
    img, listing, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    skip = re.compile(r'\.(STR|DA);', re.I)
    disc = Disc(img)
    for line in open(listing, encoding='utf-8'):
        if not line.startswith('FILE\t'):
            continue
        _, lba, size, full = line.rstrip('\n').split('\t')
        if skip.search(full):
            continue
        lba, size = int(lba), int(size)
        rel = full.lstrip('/').split(';')[0]
        dst = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(disc.read(lba, size))
        print(f"{rel}\t{lba}\t{size}")

if __name__ == '__main__':
    main()
