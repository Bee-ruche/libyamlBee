#!/usr/bin/env bash
# Fuzzing Bee pour libyaml : harnais fuzz_parse (analyseur, entrée arbitraire, ASan + UBSan).
#
# Usage :
#   bee/fuzz/lancer.sh <secondes> [--source DOSSIER] [--reference DOSSIER] [--moteur auto|libfuzzer|gcc]
#   --source     sources de libyaml à fuzzer (défaut : la racine du dépôt ; la CI passe les sources de la PR)
#   --reference  sources de libyaml de référence (la CI passe la base de la PR). Le harnais devient
#                différentiel : chaque entrée est analysée par les deux, et le flux d'événements comme le
#                statut d'erreur doivent être identiques. Chaque entrée fautive est rejouée sur la
#                référence seule : si elle y échoue aussi, l'écart est PRÉEXISTANT (signalé, ne compte pas
#                contre la PR) ; sinon, ou sans --reference, il est NOUVEAU.
#   --moteur     libfuzzer : clang -fsanitize=fuzzer,address,undefined (runtime libclang-rt requis) ;
#                gcc       : repli, gcc ASan/UBSan et le pilote aléatoire bee/fuzz/pilote_aleatoire.c ;
#                auto      : libfuzzer si clang sait lier -fsanitize=fuzzer, sinon gcc (défaut).
# Compile directement (pas de make) ; la copie de référence est renommée ref_* dès la compilation.
# Variables : CLANG (défaut clang), CC (défaut cc), BEE_FUZZ_SORTIES (journal et entrées fautives,
#             défaut bee/fuzz/sorties), BEE_CONSTR (construction), BEE_FUZZ_DISCRET (1 : ni journal,
#             ni trace, ni entrée affichés, seulement leur empreinte ; 1 par défaut sous GitHub Actions).
# Code de sortie : 0 si aucun écart nouveau, 1 sinon (entrées dans BEE_FUZZ_SORTIES, à garder pour soi :
#                  docs/securite.md du registre), 2 en cas d'usage incorrect.
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEE="$(dirname "$ICI")"
RACINE="$(dirname "$BEE")"

if [ $# -lt 1 ] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  sed -n '2,22p' "$0"
  exit 2
fi
duree="$1"
shift
source_yaml="$RACINE"
reference=""
moteur="auto"
while [ $# -gt 0 ]; do
  case "$1" in
    --source) source_yaml="$(cd "$2" && pwd)"; shift ;;
    --reference) reference="$(cd "$2" && pwd)"; shift ;;
    --moteur) moteur="$2"; shift ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
  shift
done

CLANG="${CLANG:-clang}"
CC="${CC:-cc}"
sorties="${BEE_FUZZ_SORTIES:-$ICI/sorties}"
constr="${BEE_CONSTR:-$BEE/construction/fuzz}"
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then discret="${BEE_FUZZ_DISCRET:-1}"; else discret="${BEE_FUZZ_DISCRET:-0}"; fi

if [ "$moteur" = "auto" ]; then
  essai="$(mktemp -d)"
  printf '#include <stdint.h>\n#include <stddef.h>\nint LLVMFuzzerTestOneInput(const uint8_t *d, size_t n) { (void)d; (void)n; return 0; }\n' > "$essai/essai.c"
  if "$CLANG" -fsanitize=fuzzer,address,undefined "$essai/essai.c" -o "$essai/essai" >/dev/null 2>&1; then
    moteur="libfuzzer"
  else
    moteur="gcc"
    echo "lancer.sh : $CLANG ne sait pas lier -fsanitize=fuzzer : repli sur gcc + ASan/UBSan et le pilote aléatoire (sans couverture)."
  fi
  rm -rf "$essai"
