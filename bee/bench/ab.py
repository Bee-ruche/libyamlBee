#!/usr/bin/env python3
"""Bee's interleaved A/B bench for libyaml.

Compares two revisions of libyaml on the reference corpus:

  python3 bee/bench/ab.py --base <rev> --candidate <rev> [--repetitions 10] [--instructions] [--json output.json]

How it runs:
  1. Each revision is checked out in a separate temporary folder (git worktree, detached).
     The special value « :travail » names the current working copy, uncommitted changes included.
  2. The bench (bee/bench/banc.c) and the Makefile of the current tooling (the bee/ folder that holds this script) are
     built against the libyaml sources of each revision: only the library's code differs between A and B, the bench is
     the same.
  3. After one uncounted warm-up run of each (--chauffe), the two binaries run in strict alternation, A, B, A, B…,
     N times each; each run measures the four metrics. In one run, each throughput is the best of k passes over the
     corpus (see banc.c). The median of the N values of each metric is kept for A and for B.
  4. Relative gain (positive = better): median(B) / median(A) - 1 for a « higher » metric,
     1 - median(B) / median(A) for a « lower » metric (max_memory_kb).
  5. Noise, by a sign test on the interleaved pairs. Repetition i measures A_i then B_i side by side: pair i sees about
     the same load of the machine. B « wins » the pair if B_i is better than A_i (higher, or lower for max_memory_kb).
     Tied pairs are set aside (standard sign test): N then means the number of untied pairs. If A and B are
     equivalent, the number X of pairs won by B follows a binomial distribution (N, 1/2).
     Threshold: k = the smallest integer such that P(X >= k | N, 1/2) <= 0.02 (one-sided test):
         N  :  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20
         k  :  6  7  8  8  9 10 10 11 12 12 13 14 14 15 16
     For N = 10, k = 9 (p = 0.0107). Below 6 untied pairs, no threshold reaches 0.02: nothing is « beyond noise »
     (ab.py warns if --repetitions is below 6).
       - beyond_noise: B wins at least k pairs (significant improvement);
       - degradation_beyond_noise: A wins at least k pairs (significant degradation, for R5).
     max_memory_kb is almost deterministic: the ties are set aside, and the difference is judged on the differing
     pairs only.
     Unit tests: python3 bee/bench/test_ab.py
     The [min, max] intervals are kept in the JSON for information (minmax_disjoint); this more cautious criterion had
     missed a real 5 % slowdown (minizBee's bench, level 6).
  6. With --instructions, each binary also runs under valgrind --tool=cachegrind, once per scenario (parse, load,
     emit) on a subset of the corpus (the first --prefixe-instructions bytes of each file, 128 KiB by default). Only
     the timed passes are counted (Cachegrind client requests). The count is reproducible; a difference is « beyond
     noise » if it exceeds --seuil-instructions (0.2 % by default).

Output: the JSON report on stdout (and in --json), in English: its keys follow the registry's tools/migration/names.yaml
(families ab_report and judge_report), its metric ids are parse_throughput, load_throughput, emit_throughput,
max_memory_kb and instructions_parse, instructions_load, instructions_emit (domain metric_id); bee record-measurement
reads it. A readable table on stderr.
Exit code: 0 if the measurement completed (whatever the result), 2 on error.
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

# The same definitions as projects/libyaml.yaml in the Bee registry, with the English metric ids (names.yaml, domain
# metric_id), which the bench writes too (banc.c), with the direction and the unit in English (domains direction, unit).
METRIQUES = [
    ("parse_throughput", "higher", "MB/s"),
    ("load_throughput", "higher", "MB/s"),
    ("emit_throughput", "higher", "MB/s"),
    ("max_memory_kb", "lower", "KB"),
]
# banc.c's scenario (its option --scenario) -> the instruction count's id.
SCENARIOS_INSTRUCTIONS = {"analyse": "instructions_parse", "chargement": "instructions_load", "emission": "instructions_emit"}
TRAVAIL = ":travail"


class Erreur(Exception):
    pass


def executer(commande, **options):
    resultat = subprocess.run(commande, capture_output=True, text=True, **options)
    if resultat.returncode != 0:
        raise Erreur(f"« {' '.join(commande)} » failed (code {resultat.returncode}):\n"
                     f"{resultat.stdout[-2000:]}{resultat.stderr[-4000:]}")
    return resultat.stdout


def racine_git(dossier):
    return executer(["git", "-C", dossier, "rev-parse", "--show-toplevel"]).strip()


def resoudre(depot, rev):
    if rev == TRAVAIL:
        tete = executer(["git", "-C", depot, "rev-parse", "HEAD"]).strip()
        sale = bool(executer(["git", "-C", depot, "status", "--porcelain", "--untracked-files=no"]).strip())
        return {"rev": rev, "commit": tete, "uncommitted_changes": sale}
    try:
        commit = executer(["git", "-C", depot, "rev-parse", "--verify", "--quiet", rev + "^{commit}"]).strip()
    except Erreur:
        raise Erreur(f"unknown revision: {rev} (try git fetch, or a commit id)")
    return {"rev": rev, "commit": commit}


def preparer_source(depot, info, dossier_travail, etiquette):
    """Returns the folder that holds the revision's libyaml sources."""
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
        raise Erreur(f"the bench was not built for {etiquette}")
    return binaire


