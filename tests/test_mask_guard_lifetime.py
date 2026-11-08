"""A shadow-mask stabilization guard must not be destroyed before the draw.

The code previously assigned a temporary aggregate with a destructor to an existing
guard. The temporary destructor ran immediately after the assignment, before the draw;
the real guard's destructor ran a second time at draw exit.
Run: python -I -B tests/test_mask_guard_lifetime.py
"""
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
start = source.index("struct MaskGuard {")
end = source.index("if (!record_progs()", start)
body = source[start:end]
if "mask_guard = {" in body:
    raise SystemExit("temporary MaskGuard assignment runs mask_stabilize before drawing")
if "~MaskGuard() { if (cmd) mask_stabilize(" not in body:
    raise SystemExit("the exit guard no longer invokes mask_stabilize")
for field in ("tex", "level", "layer", "w", "cmd"):
    if f"mask_guard.{field} =" not in body:
        raise SystemExit(f"missing direct guard-field assignment: {field}")
if not (body.index("mask_guard.cmd = cmd") > body.index("mask_guard.w = mw")):
    raise SystemExit("activate the guard only after its other fields are set")
print("shadow-mask guard: one deferred stabilization; no temporary destructor")
