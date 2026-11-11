#!/usr/bin/env python3
"""Add or remove the workflow context-injection hooks in a settings.json.

Merges into the existing file: every other key and every hook we did not add is
preserved untouched. Fails loudly on invalid JSON rather than clobbering it.

Usage: merge-settings.py <settings.json> <hook-path> <marker> install|uninstall
"""
import json
import os
import shutil
import sys

EVENTS = ("UserPromptSubmit", "SubagentStart")


def main() -> int:
    settings_path, hook, marker, mode = sys.argv[1:5]
    cmd = f"{hook}  # {marker}"

    settings = {}
    backed_up = False
    if os.path.exists(settings_path):
        shutil.copy2(settings_path, settings_path + ".bak")
        backed_up = True
        with open(settings_path, encoding="utf-8") as fh:
            text = fh.read().strip()
        if text:
            settings = json.loads(text)

    hooks = settings.setdefault("hooks", {})

    for event in EVENTS:
        # Drop only our own entries; anything else stays exactly as it was.
        kept = []
        for group in hooks.get(event, []):
            group = dict(group)
            group["hooks"] = [
                h for h in group.get("hooks", [])
                if marker not in str(h.get("command", ""))
            ]
            if group["hooks"]:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)

        if mode == "install":
            hooks.setdefault(event, []).append(
                {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]}
            )

    if not hooks:
        settings.pop("hooks", None)

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")

    print(f"{mode}ed: {' + '.join(EVENTS)} -> {hook}")
    if backed_up:
        print(f"backup: {settings_path}.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
