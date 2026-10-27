#!/usr/bin/env python3
"""Trouve, dans le registre Bee, la tâche que désigne le manifeste CONTRIBUTION.yaml d'une PR.

Le manifeste vient de la PR : c'est une donnée, lue avec yaml.safe_load et validée, jamais exécutée.
La tâche vient du registre (branche main) : c'est elle, et non la PR, qui fixe la métrique visée et
le droit de changer la sortie compressée.

Usage : python3 bee/ci/tache.py --manifeste pr/CONTRIBUTION.yaml --registre registre [--sortie tache.yaml]
Sortie standard, une ligne par valeur, au format de $GITHUB_OUTPUT :
  tache=miniz-0012
  type=optimisation
  metrique=debit_compression_n6
  sortie_compressee=identique
Toutes les valeurs sont validées contre une liste fermée avant d'être écrites.
Code de sortie : 0 si la tâche est trouvée, 1 sinon (message sur la sortie d'erreur).
"""

import argparse
import glob
import os
import re
import shutil
import sys

import yaml

MOTIF_TACHE = re.compile(r"^miniz-[0-9]{4}$")
TYPES = {"optimisation", "mesure", "test", "decoupage"}
METRIQUES = {"debit_compression_n1", "debit_compression_n6", "debit_compression_n9",
             "debit_decompression", "ratio_n6", "memoire_max_ko"}
SORTIES = {"identique", "peut_changer"}


def echouer(message):
    print(f"tache.py : {message}", file=sys.stderr)
    print("sortie_compressee=identique")  # en cas de doute, le contrôle le plus strict s'applique
    sys.exit(1)


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--manifeste", required=True)
    analyseur.add_argument("--registre", required=True)
    analyseur.add_argument("--sortie", default="tache.yaml")
    args = analyseur.parse_args()

    if not os.path.exists(args.manifeste):
        echouer("CONTRIBUTION.yaml absent à la racine de la PR (voir AGENTS.md du registre : bee manifeste)")
    try:
        with open(args.manifeste, encoding="utf-8") as f:
            manifeste = yaml.safe_load(f)
    except yaml.YAMLError as e:
        echouer(f"CONTRIBUTION.yaml illisible : {e}")
    if not isinstance(manifeste, dict):
        echouer("CONTRIBUTION.yaml ne contient pas un objet YAML")
    tache = manifeste.get("tache")
    if not isinstance(tache, str) or not MOTIF_TACHE.match(tache):
        echouer("la clé « tache » du manifeste doit être un identifiant miniz-NNNN")

    candidats = sorted(glob.glob(os.path.join(args.registre, "taches", "**", tache + ".yaml"), recursive=True))
    if not candidats:
        echouer(f"tâche {tache} introuvable dans le registre")
    with open(candidats[0], encoding="utf-8") as f:
        donnees = yaml.safe_load(f) or {}
    type_tache = donnees.get("type") if donnees.get("type") in TYPES else "inconnu"
    metrique = donnees.get("metrique") if donnees.get("metrique") in METRIQUES else "aucune"
    sortie = donnees.get("sortie_compressee") if donnees.get("sortie_compressee") in SORTIES else "identique"
    shutil.copyfile(candidats[0], args.sortie)
    print(f"tache={tache}")
    print(f"type={type_tache}")
    print(f"metrique={metrique}")
    print(f"sortie_compressee={sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
