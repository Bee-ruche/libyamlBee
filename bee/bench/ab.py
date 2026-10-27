#!/usr/bin/env python3
"""Banc A/B entrelacé de Bee pour miniz.

Compare deux révisions de miniz sur le corpus de référence :

  python3 bee/bench/ab.py --base <rev> --candidate <rev> [--repetitions 10] [--instructions] [--json sortie.json]

Déroulement :
  1. Chaque révision est extraite dans un dossier temporaire séparé (git worktree, en mode détaché).
     La valeur spéciale « :travail » désigne la copie de travail courante, modifications non commitées comprises.
  2. Le banc (bee/bench/banc.c) et le Makefile de l'outillage courant (le dossier bee/ qui contient ce
     script) sont compilés contre les sources de miniz de chaque révision : seul le code de la
     bibliothèque diffère entre A et B, le banc est le même.
  3. Après une exécution de chauffe non comptée de chacun (--chauffe), les deux binaires tournent en
     alternance stricte, A, B, A, B…, N fois chacun ; chaque exécution mesure les six métriques. Dans une
     exécution, chaque débit est le meilleur de k passes sur le corpus (voir banc.c). On retient la
     médiane des N valeurs de chaque métrique pour A et pour B.
  4. Gain relatif (positif = mieux) : médiane(B) / médiane(A) - 1 pour une métrique « plus haut »,
     1 - médiane(B) / médiane(A) pour une métrique « plus bas » (memoire_max_ko).
  5. Bruit, par un test du signe sur les paires entrelacées. La répétition i mesure A_i puis B_i côte à
     côte : la paire i subit à peu près la même charge de la machine. B « gagne » la paire si B_i est
     meilleur que A_i (plus haut, ou plus bas pour memoire_max_ko). Les paires à égalité sont écartées
     (test du signe standard) : N désigne ensuite le nombre de paires non égales. Si A et B sont
     équivalents, le nombre X de paires gagnées par B suit une loi binomiale (N, 1/2).
     Seuil : k = plus petit entier tel que P(X >= k | N, 1/2) <= 0,02 (test unilatéral) :
         N  :  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20
         k  :  6  7  8  8  9 10 10 11 12 12 13 14 14 15 16
     Pour N = 10, k = 9 (p = 0,0107). En dessous de 6 paires non égales, aucun seuil n'atteint 0,02 :
     rien n'est « au-delà du bruit » (ab.py prévient si --repetitions est inférieur à 6).
       - au_dela_du_bruit : B gagne au moins k paires (amélioration significative) ;
       - degradation_au_dela_du_bruit : A gagne au moins k paires (dégradation significative, pour R5).
     Métrique déterministe (ratio_n6) : si rien ne change, toutes les paires sont à égalité, et le
     test ne conclut ni à un gain ni à une dégradation ; si la valeur change, B gagne (ou perd) toutes
     les paires, et l'écart est significatif. memoire_max_ko est presque déterministe : les
     égalités sont écartées, et l'écart se juge sur les seules paires différentes.
     Tests unitaires : python3 bee/bench/test_ab.py
     Les intervalles [min, max] sont gardés dans le JSON à titre d'information (minmax_disjoints) ; ce
     critère, plus prudent, n'avait pas vu un ralentissement réel de 5 % au niveau 6.
  6. Avec --instructions, chaque binaire passe aussi sous valgrind --tool=cachegrind, une fois par
     scénario (n1, n6, n9, decompression) sur un sous-ensemble du corpus (les 128 premiers Kio de
     chaque fichier, environ 3,3 Mo). Seules les passes chronométrées sont comptées (requêtes client
     Cachegrind). Le décompte est reproductible ; un écart est « au-delà du bruit » s'il dépasse
     --seuil-instructions (0,2 % par défaut).

Sortie : le JSON sur stdout (et dans --json), un tableau lisible sur stderr.
Code de sortie : 0 si la mesure a abouti (quel que soit le résultat), 2 en cas d'erreur.
"""

import argparse
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ICI = os.path.dirname(os.path.abspath(__file__))
OUTILLAGE = os.path.dirname(ICI)  # dossier bee/

