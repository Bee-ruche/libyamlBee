#!/usr/bin/env python3
"""Assemble verdict.json pour la CI Bee du fork libyaml (job « verdict » de .github/workflows/bee-ci.yml).

Entrées :
  --jobs        résultats des jobs GitHub (toJSON(needs) : {"manifeste": {"result": "success", "outputs": {...}}, ...}).
                C'est la source de vérité de « ci » : le code de la PR ne peut pas les réécrire.
  --artefacts   dossier où les artefacts « etat-* » ont été téléchargés : fichiers d'état <etape>.txt
                (« succes » / « echec », écrits par bee/ci/etape.sh), rapport ab.json d'ab.py,
                CONTRIBUTION.yaml de la PR et tache.yaml du registre. Ce sont des DONNÉES : lues, jamais exécutées.
                Chaque fichier n'est lu qu'à la racine de l'artefact de son job (etat-banc, etat-manifeste), chaque
                fichier d'état que dans le dossier d'état de son job (DOSSIERS_ETATS) ; jamais un lien symbolique.
  --depot, --base, --tete   pour compter les lignes modifiées (git diff --numstat).

Sortie (--sortie, défaut verdict.json), avec au minimum :
  ci                « verte » si tous les jobs ont réussi, sinon « rouge »
  etape_en_echec    première étape en échec dans l'ordre de la CI (si rouge)
  gain              gain relatif sur la métrique principale de la tâche (positif = mieux), ou null
  metrique          la métrique principale retenue, ou null
  au_dela_du_bruit  test du signe d'ab.py sur la métrique principale (false si aucune métrique)
  mesures           {"A": {6 métriques}, "B": {6 métriques}} : médianes d'ab.py
  instructions      décompte Cachegrind par scénario sur un sous-corpus : {"instructions_n6": {"A", "B", "gain"}, ...}
  degradations      métriques dégradées au-delà du bruit (test du signe ; instructions au-delà du seuil), avec leur gain
  lignes_modifiees  lignes modifiées hors bee/**, tests/**, manifests/**, manifestes/** et CONTRIBUTION.yaml (pour bee enregistrer-verdict)
  amorcage          true si les juges venaient de la PR elle-même (base = commit d'amorçage, voir bee/ci/juges.sh)
  etapes, details   pour les relecteurs

Métrique principale : « metric » ou « metrique » de la copie de la tâche (tache.yaml d'etat-manifeste, bee/ci/vocabulaire.py),
null si elle dit null ; absente en CI ou illisible : « Manifeste et taille » en échec, jamais la métrique de la PR. Hors
CI et sans copie seulement : celle du manifeste (metric, sinon seule métrique de measurements.before ; ou en français).

La CI ne tranche pas R4 et R5 (seuils de gain et d'effets de bord) : elle publie les mesures et les
dégradations, l'outil du registre applique les règles.

Usage local (simulation) : python3 bee/ci/verdict.py --etats DOSSIER --ab ab.json [--manifeste F] [--tache F]
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys

from vocabulaire import METRIQUES, Illisible, lire_manifeste, metrique_de_la_tache

# (étape, libellé, job GitHub qui la porte), dans l'ordre de la CI. « juges » est écrite par
# bee/ci/juges.sh dans chaque job ; son job est None : elle compte dès qu'un job l'a écrite.
ETAPES = [
    ("juges", "Juges (base sans bee/)", None),
    ("manifeste_et_taille", "Manifeste et taille", "manifeste"),
    ("compilation_x86_64", "Compilation et tests d'origine (x86-64)", "compilation-et-tests"),
    ("compilation_arm64", "Compilation et tests d'origine (ARM64)", "compilation-et-tests"),
    ("determinisme_x86_64", "Déterminisme du flux d'événements (x86-64)", "compilation-et-tests"),
    ("determinisme_arm64", "Déterminisme du flux d'événements (ARM64)", "compilation-et-tests"),
    ("fuzzing", "Fuzzing différentiel de l'analyseur (x86-64)", "fuzzing"),
    ("banc_ab", "Banc A/B", "banc-ab"),
]
# Dossier d'état de chaque étape dans les artefacts : celui où le job qui l'écrit le dépose (bee-ci.yml : etats/ à la
# racine de son artefact, ou sous etats/ quand l'artefact porte aussi ses données). Une étape n'est lue que là, jamais
# dans un autre artefact ni plus bas.
DOSSIERS_ETATS = {
    "manifeste_et_taille": "etat-manifeste/etats",
    "compilation_x86_64": "etat-tests-x86_64", "determinisme_x86_64": "etat-tests-x86_64",
    "compilation_arm64": "etat-tests-arm64", "determinisme_arm64": "etat-tests-arm64",
    "fuzzing": "etat-fuzzing",
    "banc_ab": "etat-banc/etats",
}
# Repris de projets/libyaml.yaml (chemins_hors_decompte) dans le registre Bee, plus le manifeste, dans ses deux dossiers.
CHEMINS_HORS_DECOMPTE = ["bee/**", "tests/**", "CONTRIBUTION.yaml", "manifests/**", "manifestes/**"]


def lire_texte(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def ordinaire(chemin):
    """Un fichier ordinaire : ni lien symbolique, ni dossier."""
    return bool(chemin) and os.path.isfile(chemin) and not os.path.islink(chemin)


def etats_depuis(dossier_etats, artefacts):
    """Renvoie (états des étapes, amorçage signalé par au moins un job). Dans --etats (le dossier du job verdict, ou
    d'une simulation), chaque <etape>.txt à sa racine ; dans les artefacts, chaque <etape>.txt seulement dans le
    dossier d'état du job qui l'écrit (DOSSIERS_ETATS), « juges » et « amorcage » dans chacun de ces dossiers."""
    noms = [e for e, _, _ in ETAPES] + ["amorcage"]
    chemins = [os.path.join(dossier_etats, nom + ".txt") for nom in noms] if dossier_etats else []
    for nom in noms if artefacts else []:
        if nom in ("juges", "amorcage"):
            dossiers = sorted(set(DOSSIERS_ETATS.values()))
        else:
            dossiers = [DOSSIERS_ETATS[nom]] if nom in DOSSIERS_ETATS else []
        chemins += [os.path.join(artefacts, dossier, nom + ".txt") for dossier in dossiers]
    etats, amorcage = {}, False
    for chemin in filter(ordinaire, chemins):
        nom, valeur = os.path.basename(chemin)[:-4], lire_texte(chemin)
        if nom == "amorcage":
            amorcage = amorcage or valeur == "oui"
        # Un « echec » l'emporte toujours sur un « succes » du même nom.
        elif valeur in ("succes", "echec") and etats.get(nom) != "echec":
            etats[nom] = valeur
    return etats, amorcage


def charger_yaml(chemin):
    if not chemin or not os.path.exists(chemin):
        return None, "absent"
    try:
        import yaml
    except ImportError:
        return None, "PyYAML indisponible"
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = yaml.safe_load(f)
    except Exception as e:  # donnée de la PR : toute erreur de lecture rend simplement la donnée invalide
        return None, f"illisible ({type(e).__name__})"
    return (donnees, "ok") if isinstance(donnees, dict) else (None, "pas un objet YAML")


def metrique_principale(tache, etat_tache, manifeste, en_ci):
    """(métrique ou None, origine). Lève Illisible quand la tâche ne dit pas lisiblement sa métrique."""
    if tache is not None:
        metrique = metrique_de_la_tache(tache)
        return metrique, "tâche du registre" if metrique else "tâche du registre (metrique: null)"
    if en_ci or etat_tache != "absent":
        raise Illisible(f"copie de la tâche du registre {etat_tache} : métrique illisible")
    if manifeste is not None:
        manifeste = lire_manifeste(manifeste)
        if manifeste.get("metrique") in METRIQUES:
            return manifeste["metrique"], "manifeste (clé metrique)"
        mesures = manifeste.get("mesures") if isinstance(manifeste.get("mesures"), dict) else {}
        avant = mesures.get("avant") if isinstance(mesures.get("avant"), dict) else {}
        connues = [m for m in avant if m in METRIQUES]
        if len(connues) == 1:
            return connues[0], "manifeste (seule métrique de mesures.avant)"
    return None, "aucune métrique désignée"


def lignes_modifiees(depot, base, tete):
    if not (depot and base and tete):
        return None
    try:
        sortie = subprocess.run(["git", "-C", depot, "diff", "--numstat", "--no-renames", f"{base}...{tete}"],
                                capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    total = 0
    for ligne in sortie.splitlines():
        ajoutees, retirees, chemin = ligne.split("\t", 2)
        if ajoutees == "-" or any(fnmatch.fnmatchcase(chemin, m) for m in CHEMINS_HORS_DECOMPTE):
            continue
        total += int(ajoutees) + int(retirees)
    return total


def trouver_dans(artefacts, artefact, nom):
    """Le fichier `nom` à la racine de l'artefact du job qui le produit : jamais celui d'un autre job ou d'un sous-dossier,
    et jamais un lien symbolique."""
    chemin = os.path.join(artefacts, artefact, nom) if artefacts else None
    return chemin if ordinaire(chemin) else None


def main():
    analyseur = argparse.ArgumentParser(description="Assembles verdict.json for the Bee CI of the libyaml fork.")
    analyseur.add_argument("--jobs", help="the workflow's toJSON(needs): the jobs' results (source of truth for « ci »)")
    analyseur.add_argument("--artefacts", help="folder of the downloaded etat-* artifacts")
    analyseur.add_argument("--etats", help="folder of the <etape>.txt files, at its root (the verdict job's, or a local simulation)")
    analyseur.add_argument("--ab", help="ab.py's JSON report (default: ab.json of the etat-banc artifact)")
    analyseur.add_argument("--manifeste", help="the PR's CONTRIBUTION.yaml (data)")
    analyseur.add_argument("--tache", help="the registry's task (default: tache.yaml of the etat-manifeste artifact)")
    analyseur.add_argument("--depot", help="clone of the fork, to count the changed lines")
    analyseur.add_argument("--base")
    analyseur.add_argument("--tete")
    analyseur.add_argument("--sortie", default="verdict.json")
    args = analyseur.parse_args()

    jobs = {}
    if args.jobs:
        with open(args.jobs, encoding="utf-8") as f:
            jobs = json.load(f) or {}
    etats, amorcage = etats_depuis(args.etats, args.artefacts)
    chemin_ab = args.ab or trouver_dans(args.artefacts, "etat-banc", "ab.json")
    chemin_manifeste = args.manifeste or trouver_dans(args.artefacts, "etat-manifeste", "CONTRIBUTION.yaml")
    chemin_tache = args.tache or trouver_dans(args.artefacts, "etat-manifeste", "tache.yaml")
    manifeste, etat_manifeste = charger_yaml(chemin_manifeste)
    tache, etat_tache = charger_yaml(chemin_tache)
    try:
        metrique, origine = metrique_principale(tache, etat_tache, manifeste, bool(jobs))
    except Illisible as e:
        # La tâche fixe la métrique, jamais la PR : sans elle, pas de verdict vert (sa copie vient du job manifeste).
        metrique, origine = None, f"illisible : {e}"
        etats["manifeste_et_taille"] = "echec"
        print(f"::error::verdict.py: {e}", file=sys.stderr)

    # Étape par étape : réussie seulement si son fichier d'état dit « succes » ET (en CI) si son job a réussi.
    resultat_etapes = {}
    for etape, _, job in ETAPES:
        etat = etats.get(etape, "absent")
        if job is None:  # « juges » : un seul « echec » suffit ; absente hors CI (simulation sans juges.sh)
            resultat_etapes[etape] = "echec" if etat == "echec" else ("succes" if etat == "succes" or not jobs else "absent")
            continue
        resultat_job = (jobs.get(job) or {}).get("result") if jobs else None
        if jobs and resultat_job != "success":
            # Job en échec : l'étape garde son propre état ; une étape « succes » d'un job en échec reste
            # suspecte (autre étape du même job en échec, ou job interrompu après coup).
            if etat == "echec":
                resultat_etapes[etape] = "echec"
            elif etat == "succes":
                resultat_etapes[etape] = f"succes (job {resultat_job})"
            else:
                resultat_etapes[etape] = "absent"
        else:
            resultat_etapes[etape] = "succes" if etat == "succes" else ("echec" if etat == "echec" else "absent")
    jobs_en_echec = [nom for nom, v in jobs.items() if (v or {}).get("result") != "success"]
    # D'abord la première étape explicitement en échec ; sinon la première sans résultat (job annulé,
    # délai dépassé, machine ARM64 indisponible…) ; sinon le job en échec.
    en_echec = next((libelle for etape, libelle, _ in ETAPES if resultat_etapes[etape].startswith("echec")), None)
    if en_echec is None:
        en_echec = next((libelle + " (sans résultat)" for etape, libelle, _ in ETAPES if resultat_etapes[etape] != "succes"), None)
    if en_echec is None and jobs_en_echec:
        en_echec = "job " + ", ".join(sorted(jobs_en_echec))

    rapport = None
    if chemin_ab and os.path.exists(chemin_ab):
        try:
            with open(chemin_ab, encoding="utf-8") as f:
                rapport = json.load(f)
        except (OSError, ValueError):
            rapport = None

    metriques_ab = (rapport or {}).get("metriques", {})
    instructions = (rapport or {}).get("instructions")
    gain, bruit = None, False
    if metrique and metrique in metriques_ab:
        gain = metriques_ab[metrique].get("gain")
        bruit = bool(metriques_ab[metrique].get("au_dela_du_bruit"))
    degradations = {m: v.get("gain") for m, v in metriques_ab.items() if v.get("degradation_au_dela_du_bruit")}
    for nom, v in (instructions or {}).items():
        if v.get("au_dela_du_bruit") and (v.get("gain") or 0) < 0:
            degradations[nom] = v.get("gain")

    # « verte » exige que toutes les étapes aient réussi ET (en CI) que tous les jobs aient réussi.
    if en_echec is None and any(v != "succes" for v in resultat_etapes.values()):
        en_echec = "étape au résultat incohérent"
    verdict = {"ci": "rouge" if en_echec else "verte"}
    if en_echec:
        verdict["etape_en_echec"] = en_echec
    verdict.update({
        "gain": gain,
        "metrique": metrique,
        "au_dela_du_bruit": bruit,
        "mesures": (rapport or {}).get("mesures") or {"A": {m: None for m in METRIQUES}, "B": {m: None for m in METRIQUES}},
        "instructions": ({nom: {"A": v.get("A"), "B": v.get("B"), "gain": v.get("gain")} for nom, v in instructions.items()}
                         if instructions else None),
        "degradations": degradations,
        "lignes_modifiees": lignes_modifiees(args.depot, args.base, args.tete),
        "amorcage": amorcage,
        "etapes": resultat_etapes,
        "details": {
            "origine_metrique": origine,
            "manifeste": etat_manifeste,
            "tache": etat_tache,
            "base": args.base,
            "tete": args.tete,
            "jobs": {nom: (v or {}).get("result") for nom, v in jobs.items()},
            "gains_par_metrique": {m: v.get("gain") for m, v in metriques_ab.items()},
            "test_du_signe": {m: v.get("test_du_signe") for m, v in metriques_ab.items()},
            "methode": (rapport or {}).get("methode"),
            "machine": (rapport or {}).get("machine"),
            "repetitions": (rapport or {}).get("repetitions"),
        },
    })
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    resume = {k: verdict[k] for k in ("ci", "etape_en_echec", "gain", "metrique", "au_dela_du_bruit", "degradations",
                                      "lignes_modifiees", "amorcage") if k in verdict}
    if amorcage:
        print("BOOTSTRAP: the judges of this run came from the PR itself (amorcage: true).", file=sys.stderr)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
