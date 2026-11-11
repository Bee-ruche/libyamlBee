#!/usr/bin/env python3
"""Tests of libyamlBee's CI tooling (bee/ci/): the registry read in English, its metric ids in French or in English until
ruche-0149, the PR's manifest in either vocabulary until bee's DATE_D, and verdict.json written in English
(libyaml-0021; the registry's tools/migration/names.yaml, family fork_verdict).

Covers bee/ci/vocabulaire.py, bee/ci/tache.py and bee/ci/verifier_fork.py (end to end through bee/ci/manifeste.sh, on a
small git repository and a fake registry), bee/ci/verdict.py, bee/ci/juges.sh and its copy in
.github/workflows/bee-ci.yml, two steps of the « Manifest and size » job and the job that runs these tests for a PR
(« Tests of the PR's CI tooling », counted by the verdict). To run in the fork's sandbox:

  bee/sandbox/sans-docker.sh python3 bee/ci/test_verdict.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
VERDICT = os.path.join(ICI, "verdict.py")
MANIFESTE = os.path.join(ICI, "manifeste.sh")
JUGES = os.path.join(ICI, "juges.sh")
WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(ICI)), ".github", "workflows", "bee-ci.yml")
# The steps, by the names of their state files (written by the workflow and bee/ci/etape.sh, which keep them), then their
# keys and labels in verdict.json, written by hand: the tests check verdict.py, they do not copy it.
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "determinisme_x86_64",
          "determinisme_arm64", "fuzzing", "banc_ab"]
CLES_ETAPES = {"juges": "judges", "manifeste_et_taille": "manifest_and_size", "compilation_x86_64": "build_x86_64",
               "compilation_arm64": "build_arm64", "determinisme_x86_64": "determinism_x86_64",
               "determinisme_arm64": "determinism_arm64", "fuzzing": "fuzzing", "banc_ab": "ab_bench"}
LIBELLES = {"juges": "Judges (base without bee/)", "manifeste_et_taille": "Manifest and size",
            "compilation_x86_64": "Build and original tests (x86-64)", "compilation_arm64": "Build and original tests (ARM64)",
            "determinisme_x86_64": "Event stream determinism (x86-64)", "determinisme_arm64": "Event stream determinism (ARM64)",
            "fuzzing": "Differential fuzzing of the parser (x86-64)", "banc_ab": "A/B bench"}
JOBS_OK = {"manifeste": {"result": "success"}, "compilation-et-tests": {"result": "success"},
           "fuzzing": {"result": "success"}, "banc-ab": {"result": "success"}, "outillage-pr": {"result": "success"}}
# Folder where each job puts its state files in its artifact (bee-ci.yml), written by hand. « juges » goes in --etats,
# the verdict job's folder.
DOSSIER_ETAT = {"manifeste_et_taille": "etat-manifeste/etats", "compilation_x86_64": "etat-tests-x86_64",
                "determinisme_x86_64": "etat-tests-x86_64", "compilation_arm64": "etat-tests-arm64",
                "determinisme_arm64": "etat-tests-arm64", "fuzzing": "etat-fuzzing", "banc_ab": "etat-banc/etats"}
# verdict.json's French keys (names.yaml, family fork_verdict), that an English verdict never holds, at any depth.
CLES_FRANCAISES_DU_VERDICT = {"etape_en_echec", "metrique", "au_dela_du_bruit", "mesures", "lignes_modifiees", "amorcage",
                              "base_juge", "regle", "depart", "juge", "commun", "projet", "greffon", "graine",
                              "sorties_comparees", "constructions_suspectes", "etapes", "origine_metrique", "manifeste",
                              "tache", "tete", "gains_par_metrique", "test_du_signe", "methode"}
ENV_GIT = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

# Data written by hand, never derived from the maps of bee/ci/vocabulaire.py: the tests check the maps, they do not copy
# them. The registry's task and project descriptor as main has them: English keys and values, French metric ids (until
# ruche-0149), and the same with English metric ids (after it).
TACHE = """id: libyaml-0050
project: libyaml
category: parsing-serialization
type: optimization
size: S
title: essai
files: [src/scanner.c]
metric: debit_emission
compressed_output: may_change
status: reserved
"""
TACHE_IDS_EN = TACHE.replace("metric: debit_emission", "metric: emit_throughput")
PROJET = """id: libyaml
name: libyaml
category: parsing-serialization
upstream_repo: https://github.com/yaml/libyaml
license: MIT
status: active
metrics:
  - {id: debit_analyse, description: d, unit: MB/s, direction: higher, instructions: instructions_analyse}
  - {id: debit_chargement, description: d, unit: MB/s, direction: higher, instructions: instructions_chargement}
  - {id: debit_emission, description: d, unit: MB/s, direction: higher, instructions: instructions_emission}
  - {id: memoire_max_ko, description: d, unit: KB, direction: lower}
paths_not_counted: ["bee/**", "tests/**"]
judge_paths: ["bee/**", "tests/**", ".github/**"]
"""
PROJET_IDS_EN = """id: libyaml
name: libyaml
category: parsing-serialization
upstream_repo: https://github.com/yaml/libyaml
license: MIT
status: active
metrics:
  - {id: parse_throughput, description: d, unit: MB/s, direction: higher, instructions: instructions_parse}
  - {id: load_throughput, description: d, unit: MB/s, direction: higher, instructions: instructions_load}
  - {id: emit_throughput, description: d, unit: MB/s, direction: higher, instructions: instructions_emit}
  - {id: max_memory_kb, description: d, unit: KB, direction: lower}
paths_not_counted: ["bee/**", "tests/**"]
judge_paths: ["bee/**", "tests/**", ".github/**"]
"""
# The registry's former French layout (before its switch), no longer read.
TACHE_FR = """id: libyaml-0050
projet: libyaml
categorie: parsing-serialisation
type: optimisation
taille: S
titre: essai
fichiers: [src/scanner.c]
metrique: debit_emission
sortie_compressee: peut_changer
statut: reservee
"""
PROJET_FR = """id: libyaml
nom: libyaml
categorie: parsing-serialisation
depot_origine: https://github.com/yaml/libyaml
licence: MIT
statut: actif
metriques:
  - {id: debit_analyse, description: d, unite: Mo/s, sens: plus_haut, instructions: instructions_analyse}
  - {id: debit_chargement, description: d, unite: Mo/s, sens: plus_haut}
  - {id: debit_emission, description: d, unite: Mo/s, sens: plus_haut}
  - {id: memoire_max_ko, description: d, unite: Ko, sens: plus_bas}