# Mêmes définitions que projets/libyaml.yaml dans le registre Bee.
METRIQUES = [
    ("debit_analyse", "plus_haut", "Mo/s"),
    ("debit_chargement", "plus_haut", "Mo/s"),
    ("debit_emission", "plus_haut", "Mo/s"),
    ("memoire_max_ko", "plus_bas", "Ko"),
]
SCENARIOS_INSTRUCTIONS = ["analyse", "chargement", "emission"]
TRAVAIL = ":travail"


class Erreur(Exception):
    pass


def executer(commande, **options):
    resultat = subprocess.run(commande, capture_output=True, text=True, **options)
    if resultat.returncode != 0:
        raise Erreur(f"échec de « {' '.join(commande)} » (code {resultat.returncode}) :\n"
                     f"{resultat.stdout[-2000:]}{resultat.stderr[-4000:]}")
    return resultat.stdout


def racine_git(dossier):
    return executer(["git", "-C", dossier, "rev-parse", "--show-toplevel"]).strip()


def resoudre(depot, rev):
    if rev == TRAVAIL:
        tete = executer(["git", "-C", depot, "rev-parse", "HEAD"]).strip()
        sale = bool(executer(["git", "-C", depot, "status", "--porcelain", "--untracked-files=no"]).strip())
        return {"rev": rev, "commit": tete, "modifications_non_commitees": sale}
    try:
        commit = executer(["git", "-C", depot, "rev-parse", "--verify", "--quiet", rev + "^{commit}"]).strip()
    except Erreur:
        raise Erreur(f"révision inconnue : {rev} (essayez git fetch, ou un identifiant de commit)")
    return {"rev": rev, "commit": commit}


def preparer_source(depot, info, dossier_travail, etiquette):
    """Renvoie le dossier qui contient les sources de miniz de la révision."""
    if info["rev"] == TRAVAIL:
        return depot, None
    chemin = os.path.join(dossier_travail, "source-" + etiquette)
    executer(["git", "-C", depot, "worktree", "add", "--detach", "--force", chemin, info["commit"]])
    return chemin, chemin


def compiler(source, dossier_travail, etiquette):
    constr = os.path.join(dossier_travail, "construction-" + etiquette)
    environnement = dict(os.environ)
    executer(["make", "--no-print-directory", "-s", "-C", OUTILLAGE, f"SOURCE={source}", f"CONSTR={constr}", "banc"],
             env=environnement)
    binaire = os.path.join(constr, "banc")
    if not os.path.exists(binaire):
        raise Erreur(f"le banc n'a pas été produit pour {etiquette}")
    return binaire


def fixer_cpu(cpu):
    if cpu is None:
        return None
    return lambda: os.sched_setaffinity(0, {cpu})


