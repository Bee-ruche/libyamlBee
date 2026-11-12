#!/usr/bin/env bash
# Step 1 of the Bee CI: manifest and size.
#
# 1. Finds the PR's manifest: manifests/ or manifestes/<task>.yaml, the only file of these folders that the PR adds or
#    modifies (otherwise the former CONTRIBUTION.yaml at the root); reads the task it names (PR data) and finds it in
#    the registry (tache.py: the registry in English, the manifest in French or in English).
# 2. Runs « bee check-fork » (verifier_fork.py): valid manifest, cap on changed lines (R1), judge paths untouched by an
#    optimization (commandment 3), no binary.
#
# Usage: bee/ci/manifeste.sh <pr_clone> <registry_clone> [python]
#   python: an interpreter that has PyYAML and jsonschema (the registry's tools/requirements.txt).
# Variables: BASE_SHA and TETE_SHA (required), AUTEUR (the PR's author, optional),
#            GITHUB_OUTPUT (optional: the task's values are appended to it),
#            BEE_SORTIE_TACHE (copy of the task, default tache.yaml).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pr="$1"
registre="$2"
py="${3:-python3}"
: "${BASE_SHA:?BASE_SHA missing}" "${TETE_SHA:?TETE_SHA missing}"
sortie="${BEE_SORTIE_TACHE:-tache.yaml}"
infos="$(mktemp)"

mapfile -t manifestes < <(git -C "$pr" diff --name-only --no-renames --diff-filter=AM "$BASE_SHA...$TETE_SHA" -- 'manifests/*' 'manifestes/*')
if [ "${#manifestes[@]}" -gt 1 ]; then
  echo "The PR adds or modifies several manifests (${manifestes[*]}): one PR, one task." >&2
  exit 1
fi
manifeste="${manifestes[0]:-CONTRIBUTION.yaml}"
if ! printf '%s' "$manifeste" | grep -Eq '^(manifests|manifestes)/libyaml-[0-9]{4}\.yaml$|^CONTRIBUTION\.yaml$'; then
  echo "Invalid manifest name: manifests/libyaml-NNNN.yaml (or manifestes/libyaml-NNNN.yaml) expected." >&2
  exit 1
fi
if [ -L "$pr/$manifeste" ] || { [ -e "$pr/$manifeste" ] && [ ! -f "$pr/$manifeste" ]; }; then
  echo "The manifest $manifeste must be a regular file (neither a symbolic link nor a folder)." >&2
  exit 1
fi
echo "Manifest: $manifeste"

statut=0
"$py" "$ICI/tache.py" --manifeste "$pr/$manifeste" --registre "$registre" --sortie "$sortie" > "$infos" || statut=$?
echo "manifeste=$manifeste" >> "$infos"
cat "$infos"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  cat "$infos" >> "$GITHUB_OUTPUT"
fi
[ "$statut" -eq 0 ] || exit "$statut"

tache="$(sed -n 's/^tache=//p' "$infos")"
options=()
if [ -n "${AUTEUR:-}" ]; then
  options+=(--auteur "$AUTEUR")
fi
"$py" "$ICI/verifier_fork.py" "$registre" --tache "$tache" \
  --base "$BASE_SHA" --tete "$TETE_SHA" --depot "$pr" ${options[@]+"${options[@]}"}