chemins_hors_decompte: ["bee/**", "tests/**"]
chemins_juges: ["bee/**", "tests/**", ".github/**"]
"""
# The PR's manifest, in either vocabulary until bee's DATE_D.
MANIFESTE_FR = """tache: libyaml-0050
utilisateur: abeille
agent: {modele: m, client: c}
resume: r
changement: c
mesures: {machine: x, commande: y, repetitions: 3, avant: {debit_emission: 400}, apres: {debit_emission: 420}}
teste: [a]
non_teste: [b]
doutes: d
taille_reelle: S
"""
MANIFESTE_EN = """task: libyaml-0050
user: abeille
agent: {model: m, client: c}
summary: r
change: c
measurements: {machine: x, command: y, repetitions: 3, before: {debit_emission: 400}, after: {debit_emission: 420}}
tested: [a]
untested: [b]
doubts: d
actual_size: S
"""
MANIFESTE_EN_IDS_EN = MANIFESTE_EN.replace("debit_emission", "emit_throughput")
# A fake registry tool, built with argparse as the real one (bee check-fork's English names: anything else exits 2). It
# records its calls in journal.jsonl, and returns the code written in the file « code » next to it.
FAUX_OUTIL = '''import argparse, json, os, sys
ici = os.path.dirname(os.path.abspath(__file__))
p = argparse.ArgumentParser(prog="bee")
p.add_argument("--registry")
sous = p.add_subparsers(dest="command")
s = sous.add_parser("check-fork")
for o in ("--task", "--base", "--head", "--repo", "--author"):
    s.add_argument(o, required=o in ("--task", "--base"))
p.parse_args()
with open(os.path.join(ici, "journal.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "BEE_REGISTRY": os.environ.get("BEE_REGISTRY")}) + "\\n")
sys.exit(int(open(os.path.join(ici, "code")).read()) if os.path.exists(os.path.join(ici, "code")) else 0)
'''


def ecrire(racine, chemin, texte):
    os.makedirs(os.path.dirname(os.path.join(racine, chemin)) or racine, exist_ok=True)
    with open(os.path.join(racine, chemin), "wb") as f:
        f.write(texte if isinstance(texte, bytes) else texte.encode("utf-8"))


def lire(chemin):
    if not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def vocabulaire():
    sys.path.insert(0, ICI)
    try:
        import vocabulaire as module
    finally:
        sys.path.remove(ICI)
    return module


def cles(donnee):
    """Every key of a JSON document, at any depth, but the keys of details.jobs: the workflow's job ids (data)."""
    if isinstance(donnee, dict):
        donnee = dict(donnee, details={k: v for k, v in donnee["details"].items() if k != "jobs"}) if isinstance(
            donnee.get("details"), dict) else donnee
        return set(donnee) | {k for v in donnee.values() for k in cles(v)}
    if isinstance(donnee, list):
        return {k for v in donnee for k in cles(v)}
    return set()


