"""Compile Hookshot's actual early WriteTexels copy-size helper against synthetic strides.

No game input or Vulkan runtime is needed. The renderer interprets zero row/image
pitches as tightly packed; an early copy must allocate that complete span.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'host' / 'rx_backend.c').read_text(encoding='utf-8')
start = source.index('static int early_texel_copy_size(')
brace = source.index('{', start)
level = 0
end = None
for index in range(brace, len(source)):
    if source[index] == '{':
        level += 1
    elif source[index] == '}':
        level -= 1
        if level == 0:
            end = index + 1
            break
if end is None:
    raise AssertionError('unterminated copy-size helper')
helper = source[start:end]
test = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <limits.h>
#include <assert.h>
''' + helper + r'''
int main(void) {
    size_t n = 0;
    assert(early_texel_copy_size(4,4,1,1,1,1,0,0,&n) && n==16);
    assert(early_texel_copy_size(4,4,1,1,1,1,8,0,&n) && n==28);
    assert(early_texel_copy_size(4,4,2,1,1,1,0,0,&n) && n==32);
    assert(early_texel_copy_size(4,4,2,1,1,1,0,64,&n) && n==80);
    assert(early_texel_copy_size(8,8,1,4,4,16,0,0,&n) && n==64);
    assert(early_texel_copy_size(8,8,2,4,4,16,64,0,&n) && n==224);
    assert(early_texel_copy_size(1,1,0,1,1,1,0,0,&n) && n==1);
    assert(!early_texel_copy_size(UINT64_MAX,1,1,1,1,8,0,0,&n));
    assert(!early_texel_copy_size(1,3,1,1,1,1,UINT64_MAX,0,&n));
    assert(!early_texel_copy_size(1,1,3,1,1,1,0,UINT64_MAX,&n));
    assert(!early_texel_copy_size(0,1,1,1,1,1,0,0,&n));
    puts("PASS: 11 implicit/explicit pitch and overflow scenarios");
}
'''
compilers = [cc for cc in ('gcc','clang') if shutil.which(cc)]
if not compilers:
    raise RuntimeError('requires gcc or clang')
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    src = path / 'texels.c'
    src.write_text(test, encoding='utf-8')
    for cc in compilers:
        exe = path / ('texels_' + cc)
        subprocess.run([cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-sanitize-recover=all',
                        str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
print(f'PASS: extracted production helper under {", ".join(compilers)}')
