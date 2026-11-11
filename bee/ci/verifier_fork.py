#!/usr/bin/env python3
"""Runs the Bee registry's tool « bee check-fork » (« verifier-fork » in French), with the names its --help announces.

Le registre passe ses noms en anglais en une bascule (docs/english-names.md du registre) : outils/ → tools/,
verifier-fork → check-fork, --tache → --task, --tete → --head, --depot → --repo, --auteur → --author, --registre →
--registry, BEE_REGISTRE → BEE_REGISTRY. Ce script prend l'outil qui existe (tools/bee.py ou outils/bee.py, un seul),
puis demande à son --help l'option globale, la commande et ses options : jamais deviné. Une commande n'est retenue
que si son --help réussit et que sa ligne d'usage annonce chacune des options voulues, dans un seul des deux noms ;
une seule commande doit l'être. Sinon l'étape échoue, sans appeler l'outil. Les variables BEE_REGISTRE et
BEE_REGISTRY sont retirées, puis celle du vocabulaire annoncé désigne le même registre que l'option.

Usage : python3 bee/ci/verifier_fork.py <registre> --tache T --base B --tete H --depot D [--auteur A]
Code de sortie : celui de l'outil, ou 1 si on ne sait pas l'appeler (message sur la sortie d'erreur).
"""

import argparse
import os
import re
import subprocess
import sys

COMMANDES = ("check-fork", "verifier-fork")
# Options de la commande : nom interne → (anglais, français).
OPTIONS = {"tache": ("--task", "--tache"), "base": ("--base", "--base"), "tete": ("--head", "--tete"),
           "depot": ("--repo", "--depot"), "auteur": ("--author", "--auteur")}
GLOBALE = {"--registry": "BEE_REGISTRY", "--registre": "BEE_REGISTRE"}


def echouer(message):
    print(f"::error::verifier_fork.py: {message}", file=sys.stderr)
    sys.exit(1)


def options_annoncees(sortie):
    """Les options de la ligne d'usage d'argparse (jusqu'à la première ligne vide) : jamais celles du texte d'aide."""
    usage = sortie.split("\n\n", 1)[0]
    return set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", usage)) if usage.startswith("usage:") else set()


def un_seul(annoncees, noms, quoi):
    presents = sorted(set(noms) & annoncees)
    if len(presents) != 1:
        raise LookupError(f"{quoi}: {' or '.join(sorted(set(noms)))} expected in the usage line, found {presents or 'none'}")
    return presents[0]


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("registre")
    for nom in OPTIONS:
        analyseur.add_argument("--" + nom, required=nom != "auteur")
    args = analyseur.parse_args()

    outils = [c for c in ("tools/bee.py", "outils/bee.py") if os.path.isfile(os.path.join(args.registre, c))]
    if len(outils) != 1:
        echouer(f"the registry must have exactly one tool among tools/bee.py and outils/bee.py (found: {outils or 'none'})")
    outil = os.path.join(args.registre, outils[0])
    env = {k: v for k, v in os.environ.items() if k not in GLOBALE.values()}
    env["PYTHON_COLORS"] = "0"  # une aide sans couleurs (argparse de Python 3.14), lue telle quelle

    def aide(*arguments):
        r = subprocess.run([sys.executable, outil, *arguments, "--help"], capture_output=True, text=True, env=env)
        return r.stdout if r.returncode == 0 else "", r.stderr.strip()[-300:]

    sortie, erreur = aide()
    try:
        globale = un_seul(options_annoncees(sortie), GLOBALE, f"global option of {outils[0]} --help ({erreur or 'no error'})")
    except LookupError as e:
        echouer(str(e))
    env[GLOBALE[globale]] = args.registre
    voulues = [nom for nom in OPTIONS if getattr(args, nom) is not None]
    retenues, refus = {}, []
    for commande in COMMANDES:
        sortie, _ = aide(globale, args.registre, commande)
        try:
            if not re.match(rf"usage: \S+ {re.escape(commande)}(\s|$)", sortie):
                raise LookupError(f"{commande} --help does not announce this command")
            annoncees = options_annoncees(sortie)
            retenues[commande] = {nom: un_seul(annoncees, OPTIONS[nom], f"{commande} {OPTIONS[nom][1]}") for nom in voulues}
        except LookupError as e:
            refus.append(str(e))
    if len(retenues) != 1:
        echouer(f"exactly one command among {', '.join(COMMANDES)} is needed in the help of {outils[0]} "
                f"(kept: {sorted(retenues) or 'none'}; set aside: {'; '.join(refus) or 'none'})")
    (commande, noms), = retenues.items()
    appel = [sys.executable, outil, globale, args.registre, commande]
    for nom in voulues:
        appel += [noms[nom], getattr(args, nom)]
    print(f"Registry tool: {outils[0]} {globale} … {commande} ({', '.join(noms[n] for n in voulues)})", flush=True)
    return subprocess.run(appel, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
