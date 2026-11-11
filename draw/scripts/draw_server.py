#!/usr/bin/env python3
"""Local viewer for a shared Excalidraw board — the user draws, the agent draws back.

    python3 draw_server.py board.excalidraw [--port 8766] [--no-open] [--stay] [--vendor DIR]

Serves the real Excalidraw editor at http://127.0.0.1:8766/ on top of ONE file:

  * every edit in the browser is saved to the file (debounced, optimistic: a save whose base
    revision is stale gets the newer file back and merges before retrying);
  * the page long-polls the file's revision, so when the agent writes (draw.py add/set/rm/new)
    the change appears in the open tab, merged element by element by version — the user's
    unsaved strokes survive;
  * "Send to Claude" (or Ctrl/Cmd+Enter in the message box) exports <stem>.png and <stem>.svg
    next to the board, prints ONE JSON line to stdout and exits, so the Claude Code session
    that launched it in the background wakes up and takes its turn. The tab stays open and
    reconnects when the agent restarts the server. --stay keeps serving instead of exiting.

The Excalidraw bundle comes from unpkg (the browser fetches it, so a locked-down VM is fine as
long as the laptop is not), or from a local install when one exists:
    npm install --prefix ~/.cache/spiral/draw @excalidraw/excalidraw@0.17.6 react@18 react-dom@18
    (or --vendor <dir containing node_modules>, or DRAW_VENDOR_DIR)

Standard library only. Binds 127.0.0.1; on a remote VM forward the port (VS Code does it
automatically; otherwise ssh -L 8766:localhost:8766 <vm>).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXCALIDRAW_VERSION = "0.17.6"
CDN = {
    "react": "https://unpkg.com/react@18.3.1/umd/react.production.min.js",
    "react-dom": "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js",
    "excalidraw": f"https://unpkg.com/@excalidraw/excalidraw@{EXCALIDRAW_VERSION}/dist/excalidraw.production.min.js",
    "assets": f"https://unpkg.com/@excalidraw/excalidraw@{EXCALIDRAW_VERSION}/dist/",
}
VENDOR_FILES = {
    "react": "react/umd/react.production.min.js",
    "react-dom": "react-dom/umd/react-dom.production.min.js",
    "excalidraw": "@excalidraw/excalidraw/dist/excalidraw.production.min.js",
}
MIME = {".js": "application/javascript", ".woff2": "font/woff2", ".json": "application/json",
        ".css": "text/css", ".map": "application/json", ".txt": "text/plain", ".svg": "image/svg+xml"}


def find_vendor(explicit: str | None) -> Path | None:
    cands = [explicit, os.environ.get("DRAW_VENDOR_DIR"), os.path.expanduser("~/.cache/spiral/draw")]
    for c in cands:
        if not c:
            continue
        p = Path(c).expanduser()
        nm = p / "node_modules" if (p / "node_modules").exists() else p
        if all((nm / rel).exists() for rel in VENDOR_FILES.values()):
            return nm
    return None


class Board:
    def __init__(self, path: Path, stay: bool):
        self.path = path
        self.stay = stay
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.rev = self._rev()
        self.server = None
        self.pending_exit = None

    def _rev(self) -> str:
        if not self.path.exists():
            return "0"
        return hashlib.sha1(self.path.read_bytes()).hexdigest()[:12]

    def refresh(self) -> str:
        with self.cond:
            r = self._rev()
            if r != self.rev:
                self.rev = r
                self.cond.notify_all()
            return self.rev

    def read(self) -> dict:
        if not self.path.exists():
            return {"type": "excalidraw", "version": 2, "source": "spiral/draw", "elements": [],
                    "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None}, "files": {}}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, scene: dict, base_rev: str | None) -> tuple[bool, str]:
        with self.cond:
            cur = self._rev()
            if base_rev is not None and cur != "0" and base_rev != cur:
                self.rev = cur
                return False, cur
            scene["type"] = "excalidraw"
            scene["version"] = 2
            scene["source"] = "spiral/draw"
            tmp = self.path.with_name("." + self.path.name + ".tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(scene, fh, indent=1)
                fh.write("\n")
            os.replace(tmp, self.path)
            self.rev = self._rev()
            self.cond.notify_all()
            return True, self.rev

    def wait_change(self, since: str, timeout: float) -> str:
        deadline = time.time() + timeout
        with self.cond:
            while self.rev == since:
                left = deadline - time.time()
                if left <= 0:
                    break
                self.cond.wait(min(left, 0.5))
                r = self._rev()
                if r != self.rev:
                    self.rev = r
                    self.cond.notify_all()
            return self.rev

    def exports(self, png_b64: str | None, svg: str | None) -> dict:
        out = {}
        stem = self.path.with_suffix("")
        if png_b64:
            p = stem.with_suffix(".png")
            p.write_bytes(base64.b64decode(png_b64))
            out["png"] = str(p)
        if svg:
            p = stem.with_suffix(".svg")
            p.write_text(svg, encoding="utf-8")
            out["svg"] = str(p)
        return out

    def shutdown_soon(self, delay=0.4):
        def _stop():
            time.sleep(delay)
            if self.server:
                self.server.shutdown()
        threading.Thread(target=_stop, daemon=True).start()


def make_handler(board: Board, page: str, vendor: Path | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            path, _, qs = self.path.partition("?")
            q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            if path == "/":
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif path == "/api/scene":
                rev = board.refresh()
                self._json({"rev": rev, "scene": board.read(), "file": str(board.path)})
            elif path == "/api/poll":
                rev = board.wait_change(q.get("rev", ""), 25)
                self._json({"rev": rev})
            elif path == "/api/status":
                self._json({"rev": board.refresh(), "file": str(board.path), "stay": board.stay})
            elif path.startswith("/vendor/") and vendor:
                rel = path[len("/vendor/"):]
                root = {"react": vendor / "react/umd", "react-dom": vendor / "react-dom/umd",
                        "excalidraw": vendor / "@excalidraw/excalidraw/dist"}
                first, _, rest = rel.partition("/")
                base = root.get(first)
                if not base:
                    return self._send(404, b"no")
                f = (base / rest).resolve()
                if not str(f).startswith(str(base.resolve())) or not f.is_file():
                    return self._send(404, b"no")
                self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = self.path.partition("?")[0]
            b = self._body()
            if path == "/api/save":
                ok, rev = board.write(b.get("scene") or {}, b.get("baseRev"))
                if ok:
                    self._json({"rev": rev})
                else:
                    self._json({"rev": rev, "scene": board.read()}, 409)
            elif path in ("/api/send", "/api/export"):
                files = board.exports(b.get("png"), b.get("svg"))
                rev = board.refresh()
                if path == "/api/send":
                    line = {"file": str(board.path), "event": "send", "note": (b.get("note") or "").strip(),
                            "rev": rev, **files}
                    print(json.dumps(line), flush=True)
                    self._json({"ok": True, "exiting": not board.stay, **files})
                    if not board.stay:
                        board.shutdown_soon()
                else:
                    self._json({"ok": True, **files})
            else:
                self._send(404, b"not found", "text/plain")

    return H


def render_page(board: Board, vendor: Path | None) -> str:
    html = (HERE / "viewer.html").read_text(encoding="utf-8")
    if vendor:
        src = {"react": "/vendor/react/react.production.min.js",
               "react-dom": "/vendor/react-dom/react-dom.production.min.js",
               "excalidraw": "/vendor/excalidraw/excalidraw.production.min.js",
               "assets": "/vendor/excalidraw/"}
    else:
        src = CDN
    return (html.replace("__BOARD_NAME__", board.path.name)
                .replace("__REACT_SRC__", src["react"])
                .replace("__REACT_DOM_SRC__", src["react-dom"])
                .replace("__EXCALIDRAW_SRC__", src["excalidraw"])
                .replace("__ASSET_BASE__", src["assets"])
                .replace("__STAY__", "true" if board.stay else "false"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DRAW_PORT") or 8766))
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="do not try to open a browser")
    ap.add_argument("--stay", action="store_true", help="keep serving after Send instead of exiting")
    ap.add_argument("--vendor", help="dir with node_modules holding @excalidraw/excalidraw, react, react-dom")
    a = ap.parse_args()

    board = Board(Path(a.board).resolve(), a.stay)
    vendor = find_vendor(a.vendor)
    page = render_page(board, vendor)
    try:
        srv = ThreadingHTTPServer((a.bind, a.port), make_handler(board, page, vendor))
    except OSError as ex:
        print(f"draw_server: cannot bind {a.bind}:{a.port} ({ex}); try --port <n>", file=sys.stderr)
        return 2
    board.server = srv
    url = f"http://{a.bind}:{a.port}/"
    print(f"draw_server: {board.path.name} at {url}  ({'local bundle' if vendor else 'excalidraw from unpkg'})"
          f"{'' if a.stay else ' — Send to Claude exits this process'}", file=sys.stderr, flush=True)
    if not a.no_open:
        threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True).start()
    try:
        srv.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
