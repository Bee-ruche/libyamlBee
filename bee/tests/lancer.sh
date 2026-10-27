#!/usr/bin/env bash
# Tests Bee pour libyaml : déterminisme du flux d'événements.
#
# Pour chaque fichier du corpus de référence, l'oracle (bee/tests/oracle.c) analyse le fichier et
# écrit le flux d'événements canonique. On en prend l'empreinte SHA-256 et le statut (succès / échec
# d'analyse), et on compare à bee/tests/empreintes-reference.txt, figé à la révision de base. Une
# optimisation ne doit changer NI le flux, NI le statut d'aucun fichier.
#
# Usage :
#   bee/tests/lancer.sh                      construit l'oracle, génère le corpus, compare aux empreintes
#   bee/tests/lancer.sh --sans-empreintes    n'exige pas l'égalité des empreintes (tâche autorisée à changer la sortie)
#   bee/tests/lancer.sh --regenerer-empreintes   réécrit empreintes-reference.txt (révision de base seulement)
# Variables : SOURCE (sources de libyaml, défaut racine du dépôt), CC, BEE_CONSTR.
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"
SOURCE="${SOURCE:-$RACINE}"
CONSTR="${BEE_CONSTR:-$BEE/construction/tests}"
REFERENCE="$ICI/empreintes-reference.txt"

mode="comparer"
for arg in "$@"; do
  case "$arg" in
    --sans-empreintes) mode="sans" ;;
    --regenerer-empreintes) mode="regenerer" ;;
    *) echo "option inconnue : $arg" >&2; exit 2 ;;
  esac
done

echo "== 1/3 Corpus de référence"
python3 "$BEE/corpus/generer.py" || exit 1

echo "== 2/3 Compilation de l'oracle (sources : $SOURCE)"
make --no-print-directory -s -C "$BEE" SOURCE="$SOURCE" CONSTR="$CONSTR" oracle || exit 1
oracle="$CONSTR/oracle"

echo "== 3/3 Analyse du corpus et empreintes"
donnees="$BEE/corpus/donnees"
tmp="$(mktemp)"
for f in "$donnees"/*.yaml; do
  nom="$(basename "$f")"
  flux="$("$oracle" "$f" 2>/dev/null)"
  statut=$?
  somme="$(printf '%s' "$flux" | sha256sum | cut -d' ' -f1)"
  etat="ok"; [ "$statut" -ne 0 ] && etat="err"
  printf '%s  %s  %s\n' "$somme" "$etat" "$nom" >> "$tmp"
done
sort -k3 "$tmp" -o "$tmp"

if [ "$mode" = "regenerer" ]; then
  { echo "# Empreintes du flux d'événements de l'oracle Bee pour libyaml (bee/tests/lancer.sh)."
    echo "# <sha256 du flux>  <ok|err>  <fichier>. Figées à la révision de base."
    cat "$tmp"
  } > "$REFERENCE"
  n="$(wc -l < "$tmp")"
  rm -f "$tmp"
  echo "empreintes-reference.txt réécrit : $n fichiers."
  exit 0
fi

total="$(wc -l < "$tmp")"
if [ "$mode" = "sans" ]; then
  rm -f "$tmp"
  echo "RÉSULTAT : OK (mode --sans-empreintes), $total fichiers analysés, empreintes non vérifiées."
  exit 0
fi

if [ ! -f "$REFERENCE" ]; then
  echo "empreintes-reference.txt manquant : lancez --regenerer-empreintes sur la base." >&2
  rm -f "$tmp"; exit 2
fi
attendu="$(grep -v '^#' "$REFERENCE" | sort -k3)"
obtenu="$(cat "$tmp")"
rm -f "$tmp"
if [ "$attendu" = "$obtenu" ]; then
  echo "Déterminisme : $total flux d'événements identiques à la référence."
  echo "RÉSULTAT : OK, l'analyse est inchangée sur tout le corpus."
  exit 0
else
  echo "ÉCHEC : le flux d'événements a changé pour :" >&2
  diff <(echo "$attendu") <(echo "$obtenu") | grep '^[<>]' | awk '{print "  "$0}' | head -20 >&2
  echo "C'est interdit sauf si la tâche l'autorise (relancez --sans-empreintes)." >&2
  echo "RÉSULTAT : ÉCHEC." >&2
  exit 1
fi
