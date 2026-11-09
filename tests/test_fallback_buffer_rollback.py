"""Regression: test production fallback buffer allocation using mocked Vulkan/VMA.

    python -I -B tests/test_fallback_buffer_rollback.py --cxx clang++ --sanitize

No GPU or game assets are used. A pre-fix copy of vk_draw.cpp fails these cases.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def function_block(src, signature):
    start = src.index(signature)
    at = src.index('{', start)
    depth = 1
    end = at + 1
    while depth:
        depth += (src[end] == '{') - (src[end] == '}')
        end += 1
    return src[start:end]


HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <unordered_map>
using VkBuffer = uint64_t;
using VmaAllocation = void*;
using VkBufferUsageFlags = uint32_t;
constexpr VkBuffer VK_NULL_HANDLE = 0;
constexpr VkBufferUsageFlags VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 1,
    VK_BUFFER_USAGE_TRANSFER_DST_BIT = 2, VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT = 4,
    VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT = 8;
struct FallbackBuffers {
    VkBuffer records = VK_NULL_HANDLE, payload = VK_NULL_HANDLE;
    VmaAllocation records_mem = nullptr, payload_mem = nullptr;
    uint64_t records_address = 0, payload_address = 0;
    bool ok = false, tried = false;
};
static std::unordered_map<VkBuffer,uint64_t> live;
static uint64_t next_handle;
static unsigned create_calls, fail_on_create, fail_address_for;
static bool create_buffer(uint64_t size, VkBufferUsageFlags, bool,
                          VkBuffer& buffer, VmaAllocation& allocation, void**) {
    if (++create_calls == fail_on_create) return false;
    buffer = ++next_handle;
    allocation = reinterpret_cast<VmaAllocation>(static_cast<uintptr_t>(buffer));
    assert(live.emplace(buffer,size).second);
    return true;
}
static uint64_t fallback_buffer_address(VkBuffer buffer) {
    return buffer == fail_address_for ? 0 : buffer * 4096;
}
static void destroy_buffer(VkBuffer buffer, VmaAllocation allocation) {
    assert(allocation == reinterpret_cast<VmaAllocation>(static_cast<uintptr_t>(buffer)));
    assert(live.erase(buffer) == 1);
}
static void logf(const char*, ...) {}
// FUNCTION_UNDER_TEST
static void case_run(unsigned fail_create, unsigned fail_address) {
    live.clear(); next_handle=0; create_calls=0;
    fail_on_create=fail_create; fail_address_for=fail_address;
    FallbackBuffers buffers;
    const bool ok=make_fallback_buffers(buffers, (64ull<<20)+32, 8ull<<20);
    assert(buffers.tried);
    if (fail_create || fail_address) {
        assert(!ok && !buffers.ok);
        assert(live.empty());
        assert(!buffers.records && !buffers.payload);
        assert(!buffers.records_mem && !buffers.payload_mem);
        assert(!buffers.records_address && !buffers.payload_address);
    } else {
        assert(ok && buffers.ok && live.size()==2);
        destroy_buffer(buffers.payload,buffers.payload_mem);
        destroy_buffer(buffers.records,buffers.records_mem);
        assert(live.empty());
    }
}
int main() {
    case_run(1,0); // initial allocation fails
    case_run(2,0); // payload allocation fails after records were allocated
    case_run(0,1); // records address unavailable
    case_run(0,2); // payload address unavailable (must not publish an invalid address)
    case_run(0,0); // successful initialization unchanged
    std::puts("PASS: five production-function buffer ownership/address cases");
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'gpu/vk/vk_draw.cpp')
    ap.add_argument('--cxx', default=None)
    ap.add_argument('--sanitize', action='store_true')
    args = ap.parse_args()
    compiler = args.cxx or shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        raise RuntimeError('C++20 compiler not available')
    source = args.source.read_text(encoding='utf-8')
    function = function_block(source, 'bool make_fallback_buffers(')
    fixture = HARNESS.replace('// FUNCTION_UNDER_TEST', function)
    with tempfile.TemporaryDirectory(prefix='fallback-buffer-rollback-') as folder:
        cpp = Path(folder) / 'test.cpp'
        exe = Path(folder) / 'test'
        cpp.write_text(fixture, encoding='utf-8')
        cmd = [compiler, '-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-Werror']
        if args.sanitize:
            cmd += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
        subprocess.run(cmd + [str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == '__main__':
    main()
