#!/bin/zsh
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: ./render_pdf.sh path/to/score.ly"
  exit 1
fi

if ! command -v lilypond >/dev/null 2>&1; then
  echo "Error: lilypond is not installed."
  echo "Install LilyPond, then rerun this script to generate a PDF."
  exit 1
fi

score_file="$1"
export XDG_CACHE_HOME="${PWD}/.cache"
mkdir -p "${XDG_CACHE_HOME}/fontconfig"
lilypond "$score_file"
