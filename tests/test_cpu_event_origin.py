"""Check that a GPU event signal clears stale CPU-event provenance.

Game-free source/logic check: python -I -B tests/test_cpu_event_origin.py --cxx g++
No Vulkan/device or real replay is exercised.
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    pos = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[start:pos]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()

    source = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    cpu = block(source, "void ev_cpu_apply()")
    gpu = block(source, "case NOP_SIGNAL_EVENT: {")
    resumed = block(source, "void resume_queue(")
    if "cpu_events.insert(e.first)" not in cpu:
        raise SystemExit("CPU event origin is not tracked")
    if "std::lock_guard lk(ev_cpu_mu)" not in gpu or "cpu_events.erase(e.gpu)" not in gpu:
        raise SystemExit("GPU event signals must clear CPU origin while holding ev_cpu_mu")
    if "cpu_events.count(wait_at(q.p).gpu)" not in resumed:
        raise SystemExit("resume_queue no longer uses the CPU event origin")

    fixture = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_set>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
std::mutex ev_cpu_mu;
std::unordered_set<uint64_t> cpu_events;
void cpu_signal(uint64_t gpu) { std::lock_guard lk(ev_cpu_mu); cpu_events.insert(gpu); }
void gpu_signal(uint64_t gpu) { std::lock_guard lk(ev_cpu_mu); cpu_events.erase(gpu); }
bool from_cpu(uint64_t gpu) { std::lock_guard lk(ev_cpu_mu); return cpu_events.count(gpu) != 0; }
int main() {
    constexpr uint64_t a = 0x1000, b = 0x2000;
    cpu_signal(a); CHECK(from_cpu(a));
    cpu_signal(b); gpu_signal(a);
    CHECK(!from_cpu(a)); CHECK(from_cpu(b));
    cpu_signal(a); CHECK(from_cpu(a));
    gpu_signal(a); CHECK(!from_cpu(a));
    std::puts("PASS: GPU signals replace earlier CPU event provenance");
}
'''
    with tempfile.TemporaryDirectory(prefix="cpu-event-origin-") as directory:
        cpp = Path(directory) / "test.cpp"
        exe = Path(directory) / "test"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
