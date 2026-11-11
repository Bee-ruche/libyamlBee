#!/usr/bin/env bash
# Bee fuzzing for libyaml: fuzz_parse harness (parser, arbitrary input, ASan + UBSan).
#
# Usage:
#   bee/fuzz/lancer.sh <seconds> [--source FOLDER] [--reference FOLDER] [--moteur auto|libfuzzer|gcc]
#   --source     libyaml sources to fuzz (default: the repository's root; the CI passes the PR's sources)
#   --reference  reference libyaml sources (the CI passes the PR's base). The harness becomes
#                differential: each input is parsed by both, and the event stream and the
#                error status must be identical. Each faulty input is replayed on the
#                reference alone: if it fails there too, the discrepancy is PRE-EXISTING (reported, does not
#                count against the PR); otherwise, or without --reference, it is NEW.
#   --moteur     libfuzzer: clang -fsanitize=fuzzer,address,undefined (libclang-rt runtime required);
#                gcc:       fallback, gcc ASan/UBSan and the random driver bee/fuzz/pilote_aleatoire.c;
#                auto:      libfuzzer if clang can link -fsanitize=fuzzer, otherwise gcc (default).
# Builds directly (no make); the reference copy is renamed ref_* at build time.
# Variables: CLANG (default clang), CC (default cc), BEE_FUZZ_SORTIES (log and faulty inputs,
#            default bee/fuzz/sorties), BEE_CONSTR (build), BEE_FUZZ_DISCRET (1: no log,
#            trace or input shown, only their fingerprint; 1 by default under GitHub Actions).
# Exit code: 0 if no new discrepancy, 1 otherwise (inputs in BEE_FUZZ_SORTIES, to keep to yourself:
#            the registry's docs/security.md), 2 on incorrect usage.
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
    *) echo "unknown option: $1" >&2; exit 2 ;;
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
    echo "lancer.sh: $CLANG cannot link -fsanitize=fuzzer: falling back to gcc + ASan/UBSan and the random driver (no coverage)."
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
  *) echo "unknown engine: $moteur" >&2; exit 2 ;;
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

echo "== Corpus and seeds"
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

echo "== Build ($moteur, sources: $source_yaml${reference:+, reference: $reference})"
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

echo "== Fuzzing: fuzz_parse, $duree s"
journal="$sorties/fuzz_parse.log"
mkdir -p "$constr/corpus-fuzz_parse"
statut=0
"$constr/fuzz_parse" -max_total_time="$duree" -max_len=65536 -rss_limit_mb=2048 -timeout=25 -print_final_stats=1 \
  -artifact_prefix="$sorties/fuzz_parse/" "$constr/corpus-fuzz_parse" "$constr/graines" > "$journal" 2>&1 || statut=$?

signaler() {
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::$1::$2"; else echo "$2" >&2; fi
}

if [ "$statut" -eq 0 ]; then
  echo "-- fuzz_parse: no discrepancy. $(grep -E 'stat::number_of_executed_units|driver: done' "$journal" | tail -1)"
  exit 0
fi
echo "-- fuzz_parse: the harness failed (code $statut)."
if [ "$discret" != "1" ]; then
  echo "   End of the log $journal:" >&2
  tail -40 "$journal" >&2
fi
mapfile -t fautives < <(find "$sorties/fuzz_parse" -maxdepth 1 -type f \( -name 'crash-*' -o -name 'leak-*' -o -name 'timeout-*' -o -name 'oom-*' \) | sort)
if [ "${#fautives[@]}" -eq 0 ]; then
  signaler error "fuzz_parse: failure without a faulty input (see the log locally); counted as a new discrepancy."
  exit 1
fi
nouveau=0
for f in "${fautives[@]}"; do
  empreinte="$(sha256sum "$f" | cut -c1-16)"
  taille="$(stat -c %s "$f")"
  bac="$(mktemp -d)"
  # -max_total_time=0 : le pilote rejoue les fichiers puis s'arrête ; libFuzzer exécute le fichier une fois.
  if [ -n "$reference" ] && ! "$constr/rejeu-reference" -max_total_time=0 -rss_limit_mb=2048 -timeout=25 -artifact_prefix="$bac/" "$f" >/dev/null 2>&1; then
    signaler warning "fuzz_parse: PRE-EXISTING discrepancy (the input also fails on the reference), input sha256:$empreinte… ($taille bytes). It does not count against the PR; report it privately to the council (the registry's docs/security.md)."
  else
    nouveau=1
    precision=""
    [ -n "$reference" ] && precision=" (the input passes on the reference)"
    signaler error "fuzz_parse: NEW discrepancy$precision, input sha256:$empreinte… ($taille bytes). Reproduce it in your sandbox; publish neither the input nor the trace (the registry's docs/security.md)."
  fi
  rm -rf "$bac"
done
if [ "$discret" = "1" ]; then
  echo "   Discreet mode: no log, trace or input published. Inputs kept in $sorties/fuzz_parse/ on the machine that fuzzed."
else
  echo "   Faulty inputs: ${fautives[*]}" >&2
fi
exit "$nouveau"