class Vocabulaire(unittest.TestCase):
    """bee/ci/vocabulaire.py: the task and the project descriptor in English, their metric ids in either vocabulary (one
    per document); the manifest in either vocabulary, one per manifest."""

    def setUp(self):
        import yaml
        self.v = vocabulaire()
        self.yaml = yaml.safe_load

    def test_cartes_bijectives_et_disjointes(self):
        """A name never belongs to both vocabularies: otherwise a document could not be classified."""
        v = self.v
        for carte in (v.CLES_MANIFESTE, v.CLES_AGENT, v.CLES_MESURES, v.METRIQUES_FR):
            self.assertEqual(len(set(carte.values())), len(carte))
            self.assertFalse(set(carte) & set(carte.values()), carte)
        self.assertEqual(v.METRIQUES, ["parse_throughput", "load_throughput", "emit_throughput", "max_memory_kb"])
        self.assertLessEqual(set(v.METRIQUES), set(v.METRIQUES_FR.values()))
        self.assertEqual({v.METRIQUES_FR[f] for f in ("debit_analyse", "debit_chargement", "debit_emission", "memoire_max_ko",
                                                     "instructions_analyse", "instructions_chargement", "instructions_emission")},
                         {"parse_throughput", "load_throughput", "emit_throughput", "max_memory_kb", "instructions_parse",
                          "instructions_load", "instructions_emit"})

    def test_tache_en_anglais_metrique_dans_les_deux_vocabulaires(self):
        attendu = {"type": "optimization", "metric": "emit_throughput", "compressed_output": "may_change"}
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE), self.v.METRIQUES), attendu)
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_IDS_EN), self.v.METRIQUES), attendu)
        for type_tache in ("optimization", "review", "measurement", "test", "split"):
            with self.subTest(type=type_tache):
                texte = TACHE.replace("type: optimization", "type: " + type_tache)
                self.assertEqual(self.v.lire_tache(self.yaml(texte), ["emit_throughput"])["type"], type_tache)
        sans_sortie = self.v.lire_tache(self.yaml(TACHE.replace("compressed_output: may_change\n", "")), ["emit_throughput"])
        self.assertEqual(sans_sortie["compressed_output"], "identical")  # missing: the strictest check
        for texte in (TACHE.replace("metric: debit_emission", "metric: null").replace("optimization", "test"),
                      TACHE_IDS_EN.replace("metric: emit_throughput", "metric: null").replace("optimization", "measurement")):
            self.assertIsNone(self.v.lire_tache(self.yaml(texte), self.v.METRIQUES)["metric"])

    def test_tache_francaise_ou_illisible_refusee(self):
        """Never a default value: the registry's former French layout (keys or values), type missing or unknown, metric
        key missing, metric outside the given list, optimization without a metric."""
        for texte in (TACHE_FR, TACHE.replace("type: optimization", "type: optimisation"),
                      TACHE.replace("may_change", "peut_changer"), TACHE.replace("metric: debit_emission", "metrique: debit_emission"),
                      TACHE.replace("type: optimization\n", ""), TACHE.replace("optimization", "rapide"),
                      TACHE.replace("metric: debit_emission\n", ""), TACHE.replace("debit_emission", "vitesse"),
                      TACHE.replace("debit_emission", "[debit_analyse]"), TACHE.replace("debit_emission", "debit_compression_n6"),
                      "id: libyaml-0050\ntype: test\n", "- liste\n", "",
                      TACHE.replace("metric: debit_emission", "metric: null"),
                      TACHE_IDS_EN.replace("metric: emit_throughput", "metric: null")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte), self.v.METRIQUES)
        for tache in (TACHE, TACHE_IDS_EN):  # known to the bench, but not to the given descriptor
            with self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(tache), ["parse_throughput"])
        with self.assertRaises(self.v.Illisible):
            self.v.metrique_de_la_tache(self.yaml("type: test\nstatus: open\n"))

    def test_projet_metriques_dans_les_deux_vocabulaires(self):
        attendu = ["parse_throughput", "load_throughput", "emit_throughput", "max_memory_kb"]
        self.assertEqual(self.v.metriques_du_projet(self.yaml(PROJET)), attendu)
        self.assertEqual(self.v.metriques_du_projet(self.yaml(PROJET_IDS_EN)), attendu)

    def test_projet_francais_mele_ou_illisible(self):
        """English keys; one vocabulary of metric ids per descriptor, instruction ids included; without a readable list
        of metrics: never an empty list."""
        for texte in (PROJET_FR, PROJET.replace("metrics:", "metriques:"), PROJET.split("metrics:")[0],
                      PROJET.split("metrics:")[0] + "metrics: []\n", PROJET.split("metrics:")[0] + "metrics: debit_analyse\n",
                      PROJET.split("metrics:")[0] + "metrics: 4\n", PROJET.replace("{id: debit_chargement, ", "{"),
                      PROJET.replace("id: memoire_max_ko", "id: 12"),
                      PROJET.replace("  - {id: debit_chargement", "  - debit_chargement\n  - {id: x"),
                      PROJET.replace("id: debit_chargement", "id: load_throughput"),
                      PROJET_IDS_EN.replace("instructions: instructions_load", "instructions: instructions_chargement"),
                      "id: libyaml\nmetrics_x: []\n", "- libyaml\n", ""):
            with self.subTest(projet=texte), self.assertRaises(self.v.Illisible):
                self.v.metriques_du_projet(self.yaml(texte))

    def test_manifeste_dans_les_deux_vocabulaires(self):
        fr, en = self.v.lire_manifeste(self.yaml(MANIFESTE_FR)), self.v.lire_manifeste(self.yaml(MANIFESTE_EN))
        self.assertEqual(fr, en)
        self.assertEqual(fr, self.v.lire_manifeste(self.yaml(MANIFESTE_EN_IDS_EN)))
        self.assertEqual(fr, self.yaml(MANIFESTE_EN_IDS_EN))  # English keys, English metric ids
        self.assertEqual(en["measurements"]["before"], {"emit_throughput": 400})

    def test_manifeste_mele_refuse(self):
        """One vocabulary per manifest, at all its levels (agent, measurements), metric ids included."""
        for texte in (MANIFESTE_FR.replace("resume: r", "summary: r"), MANIFESTE_EN.replace("doubts: d", "doutes: d"),
                      MANIFESTE_FR.replace("avant:", "before:"), MANIFESTE_FR.replace("modele:", "model:"),
                      MANIFESTE_EN.replace("command:", "commande:"), MANIFESTE_FR + "measurements: {}\n",
                      MANIFESTE_EN.replace("after: {debit_emission", "after: {emit_throughput"),
                      MANIFESTE_EN_IDS_EN + "metric: debit_emission\n"):
            with self.subTest(manifeste=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_manifeste(self.yaml(texte))


class JobManifeste(unittest.TestCase):
    """bee/ci/manifeste.sh end to end (tache.py, verifier_fork.py), on a small git repository and a fake registry in
    English: the task and the descriptor read in English, their metric ids in either vocabulary, the manifest in either
    vocabulary, the tool called with its English names."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.pr, self.registre = os.path.join(self.d, "pr"), os.path.join(self.d, "registre")
        os.makedirs(self.pr)
        self.git("init", "-q", "-b", "master")
        ecrire(self.pr, "src/scanner.c", "int x;\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", self.pr] + list(args), capture_output=True, text=True, check=True,
                              env=ENV_GIT).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD")

    def lancer(self, manifestes, taches=(("tasks", TACHE),), outils=(("tools", FAUX_OUTIL),),
               projets=(("projects", PROJET),), liens=()):
        for dossier, texte in taches:
            ecrire(self.registre, f"{dossier}/libyaml/libyaml-0050.yaml", texte)
        for dossier, texte in outils:
            ecrire(self.registre, f"{dossier}/bee.py", texte)
        for dossier, texte in projets:
            ecrire(self.registre, f"{dossier}/libyaml.yaml", texte)
        for chemin, texte in manifestes:
            ecrire(self.pr, chemin, texte)
        for chemin, cible in liens:
            os.makedirs(os.path.dirname(os.path.join(self.pr, chemin)) or self.pr, exist_ok=True)
            os.symlink(cible, os.path.join(self.pr, chemin))
        ecrire(self.pr, "src/parser.c", "int y;\n")
        tete = self.commit()
        sortie, copie = os.path.join(self.d, "sortie"), os.path.join(self.d, "copie.yaml")
        open(sortie, "w").close()
        env = dict(os.environ, BASE_SHA=self.base, TETE_SHA=tete, AUTEUR="abeille", GITHUB_OUTPUT=sortie,
                   BEE_SORTIE_TACHE=copie, BEE_REGISTRY="/ailleurs")
        r = subprocess.run(["bash", MANIFESTE, self.pr, self.registre, sys.executable], capture_output=True, text=True,
                           env=env, cwd=self.d)
        self.sorties = dict(ligne.split("=", 1) for ligne in lire(sortie).split())
        self.copie = lire(copie)
        self.journal = [json.loads(ligne) for dossier, _ in outils
                        for ligne in (lire(os.path.join(self.registre, dossier, "journal.jsonl")) or "").splitlines()]
        self.tete = tete
        return r.returncode, r.stdout + r.stderr

    def appel(self):
        return ["--registry", self.registre, "check-fork", "--task", "libyaml-0050", "--base", self.base, "--head", self.tete,
                "--repo", self.pr, "--author", "abeille"]

    def refus(self, attendu, *args, **kwargs):
        """The job fails without calling the tool, writing the task's copy or giving a metric."""
        code, sortie = self.lancer(*args, **kwargs)
        self.sortie_job = sortie
        self.assertEqual((code, self.journal, self.copie), (1, [], None), sortie)
        self.assertNotIn("metrique", self.sorties)
        self.assertEqual(self.sorties.get("sortie_compressee"), "identical")
        self.assertIn(attendu, sortie)

    def test_registre_anglais_manifeste_des_deux_vocabulaires(self):
        for chemin, manifeste in (("manifests/libyaml-0050.yaml", MANIFESTE_EN), ("manifestes/libyaml-0050.yaml", MANIFESTE_FR),
                                  ("manifests/libyaml-0050.yaml", MANIFESTE_EN_IDS_EN), ("CONTRIBUTION.yaml", MANIFESTE_FR)):
            with self.subTest(chemin=chemin, manifeste=manifeste.split()[0]):
                self.setUp()
                code, sortie = self.lancer([(chemin, manifeste)])
                self.assertEqual(code, 0, sortie)
                self.assertEqual(self.journal, [{"argv": self.appel(), "BEE_REGISTRY": self.registre}])
                # The values in English, the metric in its English name, under the output names the workflow reads.
                self.assertEqual(self.sorties, {"tache": "libyaml-0050", "type": "optimization", "metrique": "emit_throughput",
                                                "sortie_compressee": "may_change", "manifeste": chemin})
                self.assertEqual(self.copie, TACHE)  # the copy verdict.py reads: the task as it is

    def test_identifiants_de_metrique_des_deux_vocabulaires(self):
        """French ids (the registry until ruche-0149) or English ones, in the task and in the descriptor, each read in
        its own vocabulary."""
        for tache, projet in ((TACHE_IDS_EN, PROJET_IDS_EN), (TACHE, PROJET_IDS_EN), (TACHE_IDS_EN, PROJET)):
            with self.subTest(tache=tache.split("metric: ")[1].split()[0], projet=projet.split("id: ")[2].split(",")[0]):
                self.setUp()
                code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)], taches=(("tasks", tache),),
                                           projets=(("projects", projet),))
                self.assertEqual((code, len(self.journal), self.sorties["metrique"], self.copie), (0, 1, "emit_throughput", tache), sortie)

    def test_disposition_francaise_du_registre_refusee(self):
        """The registry's former folders (taches/, projets/, outils/) are no longer read."""
        self.refus("task libyaml-0050 not found", [("manifests/libyaml-0050.yaml", MANIFESTE_EN)], taches=(("taches", TACHE),))
        self.setUp()
        self.refus("project descriptor not found", [("manifests/libyaml-0050.yaml", MANIFESTE_EN)], projets=(("projets", PROJET),))
        for outils in ((("outils", FAUX_OUTIL),), ()):
            with self.subTest(outils=[o for o, _ in outils]):
                self.setUp()
                code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)], outils=outils)
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("::error::verifier_fork.py: the registry has no tools/bee.py", sortie)

    def test_manifeste_mele_refuse(self):
        for texte in (MANIFESTE_EN.replace("summary: r", "resume: r"), MANIFESTE_FR.replace("avant:", "before:"),
                      MANIFESTE_EN.replace("after: {debit_emission", "after: {emit_throughput")):
            with self.subTest(manifeste=texte):
                self.setUp()
                self.refus("mixes", [("manifests/libyaml-0050.yaml", texte)])

    def test_tache_type_ou_metrique_illisible_echoue(self):
        """The job fails, without calling the tool or writing the task's copy: never a default."""
        for texte in (TACHE.replace("type: optimization\n", ""), TACHE.replace("optimization", "inconnu"),
                      TACHE.replace("metric: debit_emission\n", ""), TACHE.replace("debit_emission", "vitesse"),
                      TACHE.replace("compressed_output: may_change", "compressed_output: peut_changer"),
                      TACHE.replace("optimization", "optimisation"), TACHE_FR, "- pas un objet\n", "task: [illisible\n",
                      TACHE.replace("metric: debit_emission", "metric: null"),
                      TACHE_IDS_EN.replace("metric: emit_throughput", "metric: null")):
            with self.subTest(tache=texte):
                self.setUp()
                self.refus("task libyaml-0050", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], taches=(("tasks", texte),))
                self.assertIn("unreadable", self.sortie_job)

    def test_metrique_connue_du_registre_et_mesuree_par_le_banc(self):
        """The metric must be in the registry's descriptor AND among those the bench measures: a metric the registry
        does not list is refused; one it lists but the bench does not measure too, from this step on (otherwise it
        would be refused only at the verdict, under another name)."""
        seule = PROJET.split("metrics:")[0] + "metrics:\n  - {id: debit_analyse, unit: MB/s, direction: higher}\n"
        self.refus("unknown", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=(("projects", seule),))
        for projet, tache in ((PROJET.replace("id: debit_emission", "id: debit_nouveau"), TACHE.replace("debit_emission", "debit_nouveau")),
                              (PROJET_IDS_EN.replace("direction: lower}\n", "direction: lower}\n  - {id: latency, unit: ms, direction: lower}\n"),
                               TACHE_IDS_EN.replace("emit_throughput", "latency"))):
            with self.subTest(tache=tache):
                self.setUp()
                self.refus("does not measure it", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=(("projects", projet),),
                           taches=(("tasks", tache),))
        for tache in (TACHE.replace("debit_emission", "memoire_max_ko"), TACHE_IDS_EN.replace("emit_throughput", "max_memory_kb")):
            with self.subTest(tache=tache):
                self.setUp()
                code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], taches=(("tasks", tache),))
                self.assertEqual((code, self.sorties.get("metrique")), (0, "max_memory_kb"), sortie)

    def test_manifeste_illisible(self):
        """A manifest that is not UTF-8, or not YAML: a clean failure, without an exception's trace."""
        for texte in (MANIFESTE_FR.encode("utf-8").replace(b"resume: r", b"resume: \xff\xfe r"),
                      MANIFESTE_FR.encode("latin-1", "replace") + "doutes_bis: é\n".encode("latin-1"),
                      b"tache: [libyaml-0050\n"):
            with self.subTest(texte=texte[-30:]):
                self.setUp()
                self.refus("manifest unreadable", [("manifestes/libyaml-0050.yaml", texte)])
                self.assertNotIn("Traceback", self.sortie_job)

    def test_manifeste_fichier_ordinaire(self):
        """A manifest is a regular file: a symbolic link (into the repository or out of it) or a folder is refused
        before any reading."""
        for manifestes, liens in (([("hors.yaml", MANIFESTE_FR)], [("manifestes/libyaml-0050.yaml", "../hors.yaml")]),
                                  ([], [("manifests/libyaml-0050.yaml", "DEHORS")]),
                                  ([("hors.yaml", MANIFESTE_FR)], [("CONTRIBUTION.yaml", "hors.yaml")]),
                                  ([("CONTRIBUTION.yaml/x", "a\n")], [])):
            with self.subTest(manifestes=manifestes, liens=liens):
                self.setUp()
                ecrire(self.d, "dehors.yaml", MANIFESTE_EN)  # out of the repository
                liens = [(c, os.path.join(self.d, "dehors.yaml") if cible == "DEHORS" else cible) for c, cible in liens]
                code, sortie = self.lancer(manifestes, liens=liens)
                self.assertEqual((code, self.journal, self.copie, self.sorties), (1, [], None, {}), sortie)
                self.assertIn("must be a regular file", sortie)

    def test_descripteur_illisible_echoue(self):
        for projets, attendu in (((("projects", PROJET_FR),), "missing"),
                                 ((("projects", PROJET.split("metrics:")[0]),), "missing"),
                                 ((("projects", PROJET.replace("id: debit_chargement", "id: load_throughput")),), "mixes French metric ids"),
                                 ((("projects", "- liste\n"),), "not contain a YAML object"),
                                 ((("projects", "name: [illisible\n"),), "unreadable"),
                                 ((), "not found")):
            with self.subTest(projets=projets, attendu=attendu):
                self.setUp()
                self.refus(attendu, [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=projets)

    def test_tache_introuvable(self):
        self.refus("not found", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], taches=())

    def test_deux_manifestes_refuses(self):
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN), ("manifestes/libyaml-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("several manifests", sortie)

    def test_nom_de_manifeste(self):
        for chemin in ("manifests/libyaml-50.yaml", "manifests/sous/libyaml-0050.yaml", "manifestes/miniz-0050.yaml"):
            with self.subTest(chemin=chemin):
                self.setUp()
                code, sortie = self.lancer([(chemin, MANIFESTE_FR)])
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("Invalid manifest name", sortie)
        self.setUp()
        code, sortie = self.lancer([("manifests/libyaml-0051.yaml", MANIFESTE_EN)])  # names libyaml-0050
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("must be called", sortie)

    def test_code_de_l_outil_rendu(self):
        ecrire(self.registre, "tools/code", "1\n")
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)])
        self.assertEqual((code, len(self.journal)), (1, 1), sortie)


