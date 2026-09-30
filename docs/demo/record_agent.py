#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record a real Claude Code agent session driving naja-scope.

Runs headless `claude -p` in a single session (one naja-scope MCP server
process, so the loaded design persists across questions), restricted to the
naja-scope MCP tools — no Bash/Read/Grep, so every answer has to come from
naja-scope. Each stream-json event is stamped with its arrival time and
written to docs/demo/agent_session.jsonl, which replay_agent.py renders for
the README GIF.

    python docs/demo/record_agent.py [--model claude-sonnet-5-5]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# Only what replay_agent.py needs is kept: the init event (local paths,
# plugins, memory dirs) and per-message ids are dropped before committing.
KEEP = ("assistant", "user", "result")
RESULT_FIELDS = ("type", "num_turns", "duration_ms", "total_cost_usd")


def scrub(event):
    if event["type"] == "result":
        return {k: event[k] for k in RESULT_FIELDS if k in event}
    return {"type": event["type"],
            "message": {"content": event["message"]["content"]}}


PROMPTS = [
    "Load examples/uart.sv (top uart_top) and tell me what drives tx_o. "
    "Be concise.",
    "Which registers feed the TX state machine's next-state logic? "
    "Be concise.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--mcp", default=os.path.join(ROOT, ".venv", "bin",
                                                  "naja-scope-mcp"))
    ap.add_argument("--out", default=os.path.join(HERE, "agent_session.jsonl"))
    args = ap.parse_args()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"mcpServers": {"naja-scope": {"command": args.mcp}}}, f)
        mcp_config = f.name

    cmd = ["claude", "-p", "--input-format", "stream-json",
           "--output-format", "stream-json", "--verbose",
           "--model", args.model,
           "--mcp-config", mcp_config, "--strict-mcp-config",
           "--allowedTools", "mcp__naja-scope__*",
           "--disallowedTools",
           "Bash,Read,Grep,Glob,Edit,Write,Task,Agent,WebFetch,WebSearch"]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True,
                            env={**os.environ, "EMSDK_QUIET": "1"})
    t0 = time.monotonic()
    with open(args.out, "w") as out:
        for prompt in PROMPTS:
            out.write(json.dumps({"t": round(time.monotonic() - t0, 3),
                                  "type": "prompt", "text": prompt}) + "\n")
            proc.stdin.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": prompt}}) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                event = json.loads(line)
                if event["type"] in KEEP:
                    kept = scrub(event)
                    kept["t"] = round(time.monotonic() - t0, 3)
                    out.write(json.dumps(kept) + "\n")
                if event["type"] == "result":
                    break
        proc.stdin.close()
        proc.wait()
    os.unlink(mcp_config)
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
