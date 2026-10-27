#!/usr/bin/env python3
"""Génère le corpus de référence Bee pour libyaml, de façon déterministe.

Tout vient d'une graine fixe et d'un générateur pseudo-aléatoire écrit ici (SplitMix64),
en arithmétique entière : le résultat est identique bit pour bit quelle que soit la version
de Python (3.8 et plus) ou la machine. Aucune donnée n'est téléchargée. Le corpus mêle :
  - des documents YAML synthétiques variés (maps et séquences en bloc, styles de scalaires,
    profondeurs et tailles variées), sérialisés par un petit émetteur bloc correct écrit ici ;
  - des échantillons fixes écrits à la main qui couvrent ce que le synthétique n'atteint pas :
    style « flow », ancres et alias, multi-documents, commentaires, scalaires littéraux et pliés,
    guillemets avec échappements, tags, et quelques configurations réalistes.

Usage :
  python3 bee/corpus/generer.py                        génère dans bee/corpus/donnees/ et vérifie
  python3 bee/corpus/generer.py --verifier-seulement   vérifie les fichiers déjà générés
  python3 bee/corpus/generer.py --mettre-a-jour-sommes  réécrit bee/corpus/SHA256SUMS (réservé aux
                                                        tâches autorisées à changer le corpus)
Code de sortie : 0 si les sommes correspondent à bee/corpus/SHA256SUMS, 1 sinon.
"""

import argparse
import hashlib
import os
import sys

GRAINE = 0x1A4D2026BEE5
MASQUE = (1 << 64) - 1
ICI = os.path.dirname(os.path.abspath(__file__))
SOMMES_REFERENCE = os.path.join(ICI, "SHA256SUMS")
SORTIE_DEFAUT = os.path.join(ICI, "donnees")

MOTS = ("alpha beta gamma delta nom valeur service image port hote chemin cle liste "
        "actif faux vrai version config donnee reseau volume etape tache agent ruche "
        "miel alveole nombre texte objet groupe duree limite seuil poids score").split()


class Alea:
    """SplitMix64 : déterministe, indépendant de la plateforme."""
    def __init__(self, graine):
        self.etat = graine & MASQUE

    def suivant(self):
        self.etat = (self.etat + 0x9E3779B97F4A7C15) & MASQUE
        z = self.etat
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASQUE
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASQUE
        return (z ^ (z >> 31)) & MASQUE

    def entier(self, n):
        return self.suivant() % n if n > 0 else 0

    def mot(self):
        return MOTS[self.entier(len(MOTS))]


def scalaire(a):
    """Scalaire « sûr » (sans caractère spécial) : le synthétique reste lisible et valide."""
    choix = a.entier(5)
    if choix == 0:
        return str(a.entier(1000000))
    if choix == 1:
        return ("vrai", "faux", "null")[a.entier(3)]
    if choix == 2:
        return a.mot()
    return "-".join(a.mot() for _ in range(1 + a.entier(3)))


def structure(a, profondeur):
    """Dict / liste / scalaire imbriqués, clés et valeurs sûres."""
    if profondeur <= 0 or a.entier(3) == 0:
        return scalaire(a)
    if a.entier(2) == 0:
        n = 1 + a.entier(5)
        cles, obj = set(), {}
        for _ in range(n):
            c = a.mot()
            while c in cles:
                c = c + str(a.entier(100))
            cles.add(c)
            obj[c] = structure(a, profondeur - 1)
        return obj
    return [structure(a, profondeur - 1) for _ in range(1 + a.entier(6))]


