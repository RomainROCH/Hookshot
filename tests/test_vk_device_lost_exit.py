"""Game-free regression for the fatal VK_ERROR_DEVICE_LOST path in vk_replay.cpp.

Usage: python -I -B tests/test_vk_device_lost_exit.py [--cxx g++] [--source path]
The helper is extracted from the production file and compiled with stub Vulkan types.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def extract_function(source: str, name: str) -> str:
    marker = f'void {name}('
    at = source.index(marker)
    opening = source.index('{', at)
    depth = 1
    end = opening + 1
    while depth and end < len(source):
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    assert depth == 0, 'Unclosed function body'
    return source[at:end]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cxx', default='g++')
    p.add_argument('--source', type=Path,
                   default=Path(__file__).resolve().parents[1] / 'gpu/vk/vk_replay.cpp')
    args = p.parse_args()
    source = args.source.read_text(encoding='utf-8')
    helper = extract_function(source, 'fatal_on_device_lost')
    assert 'checkpoints_report();' in helper and 'replay_fatal(where);' in helper
    assert source.count('fatal_on_device_lost(') >= 12, 'Lost a submission or presentation guard'
    assert 'if (res == VK_ERROR_DEVICE_LOST) checkpoints_report();' not in source

    fixture = '''#include <cstdio>
#include <cstdlib>
enum VkResult { VK_SUCCESS = 0, VK_ERROR_DEVICE_LOST = -4 };
void checkpoints_report() { std::puts("checkpoint"); std::fflush(stdout); }
[[noreturn]] void replay_fatal(const char* where) {
    std::printf("fatal:%s\\n", where); std::fflush(stdout); std::_Exit(3);
}
''' + helper + '''
int main(int argc, char**) {
    fatal_on_device_lost(argc > 1 ? VK_ERROR_DEVICE_LOST : VK_SUCCESS, "synthetic submit");
    std::puts("continued");
}
'''
    with tempfile.TemporaryDirectory() as d:
        exe = Path(d) / 'test_vk_device_lost_exit'
        subprocess.run([args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-omit-frame-pointer', '-x', 'c++',
                        '-o', str(exe), '-'], input=fixture, text=True,
                       capture_output=True, check=True)
        normal = subprocess.run([str(exe)], capture_output=True, text=True)
        lost = subprocess.run([str(exe), 'lost'], capture_output=True, text=True)
    assert normal.returncode == 0 and normal.stdout == 'continued\n', normal
    assert lost.returncode == 3 and 'checkpoint\nfatal:synthetic submit\n' == lost.stdout, lost
    assert 'continued' not in lost.stdout
    print(f'PASS {args.cxx}: success continues; VK_ERROR_DEVICE_LOST records checkpoints, exits 3')


if __name__ == '__main__':
    main()
