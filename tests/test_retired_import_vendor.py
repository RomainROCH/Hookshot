#!/usr/bin/env python3
"""Game-free policy regression: retained imports on Windows are vendor-specific.

The policy block is extracted from the production vk_memory.cpp and compiled
with a stub for the chosen Vulkan device. Each case starts a fresh process
because the function caches the result in a static local.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
start = source.index("void retired_imports_give_back()")
start = source.index("#ifdef _WIN32", start)
end = source.index("#endif", start) + len("#endif")
policy = source[start:end]
assert 'RX_VK_KEEP_RETIRED' in policy and "static const bool keep" in policy

fixture = """
#include <cstdlib>
#include <cstdint>
struct Device { struct Props { uint32_t vendorID = 0; } props; } dev;
bool retained() {
""" + policy + """
    return keep;
}
int main(int argc, char** argv) {
    if (argc != 2) return 99;
    dev.props.vendorID = (uint32_t)std::strtoul(argv[1], nullptr, 0);
    return retained() ? 0 : 1;
}
"""

cases = [
    ("win", 0x10DE, None, False),  # NVIDIA: release after timeline-safe retirement
    ("win", 0x1002, None, True),   # AMD: preserve existing conservative default
    ("win", 0x8086, None, True),   # Intel: preserve existing conservative default
    ("win", 0x10DE, "1", True),   # manual override remains available
    ("win", 0x10DE, "0", False),
    ("win", 0x1002, "0", False),
    ("linux", 0x10DE, None, False),  # Linux defaults unchanged
    ("linux", 0x1002, None, False),
    ("linux", 0x1002, "1", True),
]
compilers = [name for name in ("g++", "clang++") if shutil.which(name)]
if not compilers:
    print("SKIP: no C++ compiler for vendor-policy fixture")
else:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        file = root / "policy.cpp"
        file.write_text(fixture)
        for compiler in compilers:
            for platform in ("win", "linux"):
                exe = root / "policy"
                cmd = [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(file), "-o", str(exe)]
                if platform == "win":
                    cmd.insert(1, "-D_WIN32")
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                for test_platform, vendor, override, expected in cases:
                    if test_platform != platform:
                        continue
                    env = os.environ.copy()
                    env.pop("RX_VK_KEEP_RETIRED", None)
                    if override is not None:
                        env["RX_VK_KEEP_RETIRED"] = override
                    proc = subprocess.run(
                        [str(exe), hex(vendor)], env=env, capture_output=True, text=True
                    )
                    assert proc.returncode in (0, 1), (compiler, platform, vendor, proc.stderr)
                    assert (proc.returncode == 0) == expected, (
                        compiler, platform, hex(vendor), override, expected, proc.returncode
                    )
            print(f"{compiler}: {len(cases)} policy cases passed")
