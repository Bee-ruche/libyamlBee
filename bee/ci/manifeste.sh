#!/usr/bin/env bash
# Étape 1 de la CI Bee : manifeste et taille.
#
# 1. Lit la tâche que désigne CONTRIBUTION.yaml (donnée de la PR) et la retrouve dans le registre.
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

statut=0
"$py" "$ICI/tache.py" --manifeste "$pr/CONTRIBUTION.yaml" --registre "$registre" --sortie "$sortie" > "$infos" || statut=$?
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