def fixer_cpu(cpu):
    if cpu is None:
        return None
    return lambda: os.sched_setaffinity(0, {cpu})


def lancer_banc(binaire, corpus, options_banc, cpu):
    sortie = subprocess.run([binaire, "--corpus", corpus] + options_banc, capture_output=True, text=True,
                            preexec_fn=fixer_cpu(cpu))
    if sortie.returncode != 0:
        raise Erreur(f"the bench {binaire} failed (code {sortie.returncode}): {sortie.stderr.strip()}")
    try:
        return json.loads(sortie.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Erreur(f"unreadable output from the bench {binaire}: {sortie.stdout!r}")


def compter_instructions(binaire, corpus, scenario, dossier_travail, etiquette, prefixe):
    if shutil.which("valgrind") is None:
        raise Erreur("--instructions needs valgrind, not found in the PATH")
    info = json.loads(executer([binaire, "--info"]))
    fichier = os.path.join(dossier_travail, f"cachegrind-{etiquette}-{scenario}.out")
    commande = ["valgrind", "--tool=cachegrind", "--cache-sim=no", f"--cachegrind-out-file={fichier}"]
    if info.get("cachegrind_requetes_client"):
        commande.append("--instr-at-start=no")
    commande += [binaire, "--corpus", corpus, "--scenario", scenario, "--passes", "1", "--prefixe", str(prefixe),
                 "--sans-memoire"]
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0:
        raise Erreur(f"cachegrind failed for {etiquette}/{scenario}: {resultat.stderr[-2000:]}")
    trouve = re.search(r"I\s+refs:\s+([\d,]+)", resultat.stderr)
    if not trouve:
        raise Erreur(f"instruction count not found in cachegrind's output ({etiquette}/{scenario})")
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
    meilleur = (lambda a, b: b > a) if sens == "higher" else (lambda a, b: b < a)
    victoires_b = sum(1 for a, b in paires if meilleur(a, b))
    victoires_a = sum(1 for a, b in paires if meilleur(b, a))
    n_utiles = victoires_a + victoires_b
    k = seuil_signe(n_utiles) if n_utiles else None
    return {
        "pairs": len(paires), "useful_pairs": n_utiles,
        "b_wins": victoires_b, "a_wins": victoires_a, "ties": len(paires) - n_utiles,
        "threshold_k": k,
        "p_improvement": p_unilaterale(n_utiles, victoires_b) if n_utiles else None,
        "p_degradation": p_unilaterale(n_utiles, victoires_a) if n_utiles else None,
        "beyond_noise": k is not None and victoires_b >= k,
        "degradation_beyond_noise": k is not None and victoires_a >= k,
    }


def resume(valeurs):
    valeurs = [v for v in valeurs if v is not None]
    if not valeurs:
        return {"median": None, "min": None, "max": None, "values": []}
    return {"median": statistics.median(valeurs), "min": min(valeurs), "max": max(valeurs), "values": valeurs}


def gain_relatif(a, b, sens):
    if a in (None, 0) or b is None:
        return None
    return (b / a - 1.0) if sens == "higher" else (1.0 - b / a)


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
    return {"processor": modele, "architecture": platform.machine(), "cores": os.cpu_count(),
            "system": platform.platform(), "compiler": version}


def afficher_tableau(rapport):
    lignes = [f"{'metric':26s} {'median A':>12s} {'median B':>12s} {'gain':>8s}  {'B wins':>8s}  verdict"]
    for nom, m in rapport["metrics"].items():
        a, b = m["A"], m["B"]
        if a["median"] is None:
            continue
        s = m["sign_test"]
        gain = "-" if m["gain"] is None else f"{100 * m['gain']:+.2f}%"
        if m["beyond_noise"]:
            verdict = "improvement beyond noise"
        elif m["degradation_beyond_noise"]:
            verdict = "DEGRADATION beyond noise"
        else:
            verdict = "within noise"
        lignes.append(f"{nom:26s} {a['median']:12.3f} {b['median']:12.3f} {gain:>8s}  "
                      f"{s['b_wins']:>3d}/{s['useful_pairs']:<4d}  {verdict}"
                      + (f" ({s['ties']} ties set aside)" if s["ties"] else ""))
    for nom, m in (rapport.get("instructions") or {}).items():
        gain = "-" if m["gain"] is None else f"{100 * m['gain']:+.3f}%"
        if not m["beyond_noise"]:
            verdict = "within noise"
        else:
            verdict = "fewer instructions" if m["gain"] > 0 else "MORE instructions"
        lignes.append(f"{nom:26s} {m['A']:12d} {m['B']:12d} {gain:>8s}  {'':>8s}  {verdict}")
    print("\n".join(lignes), file=sys.stderr)


def main():
    analyseur = argparse.ArgumentParser(description="Bee's interleaved A/B bench for libyaml (see the module's help).")
    analyseur.add_argument("--base", required=True, help="revision A (reference), e.g. upstream/master or a commit")
    analyseur.add_argument("--candidate", required=True, help="revision B (candidate), e.g. HEAD; « :travail » for the working copy")
    analyseur.add_argument("--repetitions", type=int, default=10, help="runs of each binary (default 10)")
    analyseur.add_argument("--chauffe", type=int, default=1,
                           help="uncounted runs of A then B before measuring (default 1: warm caches and frequency)")
    analyseur.add_argument("--instructions", action="store_true", help="also counts instructions with cachegrind")
    analyseur.add_argument("--json", help="also writes the JSON report to this file")
    analyseur.add_argument("--depot", default=os.path.dirname(OUTILLAGE), help="git repository of libyaml (default: this script's)")
    analyseur.add_argument("--corpus", help="corpus folder (default: bee/corpus/donnees, regenerated and checked)")
    analyseur.add_argument("--passes", help="passed to the bench (--passes K): number of passes per run")
    analyseur.add_argument("--cpu", type=int, help="pins the runs to this core (sched_setaffinity)")
    analyseur.add_argument("--prefixe-instructions", type=int, default=131072, help="bytes kept per file for cachegrind")
    analyseur.add_argument("--seuil-instructions", type=float, default=0.002, help="relative difference in instructions deemed significant")
    analyseur.add_argument("--garder", action="store_true", help="does not delete the temporary folder (diagnosis)")
    args = analyseur.parse_args()

    if args.repetitions < 1:
        raise Erreur("--repetitions must be at least 1")
    depot = racine_git(args.depot)
    base, candidat = resoudre(depot, args.base), resoudre(depot, args.candidate)

    corpus = args.corpus
    if corpus is None:
        corpus = os.path.join(OUTILLAGE, "corpus", "donnees")
        resultat = subprocess.run([sys.executable, os.path.join(OUTILLAGE, "corpus", "generer.py")], capture_output=True, text=True)
        if resultat.returncode != 0:
            raise Erreur("corpus not conforming: " + resultat.stderr.strip())
    options_banc = ["--passes", args.passes] if args.passes else []

    dossier_travail = tempfile.mkdtemp(prefix="bee-ab-")
    worktrees = []
    debut = time.time()
    try:
        print(f"ab: A = {base['rev']} ({base['commit'][:12]}), B = {candidat['rev']} ({candidat['commit'][:12]})", file=sys.stderr)
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
            print(f"ab: repetition {i + 1}/{args.repetitions} done", file=sys.stderr)

        rapport = {
            "base": base, "candidate": candidat, "repetitions": args.repetitions, "warmup": args.chauffe,
            "order": "A, B, A, B…",
            "machine": description_machine(),
            "method": {
                "retained_value": "median of the repetitions",
                "gain": "median(B)/median(A) - 1 (higher); 1 - median(B)/median(A) (lower); positive = better",
                "beyond_noise": (f"sign test on the interleaved pairs (A_i, B_i): B wins at least k pairs, "
                                 f"k = the smallest integer such that P(X >= k | N, 1/2) <= {SEUIL_TEST_DU_SIGNE}; "
                                 f"here N = {args.repetitions}, k = {seuil_signe(args.repetitions)}"),
                "degradation_beyond_noise": "the same test, A wins at least k pairs",
                "minmax_disjoint": "information only: the [min, max] intervals of A and B are disjoint",
            },
            "metrics": {}, "measurements": {"A": {}, "B": {}},
        }
        if seuil_signe(args.repetitions) is None:
            print(f"ab: warning, with {args.repetitions} repetitions the sign test can never conclude "
                  f"(it takes at least 6): everything will stay « within noise ».", file=sys.stderr)
        for nom, sens, unite in METRIQUES:
            valeurs_a = [m.get(nom) for m in mesures["A"]]
            valeurs_b = [m.get(nom) for m in mesures["B"]]
            a, b = resume(valeurs_a), resume(valeurs_b)
            disjoints = (a["median"] is not None and b["median"] is not None and (a["max"] < b["min"] or b["max"] < a["min"]))
            signe = test_du_signe(valeurs_a, valeurs_b, sens)
            rapport["metrics"][nom] = {
                "direction": sens, "unit": unite, "A": a, "B": b,
                "gain": gain_relatif(a["median"], b["median"], sens),
                "beyond_noise": signe["beyond_noise"],
                "degradation_beyond_noise": signe["degradation_beyond_noise"],
                "sign_test": signe,
                "minmax_disjoint": disjoints,
            }
            rapport["measurements"]["A"][nom] = a["median"]
            rapport["measurements"]["B"][nom] = b["median"]

        if args.instructions:
            rapport["instructions"] = {}
            encadre = True
            for scenario, identifiant in SCENARIOS_INSTRUCTIONS.items():
                comptes = {}
                for etiquette in ("A", "B"):
                    comptes[etiquette], requetes = compter_instructions(binaires[etiquette], corpus, scenario, dossier_travail,
                                                                       etiquette, args.prefixe_instructions)
                    encadre = encadre and requetes
                gain = gain_relatif(comptes["A"], comptes["B"], "lower")
                rapport["instructions"][identifiant] = {
                    "direction": "lower", "unit": "instructions", "A": comptes["A"], "B": comptes["B"], "gain": gain,
                    "beyond_noise": gain is not None and abs(gain) > args.seuil_instructions}
            rapport["method"]["instructions"] = (
                f"valgrind --tool=cachegrind, one run per scenario, the first {args.prefixe_instructions} bytes "
                f"of each file; {'timed passes only' if encadre else 'whole program (valgrind header missing)'}; "
                f"beyond noise if the difference exceeds {100 * args.seuil_instructions:.2f} %")
        rapport["duration_s"] = round(time.time() - debut, 1)
    finally:
        for wt in worktrees:
            if wt:
                subprocess.run(["git", "-C", depot, "worktree", "remove", "--force", wt], capture_output=True)
        subprocess.run(["git", "-C", depot, "worktree", "prune"], capture_output=True)
        if args.garder:
            print(f"ab: temporary folder kept: {dossier_travail}", file=sys.stderr)
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
        print(f"ab: error: {e}", file=sys.stderr)
        sys.exit(2)
