#!/usr/bin/env python3
"""Report board text that does not fit its box, or that lands on top of one.

Two distinct failures, two checks:

  1. OVERFLOW  draw.py never re-wraps a box label: it splits on the \n the author
     wrote and clamps the box to BOX_W_MAX. A longer line spills over the border.
     Only text bound to a box is measured — the title, subtitle, lane labels and
     legend size themselves and are never clamped.

  2. COLLISION  an arrow's label sits at the arrow's midpoint and is not checked
     against anything, so a long hop drops its text onto a box in between.

    python3 overflow-check.py <board>.excalidraw

Silence means the board is clean. Exit 1 if anything overflows or collides.
"""
import json
import sys
from pathlib import Path

FS, CHAR_W, BOX_W_MAX, PAD = 16.0, 0.56, 340, 32
LIMIT = BOX_W_MAX - PAD
BUDGET = int(LIMIT / (FS * CHAR_W))
MARGIN = 4  # px of slop before an overlap is worth reporting


def role(e):
    return (e.get("customData") or {}).get("role")


def rect(e):
    return (e["x"], e["y"], e["x"] + e.get("width", 0), e["y"] + e.get("height", 0))


def hits(a, b, margin=MARGIN):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 - margin and ax1 > bx0 + margin and ay0 < by1 - margin and ay1 > by0 + margin


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <board>.excalidraw", file=sys.stderr)
        return 2
    scene = json.loads(Path(sys.argv[1]).read_text())
    els = [e for e in scene.get("elements", []) if not e.get("isDeleted")]
    idx = {e["id"]: e for e in els}
    boxes = [e for e in els if role(e) == "box"]

    bad = []
    for e in els:
        if e.get("type") != "text":
            continue
        holder = idx.get(e.get("containerId") or "")
        if holder is not None and role(holder) == "box":
            for line in e.get("text", "").split("\n"):
                need = len(line) * FS * CHAR_W
                if need > LIMIT:
                    bad.append(f"OVERFLOWS by {need - LIMIT:.0f}px "
                               f"({len(line)} chars, budget {BUDGET}): {line!r}")
            continue
        if holder is not None and holder.get("type") == "arrow":
            for box in boxes:
                if hits(rect(e), rect(box)):
                    label = " / ".join(e.get("text", "").split("\n"))
                    on = idx.get(box.get("boundElements") and next(
                        (b["id"] for b in box["boundElements"] if b.get("type") == "text"), ""), {})
                    onto = " / ".join(on.get("text", "?").split("\n"))[:40]
                    bad.append(f"COLLIDES: arrow label {label!r} sits on box {onto!r}")
                    break

    for line in bad:
        print(line)
    if bad:
        print(f"\n{len(bad)} problem(s). Break a long line with \\n, split the box in two, "
              f"or shorten the arrow hop.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