def lancer_banc(binaire, corpus, options_banc, cpu):
    sortie = subprocess.run([binaire, "--corpus", corpus] + options_banc, capture_output=True, text=True,
                            preexec_fn=fixer_cpu(cpu))
    if sortie.returncode != 0:
        raise Erreur(f"le banc {binaire} a échoué (code {sortie.returncode}) : {sortie.stderr.strip()}")
    try:
        return json.loads(sortie.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Erreur(f"sortie illisible du banc {binaire} : {sortie.stdout!r}")


def compter_instructions(binaire, corpus, scenario, dossier_travail, etiquette, prefixe):
    if shutil.which("valgrind") is None:
        raise Erreur("--instructions demande valgrind, introuvable dans le PATH")
    info = json.loads(executer([binaire, "--info"]))
    fichier = os.path.join(dossier_travail, f"cachegrind-{etiquette}-{scenario}.out")
    commande = ["valgrind", "--tool=cachegrind", "--cache-sim=no", f"--cachegrind-out-file={fichier}"]
    if info.get("cachegrind_requetes_client"):
        commande.append("--instr-at-start=no")
    commande += [binaire, "--corpus", corpus, "--scenario", scenario, "--passes", "1", "--prefixe", str(prefixe),
                 "--sans-memoire"]
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0:
        raise Erreur(f"cachegrind a échoué pour {etiquette}/{scenario} : {resultat.stderr[-2000:]}")
    trouve = re.search(r"I\s+refs:\s+([\d,]+)", resultat.stderr)
    if not trouve:
        raise Erreur(f"décompte d'instructions introuvable dans la sortie de cachegrind ({etiquette}/{scenario})")
    return int(trouve.group(1).replace(",", "")), bool(info.get("cachegrind_requetes_client"))


SEUIL_TEST_DU_SIGNE = 0.02


def seuil_signe(n, alpha=SEUIL_TEST_DU_SIGNE):
    """Plus petit k tel que P(X >= k | n, 1/2) <= alpha ; None si aucun (n trop petit)."""
    for k in range(n + 1):
        if sum(math.comb(n, j) for j in range(k, n + 1)) / 2 ** n <= alpha:
            return k
    return None


def p_unilaterale(n, k):
    return sum(math.comb(n, j) for j in range(k, n + 1)) / 2 ** n


def test_du_signe(valeurs_a, valeurs_b, sens):
    """Test du signe standard sur les paires (A_i, B_i).

    Les égalités sont écartées ; le seuil k et les valeurs p se calculent sur les N' paires restantes.
    Si toutes les paires sont à égalité (N' = 0), il n'y a ni gain ni dégradation."""
    paires = [(a, b) for a, b in zip(valeurs_a, valeurs_b) if a is not None and b is not None]
    meilleur = (lambda a, b: b > a) if sens == "plus_haut" else (lambda a, b: b < a)
    victoires_b = sum(1 for a, b in paires if meilleur(a, b))
    victoires_a = sum(1 for a, b in paires if meilleur(b, a))
    n_utiles = victoires_a + victoires_b
    k = seuil_signe(n_utiles) if n_utiles else None
    return {
        "paires": len(paires), "paires_utiles": n_utiles,
        "victoires_B": victoires_b, "victoires_A": victoires_a, "egalites": len(paires) - n_utiles,
        "seuil_k": k,
        "p_amelioration": p_unilaterale(n_utiles, victoires_b) if n_utiles else None,
        "p_degradation": p_unilaterale(n_utiles, victoires_a) if n_utiles else None,
        "au_dela_du_bruit": k is not None and victoires_b >= k,
        "degradation_au_dela_du_bruit": k is not None and victoires_a >= k,
    }


def resume(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    if not valeurs:
        return {"mediane": None, "min": None, "max": None, "valeurs": []}
    return {"mediane": statistics.median(valeurs), "min": min(valeurs), "max": max(valeurs), "valeurs": valeurs}


def gain_relatif(a, b, sens):
    if a in (None, 0) or b is None:
        return None
    return (b / a - 1.0) if sens == "plus_haut" else (1.0 - b / a)


def description_machine():
    modele = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for ligne in f:
                if ligne.lower().startswith(("model name", "cpu model")):
                    modele = ligne.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    compilateur = os.environ.get("CC", "cc")
    try:
        version = subprocess.run([compilateur, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    except (OSError, IndexError):
        version = compilateur
    return {"processeur": modele, "architecture": platform.machine(), "coeurs": os.cpu_count(),
            "systeme": platform.platform(), "compilateur": version}


def afficher_tableau(rapport):
    lignes = [f"{'métrique':26s} {'médiane A':>12s} {'médiane B':>12s} {'gain':>8s}  {'B gagne':>8s}  verdict"]
    for nom, m in rapport["metriques"].items():
        a, b = m["A"], m["B"]
        if a["mediane"] is None:
            continue
        s = m["test_du_signe"]
        gain = "-" if m["gain"] is None else f"{100 * m['gain']:+.2f} %"
        if m["au_dela_du_bruit"]:
            verdict = "amélioration au-delà du bruit"
        elif m["degradation_au_dela_du_bruit"]:
            verdict = "DÉGRADATION au-delà du bruit"
        else:
            verdict = "dans le bruit"
        lignes.append(f"{nom:26s} {a['mediane']:12.3f} {b['mediane']:12.3f} {gain:>8s}  "
                      f"{s['victoires_B']:>3d}/{s['paires_utiles']:<4d}  {verdict}"
                      + (f" ({s['egalites']} égalités écartées)" if s["egalites"] else ""))
    for nom, m in (rapport.get("instructions") or {}).items():
        gain = "-" if m["gain"] is None else f"{100 * m['gain']:+.3f} %"
        if not m["au_dela_du_bruit"]:
            verdict = "dans le bruit"
        else:
            verdict = "moins d'instructions" if m["gain"] > 0 else "PLUS d'instructions"
        lignes.append(f"{nom:26s} {m['A']:12d} {m['B']:12d} {gain:>8s}  {'':>8s}  {verdict}")
    print("\n".join(lignes), file=sys.stderr)


def main():
    analyseur = argparse.ArgumentParser(description="Banc A/B entrelacé de Bee pour miniz (voir l'aide du module).")
    analyseur.add_argument("--base", required=True, help="révision A (référence), par ex. upstream/master ou un commit")
    analyseur.add_argument("--candidate", required=True, help="révision B (candidate), par ex. HEAD ; « :travail » pour la copie de travail")
    analyseur.add_argument("--repetitions", type=int, default=10, help="exécutions de chaque binaire (défaut 10)")
    analyseur.add_argument("--chauffe", type=int, default=1,
                           help="exécutions non comptées de A puis B avant la mesure (défaut 1 : caches et fréquence à chaud)")
    analyseur.add_argument("--instructions", action="store_true", help="compte aussi les instructions avec cachegrind")
    analyseur.add_argument("--json", help="écrit aussi le rapport JSON dans ce fichier")
    analyseur.add_argument("--depot", default=os.path.dirname(OUTILLAGE), help="dépôt git de miniz (défaut : celui de ce script)")
    analyseur.add_argument("--corpus", help="dossier du corpus (défaut : bee/corpus/donnees, régénéré et vérifié)")
    analyseur.add_argument("--passes", help="transmis au banc (--passes K) : nombre de passes par exécution")
    analyseur.add_argument("--cpu", type=int, help="épingle les exécutions sur ce cœur (sched_setaffinity)")
    analyseur.add_argument("--prefixe-instructions", type=int, default=131072, help="octets gardés par fichier pour cachegrind")
    analyseur.add_argument("--seuil-instructions", type=float, default=0.002, help="écart relatif d'instructions jugé significatif")
    analyseur.add_argument("--garder", action="store_true", help="ne supprime pas le dossier temporaire (diagnostic)")
    args = analyseur.parse_args()

    if args.repetitions < 1:
        raise Erreur("--repetitions doit valoir au moins 1")
    depot = racine_git(args.depot)
    base, candidat = resoudre(depot, args.base), resoudre(depot, args.candidate)

    corpus = args.corpus
    if corpus is None:
        corpus = os.path.join(OUTILLAGE, "corpus", "donnees")
        resultat = subprocess.run([sys.executable, os.path.join(OUTILLAGE, "corpus", "generer.py")], capture_output=True, text=True)
        if resultat.returncode != 0:
            raise Erreur("corpus non conforme : " + resultat.stderr.strip())
    options_banc = ["--passes", args.passes] if args.passes else []

    dossier_travail = tempfile.mkdtemp(prefix="bee-ab-")
    worktrees = []
    debut = time.time()
    try:
        print(f"ab : A = {base['rev']} ({base['commit'][:12]}), B = {candidat['rev']} ({candidat['commit'][:12]})", file=sys.stderr)
        source_a, wt = preparer_source(depot, base, dossier_travail, "A")
        worktrees.append(wt)
        source_b, wt = preparer_source(depot, candidat, dossier_travail, "B")
        worktrees.append(wt)
        binaires = {"A": compiler(source_a, dossier_travail, "A"), "B": compiler(source_b, dossier_travail, "B")}

        for i in range(args.chauffe):
            for etiquette in ("A", "B"):
                lancer_banc(binaires[etiquette], corpus, options_banc, args.cpu)
        mesures = {"A": [], "B": []}
        for i in range(args.repetitions):
            for etiquette in ("A", "B"):
                mesures[etiquette].append(lancer_banc(binaires[etiquette], corpus, options_banc, args.cpu))
            print(f"ab : répétition {i + 1}/{args.repetitions} faite", file=sys.stderr)

        rapport = {
            "base": base, "candidat": candidat, "repetitions": args.repetitions, "chauffe": args.chauffe,
            "ordre": "A, B, A, B…",
            "machine": description_machine(),
            "methode": {
                "valeur_retenue": "médiane des répétitions",
                "gain": "médiane(B)/médiane(A) - 1 (plus_haut) ; 1 - médiane(B)/médiane(A) (plus_bas) ; positif = mieux",
                "au_dela_du_bruit": (f"test du signe sur les paires entrelacées (A_i, B_i) : B gagne au moins k paires, "
                                     f"k = plus petit entier tel que P(X >= k | N, 1/2) <= {SEUIL_TEST_DU_SIGNE} ; "
                                     f"ici N = {args.repetitions}, k = {seuil_signe(args.repetitions)}"),
                "degradation_au_dela_du_bruit": "même test, A gagne au moins k paires",
                "minmax_disjoints": "information seulement : intervalles [min, max] de A et de B disjoints",
            },
            "metriques": {}, "mesures": {"A": {}, "B": {}},
        }
        if seuil_signe(args.repetitions) is None:
            print(f"ab : attention, avec {args.repetitions} répétitions le test du signe ne peut jamais conclure "
                  f"(il en faut au moins 6) : tout restera « dans le bruit ».", file=sys.stderr)
        for nom, sens, unite in METRIQUES:
            valeurs_a = [m.get(nom) for m in mesures["A"]]
            valeurs_b = [m.get(nom) for m in mesures["B"]]
            a, b = resume(valeurs_a), resume(valeurs_b)
            disjoints = (a["mediane"] is not None and b["mediane"] is not None and (a["max"] < b["min"] or b["max"] < a["min"]))
            signe = test_du_signe(valeurs_a, valeurs_b, sens)
            rapport["metriques"][nom] = {
                "sens": sens, "unite": unite, "A": a, "B": b,
                "gain": gain_relatif(a["mediane"], b["mediane"], sens),
                "au_dela_du_bruit": signe["au_dela_du_bruit"],
                "degradation_au_dela_du_bruit": signe["degradation_au_dela_du_bruit"],
                "test_du_signe": signe,
                "minmax_disjoints": disjoints,
            }
            rapport["mesures"]["A"][nom] = a["mediane"]
            rapport["mesures"]["B"][nom] = b["mediane"]

        if args.instructions:
            rapport["instructions"] = {}
            encadre = True
            for scenario in SCENARIOS_INSTRUCTIONS:
                comptes = {}
                for etiquette in ("A", "B"):
                    comptes[etiquette], requetes = compter_instructions(binaires[etiquette], corpus, scenario, dossier_travail,
                                                                       etiquette, args.prefixe_instructions)
                    encadre = encadre and requetes
                gain = gain_relatif(comptes["A"], comptes["B"], "plus_bas")
                rapport["instructions"]["instructions_" + scenario] = {
                    "sens": "plus_bas", "unite": "instructions", "A": comptes["A"], "B": comptes["B"], "gain": gain,
                    "au_dela_du_bruit": gain is not None and abs(gain) > args.seuil_instructions}
            rapport["methode"]["instructions"] = (
                f"valgrind --tool=cachegrind, une exécution par scénario, {args.prefixe_instructions} premiers octets "
                f"de chaque fichier ; {'passes mesurées seulement' if encadre else 'programme entier (en-tête valgrind absent)'} ; "
                f"au-delà du bruit si l'écart dépasse {100 * args.seuil_instructions:.2f} %")
        rapport["duree_s"] = round(time.time() - debut, 1)
    finally:
        for wt in worktrees:
            if wt:
                subprocess.run(["git", "-C", depot, "worktree", "remove", "--force", wt], capture_output=True)
        subprocess.run(["git", "-C", depot, "worktree", "prune"], capture_output=True)
        if args.garder:
            print(f"ab : dossier temporaire conservé : {dossier_travail}", file=sys.stderr)
        else:
            shutil.rmtree(dossier_travail, ignore_errors=True)

    afficher_tableau(rapport)
    texte = json.dumps(rapport, ensure_ascii=False, indent=2)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(texte + "\n")
    print(texte)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Erreur as e:
        print(f"ab : erreur : {e}", file=sys.stderr)
        sys.exit(2)
