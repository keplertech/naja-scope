#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail CI when a runner label resolves to an unexpected CPU architecture."""

from __future__ import annotations

import platform
import sys


ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}


def canonical_architecture(value: str) -> str:
    """Normalize the architecture names used by Python and GitHub runners."""
    normalized = value.strip().lower()
    return ALIASES.get(normalized, normalized)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <expected-architecture>", file=sys.stderr)
        return 2

    expected = canonical_architecture(sys.argv[1])
    reported = platform.machine()
    actual = canonical_architecture(reported)
    if actual != expected:
        print(
            f"architecture mismatch: expected {expected}, "
            f"platform.machine() reported {reported!r} ({actual})",
            file=sys.stderr,
        )
        return 1

    print(f"verified native architecture: {reported} ({actual})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
