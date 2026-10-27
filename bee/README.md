# Outillage d'évaluation Bee pour libyaml

Ce dossier `bee/` contient tout ce qui **juge** les contributions à ce fork : corpus, oracle de
déterminisme, banc de mesure, et (à venir) fuzzing et CI. Le code de libyaml lui-même n'y est pas
modifié. libyamlBee est un **fork indépendant** de [libyaml](https://github.com/yaml/libyaml), géré
par le projet [Bee](https://github.com/Bee-ruche/registre) ; il n'est pas affilié au projet d'origine.

## Ce qu'une contribution doit respecter

Une optimisation rend l'analyse ou l'émission plus rapide **sans changer le résultat** : pour chaque
entrée, libyaml doit produire **exactement le même flux d'événements** et le même statut (succès ou
erreur d'analyse). C'est l'invariant que vérifie l'oracle.

## Prérequis

`gcc` (ou `clang`), `make`, `python3` (3.8+). Pour le profilage : `valgrind`. Pour libFuzzer :
`clang` avec `libclang-rt`. libyaml se compile sans `config.h` ; l'outillage fournit les macros de
version et `YAML_DECLARE_STATIC` (voir `bee/Makefile`).

## Déterminisme (correction)

```bash
bee/tests/lancer.sh                 # construit l'oracle, génère le corpus, compare aux empreintes
bee/tests/lancer.sh --sans-empreintes   # pour une tâche autorisée à changer la sortie
```

Pour chaque fichier du corpus, `bee/tests/oracle.c` écrit le flux d'événements canonique (format
yaml-test-suite : `+STR`, `+MAP &ancre <tag>`, `=VAL`, `=ALI`, …). On compare son empreinte SHA-256
et son statut à `bee/tests/empreintes-reference.txt`, figé à la révision de base. Le moindre écart
fait échouer les tests.

## Banc de mesure

```bash
make -C bee banc
bee/construction/banc/banc --corpus bee/corpus/donnees --passes 3
python3 bee/bench/ab.py --base upstream/master --candidate HEAD --repetitions 10 --instructions
```

Quatre métriques : `debit_analyse` (parseur d'événements seul), `debit_chargement`
(`yaml_parser_load`, arbre du document), `debit_emission` (`yaml_emitter_dump`), `memoire_max_ko`
(pic de tas d'un processus fils qui charge et émet tout le corpus). `ab.py` compare deux révisions en
alternance stricte et tranche le bruit par un **test du signe** sur les paires entrelacées (au moins
9 paires gagnées sur 10) ; avec `--instructions`, il compte aussi les instructions (Cachegrind).
L'analyse de YAML est limitée par le CPU : une baisse d'instructions se voit au chronomètre.

## Corpus

`python3 bee/corpus/generer.py` écrit un corpus déterministe dans `bee/corpus/donnees/` et vérifie
`bee/corpus/SHA256SUMS`. Il mêle des documents synthétiques variés (maps et séquences en bloc, styles
de scalaires, profondeurs variées) et des échantillons fixes qui couvrent le style « flow », les
ancres et alias, le multi-documents, les commentaires, les scalaires littéraux et pliés, les tags, et
quelques configurations réalistes (Kubernetes, CI). Aucune donnée n'est téléchargée.

## Périmètre

Les chemins qui jugent les contributions (`bee/**`, `tests/**`, `.github/**`) ne peuvent pas être
modifiés par une tâche d'optimisation (commandement 3). Les sources de libyaml jugées sont `src/*.c`
et `include/yaml.h`.

## Limites connues

- **Émetteur et round-trip.** L'oracle vérifie l'analyse. Une vérification d'aller-retour (événements
  → YAML → événements identiques) pour les optimisations de l'émetteur reste à ajouter.
- **Fuzzing.** Le harnais de fuzzing différentiel de l'analyseur (entrée arbitraire, ASan/UBSan)
  n'est pas encore écrit : c'est une bonne tâche Bee pour durcir le fork.
- **Sandbox.** Le Dockerfile n'est pas encore épinglé par digest.
- **Non vérifié hors cette machine.** Les premiers chiffres viennent d'un seul environnement ; le banc
  distribué du registre (`bee enregistrer-mesure`) élargira à d'autres configurations.
