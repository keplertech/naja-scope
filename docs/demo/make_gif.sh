#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Render docs/demo/agent_session.jsonl (a real agent transcript captured by
# record_agent.py) to docs/demo/naja-scope-demo.gif.
# Requires: asciinema (>=3), agg.
#   python docs/demo/record_agent.py   # optional: re-record (runs Claude)
#   docs/demo/make_gif.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CAST="$(mktemp -t naja-scope-demo).cast"
asciinema rec --overwrite --quiet --window-size 100x34 \
  -c "python3 $HERE/replay_agent.py" "$CAST"
agg --theme monokai --font-size 15 --idle-time-limit 3 --last-frame-duration 4 \
  "$CAST" "$HERE/naja-scope-demo.gif"
rm -f "$CAST"
echo "wrote $HERE/naja-scope-demo.gif"