fi
DRAPEAUX=(-g -O1 -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all -std=gnu99 -D_GNU_SOURCE
          -DYAML_DECLARE_STATIC -DYAML_VERSION_MAJOR=0 -DYAML_VERSION_MINOR=2 -DYAML_VERSION_PATCH=5 '-DYAML_VERSION_STRING="0.2.5"')
case "$moteur" in
  libfuzzer) compilateur="$CLANG"; couverture=(-fsanitize=fuzzer-no-link); edition=(-fsanitize=fuzzer); pilote=() ;;
  gcc) compilateur="$CC"; couverture=(); edition=(); pilote=("$ICI/pilote_aleatoire.c")
       # Le pilote sauve l'entrée fautive sur SIGABRT : ASan et UBSan doivent avorter, pas sortir.
       export ASAN_OPTIONS="${ASAN_OPTIONS:-abort_on_error=1}" UBSAN_OPTIONS="${UBSAN_OPTIONS:-abort_on_error=1:print_stacktrace=1}" ;;
  *) echo "moteur inconnu : $moteur" >&2; exit 2 ;;
esac
constr="$constr/$moteur"
rm -rf "$constr" "$sorties/fuzz_parse"
mkdir -p "$constr" "$sorties/fuzz_parse"

# objets <sources libyaml> <dossier> [options…] : libyaml + fuzz_parse.c en .o, avec les options données
# (-D…, -include…) pour chaque fichier.
objets() {
  local src="$1" dossier="$2" f
  shift 2
  mkdir -p "$dossier"
  for f in "$src"/src/*.c; do
    "$compilateur" "${DRAPEAUX[@]}" "${couverture[@]}" -I"$src/include" "$@" -c "$f" -o "$dossier/$(basename "$f" .c).o"
  done
  "$compilateur" "${DRAPEAUX[@]}" "${couverture[@]}" -I"$src/include" "$@" -c "$ICI/fuzz_parse.c" -o "$dossier/fuzz_parse.o"
}
lier() { local sortie="$1"; shift; "$compilateur" "${DRAPEAUX[@]}" "${edition[@]}" "$@" "${pilote[@]}" -o "$sortie"; }

echo "== Corpus et graines"
python3 "$BEE/corpus/generer.py" >/dev/null
# Graines : chaque fichier du corpus (64 Kio au plus), lu d'un coup (octet 0) et par morceaux de 7 octets ;
# plus quelques documents en UTF-16 (LE et BE, avec BOM) pour le décodeur du lecteur.
python3 - "$BEE/corpus/donnees" "$constr/graines" <<'FIN'
import pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for i, f in enumerate(sorted(src.glob("*.yaml"))):
    d = f.read_bytes()[:65535]
    (dst / f"{f.stem}-0").write_bytes(b"\x00" + d)
    (dst / f"{f.stem}-7").write_bytes(b"\x07" + d)
    if len(d) < 4096:
        texte = d.decode("utf-8", "replace")
        (dst / f"{f.stem}-utf16le").write_bytes(b"\x00\xff\xfe" + texte.encode("utf-16-le"))
        (dst / f"{f.stem}-utf16be").write_bytes(b"\x05\xfe\xff" + texte.encode("utf-16-be"))
FIN

echo "== Compilation ($moteur, sources : $source_yaml${reference:+, référence : $reference})"
if [ -n "$reference" ]; then
  objets "$source_yaml" "$constr/candidat"
  objets "$reference" "$constr/reference-seule" -DBEE_SANS_REFERENCE
  lier "$constr/rejeu-reference" "$constr/reference-seule/"*.o
  # Copie de référence : tous ses symboles globaux définis (yaml_*, bee_flux, MAX_NESTING_LEVEL…)
  # deviennent ref_* dès la compilation (un #define par symbole), pour cohabiter avec le candidat dans le
  # même exécutable. Les renommer après coup (objcopy) ne suffit pas avec clang : ASan nomme ses groupes
  # COMDAT d'après les symboles exportés du module, identiques dans les deux copies, et l'éditeur de
  # liens écarte alors ceux de la référence (« defined in discarded section »).
  nm -g --defined-only "$constr/reference-seule/"*.o \
    | awk 'NF == 3 && $3 ~ /^[A-Za-z_][A-Za-z0-9_]*$/ && $3 !~ /^__/ && $3 != "LLVMFuzzerTestOneInput" {print "#define " $3 " ref_" $3}' \
    | sort -u > "$constr/renommage.h"
  objets "$reference" "$constr/reference" -DBEE_FLUX_SEUL -include "$constr/renommage.h"
  lier "$constr/fuzz_parse" "$constr/candidat/"*.o "$constr/reference/"*.o
else
  objets "$source_yaml" "$constr/candidat" -DBEE_SANS_REFERENCE
  lier "$constr/fuzz_parse" "$constr/candidat/"*.o
fi

echo "== Fuzzing : fuzz_parse, $duree s"
journal="$sorties/fuzz_parse.log"
mkdir -p "$constr/corpus-fuzz_parse"
statut=0
"$constr/fuzz_parse" -max_total_time="$duree" -max_len=65536 -rss_limit_mb=2048 -timeout=25 -print_final_stats=1 \
  -artifact_prefix="$sorties/fuzz_parse/" "$constr/corpus-fuzz_parse" "$constr/graines" > "$journal" 2>&1 || statut=$?

signaler() {
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::$1::$2"; else echo "$2" >&2; fi
}

if [ "$statut" -eq 0 ]; then
  echo "-- fuzz_parse : aucun écart. $(grep -E 'stat::number_of_executed_units|pilote : terminé' "$journal" | tail -1)"
  exit 0
fi
echo "-- fuzz_parse : le harnais a échoué (code $statut)."
if [ "$discret" != "1" ]; then
  echo "   Fin du journal $journal :" >&2
  tail -40 "$journal" >&2
fi
mapfile -t fautives < <(find "$sorties/fuzz_parse" -maxdepth 1 -type f \( -name 'crash-*' -o -name 'leak-*' -o -name 'timeout-*' -o -name 'oom-*' \) | sort)
if [ "${#fautives[@]}" -eq 0 ]; then
  signaler error "fuzz_parse : échec sans entrée fautive (voir le journal en local) ; compté comme écart nouveau."
  exit 1
fi
nouveau=0
for f in "${fautives[@]}"; do
  empreinte="$(sha256sum "$f" | cut -c1-16)"
  taille="$(stat -c %s "$f")"
  bac="$(mktemp -d)"
  # -max_total_time=0 : le pilote rejoue les fichiers puis s'arrête ; libFuzzer exécute le fichier une fois.
  if [ -n "$reference" ] && ! "$constr/rejeu-reference" -max_total_time=0 -rss_limit_mb=2048 -timeout=25 -artifact_prefix="$bac/" "$f" >/dev/null 2>&1; then
    signaler warning "fuzz_parse : écart PRÉEXISTANT (l'entrée échoue aussi sur la référence), entrée sha256:$empreinte… ($taille octets). Il ne compte pas contre la PR ; à signaler en privé au conseil (docs/securite.md du registre)."
  else
    nouveau=1
    precision=""
    [ -n "$reference" ] && precision=" (l'entrée passe sur la référence)"
    signaler error "fuzz_parse : écart NOUVEAU$precision, entrée sha256:$empreinte… ($taille octets). Reproduisez-le dans votre sandbox ; ne publiez ni l'entrée ni la trace (docs/securite.md du registre)."
  fi
  rm -rf "$bac"
done
if [ "$discret" = "1" ]; then
  echo "   Mode discret : ni journal, ni trace, ni entrée publiés. Entrées gardées dans $sorties/fuzz_parse/ sur la machine qui a fuzzé."
else
  echo "   Entrées fautives : ${fautives[*]}" >&2
fi
exit "$nouveau"
