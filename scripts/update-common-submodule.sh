#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/update-common-submodule.sh [--commit]

Updates the parent repository's submodules/common gitlink to the current HEAD of
the local common repository, after pushing common to its upstream.

Environment:
  COMMON_REPO           Local common repository path. Default: /home/mental1104/code/common
  COMMON_SUBMODULE_PATH Submodule path in this repository. Default: submodules/common
EOF
}

commit_change=0
for arg in "$@"; do
  case "$arg" in
    --commit)
      commit_change=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
common_repo="${COMMON_REPO:-/home/mental1104/code/common}"
submodule_path="${COMMON_SUBMODULE_PATH:-submodules/common}"
submodule_abs="$repo_root/$submodule_path"

if [ ! -d "$common_repo/.git" ]; then
  echo "common repository not found: $common_repo" >&2
  exit 1
fi

if ! git -C "$repo_root" config -f .gitmodules --get "submodule.$submodule_path.url" >/dev/null; then
  echo "submodule is not registered in .gitmodules: $submodule_path" >&2
  exit 1
fi

if [ -n "$(git -C "$common_repo" status --porcelain)" ]; then
  echo "common repository has uncommitted changes. Commit or stash them first:" >&2
  echo "  $common_repo" >&2
  git -C "$common_repo" status --short >&2
  exit 1
fi

common_branch="$(git -C "$common_repo" branch --show-current)"
if [ -n "$common_branch" ]; then
  if git -C "$common_repo" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    git -C "$common_repo" push
  else
    git -C "$common_repo" push -u origin "$common_branch"
  fi
else
  echo "common repository is in detached HEAD; skipping automatic push." >&2
fi

new_sha="$(git -C "$common_repo" rev-parse HEAD)"
current_sha="$(git -C "$repo_root" rev-parse "HEAD:$submodule_path")"

if [ "$new_sha" = "$current_sha" ]; then
  echo "common submodule is already up to date: $new_sha"
  exit 0
fi

if ! git -C "$repo_root" diff --quiet || ! git -C "$repo_root" diff --cached --quiet; then
  echo "parent repository has uncommitted changes; refusing to update gitlink automatically." >&2
  echo "Commit or stash them, then rerun:" >&2
  echo "  scripts/update-common-submodule.sh --commit" >&2
  exit 1
fi

echo "updating $submodule_path:"
echo "  $current_sha -> $new_sha"

git -C "$repo_root" update-index --no-assume-unchanged "$submodule_path" 2>/dev/null || true

if [ -L "$submodule_abs" ]; then
  git -C "$repo_root" update-index --cacheinfo "160000,$new_sha,$submodule_path"
  git -C "$repo_root" update-index --assume-unchanged "$submodule_path"
else
  if [ ! -d "$submodule_abs/.git" ] && [ ! -f "$submodule_abs/.git" ]; then
    echo "$submodule_path is neither a symlink nor a submodule working tree." >&2
    exit 1
  fi
  git -C "$submodule_abs" fetch origin
  git -C "$submodule_abs" checkout --detach "$new_sha"
  git -C "$repo_root" add "$submodule_path"
fi

if [ "$commit_change" -eq 1 ]; then
  git -C "$repo_root" commit -m "Update common submodule" -- "$submodule_path"
else
  echo "gitlink staged. Commit it with:"
  echo "  git commit -m \"Update common submodule\" -- $submodule_path"
fi
