#!/usr/bin/env bash
# Prépare les juges d'un job de la CI Bee : le dossier bee/ de la base de la PR.
#
# Usage : juges.sh <dossier_base> <dossier_pr> <base_sha>     (variable ETATS : dossier des états)
#
# Cas normal : la base contient bee/, rien ne change ; les juges sont ceux de la base.
# Amorçage : si et seulement si <base_sha> vaut exactement BEE_COMMIT_AMORCAGE (master d'origine du
#   fork, avant tout outillage Bee), bee/ de la PR est copié dans la base. Les juges viennent alors
#   de la PR elle-même ; le journal le signale et <ETATS>/amorcage.txt le note pour verdict.json.
# Tout autre cas sans bee/ dans la base : échec (code 1). Une base sans juges n'est pas acceptée.
# Dans tous les cas, <ETATS>/juges.txt reçoit « succes » ou « echec » (étape « juges » du verdict).
#
# Le workflow .github/workflows/bee-ci.yml contient une copie identique de la logique ci-dessous
# (variable BEE_JUGES, exécutée par l'étape « Juges » de chaque job), car à l'amorçage la base ne
# contient pas encore ce script. bee/ci/test_verdict.py vérifie que les deux copies sont identiques.
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "usage : $0 <dossier_base> <dossier_pr> <base_sha>" >&2
  exit 2
fi
base="$1"
pr="$2"
base_sha="$3"
etats="${ETATS:-etats}"
BEE_COMMIT_AMORCAGE="${BEE_COMMIT_AMORCAGE:-90a56d4500aa1a1798514c5cb55c3ad4cb095f94}"

# --- début de la logique recopiée dans bee-ci.yml ---
mkdir -p "$etats"
if [ -f "$base/bee/ci/etape.sh" ]; then
  echo "Juges : bee/ de la base de la PR ($base_sha)."
  echo "succes" > "$etats/juges.txt"
elif [ "$base_sha" = "$BEE_COMMIT_AMORCAGE" ] && [ -f "$pr/bee/ci/etape.sh" ]; then
  echo "::warning::AMORÇAGE : la base $base_sha (commit d'amorçage épinglé) ne contient pas bee/ ; les juges viennent de la PR elle-même (verdict.json : amorcage: true)."
  rm -rf "$base/bee"
  cp -a "$pr/bee" "$base/bee"
  mkdir -p "$base/.github/workflows"
  cp -a "$pr/.github/workflows/bee-ci.yml" "$base/.github/workflows/bee-ci.yml"
  echo "oui" > "$etats/amorcage.txt"
  echo "succes" > "$etats/juges.txt"
else
  echo "echec" > "$etats/juges.txt"
  echo "::error::La base de la PR ($base_sha) ne contient pas bee/ : pas de juges, CI refusée (seul le commit d'amorçage $BEE_COMMIT_AMORCAGE est accepté sans juges)." >&2
  exit 1
fi
# --- fin de la logique recopiée dans bee-ci.yml ---
