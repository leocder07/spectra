#!/bin/bash
# no-any-types.sh — Blocks Any type usage in src/ files
# PreToolUse hook for Write/Edit operations

FILE="$1"

# Only check src/spectra/ files
if [[ ! "$FILE" =~ src/spectra/ ]]; then
    exit 0
fi

# Check for Any type usage
if grep -qE "(from typing import.*\bAny\b|: Any\b|# type: ignore)" "$FILE" 2>/dev/null; then
    echo "BLOCKED: Any type and # type: ignore are forbidden in src/"
    echo "Use specific types, Protocol, or Generic instead"
    exit 1
fi

exit 0
