"""Guard the Vulkan scaler's lifetime and the frame pacer's job queue ownership.

    python -I -B tests/test_framegen_sync_guards.py

This is a source-level regression check without game files or a GPU. It does not
substitute for a driver test when the scale size changes during play.
"""
from pathlib import Path
import re

source = (Path(__file__).resolve().parents[1] / "gpu/vk/vk_framegen.cpp").read_text(encoding="utf-8")
start = source.index("VkImage framegen_scale(")
end = source.index("VkImage framegen_made_image(", start)
scaler = source[start:end]
for name in ("cropped", "scaled"):
    sites = list(re.finditer(r"drop_img\\(scale\\." + name + r"\\);", scaler))
    assert sites, name + ": resize site is missing"
    before = scaler[:sites[0].start()]
    assert re.search(
        r"std::lock_guard\\s+\\w+\\(dev\\.present_mu\\);\\s*"
        r"queue_flush_locked\\(\\);\\s*vkDeviceWaitIdle\\(dev\\.device\\);[^\\n]*\\s*\\}",
        before[-480:], re.S), name + ": image may be freed while a submit still uses it"

start = source.index("void display_main()")
end = source.index("} // namespace", start)
display = source[start:end]
assert not re.search(r"\\|\\|\\s*!\\s*fg\\.jobs\\.empty\\(\\)", display), "unsynchronized pacer read"
assert re.search(
    r"std::lock_guard\\s+\\w+\\(fg\\.mu\\);\\s*"
    r"\\w+\\s*=\\s*!\\s*fg\\.jobs\\.empty\\(\\);", display
), "pacer backlog should be sampled under fg.mu"
print("PASS: queue completion precedes scaler image destruction; frame-pacer backlog uses fg.mu")
