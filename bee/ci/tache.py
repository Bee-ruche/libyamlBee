#!/usr/bin/env python3
"""Finds, in the Bee registry, the task that a PR's manifest names (manifests/<task>.yaml or manifestes/).

Le manifeste vient de la PR : c'est une donnée, lue avec yaml.safe_load et validée, jamais exécutée.
La tâche et la liste des métriques viennent du registre (branche main, projets/libyaml.yaml) : c'est
lui, et non la PR, qui fixe la métrique visée. Les deux vocabulaires du registre sont lus (bee/ci/vocabulaire.py) :
tasks/ ou taches/, projects/ ou projets/, clés et valeurs anglaises ou françaises ; un document qui les mêle est refusé.

Usage : python3 bee/ci/tache.py --manifeste pr/manifestes/libyaml-0012.yaml --registre registre [--sortie tache.yaml]
Sortie standard, une ligne par valeur, au format de $GITHUB_OUTPUT :
  tache=libyaml-0010
  type=optimisation
  metrique=debit_analyse
  sortie_compressee=identique
Toutes les valeurs sont validées contre une liste fermée avant d'être écrites.
Code de sortie : 0 si la tâche est trouvée, 1 sinon (message sur la sortie d'erreur).
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
    print("sortie_compressee=identique")  # en cas de doute, le contrôle le plus strict s'applique
    sys.exit(1)


def lire_unique(registre, dossiers, nom, quoi):
    """(chemin, données) du seul fichier <dossier>/<nom> du registre parmi `dossiers` (anglais, puis français)."""
    trouves = [os.path.join(d, nom) for d in dossiers if os.path.isfile(os.path.join(registre, d, nom))]
    if len(trouves) != 1:
        echouer(f"{quoi} {'not found' if not trouves else 'found more than once'} in the registry "
                f"({' or '.join(os.path.join(d, nom) for d in dossiers)}; found: {trouves or 'none'})")
    try:
        with open(os.path.join(registre, trouves[0]), encoding="utf-8") as f:
            return os.path.join(registre, trouves[0]), yaml.safe_load(f)
    except (OSError, ValueError, yaml.YAMLError) as e:
        echouer(f"{quoi} {trouves[0]} unreadable in the registry: {e}")


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
        tache = lire_manifeste(manifeste).get("tache")
    except Illisible as e:
        echouer(str(e))
    if not isinstance(tache, str) or not MOTIF_TACHE.match(tache):
        echouer(f"the manifest's key « task » (or « tache ») must be a {PROJET}-NNNN id")
    nom = os.path.basename(args.manifeste)
    if nom != "CONTRIBUTION.yaml" and nom != tache + ".yaml":
        echouer(f"the manifest {nom} names the task {tache}: it must be called manifests/{tache}.yaml (or manifestes/)")

    # Liste fermée des métriques : celle du descripteur de projet du registre (jamais celle de la PR).
    _, projet = lire_unique(args.registre, ("projects", "projets"), PROJET + ".yaml", "project descriptor")
    try:
        metriques = metriques_du_projet(projet)
    except Illisible as e:
        echouer(str(e))
    chemin, donnees = lire_unique(args.registre, (os.path.join("tasks", PROJET), os.path.join("taches", PROJET)),
                                  tache + ".yaml", f"task {tache}")
    try:
        valeurs = lire_tache(donnees, metriques)
    except Illisible as e:
        echouer(f"task {tache} unreadable: {e}")
    if valeurs["metrique"] is not None and valeurs["metrique"] not in METRIQUES:
        echouer(f"metric « {valeurs['metrique']} » known to the registry, but libyamlBee's bench does not measure it "
                f"(bee/bench/ab.py: {', '.join(METRIQUES)}): verdict.py could not judge it")
    shutil.copyfile(chemin, args.sortie)
    print(f"tache={tache}")
    print(f"type={valeurs['type']}")
    print(f"metrique={valeurs['metrique'] or 'aucune'}")
    print(f"sortie_compressee={valeurs['sortie_compressee']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
