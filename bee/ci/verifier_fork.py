#!/usr/bin/env python3
"""Runs the Bee registry's tool « bee check-fork » (tools/bee.py of the registry's branch main).

The registry writes English since its switch (ruche-0145): tools/bee.py, the command check-fork and its options --task,
--base, --head, --repo and --author, the global option --registry and the variable BEE_REGISTRY, which is set to the same
registry as the option. A registry without tools/bee.py fails the step, without calling anything.

Usage: python3 bee/ci/verifier_fork.py <registry> --tache T --base B --tete H --depot D [--auteur A]
Exit code: the tool's, or 1 if the registry has no tools/bee.py (message on standard error).
"""

import argparse
import os
import subprocess
import sys

OUTIL = os.path.join("tools", "bee.py")
# Options of this script -> those of bee check-fork.
OPTIONS = {"tache": "--task", "base": "--base", "tete": "--head", "depot": "--repo", "auteur": "--author"}


def echouer(message):
    print(f"::error::verifier_fork.py: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("registre")
    for nom in OPTIONS:
        analyseur.add_argument("--" + nom, required=nom != "auteur")
    args = analyseur.parse_args()

    outil = os.path.join(args.registre, OUTIL)
    if not os.path.isfile(outil):
        echouer(f"the registry has no {OUTIL}: bee check-fork cannot run")
    env = dict(os.environ, BEE_REGISTRY=args.registre)
    voulues = [nom for nom in OPTIONS if getattr(args, nom) is not None]
    appel = [sys.executable, outil, "--registry", args.registre, "check-fork"]
    for nom in voulues:
        appel += [OPTIONS[nom], getattr(args, nom)]
    print(f"Registry tool: {OUTIL} --registry … check-fork ({', '.join(OPTIONS[n] for n in voulues)})", flush=True)
    return subprocess.run(appel, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
