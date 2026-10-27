#!/usr/bin/env python3
"""Assemble verdict.json pour la CI Bee du fork miniz (job « verdict » de .github/workflows/bee-ci.yml).

Entrées :
  --jobs        résultats des jobs GitHub (toJSON(needs) : {"manifeste": {"result": "success", "outputs": {...}}, ...}).
                C'est la source de vérité de « ci » : le code de la PR ne peut pas les réécrire.
  --artefacts   dossier où les artefacts « etat-* » ont été téléchargés : fichiers d'état <etape>.txt
                (« succes » / « echec », écrits par bee/ci/etape.sh), rapport ab.json d'ab.py,
                CONTRIBUTION.yaml de la PR et tache.yaml du registre. Ce sont des DONNÉES : lues, jamais exécutées.
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
  lignes_modifiees  lignes modifiées hors bee/**, tests/** et CONTRIBUTION.yaml (pour bee enregistrer-verdict)
  amorcage          true si les juges venaient de la PR elle-même (base = commit d'amorçage, voir bee/ci/juges.sh)
  etapes, details   pour les relecteurs

Métrique principale, dans l'ordre : la clé « metrique » de la tâche du registre (tache.yaml), sinon une clé
« metrique » du manifeste, sinon la seule métrique de mesures.avant du manifeste. Faute de quoi, gain = null.

La CI ne tranche pas R4 et R5 (seuils de gain et d'effets de bord) : elle publie les mesures et les
dégradations, l'outil du registre applique les règles.

Usage local (simulation) : python3 bee/ci/verdict.py --etats DOSSIER --ab ab.json [--manifeste F] [--tache F]
"""

import argparse
import fnmatch
import glob
import json
import os
import subprocess
import sys

# (étape, libellé, job GitHub qui la porte), dans l'ordre de la CI. « juges » est écrite par
# bee/ci/juges.sh dans chaque job ; son job est None : elle compte dès qu'un job l'a écrite.
ETAPES = [
    ("juges", "Juges (base sans bee/)", None),
    ("manifeste_et_taille", "Manifeste et taille", "manifeste"),
    ("compilation_x86_64", "Compilation et tests d'origine (x86-64)", "compilation-et-tests"),
    ("compilation_arm64", "Compilation et tests d'origine (ARM64)", "compilation-et-tests"),
    ("determinisme_x86_64", "Déterminisme du flux d'événements (x86-64)", "compilation-et-tests"),
    ("determinisme_arm64", "Déterminisme du flux d'événements (ARM64)", "compilation-et-tests"),
    ("banc_ab", "Banc A/B", "banc-ab"),
]
METRIQUES = ["debit_analyse", "debit_chargement", "debit_emission", "memoire_max_ko"]
# Repris de projets/miniz.yaml (chemins_hors_decompte) dans le registre Bee.
CHEMINS_HORS_DECOMPTE = ["bee/**", "tests/**", "CONTRIBUTION.yaml"]


def lire_texte(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def etats_depuis(dossiers):
    """Renvoie (états des étapes, amorçage signalé par au moins un job)."""
    etats, amorcage = {}, False
    for dossier in dossiers:
        for chemin in glob.glob(os.path.join(dossier, "**", "*.txt"), recursive=True):
            nom = os.path.basename(chemin)[:-4]
            if nom == "amorcage":
                amorcage = amorcage or lire_texte(chemin) == "oui"
            elif any(nom == e for e, _, _ in ETAPES):
                valeur = lire_texte(chemin)
                # Un « echec » l'emporte toujours sur un « succes » du même nom.
                if valeur in ("succes", "echec") and etats.get(nom) != "echec":
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


def metrique_principale(tache, manifeste):
    if isinstance(tache, dict) and tache.get("metrique") in METRIQUES:
        return tache["metrique"], "tâche du registre"
    if isinstance(manifeste, dict):
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


def trouver(dossier, nom):
    if not dossier:
        return None
    trouves = sorted(glob.glob(os.path.join(dossier, "**", nom), recursive=True))
    return trouves[0] if trouves else None


def main():
    analyseur = argparse.ArgumentParser(description="Assemble verdict.json pour la CI Bee du fork miniz.")
    analyseur.add_argument("--jobs", help="toJSON(needs) du workflow : résultats des jobs (source de vérité de « ci »)")
    analyseur.add_argument("--artefacts", help="dossier des artefacts etat-* téléchargés")
    analyseur.add_argument("--etats", help="dossier des fichiers <etape>.txt (simulation locale)")
    analyseur.add_argument("--ab", help="rapport JSON d'ab.py (défaut : ab.json trouvé dans --artefacts)")
    analyseur.add_argument("--manifeste", help="CONTRIBUTION.yaml de la PR (donnée)")
    analyseur.add_argument("--tache", help="tâche du registre (défaut : tache.yaml trouvé dans --artefacts)")
    analyseur.add_argument("--depot", help="clone du fork, pour compter les lignes modifiées")
    analyseur.add_argument("--base")
    analyseur.add_argument("--tete")
    analyseur.add_argument("--sortie", default="verdict.json")
    args = analyseur.parse_args()

    jobs = {}
    if args.jobs:
        with open(args.jobs, encoding="utf-8") as f:
            jobs = json.load(f) or {}
    etats, amorcage = etats_depuis([d for d in (args.etats, args.artefacts) if d])
    chemin_ab = args.ab or trouver(args.artefacts, "ab.json")
    chemin_manifeste = args.manifeste or trouver(args.artefacts, "CONTRIBUTION.yaml")
    chemin_tache = args.tache or trouver(args.artefacts, "tache.yaml")

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

    manifeste, etat_manifeste = charger_yaml(chemin_manifeste)
    tache, etat_tache = charger_yaml(chemin_tache)
    metrique, origine = metrique_principale(tache, manifeste)

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
        print("AMORÇAGE : les juges de cette exécution venaient de la PR elle-même (amorcage: true).", file=sys.stderr)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
