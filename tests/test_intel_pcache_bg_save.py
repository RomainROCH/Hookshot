"""Game-free policy check for Intel background Vulkan pipeline-cache saves.

The policy is kept in a pure C++ header so the test compiles the actual production decision,
not an independently rewritten copy. Report and workaround credit: @ploob-boop, Hookshot #999.
"""
import argparse
import os
import pathlib
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = ROOT / "gpu/vk/vk_pipeline_cache_save_policy.h"
DRAW = ROOT / "gpu/vk/vk_draw.cpp"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cxx", required=True)
    args = p.parse_args()
    src = DRAW.read_text(encoding="utf-8")
    fn = src.split("void pipeline_cache_save(bool force) {", 1)[1].split("auto save =", 1)[0]
    assert '#include "vk_pipeline_cache_save_policy.h"' in src
    assert "PipelineCachePolicy::DeferIntelBackgroundSave(" in fn
    assert fn.index("PipelineCachePolicy::DeferIntelBackgroundSave(") < fn.index("pcache_built_since_save = 0;")
    code = r'''#include "gpu/vk/vk_pipeline_cache_save_policy.h"
#include <initializer_list>
#include <cassert>
#include <cstdint>
int main() {
    int cases = 0;
    for (bool force: {false, true})
        for (std::uint32_t vendor: {0x8086u, 0x1002u, 0x10deu, 0u})
            for (bool opt_in: {false, true}) {
                const bool expected = !force && vendor == 0x8086u && !opt_in;
                assert(mkwvk::PipelineCachePolicy::DeferIntelBackgroundSave(force, vendor, opt_in) == expected);
                ++cases;
            }
    assert(cases == 16);
}
'''
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "case.cpp"
        exe = pathlib.Path(td) / ("case.exe" if os.name == "nt" else "case")
        path.write_text(code, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I", str(ROOT), str(path), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("Intel background pipeline-cache policy: 16/16 combinations passed")


if __name__ == "__main__":
    main()
