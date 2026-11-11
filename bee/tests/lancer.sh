#!/usr/bin/env bash
# Tests Bee pour libyaml : déterminisme du flux d'événements et aller-retour de l'émetteur.
#
# 1. Déterminisme de l'analyse. Pour chaque fichier du corpus de référence, l'oracle
#    (bee/tests/oracle.c) analyse le fichier et écrit le flux d'événements canonique. On en prend
#    l'empreinte SHA-256 et le statut (succès / échec d'analyse), et on compare à
#    bee/tests/empreintes-reference.txt, figé à la révision de base.
# 2. Aller-retour de l'émetteur. bee/tests/aller_retour.c analyse chaque fichier, ré-émet ses
#    événements avec l'émetteur de libyaml, ré-analyse la sortie et exige le même flux d'événements
#    (normalisations tolérées listées en tête de aller_retour.c), sur le corpus et sur les cas
#    intégrés à aller_retour.c (« interne/… » : normalisations, directives, entrées invalides).
#    L'empreinte SHA-256 de la sortie émise et le statut (ok / rejete) sont comparés à
#    bee/tests/empreintes-aller-retour.txt, figé à la révision de base. Un aller-retour en échec fait
#    toujours échouer, même avec --sans-empreintes.
# Une optimisation ne doit changer NI le flux, NI la sortie de l'émetteur, NI le statut d'aucun fichier.
#
# Usage :
#   bee/tests/lancer.sh                      construit les harnais, génère le corpus, compare aux empreintes
#   bee/tests/lancer.sh --sans-empreintes    n'exige pas l'égalité des empreintes (tâche autorisée à changer la sortie)
#   bee/tests/lancer.sh --regenerer-empreintes   réécrit les deux fichiers d'empreintes (révision de base
#                                            seulement ; refusé si un aller-retour échoue)
# Variables : SOURCE (sources de libyaml, défaut racine du dépôt), CC, BEE_CONSTR.
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"
SOURCE="${SOURCE:-$RACINE}"
CONSTR="${BEE_CONSTR:-$BEE/construction/tests}"
REFERENCE="$ICI/empreintes-reference.txt"
REFERENCE_AR="$ICI/empreintes-aller-retour.txt"

mode="comparer"
while [ $# -gt 0 ]; do
  case "$1" in
    --sans-empreintes) mode="sans" ;;
    --regenerer-empreintes) mode="regenerer" ;;
    --source) SOURCE="$(cd "$2" && pwd)"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

echo "== 1/4 Reference corpus"
python3 "$BEE/corpus/generer.py" || exit 1

echo "== 2/4 Building the oracle and the round trip (sources: $SOURCE)"
make --no-print-directory -s -C "$BEE" SOURCE="$SOURCE" CONSTR="$CONSTR" oracle aller-retour || exit 1
oracle="$CONSTR/oracle"

echo "== 3/4 Parsing the corpus, fingerprints"
donnees="$BEE/corpus/donnees"
tmp="$(mktemp)"
tmp_ar="$(mktemp)"
for f in "$donnees"/*.yaml; do
  nom="$(basename "$f")"
  flux="$("$oracle" "$f" 2>/dev/null)"
  statut=$?
  somme="$(printf '%s' "$flux" | sha256sum | cut -d' ' -f1)"
  etat="ok"; [ "$statut" -ne 0 ] && etat="err"
  printf '%s  %s  %s\n' "$somme" "$etat" "$nom" >> "$tmp"
done
sort -k3 "$tmp" -o "$tmp"

echo "== 4/4 Emitter round trip (events → YAML → events)"
"$CONSTR/aller_retour" --internes "$donnees"/*.yaml > "$tmp_ar"
statut_ar=$?
sort -k3 "$tmp_ar" -o "$tmp_ar"

if [ "$mode" = "regenerer" ]; then
  if [ "$statut_ar" -ne 0 ]; then
    echo "Round trip failed (code $statut_ar): no fingerprint rewritten." >&2
    rm -f "$tmp" "$tmp_ar"; exit 1
  fi
  { echo "# Empreintes du flux d'événements de l'oracle Bee pour libyaml (bee/tests/lancer.sh)."
    echo "# <sha256 du flux>  <ok|err>  <fichier>. Figées à la révision de base."
    cat "$tmp"
  } > "$REFERENCE"
  { echo "# Empreintes de la sortie de l'émetteur, aller-retour Bee pour libyaml (bee/tests/aller_retour.c)."
    echo "# <sha256 du YAML ré-émis>  <ok|rejete>  <fichier>. Figées à la révision de base."
    cat "$tmp_ar"
  } > "$REFERENCE_AR"
  n="$(wc -l < "$tmp")"
  n_ar="$(wc -l < "$tmp_ar")"
  rm -f "$tmp" "$tmp_ar"
  echo "empreintes-reference.txt ($n files) and empreintes-aller-retour.txt ($n_ar documents) rewritten."
  exit 0
fi

total="$(wc -l < "$tmp")"
total_ar="$(wc -l < "$tmp_ar")"
if [ "$mode" = "sans" ]; then
  rm -f "$tmp" "$tmp_ar"
  if [ "$statut_ar" -ne 0 ]; then
    echo "RESULT: FAILED, the emitter round trip fails (details above)." >&2
    exit 1
  fi
  echo "RESULT: OK (--sans-empreintes mode), $total files parsed, round trip stable, fingerprints not checked."
  exit 0
fi

if [ ! -f "$REFERENCE" ] || [ ! -f "$REFERENCE_AR" ]; then
  echo "empreintes-reference.txt or empreintes-aller-retour.txt missing: run --regenerer-empreintes on the base." >&2
  rm -f "$tmp" "$tmp_ar"; exit 2
fi
echec=0
attendu="$(grep -v '^#' "$REFERENCE" | sort -k3)"
obtenu="$(cat "$tmp")"
if [ "$attendu" = "$obtenu" ]; then
  echo "Determinism: $total event streams identical to the reference."
else
  echo "FAILED: the event stream changed for:" >&2
  diff <(echo "$attendu") <(echo "$obtenu") | grep '^[<>]' | awk '{print "  "$0}' | head -20 >&2
  echec=1
fi
if [ "$statut_ar" -ne 0 ]; then
  echo "FAILED: the emitter round trip does not read back the same event stream (details above)." >&2
  echec=1
fi
attendu_ar="$(grep -v '^#' "$REFERENCE_AR" | sort -k3)"
obtenu_ar="$(cat "$tmp_ar")"
rm -f "$tmp" "$tmp_ar"
if [ "$attendu_ar" = "$obtenu_ar" ]; then
  echo "Round trip: $total_ar emitter outputs identical to the reference."
else
  echo "FAILED: the emitter output (or the round-trip status) changed for:" >&2
  diff <(echo "$attendu_ar") <(echo "$obtenu_ar") | grep '^[<>]' | awk '{print "  "$0}' | head -20 >&2
  echec=1
fi
if [ "$echec" -eq 0 ]; then
  echo "RESULT: OK, parsing and emitting are unchanged on the whole corpus."
  exit 0
fi
echo "A fingerprint change is forbidden unless the task allows it (rerun with --sans-empreintes);" >&2
echo "a failed round trip never is." >&2
echo "RESULT: FAILED." >&2
exit 1
