#!/usr/bin/env python3
"""Assembles verdict.json for the Bee CI of the libyaml fork (job « verdict » of .github/workflows/bee-ci.yml).

Inputs:
  --jobs        the GitHub jobs' results (toJSON(needs): {"manifeste": {"result": "success", "outputs": {...}}, ...}).
                They are the source of truth for « ci »: the PR's code cannot rewrite them.
  --artefacts   folder where the « etat-* » artifacts were downloaded: state files <etape>.txt (« succes » / « echec »,
                written by bee/ci/etape.sh), ab.py's report ab.json, the PR's CONTRIBUTION.yaml and the registry's
                tache.yaml. They are DATA: read, never executed. Each file is read only at the root of its job's artifact
                (etat-banc, etat-manifeste), each state file only in its job's state folder (DOSSIERS_ETATS); never a
                symbolic link.
  --depot, --base, --tete   to count the changed lines (git diff --numstat).

Output (--sortie, default verdict.json), in English (the registry's tools/migration/names.yaml, family fork_verdict),
with at least:
  ci                « green » if every job passed, otherwise « red »
  failed_step       the first failed step in the CI's order (if red)
  gain              relative gain on the task's main metric (positive = better), or null
  metric            the main metric kept, or null
  beyond_noise      ab.py's sign test on the main metric (false without a metric)
  measurements      {"A": {4 metrics}, "B": {4 metrics}}: ab.py's medians
  instructions      Cachegrind count per scenario on a sub-corpus: {"instructions_parse": {"A", "B", "gain"}, ...}
  degradations      metrics degraded beyond noise (sign test; instructions beyond the threshold), with their gain
  changed_lines     lines changed outside bee/**, tests/**, manifests/**, manifestes/** and CONTRIBUTION.yaml (for
                    bee record-verdict)
  bootstrap         true if the judges came from the PR itself (base = bootstrap commit, see bee/ci/juges.sh)
  steps, details    for the reviewers
Metric ids are written in English (parse_throughput, load_throughput, emit_throughput, max_memory_kb,
instructions_parse/_load/_emit); bee reads them in either vocabulary until its DATE_D.

Main metric: « metric » of the task's copy (tache.yaml of etat-manifeste, bee/ci/vocabulaire.py; a French metric id is
read in English), null if it says null; missing in CI or unreadable: « Manifest and size » failed, never the PR's
metric. Outside CI and without a copy only: the manifest's (metric, otherwise the only metric of measurements.before;
or in French).

The CI does not decide R4 and R5 (gain and side-effect thresholds): it publishes the measurements and the degradations,
the registry's tool applies the rules.

Local use (simulation): python3 bee/ci/verdict.py --etats FOLDER --ab ab.json [--manifeste F] [--tache F]
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys

from vocabulaire import METRIQUES, Illisible, lire_manifeste, metrique_de_la_tache

# (step, its key in verdict.json, label, GitHub job that carries it), in the CI's order. The step is the name of its state
# file (<etape>.txt, written by the workflow and the base's scripts); the key and the label are what verdict.json says.
# « juges » is written by bee/ci/juges.sh in each job; its job is None: it counts as soon as a job has written it.
ETAPES = [
    ("juges", "judges", "Judges (base without bee/)", None),
    ("manifeste_et_taille", "manifest_and_size", "Manifest and size", "manifeste"),
    ("compilation_x86_64", "build_x86_64", "Build and original tests (x86-64)", "compilation-et-tests"),
    ("compilation_arm64", "build_arm64", "Build and original tests (ARM64)", "compilation-et-tests"),
    ("determinisme_x86_64", "determinism_x86_64", "Event stream determinism (x86-64)", "compilation-et-tests"),
    ("determinisme_arm64", "determinism_arm64", "Event stream determinism (ARM64)", "compilation-et-tests"),
    ("fuzzing", "fuzzing", "Differential fuzzing of the parser (x86-64)", "fuzzing"),
    ("banc_ab", "ab_bench", "A/B bench", "banc-ab"),
]
# A step's result in verdict.json; the state files keep « succes » and « echec » (bee/ci/etape.sh, juges.sh).
RESULTATS = {"succes": "passed", "echec": "failed", "absent": "absent"}
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
# From projects/libyaml.yaml (paths_not_counted) in the Bee registry, plus the manifest, in both its folders.
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
    noms = [e for e, _, _, _ in ETAPES] + ["amorcage"]
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
        return None, "PyYAML unavailable"
    try:
        with open(chemin, encoding="utf-8") as f:
            donnees = yaml.safe_load(f)
    except Exception as e:  # PR data: any reading error simply makes the data invalid
        return None, f"unreadable ({type(e).__name__})"
    return (donnees, "ok") if isinstance(donnees, dict) else (None, "not a YAML object")


def metrique_principale(tache, etat_tache, manifeste, en_ci):
    """(metric in English or None, origin). Raises Illisible when the task does not say its metric readably."""
    if tache is not None:
        metrique = metrique_de_la_tache(tache)
        return metrique, "registry task" if metrique else "registry task (metric: null)"
    if en_ci or etat_tache != "absent":
        raise Illisible(f"copy of the registry's task {etat_tache}: metric unreadable")
    if manifeste is not None:
        manifeste = lire_manifeste(manifeste)
        if manifeste.get("metric") in METRIQUES:
            return manifeste["metric"], "manifest (key metric)"
        mesures = manifeste.get("measurements") if isinstance(manifeste.get("measurements"), dict) else {}
        avant = mesures.get("before") if isinstance(mesures.get("before"), dict) else {}
        connues = [m for m in avant if m in METRIQUES]
        if len(connues) == 1:
            return connues[0], "manifest (only metric of measurements.before)"
    return None, "no metric named"


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


def resultat_en_anglais(resultat):
    """A step's result as verdict.json says it: « succes (job failure) » -> « passed (job failure) »."""
    mot, _, reste = resultat.partition(" ")
    return RESULTATS.get(mot, mot) + (" " + reste if reste else "")


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
        # The task sets the metric, never the PR: without it, no green verdict (its copy comes from the manifeste job).
        metrique, origine = None, f"unreadable: {e}"
        etats["manifeste_et_taille"] = "echec"
        print(f"::error::verdict.py: {e}", file=sys.stderr)

    # Étape par étape : réussie seulement si son fichier d'état dit « succes » ET (en CI) si son job a réussi.
    resultat_etapes = {}
    for etape, _, _, job in ETAPES:
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
    en_echec = next((libelle for etape, _, libelle, _ in ETAPES if resultat_etapes[etape].startswith("echec")), None)
    if en_echec is None:
        en_echec = next((libelle + " (no result)" for etape, _, libelle, _ in ETAPES if resultat_etapes[etape] != "succes"), None)
    if en_echec is None and jobs_en_echec:
        en_echec = "job " + ", ".join(sorted(jobs_en_echec))

    rapport = None
    if chemin_ab and os.path.exists(chemin_ab):
        try:
            with open(chemin_ab, encoding="utf-8") as f:
                rapport = json.load(f)
        except (OSError, ValueError):
            rapport = None

    # ab.py's report (bee/bench/ab.py, from the same bee/ folder as this script), in English.
    metriques_ab = (rapport or {}).get("metrics", {})
    instructions = (rapport or {}).get("instructions")
    gain, bruit = None, False
    if metrique and metrique in metriques_ab:
        gain = metriques_ab[metrique].get("gain")
        bruit = bool(metriques_ab[metrique].get("beyond_noise"))
    degradations = {m: v.get("gain") for m, v in metriques_ab.items() if v.get("degradation_beyond_noise")}
    for nom, v in (instructions or {}).items():
        if v.get("beyond_noise") and (v.get("gain") or 0) < 0:
            degradations[nom] = v.get("gain")

    # « green » requires every step to have passed AND (in CI) every job to have passed.
    if en_echec is None and any(v != "succes" for v in resultat_etapes.values()):
        en_echec = "step with an inconsistent result"
    verdict = {"ci": "red" if en_echec else "green"}
    if en_echec:
        verdict["failed_step"] = en_echec
    verdict.update({
        "gain": gain,
        "metric": metrique,
        "beyond_noise": bruit,
        "measurements": (rapport or {}).get("measurements") or {"A": {m: None for m in METRIQUES}, "B": {m: None for m in METRIQUES}},
        "instructions": ({nom: {"A": v.get("A"), "B": v.get("B"), "gain": v.get("gain")} for nom, v in instructions.items()}
                         if instructions else None),
        "degradations": degradations,
        "changed_lines": lignes_modifiees(args.depot, args.base, args.tete),
        "bootstrap": amorcage,
        "steps": {cle: resultat_en_anglais(resultat_etapes[etape]) for etape, cle, _, _ in ETAPES},
        "details": {
            "metric_origin": origine,
            "manifest": etat_manifeste,
            "task": etat_tache,
            "base": args.base,
            "head": args.tete,
            "jobs": {nom: (v or {}).get("result") for nom, v in jobs.items()},
            "gains_by_metric": {m: v.get("gain") for m, v in metriques_ab.items()},
            "sign_test": {m: v.get("sign_test") for m, v in metriques_ab.items()},
            "method": (rapport or {}).get("method"),
            "machine": (rapport or {}).get("machine"),
            "repetitions": (rapport or {}).get("repetitions"),
        },
    })
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    resume = {k: verdict[k] for k in ("ci", "failed_step", "gain", "metric", "beyond_noise", "degradations",
                                      "changed_lines", "bootstrap") if k in verdict}
    if amorcage:
        print("BOOTSTRAP: the judges of this run came from the PR itself (bootstrap: true).", file=sys.stderr)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
