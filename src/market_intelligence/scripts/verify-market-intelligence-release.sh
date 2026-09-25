#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <registry-image@sha256:digest> <full-source-commit> <sha256:digest>" >&2
  exit 2
fi

expected_ref="$1"
expected_revision="$2"
expected_digest="$3"
container_name="${MARKET_INTELLIGENCE_CONTAINER:-ai-market-intelligence}"

if [[ ! "$expected_digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "Expected an immutable sha256 image digest." >&2
  exit 2
fi
case "$expected_ref" in
  *@"$expected_digest") ;;
  *)
    echo "Image reference must end with the supplied @${expected_digest} digest." >&2
    exit 2
    ;;
esac
if [[ ! "$expected_revision" =~ ^[a-f0-9]{40,64}$ ]]; then
  echo "Expected the full source commit hash." >&2
  exit 2
fi

docker inspect "$container_name" >/dev/null
actual_ref="$(docker inspect --format '{{.Config.Image}}' "$container_name")"
image_id="$(docker inspect --format '{{.Image}}' "$container_name")"
actual_revision="$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id")"
repo_digests="$(docker image inspect --format '{{join .RepoDigests "\n"}}' "$image_id")"
actual_digest="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_name" | sed -n 's/^MARKET_INTELLIGENCE_IMAGE_DIGEST=//p' | tail -1)"
health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_name")"

if [ "$actual_ref" != "$expected_ref" ]; then
  printf 'Release ref mismatch: expected %s, running %s\n' "$expected_ref" "$actual_ref" >&2
  exit 1
fi
if [ "$actual_revision" != "$expected_revision" ]; then
  printf 'Source revision mismatch: expected %s, image label %s\n' "$expected_revision" "$actual_revision" >&2
  exit 1
fi
if [ "$actual_digest" != "$expected_digest" ]; then
  printf 'Runtime metadata digest mismatch: expected %s, configured %s\n' "$expected_digest" "${actual_digest:-<empty>}" >&2
  exit 1
fi
if ! grep -Fq "$expected_ref" <<<"$repo_digests"; then
  printf 'The running image has no matching repository digest: %s\n' "$expected_ref" >&2
  exit 1
fi
if [ "$health" != "healthy" ]; then
  printf 'The running service is not healthy (status: %s).\n' "$health" >&2
  exit 1
fi

printf 'release=verified\nimage=%s\ncommit=%s\ndigest=%s\nhealth=%s\n' \
  "$actual_ref" "$actual_revision" "$actual_digest" "$health"
