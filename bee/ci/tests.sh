#!/usr/bin/env bash
# Étape « déterminisme du flux d'événements » de la CI Bee pour libyaml.
#
# Les juges sont ceux de la base (le dossier bee/ qui contient ce script) : la PR ne peut pas
# assouplir ce qui la juge. Seules les sources de libyaml viennent de la PR (--source). Si la PR
# modifie elle-même bee/ (tâches de type test ou mesure), son propre outillage doit aussi passer sur
# ses propres sources.
#
# Usage : bee/ci/tests.sh <clone_pr>
# Variables : BASE_SHA et TETE_SHA (facultatifs).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
pr="$(cd "$1" && pwd)"

echo "== Outillage de la base, sources de la PR"
"$BEE/tests/lancer.sh" --source "$pr"

if [ -n "${BASE_SHA:-}" ] && [ -n "$(git -C "$pr" diff --name-only "${BASE_SHA}...${TETE_SHA:-HEAD}" -- bee/)" ]; then
  echo "== La PR modifie bee/ : son propre outillage, sur ses propres sources"
  BEE_CONSTR="$pr/bee/construction/tests-pr" "$pr/bee/tests/lancer.sh" --source "$pr"
fi
