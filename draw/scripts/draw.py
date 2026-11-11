#!/usr/bin/env python3
"""draw.py — the agent's eyes and hands on a shared Excalidraw board.

The board is an ordinary `.excalidraw` file. The user draws on it in a browser (see
draw_server.py, the VS Code Excalidraw extension, or excalidraw.com → Open); the agent reads
it and draws back into the SAME file. Nothing else is the source of truth.

    draw.py new      <spec.json> <board.excalidraw> [--repo DIR] [--link-prefix URL]
    draw.py describe <board>                         # the whole board, in words, with #handles
    draw.py diff     <board>                         # what changed since the agent last looked
    draw.py ack      <board>                         # "seen" — the next diff starts from here
    draw.py add box   <board> --label L [--at path:line] [--kind K] [--near #h] [--lane #h] [--step N]
    draw.py add arrow <board> --from #h --to #h [--label L] [--when COND] [--kind K]
    draw.py add note  <board> --text T --near #h [--as answer|question|warning]
    draw.py set      <board> #h [--kind K] [--label L] [--at path:line] [--step N] [--text T]
    draw.py rm       <board> #h [#h ...]
    draw.py phase    <board> --built 1 2 3           # those build steps shipped: boxes go grey, badges green; plan the next slice here
    draw.py check    <board> [--repo DIR]           # every agent box has a path:line that exists
    draw.py review   <plan-board> --repo DIR --base REF --head REF [--system BOARD] [--files F ...]
                                                     # did the change touch what the plan said? recoloured copy + verdict
    draw.py serve    <board> [server options]       # the viewer (delegates to draw_server.py)

Handles: `#key` = an agent box's key (from the spec, or slugified label); `#u:xxxxxx` = an
element the user drew (printed by describe); or any unique substring of a box's text.

Standard library only. Every agent write bumps `version` on the elements it touches, so a
viewer that merges by version picks the change up without losing the user's unsaved strokes.
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("DRAW_STATE_DIR") or os.path.expanduser("~/.local/state/workflow/draw"))
SOURCE = "spiral/draw"

# ── vocabulary ───────────────────────────────────────────────────────────────────────────
# One colour means one thing, on every board. Boxes: background + stroke. Arrows: stroke only.
KINDS = {
    "unchanged": ("#e9ecef", "#868e96", "exists today, not touched"),
    "new":       ("#b2f2bb", "#2f9e44", "the plan adds it"),
    "touched":   ("#ffec99", "#f08c00", "exists, the plan changes it"),
    "removed":   ("#f8f9fa", "#adb5bd", "the plan deletes it"),
    "failing":   ("#ffc9c9", "#e03131", "the bug's path — actual differs from expected here"),
    "external":  ("#a5d8ff", "#1971c2", "outside this repo: a service, a person, another process"),
}
EDGE_KINDS = {
    "unchanged": ("#495057", 2, "solid"),
    "new":       ("#2f9e44", 3, "solid"),
    "touched":   ("#f08c00", 3, "solid"),
    "removed":   ("#adb5bd", 2, "dashed"),
    "failing":   ("#e03131", 3, "solid"),
    "trace":     ("#1971c2", 3, "solid"),   # the one worked example travels along these
    # Flow type. Box colour says what the plan did; ARROW colour says what moves.
    "data":      ("#0c8599", 3, "solid"),   # something is carried: a value, an event, a payload
    "logic":     ("#7048e8", 2, "dashed"),  # control only: a call, a branch, a decision
}
NOTE_KINDS = {
    "answer":   ("#fff9db", "#f08c00"),
    "question": ("#e7f5ff", "#1971c2"),
    "warning":  ("#ffe3e3", "#e03131"),
}
# ── system-level vocabulary: the basic building blocks of systems design ──────────────────
# A system box says WHAT KIND of running or stored thing it is, because that decides what it
# may get wrong: a store must survive a restart, a cache may be stale, a queue may deliver late.
ROLES = {
    "person":   "a human who uses or operates the system",
    "client":   "a UI or CLI a person drives; holds no data of record",
    "service":  "a process that answers requests; keeps no state unless it owns a store",
    "worker":   "a process that takes jobs off a queue or a schedule; nobody waits on it",
    "store":    "durable state (database, files, bucket); survives a restart; one owner writes it",
    "queue":    "a buffer or log between a sender and a worker; decouples their timing",
    "cache":    "a copy kept for speed; may be stale and can be rebuilt from its source",
    "external": "a system this repo neither owns nor deploys",
}
ROLE_SHAPE = {"person": "actor", "store": "store", "queue": "store", "cache": "store"}
STATEFUL_ROLES = ("store", "queue", "cache")
# How an arrow talks decides who waits, and who fails together.
VIAS = {
    "call":    ("solid", "sync call: the caller waits; a slow or down callee makes the caller slow or down"),
    "message": ("dotted", "async message: sent and not waited for; the receiver runs on its own time"),
}
# What a lane's edge separates, weakest to strongest. A crossing costs what its strongest side costs.
BOUNDARIES = {
    "process": "separate memory: crossing means serialising the data",
    "network": "a network hop: latency, timeouts and partial failure",
    "trust":   "different permissions: input crossing it must be checked",
}
AGENT_ID = re.compile(r"^(n|t|e|et|note|notet|notea|nt|legend|legendt|legendl|legendlt|rlegend|rlegendt|lane|lanet|badge|badget|rbadge|rbadget):|^(title|subtitle)$")
# Files a review never asks the board to account for: nobody designs a lockfile, a generated
# artefact is the output of a box rather than a box, and repo plumbing (what git ignores, what
# CI runs) is not the system the board describes. Never dropped silently — the verdict line and
# the report both name how many were set aside, and --no-default-ignores turns it off.
#
# Deliberately NOT here: PR and issue templates, CODEOWNERS, and anything under .github/ that is
# not CI. Those decide how the team works and a change to one is a real finding.
DEFAULT_IGNORES = (
    # repo plumbing
    ".gitignore", "*/.gitignore", ".gitattributes", "*/.gitattributes",
    ".github/workflows/*", ".github/actions/*", ".github/dependabot.yml",
    ".gitlab-ci.yml", ".circleci/*", ".travis.yml", "azure-pipelines.yml", "Jenkinsfile",
    ".buildkite/*", ".drone.yml", "appveyor.yml", ".woodpecker.yml", "*/.gitlab-ci.yml",
    # lockfiles
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "Cargo.lock",
    "poetry.lock", "uv.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock", "go.sum",
    "*/package-lock.json", "*/yarn.lock", "*/pnpm-lock.yaml", "*/Cargo.lock", "*/go.sum",
    "vendor/*", "*/vendor/*", "node_modules/*", "*/node_modules/*",
    "*/__snapshots__/*", "*.snap", "*.generated.*", "*.pb.go", "*_pb2.py", "*_pb2.pyi",
    "*.min.js", "*.min.css", "dist/*", "build/*", "target/*",
)

SHAPES = ("box", "store", "actor")
MAX_BOXES = 12

FONT = 1          # Virgil — the hand-drawn face every Excalidraw build ships
FS = 16           # box text
FS_SMALL = 13     # path line, lane label, legend
LH = 1.25
CHAR_W = 0.56     # average glyph width as a fraction of font size — Virgil is wide

BOX_W_MIN, BOX_W_MAX, BOX_H_MIN = 200, 340, 64
SLOT_GAP, ROW_GAP, BAND_GAP, PAD = 40, 130, 90, 28
NOTE_W = 240


# ── small helpers ─────────────────────────────────────────────────────────────────────────
def h32(s: str) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF


def now_ms() -> int:
    return int(time.time() * 1000)


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "x"


def short_at(at: str) -> str:
    """`src/handler/conversation/tool_blocks.rs:103` → `conversation/tool_blocks.rs:103`."""
    if not at:
        return ""
    path, _, line = at.partition(":")
    parts = path.split("/")
    p = "/".join(parts[-2:]) if len(parts) > 2 else path
    return f"[{p}:{line}]" if line else f"[{p}]"


def wrap(text: str, width_chars: int) -> list[str]:
    out = []
    for para in text.split("\n"):
        line = ""
        for w in para.split(" "):
            if line and len(line) + 1 + len(w) > width_chars:
                out.append(line)
                line = w
            else:
                line = f"{line} {w}" if line else w
        out.append(line)
    return out


def measure(lines: list[str], fs: float) -> tuple[float, float]:
    w = max((len(l) for l in lines), default=1) * fs * CHAR_W
    return w, len(lines) * fs * LH


def load(path: Path) -> dict:
    if not path.exists():
        return {"type": "excalidraw", "version": 2, "source": SOURCE, "elements": [],
                "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None}, "files": {}}
    with open(path, encoding="utf-8") as fh:
        scene = json.load(fh)
    scene.setdefault("elements", [])
    scene.setdefault("appState", {"viewBackgroundColor": "#ffffff", "gridSize": None})
    scene.setdefault("files", {})
    return scene


LEGEND_IDS = ("legend:", "legendt:", "legendl:", "legendlt:")


def rebuild_legend(els: list[dict]) -> list[dict]:
    """Redraw the legend from the kinds actually on the board RIGHT NOW.

    Called from `save`, so every write refreshes it. A legend that still names a
    colour nobody uses — or omits one the agent just drew — is worse than none:
    the reader trusts it and misreads the board.
    """
    kept = [e for e in els if not str(e.get("id", "")).startswith(LEGEND_IDS)]
    boxes = scene_boxes(kept)
    if not boxes:
        return kept
    used = {agent_data(b).get("kind", "unchanged") for b in boxes}
    used_edges = {
        agent_data(e).get("kind", "unchanged")
        for e in live(kept)
        if e.get("type") == "arrow"
        and agent_data(e).get("role") == "arrow"
        and not str(e.get("id", "")).startswith("notea:")
    }
    bottom = max(b["y"] + b["height"] for b in boxes)
    for n in note_boxes(kept):
        bottom = max(bottom, n["y"] + n["height"])
    lx, ly = 40, bottom + 40
    out = []
    for kind in KINDS:
        if kind not in used:
            continue
        bg, stroke, meaning = KINDS[kind]
        r = base(f"legend:{kind}", "rectangle", lx, ly, 28, 20, backgroundColor=bg, strokeColor=stroke,
                 roundness={"type": 3}, roughness=0, strokeWidth=1)
        r["customData"] = {"by": "agent", "role": "legend"}
        t = mk_text(f"legendt:{kind}", f"{kind} \u2014 {meaning}", lx + 36, ly,
                    len(meaning) * FS_SMALL * CHAR_W + 120, FS_SMALL * LH,
                    fs=FS_SMALL, align="left", valign="top", color="#495057")
        out += [r, t]
        ly += 28
    for kind in ("data", "logic", "new", "failing", "trace", "removed", "touched"):
        if kind in used_edges and kind not in used:
            stroke, width, style = EDGE_KINDS[kind]
            ln = base(f"legendl:{kind}", "line", lx, ly + 10, 28, 0, strokeColor=stroke, strokeWidth=width,
                      strokeStyle=style, points=[[0, 0], [28, 0]], roughness=0)
            ln["customData"] = {"by": "agent", "role": "legend"}
            meaning = {"trace": "the worked example travels here", "new": "arrow the plan adds",
                       "failing": "the failing hop", "removed": "arrow the plan removes",
                       "touched": "arrow the plan changes",
                       "data": "DATA \u2014 something is carried along this arrow",
                       "logic": "LOGIC \u2014 control only, nothing is carried"}[kind]
            t = mk_text(f"legendlt:{kind}", meaning, lx + 36, ly, len(meaning) * FS_SMALL * CHAR_W + 40,
                        FS_SMALL * LH, fs=FS_SMALL, align="left", valign="top", color="#495057")
            out += [ln, t]
            ly += 28
    # system vocabulary: only what this board uses, each with what it may get wrong
    arrows = [agent_data(e) for e in live(kept) if e.get("type") == "arrow" and agent_data(e).get("role") == "arrow"]
    for via, (style, meaning) in VIAS.items():
        if not any(d.get("via") == via for d in arrows):
            continue
        ln = base(f"legendl:via-{via}", "line", lx, ly + 10, 28, 0, strokeColor="#495057", strokeWidth=2,
                  strokeStyle=style, points=[[0, 0], [28, 0]], roughness=0)
        ln["customData"] = {"by": "agent", "role": "legend"}
        t = mk_text(f"legendlt:via-{via}", meaning, lx + 36, ly, len(meaning) * FS_SMALL * CHAR_W + 40,
                    FS_SMALL * LH, fs=FS_SMALL, align="left", valign="top", color="#495057")
        out += [ln, t]
        ly += 28
    roles = {agent_data(b).get("part") for b in boxes} - {None, ""}
    bnds = {agent_data(e).get("boundary") for e in live(kept) if agent_data(e).get("role") == "lane"} - {None, ""}
    rows = [f"{r} — {ROLES[r]}" for r in ROLES if r in roles]
    rows += [f"{b} boundary — {BOUNDARIES[b]}" for b in BOUNDARIES if b in bnds]
    for i, text in enumerate(rows):
        t = mk_text(f"legendt:sys-{i}", text, lx, ly, len(text) * FS_SMALL * CHAR_W + 40, FS_SMALL * LH,
                    fs=FS_SMALL, align="left", valign="top", color="#495057")
        t["customData"] = {"by": "agent", "role": "legend"}
        out.append(t)
        ly += 22
    return kept + out


def save(path: Path, scene: dict) -> None:
    scene["elements"] = rebuild_legend(scene.get("elements") or [])
    scene["type"] = "excalidraw"
    scene["version"] = 2
    scene.setdefault("source", SOURCE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".draw-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(scene, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def live(els: list[dict]) -> list[dict]:
    return [e for e in els if not e.get("isDeleted")]


def by_id(els: list[dict]) -> dict:
    return {e["id"]: e for e in els}


def is_box(e: dict) -> bool:
    return e.get("type") in ("rectangle", "ellipse", "diamond") and not e.get("isDeleted")


def agent_data(e: dict) -> dict:
    d = e.get("customData") or {}
    return d if d.get("by") == "agent" else {}


def bound_text(e: dict, idx: dict) -> str:
    for b in e.get("boundElements") or []:
        if b.get("type") == "text" and b.get("id") in idx and not idx[b["id"]].get("isDeleted"):
            return idx[b["id"]].get("text", "")
    # a text element whose containerId points here but the box lost the back-reference
    for t in idx.values():
        if t.get("type") == "text" and t.get("containerId") == e["id"] and not t.get("isDeleted"):
            return t.get("text", "")
    return ""


def bbox(e: dict) -> tuple[float, float, float, float]:
    if e.get("type") in ("arrow", "line", "freedraw"):
        xs = [e["x"] + p[0] for p in e.get("points") or [[0, 0]]]
        ys = [e["y"] + p[1] for p in e.get("points") or [[0, 0]]]
        return min(xs), min(ys), max(xs), max(ys)
    return e["x"], e["y"], e["x"] + e.get("width", 0), e["y"] + e.get("height", 0)


def center(e: dict) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox(e)
    return (x0 + x1) / 2, (y0 + y1) / 2


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_box(pt, boxes: list[dict], exclude=()) -> dict | None:
    best, bd = None, 1e18
    for b in boxes:
        if b["id"] in exclude:
            continue
        d = dist(pt, center(b))
        if d < bd:
            best, bd = b, d
    return best


def overlaps(r, els: list[dict], margin=12) -> bool:
    x0, y0, x1, y1 = r
    for e in els:
        if e.get("type") in ("arrow", "line", "freedraw", "text") and not e.get("containerId"):
            continue
        if agent_data(e).get("role") in ("lane", "legend"):
            continue  # a lane is a region, not an obstacle; the legend sits below everything
        a0, b0, a1, b1 = bbox(e)
        if x0 < a1 + margin and x1 > a0 - margin and y0 < b1 + margin and y1 > b0 - margin:
            return True
    return False


# ── element constructors ──────────────────────────────────────────────────────────────────
def base(eid: str, etype: str, x, y, w, h, **kw) -> dict:
    e = {
        "id": eid, "type": etype, "x": float(x), "y": float(y), "width": float(w), "height": float(h),
        "angle": 0, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
        "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
        "seed": h32(eid + ":seed"), "version": 1, "versionNonce": h32(eid + ":v1"),
        "isDeleted": False, "boundElements": [], "updated": now_ms(), "link": None, "locked": False,
    }
    e.update(kw)
    return e


def mk_text(eid: str, text: str, x, y, w, h, fs=FS, container=None, align="center",
            valign="middle", color="#1e1e1e", font=FONT) -> dict:
    return base(eid, "text", x, y, w, h, strokeColor=color, text=text, originalText=text,
                fontSize=fs, fontFamily=font, textAlign=align, verticalAlign=valign,
                containerId=container, lineHeight=LH, autoResize=True)


def touch(e: dict) -> None:
    """Mark an element as changed by the agent so a version-merging viewer takes it."""
    e["version"] = int(e.get("version", 1)) + 1
    e["versionNonce"] = h32(f"{e['id']}:v{e['version']}:{now_ms()}")
    e["updated"] = now_ms()


def bind(container: dict, text: dict) -> None:
    text["containerId"] = container["id"]
    be = [b for b in container.get("boundElements") or [] if b.get("type") != "text"]
    be.append({"id": text["id"], "type": "text"})
    container["boundElements"] = be


def fit_text_in(container: dict, text: dict) -> None:
    """Centre a bound text inside its container from our own measurement."""
    lines = text["text"].split("\n")
    w, h = measure(lines, text["fontSize"])
    w = min(w, container["width"] - 16)
    text["width"], text["height"] = w, h
    text["x"] = container["x"] + (container["width"] - w) / 2
    text["y"] = container["y"] + (container["height"] - h) / 2


def style_box(e: dict, kind: str, shape: str) -> None:
    bg, stroke, _ = KINDS[kind]
    e["backgroundColor"], e["strokeColor"] = bg, stroke
    e["strokeStyle"] = "dashed" if kind == "removed" else "solid"
    e["fillStyle"] = "hachure" if shape == "store" else "solid"
    e["roundness"] = None if shape == "store" else {"type": 3}
    e["opacity"] = 60 if kind == "removed" else 100


def box_label(label: str, at: str, tech: str = "", role: str = "") -> str:
    lines = [label]
    tl = " · ".join(x for x in (role, tech) if x)
    if tl:
        lines.append(f"[{tl}]")
    if at:
        lines.append(short_at(at))
    return "\n".join(lines)


def mk_box(key: str, label: str, at: str = "", kind: str = "unchanged", shape: str = "box",
           x=0, y=0, w=BOX_W_MIN, h=BOX_H_MIN, step=None, lane=None, link=None, tech: str = "",
           role: str = "") -> tuple[dict, dict]:
    etype = {"box": "rectangle", "store": "rectangle", "actor": "ellipse"}[shape]
    e = base(f"n:{key}", etype, x, y, w, h, link=link)
    style_box(e, kind, shape)
    e["customData"] = {"by": "agent", "role": "box", "key": key, "label": label, "at": at,
                       "kind": kind, "shape": shape, "step": step, "lane": lane, "tech": tech, "part": role}
    t = mk_text(f"t:{key}", box_label(label, at, tech, role), x, y, w, h, container=e["id"])
    bind(e, t)
    fit_text_in(e, t)
    return e, t


def boundary_point(e: dict, toward) -> tuple[float, float]:
    """Where the segment centre→toward leaves e's box (ellipse treated as its box)."""
    cx, cy = center(e)
    x0, y0, x1, y1 = bbox(e)
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    tx = hw / abs(dx) if dx else 1e18
    ty = hh / abs(dy) if dy else 1e18
    t = min(tx, ty)
    if e.get("type") == "ellipse":  # scale to the ellipse instead of the corner
        ang = math.atan2(dy / hh if hh else 0, dx / hw if hw else 0)
        return cx + hw * math.cos(ang), cy + hh * math.sin(ang)
    return cx + dx * t, cy + dy * t


