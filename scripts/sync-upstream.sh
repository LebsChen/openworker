#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git fetch upstream

if [[ "$(git symbolic-ref --short HEAD)" != "main" ]]; then
  git switch main
fi

git merge --ff-only upstream/main

cat <<'EOF'
Upstream main is synchronized.
Rebase the development branch separately when ready:
  git switch devos
  git rebase upstream/main
EOF