def rapport_ab(facteur=1, instructions=None, degradees=()):
    """ab.py's report, in English: a different gain per metric, to see which one the verdict kept (and where the report
    comes from: `facteur` multiplies the gains of a report put elsewhere); `degradees`: metrics degraded beyond noise."""
    gains = {m: facteur * g for m, g in
             {"parse_throughput": 0.01, "load_throughput": 0.02, "emit_throughput": 0.05, "max_memory_kb": 0.0}.items()}
    return {"metrics": {m: {"gain": -0.03 if m in degradees else g, "beyond_noise": g >= 0.02 and m not in degradees,
                            "degradation_beyond_noise": m in degradees, "sign_test": {"b_wins": 9, "useful_pairs": 10}}
                        for m, g in gains.items()},
            "measurements": {"A": {m: 100.0 for m in gains}, "B": {m: 100.0 * (1 + g) for m, g in gains.items()}},
            "instructions": instructions, "method": {"retained_value": "median of the repetitions"},
            "machine": {"architecture": "x86_64"}, "repetitions": 10}


class VerdictEnAnglais(unittest.TestCase):
    """verdict.py: verdict.json in English (names.yaml, family fork_verdict), metric ids in English; the metric of the
    task's copy (artifact etat-manifeste), its id in French or in English; unreadable, missing in CI or from another
    artifact: never a default, never the PR's metric."""

    def executer(self, jobs=JOBS_OK, tache=None, manifeste=None, ailleurs=(), ab=True, etats=None, liens=(), rapport=None):
        """Verdict on artifacts: each state (all « succes » by default) where its job puts it, the task's copy, the
        manifest and ab.json at their place, files `ailleurs`, and symbolic links `liens` (path, content) to a file
        out of the artifacts."""
        with tempfile.TemporaryDirectory() as d:
            artefacts = os.path.join(d, "artefacts")
            for etape, valeur in ({e: "succes" for e in ETAPES} if etats is None else etats).items():
                ecrire(os.path.join(artefacts, DOSSIER_ETAT[etape]) if etape in DOSSIER_ETAT else os.path.join(d, "etats"),
                       f"{etape}.txt", valeur + "\n")
            for i, (chemin, contenu) in enumerate(liens):
                ecrire(d, f"cible-{i}", contenu)
                os.makedirs(os.path.dirname(os.path.join(artefacts, chemin)), exist_ok=True)
                os.symlink(os.path.join(d, f"cible-{i}"), os.path.join(artefacts, chemin))
            if ab:
                ecrire(artefacts, "etat-banc/ab.json", json.dumps(rapport or rapport_ab()))
            for nom, contenu in (("tache.yaml", tache), ("CONTRIBUTION.yaml", manifeste)):
                if contenu is not None:
                    ecrire(artefacts, f"etat-manifeste/{nom}", contenu)
            for chemin, contenu in ailleurs:
                ecrire(artefacts, chemin, contenu)
            os.makedirs(os.path.join(d, "etats"), exist_ok=True)
            commande = [sys.executable, VERDICT, "--artefacts", artefacts, "--etats", os.path.join(d, "etats"),
                        "--sortie", os.path.join(d, "verdict.json")]
            if jobs is not None:
                ecrire(d, "jobs.json", json.dumps(jobs))
                commande += ["--jobs", os.path.join(d, "jobs.json")]
            subprocess.run(commande, check=True, capture_output=True)
            with open(os.path.join(d, "verdict.json")) as f:
                return json.load(f)

    def test_verdict_vert_en_anglais(self):
        v = self.executer(tache=TACHE)
        self.assertEqual(set(v), {"ci", "gain", "metric", "beyond_noise", "measurements", "instructions", "degradations",
                                  "changed_lines", "bootstrap", "steps", "details"})
        self.assertEqual((v["ci"], v["metric"], v["gain"], v["beyond_noise"], v["bootstrap"]), ("green", "emit_throughput", 0.05, True, False))
        self.assertEqual(v["steps"], {CLES_ETAPES[e]: "passed" for e in ETAPES})
        self.assertEqual(list(v["steps"]), [CLES_ETAPES[e] for e in ETAPES])  # in the CI's order
        self.assertEqual(set(v["details"]), {"metric_origin", "manifest", "task", "base", "head", "jobs", "gains_by_metric",
                                             "sign_test", "method", "machine", "repetitions"})
        self.assertEqual((v["details"]["manifest"], v["details"]["task"], v["details"]["method"]),
                         ("absent", "ok", {"retained_value": "median of the repetitions"}))
        self.assertEqual(v["details"]["sign_test"]["emit_throughput"], {"b_wins": 9, "useful_pairs": 10})
        self.assertEqual(set(v["measurements"]["B"]), {"parse_throughput", "load_throughput", "emit_throughput", "max_memory_kb"})
        self.assertFalse(cles(v) & CLES_FRANCAISES_DU_VERDICT, v)

    def test_verdict_rouge_en_anglais(self):
        """The first failed step in the CI's order, by its English label; a step without a result, a step that passed in
        a failed job, a failed job without a failed step, in English too."""
        for echec in ETAPES:
            with self.subTest(echec=echec):
                v = self.executer(tache=TACHE, etats={e: "echec" if e == echec else "succes" for e in ETAPES})
                self.assertEqual((v["ci"], v["failed_step"], v["steps"][CLES_ETAPES[echec]]), ("red", LIBELLES[echec], "failed"))
                self.assertFalse(cles(v) & CLES_FRANCAISES_DU_VERDICT, v)
        v = self.executer(tache=TACHE, etats={e: "succes" for e in ETAPES if e != "fuzzing"})
        self.assertEqual((v["ci"], v["failed_step"], v["steps"]["fuzzing"]), ("red", LIBELLES["fuzzing"] + " (no result)", "absent"))
        v = self.executer(jobs=dict(JOBS_OK, **{"compilation-et-tests": {"result": "failure"}}), tache=TACHE)
        self.assertEqual((v["ci"], v["failed_step"], v["steps"]["build_arm64"]),
                         ("red", LIBELLES["compilation_x86_64"] + " (no result)", "passed (job failure)"))
        v = self.executer(jobs=dict(JOBS_OK, **{"compilation-et-tests": {"result": "failure"}}), tache=TACHE,
                          etats={e: "echec" if e == "determinisme_arm64" else "succes" for e in ETAPES})
        self.assertEqual((v["failed_step"], v["steps"]["determinism_arm64"]), (LIBELLES["determinisme_arm64"], "failed"))

    def test_identifiants_de_metrique_en_anglais(self):
        """Instructions and degradations keyed by the English ids of ab.py's report, which verdict.py copies."""
        instructions = {"instructions_parse": {"direction": "lower", "unit": "instructions", "A": 1000, "B": 990, "gain": 0.01, "beyond_noise": True},
                        "instructions_load": {"direction": "lower", "unit": "instructions", "A": 1000, "B": 1000, "gain": 0.0, "beyond_noise": False},
                        "instructions_emit": {"direction": "lower", "unit": "instructions", "A": 1000, "B": 1010, "gain": -0.01, "beyond_noise": True}}
        v = self.executer(tache=TACHE_IDS_EN, rapport=rapport_ab(instructions=instructions, degradees=("max_memory_kb",)))
        self.assertEqual(v["instructions"], {"instructions_parse": {"A": 1000, "B": 990, "gain": 0.01},
                                             "instructions_load": {"A": 1000, "B": 1000, "gain": 0.0},
                                             "instructions_emit": {"A": 1000, "B": 1010, "gain": -0.01}})
        self.assertEqual(v["degradations"], {"max_memory_kb": -0.03, "instructions_emit": -0.01})
        self.assertEqual((v["ci"], v["metric"]), ("green", "emit_throughput"))

    def test_metrique_de_la_tache_dans_les_deux_vocabulaires(self):
        for tache in (TACHE, TACHE_IDS_EN):
            with self.subTest(tache=tache):
                v = self.executer(tache=tache, manifeste=MANIFESTE_FR.replace("debit_emission", "debit_analyse"))
                self.assertEqual((v["ci"], v["metric"], v["gain"], v["beyond_noise"]), ("green", "emit_throughput", 0.05, True))
                self.assertEqual(v["details"]["metric_origin"], "registry task")

    def test_tache_illisible_rend_rouge(self):
        """Copy missing in CI, French keys, without a metric key, unknown metric, not a mapping: red, and the PR does
        not pick the metric (the manifest names one)."""
        for tache in (None, "type: test\n", "metric: vitesse\n", "metrique: debit_analyse\n", TACHE_FR,
                      "- debit_analyse\n", "id: libyaml-0050\ntype: test\n", "metric: [illisible\n"):
            with self.subTest(tache=tache):
                v = self.executer(tache=tache, manifeste=MANIFESTE_EN)
                self.assertEqual((v["ci"], v["failed_step"], v["metric"], v["gain"]), ("red", "Manifest and size", None, None))
                self.assertTrue(v["details"]["metric_origin"].startswith("unreadable"))
                self.assertEqual(v["steps"]["manifest_and_size"], "failed")

    def test_copie_de_la_tache_seulement_dans_etat_manifeste(self):
        """A tache.yaml or a manifest put in another job's artifact is never read."""
        autre = TACHE.replace("debit_emission", "debit_analyse")
        v = self.executer(tache=TACHE_IDS_EN, ailleurs=[("etat-banc/etats/tache.yaml", autre), ("etat-banc/CONTRIBUTION.yaml", MANIFESTE_FR)])
        self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", "emit_throughput", 0.05))
        v = self.executer(tache=None, ailleurs=[("etat-banc/etats/tache.yaml", autre)])
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))
        v = self.executer(jobs=None, tache=None, ailleurs=[("etat-tests-x86_64/tache.yaml", autre),
                                                           ("etat-fuzzing/CONTRIBUTION.yaml", MANIFESTE_FR)])
        self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", None, None))
        v = self.executer(tache=None, ailleurs=[("etat-manifeste/etats/tache.yaml", TACHE)])  # the root only
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))

    def test_rapport_ab_seulement_dans_etat_banc(self):
        """ab.json is read only at the root of the bench's artifact (etat-banc): one in another artifact or in a
        subfolder, even sorted first, is never read."""
        faux = json.dumps(rapport_ab(facteur=10))
        ailleurs = [("etat-banc/AAA/ab.json", faux), ("etat-banc/etats/ab.json", faux), ("etat-fuzzing/ab.json", faux),
                    ("etat-tests-x86_64/ab.json", faux), ("etat-manifeste/ab.json", faux)]
        v = self.executer(tache=TACHE, ailleurs=ailleurs)
        self.assertEqual((v["ci"], v["metric"], v["gain"], v["measurements"]["B"]["emit_throughput"]),
                         ("green", "emit_throughput", 0.05, 105.0))
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                v = self.executer(jobs=jobs, tache=TACHE, ailleurs=ailleurs, ab=False)
                self.assertEqual((v["metric"], v["gain"], v["beyond_noise"], v["measurements"]["B"]["emit_throughput"]),
                                 ("emit_throughput", None, False, None))

    def test_etat_lu_seulement_dans_le_dossier_de_son_job(self):
        """Each <etape>.txt is read only in the state folder of the job that writes it: a « succes » put in another
        artifact, in another job's folder, at the root or in a subfolder of the right artifact does not replace a missing
        state (red, no result); a state that is a symbolic link neither."""
        self.assertEqual(self.executer(tache=TACHE)["ci"], "green")  # the honest path
        for manquante, proprietaire in DOSSIER_ETAT.items():
            autre = "etat-manifeste/etats" if proprietaire != "etat-manifeste/etats" else "etat-fuzzing"
            dossiers = ["juge", "etat-evil", "etat-evil/etats", "x/etats", autre, proprietaire + "/sous"]
            dossiers += [proprietaire.split("/")[0]] if "/" in proprietaire else []
            etats = {e: "succes" for e in ETAPES if e != manquante}
            with self.subTest(manquante=manquante):
                v = self.executer(tache=TACHE, etats=etats, ailleurs=[(f"{d}/{manquante}.txt", "succes\n") for d in dossiers])
                self.assertEqual((v["ci"], v["steps"][CLES_ETAPES[manquante]]), ("red", "absent"))
                v = self.executer(tache=TACHE, etats=etats, liens=[(f"{proprietaire}/{manquante}.txt", "succes\n")])
                self.assertEqual((v["ci"], v["steps"][CLES_ETAPES[manquante]]), ("red", "absent"))
        v = self.executer(tache=TACHE, ailleurs=[("etat-evil/amorcage.txt", "oui\n"), ("x/etats/amorcage.txt", "oui\n")])
        self.assertFalse(v["bootstrap"])
        self.assertTrue(self.executer(tache=TACHE, ailleurs=[("etat-fuzzing/amorcage.txt", "oui\n")])["bootstrap"])

    def test_lien_symbolique_jamais_lu(self):
        """The task's copy and ab.json are never read through a symbolic link, even at their place."""
        v = self.executer(tache=None, liens=[("etat-manifeste/tache.yaml", TACHE)])
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))
        v = self.executer(tache=TACHE, ab=False, liens=[("etat-banc/ab.json", json.dumps(rapport_ab()))])
        self.assertEqual((v["metric"], v["gain"]), ("emit_throughput", None))

    def test_metrique_null_jamais_celle_du_manifeste(self):
        tache = TACHE.replace("metric: debit_emission", "metric: null").replace("optimization", "test")
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                v = self.executer(jobs=jobs, tache=tache, manifeste=MANIFESTE_FR)
                self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", None, None))
                self.assertEqual(v["details"]["metric_origin"], "registry task (metric: null)")

    def test_simulation_sans_tache_lit_le_manifeste(self):
        """Outside CI only, without the task's copy: the manifest, in one vocabulary."""
        for manifeste in (MANIFESTE_EN, MANIFESTE_FR, MANIFESTE_EN_IDS_EN, "metric: debit_emission\ntask: libyaml-0050\n",
                          "metric: emit_throughput\ntask: libyaml-0050\n", "metrique: debit_emission\ntache: libyaml-0050\n"):
            with self.subTest(manifeste=manifeste):
                v = self.executer(jobs=None, manifeste=manifeste)
                self.assertEqual((v["ci"], v["metric"], v["gain"]), ("green", "emit_throughput", 0.05))
        v = self.executer(jobs=None, manifeste=MANIFESTE_EN.replace("before:", "avant:"))
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))
        v = self.executer(jobs=JOBS_OK, manifeste=MANIFESTE_EN)  # in CI, never: the task's copy is missing
        self.assertEqual((v["ci"], v["failed_step"], v["metric"]), ("red", "Manifest and size", None))

    def test_lignes_hors_manifestes_des_deux_dossiers(self):
        """R1: manifests/** and manifestes/** not counted, as bee/**, tests/** and CONTRIBUTION.yaml."""
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                return subprocess.run(["git", "-C", d] + list(a), capture_output=True, text=True, check=True, env=ENV_GIT).stdout.strip()
            git("init", "-q", "-b", "master")
            ecrire(d, "src/scanner.c", "int x;\n")
            git("add", "-A"), git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            for chemin in ("manifests/libyaml-0050.yaml", "manifestes/libyaml-0051.yaml", "bee/x", "tests/y", "CONTRIBUTION.yaml"):
                ecrire(d, chemin, "a\nb\nc\nd\n")
            ecrire(d, "src/scanner.c", "int x;\nint y;\nint z;\n")
            git("add", "-A"), git("commit", "-q", "-m", "tete")
            sortie = os.path.join(d, "v.json")
            subprocess.run([sys.executable, VERDICT, "--depot", d, "--base", base, "--tete", git("rev-parse", "HEAD"),
                            "--sortie", sortie], check=True, capture_output=True)
            with open(sortie) as f:
                self.assertEqual(json.load(f)["changed_lines"], 2)


