#!/usr/bin/env python3
"""Tests de l'outillage de CI de libyamlBee (bee/ci/) : le registre et les manifestes lus dans leurs deux vocabulaires
(français, anglais), avant la bascule du registre en anglais (libyaml-0020, docs/english-migration.md du registre).

Couvre bee/ci/vocabulaire.py, bee/ci/tache.py et bee/ci/verifier_fork.py (de bout en bout par bee/ci/manifeste.sh, sur
un petit dépôt git et un faux registre dans chaque disposition), la métrique principale de bee/ci/verdict.py, deux
étapes du job « Manifeste et taille » de .github/workflows/bee-ci.yml et le job qui lance ces tests pour une PR
(« Tests de l'outillage de CI de la PR », compté par le verdict). À lancer dans la sandbox du fork :

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
WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(ICI)), ".github", "workflows", "bee-ci.yml")
ETAPES = ["juges", "manifeste_et_taille", "compilation_x86_64", "compilation_arm64", "determinisme_x86_64",
          "determinisme_arm64", "fuzzing", "banc_ab"]
JOBS_OK = {"manifeste": {"result": "success"}, "compilation-et-tests": {"result": "success"},
           "fuzzing": {"result": "success"}, "banc-ab": {"result": "success"}, "outillage-pr": {"result": "success"}}
# Dossier où chaque job dépose ses fichiers d'état dans son artefact (bee-ci.yml), écrit à la main : les tests vérifient
# verdict.py, ils ne le recopient pas. « juges » va dans --etats, le dossier du job verdict.
DOSSIER_ETAT = {"manifeste_et_taille": "etat-manifeste/etats", "compilation_x86_64": "etat-tests-x86_64",
                "determinisme_x86_64": "etat-tests-x86_64", "compilation_arm64": "etat-tests-arm64",
                "determinisme_arm64": "etat-tests-arm64", "fuzzing": "etat-fuzzing", "banc_ab": "etat-banc/etats"}
ENV_GIT = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

# Données écrites à la main dans chaque vocabulaire (docs/english-names.md du registre), jamais dérivées des cartes de
# bee/ci/vocabulaire.py : les tests vérifient les cartes, ils ne les recopient pas.
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
TACHE_EN = """id: libyaml-0050
project: libyaml
category: parsing-serialisation
type: optimization
size: S
title: essai
files: [src/scanner.c]
metric: debit_emission
compressed_output: may_change
status: reserved
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
PROJET_EN = """id: libyaml
name: libyaml
category: parsing-serialisation
upstream_repo: https://github.com/yaml/libyaml
license: MIT
status: active
metrics:
  - {id: debit_analyse, description: d, unit: MB/s, direction: higher, instructions: instructions_analyse}
  - {id: debit_chargement, description: d, unit: MB/s, direction: higher}
  - {id: debit_emission, description: d, unit: MB/s, direction: higher}
  - {id: memoire_max_ko, description: d, unit: KB, direction: lower}
paths_not_counted: ["bee/**", "tests/**"]
judge_paths: ["bee/**", "tests/**", ".github/**"]
"""
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
OPTIONS_FR = ("--tache", "--base", "--tete", "--depot", "--auteur")
OPTIONS_EN = ("--task", "--base", "--head", "--repo", "--author")
# Faux outil du registre, construit avec argparse comme le vrai : son aide nomme aussi, dans ses textes, les noms de
# l'autre vocabulaire, que seule la ligne d'usage doit compter. Il note ses appels (hors --help) dans journal.jsonl.
FAUX_OUTIL = '''import argparse, json, os, sys
ici = os.path.dirname(os.path.abspath(__file__))
p = argparse.ArgumentParser(prog="bee", description="Outil (verifier-fork, check-fork, --tache, --task, --registre, --registry).")
p.add_argument("--version", action="version", version="bee 0")
p.add_argument(GLOBALE, help="chemin du registre (ancien nom : --registre ; nouveau : --registry ; $BEE_REGISTRE)")
sous = p.add_subparsers(dest="commande", metavar="commande")
sous.add_parser("lister", help="liste ; voir aussi verifier-fork et check-fork")
for nom, options in COMMANDES:
    s = sous.add_parser(nom, help="vérifie une branche (" + nom + ")", description="--tache --task --tete --head --depot --repo")
    for o in options or ():
        s.add_argument(o, required=o in ("--tache", "--task", "--base"), help="aussi --tache --task --auteur --author")
a = p.parse_args()
with open(os.path.join(ici, "journal.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "BEE_REGISTRE": os.environ.get("BEE_REGISTRE"),
                        "BEE_REGISTRY": os.environ.get("BEE_REGISTRY")}) + "\\n")
sys.exit(int(open(os.path.join(ici, "code")).read()) if os.path.exists(os.path.join(ici, "code")) else 0)
'''


def faux_outil(globale, commandes):
    return f"GLOBALE = {globale!r}\nCOMMANDES = {commandes!r}\n" + FAUX_OUTIL


OUTIL_FR = faux_outil("--registre", [("verifier-fork", OPTIONS_FR)])
OUTIL_EN = faux_outil("--registry", [("check-fork", OPTIONS_EN)])


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


