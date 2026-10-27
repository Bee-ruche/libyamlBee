#!/usr/bin/env bash
# Compile miniz avec son propre CMakeLists.txt (bibliothèque, exemples, tests Catch2) et lance ses
# tests d'origine (ctest). Ce sont les commandes de la CI Bee, à rejouer telles quelles en local.
#
# Usage : bee/ci/tests_origine.sh <sources_miniz> [dossier_construction]
set -euo pipefail

source_miniz="$(cd "$1" && pwd)"
constr="${2:-$(mktemp -d)}"
cmake -S "$source_miniz" -B "$constr" -DCMAKE_BUILD_TYPE=Release
cmake --build "$constr" -j "$(nproc)"
ctest --test-dir "$constr" --output-on-failure
