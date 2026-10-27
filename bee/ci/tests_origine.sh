#!/usr/bin/env bash
# Compile libyaml avec son propre CMakeLists.txt et lance ses tests d'origine (ctest). Ce sont les commandes de la CI Bee, à rejouer telles quelles en local.
#
# Usage : bee/ci/tests_origine.sh <sources_libyaml> [dossier_construction]
set -euo pipefail

source_libyaml="$(cd "$1" && pwd)"
constr="${2:-$(mktemp -d)}"
cmake -S "$source_libyaml" -B "$constr" -DCMAKE_BUILD_TYPE=Release
cmake --build "$constr" -j "$(nproc)"
ctest --test-dir "$constr" --output-on-failure