class EtapesDuWorkflow(unittest.TestCase):
    """Two steps of bee-ci.yml's manifest job, extracted as they are: the registry's tools/requirements.txt, and the
    manifest kept from manifests/ or manifestes/."""

    def script(self, debut):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        scripts = [e["run"] for e in etapes if e.get("name", "").startswith(debut)]
        self.assertEqual(len(scripts), 1, debut)
        return scripts[0]

    def exigences(self, fichiers):
        script = self.script("The bee tool's dependencies")
        with tempfile.TemporaryDirectory() as d:
            for chemin in fichiers:
                ecrire(d, chemin, "pyyaml>=6\n")
            ecrire(d, "bin/pip", '#!/bin/sh\necho "$@" > "$(dirname "$0")/../appel"\n')
            os.chmod(os.path.join(d, "bin", "pip"), 0o755)
            env = dict(os.environ, PATH=os.path.join(d, "bin") + os.pathsep + os.environ["PATH"])
            r = subprocess.run(["bash", "-e", "-c", script], cwd=d, capture_output=True, text=True, env=env)
            appel = (lire(os.path.join(d, "appel")) or "").strip() or None
        return r.returncode, appel, r.stderr

    def test_exigences_du_registre(self):
        self.assertEqual(self.exigences(["registre/tools/requirements.txt"])[:2], (0, "install -r registre/tools/requirements.txt"))

    def test_exigences_absentes_echoue(self):
        """The registry's former outils/ is no longer read: without tools/requirements.txt, the step fails."""
        for fichiers in ([], ["registre/outils/requirements.txt"]):
            with self.subTest(fichiers=fichiers):
                code, appel, erreur = self.exigences(fichiers)
                self.assertEqual((code, appel), (1, None))
                self.assertIn("::error::", erreur)

    def test_manifeste_conserve_des_deux_dossiers(self):
        script = self.script("Keep the manifest")
        for chemin, garde, lien in (("manifests/libyaml-0050.yaml", True, False), ("manifestes/libyaml-0050.yaml", True, False),
                                    ("CONTRIBUTION.yaml", True, False), ("manifests/libyaml-50.yaml", False, False),
                                    ("autre/libyaml-0050.yaml", False, False), ("manifests/../tache.yaml", False, False),
                                    # a manifest is a regular file: a symbolic link is not copied
                                    ("manifests/libyaml-0050.yaml", False, True), ("CONTRIBUTION.yaml", False, True)):
            with self.subTest(chemin=chemin, lien=lien), tempfile.TemporaryDirectory() as d:
                ecrire(d, "dehors.yaml" if lien else "pr/" + chemin, "task: libyaml-0050\n")
                if lien:
                    os.makedirs(os.path.dirname(os.path.join(d, "pr", chemin)), exist_ok=True)
                    os.symlink(os.path.join(d, "dehors.yaml"), os.path.join(d, "pr", chemin))
                env = dict(os.environ, MANIFESTE=chemin, ETATS=os.path.join(d, "etats"))
                r = subprocess.run(["bash", "-e", "-c", script], cwd=d, capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(os.path.exists(os.path.join(d, "donnees", "CONTRIBUTION.yaml")), garde)


def logique_juges(texte, debut, fin):
    return texte.split(debut, 1)[1].split(fin, 1)[0]


class Juges(unittest.TestCase):
    """bee/ci/juges.sh and its copy in bee-ci.yml (BEE_JUGES): identical; the base's judges, the bootstrap only for the
    pinned commit, otherwise a failure; the state values the base's verdict.py reads (succes, echec, oui)."""

    def workflow(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_copie_du_workflow_identique(self):
        with open(JUGES, encoding="utf-8") as f:
            texte = f.read()
        script = logique_juges(texte, "# --- start of the logic copied into bee-ci.yml ---\n", "# --- end of the logic copied into bee-ci.yml ---")
        workflow = self.workflow()
        self.assertEqual(workflow["env"]["BEE_JUGES"], script)
        self.assertIn(f'BEE_COMMIT_AMORCAGE="${{BEE_COMMIT_AMORCAGE:-{workflow["env"]["BEE_COMMIT_AMORCAGE"]}}}"', texte)
        for nom, job in workflow["jobs"].items():
            etapes = [e.get("name", "") for e in job["steps"]]
            juges = [i for i, n in enumerate(etapes) if n.startswith("Judges")]
            self.assertEqual(len(juges), 1, f"job {nom}: one Judges step")
            self.assertIn('eval "$BEE_JUGES"', job["steps"][juges[0]]["run"])
            for e in job["steps"][:juges[0]]:  # no step uses base/bee before the Judges step
                self.assertNotIn("base/bee", e.get("run", ""), f"job {nom}: base/bee used before Judges")

    def preparer(self, d, base_avec_bee, pr_avec_bee=True):
        base, pr = os.path.join(d, "base"), os.path.join(d, "pr")
        for racine, avec in ((base, base_avec_bee), (pr, pr_avec_bee)):
            os.makedirs(racine)
            if avec:
                ecrire(racine, "bee/ci/etape.sh", "# " + racine + "\n")
                ecrire(racine, ".github/workflows/bee-ci.yml", "# workflow of " + racine + "\n")
        return base, pr

    def lancer(self, d, base, pr, base_sha, copie):
        """juges.sh, or (copie) the workflow's BEE_JUGES as the « Judges » step runs it."""
        amorcage = self.workflow()["env"]["BEE_COMMIT_AMORCAGE"]
        if copie:
            env = dict(os.environ, BEE_JUGES=self.workflow()["env"]["BEE_JUGES"], BEE_COMMIT_AMORCAGE=amorcage)
            commande = ["bash", "-e", "-c", f'export base="{base}" pr="{pr}" base_sha="{base_sha}" etats="{d}/etats"\neval "$BEE_JUGES"']
        else:
            env = dict(os.environ, ETATS=os.path.join(d, "etats"))
            env.pop("BEE_COMMIT_AMORCAGE", None)
            commande = ["bash", JUGES, base, pr, base_sha]
        r = subprocess.run(commande, capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr, lire(os.path.join(d, "etats", "juges.txt")), lire(os.path.join(d, "etats", "amorcage.txt"))

    def test_les_deux_copies_se_comportent_de_meme(self):
        amorcage = self.workflow()["env"]["BEE_COMMIT_AMORCAGE"]
        for copie in (False, True):
            with self.subTest(copie=copie):
                with tempfile.TemporaryDirectory() as d:  # the base's judges
                    base, pr = self.preparer(d, base_avec_bee=True)
                    code, sortie, juges, amorce = self.lancer(d, base, pr, "0" * 40, copie)
                    self.assertEqual((code, juges, amorce), (0, "succes\n", None), sortie)
                    self.assertIn("Judges: bee/ of the PR's base", sortie)
                    self.assertEqual(lire(os.path.join(base, "bee", "ci", "etape.sh")), "# " + base + "\n")
                with tempfile.TemporaryDirectory() as d:  # bootstrap: the pinned commit only
                    base, pr = self.preparer(d, base_avec_bee=False)
                    code, sortie, juges, amorce = self.lancer(d, base, pr, amorcage, copie)
                    self.assertEqual((code, juges, amorce), (0, "succes\n", "oui\n"), sortie)
                    self.assertIn("::warning::BOOTSTRAP:", sortie)
                    self.assertEqual(lire(os.path.join(base, "bee", "ci", "etape.sh")), "# " + pr + "\n")
                for sha, pr_avec_bee in (("1" * 40, True), (amorcage[:-1] + "0", True), (amorcage.upper(), True), ("", True),
                                         (amorcage, False)):
                    with self.subTest(sha=sha, pr_avec_bee=pr_avec_bee), tempfile.TemporaryDirectory() as d:
                        base, pr = self.preparer(d, base_avec_bee=False, pr_avec_bee=pr_avec_bee)
                        code, sortie, juges, amorce = self.lancer(d, base, pr, sha, copie)
                        self.assertEqual((code, juges, amorce), (1, "echec\n", None), sortie)
                        self.assertIn("::error::The PR's base", sortie)
                        self.assertFalse(os.path.exists(os.path.join(base, "bee")))


class JobOutillagePr(unittest.TestCase):
    """Job « Tests of the PR's CI tooling » of bee-ci.yml (libyaml-0022, on minizBee's model): when the PR modifies
    bee/ci/, bee/sandbox/ or this workflow, it runs its bee/ci/test_verdict.py in the base's sandbox; the PR's code, so
    read only, no artifact or output: only its result counts, and the verdict counts it (needs)."""

    executer = VerdictEnAnglais.executer

    def workflow(self):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_job_isole_et_compte_par_le_verdict(self):
        workflow = self.workflow()
        job = workflow["jobs"]["outillage-pr"]
        self.assertEqual((workflow["permissions"], job.get("permissions")), ({"contents": "read"}, {"contents": "read"}))
        self.assertNotIn("outputs", job)
        verdict = workflow["jobs"]["verdict"]
        self.assertEqual((verdict["if"], set(verdict["needs"])), ("always()", set(workflow["jobs"]) - {"verdict"}))
        self.assertEqual(set(JOBS_OK), set(verdict["needs"]))  # les résultats simulés ici sont ceux que le verdict reçoit
        noms = [e.get("name", "") for e in job["steps"]]
        i_juges = next(i for i, n in enumerate(noms) if n.startswith("Judges"))
        for i, e in enumerate(job["steps"]):
            texte = json.dumps(e)
            for interdit in ("upload-artifact", "actions/cache", "secrets.", "GITHUB_OUTPUT", "GITHUB_ENV"):
                self.assertNotIn(interdit, texte, noms[i])
            if "actions/checkout" in e.get("uses", ""):
                self.assertIs(e["with"]["persist-credentials"], False, noms[i])
            if i < i_juges:
                self.assertNotIn("base/bee", e.get("run", ""), noms[i])
        etape = job["steps"][-1]["run"]
        self.assertIn('git -C pr diff --quiet "$BASE_SHA...$TETE_SHA" -- bee/ci bee/sandbox .github/workflows/bee-ci.yml', etape)
        self.assertIn("cd pr && ../base/bee/sandbox/sans-docker.sh /usr/bin/python3 bee/ci/test_verdict.py", etape)
        self.assertLess(etape.index("sudo systemctl stop docker.socket docker\n"), etape.index("../base/bee/sandbox/sans-docker.sh"))
        self.assertNotRegex(etape, r"(python3?|bash|sh)\s+(\./)?pr/")  # le code de la PR ne tourne que dans la sandbox

    def lancer_etape(self, chemins, code_tests=0):
        """L'étape telle quelle, sur un petit dépôt git : sudo et la sandbox de la base remplacés par des témoins."""
        script = self.workflow()["jobs"]["outillage-pr"]["steps"][-1]["run"]
        with tempfile.TemporaryDirectory() as d:
            pr, journal = os.path.join(d, "pr"), os.path.join(d, "journal")
            git = lambda *a: subprocess.run(["git", "-C", pr] + list(a), capture_output=True, text=True, check=True, env=ENV_GIT).stdout.strip()  # noqa: E731
            os.makedirs(pr)
            git("init", "-q", "-b", "master")
            for chemin in ("src/parser.c", "bee/ci/vocabulaire.py", ".github/workflows/bee-ci.yml"):
                ecrire(pr, chemin, "a\n")
            git("add", "-A"), git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            for chemin in chemins:
                ecrire(pr, chemin, "b\n")
            git("add", "-A"), git("commit", "-q", "-m", "tete")
            ecrire(d, "bin/sudo", f'#!/bin/sh\necho "sudo $*" >> "{journal}"\n')
            ecrire(d, "base/bee/sandbox/sans-docker.sh", f'#!/bin/sh\necho "sandbox $(pwd) $*" >> "{journal}"\nexit {code_tests}\n')
            for temoin in ("bin/sudo", "base/bee/sandbox/sans-docker.sh"):
                os.chmod(os.path.join(d, temoin), 0o755)
            env = dict(os.environ, PATH=os.path.join(d, "bin") + os.pathsep + os.environ["PATH"], BASE_SHA=base,
                       TETE_SHA=git("rev-parse", "HEAD"))
            r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=d, capture_output=True, text=True, env=env)
            return r.returncode, (lire(journal) or "").splitlines(), pr

    def test_etape_lance_les_tests_de_la_pr_dans_la_sandbox(self):
        """bee/ci/ ou le workflow modifiés : les tests de la PR tournent dans la sandbox de la base, depuis la PR, après
        les préparatifs (sudo) ; leur échec rend le job rouge. Ni l'un ni l'autre modifié : rien ne tourne."""
        for chemins, code_tests, attendu in ((["bee/ci/vocabulaire.py"], 1, 1), (["bee/ci/nouveau.py"], 1, 1),
                                             ([".github/workflows/bee-ci.yml"], 1, 1), (["bee/sandbox/sans-docker.sh"], 1, 1),
                                             (["bee/ci/vocabulaire.py"], 0, 0)):
            with self.subTest(chemins=chemins, code_tests=code_tests):
                code, journal, pr = self.lancer_etape(chemins, code_tests)
                self.assertEqual(code, attendu, journal)
                self.assertEqual(journal[-1], f"sandbox {pr} /usr/bin/python3 bee/ci/test_verdict.py")
                self.assertTrue(journal[:-1] and all(l.startswith("sudo ") for l in journal[:-1]), journal)
                self.assertIn("sudo systemctl stop docker.socket docker", journal[:-1])  # Docker arrêté avant la PR
        code, journal, _ = self.lancer_etape(["src/parser.c"], 1)
        self.assertEqual((code, journal), (0, []))

    def test_sandbox_isole_processus_tmp_reseau_et_environnement(self):
        """bee/sandbox/sans-docker.sh, où tournent les tests de la PR : PID 1 dans son espace de noms, dont le /proc ne
        montre aucun processus de l'appelant ; un /tmp vide, à elle ; pas de réseau ; aucune variable de l'appelant ; le
        dépôt à sa racine. Aussi lancée dans une autre sandbox dont la table des montages de l'espace utilisateur
        (/run/mount/utab) est en lecture seule, comme sur un runner de GitHub : ses montages ne l'écrivent pas."""
        sandbox = os.path.join(os.path.dirname(ICI), "sandbox", "sans-docker.sh")
        # Espace de noms jetable où /run/mount/utab existe mais ne s'écrit pas (ses propres montages ne l'écrivent pas).
        utab_ro = ["unshare", "-rm", "--propagation", "private", "bash", "-c",
                   'set -e; mount -n -t tmpfs tmpfs /run; mkdir /run/mount; touch /run/mount/utab; '
                   'mount -n --bind /run/mount /run/mount; mount -n -o remount,ro,bind /run/mount; '
                   '! touch /run/mount/utab 2>/dev/null; exec "$@"', "-"]
        for enveloppe in ([], utab_ro):
            with self.subTest(utab_en_lecture_seule=bool(enveloppe)):
                self.verifier_sandbox(sandbox, enveloppe)

    def verifier_sandbox(self, sandbox, enveloppe):
        script = ('echo "pid=$$"; for f in /proc/[0-9]*/cmdline; do tr "\\0" " " < "$f"; echo; done | grep -c "^sleep 61" || true; '
                  'ls -A /tmp | wc -l; test -e "$1/temoin" && echo tmp-appelant || echo tmp-prive; echo "var=${BEE_TEMOIN:-absente}"; '
                  '/usr/bin/python3 -c "import socket; socket.create_connection((\'192.0.2.1\', 9), 1)" 2>/dev/null && echo reseau || echo sans-reseau; '
                  'cat temoin')
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            ecrire(d, "temoin", "depot\n")
            temoin = subprocess.Popen(["sleep", "61"])
            try:
                r = subprocess.run(enveloppe + ["bash", sandbox, "bash", "-c", script, "-", d], cwd=d, capture_output=True, text=True,
                                   env=dict(os.environ, BEE_TEMOIN="fuite"), timeout=60)
            finally:
                temoin.kill()
                temoin.wait()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["pid=1", "0", "0", "tmp-prive", "var=absente", "sans-reseau", "depot"], r.stderr)

    def test_le_verdict_compte_son_resultat(self):
        """Red if the job did not pass (failure, cancelled, skipped), even if a state file says « succes »."""
        ailleurs = [("etat-banc/etats/outillage_pr.txt", "succes\n")]
        for resultat in ("failure", "cancelled", "skipped"):
            with self.subTest(resultat=resultat):
                v = self.executer(jobs=dict(JOBS_OK, **{"outillage-pr": {"result": resultat}}), tache=TACHE, ailleurs=ailleurs)
                self.assertEqual((v["ci"], v["failed_step"]), ("red", "job outillage-pr"))
        v = self.executer(jobs=JOBS_OK, tache=TACHE)
        self.assertEqual((v["ci"], v["details"]["jobs"]["outillage-pr"]), ("green", "success"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