class Vocabulaire(unittest.TestCase):
    """bee/ci/vocabulaire.py : tâche, descripteur de projet et manifeste lus dans les deux vocabulaires, un seul par
    document."""

    def setUp(self):
        import yaml
        self.v = vocabulaire()
        self.yaml = yaml.safe_load

    def test_cartes_bijectives_et_disjointes(self):
        """Un nom n'est jamais des deux vocabulaires à la fois : sinon un document ne serait pas classable."""
        v = self.v
        for carte in (v.CLES_TACHE, v.CLES_PROJET, v.CLES_METRIQUE, v.CLES_MANIFESTE, v.CLES_AGENT, v.CLES_MESURES,
                      v.SORTIES):
            self.assertEqual(len(set(carte.values())), len(carte))
            self.assertFalse(set(carte) & set(carte.values()), carte)
        types = dict(v.TYPES)
        self.assertEqual(types.pop("test"), "test")
        self.assertFalse(set(types) & set(types.values()))

    def test_tache_dans_les_deux_vocabulaires(self):
        attendu = {"type": "optimisation", "metrique": "debit_emission", "sortie_compressee": "peut_changer"}
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_FR), self.v.METRIQUES), attendu)
        self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN), self.v.METRIQUES), attendu)
        for fr, en in (("optimisation", "optimization"), ("relecture", "review"), ("mesure", "measurement"),
                       ("test", "test"), ("decoupage", "split")):
            with self.subTest(type=en):
                self.assertEqual(self.v.lire_tache(self.yaml(TACHE_FR.replace("optimisation", fr)), ["debit_emission"])["type"], fr)
                self.assertEqual(self.v.lire_tache(self.yaml(TACHE_EN.replace("optimization", en)), ["debit_emission"])["type"], fr)
        sans_sortie = self.v.lire_tache(self.yaml(TACHE_EN.replace("compressed_output: may_change\n", "")), ["debit_emission"])
        self.assertEqual(sans_sortie["sortie_compressee"], "identique")  # absente : le contrôle le plus strict
        for texte in (TACHE_EN.replace("metric: debit_emission", "metric: null").replace("optimization", "test"),
                      TACHE_FR.replace("metrique: debit_emission", "metrique: null").replace("optimisation", "mesure")):
            self.assertIsNone(self.v.lire_tache(self.yaml(texte), self.v.METRIQUES)["metrique"])

    def test_tache_melee_refusee(self):
        for texte in (TACHE_FR.replace("statut: reservee", "status: reserved"),
                      TACHE_FR + "metric: debit_emission\n",
                      TACHE_EN.replace("compressed_output: may_change", "sortie_compressee: peut_changer"),
                      TACHE_EN.replace("type: optimization", "type: optimisation"),  # valeur de l'autre vocabulaire
                      TACHE_EN.replace("may_change", "peut_changer"),
                      TACHE_FR.replace("type: optimisation", "type: split")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte), self.v.METRIQUES)

    def test_tache_type_ou_metrique_illisible(self):
        """Jamais une valeur par défaut : type absent ou inconnu, clé de métrique absente, métrique hors de la liste
        donnée, optimisation sans métrique."""
        for texte in (TACHE_FR.replace("type: optimisation\n", ""), TACHE_EN.replace("optimization", "rapide"),
                      TACHE_FR.replace("metrique: debit_emission\n", ""), TACHE_EN.replace("metric: debit_emission\n", ""),
                      TACHE_EN.replace("debit_emission", "vitesse"), TACHE_FR.replace("debit_emission", "[debit_analyse]"),
                      "id: libyaml-0050\ntype: test\n", "- liste\n", "",
                      TACHE_EN.replace("metric: debit_emission", "metric: null"),
                      TACHE_FR.replace("metrique: debit_emission", "metrique: null")):
            with self.subTest(tache=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_tache(self.yaml(texte), self.v.METRIQUES)
        with self.assertRaises(self.v.Illisible):  # connue du banc, mais pas du descripteur donné
            self.v.lire_tache(self.yaml(TACHE_FR), ["debit_analyse"])
        with self.assertRaises(self.v.Illisible):
            self.v.metrique_de_la_tache(self.yaml("type: test\nstatus: open\n"))

    def test_projet_dans_les_deux_vocabulaires(self):
        attendu = ["debit_analyse", "debit_chargement", "debit_emission", "memoire_max_ko"]
        self.assertEqual(self.v.metriques_du_projet(self.yaml(PROJET_FR)), attendu)
        self.assertEqual(self.v.metriques_du_projet(self.yaml(PROJET_EN)), attendu)

    def test_projet_mele_ou_illisible(self):
        """Un vocabulaire par descripteur, métriques comprises ; sans liste de métriques lisible : jamais une liste
        vide (qui rendait autrefois toute métrique « aucune »)."""
        for texte in (PROJET_FR.replace("licence: MIT", "license: MIT"), PROJET_EN.replace("status: active", "statut: actif"),
                      PROJET_FR + "metrics: []\n", PROJET_EN.replace("metrics:", "metriques:"),
                      PROJET_FR.replace("unite: Ko", "unit: Ko"), PROJET_EN.replace("direction: lower", "sens: plus_bas"),
                      PROJET_FR.split("metriques:")[0], PROJET_EN.split("metrics:")[0] + "metrics: []\n",
                      PROJET_FR.split("metriques:")[0] + "metriques: debit_analyse\n",
                      PROJET_FR.split("metriques:")[0] + "metriques: 4\n",
                      PROJET_FR.replace("{id: debit_chargement, ", "{"), PROJET_EN.replace("id: memoire_max_ko", "id: 12"),
                      PROJET_FR.replace("  - {id: debit_chargement", "  - debit_chargement\n  - {id: x"),
                      "id: libyaml\nmetriques_x: []\n", "- libyaml\n", ""):
            with self.subTest(projet=texte), self.assertRaises(self.v.Illisible):
                self.v.metriques_du_projet(self.yaml(texte))

    def test_manifeste_dans_les_deux_vocabulaires(self):
        fr, en = self.v.lire_manifeste(self.yaml(MANIFESTE_FR)), self.v.lire_manifeste(self.yaml(MANIFESTE_EN))
        self.assertEqual(fr, en)
        self.assertEqual(fr, self.yaml(MANIFESTE_FR))
        self.assertEqual(en["mesures"]["avant"], {"debit_emission": 400})

    def test_manifeste_mele_refuse(self):
        """Un seul vocabulaire par manifeste, à tous ses niveaux (agent, mesures)."""
        for texte in (MANIFESTE_FR.replace("resume: r", "summary: r"), MANIFESTE_EN.replace("doubts: d", "doutes: d"),
                      MANIFESTE_FR.replace("avant:", "before:"), MANIFESTE_FR.replace("modele:", "model:"),
                      MANIFESTE_EN.replace("command:", "commande:"), MANIFESTE_FR + "measurements: {}\n"):
            with self.subTest(manifeste=texte), self.assertRaises(self.v.Illisible):
                self.v.lire_manifeste(self.yaml(texte))


class JobManifeste(unittest.TestCase):
    """bee/ci/manifeste.sh de bout en bout (tache.py, verifier_fork.py), sur un petit dépôt git et un faux registre
    dans chaque disposition : tâches, descripteur, outil, commande, options et manifeste lus dans les deux vocabulaires."""

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

    def lancer(self, manifestes, taches=(("taches", TACHE_FR),), outils=(("outils", OUTIL_FR),),
               projets=(("projets", PROJET_FR),), liens=()):
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
                   BEE_SORTIE_TACHE=copie, BEE_REGISTRE="/ailleurs", BEE_REGISTRY="/ailleurs")
        r = subprocess.run(["bash", MANIFESTE, self.pr, self.registre, sys.executable], capture_output=True, text=True,
                           env=env, cwd=self.d)
        self.sorties = dict(ligne.split("=", 1) for ligne in lire(sortie).split())
        self.copie = lire(copie)
        self.journal = [json.loads(ligne) for dossier, _ in outils
                        for ligne in (lire(os.path.join(self.registre, dossier, "journal.jsonl")) or "").splitlines()]
        self.tete = tete
        return r.returncode, r.stdout + r.stderr

    def appel(self, globale, commande, options):
        valeurs = ("libyaml-0050", self.base, self.tete, self.pr, "abeille")
        return [globale, self.registre, commande] + [x for paire in zip(options, valeurs) for x in paire]

    def refus(self, attendu, *args, **kwargs):
        """Le job échoue sans appeler l'outil ni écrire la copie de la tâche, ni sortir de métrique."""
        code, sortie = self.lancer(*args, **kwargs)
        self.sortie_job = sortie
        self.assertEqual((code, self.journal, self.copie), (1, [], None), sortie)
        self.assertNotIn("metrique", self.sorties)
        self.assertEqual(self.sorties.get("sortie_compressee"), "identique")
        self.assertIn(attendu, sortie)

    def test_registre_et_manifeste_francais(self):
        code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)])
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.journal, [{"argv": self.appel("--registre", "verifier-fork", OPTIONS_FR),
                                         "BEE_REGISTRE": self.registre, "BEE_REGISTRY": None}])
        self.assertEqual(self.sorties, {"tache": "libyaml-0050", "type": "optimisation", "metrique": "debit_emission",
                                        "sortie_compressee": "peut_changer", "manifeste": "manifestes/libyaml-0050.yaml"})
        self.assertEqual(self.copie, TACHE_FR)  # la copie lue par verdict.py : la tâche telle quelle

    def test_registre_et_manifeste_anglais(self):
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)], taches=(("tasks", TACHE_EN),),
                                   outils=(("tools", OUTIL_EN),), projets=(("projects", PROJET_EN),))
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.journal, [{"argv": self.appel("--registry", "check-fork", OPTIONS_EN),
                                         "BEE_REGISTRE": None, "BEE_REGISTRY": self.registre}])
        # Valeurs ramenées aux noms internes de libyamlBee.
        self.assertEqual(self.sorties, {"tache": "libyaml-0050", "type": "optimisation", "metrique": "debit_emission",
                                        "sortie_compressee": "peut_changer", "manifeste": "manifests/libyaml-0050.yaml"})
        self.assertEqual(self.copie, TACHE_EN)

    def test_dossiers_et_vocabulaires_independants(self):
        """Un vocabulaire par document, pas par registre : chaque document est lu dans le sien."""
        for manifeste, taches, outils, projets in (
                (("manifests/libyaml-0050.yaml", MANIFESTE_FR), (("taches", TACHE_FR),), (("outils", OUTIL_FR),), (("projects", PROJET_EN),)),
                (("manifestes/libyaml-0050.yaml", MANIFESTE_EN), (("tasks", TACHE_EN),), (("tools", OUTIL_EN),), (("projets", PROJET_FR),)),
                (("manifestes/libyaml-0050.yaml", MANIFESTE_FR), (("tasks", TACHE_FR),), (("outils", OUTIL_FR),), (("projets", PROJET_EN),))):
            with self.subTest(manifeste=manifeste[0], taches=taches[0][0], projets=projets[0][0]):
                self.setUp()
                code, sortie = self.lancer([manifeste], taches, outils, projets)
                self.assertEqual((code, len(self.journal), self.sorties["manifeste"], self.sorties["metrique"]),
                                 (0, 1, manifeste[0], "debit_emission"), sortie)

    def test_manifeste_mele_refuse(self):
        for texte in (MANIFESTE_EN.replace("summary: r", "resume: r"), MANIFESTE_FR.replace("avant:", "before:")):
            with self.subTest(manifeste=texte):
                self.setUp()
                self.refus("mêle les deux vocabulaires", [("manifests/libyaml-0050.yaml", texte)])

    def test_tache_type_ou_metrique_illisible_echoue(self):
        """Le job échoue, sans appeler l'outil ni écrire la copie de la tâche : jamais un défaut."""
        for dossier, texte in (("tasks", TACHE_EN.replace("type: optimization\n", "")),
                               ("taches", TACHE_FR.replace("optimisation", "inconnu")),
                               ("tasks", TACHE_EN.replace("metric: debit_emission\n", "")),
                               ("taches", TACHE_FR.replace("metrique: debit_emission\n", "")),
                               ("tasks", TACHE_EN.replace("debit_emission", "vitesse")),
                               ("tasks", TACHE_EN.replace("compressed_output: may_change", "sortie_compressee: peut_changer")),
                               ("taches", TACHE_FR.replace("optimisation", "optimization")), ("tasks", "- pas un objet\n"),
                               ("tasks", "tache: [illisible\n"),
                               ("tasks", TACHE_EN.replace("metric: debit_emission", "metric: null")),
                               ("taches", TACHE_FR.replace("metrique: debit_emission", "metrique: null"))):
            with self.subTest(dossier=dossier, tache=texte):
                self.setUp()
                self.refus("tâche libyaml-0050", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], taches=((dossier, texte),))
                self.assertIn("illisible", self.sortie_job)

    def test_metrique_connue_du_registre_et_mesuree_par_le_banc(self):
        """La métrique doit être dans le descripteur du registre ET dans celles que le banc mesure : une métrique que
        le registre ne liste pas est refusée ; une qu'il liste mais que le banc ne mesure pas aussi, dès cette étape
        (sans quoi elle ne serait refusée qu'au verdict, sous un autre nom)."""
        seule = PROJET_EN.split("metrics:")[0] + "metrics:\n  - {id: debit_analyse, unit: MB/s, direction: higher}\n"
        self.refus("inconnue", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=(("projects", seule),))
        for projets, tache in ((("projets", PROJET_FR.replace("id: debit_emission", "id: debit_nouveau")),
                                TACHE_FR.replace("debit_emission", "debit_nouveau")),
                               (("projects", PROJET_EN.replace("direction: lower}\n", "direction: lower}\n  - {id: latence, unit: ms, direction: lower}\n")),
                                TACHE_EN.replace("debit_emission", "latence"))):
            with self.subTest(projets=projets[0]):
                self.setUp()
                self.refus("ne mesure pas", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=(projets,),
                           taches=(("taches", tache),))
        self.setUp()
        code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)],
                                   taches=(("taches", TACHE_FR.replace("debit_emission", "memoire_max_ko")),))
        self.assertEqual((code, self.sorties.get("metrique")), (0, "memoire_max_ko"), sortie)

    def test_manifeste_illisible(self):
        """Un manifeste qui n'est pas de l'UTF-8, ou pas du YAML : échec net, sans trace d'exception."""
        for texte in (MANIFESTE_FR.encode("utf-8").replace(b"resume: r", b"resume: \xff\xfe r"),
                      MANIFESTE_FR.encode("latin-1", "replace") + "doutes_bis: é\n".encode("latin-1"),
                      b"tache: [libyaml-0050\n"):
            with self.subTest(texte=texte[-30:]):
                self.setUp()
                self.refus("manifeste illisible", [("manifestes/libyaml-0050.yaml", texte)])
                self.assertNotIn("Traceback", self.sortie_job)

    def test_manifeste_fichier_ordinaire(self):
        """Un manifeste est un fichier ordinaire : un lien symbolique (vers le dépôt ou hors de lui) ou un dossier
        est refusé avant toute lecture."""
        for manifestes, liens in (([("hors.yaml", MANIFESTE_FR)], [("manifestes/libyaml-0050.yaml", "../hors.yaml")]),
                                  ([], [("manifests/libyaml-0050.yaml", "DEHORS")]),
                                  ([("hors.yaml", MANIFESTE_FR)], [("CONTRIBUTION.yaml", "hors.yaml")]),
                                  ([("CONTRIBUTION.yaml/x", "a\n")], [])):
            with self.subTest(manifestes=manifestes, liens=liens):
                self.setUp()
                ecrire(self.d, "dehors.yaml", MANIFESTE_EN)  # hors du dépôt
                liens = [(c, os.path.join(self.d, "dehors.yaml") if cible == "DEHORS" else cible) for c, cible in liens]
                code, sortie = self.lancer(manifestes, liens=liens)
                self.assertEqual((code, self.journal, self.copie, self.sorties), (1, [], None, {}), sortie)
                self.assertIn("doit être un fichier ordinaire", sortie)

    def test_descripteur_illisible_echoue(self):
        for projets, attendu in (((("projets", PROJET_FR.replace("licence:", "license:")),), "mêle les deux vocabulaires"),
                                 ((("projects", PROJET_EN.split("metrics:")[0]),), "absente"),
                                 ((("projets", "- liste\n"),), "pas un objet"),
                                 ((("projets", "nom: [illisible\n"),), "illisible"),
                                 ((), "introuvable"),
                                 ((("projets", PROJET_FR), ("projects", PROJET_EN)), "plusieurs fois")):
            with self.subTest(projets=[p for p, _ in projets], attendu=attendu):
                self.setUp()
                self.refus(attendu, [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], projets=projets)

    def test_tache_introuvable_ou_dans_les_deux_dispositions(self):
        self.refus("introuvable", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], taches=())
        self.setUp()
        self.refus("plusieurs fois", [("manifestes/libyaml-0050.yaml", MANIFESTE_FR)],
                   taches=(("taches", TACHE_FR), ("tasks", TACHE_EN)))

    def test_deux_manifestes_refuses(self):
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN), ("manifestes/libyaml-0050.yaml", MANIFESTE_FR)])
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("plusieurs manifestes", sortie)

    def test_nom_de_manifeste(self):
        for chemin in ("manifests/libyaml-50.yaml", "manifests/sous/libyaml-0050.yaml", "manifestes/miniz-0050.yaml"):
            with self.subTest(chemin=chemin):
                self.setUp()
                code, sortie = self.lancer([(chemin, MANIFESTE_FR)])
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("Nom de manifeste invalide", sortie)
        self.setUp()
        code, sortie = self.lancer([("manifests/libyaml-0051.yaml", MANIFESTE_EN)])  # désigne libyaml-0050
        self.assertEqual((code, self.journal), (1, []), sortie)
        self.assertIn("doit s'appeler", sortie)

    def test_un_seul_outil(self):
        for outils in ((("outils", OUTIL_FR), ("tools", OUTIL_EN)), ()):
            with self.subTest(outils=[o for o, _ in outils]):
                self.setUp()
                code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], outils=outils)
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("exactement un outil", sortie)

    def test_commande_et_options_demandees_a_l_aide(self):
        """Jamais deviné : une commande sans les options voulues (un relais qui refuse l'ancien nom, par exemple)
        est écartée ; deux commandes complètes, aucune, une option dans les deux noms ou absente : échec."""
        bascule = faux_outil("--registry", [("verifier-fork", None), ("check-fork", OPTIONS_EN)])
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)], outils=(("tools", bascule),))
        self.assertEqual(code, 0, sortie)
        self.assertEqual([a["argv"] for a in self.journal], [self.appel("--registry", "check-fork", OPTIONS_EN)])
        melees = ("--tache", "--base", "--head", "--depot", "--author")
        self.setUp()
        code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)],
                                   outils=(("outils", faux_outil("--registre", [("check-fork", melees)])),))
        self.assertEqual(code, 0, sortie)  # l'aide annonce ces noms-là : ce sont eux qu'on passe
        self.assertEqual([a["argv"] for a in self.journal], [self.appel("--registre", "check-fork", melees)])
        for outil in (faux_outil("--registre", [("verifier-fork", OPTIONS_FR), ("check-fork", OPTIONS_EN)]),
                      faux_outil("--registre", []),
                      faux_outil("--registre", [("check-fork", OPTIONS_EN + ("--tache",))]),
                      faux_outil("--registre", [("check-fork", OPTIONS_EN[:4])]),
                      faux_outil("--registre", [("verifier-fork", OPTIONS_FR[:2] + OPTIONS_FR[3:])]),
                      faux_outil("--chemin", [("verifier-fork", OPTIONS_FR)]),
                      "import sys\nsys.exit(2)\n"):
            with self.subTest(outil=outil.splitlines()[:2]):
                self.setUp()
                code, sortie = self.lancer([("manifestes/libyaml-0050.yaml", MANIFESTE_FR)], outils=(("outils", outil),))
                self.assertEqual((code, self.journal), (1, []), sortie)
                self.assertIn("::error::verifier_fork.py", sortie)

    def test_code_de_l_outil_rendu(self):
        ecrire(self.registre, "tools/code", "1\n")
        code, sortie = self.lancer([("manifests/libyaml-0050.yaml", MANIFESTE_EN)], taches=(("tasks", TACHE_EN),),
                                   outils=(("tools", OUTIL_EN),), projets=(("projects", PROJET_EN),))
        self.assertEqual((code, len(self.journal)), (1, 1), sortie)