def emettre(obj, niveau=0):
    """Émetteur YAML en style bloc, correct pour le sous-ensemble produit par structure()."""
    marge = "  " * niveau
    if isinstance(obj, dict):
        if not obj:
            return marge + "{}\n"
        out = []
        for cle, val in obj.items():
            if isinstance(val, (dict, list)) and val:
                out.append(f"{marge}{cle}:\n{emettre(val, niveau + 1)}")
            else:
                out.append(f"{marge}{cle}: {emettre_en_ligne(val)}\n")
        return "".join(out)
    if isinstance(obj, list):
        if not obj:
            return marge + "[]\n"
        out = []
        for val in obj:
            if isinstance(val, (dict, list)) and val:
                bloc = emettre(val, niveau + 1)
                # « - » suivi du premier élément sur la même ligne de marge augmentée :
                out.append(f"{marge}-\n{bloc}")
            else:
                out.append(f"{marge}- {emettre_en_ligne(val)}\n")
        return "".join(out)
    return marge + emettre_en_ligne(obj) + "\n"


def emettre_en_ligne(val):
    if isinstance(val, (dict, list)) and not val:
        return "{}" if isinstance(val, dict) else "[]"
    return str(val)


# Échantillons fixes : ce que le synthétique ne couvre pas. Chacun doit être du YAML valide.
FIXES = {
    "flow.yaml":
        "map: {a: 1, b: 2, c: [x, y, z], d: {e: f}}\n"
        "seq: [1, 2, [3, 4], {k: v}, ~, true, false]\n"
        "vide_map: {}\n"
        "vide_seq: []\n"
        "mixte: [{nom: a, val: 1}, {nom: b, val: 2}]\n",
    "ancres.yaml":
        "base: &base\n  moteur: libyaml\n  actif: true\n"
        "copie1:\n  <<: *base\n  nom: un\n"
        "copie2:\n  <<: *base\n  nom: deux\n"
        "liste: &l [alpha, beta]\n"
        "reutilise: *l\n"
        "noeud: &n valeur partagee\n"
        "ici: *n\n",
    "multidoc.yaml":
        "---\ndoc: 1\ncontenu: premier\n...\n"
        "---\ndoc: 2\ncontenu: second\n...\n"
        "---\n- a\n- b\n- c\n...\n",
    "scalaires.yaml":
        "plain: du texte simple\n"
        "double: \"ligne avec \\\" guillemet et \\t tabulation et \\n saut\"\n"
        "simple: 'texte avec '' apostrophe doublee'\n"
        "litteral: |\n  ligne 1\n  ligne 2\n    indentee\n  ligne 3\n"
        "plie: >\n  mot mot mot mot mot\n  mot mot mot mot mot\n\n  nouveau paragraphe\n"
        "nombres: [0, -1, 42, 3.14, 1e3, 0x1F, 0o17]\n"
        "speciaux: [~, null, true, false, yes, no, .inf, .nan]\n",
    "commentaires.yaml":
        "# commentaire de tête\n"
        "cle: valeur  # commentaire en ligne\n"
        "# entre deux\n"
        "liste:\n  - a  # premier\n  - b\n  # avant c\n  - c\n"
        "fin: ok\n",
    "tags.yaml":
        "explicite: !!str 123\n"
        "entier: !!int \"456\"\n"
        "booleen: !!bool \"true\"\n"
        "sequence: !!seq [a, b]\n"
        "map: !!map {k: v}\n"
        "perso: !monlabel donnee\n",
    "k8s.yaml":
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ruche\n  labels:\n    app: bee\n"
        "spec:\n  replicas: 3\n  selector:\n    matchLabels:\n      app: bee\n"
        "  template:\n    metadata:\n      labels:\n        app: bee\n"
        "    spec:\n      containers:\n        - name: abeille\n          image: bee:1.0\n"
        "          ports:\n            - containerPort: 8080\n"
        "          env:\n            - name: MODE\n              value: production\n"
        "          resources:\n            limits:\n              cpu: \"500m\"\n              memory: 256Mi\n",
    "ci.yaml":
        "name: integration\non:\n  push:\n    branches: [main]\n  pull_request: {}\n"
        "jobs:\n  construire:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: compiler\n        run: make\n"
        "      - name: tester\n        run: |\n          make test\n          echo fini\n"
        "  deployer:\n    needs: construire\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: ./deploy.sh\n",
    "profond.yaml": "a:\n" + "".join("  " * i + f"n{i}:\n" for i in range(1, 30)) + "  " * 30 + "fond: atteint\n",
}


