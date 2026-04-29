#!/usr/bin/env bash
# Defensive PyPI squat registration (Q1 #10).
#
# Reserves the names below on PyPI by publishing a stub package whose
# only content is a README pointing at the real `spectra-ai`. The stub
# source lives in scripts/squat-stub/. SQUAT_NAME is injected per build.
#
# Why: a typo'd `pip install spectraai` (or any of the variants) must
# resolve to a benign no-op, not an attacker-controlled package that
# steals ANTHROPIC_API_KEY at install time.
#
# Manual run (maintainer only):
#   export TWINE_USERNAME=__token__
#   export TWINE_PASSWORD=pypi-AgEIcHl...   # PyPI API token, scoped to upload
#   ./scripts/register_pypi_squats.sh
#
# Re-runs are idempotent for names already owned (twine will refuse to
# overwrite an existing version — that's the desired safety net). To
# republish, bump version in scripts/squat-stub/setup.py.
#
# Verify after upload:
#   pip index versions <squat-name>
#   pip install <squat-name> && cat $(python -c "import pkgutil, os; print(os.path.dirname(pkgutil.get_loader('<squat-name>').get_filename()))")/README.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STUB_DIR="${SCRIPT_DIR}/squat-stub"

# ── Defensive squat names ────────────────────────────────────────────
# Order matters only for log readability. Variants chosen by:
#   1. Common typos of "spectra-ai" / "spectra"
#   2. Naming conventions a user might guess (cli, py, api)
#   3. Tool category words a user might combine (analyzer, code, review)
SQUAT_NAMES=(
  "spectra_ai"        # underscore variant of spectra-ai
  "spectraai"         # no-separator typo
  "spectra-cli"       # likely first guess for the CLI
  "spectra-py"        # python convention
  "spectraapi"        # no-separator + api suffix
  "spectra-analyzer"  # category word
  "spectra-code"      # category word
  "spectra-review"    # category word
)

# ── Pre-flight ───────────────────────────────────────────────────────
if [[ -z "${TWINE_USERNAME:-}" || -z "${TWINE_PASSWORD:-}" ]]; then
  echo "ERROR: TWINE_USERNAME and TWINE_PASSWORD must be set." >&2
  echo "       Use TWINE_USERNAME=__token__ and a scoped PyPI API token." >&2
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python not found on PATH." >&2
  exit 1
fi

# Tooling — installed into a throwaway venv so we don't pollute the host.
VENV_DIR="$(mktemp -d)/squat-venv"
python -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip build twine

# ── Build + upload loop ──────────────────────────────────────────────
cd "$STUB_DIR"
for NAME in "${SQUAT_NAMES[@]}"; do
  echo ""
  echo "▸ ${NAME}: building stub"
  rm -rf build/ dist/ ./*.egg-info
  SQUAT_NAME="$NAME" python -m build --quiet

  echo "▸ ${NAME}: uploading to PyPI"
  # --skip-existing: idempotent re-runs after a name is already reserved.
  if ! twine upload --skip-existing dist/*; then
    echo "✗ ${NAME}: upload failed (see above). Continuing." >&2
    continue
  fi
  echo "✓ ${NAME}: reserved"
done

echo ""
echo "✓ Done. ${#SQUAT_NAMES[@]} names processed."
echo "  Verify any of them at: https://pypi.org/project/<name>/"