def rapport_ab(facteur=1):
    """Rapport d'ab.py : un gain différent par métrique, pour voir laquelle le verdict a retenue (et d'où vient le
    rapport : `facteur` multiplie les gains d'un rapport déposé ailleurs)."""
    gains = {m: facteur * g for m, g in
             {"debit_analyse": 0.01, "debit_chargement": 0.02, "debit_emission": 0.05, "memoire_max_ko": 0.0}.items()}
    return {"metriques": {m: {"gain": g, "au_dela_du_bruit": g >= 0.02, "degradation_au_dela_du_bruit": False,
                              "test_du_signe": {}} for m, g in gains.items()},
            "mesures": {"A": {m: 100.0 for m in gains}, "B": {m: 100.0 * (1 + g) for m, g in gains.items()}},
            "instructions": None}


class DeuxVocabulairesDansLeVerdict(unittest.TestCase):
    """verdict.py : la métrique de la copie de la tâche (artefact etat-manifeste), en anglais ou en français ;
    illisible, absente en CI ou venue d'un autre artefact : jamais un défaut, jamais la métrique de la PR."""

    def executer(self, jobs=JOBS_OK, tache=None, manifeste=None, ailleurs=(), ab=True, etats=None, liens=()):
        """Verdict sur des artefacts : chaque état (tous « succes » par défaut) là où son job le dépose, la copie de la
        tâche, le manifeste et ab.json à leur place, des fichiers `ailleurs`, et des liens symboliques `liens` (chemin,
        contenu) vers un fichier hors des artefacts."""
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
                ecrire(artefacts, "etat-banc/ab.json", json.dumps(rapport_ab()))
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

    def test_metrique_de_la_tache_dans_les_deux_vocabulaires(self):
        for tache in (TACHE_EN, TACHE_FR):
            with self.subTest(tache=tache):
                v = self.executer(tache=tache, manifeste=MANIFESTE_FR.replace("debit_emission", "debit_analyse"))
                self.assertEqual((v["ci"], v["metrique"], v["gain"], v["au_dela_du_bruit"]), ("verte", "debit_emission", 0.05, True))
                self.assertEqual(v["details"]["origine_metrique"], "tâche du registre")

    def test_tache_illisible_rend_rouge(self):
        """Copie absente en CI, mêlée, sans clé de métrique, métrique inconnue, pas un objet : rouge, et la PR ne
        choisit pas la métrique (le manifeste en désigne une)."""
        for tache in (None, "type: test\n", "metric: vitesse\n", "metrique: debit_analyse\nmetric: debit_analyse\n",
                      "metric: debit_analyse\nstatut: ouverte\n", "- debit_analyse\n", "id: libyaml-0050\ntype: test\n",
                      "metrique: [illisible\n"):
            with self.subTest(tache=tache):
                v = self.executer(tache=tache, manifeste=MANIFESTE_EN)
                self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"], v["gain"]), ("rouge", "Manifeste et taille", None, None))
                self.assertTrue(v["details"]["origine_metrique"].startswith("illisible"))

    def test_copie_de_la_tache_seulement_dans_etat_manifeste(self):
        """Un tache.yaml ou un manifeste déposé dans l'artefact d'un autre job n'est jamais lu."""
        autre = TACHE_FR.replace("debit_emission", "debit_analyse")
        v = self.executer(tache=TACHE_EN, ailleurs=[("etat-banc/etats/tache.yaml", autre), ("etat-banc/CONTRIBUTION.yaml", MANIFESTE_FR)])
        self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", "debit_emission", 0.05))
        v = self.executer(tache=None, ailleurs=[("etat-banc/etats/tache.yaml", autre)])
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))
        v = self.executer(jobs=None, tache=None, ailleurs=[("etat-tests-x86_64/tache.yaml", autre),
                                                           ("etat-fuzzing/CONTRIBUTION.yaml", MANIFESTE_FR)])
        self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", None, None))
        v = self.executer(tache=None, ailleurs=[("etat-manifeste/etats/tache.yaml", TACHE_EN)])  # racine seulement
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))

    def test_rapport_ab_seulement_dans_etat_banc(self):
        """ab.json n'est lu qu'à la racine de l'artefact du banc (etat-banc) : celui d'un autre artefact ou d'un
        sous-dossier, même rangé avant dans l'ordre alphabétique, n'est jamais lu."""
        faux = json.dumps(rapport_ab(facteur=10))
        ailleurs = [("etat-banc/AAA/ab.json", faux), ("etat-banc/etats/ab.json", faux), ("etat-fuzzing/ab.json", faux),
                    ("etat-tests-x86_64/ab.json", faux), ("etat-manifeste/ab.json", faux)]
        v = self.executer(tache=TACHE_FR, ailleurs=ailleurs)
        self.assertEqual((v["ci"], v["metrique"], v["gain"], v["mesures"]["B"]["debit_emission"]),
                         ("verte", "debit_emission", 0.05, 105.0))
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                v = self.executer(jobs=jobs, tache=TACHE_FR, ailleurs=ailleurs, ab=False)
                self.assertEqual((v["metrique"], v["gain"], v["au_dela_du_bruit"], v["mesures"]["B"]["debit_emission"]),
                                 ("debit_emission", None, False, None))

    def test_etat_lu_seulement_dans_le_dossier_de_son_job(self):
        """Chaque <etape>.txt n'est lu que dans le dossier d'état du job qui l'écrit : un « succes » déposé dans un autre
        artefact, dans le dossier d'un autre job, à la racine ou dans un sous-dossier du bon artefact ne remplace pas un
        état manquant (rouge, sans résultat) ; un état qui est un lien symbolique non plus."""
        self.assertEqual(self.executer(tache=TACHE_FR)["ci"], "verte")  # le parcours honnête
        for manquante, proprietaire in DOSSIER_ETAT.items():
            autre = "etat-manifeste/etats" if proprietaire != "etat-manifeste/etats" else "etat-fuzzing"
            dossiers = ["juge", "etat-evil", "etat-evil/etats", "x/etats", autre, proprietaire + "/sous"]
            dossiers += [proprietaire.split("/")[0]] if "/" in proprietaire else []
            etats = {e: "succes" for e in ETAPES if e != manquante}
            with self.subTest(manquante=manquante):
                v = self.executer(tache=TACHE_FR, etats=etats, ailleurs=[(f"{d}/{manquante}.txt", "succes\n") for d in dossiers])
                self.assertEqual((v["ci"], v["etapes"][manquante]), ("rouge", "absent"))
                v = self.executer(tache=TACHE_FR, etats=etats, liens=[(f"{proprietaire}/{manquante}.txt", "succes\n")])
                self.assertEqual((v["ci"], v["etapes"][manquante]), ("rouge", "absent"))
        v = self.executer(tache=TACHE_FR, ailleurs=[("etat-evil/amorcage.txt", "oui\n"), ("x/etats/amorcage.txt", "oui\n")])
        self.assertFalse(v["amorcage"])
        self.assertTrue(self.executer(tache=TACHE_FR, ailleurs=[("etat-fuzzing/amorcage.txt", "oui\n")])["amorcage"])

    def test_lien_symbolique_jamais_lu(self):
        """La copie de la tâche et ab.json ne sont jamais lus à travers un lien symbolique, même à leur place."""
        v = self.executer(tache=None, liens=[("etat-manifeste/tache.yaml", TACHE_FR)])
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))
        v = self.executer(tache=TACHE_FR, ab=False, liens=[("etat-banc/ab.json", json.dumps(rapport_ab()))])
        self.assertEqual((v["metrique"], v["gain"]), ("debit_emission", None))

    def test_metrique_null_jamais_celle_du_manifeste(self):
        tache = TACHE_EN.replace("metric: debit_emission", "metric: null").replace("optimization", "test")
        for jobs in (JOBS_OK, None):
            with self.subTest(ci=jobs is not None):
                v = self.executer(jobs=jobs, tache=tache, manifeste=MANIFESTE_FR)
                self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", None, None))
                self.assertEqual(v["details"]["origine_metrique"], "tâche du registre (metrique: null)")

    def test_simulation_sans_tache_lit_le_manifeste(self):
        """Hors CI seulement, sans copie de la tâche : le manifeste, dans un seul vocabulaire."""
        for manifeste in (MANIFESTE_EN, MANIFESTE_FR, "metric: debit_emission\ntask: libyaml-0050\n",
                          "metrique: debit_emission\ntache: libyaml-0050\n"):
            with self.subTest(manifeste=manifeste):
                v = self.executer(jobs=None, manifeste=manifeste)
                self.assertEqual((v["ci"], v["metrique"], v["gain"]), ("verte", "debit_emission", 0.05))
        v = self.executer(jobs=None, manifeste=MANIFESTE_EN.replace("before:", "avant:"))
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))
        v = self.executer(jobs=JOBS_OK, manifeste=MANIFESTE_EN)  # en CI, jamais : la copie de la tâche manque
        self.assertEqual((v["ci"], v["etape_en_echec"], v["metrique"]), ("rouge", "Manifeste et taille", None))

    def test_lignes_hors_manifestes_des_deux_dossiers(self):
        """R1 : manifests/** et manifestes/** hors décompte, comme bee/**, tests/** et CONTRIBUTION.yaml."""
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
                self.assertEqual(json.load(f)["lignes_modifiees"], 2)


