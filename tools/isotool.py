#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MODE2/2352 raw PS1 track reader + ISO9660 walker (read-only survey tool)."""
import sys, struct, os

RAW = 2352
HDR = 24          # 12 sync + 4 header + 8 subheader (Mode2 Form1)
USER = 2048

class Disc:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        self.sectors = self.size // RAW

    def sector_raw(self, lba):
        self.f.seek(lba * RAW)
        return self.f.read(RAW)

    def sector(self, lba):
        s = self.sector_raw(lba)
        return s[HDR:HDR+USER]

    def read(self, lba, nbytes):
        out = bytearray()
        while len(out) < nbytes:
            out += self.sector(lba)
            lba += 1
        return bytes(out[:nbytes])

    def subheader(self, lba):
        return self.sector_raw(lba)[16:24]

def both_u32(b, off):
    return struct.unpack_from('<I', b, off)[0]

def parse_dirrec(b, off):
    ln = b[off]
    if ln == 0:
        return None, off
    lba = both_u32(b, off+2)
    size = both_u32(b, off+10)
    flags = b[off+25]
    namelen = b[off+32]
    name = b[off+33:off+33+namelen]
    return dict(lba=lba, size=size, flags=flags, name=name, reclen=ln), off+ln

def walk(disc, lba, size, path, out, depth=0):
    data = disc.read(lba, size)
    off = 0
    while off < len(data):
        if data[off] == 0:
            # advance to next logical sector boundary
            off = (off // USER + 1) * USER
            if off >= len(data):
                break
            continue
        rec, off = parse_dirrec(data, off)
        if rec is None:
            break
        nm = rec['name']
        if nm in (b'\x00', b'\x01'):
            continue
        name = nm.decode('ascii', 'replace')
        full = path + '/' + name
        if rec['flags'] & 0x02:
            out.append((full + '/', rec['lba'], rec['size'], 'DIR'))
            walk(disc, rec['lba'], rec['size'], full, out, depth+1)
        else:
            out.append((full, rec['lba'], rec['size'], 'FILE'))

def main():
    disc = Disc(sys.argv[1])
    print(f"# image sectors={disc.sectors} bytes={disc.size}")
    pvd = disc.sector(16)
    print("# PVD id:", pvd[1:6], "sysid:", pvd[8:40].decode('ascii','replace').strip(),
          "volid:", pvd[40:72].decode('ascii','replace').strip())
    volsize = struct.unpack_from('<I', pvd, 80)[0]
    print("# volume space size (sectors):", volsize)
    root = pvd[156:156+34]
    rlba = struct.unpack_from('<I', root, 2)[0]
    rsize = struct.unpack_from('<I', root, 10)[0]
    print(f"# root dir lba={rlba} size={rsize}")
    out = []
    walk(disc, rlba, rsize, '', out)
    print(f"# entries={len(out)}")
    for full, lba, size, kind in out:
        print(f"{kind}\t{lba}\t{size}\t{full}")

if __name__ == '__main__':
    main()