def route_arrow(arrow: dict, a: dict, b: dict, offset: float = 0.0) -> None:
    ca, cb = center(a), center(b)
    p0 = boundary_point(a, cb)
    p1 = boundary_point(b, ca)
    if offset:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy) or 1
        ox, oy = -dy / n * offset, dx / n * offset
        p0, p1 = (p0[0] + ox, p0[1] + oy), (p1[0] + ox, p1[1] + oy)
    arrow["x"], arrow["y"] = p0
    arrow["points"] = [[0, 0], [p1[0] - p0[0], p1[1] - p0[1]]]
    arrow["width"], arrow["height"] = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])
    arrow["startBinding"] = {"elementId": a["id"], "focus": 0, "gap": 1}
    arrow["endBinding"] = {"elementId": b["id"], "focus": 0, "gap": 1}


def attach_arrow(a: dict, b: dict, arrow: dict) -> None:
    for e in (a, b):
        be = [x for x in e.get("boundElements") or [] if x.get("id") != arrow["id"]]
        be.append({"id": arrow["id"], "type": "arrow"})
        e["boundElements"] = be


def mk_arrow(eid: str, a: dict, b: dict, label: str = "", kind: str = "unchanged",
             dashed: bool = False, head: str = "arrow", offset: float = 0.0,
             data: dict | None = None) -> list[dict]:
    stroke, width, style = EDGE_KINDS.get(kind, EDGE_KINDS["unchanged"])
    if (data or {}).get("via") == "message":
        style = VIAS["message"][0]
    e = base(eid, "arrow", 0, 0, 0, 0, strokeColor=stroke, strokeWidth=width,
             strokeStyle="dashed" if dashed else style, roundness={"type": 2},
             startArrowhead=None, endArrowhead=head, lastCommittedPoint=None, elbowed=False)
    e["customData"] = {"by": "agent", "role": "arrow", "kind": kind, "label": label, **(data or {})}
    route_arrow(e, a, b, offset)
    attach_arrow(a, b, e)
    out = [e]
    if label:
        lines = wrap(label, 24)
        w, h = measure(lines, FS_SMALL)
        mx = e["x"] + e["points"][1][0] / 2
        my = e["y"] + e["points"][1][1] / 2
        t = mk_text(eid.replace("e:", "et:", 1), "\n".join(lines), mx - w / 2, my - h / 2, w, h,
                    fs=FS_SMALL, container=e["id"], color=stroke)
        bind(e, t)
        out.append(t)
    return out


