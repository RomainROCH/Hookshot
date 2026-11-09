#!/usr/bin/env python3
"""Compile the real OoT render-target pool policy against synthetic wide display sizes."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def function_from_source(source):
    token = 'uint64_t hos_rt_pool_size(uint64_t game) {'
    start = source.find(token)
    if start < 0:
        raise ValueError('hos_rt_pool_size missing')
    opening = source.find('{', start)
    depth = 0
    for i in range(opening, len(source)):
        depth += (source[i] == '{') - (source[i] == '}')
        if not depth:
            return source[start:i + 1]
    raise ValueError('unterminated hos_rt_pool_size')


def harness(fn):
    return r'''#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
volatile uint64_t hos_wide_out;
static int output_mode;
uint32_t hos_output_size(int height) {
    return output_mode == 2 ? (height ? 2160 : 3840) : (height ? 1440 : 2560);
}
void hos_log(const char *fmt, ...) { (void)fmt; }
''' + fn + r'''
static unsigned failures;
static void check(const char *name, uint32_t width, uint32_t height,
                  int mode, uint64_t expected) {
    output_mode = mode;
    hos_wide_out = width ? ((uint64_t)height << 32 | width) : 0;
    uint64_t actual = hos_rt_pool_size(0x13100000ULL);
    printf("%s: %llu (want %llu)\n", name,
           (unsigned long long)actual, (unsigned long long)expected);
    if (actual != expected) ++failures;
}
static uint64_t scaled(uint32_t width, uint32_t height) {
    const uint64_t pixels = (uint64_t)width * height;
    const uint64_t game = 0x13100000ULL;
    const uint64_t base = 2560ULL * 1440;
    return pixels > base ? (game * pixels / base + 0xfffffULL) & ~0xfffffULL : game;
}
int main(void) {
    if (getenv("HOS_RT_POOL_MB")) {
        check("explicit override", 5120, 1440, 0, 512ULL << 20);
    } else {
        check("16:9 default", 0, 0, 0, 0x13100000ULL);
        check("21:9 3440x1440", 3440, 1440, 0, scaled(3440, 1440));
        check("32:9 5120x1440", 5120, 1440, 0, scaled(5120, 1440));
        check("4K 16:9", 0, 0, 2, scaled(3840, 2160));
        check("4K 32:9", 7680, 2160, 2, scaled(7680, 2160));
    }
    if (failures) fprintf(stderr, "FAIL: %u pool size mismatches\n", failures);
    return failures != 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'host/nn_applet.c')
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='oot-wide-pool-') as temp:
        fixture = Path(temp) / 'fixture.c'
        fixture.write_text(harness(function_from_source(source)), encoding='utf-8')
        exe = Path(temp) / 'test_rt_pool'
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                        '-fsanitize=undefined', '-fno-sanitize-recover=undefined',
                        str(fixture), '-o', str(exe)], check=True)
        environment = os.environ.copy()
        environment.pop('HOS_RT_POOL_MB', None)
        subprocess.run([str(exe)], env=environment, check=True)
        environment['HOS_RT_POOL_MB'] = '512'
        subprocess.run([str(exe)], env=environment, check=True)
    print('PASS: production pool calculation follows the widened frame; override remains explicit')


if __name__ == '__main__':
    main()
