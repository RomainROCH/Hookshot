#!/usr/bin/env python3
"""Game-free regression for the capture eviction sweep in vk_memory.cpp.

Compiles the actual production sweep with a small std::map fixture. A pinned
old capture must not retain unrelated newer captures already past the GPU
timeline; still-in-flight buffers must never be freed.
"""
import pathlib
import shutil
import subprocess
import tempfile

source = (pathlib.Path(__file__).resolve().parents[1] / "gpu/vk/vk_memory.cpp").read_text()
start = source.index("bool take_capture(")
a = source.index("    for (auto it = cap_bufs.begin();", start)
b = source.index("    uint32_t g = 0;", a)
policy = source[a:b]
assert "cap_buf_retire(dead)" in policy

fixture = r"""
#include <cstdint>
#include <algorithm>
#include <iterator>
#include <map>
#include <cstdio>
struct CapBuf { uint64_t value, last_use, size; };
std::map<uint32_t, CapBuf> cap_bufs;
uint64_t cap_bytes = 0;
constexpr size_t kKeep = 2;
constexpr uint64_t kCapBytesMax = 200;
void cap_buf_retire(std::map<uint32_t, CapBuf>::iterator it) {
    cap_bytes -= it->second.size;
    cap_bufs.erase(it);
}
void sweep(uint64_t completed) {
""" + policy + r"""
}
int main() {
    // Oldest capture is reused by a future submission; three later captures are complete.
    cap_bufs = {{1, {1, 100, 100}}, {2, {2, 0, 100}},
                {3, {3, 0, 100}}, {4, {4, 0, 100}}};
    cap_bytes = 400;
    sweep(10);
    if (cap_bufs.size() != 2 || !cap_bufs.count(1) || cap_bytes != 200) return 1;
    // Nothing is retired when everything is still in flight.
    cap_bufs = {{1, {1, 100, 100}}, {2, {11, 0, 100}},
                {3, {12, 0, 100}}, {4, {13, 0, 100}}};
    cap_bytes = 400;
    sweep(10);
    if (cap_bufs.size() != 4 || cap_bytes != 400) return 2;
    // A byte budget can be exceeded even when entry count does not exceed kKeep.
    cap_bufs = {{1, {1, 100, 150}}, {2, {2, 0, 150}}};
    cap_bytes = 300;
    sweep(10);
    if (cap_bufs.size() != 1 || !cap_bufs.count(1) || cap_bytes != 150) return 3;
    // Once the formerly pinned entry completes, future reclamation is possible.
    cap_bufs.emplace(5, CapBuf{5, 0, 150});
    cap_bytes = 300;
    sweep(150);
    if (cap_bufs.size() != 1 || cap_bytes != 150) return 4;
    return 0;
}
"""
compilers = [tool for tool in ("g++", "clang++") if shutil.which(tool)]
if not compilers:
    print("SKIP: no C++ compiler for capture retirement fixture")
else:
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp)
        file = path / "capture.cpp"
        file.write_text(fixture)
        for compiler in compilers:
            exe = path / "capture"
            subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                            str(file), "-o", str(exe)], check=True, capture_output=True)
            result = subprocess.run([str(exe)], capture_output=True)
            assert result.returncode == 0, (compiler, result.returncode, result.stderr)
            print(f"{compiler}: capture retirement regression passed")