def mk_note(eid: str, text: str, x, y, kind: str = "answer", near_id: str | None = None) -> list[dict]:
    bg, stroke = NOTE_KINDS[kind]
    lines = wrap(text, 30)
    w, h = measure(lines, FS_SMALL)
    w, h = max(NOTE_W, w + 24), h + 24
    r = base(eid, "rectangle", x, y, w, h, backgroundColor=bg, strokeColor=stroke,
             strokeWidth=1, roundness={"type": 3})
    r["customData"] = {"by": "agent", "role": "note", "kind": kind, "text": text, "near": near_id}
    t = mk_text(eid.replace("note:", "notet:", 1), "\n".join(lines), x + 12, y + 12, w - 24, h - 24,
                fs=FS_SMALL, container=r["id"], align="left", valign="top", color="#343a40")
    bind(r, t)
    return [r, t]


# ── the first board: spec → scene ─────────────────────────────────────────────────────────
def check_spec(spec: dict, allow_big=False) -> list[str]:
    errs = []
    nodes = spec.get("nodes") or []
    ids = [n.get("id") for n in nodes]
    if len(nodes) > MAX_BOXES and not allow_big:
        errs.append(f"{len(nodes)} boxes; a board a reader can hold has ≤{MAX_BOXES}. Split it: one "
                    f"overview board, and a `detail` board per box that needs opening up (--allow-big to override)")
    if len(set(ids)) != len(ids):
        errs.append("duplicate node ids")
    lanes = {l["id"] for l in spec.get("lanes") or []}
    for n in nodes:
        if not n.get("id") or not n.get("label"):
            errs.append(f"node without id/label: {n}")
        if n.get("kind", "unchanged") not in KINDS:
            errs.append(f"node {n.get('id')}: unknown kind {n.get('kind')!r} (one of {', '.join(KINDS)})")
        if n.get("shape", "box") not in SHAPES:
            errs.append(f"node {n.get('id')}: unknown shape {n.get('shape')!r} (one of {', '.join(SHAPES)})")
        if n.get("lane") and n["lane"] not in lanes:
            errs.append(f"node {n.get('id')}: lane {n['lane']!r} not declared")
        if n.get("role") and n["role"] not in ROLES:
            errs.append(f"node {n.get('id')}: unknown role {n['role']!r} (one of {', '.join(ROLES)})")
        if n.get("covers") is not None and not (isinstance(n["covers"], list) and all(isinstance(c, str) for c in n["covers"])):
            errs.append(f"node {n.get('id')}: covers must be a list of path globs")
        if not n.get("at") and n.get("kind", "unchanged") not in ("external", "new") and n.get("shape") != "actor":
            errs.append(f"node {n.get('id')}: no `at` (path:line). A box the reader cannot open is a concept, not a thing")
    for e in spec.get("edges") or []:
        if e.get("from") not in ids or e.get("to") not in ids:
            errs.append(f"edge {e.get('from')}→{e.get('to')} references an unknown node")
        if e.get("kind", "unchanged") not in EDGE_KINDS:
            errs.append(f"edge {e.get('from')}→{e.get('to')}: unknown kind {e.get('kind')!r}")
        if e.get("via") and e["via"] not in VIAS:
            errs.append(f"edge {e.get('from')}→{e.get('to')}: unknown via {e['via']!r} (one of {', '.join(VIAS)})")
    for l in spec.get("lanes") or []:
        if l.get("boundary") and l["boundary"] not in BOUNDARIES:
            errs.append(f"lane {l.get('id')}: unknown boundary {l['boundary']!r} (one of {', '.join(BOUNDARIES)})")
    if spec.get("mode") == "bug" and not spec.get("example"):
        errs.append("mode bug needs `example`: the one concrete input followed through the boxes")
    return errs


def system_gaps(spec: dict) -> list[str]:
    """What a system board leaves unsaid. Warnings, not failures: an old board still renders."""
    if spec.get("level") != "system":
        return []
    out = []
    for n in spec.get("nodes") or []:
        if not n.get("role"):
            out.append(f"node {n['id']}: no role — say what kind of part it is ({', '.join(ROLES)})")
    for e in spec.get("edges") or []:
        if not e.get("via"):
            out.append(f"edge {e['from']}→{e['to']}: no via — does the sender wait (call) or not (message)?")
    for l in spec.get("lanes") or []:
        if not l.get("boundary"):
            out.append(f"lane {l['id']}: no boundary — what separates it ({', '.join(BOUNDARIES)})?")
    return out


def verify_at(at: str, repo: Path) -> str:
    """'' when path:line exists under repo, else the reason."""
    path, _, line = at.partition(":")
    p = repo / path
    if not p.exists():
        return f"{path} does not exist under {repo}"
    if line:
        try:
            n = int(line.split("-")[0])
        except ValueError:
            return f"{at}: line is not a number"
        try:
            total = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        except OSError as ex:
            return f"{path}: {ex}"
        if n > total:
            return f"{at}: file has {total} lines"
    return ""


