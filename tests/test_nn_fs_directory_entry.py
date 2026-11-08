#!/usr/bin/env python3
"""Source-level ABI regression check for Hookshot's nn::fs::ReadDirectory.

This intentionally does not claim to execute the guest game or compile Hookshot.
"""
import argparse
import ctypes
from pathlib import Path
import re

class DirectoryEntry(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 0x301),
        ("padding1", ctypes.c_uint8 * 3),
        ("type", ctypes.c_uint8),
        ("padding2", ctypes.c_uint8 * 3),
        ("size", ctypes.c_int64),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "host/nn_fs.c")
    args = ap.parse_args()
    source = args.source.read_text(encoding="utf-8")
    block = source.split("HLE(_ZN2nn2fs13ReadDirectory", 1)[1].split("\nHLE(", 1)[0]
    assigns = re.findall(r"\*\(uint8_t\s*\*\)GP\(e\s*\+\s*(0x[0-9a-fA-F]+)\)\s*=\s*(isdir|x->is_dir)\s*\?\s*0\s*:\s*1;", block)
    assert len(assigns) == 2, f"expected both native and synthetic-entry paths; found {assigns!r}"
    assert {kind for _offset, kind in assigns} == {"isdir", "x->is_dir"}, assigns
    assert DirectoryEntry.type.offset == 0x304
    assert DirectoryEntry.size.offset == 0x308
    assert ctypes.sizeof(DirectoryEntry) == 0x310
    for offset, kind in assigns:
        for is_dir in (False, True):
            b = bytearray(ctypes.sizeof(DirectoryEntry))
            b[int(offset, 16)] = 0 if is_dir else 1
            assert b[DirectoryEntry.type.offset] == (0 if is_dir else 1), (kind, offset, is_dir)
            assert b[0x302] == 0, (kind, offset)
    print("PASS: both ReadDirectory paths write the ABI type byte at 0x304")

if __name__ == "__main__":
    main()
