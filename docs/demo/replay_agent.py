#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay a recorded agent session (agent_session.jsonl) as a terminal render.

Everything shown comes from the transcript captured by record_agent.py: the
user prompts, the agent's own tool calls and arguments, the raw naja-scope
JSON results (collapsed to their first lines, as Claude Code does), and the
agent's answers verbatim. Pacing follows the recorded timestamps. The only
thing hidden is Claude Code's internal ToolSearch step (deferred-tool schema
loading), which is harness plumbing rather than a naja-scope call.
"""

import json
import os
import re
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))

WIDTH = 96
RESULT_LINES = 6

RESET = "\033[0m"
BOLD = "\033[1m"
ORANGE = "\033[38;5;209m"
GREEN = "\033[38;5;114m"
CYAN = "\033[38;5;117m"
GREY = "\033[38;5;245m"


def out(s="", end="\n"):
    sys.stdout.write(s + end)
    sys.stdout.flush()


def md(line):
    """Minimal inline markdown: **bold** and `code`."""
    line = re.sub(r"\*\*(.+?)\*\*", lambda m: BOLD + m.group(1) + RESET, line)
    return re.sub(r"`([^`]+)`", lambda m: CYAN + m.group(1) + RESET, line)


def stream(text, indent, delay=0.012):
    for i, ch in enumerate(text):
        out(ch, end="")
        if ch == " ":
            time.sleep(delay)
    out()


def wrap_paragraphs(text, first, rest):
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        sub = rest + ("  " if para.lstrip().startswith("- ") else "")
        lines.extend(textwrap.wrap(para, WIDTH, initial_indent=first if not lines
                                   else rest, subsequent_indent=sub))
    return lines


def show_prompt(text):
    out(f"{BOLD}{ORANGE}>{RESET} ", end="")
    for ch in text:
        out(ch, end="")
        time.sleep(0.022)
    out()


def show_tool(name, args):
    short = name.replace("mcp__naja-scope__", "")
    arg_s = ", ".join(f"{k}={json.dumps(v)}" for k, v in args.items())
    out(f"\n{GREEN}●{RESET} {BOLD}naja-scope · {short}{RESET}{GREY}({arg_s}){RESET}")


def show_result(content):
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content
                          if isinstance(c, dict))
    lines = content.splitlines()
    for i, line in enumerate(lines[:RESULT_LINES]):
        prefix = "  ⎿  " if i == 0 else "     "
        out(f"{GREY}{prefix}{line[:WIDTH - 5]}{RESET}")
        time.sleep(0.03)
    if len(lines) > RESULT_LINES:
        out(f"{GREY}     … +{len(lines) - RESULT_LINES} lines{RESET}")


def show_text(text):
    out()
    wrapped = wrap_paragraphs(text.strip(), "", "  ")
    for i, line in enumerate(wrapped):
        lead = f"{BOLD}●{RESET} " if i == 0 else ""
        out(lead + md(line), end="")
        out()
        time.sleep(0.12)
    out()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "agent_session.jsonl")
    events = [json.loads(l) for l in open(path)]
    hidden = set()

    out(f"{GREY}# Real Claude Code session · naja-scope MCP tools only "
        f"(no grep, no file reads){RESET}\n")
    time.sleep(1.2)

    last_t = 0.0
    for ev in events:
        # Follow the recorded pacing, capped so model thinking time
        # doesn't turn into dead air in the GIF.
        time.sleep(min(max(ev["t"] - last_t, 0.0), 1.2))
        last_t = ev["t"]
        kind = ev["type"]
        if kind == "prompt":
            show_prompt(ev["text"])
        elif kind == "assistant":
            for c in ev["message"]["content"]:
                if c["type"] == "tool_use":
                    if c["name"].startswith("mcp__naja-scope__"):
                        show_tool(c["name"], c["input"])
                    else:
                        hidden.add(c["id"])
                elif c["type"] == "text" and c["text"].strip():
                    show_text(c["text"])
        elif kind == "user":
            content = ev["message"]["content"]
            for c in content if isinstance(content, list) else []:
                if (isinstance(c, dict) and c.get("type") == "tool_result"
                        and c["tool_use_id"] not in hidden):
                    show_result(c["content"])
        elif kind == "result":
            out(f"{GREY}  ({ev.get('num_turns')} turns · "
                f"{ev.get('duration_ms', 0) / 1000:.1f}s){RESET}\n")
            time.sleep(1.5)

    out(f"{GREY}# pip install naja-scope{RESET}\033[?25l")
    time.sleep(4)


if __name__ == "__main__":
    main()
