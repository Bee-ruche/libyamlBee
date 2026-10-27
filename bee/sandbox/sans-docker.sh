#!/usr/bin/env bash
# Sandbox sans Docker, pour Linux (session cloud jetable, VM) : exécute une commande dans le dépôt
#   - sans réseau (espace de noms réseau vide) ;
#   - sans les variables d'environnement de l'utilisateur (env -i : ni jeton, ni proxy) ;
#   - avec un dossier personnel vide (ses fichiers de configuration, ~/.config/gh compris, sont masqués).
# Le dépôt reste lisible et modifiable : c'est là qu'on compile et qu'on mesure. La commande part de
# la racine du dépôt.
#
# Usage : bee/sandbox/sans-docker.sh <commande> [arguments…]
#   ex. bee/sandbox/sans-docker.sh make -C bee differentiel
#       bee/sandbox/sans-docker.sh bash          (session interactive)
#
# Exige les espaces de noms utilisateur (unshare -r). C'est une isolation plus légère qu'une VM ou un
# conteneur, suffisante pour compiler et mesurer le code des projets Bee. Si elle échoue, utilisez
# Docker (bee/README.md).
set -euo pipefail
[ $# -ge 1 ] || { echo "usage : $0 <commande> [arguments…]" >&2; exit 2; }
command -v unshare >/dev/null || { echo "unshare introuvable : utilisez Docker (bee/README.md)." >&2; exit 1; }
depot="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if ! unshare -rmn true 2>/dev/null; then
  echo "Les espaces de noms utilisateur sont refusés sur cette machine : utilisez Docker (bee/README.md)." >&2
  exit 1
fi
exec unshare -rmn --propagation private -- bash -c '
  set -e
  depot="$1"; shift
  vue="$(mktemp -d -t bee-sandbox.XXXXXX)"
  mount --bind "$depot" "$vue"
  mount -t tmpfs tmpfs "$HOME"
  cd "$vue"
  exec env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 TERM="${TERM:-dumb}" "$@"
' bee-sandbox "$depot" "$@"