class EtapesDuWorkflow(unittest.TestCase):
    """Deux étapes du job manifeste de bee-ci.yml, extraites telles quelles : le fichier d'exigences qui existe (un
    seul), et le manifeste conservé depuis manifests/ ou manifestes/."""

    def script(self, debut):
        import yaml
        with open(WORKFLOW, encoding="utf-8") as f:
            etapes = yaml.safe_load(f)["jobs"]["manifeste"]["steps"]
        scripts = [e["run"] for e in etapes if e.get("name", "").startswith(debut)]
        self.assertEqual(len(scripts), 1, debut)
        return scripts[0]

    def exigences(self, fichiers):
        script = self.script("Dépendances de l'outil bee")
        with tempfile.TemporaryDirectory() as d:
            for chemin in fichiers:
                ecrire(d, chemin, "pyyaml>=6\n")
            ecrire(d, "bin/pip", '#!/bin/sh\necho "$@" > "$(dirname "$0")/../appel"\n')
            os.chmod(os.path.join(d, "bin", "pip"), 0o755)
            env = dict(os.environ, PATH=os.path.join(d, "bin") + os.pathsep + os.environ["PATH"])
            r = subprocess.run(["bash", "-e", "-c", script], cwd=d, capture_output=True, text=True, env=env)
            appel = (lire(os.path.join(d, "appel")) or "").strip() or None
        return r.returncode, appel, r.stderr

    def test_exigences_le_fichier_qui_existe(self):
        self.assertEqual(self.exigences(["registre/outils/requirements.txt"])[:2], (0, "install -r registre/outils/requirements.txt"))
        self.assertEqual(self.exigences(["registre/tools/requirements.txt"])[:2], (0, "install -r registre/tools/requirements.txt"))

    def test_exigences_aucun_ou_deux_echoue(self):
        for fichiers in ([], ["registre/outils/requirements.txt", "registre/tools/requirements.txt"]):
            with self.subTest(fichiers=fichiers):
                code, appel, erreur = self.exigences(fichiers)
                self.assertEqual((code, appel), (1, None))
                self.assertIn("::error::", erreur)

    def test_manifeste_conserve_des_deux_dossiers(self):
        script = self.script("Conserver le manifeste")
        for chemin, garde, lien in (("manifests/libyaml-0050.yaml", True, False), ("manifestes/libyaml-0050.yaml", True, False),
                                    ("CONTRIBUTION.yaml", True, False), ("manifests/libyaml-50.yaml", False, False),
                                    ("autre/libyaml-0050.yaml", False, False), ("manifests/../tache.yaml", False, False),
                                    # un manifeste est un fichier ordinaire : un lien symbolique n'est pas copié
                                    ("manifests/libyaml-0050.yaml", False, True), ("CONTRIBUTION.yaml", False, True)):
            with self.subTest(chemin=chemin, lien=lien), tempfile.TemporaryDirectory() as d:
                ecrire(d, "dehors.yaml" if lien else "pr/" + chemin, "tache: libyaml-0050\n")
                if lien:
                    os.makedirs(os.path.dirname(os.path.join(d, "pr", chemin)), exist_ok=True)
                    os.symlink(os.path.join(d, "dehors.yaml"), os.path.join(d, "pr", chemin))
                env = dict(os.environ, MANIFESTE=chemin, ETATS=os.path.join(d, "etats"))
                r = subprocess.run(["bash", "-e", "-c", script], cwd=d, capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(os.path.exists(os.path.join(d, "donnees", "CONTRIBUTION.yaml")), garde)


class JobOutillagePr(unittest.TestCase):
    """Job « Tests de l'outillage de CI de la PR » de bee-ci.yml (libyaml-0022, sur le modèle de minizBee) : quand la PR
    modifie bee/ci/, bee/sandbox/ ou ce workflow, il lance son bee/ci/test_verdict.py dans la sandbox de la base ; code de la PR, donc
    lecture seule, ni artefact ni sortie : seul son résultat compte, et le verdict le compte (needs)."""

    executer = DeuxVocabulairesDansLeVerdict.executer

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
        i_juges = next(i for i, n in enumerate(noms) if n.startswith("Juges"))
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
        dépôt à sa racine."""
        sandbox = os.path.join(os.path.dirname(ICI), "sandbox", "sans-docker.sh")
        script = ('echo "pid=$$"; for f in /proc/[0-9]*/cmdline; do tr "\\0" " " < "$f"; echo; done | grep -c "^sleep 61" || true; '
                  'ls -A /tmp | wc -l; test -e "$1/temoin" && echo tmp-appelant || echo tmp-prive; echo "var=${BEE_TEMOIN:-absente}"; '
                  '/usr/bin/python3 -c "import socket; socket.create_connection((\'192.0.2.1\', 9), 1)" 2>/dev/null && echo reseau || echo sans-reseau; '
                  'cat temoin')
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            ecrire(d, "temoin", "depot\n")
            temoin = subprocess.Popen(["sleep", "61"])
            try:
                r = subprocess.run(["bash", sandbox, "bash", "-c", script, "-", d], cwd=d, capture_output=True, text=True,
                                   env=dict(os.environ, BEE_TEMOIN="fuite"), timeout=60)
            finally:
                temoin.kill()
                temoin.wait()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["pid=1", "0", "0", "tmp-prive", "var=absente", "sans-reseau", "depot"], r.stderr)

    def test_le_verdict_compte_son_resultat(self):
        """Rouge si le job n'a pas réussi (échec, annulé, sauté), même si un fichier d'état dit « succes »."""
        ailleurs = [("etat-banc/etats/outillage_pr.txt", "succes\n")]
        for resultat in ("failure", "cancelled", "skipped"):
            with self.subTest(resultat=resultat):
                v = self.executer(jobs=dict(JOBS_OK, **{"outillage-pr": {"result": resultat}}), tache=TACHE_FR, ailleurs=ailleurs)
                self.assertEqual((v["ci"], v["etape_en_echec"]), ("rouge", "job outillage-pr"))
        v = self.executer(jobs=JOBS_OK, tache=TACHE_FR)
        self.assertEqual((v["ci"], v["details"]["jobs"]["outillage-pr"]), ("verte", "success"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