def layout(spec: dict) -> dict:
    """-> {node_id: (x, y)}, plus '__rows__', '__bands__' geometry. Layers = rows (flow top→bottom),
    lanes = column bands; nodes without a lane share a trailing band."""
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    ids = [n["id"] for n in nodes]
    order = {nid: i for i, nid in enumerate(ids)}
    succ = {i: [] for i in ids}
    pred = {i: [] for i in ids}
    for e in edges:
        if e["from"] == e["to"]:
            continue
        succ[e["from"]].append(e["to"])
        pred[e["to"]].append(e["from"])
    # drop back edges (cycles) for layering
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for v in succ[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2
    for u in ids:
        if u not in state:
            dfs(u)
    layer = {}
    pinned = {n["id"]: n["row"] for n in nodes if isinstance(n.get("row"), int)}

    def depth(u):
        if u in layer:
            return layer[u]
        ps = [p for p in pred[u] if (p, u) not in back]
        layer[u] = max(pinned.get(u, 0), 0 if not ps else 1 + max(depth(p) for p in ps))
        return layer[u]
    for u in ids:
        depth(u)
    nrows = max(layer.values(), default=0) + 1

    lanes = [l["id"] for l in spec.get("lanes") or []]
    lane_of = {n["id"]: (n.get("lane") if n.get("lane") in lanes else None) for n in nodes}
    bands = lanes + ([None] if any(v is None for v in lane_of.values()) else [])

    # uniform box size from the longest label
    lab = {}
    for n in nodes:
        lab[n["id"]] = box_label(n["label"], n.get("at", ""), n.get("tech", ""), n.get("role", "")).split("\n")
    w_needed = max((measure(l, FS)[0] for l in lab.values()), default=BOX_W_MIN) + 32
    W = max(BOX_W_MIN, min(BOX_W_MAX, w_needed))
    H = max(BOX_H_MIN, max((len(l) for l in lab.values()), default=1) * FS * LH + 28)

    # slot assignment per (band, row), ordered by barycentre of predecessors then input order
    cells = {(b, r): [] for b in bands for r in range(nrows)}
    for n in nodes:
        cells[(lane_of[n["id"]], layer[n["id"]])].append(n["id"])
    slot = {}
    for r in range(nrows):
        for b in bands:
            c = cells[(b, r)]

            def key(nid):
                ps = [slot[p][1] for p in pred[nid] if p in slot]
                return (sum(ps) / len(ps) if ps else 1e9, order[nid])
            c.sort(key=key)
            for i, nid in enumerate(c):
                slot[nid] = (b, i)
    band_slots = {b: max((len(cells[(b, r)]) for r in range(nrows)), default=0) for b in bands}
    band_w = {b: max(1, band_slots[b]) * (W + SLOT_GAP) - SLOT_GAP + 2 * PAD for b in bands}

    top = 150 if spec.get("title") else 60
    x = 40
    band_x = {}
    for b in bands:
        band_x[b] = x
        x += band_w[b] + BAND_GAP
    pos = {}
    for r in range(nrows):
        y = top + PAD + r * (H + ROW_GAP)
        for b in bands:
            c = cells[(b, r)]
            used = len(c) * (W + SLOT_GAP) - SLOT_GAP
            start = band_x[b] + PAD + (band_w[b] - 2 * PAD - used) / 2
            for i, nid in enumerate(c):
                pos[nid] = (start + i * (W + SLOT_GAP), y)
    geo = {
        "W": W, "H": H, "top": top, "nrows": nrows, "bands": bands, "band_x": band_x, "band_w": band_w,
        "bottom": top + PAD + nrows * (H + ROW_GAP) - ROW_GAP + PAD,
        "right": max(band_x[b] + band_w[b] for b in bands) if bands else 40 + W,
    }
    return {"pos": pos, "geo": geo}


def build(spec: dict, existing: dict | None = None, link_prefix: str = "") -> list[dict]:
    """Spec → elements. When `existing` (a previous scene) is given, boxes, lanes and notes keep
    the x/y the user left them at; arrows are re-routed from those positions."""
    L = layout(spec)
    pos, geo = L["pos"], L["geo"]
    W, H = geo["W"], geo["H"]
    keep = {}
    if existing:
        for e in live(existing.get("elements", [])):
            if e["id"].startswith(("n:", "lane:", "note:")):
                keep[e["id"]] = (e["x"], e["y"], e.get("width"), e.get("height"))
    els: list[dict] = []

    # lanes first (drawn behind)
    lane_defs = {l["id"]: l for l in spec.get("lanes") or []}
    lane_rows = {}
    for b in geo["bands"]:
        if b is None:
            continue
        lid = f"lane:{b}"
        x, y = geo["band_x"][b], geo["top"]
        w, h = geo["band_w"][b], geo["bottom"] - geo["top"]
        if lid in keep:
            x, y, w2, h2 = keep[lid]
            w, h = w2 or w, h2 or h
        r = base(lid, "rectangle", x, y, w, h, strokeColor="#adb5bd", strokeStyle="dashed",
                 strokeWidth=1, roughness=0, roundness={"type": 3}, groupIds=[f"g:{lid}"])
        bnd = lane_defs[b].get("boundary") or ""
        r["customData"] = {"by": "agent", "role": "lane", "key": b, "label": lane_defs[b]["label"], "boundary": bnd}
        ltext = lane_defs[b]["label"] + (f" · {bnd} boundary" if bnd else "")
        t = mk_text(f"lanet:{b}", ltext, x + 12, y + 8, w - 24, FS_SMALL * LH,
                    fs=FS_SMALL, align="left", valign="top", color="#868e96")
        t["groupIds"] = [f"g:{lid}"]
        els += [r, t]
        lane_rows[b] = r

    # title block
    if spec.get("title"):
        els.append(mk_text("title", spec["title"], 40, 40, max(400, len(spec["title"]) * 24 * CHAR_W), 24 * LH,
                           fs=24, align="left", valign="top"))
        sub = " · ".join(s for s in (
            spec.get("question"), f"example: {spec['example']}" if spec.get("example") else None,
            f"mode: {spec['mode']}" if spec.get("mode") else None,
            f"level: {spec['level']} — a box with a link opens its detail board" if spec.get("level") else None) if s)
        if sub:
            els.append(mk_text("subtitle", sub, 40, 78, max(400, len(sub) * FS_SMALL * CHAR_W), FS_SMALL * LH,
                               fs=FS_SMALL, align="left", valign="top", color="#868e96"))

    # boxes
    boxes = {}
    for n in spec.get("nodes") or []:
        x, y = pos[n["id"]]
        w, h = W, H
        nid = f"n:{n['id']}"
        if nid in keep:
            x, y, w2, h2 = keep[nid]
            w, h = w2 or w, h2 or h
        link = None
        at = n.get("at", "")
        if link_prefix and at:
            link = link_prefix + at
        elif n.get("detail"):
            link = f"./{n['detail']}.excalidraw"
        shape = n.get("shape") or ROLE_SHAPE.get(n.get("role", ""), "box")
        e, t = mk_box(n["id"], n["label"], at, n.get("kind", "unchanged"), shape,
                      x, y, w, h, step=n.get("step"), lane=n.get("lane"), link=link, tech=n.get("tech", ""),
                      role=n.get("role", ""))
        if n.get("detail"):
            e["customData"]["detail"] = n["detail"]
        if n.get("covers"):
            e["customData"]["covers"] = list(n["covers"])
        if n.get("unverified"):
            e["customData"]["unverified"] = True
            t["text"] = t["originalText"] = t["text"] + "\nUNVERIFIED"
            fit_text_in(e, t)
        els += [e, t]
        boxes[n["id"]] = e
        if n.get("step") is not None:
            bx, by = e["x"] - 14, e["y"] - 14
            b = base(f"badge:{n['id']}", "ellipse", bx, by, 30, 30, backgroundColor="#1e1e1e",
                     strokeColor="#1e1e1e", roughness=0)
            b["customData"] = {"by": "agent", "role": "badge", "key": n["id"]}
            bt = mk_text(f"badget:{n['id']}", str(n["step"]), bx, by, 30, 30, fs=14, container=b["id"], color="#ffffff")
            bind(b, bt)
            fit_text_in(b, bt)
            els += [b, bt]

    # arrows — several between the same pair fan out symmetrically, measured in ONE frame
    # (from the smaller id to the larger), so an arrow going the other way lands on the far side
    edges = spec.get("edges") or []
    pair_total: dict = {}
    for ed in edges:
        key = tuple(sorted((ed["from"], ed["to"])))
        pair_total[key] = pair_total.get(key, 0) + 1
    pair_seen: dict = {}
    for i, ed in enumerate(edges):
        key = tuple(sorted((ed["from"], ed["to"])))
        k = pair_seen.get(key, 0)
        pair_seen[key] = k + 1
        offset = (k - (pair_total[key] - 1) / 2) * 44
        if ed["from"] > ed["to"]:
            offset = -offset
        label = ed.get("label", "")
        if ed.get("when"):
            label = f"{label}\nif {ed['when']}" if label else f"if {ed['when']}"
        els += mk_arrow(f"e:{i}:{ed['from']}->{ed['to']}", boxes[ed["from"]], boxes[ed["to"]], label,
                        ed.get("kind", "unchanged"), offset=offset,
                        data={"from": ed["from"], "to": ed["to"], "when": ed.get("when"),
                              "via": ed.get("via"), "on_fail": ed.get("on_fail")})

    # notes in a margin column to the right, connected by a dotted line
    nx = geo["right"] + 60
    ny = geo["top"]
    for i, note in enumerate(spec.get("notes") or []):
        near = boxes.get(note.get("near"))
        nid = f"note:{i}"
        x, y = (nx, near["y"] if near else ny)
        if nid in keep:
            x, y = keep[nid][0], keep[nid][1]
        parts = mk_note(nid, note["text"], x, y, note.get("kind", "answer"), near["id"] if near else None)
        r = parts[0]
        while overlaps(bbox(r), [e for e in els if e["id"].startswith("note:")]):
            r["y"] += r["height"] + 16
            parts[1]["y"] = r["y"] + 12
        ny = r["y"] + r["height"] + 16
        els += parts
        if near:
            els += mk_arrow(f"notea:{i}", r, near, "", "removed", dashed=True, head="dot")

    # legend: only the kinds this board uses
    used = [n.get("kind", "unchanged") for n in spec.get("nodes") or []]
    used_edges = [e.get("kind", "unchanged") for e in spec.get("edges") or []]
    lx, ly = 40, geo["bottom"] + 40
    for kind in KINDS:
        if kind not in used:
            continue
        bg, stroke, meaning = KINDS[kind]
        r = base(f"legend:{kind}", "rectangle", lx, ly, 28, 20, backgroundColor=bg, strokeColor=stroke,
                 roundness={"type": 3}, roughness=0, strokeWidth=1)
        r["customData"] = {"by": "agent", "role": "legend"}
        t = mk_text(f"legendt:{kind}", f"{kind} — {meaning}", lx + 36, ly, len(meaning) * FS_SMALL * CHAR_W + 120,
                    FS_SMALL * LH, fs=FS_SMALL, align="left", valign="top", color="#495057")
        els += [r, t]
        ly += 28
    for kind in ("data", "logic", "new", "failing", "trace", "removed", "touched"):
        if kind in used_edges and kind not in used:
            stroke, width, style = EDGE_KINDS[kind]
            ln = base(f"legendl:{kind}", "line", lx, ly + 10, 28, 0, strokeColor=stroke, strokeWidth=width,
                      strokeStyle=style, points=[[0, 0], [28, 0]], roughness=0)
            meaning = {"trace": "the worked example travels here", "new": "arrow the plan adds",
                       "failing": "the failing hop", "removed": "arrow the plan removes",
                       "touched": "arrow the plan changes",
                       "data": "DATA — something is carried along this arrow",
                       "logic": "LOGIC — control only, nothing is carried"}[kind]
            t = mk_text(f"legendlt:{kind}", meaning, lx + 36, ly, len(meaning) * FS_SMALL * CHAR_W + 40,
                        FS_SMALL * LH, fs=FS_SMALL, align="left", valign="top", color="#495057")
            els += [ln, t]
            ly += 28
    if existing:
        old = by_id(existing.get("elements", []))
        for e in els:
            if e["id"] in old:
                e["version"] = int(old[e["id"]].get("version", 1)) + 1
                e["versionNonce"] = h32(f"{e['id']}:v{e['version']}:{now_ms()}")
    return els


# ── reading the board ─────────────────────────────────────────────────────────────────────
def handle(e: dict) -> str:
    d = agent_data(e)
    if d.get("key") and d.get("role") == "box":
        return f"#{d['key']}"
    return f"#u:{hashlib.sha1(e['id'].encode()).hexdigest()[:6]}"


def scene_boxes(els: list[dict]) -> list[dict]:
    return [e for e in live(els) if is_box(e) and agent_data(e).get("role") not in ("lane", "legend", "badge", "note")]


def note_boxes(els: list[dict]) -> list[dict]:
    return [e for e in live(els) if agent_data(e).get("role") == "note"]


def free_texts(els: list[dict]) -> list[dict]:
    return [e for e in live(els) if e["type"] == "text" and not e.get("containerId")
            and e["id"] not in ("title", "subtitle") and not e["id"].startswith(("lanet:", "legendt:", "legendlt:"))]


def text_of(e: dict, idx: dict) -> str:
    return e.get("text", "") if e["type"] == "text" else bound_text(e, idx)


def resolve(els: list[dict], ref: str) -> dict:
    """#key, #u:xxxxxx, or a unique substring of a box's text → the element."""
    idx = by_id(els)
    cands = scene_boxes(els) + note_boxes(els) + free_texts(els)
    ref = ref.strip()
    for e in cands:
        if handle(e) == ref or e["id"] == ref or f"n:{ref.lstrip('#')}" == e["id"]:
            return e
    needle = ref.lstrip("#").lower()
    hits = [e for e in cands if needle in text_of(e, idx).lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"draw: no box matches {ref!r} — run `describe` for the handles")
    raise SystemExit(f"draw: {ref!r} matches {len(hits)} boxes: " + ", ".join(handle(h) for h in hits))


def endpoint_box(arrow: dict, which: str, boxes: list[dict], idx: dict) -> dict | None:
    b = arrow.get(f"{which}Binding") or {}
    if b.get("elementId") in idx and not idx[b["elementId"]].get("isDeleted"):
        return idx[b["elementId"]]
    pts = arrow.get("points") or [[0, 0]]
    p = pts[0] if which == "start" else pts[-1]
    pt = (arrow["x"] + p[0], arrow["y"] + p[1])
    nb = nearest_box(pt, boxes)
    if nb and dist(pt, center(nb)) < max(nb["width"], nb["height"]) * 0.9:
        return nb
    return None


def who(e: dict) -> str:
    return "agent" if agent_data(e) else "you"


def kind_of_color(bg: str) -> str | None:
    for k, (b, s, _) in KINDS.items():
        if (bg or "").lower() == b:
            return k
    return None


def describe(scene: dict, path: Path) -> str:
    els = scene.get("elements", [])
    idx = by_id(els)
    lv = live(els)
    boxes = scene_boxes(els)
    out = []
    title = next((e["text"] for e in lv if e["id"] == "title"), None)
    sub = next((e["text"] for e in lv if e["id"] == "subtitle"), None)
    mine = [b for b in boxes if agent_data(b)]
    yours = [b for b in boxes if not agent_data(b)]
    arrows = [e for e in lv if e["type"] == "arrow" and not e["id"].startswith("notea:")]
    free_text = free_texts(els)
    strokes = [e for e in lv if e["type"] in ("freedraw", "line") and not e["id"].startswith("legendl:")]
    images = [e for e in lv if e["type"] == "image"]
    notes = note_boxes(els)
    lanes = [e for e in lv if agent_data(e).get("role") == "lane"]
    out.append(f"BOARD {path.name}" + (f" — {title}" if title else ""))
    if sub:
        out.append(f"  {sub}")
    out.append(f"  boxes {len(boxes)} ({len(mine)} agent, {len(yours)} yours) · arrows {len(arrows)} · "
               f"notes {len(notes)} · free text {len(free_text)} · strokes {len(strokes)}")
    if lanes:
        out.append("  lanes: " + " | ".join(
            f"{agent_data(l).get('key')} = {agent_data(l)['label']}"
            + (f" ({agent_data(l)['boundary']} boundary)" if agent_data(l).get("boundary") else "") for l in lanes))
    steps = sorted({agent_data(b).get("step") for b in boxes if agent_data(b).get("step") is not None})
    built = (agent_data(idx.get("title") or {}) or {}).get("built") or []
    if steps or built:
        out.append(f"  phases: built {built or '—'} · planned on the board {[s for s in steps if s not in built] or '—'}")

    def lane_for(e):
        cx, cy = center(e)
        for l in lanes:
            x0, y0, x1, y1 = bbox(l)
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return agent_data(l).get("key") or agent_data(l)["label"]
        return None
    out.append("BOXES")
    for b in sorted(boxes, key=lambda e: (round(e["y"] / 40), e["x"])):
        d = agent_data(b)
        txt = bound_text(b, idx).replace("\n", " · ")
        if d:
            line = f"  {handle(b):<14} {(d.get('label') or '').replace(chr(10), ' · ')}"
            if d.get("at"):
                line += f" · {d['at']}"
            line += f" · {d.get('kind')}"
            if d.get("part"):
                line += f" · role {d['part']}"
            if d.get("step") is not None:
                line += f" · step {d['step']}"
            cur_kind = kind_of_color(b.get("backgroundColor"))
            if cur_kind and cur_kind != d.get("kind"):
                line += f" · RECOLOURED by you to {cur_kind}"
            if d.get("tech"):
                line += f" · [{d['tech']}]"
            if txt and txt != box_label(d.get("label", ""), d.get("at", ""), d.get("tech", ""), d.get("part", "")).replace("\n", " · "):
                line += f' · RELABELLED by you: "{txt}"'
            if d.get("unverified"):
                line += " · UNVERIFIED"
        else:
            near = nearest_box(center(b), mine)
            line = f'  {handle(b):<14} "{txt}"  drawn by you ({b["type"]}, stroke {b.get("strokeColor")})'
            if near:
                line += f" near {handle(near)}"
        ln = lane_for(b)
        if ln:
            line += f" · lane: {ln}"
        out.append(line)
    if arrows:
        out.append("ARROWS")
        for a in arrows:
            s = endpoint_box(a, "start", boxes, idx)
            t = endpoint_box(a, "end", boxes, idx)
            lab = bound_text(a, idx).replace("\n", " ")
            d = agent_data(a)
            line = f"  {handle(s) if s else '?':<14} → {handle(t) if t else '?':<14}"
            if lab:
                line += f' "{lab}"'
            if d:
                line += f"  ({d.get('kind')}" + (f", {d['via']}" if d.get("via") else "") + ")"
                if d.get("on_fail"):
                    line += f"  on failure: {d['on_fail']}"
            else:
                line += f"  (yours, stroke {a.get('strokeColor')})"
            out.append(line)
    if notes:
        out.append("NOTES (agent)")
        for n in notes:
            d = agent_data(n)
            near = idx.get(d.get("near") or "")
            out.append(f"  [{d.get('kind')}] {d.get('text')}" + (f"  → {handle(near)}" if near else ""))
    if free_text:
        out.append("FREE TEXT")
        for t in free_text:
            near = nearest_box(center(t), boxes)
            out.append(f'  {handle(t):<14} "{t.get("text", "").strip()}"  ({who(t)})' + (f" near {handle(near)}" if near else ""))
    if strokes:
        out.append("STROKES (yours)")
        for s in strokes:
            x0, y0, x1, y1 = bbox(s)
            enclosed = [b for b in boxes if x0 <= bbox(b)[0] and y0 <= bbox(b)[1] and x1 >= bbox(b)[2] and y1 >= bbox(b)[3]]
            if enclosed:
                out.append(f"  circled: {', '.join(handle(b) for b in enclosed)}")
                continue
            hit = [b for b in boxes if bbox(b)[0] <= (x0 + x1) / 2 <= bbox(b)[2] and bbox(b)[1] <= (y0 + y1) / 2 <= bbox(b)[3]]
            if hit:
                out.append(f"  mark over {handle(hit[0])} ({s['type']}, {int(x1 - x0)}×{int(y1 - y0)}px)")
                continue
            near = nearest_box(((x0 + x1) / 2, (y0 + y1) / 2), boxes)
            out.append(f"  {s['type']} {int(x1 - x0)}×{int(y1 - y0)}px" + (f" near {handle(near)}" if near else ""))
    if images:
        out.append(f"IMAGES: {len(images)} pasted")
    return "\n".join(out)


# ── diff since the agent last looked ──────────────────────────────────────────────────────
def state_path(board: Path) -> Path:
    return STATE_DIR / (hashlib.sha1(str(board.resolve()).encode()).hexdigest()[:16] + ".json")


def snapshot(scene: dict) -> dict:
    snap = {}
    idx = by_id(scene.get("elements", []))
    for e in live(scene.get("elements", [])):
        snap[e["id"]] = {
            "v": e.get("version", 1), "type": e["type"], "text": bound_text(e, idx) if e["type"] != "text" else e.get("text", ""),
            "bg": e.get("backgroundColor"), "x": round(e["x"]), "y": round(e["y"]),
            "sb": (e.get("startBinding") or {}).get("elementId"), "eb": (e.get("endBinding") or {}).get("elementId"),
        }
    return snap


def ack(board: Path, scene: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(state_path(board), "w", encoding="utf-8") as fh:
        json.dump({"board": str(board.resolve()), "at": now_ms(), "snap": snapshot(scene)}, fh)


def diff(board: Path, scene: dict) -> str:
    sp = state_path(board)
    if not sp.exists():
        return "no earlier look at this board on record — everything below is the whole board\n\n" + describe(scene, board)
    with open(sp, encoding="utf-8") as fh:
        old = json.load(fh)["snap"]
    els = scene.get("elements", [])
    idx = by_id(els)
    boxes = scene_boxes(els)
    new = snapshot(scene)
    out = []

    def name(eid):
        e = idx.get(eid)
        if not e:
            return old.get(eid, {}).get("text") or eid
        if e["type"] in ("rectangle", "ellipse", "diamond"):
            return handle(e) + (f' "{bound_text(e, idx).splitlines()[0]}"' if bound_text(e, idx) else "")
        return handle(e)

    def nearest_name(e):
        nb = nearest_box(center(e), boxes, exclude=(e["id"],))
        return f" near {handle(nb)}" if nb else ""

    moved = 0
    for eid, s in new.items():
        e = idx[eid]
        if e.get("containerId"):
            continue  # reported through its container
        if eid not in old:
            if e["type"] in ("rectangle", "ellipse", "diamond"):
                out.append(f'+ box {handle(e)} "{bound_text(e, idx)}" ({e["type"]}, {who(e)}){nearest_name(e)}')
            elif e["type"] == "arrow":
                s_ = endpoint_box(e, "start", boxes, idx)
                t_ = endpoint_box(e, "end", boxes, idx)
                lab = bound_text(e, idx)
                out.append(f"+ arrow {handle(s_) if s_ else '?'} → {handle(t_) if t_ else '?'}"
                           + (f' "{lab}"' if lab else "") + f" ({who(e)})")
            elif e["type"] == "text":
                out.append(f'+ text {handle(e)} "{e.get("text", "").strip()}" ({who(e)}){nearest_name(e)}')
            elif e["type"] in ("freedraw", "line"):
                x0, y0, x1, y1 = bbox(e)
                enclosed = [b for b in boxes if x0 <= bbox(b)[0] and y0 <= bbox(b)[1] and x1 >= bbox(b)[2] and y1 >= bbox(b)[3]]
                if enclosed:
                    out.append(f"+ circled {', '.join(handle(b) for b in enclosed)} ({who(e)})")
                else:
                    out.append(f"+ {e['type']} stroke {int(x1 - x0)}×{int(y1 - y0)}px ({who(e)}){nearest_name(e)}")
            elif e["type"] == "image":
                out.append(f"+ image pasted{nearest_name(e)}")
            else:
                out.append(f"+ {e['type']} ({who(e)}){nearest_name(e)}")
            continue
        o = old[eid]
        if o["v"] == s["v"] and o["text"] == s["text"]:
            continue
        changes = []
        if o["text"] != s["text"]:
            changes.append(f'text "{o["text"]}" → "{s["text"]}"')
        if o["bg"] != s["bg"]:
            k = kind_of_color(s["bg"])
            changes.append(f"recoloured to {k or s['bg']}")
        if e["type"] == "arrow" and (o["sb"], o["eb"]) != (s["sb"], s["eb"]):
            changes.append(f"now {name(s['sb']) if s['sb'] else '?'} → {name(s['eb']) if s['eb'] else '?'}")
        if abs(o["x"] - s["x"]) + abs(o["y"] - s["y"]) > 8 and not changes:
            moved += 1
            continue
        if changes:
            out.append(f"~ {name(eid)}: " + "; ".join(changes))
    for eid, o in old.items():
        if eid not in new and not idx.get(eid, {}).get("containerId"):
            label = o["text"] or o["type"]
            out.append(f'- {o["type"]} "{label}" removed' if o["type"] != "arrow" else f'- arrow "{label}" removed')
    if moved:
        out.append(f"({moved} element(s) moved — layout only, kept as is)")
    if not out:
        return "no change since the agent last looked"
    return "\n".join(out)


# ── the hands: add / set / rm ─────────────────────────────────────────────────────────────
def free_spot(els: list[dict], near: dict | None, w: float, h: float) -> tuple[float, float]:
    if near is None:
        boxes = [e for e in live(els) if e["type"] in ("rectangle", "ellipse", "diamond")]
        if not boxes:
            return 60, 160
        x = min(b["x"] for b in boxes)
        y = max(bbox(b)[3] for b in boxes) + ROW_GAP
        return x, y
    nx0, ny0, nx1, ny1 = bbox(near)
    for x, y in ((nx1 + SLOT_GAP, ny0), (nx0, ny1 + ROW_GAP), (nx0 - w - SLOT_GAP, ny0), (nx0, ny0 - h - ROW_GAP),
                 (nx1 + SLOT_GAP, ny1 + ROW_GAP)):
        if not overlaps((x, y, x + w, y + h), live(els)):
            return x, y
    return nx1 + SLOT_GAP, ny1 + ROW_GAP + 40


def cmd_add(a) -> int:
    board = Path(a.board)
    scene = load(board)
    els = scene["elements"]
    if a.what == "box":
        key = a.key or slug(a.label.split("\n")[0])
        if any(e["id"] == f"n:{key}" for e in live(els)):
            raise SystemExit(f"draw: a box #{key} already exists — use `set`, or --key for a new one")
        near = resolve(els, a.near) if a.near else None
        lane = resolve_lane(els, a.lane) if a.lane else None
        lines = box_label(a.label, a.at or "", a.tech, a.role or "").split("\n")
        w = max(BOX_W_MIN, min(BOX_W_MAX, measure(lines, FS)[0] + 32))
        h = max(BOX_H_MIN, len(lines) * FS * LH + 28)
        if near is None and lane is not None:
            inside = [e for e in scene_boxes(els) if bbox(lane)[0] <= center(e)[0] <= bbox(lane)[2]]
            near = max(inside, key=lambda e: e["y"]) if inside else None
            x, y = (near["x"], bbox(near)[3] + ROW_GAP) if near else (lane["x"] + PAD, lane["y"] + PAD + 20)
            while overlaps((x, y, x + w, y + h), live(els)):
                y += h + SLOT_GAP
        else:
            x, y = free_spot(els, near, w, h)
        shape = a.shape or ROLE_SHAPE.get(a.role or "", "box")
        e, t = mk_box(key, a.label, a.at or "", a.kind, shape, x, y, w, h, step=a.step,
                      lane=agent_data(lane).get("key") if lane else None, tech=a.tech, role=a.role or "")
        if a.covers:
            e["customData"]["covers"] = list(a.covers)
        els += [e, t]
        if lane is not None:
            grow_lane(lane, e)
        print(f"added box #{key} at ({int(x)}, {int(y)})")
    elif a.what == "arrow":
        s, t = resolve(els, a.src), resolve(els, a.dst)
        n = sum(1 for e in live(els) if e["type"] == "arrow")
        label = a.label or ""
        if a.when:
            label = f"{label}\nif {a.when}" if label else f"if {a.when}"
        parts = mk_arrow(f"e:a{n}:{s['id']}->{t['id']}", s, t, label, a.kind,
                         data={"from": s["id"], "to": t["id"], "when": a.when, "via": a.via, "on_fail": a.on_fail})
        touch(s)
        touch(t)
        els += parts
        print(f"added arrow {handle(s)} → {handle(t)}" + (f' "{a.label}"' if a.label else ""))
    elif a.what == "note":
        near = resolve(els, a.near)
        n = sum(1 for e in live(els) if agent_data(e).get("role") == "note")
        w = NOTE_W
        h = len(wrap(a.text, 30)) * FS_SMALL * LH + 24
        x, y = free_spot(els, near, w, h)
        parts = mk_note(f"note:a{n}", a.text, x, y, a.as_, near["id"])
        els += parts
        els += mk_arrow(f"notea:a{n}", parts[0], near, "", "removed", dashed=True, head="dot")
        touch(near)
        print(f"added {a.as_} note near {handle(near)}")
    save(board, scene)
    ack(board, scene)
    return 0


def resolve_lane(els, ref):
    lanes = [e for e in live(els) if agent_data(e).get("role") == "lane"]
    for l in lanes:
        d = agent_data(l)
        if ref.lstrip("#") in (d.get("key"), d.get("label")) or ref.lower() in d.get("label", "").lower():
            return l
    raise SystemExit(f"draw: no lane matches {ref!r}; lanes: " + ", ".join(agent_data(l)["label"] for l in lanes))


def grow_lane(lane: dict, box: dict) -> None:
    x0, y0, x1, y1 = bbox(lane)
    bx0, by0, bx1, by1 = bbox(box)
    nx0, ny0 = min(x0, bx0 - PAD), min(y0, by0 - PAD)
    nx1, ny1 = max(x1, bx1 + PAD), max(y1, by1 + PAD)
    if (nx0, ny0, nx1, ny1) != (x0, y0, x1, y1):
        lane["x"], lane["y"], lane["width"], lane["height"] = nx0, ny0, nx1 - nx0, ny1 - ny0
        touch(lane)


def cmd_set(a) -> int:
    board = Path(a.board)
    scene = load(board)
    els = scene["elements"]
    idx = by_id(els)
    e = resolve(els, a.ref)
    d = e.setdefault("customData", {})
    if not d.get("by"):
        d.update({"by": "agent", "role": "box", "key": slug(bound_text(e, idx) or e["id"]),
                  "label": bound_text(e, idx), "at": "", "kind": "unchanged", "shape": "box", "adopted": True})
    changed = []
    if a.kind:
        d["kind"] = a.kind
        style_box(e, a.kind, d.get("shape", "box"))
        changed.append(f"kind → {a.kind}")
    if a.label is not None:
        d["label"] = a.label
        changed.append(f"label → {a.label!r}")
    if a.at is not None:
        d["at"] = a.at
        changed.append(f"at → {a.at}")
    if a.step is not None:
        d["step"] = a.step
        changed.append(f"step → {a.step}")
    if d.get("role") == "note" and a.text is not None:
        d["text"] = a.text
    if a.tech is not None:
        d["tech"] = a.tech
        changed.append(f"tech → {a.tech!r}")
    if a.role is not None:
        d["part"] = a.role
        changed.append(f"role → {a.role}")
    if a.covers is not None:
        d["covers"] = list(a.covers)
        changed.append(f"covers → {a.covers}")
    if a.label is not None or a.at is not None or a.text is not None or a.tech is not None or a.role is not None:
        txt = box_label(d.get("label", ""), d.get("at", ""), d.get("tech", ""), d.get("part", "")) if d.get("role") != "note" else "\n".join(wrap(d["text"], 30))
        t = None
        for b in e.get("boundElements") or []:
            if b.get("type") == "text" and b["id"] in idx:
                t = idx[b["id"]]
        if t is None:
            t = mk_text(f"t:{d['key']}", txt, e["x"], e["y"], e["width"], e["height"], container=e["id"])
            bind(e, t)
            els.append(t)
        t["text"] = t["originalText"] = txt
        fit_text_in(e, t)
        touch(t)
    touch(e)
    save(board, scene)
    ack(board, scene)
    print(f"{handle(e)}: " + (", ".join(changed) or "no change"))
    return 0


def cmd_rm(a) -> int:
    board = Path(a.board)
    scene = load(board)
    els = scene["elements"]
    idx = by_id(els)
    for ref in a.refs:
        e = resolve(els, ref)
        gone = {e["id"]}
        for b in e.get("boundElements") or []:
            gone.add(b["id"])
        for x in els:
            if x["id"] in gone or x.get("containerId") in gone or \
               (x.get("startBinding") or {}).get("elementId") == e["id"] or (x.get("endBinding") or {}).get("elementId") == e["id"]:
                x["isDeleted"] = True
                touch(x)
        for x in els:  # drop the dangling back-references
            if x.get("boundElements"):
                x["boundElements"] = [b for b in x["boundElements"] if not idx.get(b["id"], {}).get("isDeleted")]
        print(f"removed {handle(e)} and its arrows")
    save(board, scene)
    ack(board, scene)
    return 0


def cmd_phase(a) -> int:
    """Phase N is built: every box planned for it stops being 'new'/'touched' and becomes part of
    the as-is picture; its badge turns green. What is left green or yellow is what is still to plan
    or build — so the next planning round starts from a board that tells the truth."""
    board = Path(a.board)
    scene = load(board)
    els = scene["elements"]
    idx = by_id(els)
    steps = set(a.built)
    built_keys, changed = set(), 0
    for e in live(els):
        d = agent_data(e)
        if d.get("role") == "box" and d.get("step") in steps:
            built_keys.add(d.get("key"))
            d["built"] = True
            if d.get("kind") in ("new", "touched"):
                d["planned_kind"] = d["kind"]
                d["kind"] = "unchanged"
                style_box(e, "unchanged", d.get("shape", "box"))
                touch(e)
                changed += 1
    for e in live(els):
        d = agent_data(e)
        if d.get("role") == "badge" and d.get("key") in built_keys:
            e["backgroundColor"] = e["strokeColor"] = "#2f9e44"
            touch(e)
        if d.get("role") == "arrow" and d.get("kind") in ("new", "touched"):
            a_, b_ = idx.get(d.get("from") or ""), idx.get(d.get("to") or "")
            if a_ is not None and b_ is not None and \
               agent_data(a_).get("kind") == "unchanged" and agent_data(b_).get("kind") == "unchanged":
                d["planned_kind"] = d["kind"]
                d["kind"] = "unchanged"
                stroke, width, style = EDGE_KINDS["unchanged"]
                if d.get("via") == "message":
                    style = VIAS["message"][0]
                e["strokeColor"], e["strokeWidth"], e["strokeStyle"] = stroke, width, style
                for b in e.get("boundElements") or []:
                    if b.get("type") == "text" and b["id"] in idx:
                        idx[b["id"]]["strokeColor"] = stroke
                        touch(idx[b["id"]])
                touch(e)
                changed += 1
    n = ", ".join(str(x) for x in sorted(steps))
    if not built_keys:
        raise SystemExit(f"draw: no box carries step {n} — `set #box --step N` first, or check `describe`")
    title = idx.get("title")
    if title is not None:
        td = title.setdefault("customData", {"by": "agent", "role": "title"})
        built = sorted(set(td.get("built") or []) | steps)
        td["built"] = built
        touch(title)
    sub = idx.get("subtitle")
    if sub is not None:
        base_txt = sub["text"].split(" · built: ")[0]
        done = sorted(set((agent_data(title) or {}).get("built") or steps)) if title is not None else sorted(steps)
        sub["text"] = sub["originalText"] = f"{base_txt} · built: {', '.join(map(str, done))} — plan the next slice on this board before /implement"
        sub["width"] = max(400, len(sub["text"]) * FS_SMALL * CHAR_W)
        touch(sub)
    save(board, scene)
    ack(board, scene)
    left = [handle(e) for e in scene_boxes(els) if agent_data(e).get("kind") in ("new", "touched")]
    print(f"steps {n} built: {len(built_keys)} box(es) now part of the as-is picture, {changed} element(s) recoloured; "
          + (f"still planned: {', '.join(left)}" if left else "nothing left in green or yellow — plan the next "
             f"slice here with `add box --step <n>`"))
    return 0


def changed_files(repo: Path, base: str, head: str, files) -> list[str]:
    if files:
        return list(files)
    for rng in (f"{base}...{head}", f"{base}..{head}"):
        r = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", rng], capture_output=True, text=True)
        if r.returncode == 0:
            return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    raise SystemExit(f"draw: git diff failed for {base}..{head} in {repo}: {r.stderr.strip()}")


def box_patterns(d: dict) -> list[str]:
    pats = list(d.get("covers") or [])
    at = (d.get("at") or "").split(":")[0]
    if at:
        pats.append(at)
    return pats


def file_hits(file: str, pats: list[str]) -> bool:
    for pat in pats:
        pat = pat.rstrip("/")
        if file == pat or file.startswith(pat + "/") or fnmatch.fnmatch(file, pat):
            return True
    return False


def review_boxes(els: list[dict], files: list[str]) -> tuple[dict, list[str]]:
    """-> ({box_id: {"status", "files", "planned"}}, files_outside)."""
    result, landed = {}, set()
    for b in scene_boxes(els):
        d = agent_data(b)
        if not d:
            continue
        pats = box_patterns(d)
        hits = [f for f in files if pats and file_hits(f, pats)]
        landed.update(hits)
        planned = d.get("kind") in ("new", "touched", "removed") or d.get("step") is not None
        status = ("built" if hits else "missing") if planned else ("unspecced" if hits else "untouched")
        result[b["id"]] = {"status": status, "files": hits, "planned": planned}
    return result, [f for f in files if f not in landed]


def cmd_review(a) -> int:
    plan = Path(a.board)
    repo = Path(a.repo).resolve()
    scene = load(plan)
    els = scene["elements"]
    idx = by_id(els)
    files = changed_files(repo, a.base, a.head, a.files)
    rng = f"{a.base}..{a.head}" if not a.files else f"{len(files)} file(s) given"
    ign_pats = ([] if a.no_default_ignores else list(DEFAULT_IGNORES)) + list(a.ignore or [])
    if a.list_ignores:
        print("\n".join(ign_pats))
        return 0
    ignored = [f for f in files if file_hits(f, ign_pats)]
    files = [f for f in files if f not in ignored]
    res, outside = review_boxes(els, files)
    as_is = not any(v["planned"] for v in res.values())
    if as_is:  # nothing was planned here: every touched box is simply "touched", never unspecced
        for v in res.values():
            if v["status"] == "unspecced":
                v["status"] = "touched"
    built = [k for k, v in res.items() if v["status"] == "built"]
    missing = [k for k, v in res.items() if v["status"] == "missing"]
    unspecced = [k for k, v in res.items() if v["status"] == "unspecced"]

    # ── the review board: a recoloured copy, the plan board itself is never written ──
    out = copy.deepcopy(scene)
    oels = out["elements"]
    oidx = by_id(oels)
    for bid, v in res.items():
        b = oidx[bid]
        d = b["customData"]
        d["review"] = v["status"]
        if v["status"] == "built":
            badge = oidx.get(f"badge:{d.get('key')}")
            if badge is not None:
                badge["backgroundColor"] = badge["strokeColor"] = "#2f9e44"
                touch(badge)
            else:
                bx, by = b["x"] + b["width"] - 16, b["y"] - 14
                bd = base(f"rbadge:{d.get('key')}", "ellipse", bx, by, 30, 30, backgroundColor="#2f9e44",
                          strokeColor="#2f9e44", roughness=0)
                bd["customData"] = {"by": "agent", "role": "badge", "key": d.get("key")}
                bt = mk_text(f"rbadget:{d.get('key')}", "✓", bx, by, 30, 30, fs=14, container=bd["id"], color="#ffffff")
                bind(bd, bt)
                fit_text_in(bd, bt)
                oels += [bd, bt]
        elif v["status"] == "missing":
            b["strokeStyle"], b["opacity"] = "dashed", 55
            touch(b)
        elif v["status"] == "touched":
            style_box(b, "touched", d.get("shape", "box"))
            touch(b)
        elif v["status"] == "unspecced":
            style_box(b, "failing", d.get("shape", "box"))
            touch(b)
            n = sum(1 for e in oels if agent_data(e).get("role") == "note")
            shown = ", ".join(v["files"][:4]) + (" …" if len(v["files"]) > 4 else "")
            x, y = free_spot(oels, b, NOTE_W, 90)
            parts = mk_note(f"note:r{n}", f"UNSPECCED — changed but not in the plan: {shown}", x, y, "warning", b["id"])
            oels += parts
            oels += mk_arrow(f"notea:r{n}", parts[0], b, "", "removed", dashed=True, head="dot")
    ok = not unspecced and (not outside or as_is)
    if outside and not as_is:
        boxes = scene_boxes(oels)
        x0 = (max(bbox(e)[2] for e in boxes) - NOTE_W) if boxes else 600   # right of the title, never on it
        shown = ", ".join(outside[:8]) + (f" … +{len(outside) - 8}" if len(outside) > 8 else "")
        parts = mk_note("note:outside", f"{len(outside)} changed file(s) not on this board: {shown}", x0, 20, "warning")
        oels += parts
    # legend rows for the review states, under the plan legend (rebuilt first, so save() places it identically)
    oels = rebuild_legend(oels)
    out["elements"] = oels
    leg = [e for e in oels if e["id"].startswith(("legend:", "legendl:", "legendlt:", "legendt:"))]
    ly = (max(bbox(e)[3] for e in leg) + 8) if leg else (max(bbox(e)[3] for e in scene_boxes(oels)) + 40 if scene_boxes(oels) else 400)
    for key, bg, stroke, style, meaning in (
            ("built", "#b2f2bb", "#2f9e44", "solid", "built ✓ — planned, and this change touched it"),
            ("unspecced", "#ffc9c9", "#e03131", "solid", "UNSPECCED — changed, but the plan did not say so"),
            ("missing", "#f8f9fa", "#adb5bd", "dashed", "missing — planned, not reached by this change")):
        r = base(f"rlegend:{key}", "rectangle", 40, ly, 28, 20, backgroundColor=bg, strokeColor=stroke,
                 strokeStyle=style, roundness={"type": 3}, roughness=0, strokeWidth=1)
        r["customData"] = {"by": "agent", "role": "legend"}
        t = mk_text(f"rlegendt:{key}", meaning, 76, ly, len(meaning) * FS_SMALL * CHAR_W + 40, FS_SMALL * LH,
                    fs=FS_SMALL, align="left", valign="top", color="#495057")
        oels += [r, t]
        ly += 28
    title = oidx.get("title")
    verdict = "MAP" if as_is else ("RIGHT THING" if ok else "CHECK")
    if title is not None:
        title["text"] = title["originalText"] = f"REVIEW {rng} — {verdict}: " + title["text"]
        title["strokeColor"] = "#f08c00" if as_is else ("#2f9e44" if ok else "#e03131")
        title["width"] = max(400, len(title["text"]) * 24 * CHAR_W)
        touch(title)
    sub = oidx.get("subtitle")
    summary = (f"{len(built)} planned box(es) built · {len(missing)} planned, not in this change · "
               f"{len(unspecced)} unplanned box(es) touched · {len(outside)} file(s) outside the board"
               + (f" · {len(ignored)} plumbing/lock/generated file(s) set aside" if ignored else ""))
    if sub is not None:
        sub["text"] = sub["originalText"] = summary
        sub["width"] = max(400, len(summary) * FS_SMALL * CHAR_W)
        touch(sub)
    dest = Path(a.out) if a.out else plan.with_name(plan.name.replace(".excalidraw", ".review.excalidraw"))
    save(dest, out)

    # ── optional lift onto the system board ──
    sys_lines = []
    if a.system:
        sysb = Path(a.system)
        sscene = load(sysb)
        sels = sscene["elements"]
        sres, _ = review_boxes(sels, files)
        sout = copy.deepcopy(sscene)
        soidx = by_id(sout["elements"])
        lanes = [e for e in live(sout["elements"]) if agent_data(e).get("role") == "lane"]

        def lane_of(e):
            cx, cy = center(e)
            for l in lanes:
                x0, y0, x1, y1 = bbox(l)
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    return agent_data(l).get("key")
            return None
        touched = {k for k, v in sres.items() if v["files"]}
        for bid in touched:
            b = soidx[bid]
            d = b["customData"]
            d["review"] = "touched"
            planned_files = all(any(res[cb]["planned"] and f in res[cb]["files"] for cb in res) for f in sres[bid]["files"])
            style_box(b, "touched" if planned_files else "failing", d.get("shape", "box"))
            touch(b)
        def end_box(ref):
            # A spec-built arrow names its box by spec id ("tui"), one added by `add arrow` by
            # element id ("n:tui"); accept both.
            ref = ref or ""
            return soidx.get(ref if ref.startswith("n:") else f"n:{ref}")
        lane_bnd = {agent_data(l).get("key"): agent_data(l).get("boundary") or "" for l in lanes}
        rank = {b: i for i, b in enumerate(("",) + tuple(BOUNDARIES))}

        def crossing_type(la, lb):
            return max(lane_bnd.get(la, ""), lane_bnd.get(lb, ""), key=lambda b: rank.get(b, 0))
        crossings, links = [], []
        for e in live(sout["elements"]):
            d = agent_data(e)
            if d.get("role") != "arrow" or str(e.get("id", "")).startswith("notea:"):
                continue
            a_, b_ = end_box(d.get("from")), end_box(d.get("to"))
            if a_ is None or b_ is None:
                continue
            fa, fb = a_["id"], b_["id"]
            changed = d.get("kind") in ("new", "touched") or (fa in touched and fb in touched)
            links.append((e, a_, b_, d, changed))
            if fa in touched and fb in touched and lane_of(a_) != lane_of(b_):
                fl = sres[fa]["files"] + sres[fb]["files"]
                planned = all(any(res[cb]["planned"] and f in res[cb]["files"] for cb in res) for f in fl)
                crossings.append((handle(a_), handle(b_), lane_of(a_), lane_of(b_), planned,
                                  crossing_type(lane_of(a_), lane_of(b_)), d.get("via") or ""))
                if not planned:
                    e["strokeColor"], e["strokeWidth"] = "#e03131", 3
                    touch(e)

        # ── design flags: the trade-offs that are risky unless someone decided them on purpose ──
        flags = []
        for sb in scene_boxes(sout["elements"]):
            sd = agent_data(sb)
            if sd.get("part") not in STATEFUL_ROLES and sd.get("shape") != "store":
                continue
            writers = [(a_, d, ch) for (_, a_, b_, d, ch) in links if b_["id"] == sb["id"]]
            names = sorted({handle(a_) for a_, _, _ in writers})
            if len(names) > 1 and any(ch for _, _, ch in writers):
                flags.append((sb, f"{len(names)} writers to {handle(sb)} ({', '.join(names)}), and this change "
                                  f"touches one: which write wins, and who is the owner?"))
        for e, a_, b_, d, ch in links:
            if not ch or lane_of(a_) == lane_of(b_):
                continue
            kind = crossing_type(lane_of(a_), lane_of(b_))
            if d.get("via") == "call" and kind in ("network", "trust") and not d.get("on_fail"):
                flags.append((b_, f"{handle(a_)} now waits on {handle(b_)} across a {kind} boundary, and nothing "
                                  f"says what happens when it is slow or down (timeout, retry, fallback)"))
        for ha, hb, la, lb, planned, kind, _ in crossings:
            if kind == "trust" and not planned:
                flags.append((None, f"{ha} → {hb} crosses a trust boundary unplanned: what checks the input?"))
        nf = 0
        for anchor, text in flags:
            if anchor is None:
                continue
            x, y = free_spot(sout["elements"], anchor, NOTE_W, 90)
            parts = mk_note(f"note:f{nf}", "DESIGN FLAG — " + text, x, y, "warning", anchor["id"])
            sout["elements"] += parts
            sout["elements"] += mk_arrow(f"notea:f{nf}", parts[0], anchor, "", "removed", dashed=True, head="dot")
            nf += 1
        st = soidx.get("title")
        if st is not None:
            st["text"] = st["originalText"] = f"REVIEW {rng} — running parts touched: {len(touched)}: " + st["text"]
            st["width"] = max(400, len(st["text"]) * 24 * CHAR_W)
            touch(st)
        sdest = sysb.with_name(sysb.name.replace(".excalidraw", ".review.excalidraw"))
        save(sdest, sout)
        sys_lines.append(f"system board: {len(touched)} running part(s) touched → {sdest}")
        for ha, hb, la, lb, planned, kind, via in crossings:
            how = " · ".join(x for x in (f"{kind} boundary" if kind else "", via) if x)
            sys_lines.append(f"  boundary {la} → {lb}: {ha} → {hb}" + (f" ({how})" if how else "")
                             + f" — {'planned' if planned else 'UNPLANNED crossing'}")
            if not planned:
                ok = False
        if not crossings:
            sys_lines.append("  no touched arrow crosses a lane")
        for _, text in flags:
            sys_lines.append(f"  DESIGN FLAG: {text}")

    # ── the words ──
    def hs(bid):
        return handle(idx[bid])
    touched_boxes = [k for k, v in res.items() if v["status"] == "touched"]
    if as_is:
        line = (f"MAP — no plan to compare against; {len(files)} changed file(s) touch {len(touched_boxes)} box(es): "
                f"{', '.join(hs(b) for b in touched_boxes) or 'none'}"
                + (f"; {len(outside)} file(s) on no box: {', '.join(outside[:6])}" + (" …" if len(outside) > 6 else "") if outside else ""))
    elif ok:
        line = (f"RIGHT THING — {len(files)} changed file(s) all land on planned boxes: "
                f"{', '.join(hs(b) for b in built) or 'none'}"
                + (f"; still to build: {', '.join(hs(b) for b in missing)}" if missing else ""))
    else:
        parts = []
        if unspecced:
            parts.append(f"{len(unspecced)} unplanned box(es) touched: {', '.join(hs(b) for b in unspecced)}")
        if outside:
            parts.append(f"{len(outside)} file(s) outside the board: {', '.join(outside[:6])}" + (" …" if len(outside) > 6 else ""))
        line = "CHECK — " + "; ".join(parts) if parts else "CHECK — an unplanned boundary crossing (see system board)"
    if ignored:
        line += f" (set aside: {len(ignored)} plumbing/lock/generated file(s))"
    print(line)
    print(f"review board: {dest}")
    if ignored:
        print("set aside as repo plumbing / lock / generated, not asked of the board: " + ", ".join(ignored))
    for l in sys_lines:
        print(l)
    print()
    print("| box | plan | changed files | verdict |")
    print("|---|---|---|---|")
    for bid, v in res.items():
        d = agent_data(idx[bid])
        if v["status"] == "untouched":
            continue
        plan_s = f"{d.get('kind')}" + (f" · step {d.get('step')}" if d.get("step") is not None else "")
        print(f"| {hs(bid)} | {plan_s} | {', '.join(v['files']) or '—'} | {v['status'].upper() if v['status'] != 'built' else 'built ✓'} |")
    return 0 if ok else 1


def cmd_check(a) -> int:
    board = Path(a.board)
    scene = load(board)
    els = scene["elements"]
    boxes = scene_boxes(els)
    problems = []
    if len(boxes) > MAX_BOXES:
        problems.append(f"{len(boxes)} boxes on the board; a reader holds ≤{MAX_BOXES} — split into overview + detail boards")
    repo = Path(a.repo).resolve() if a.repo else None
    for b in boxes:
        d = agent_data(b)
        if not d:
            continue
        if d.get("kind") not in ("external", "new") and d.get("shape") != "actor" and not d.get("at"):
            problems.append(f"{handle(b)} has no path:line")
        if repo and d.get("at"):
            why = verify_at(d["at"], repo)
            if why:
                problems.append(f"{handle(b)}: {why}")
        if d.get("unverified"):
            problems.append(f"{handle(b)} is marked UNVERIFIED — open the file and confirm or remove it")
    for p in problems:
        print("FAIL " + p)
    if not problems:
        print(f"ok: {len(boxes)} boxes" + (", every path:line exists" if repo else ""))
    return 1 if problems else 0


def read_spec(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def cmd_new(a) -> int:
    spec = read_spec(a.spec)
    errs = check_spec(spec, a.allow_big)
    if a.repo:
        repo = Path(a.repo).resolve()
        for n in spec.get("nodes") or []:
            if n.get("at"):
                why = verify_at(n["at"], repo)
                if why:
                    errs.append(f"node {n['id']}: {why}")
    if errs:
        for e in errs:
            print("FAIL " + e, file=sys.stderr)
        return 1
    for w in system_gaps(spec):
        print("WARN " + w, file=sys.stderr)
    board = Path(a.board)
    existing = load(board) if board.exists() and not a.fresh_layout else None
    scene = load(board) if board.exists() else load(Path("/nonexistent"))
    els = build(spec, existing, a.link_prefix or "")
    if existing and a.keep_yours:
        mine = {e["id"] for e in els}
        # An id the agent generates is agent-owned even when `customData` is gone: a save
        # from inside the browser can strip it, and re-adopting those as "yours" is how a
        # previous redraw's arrows survive into the next one and read as duplicates.
        yours = [e for e in live(existing["elements"])
                 if not agent_data(e)
                 and not AGENT_ID.match(str(e.get("id", "")))
                 and e["id"] not in mine
                 and not (e.get("containerId") in mine)]
        els += yours
    scene["elements"] = els
    scene["source"] = SOURCE
    save(board, scene)
    ack(board, scene)
    n = len(spec.get("nodes") or [])
    print(f"wrote {board}: {n} boxes, {len(spec.get('edges') or [])} arrows, {len(spec.get('notes') or [])} notes")
    return 0


def cmd_serve(a, rest) -> int:
    srv = HERE / "draw_server.py"
    return subprocess.call([sys.executable, str(srv), a.board] + rest)


EXAMPLE = {
    "title": "How a skill and its agents reach a session",
    "question": "what does ./workflow/install.sh actually write, and where?",
    "mode": "as-is",
    "lanes": [{"id": "repo", "label": "~/spiral — the source of truth"},
              {"id": "home", "label": "~/.claude — what a session reads"}],
    "nodes": [
        {"id": "install", "label": "install.sh", "at": "workflow/install.sh:36", "lane": "repo"},
        {"id": "settings", "label": "settings.json", "at": "", "kind": "external", "shape": "store", "lane": "home"},
    ],
    "edges": [{"from": "install", "to": "settings", "label": "merges two hook entries", "when": "install"}],
    "notes": [{"text": "a .bak is written on every run", "near": "settings"}],
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="spec.json → a fresh board (keeps positions if the board exists)")
    p.add_argument("spec")
    p.add_argument("board")
    p.add_argument("--repo", help="verify every node's path:line under this directory")
    p.add_argument("--link-prefix", help="e.g. vscode://file/abs/repo/ — boxes become clickable")
    p.add_argument("--allow-big", action="store_true")
    p.add_argument("--fresh-layout", action="store_true", help="ignore positions in the existing board")
    p.add_argument("--keep-yours", action="store_true", help="carry the user's own elements over from the existing board")

    for name in ("describe", "diff", "ack"):
        p = sub.add_parser(name)
        p.add_argument("board")

    p = sub.add_parser("add")
    ps = p.add_subparsers(dest="what", required=True)
    b = ps.add_parser("box")
    b.add_argument("board")
    b.add_argument("--label", required=True)
    b.add_argument("--at", default="")
    b.add_argument("--kind", default="unchanged", choices=list(KINDS))
    b.add_argument("--shape", choices=list(SHAPES), help="default: from --role, else box")
    b.add_argument("--role", choices=list(ROLES), help="system level: what kind of part it is")
    b.add_argument("--near")
    b.add_argument("--lane")
    b.add_argument("--step", type=int)
    b.add_argument("--key")
    b.add_argument("--tech", default="", help="C4 technology line, rendered in brackets")
    b.add_argument("--covers", nargs="*", help="path globs this box stands for")
    r = ps.add_parser("arrow")
    r.add_argument("board")
    r.add_argument("--from", dest="src", required=True)
    r.add_argument("--to", dest="dst", required=True)
    r.add_argument("--label", default="")
    r.add_argument("--when")
    r.add_argument("--kind", default="unchanged", choices=list(EDGE_KINDS))
    r.add_argument("--via", choices=list(VIAS), help="system level: does the sender wait (call) or not (message)")
    r.add_argument("--on-fail", dest="on_fail", help="what happens when the receiver is slow or down")
    n = ps.add_parser("note")
    n.add_argument("board")
    n.add_argument("--text", required=True)
    n.add_argument("--near", required=True)
    n.add_argument("--as", dest="as_", default="answer", choices=list(NOTE_KINDS))

    p = sub.add_parser("set")
    p.add_argument("board")
    p.add_argument("ref")
    p.add_argument("--kind", choices=list(KINDS))
    p.add_argument("--label")
    p.add_argument("--at")
    p.add_argument("--step", type=int)
    p.add_argument("--text")
    p.add_argument("--tech", help="C4 technology line, rendered in brackets")
    p.add_argument("--role", choices=list(ROLES), help="system level: what kind of part it is")
    p.add_argument("--covers", nargs="*", help="path globs this box stands for (review maps files through them)")

    p = sub.add_parser("rm")
    p.add_argument("board")
    p.add_argument("refs", nargs="+")

    p = sub.add_parser("check")
    p.add_argument("board")
    p.add_argument("--repo")

    p = sub.add_parser("review", help="did a change touch what the plan board said? recoloured copy + verdict")
    p.add_argument("board", help="the plan board (read only)")
    p.add_argument("--repo", required=True)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--files", nargs="*", help="review these paths instead of a git range")
    p.add_argument("--ignore", nargs="*", help="extra path globs no box has to account for")
    p.add_argument("--list-ignores", action="store_true", help="print the default ignore globs and exit")
    p.add_argument("--no-default-ignores", action="store_true",
                   help="ask the board to account for lockfiles and generated files too")
    p.add_argument("--system", help="also lift onto this system board (writes <name>.review.excalidraw)")
    p.add_argument("--out", help="where to write the review board (default: <plan>.review.excalidraw)")

    p = sub.add_parser("phase", help="mark a phase built; its boxes join the as-is picture")
    p.add_argument("board")
    p.add_argument("--built", type=int, nargs="+", required=True, metavar="N", help="build-order step numbers that shipped")

    p = sub.add_parser("serve", help="open the board in the browser; extra args go to draw_server.py")
    p.add_argument("board")

    p = sub.add_parser("example", help="print an example spec.json")

    a, rest = ap.parse_known_args(argv)
    if a.cmd == "example":
        print(json.dumps(EXAMPLE, indent=2))
        return 0
    if a.cmd == "serve":
        return cmd_serve(a, rest)
    if rest:
        ap.error("unrecognised arguments: " + " ".join(rest))
    if a.cmd == "new":
        return cmd_new(a)
    board = Path(a.board)
    if a.cmd in ("describe", "diff", "ack"):
        if not board.exists():
            raise SystemExit(f"draw: no board at {board}")
        scene = load(board)
        if a.cmd == "describe":
            print(describe(scene, board))
            ack(board, scene)
        elif a.cmd == "diff":
            print(diff(board, scene))
            ack(board, scene)
        else:
            ack(board, scene)
            print("ok")
        return 0
    if a.cmd == "add":
        return cmd_add(a)
    if a.cmd == "set":
        return cmd_set(a)
    if a.cmd == "rm":
        return cmd_rm(a)
    if a.cmd == "check":
        return cmd_check(a)
    if a.cmd == "phase":
        return cmd_phase(a)
    if a.cmd == "review":
        return cmd_review(a)
    return 2


if __name__ == "__main__":
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass
    sys.exit(main())
