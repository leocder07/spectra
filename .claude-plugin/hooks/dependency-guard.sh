#!/bin/bash
# dependency-guard.sh — Prevents Clean Architecture layer violations
# PreToolUse hook for Write/Edit operations on src/ files

FILE="$1"

# Only check src/spectra/ files
if [[ ! "$FILE" =~ src/spectra/ ]]; then
    exit 0
fi

# Layer 1: entities/ must not import from spectra subpackages
if [[ "$FILE" =~ src/spectra/entities/ ]]; then
    if grep -qE "from spectra\.(use_cases|adapters|infrastructure)" "$FILE" 2>/dev/null; then
        echo "BLOCKED: entities/ cannot import from use_cases/, adapters/, or infrastructure/"
        echo "Layer 1 depends on NOTHING from spectra package"
        exit 1
    fi
fi

# Layer 2: use_cases/ must not import from adapters/ or infrastructure/
if [[ "$FILE" =~ src/spectra/use_cases/ ]]; then
    if grep -qE "from spectra\.(adapters|infrastructure)" "$FILE" 2>/dev/null; then
        echo "BLOCKED: use_cases/ cannot import from adapters/ or infrastructure/"
        echo "Layer 2 depends ONLY on entities/"
        exit 1
    fi
fi

# Layer 3: adapters/ must not import from infrastructure/
if [[ "$FILE" =~ src/spectra/adapters/ ]]; then
    if grep -qE "from spectra\.infrastructure" "$FILE" 2>/dev/null; then
        echo "BLOCKED: adapters/ cannot import from infrastructure/"
        echo "Layer 3 depends on entities/ and use_cases/ only"
        exit 1
    fi
fi

exit 0
