#!/usr/bin/env bash
set -euo pipefail

digest="$(awk '{
  for (i = 1; i < NF; i++) {
    if (tolower($i) == "digest:") digest = $(i + 1)
  }
} END { print digest }')"

if [[ ! "$digest" =~ ^sha256:[[:xdigit:]]{64}$ ]]; then
  printf 'Could not extract a valid SHA-256 digest from docker push output.\n' >&2
  exit 1
fi

printf '%s\n' "$digest"
