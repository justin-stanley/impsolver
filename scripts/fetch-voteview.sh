#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
# Download the Voteview member and vote files used to build rosters and alignment.
# Usage: scripts/fetch-voteview.sh [CONGRESS ...]   (default: 116 119)
# Voteview asks that the data be cited; see DATA.md.
set -euo pipefail
dest="$(cd "$(dirname "$0")/.." && pwd)/data/voteview"
mkdir -p "$dest"
congresses=("$@")
[ ${#congresses[@]} -eq 0 ] && congresses=(116 119)
for c in "${congresses[@]}"; do
  for ch in H S; do
    for kind in votes members; do
      url="https://voteview.com/static/data/out/${kind}/${ch}${c}_${kind}.csv"
      echo "fetching $url"
      curl -sSfL -o "$dest/${ch}${c}_${kind}.csv" "$url"
    done
  done
done
echo "saved to $dest"
