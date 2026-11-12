#!/usr/bin/env python3
"""Finds, in the Bee registry, the task that a PR's manifest names (manifests/<task>.yaml or manifestes/).

The manifest comes from the PR: it is data, read with yaml.safe_load and validated, never executed. The task and the
list of metrics come from the registry (branch main, tasks/libyaml/ and projects/libyaml.yaml): the registry, not the
PR, sets the metric aimed at. The registry is read in English (bee/ci/vocabulaire.py), its metric ids in French or in
English until ruche-0149; the manifest in either vocabulary until bee's DATE_D.

Usage: python3 bee/ci/tache.py --manifeste pr/manifests/libyaml-0012.yaml --registre registre [--sortie tache.yaml]
Standard output, one line per value, in the format of $GITHUB_OUTPUT (the names stay those the workflow reads):
  tache=libyaml-0010
  type=optimization
  metrique=parse_throughput
  sortie_compressee=identical
Every value is checked against a closed list before it is written; the metric in its English name.
Exit code: 0 if the task is found, 1 otherwise (message on standard error).
"""

import argparse
import os
import re
import shutil
import sys

import yaml

from vocabulaire import METRIQUES, Illisible, lire_manifeste, lire_tache, metriques_du_projet

PROJET = "libyaml"
MOTIF_TACHE = re.compile(r"^" + PROJET + r"-[0-9]{4}$")


def echouer(message):
    print(f"tache.py: {message}", file=sys.stderr)
    print("sortie_compressee=identical")  # in doubt, the strictest check applies
    sys.exit(1)


def lire_unique(registre, chemin, quoi):
    """(path, data) of the registry's file <chemin>."""
    if not os.path.isfile(os.path.join(registre, chemin)):
        echouer(f"{quoi} not found in the registry ({chemin})")
    try:
        with open(os.path.join(registre, chemin), encoding="utf-8") as f:
            return os.path.join(registre, chemin), yaml.safe_load(f)
    except (OSError, ValueError, yaml.YAMLError) as e:
        echouer(f"{quoi} {chemin} unreadable in the registry: {e}")


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--manifeste", required=True)
    analyseur.add_argument("--registre", required=True)
    analyseur.add_argument("--sortie", default="tache.yaml")
    args = analyseur.parse_args()

    if not os.path.exists(args.manifeste):
        echouer("manifest missing: the PR must add manifests/<task>.yaml (see the registry's AGENTS.md: bee manifest)")
    try:
        with open(args.manifeste, encoding="utf-8") as f:
            manifeste = yaml.safe_load(f)
    except (OSError, ValueError, yaml.YAMLError) as e:  # ValueError : un manifeste qui n'est pas de l'UTF-8
        echouer(f"manifest unreadable (UTF-8 and YAML expected): {type(e).__name__}: {e}")
    try:
        tache = lire_manifeste(manifeste).get("task")
    except Illisible as e:
        echouer(str(e))
    if not isinstance(tache, str) or not MOTIF_TACHE.match(tache):
        echouer(f"the manifest's key « task » (or « tache ») must be a {PROJET}-NNNN id")
    nom = os.path.basename(args.manifeste)
    if nom != "CONTRIBUTION.yaml" and nom != tache + ".yaml":
        echouer(f"the manifest {nom} names the task {tache}: it must be called manifests/{tache}.yaml (or manifestes/)")

    # Closed list of the metrics: the registry's project descriptor's (never the PR's).
    _, projet = lire_unique(args.registre, os.path.join("projects", PROJET + ".yaml"), "project descriptor")
    try:
        metriques = metriques_du_projet(projet)
    except Illisible as e:
        echouer(str(e))
    chemin, donnees = lire_unique(args.registre, os.path.join("tasks", PROJET, tache + ".yaml"), f"task {tache}")
    try:
        valeurs = lire_tache(donnees, metriques)
    except Illisible as e:
        echouer(f"task {tache} unreadable: {e}")
    if valeurs["metric"] is not None and valeurs["metric"] not in METRIQUES:
        echouer(f"metric « {valeurs['metric']} » known to the registry, but libyamlBee's bench does not measure it "
                f"(bee/bench/ab.py: {', '.join(METRIQUES)}): verdict.py could not judge it")
    shutil.copyfile(chemin, args.sortie)
    print(f"tache={tache}")
    print(f"type={valeurs['type']}")
    print(f"metrique={valeurs['metric'] or 'none'}")
    print(f"sortie_compressee={valeurs['compressed_output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
