#!/usr/bin/env bash
# Exécute une étape de la CI Bee et note son résultat pour verdict.py.
#
# Usage : bee/ci/etape.sh <dossier_etats> <etape> <commande> [arguments...]
# Écrit <dossier_etats>/<etape>.txt : « succes » si la commande réussit, « echec » sinon.
# Le fichier vaut « echec » dès le départ : une étape interrompue (délai, annulation) compte comme un échec.
# Le code de sortie est celui de la commande.
set -uo pipefail

if [ $# -lt 3 ]; then
  echo "usage : $0 <dossier_etats> <etape> <commande> [arguments...]" >&2
  exit 2
fi
dossier="$1"
etape="$2"
shift 2
case "$etape" in
  *[!a-z0-9_]*|"") echo "nom d'étape invalide : $etape" >&2; exit 2 ;;
esac

mkdir -p "$dossier"
echo "echec" > "$dossier/$etape.txt"
echo "== étape $etape : $*"
"$@"
code=$?
if [ "$code" -eq 0 ]; then
  echo "succes" > "$dossier/$etape.txt"
  echo "== étape $etape : réussie"
else
  echo "echec" > "$dossier/$etape.txt"
  echo "== étape $etape : ÉCHEC (code $code)" >&2
fi
exit "$code"
