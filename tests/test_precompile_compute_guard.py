"""Extract and execute the real precompile handover guard with a paused compute worker.

No GPU, Vulkan SDK or game content needed.
Usage: python tests/test_precompile_compute_guard.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

FIXTURE = r'''
#include <atomic>
#include <chrono>
#include <cassert>
#include <memory>
#include <thread>
#include <barrier>
#include <vector>
#include <cstdio>
struct Run {
    std::atomic<size_t> next{0}, done{0}, compute_done{0};
};
bool may_handover(const std::shared_ptr<Run>& run, bool hand_over,
                  long long tail_ms, size_t total, const std::vector<int>& computes) {
    const auto now = std::chrono::steady_clock::now();
    const auto all_begun = now - std::chrono::milliseconds(5000);
    return hand_over && tail_ms > 0 && run->next.load() >= total && (GUARD);
}
int main() {
    for (int i = 0; i < 500; ++i) {
        const size_t total = 8;
        auto run = std::make_shared<Run>();
        const std::vector<int> computes{1, 2};
        std::barrier all_claimed(2), resume_worker(2);
        std::thread worker([&] {
            run->next.store(total, std::memory_order_release);
            all_claimed.arrive_and_wait();
            resume_worker.arrive_and_wait();
            run->compute_done.fetch_add(2, std::memory_order_release);
        });
        all_claimed.arrive_and_wait();
        assert(!may_handover(run, true, 3000, total, computes));
        resume_worker.arrive_and_wait();
        worker.join();
        assert(may_handover(run, true, 3000, total, computes));
        assert(!may_handover(run, false, 3000, total, computes));
        assert(!may_handover(run, true, 0, total, computes));
    }
    std::puts("PASS: 500 paused-worker handovers; compute must finish before game starts");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--source', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'gpu/vk/vk_draw.cpp')
    args = parser.parse_args()
    code = args.source.read_text(encoding='utf-8')
    needle = 'else if (now - all_begun >= std::chrono::milliseconds(tail_ms) &&'
    pos = code.index(needle)
    end = code.index(') {', pos)
    guard = code[pos + len('else if ('):end]
    if 'run->compute_done.load(std::memory_order_acquire) == computes.size()' not in guard:
        raise AssertionError('compute completion must be in handover gate')
    if code.count('run->compute_done.fetch_add(1, std::memory_order_release)') != 1:
        raise AssertionError('compute worker must publish completion')
    with tempfile.TemporaryDirectory() as d:
        cpp = Path(d) / 'precompile_guard.cpp'
        exe = Path(d) / 'precompile_guard'
        cpp.write_text(FIXTURE.replace('GUARD', guard), encoding='utf-8')
        subprocess.run([args.cxx, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-pthread', str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