def fichiers_synthetiques(a):
    """Noms triés, contenus déterministes. Tailles variées, du petit au gros."""
    fichiers = {}
    specs = [("petit", 12, 2, 8), ("moyen", 10, 3, 40), ("gros", 6, 4, 220), ("large", 3, 5, 700)]
    for prefixe, combien, prof, largeur in specs:
        for i in range(combien):
            racine = {}
            for j in range(largeur):
                racine[f"{a.mot()}_{j}"] = structure(a, prof)
            fichiers[f"syn-{prefixe}-{i:02d}.yaml"] = emettre(racine)
    return fichiers


def sommes_du_dossier(dossier):
    sommes = {}
    for nom in os.listdir(dossier):
        chemin = os.path.join(dossier, nom)
        if os.path.isfile(chemin):
            with open(chemin, "rb") as f:
                sommes[nom] = hashlib.sha256(f.read()).hexdigest()
    return sommes


def lire_sommes(chemin):
    sommes = {}
    if not os.path.exists(chemin):
        return sommes
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#"):
                somme, nom = ligne.split(None, 1)
                sommes[nom] = somme
    return sommes


def comparer(obtenues, attendues):
    problemes = []
    for nom in sorted(set(obtenues) | set(attendues)):
        if nom not in obtenues:
            problemes.append(f"manquant : {nom}")
        elif nom not in attendues:
            problemes.append(f"en trop : {nom}")
        elif obtenues[nom] != attendues[nom]:
            problemes.append(f"somme différente : {nom}")
    return problemes


def main():
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("--sortie", default=SORTIE_DEFAUT)
    analyseur.add_argument("--verifier-seulement", action="store_true")
    analyseur.add_argument("--mettre-a-jour-sommes", action="store_true")
    args = analyseur.parse_args()

    if not args.verifier_seulement:
        os.makedirs(args.sortie, exist_ok=True)
        a = Alea(GRAINE)
        fichiers = dict(FIXES)
        fichiers.update(fichiers_synthetiques(a))
        # Nettoie les fichiers obsolètes pour que le dossier corresponde exactement.
        for nom in os.listdir(args.sortie):
            if nom.endswith(".yaml") and nom not in fichiers:
                os.remove(os.path.join(args.sortie, nom))
        for nom, contenu in fichiers.items():
            with open(os.path.join(args.sortie, nom), "w", encoding="utf-8", newline="\n") as f:
                f.write(contenu)

    obtenues = sommes_du_dossier(args.sortie)
    total = sum(os.path.getsize(os.path.join(args.sortie, n)) for n in obtenues)

    if args.mettre_a_jour_sommes:
        with open(SOMMES_REFERENCE, "w", encoding="utf-8") as f:
            f.write("# Sommes SHA-256 du corpus de référence Bee pour libyaml (python3 bee/corpus/generer.py).\n")
            f.write("# Vérification manuelle : cd bee/corpus/donnees && grep -v '^#' ../SHA256SUMS | sha256sum -c\n")
            for nom in sorted(obtenues):
                f.write(f"{obtenues[nom]}  {nom}\n")
        print(f"SHA256SUMS réécrit : {len(obtenues)} fichiers, {total} octets.")
        return 0

    problemes = comparer(obtenues, lire_sommes(SOMMES_REFERENCE))
    if problemes:
        print("ÉCHEC : le corpus ne correspond pas à bee/corpus/SHA256SUMS :", file=sys.stderr)
        for p in problemes[:50]:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"Corpus conforme : {len(obtenues)} fichiers, {total} octets ({total / 1e6:.2f} Mo), dans {args.sortie}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
