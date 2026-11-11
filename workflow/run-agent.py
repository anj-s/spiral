#!/usr/bin/env python3
"""Render or run one spiral agent on any harness.

The agent sources in ../agents/ are the single source of truth. Claude Code gets them as
generated subagents (gen-agents.py); every other harness gets them through this script:

  run-agent.py <name> --var k=v ...                   # INLINE: print the filled prompt
  run-agent.py <name> --var k=v ... --backend claude  # PROCESS: run it as a fresh CLI process
  run-agent.py <name> --list-inputs                   # which {{inputs}} the prompt needs

Inputs are the {{placeholders}} in the prompt. Every one must be supplied with --var k=v or
--var-file k=path; a missing one exits 2 and names it, so a prompt never ships with a hole.
$SPEC_STORE inside a prompt is expanded (default ~/specs).

Process backends feed the prompt on STDIN and return the agent's stdout; the child's exit code
is this script's exit code. Built in: claude, codex, gemini. Anything else: --cmd '<argv>', with
the prompt on stdin, or containing {prompt_file} to receive it as a path.

The parser is gen-agents.py's parse_source — one parser, so a source that generates also runs.
"""
import argparse
import importlib.util
import os
import re
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


def load_parser():
    spec = importlib.util.spec_from_file_location("gen_agents", os.path.join(HERE, "gen-agents.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_source


def backend_argv(name, model, tools, cmd_template, prompt_file):
    """-> argv list. Prompt goes on stdin unless the template names {prompt_file}."""
    if name == "cmd":
        if not cmd_template:
            raise SystemExit("run-agent: --backend cmd needs --cmd '<argv>'")
        return [a.replace("{prompt_file}", prompt_file) for a in shlex.split(cmd_template)]
    if name == "claude":
        argv = ["claude", "-p", "--model", model]
        if tools:
            argv += ["--allowedTools"] + tools
        return argv
    if name == "codex":
        return ["codex", "exec", "-"]  # `-` = read the prompt from stdin
    if name == "gemini":
        return ["gemini"]  # piped stdin runs non-interactively
    raise SystemExit(f"run-agent: unknown backend {name!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="agent name, e.g. spec-code-reader")
    ap.add_argument("--var", action="append", default=[], metavar="K=V", help="fill {{K}} with V")
    ap.add_argument("--var-file", action="append", default=[], metavar="K=PATH", help="fill {{K}} with PATH's contents")
    ap.add_argument("--list-inputs", action="store_true", help="print the prompt's inputs and exit")
    ap.add_argument("--allow-missing", action="store_true", help="leave unfilled {{inputs}} in place instead of failing")
    ap.add_argument("--backend", default="inline", choices=["inline", "claude", "codex", "gemini", "cmd"])
    ap.add_argument("--cmd", default=None, help="argv template for --backend cmd; {prompt_file} receives the prompt path")
    ap.add_argument("--model", default=None, help="override the agent's **model:** hint")
    ap.add_argument("--no-tools", action="store_true", help="do not pass the agent's **tools:** to the backend")
    ap.add_argument("--out", default=None, help="also write the output (or the rendered prompt) here")
    ap.add_argument("--timeout", type=float, default=0, help="seconds before the backend is killed (0 = none)")
    ap.add_argument("--agents-dir", default=os.environ.get("ANJ_AGENTS_DIR") or os.path.join(HERE, "..", "agents"))
    a = ap.parse_args()

    src = os.path.join(a.agents_dir, f"{a.name}.md")
    if not os.path.isfile(src):
        print(f"run-agent: no agent source {src}", file=sys.stderr)
        return 2
    name, _desc, tools, model, prompt = load_parser()(src)
    tools = [t for t in tools.split(", ") if t]
    model = a.model or model

    inputs = sorted(set(PLACEHOLDER.findall(prompt)))
    if a.list_inputs:
        print("\n".join(inputs))
        return 0

    values = {}
    for kv in a.var:
        k, sep, v = kv.partition("=")
        if not sep:
            print(f"run-agent: --var expects K=V, got {kv!r}", file=sys.stderr)
            return 2
        values[k] = v
    for kv in a.var_file:
        k, sep, path = kv.partition("=")
        if not sep:
            print(f"run-agent: --var-file expects K=PATH, got {kv!r}", file=sys.stderr)
            return 2
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            values[k] = fh.read()

    unknown = sorted(set(values) - set(inputs))
    if unknown:
        print(f"run-agent: {name} has no input(s) {', '.join(unknown)}; it takes: {', '.join(inputs)}", file=sys.stderr)
        return 2
    missing = [i for i in inputs if i not in values]
    if missing and not a.allow_missing:
        print(f"run-agent: {name} is missing input(s): {', '.join(missing)}  (use --var K=V or --var-file K=PATH)", file=sys.stderr)
        return 2

    filled = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), prompt)
    store = os.path.expanduser(os.environ.get("SPEC_STORE") or "~/specs")
    filled = filled.replace("$SPEC_STORE", store)
    if not filled.endswith("\n"):
        filled += "\n"  # one canonical form: inline stdout, --out and backend stdin are byte-identical

    if a.backend == "inline":
        sys.stdout.write(filled)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(filled)
        return 0

    with tempfile.NamedTemporaryFile("w", suffix=f"-{name}.prompt.md", delete=False, encoding="utf-8") as tmp:
        tmp.write(filled)
        prompt_file = tmp.name
    try:
        argv = backend_argv(a.backend, model, [] if a.no_tools else tools, a.cmd, prompt_file)
        print(f"run-agent: {name} via {a.backend} — {shlex.join(argv)}  (model hint: {model})", file=sys.stderr)
        try:
            proc = subprocess.run(argv, input=filled, text=True, capture_output=True,
                                  timeout=a.timeout or None)
        except FileNotFoundError:
            print(f"run-agent: backend executable not found: {argv[0]}", file=sys.stderr)
            return 127
        except subprocess.TimeoutExpired:
            print(f"run-agent: {name} via {a.backend} timed out after {a.timeout:g}s", file=sys.stderr)
            return 124
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        sys.stdout.write(proc.stdout)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(proc.stdout)
        return proc.returncode
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # reader closed early (`| head`): not our error, no traceback
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(141)
