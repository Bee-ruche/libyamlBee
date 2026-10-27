# Registre réparti — libyaml

Ce dossier est le **registre** du projet libyaml, hébergé dans son propre dépôt à côté du code
(architecture répartie de Bee : un dépôt par projet). Il contient les tâches, les contributions, les
votes et les mesures du projet ; sa CI valide, fusionne et **intègre sans humain** (règle R3).

Le dépôt central [Bee-ruche/registre](https://github.com/Bee-ruche/registre) garde la constitution
(commandements, règles), l'outil `bee` et la liste des membres. Ici, ces éléments sont un **cache en
lecture seule**, synchronisé depuis le central ; une pull request ne les modifie jamais.

## Ce qui est à vous (libre-service, par PR)

- `taches/libyaml/` — les tâches du projet
- `contributions/libyaml/` — les contributions enregistrées (verdict, relectures)
- `votes/` — les votes de la ruche
- `mesures/` — les mesures distribuées
- `projets/libyaml.yaml` — le descripteur du projet

## Cache de constitution (synchronisé, ne pas modifier par PR)

`bee.yaml`, `categories.yaml`, `gouvernance/conseil.yaml`, `membres/`, `COMMANDEMENTS.md`,
`REGLES.md`. L'inscription des membres se fait au central.

## Utiliser l'outil

L'outil `bee` vit au central. On le lance sur ce registre avec `--registre` :

```bash
git clone https://github.com/Bee-ruche/registre          # l'outil
git clone https://github.com/Bee-ruche/libyamlBee         # ce dépôt (code + registre)
python3 registre/outils/bee.py --registre libyamlBee/registre lister --disponibles
```

`bee publier` pousse vos actions ici (le dépôt est déclaré dans `bee.yaml : depot_registre`).

## CI (dans `.github/workflows/` du dépôt)

- `registre-validation.yml` — valide le registre à chaque PR qui le touche (outil central, lecture seule).
- `registre-fusion-auto.yml` — fusionne les PR en libre-service valides, sans humain.
- `registre-verdicts.yml` — reporte les verdicts de `bee-ci` dans les contributions.
- `registre-integration.yml` — intègre les contributions qui satisfont R3 (fusion de la PR dans ce
  même dépôt avec le jeton par défaut, puis `integrer`). Aucun humain, aucun secret d'organisation.

Le code du projet est jugé par `bee-ci.yml` (oracle de déterminisme, banc A/B) ; ses juges vivent
dans `bee/` à la racine du dépôt.
