#!/usr/bin/env bash
# Étape 1 de la CI Bee : manifeste et taille.
#
# 1. Trouve le manifeste de la PR : manifestes/<tâche>.yaml, le seul fichier de manifestes/ que la PR ajoute
#    ou modifie (sinon l'ancien CONTRIBUTION.yaml à la racine) ; lit la tâche qu'il désigne (donnée de la
#    PR) et la retrouve dans le registre.
# 2. Lance « bee verifier-fork », l'outil du registre (branche main) : manifeste valide, plafond de
#    lignes modifiées (R1), chemins juges intacts pour une optimisation (commandement 3), aucun binaire.
#
# Usage : bee/ci/manifeste.sh <clone_pr> <clone_registre> [python]
#   python : interpréteur qui a PyYAML et jsonschema (outils/requirements.txt du registre).
# Variables : BASE_SHA et TETE_SHA (obligatoires), AUTEUR (auteur de la PR, facultatif),
#             GITHUB_OUTPUT (facultatif : les valeurs de la tâche y sont ajoutées),
#             BEE_SORTIE_TACHE (copie de la tâche, défaut tache.yaml).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pr="$1"
registre="$2"
py="${3:-python3}"
: "${BASE_SHA:?BASE_SHA manquant}" "${TETE_SHA:?TETE_SHA manquant}"
sortie="${BEE_SORTIE_TACHE:-tache.yaml}"
infos="$(mktemp)"

mapfile -t manifestes < <(git -C "$pr" diff --name-only --no-renames --diff-filter=AM "$BASE_SHA...$TETE_SHA" -- 'manifestes/*')
if [ "${#manifestes[@]}" -gt 1 ]; then
  echo "La PR ajoute ou modifie plusieurs manifestes (${manifestes[*]}) : une PR, une tâche." >&2
  exit 1
fi
manifeste="${manifestes[0]:-CONTRIBUTION.yaml}"
if ! printf '%s' "$manifeste" | grep -Eq '^(manifestes/libyaml-[0-9]{4}\.yaml|CONTRIBUTION\.yaml)$'; then
  echo "Nom de manifeste invalide : manifestes/libyaml-NNNN.yaml attendu." >&2
  exit 1
fi
echo "Manifeste : $manifeste"

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
"$py" "$registre/outils/bee.py" --registre "$registre" verifier-fork --tache "$tache" \
  --base "$BASE_SHA" --tete "$TETE_SHA" --depot "$pr" ${options[@]+"${options[@]}"}
