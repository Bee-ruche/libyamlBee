"""Les deux vocabulaires du registre Bee, français et anglais (docs/english-names.md du registre).

Le registre passe tous ses noms en anglais en une seule bascule (docs/english-migration.md, sections 6, 12 et 13). Le
job « Manifeste et taille » lit le registre sur main, sans épingle : libyamlBee lit donc les deux formes, avant comme
après, et ramène tout à ses noms internes (français). Les identifiants de métrique restent les mêmes dans les deux.

Un document (tâche, manifeste, descripteur de projet) est dans UN vocabulaire : un document qui mêle des clés des deux
est refusé. Ce qu'on ne sait pas lire lève Illisible, jamais une valeur par défaut.
"""


class Illisible(ValueError):
    """Une donnée du registre ou de la PR que libyamlBee ne sait pas lire : l'étape échoue avec ce message."""


# Les métriques que le banc de libyamlBee mesure (bee/bench/ab.py) : celles que verdict.py sait juger.
METRIQUES = ["debit_analyse", "debit_chargement", "debit_emission", "memoire_max_ko"]
# Valeurs énumérées d'une tâche, français → anglais (« test » est le même mot).
TYPES = {"optimisation": "optimization", "relecture": "review", "mesure": "measurement", "test": "test", "decoupage": "split"}
SORTIES = {"identique": "identical", "peut_changer": "may_change"}
# Clés d'une tâche (schemas/tache.schema.json), français → anglais ; id, type, notes, contribution et reservation
# s'écrivent de même dans les deux.
CLES_TACHE = {"projet": "project", "categorie": "category", "taille": "size", "titre": "title", "contexte": "context",
              "fichiers": "files", "portee": "reach", "metrique": "metric", "critere_acceptation": "acceptance_criteria",
              "hors_perimetre": "out_of_scope", "statut": "status", "cree_par": "created_by", "cree_le": "created_on",
              "noeud": "node", "depend_de": "depends_on", "poste": "area", "paralleles": "parallel",
              "sortie_compressee": "compressed_output"}
# Clés du descripteur de projet (schemas/projet.schema.json) ; id, fork, reference, description et instructions sont
# les mêmes. Une métrique y a toujours unite et sens : son vocabulaire est vérifié avec celui du document.
CLES_PROJET = {"nom": "name", "categorie": "category", "depot_origine": "upstream_repo", "licence": "license",
               "perimetre": "scope", "hors_perimetre": "out_of_scope", "statut": "status", "phase_ouverture": "opening_phase",
               "palier_mainteneur": "maintainer_tier", "metriques": "metrics", "chemins_hors_decompte": "paths_not_counted",
               "chemins_juges": "judge_paths", "commandes": "commands", "verdict_exige_base_juge": "verdict_requires_judge_base"}
CLES_METRIQUE = {"unite": "unit", "sens": "direction"}
# Clés d'un manifeste (schemas/contribution.schema.json), par niveau ; agent, client, machine et repetitions sont
# les mêmes. « metrique » n'est pas au schéma, mais verdict.py la lit (simulation locale sans tâche).
CLES_MANIFESTE = {"tache": "task", "utilisateur": "user", "resume": "summary", "changement": "change",
                  "mesures": "measurements", "teste": "tested", "non_teste": "untested", "doutes": "doubts",
                  "taille_reelle": "actual_size", "metrique": "metric"}
CLES_AGENT = {"modele": "model"}
CLES_MESURES = {"commande": "command", "avant": "before", "apres": "after"}


def langue(niveaux, quoi):
    """« fr », « en » ou None (aucune clé propre à l'un ou à l'autre) pour des (objet, carte) d'un même document."""
    francais = sorted(k for d, carte in niveaux for k in d if k in carte)
    anglais = sorted(k for d, carte in niveaux for k in d if k in carte.values())
    if francais and anglais:
        raise Illisible(f"{quoi} mêle les deux vocabulaires (clés françaises {francais}, anglaises {anglais}) : refusé")
    return "en" if anglais else ("fr" if francais else None)


def en_francais(d, carte, langue_document):
    inverse = {en: fr for fr, en in carte.items()} if langue_document == "en" else {}
    return {inverse.get(k, k): v for k, v in d.items()}


def tache_en_francais(donnees):
    """La tâche avec ses clés internes (françaises). Ses valeurs restent dans son vocabulaire : voir valeur()."""
    if not isinstance(donnees, dict):
        raise Illisible("la tâche ne contient pas un objet YAML")
    langue_tache = langue([(donnees, CLES_TACHE)], "la tâche")
    if langue_tache is None:
        raise Illisible("la tâche n'a aucune clé connue, ni française ni anglaise : illisible")
    return en_francais(donnees, CLES_TACHE, langue_tache), langue_tache


def valeur(tache, cle, valeurs, langue_tache):
    """Valeur énumérée, ramenée au français ; une valeur de l'autre vocabulaire, ou inconnue : Illisible."""
    v = tache.get(cle)
    connues = {en: fr for fr, en in valeurs.items()} if langue_tache == "en" else {fr: fr for fr in valeurs}
    if not isinstance(v, str) or v not in connues:
        raise Illisible(f"{cle} « {v} » illisible dans une tâche en {'anglais' if langue_tache == 'en' else 'français'} "
                        f"(attendu : {', '.join(sorted(connues))})")
    return connues[v]


def metrique_de_la_tache(donnees, connues=METRIQUES):
    """La métrique principale de la tâche : un identifiant de `connues`, ou None si la tâche dit explicitement qu'elle
    n'en a pas (metrique: null). Clé absente, ou métrique inconnue : Illisible (le verdict ne choisit jamais la sienne)."""
    tache, langue_tache = tache_en_francais(donnees)
    if "metrique" not in tache:
        raise Illisible(f"clé « {'metric' if langue_tache == 'en' else 'metrique'} » absente de la tâche : métrique illisible")
    if tache["metrique"] is not None and tache["metrique"] not in connues:
        raise Illisible(f"métrique « {tache['metrique']} » inconnue (attendu : {', '.join(sorted(connues))} ou null)")
    return tache["metrique"]


def lire_tache(donnees, connues):
    """type, metrique et sortie_compressee de la tâche, en noms internes ; `connues` : les métriques du projet. Une
    sortie_compressee absente vaut « identique », le contrôle le plus strict ; présente, elle doit être lisible. Une
    optimisation sans métrique (metric: null) est illisible : R4 n'aurait rien à juger."""
    metrique = metrique_de_la_tache(donnees, connues)
    tache, langue_tache = tache_en_francais(donnees)
    sortie = valeur(tache, "sortie_compressee", SORTIES, langue_tache) if "sortie_compressee" in tache else "identique"
    type_tache = valeur(tache, "type", TYPES, langue_tache)
    if type_tache == "optimisation" and metrique is None:
        raise Illisible("une tâche d'optimisation sans métrique (metric: null) : illisible, R4 n'aurait rien à juger")
    return {"type": type_tache, "metrique": metrique, "sortie_compressee": sortie}


def metriques_du_projet(donnees):
    """Les identifiants des métriques du descripteur de projet (metrics ou metriques). Document mêlé (métriques
    comprises), sans cette clé, liste vide ou métrique sans identifiant : Illisible, jamais une liste vide."""
    if not isinstance(donnees, dict):
        raise Illisible("le descripteur de projet ne contient pas un objet YAML")
    liste = donnees.get("metrics", donnees.get("metriques"))
    liste = liste if isinstance(liste, list) else None
    niveaux = [(donnees, CLES_PROJET)] + [(m, CLES_METRIQUE) for m in liste or [] if isinstance(m, dict)]
    langue_projet = langue(niveaux, "le descripteur de projet")
    if langue_projet is None or not liste:
        cle = "metrics" if langue_projet == "en" else "metriques"
        raise Illisible(f"clé « {cle} » absente, vide ou pas une liste dans le descripteur de projet : métriques illisibles")
    ids = [m.get("id") if isinstance(m, dict) else None for m in liste]
    if not all(isinstance(i, str) and i for i in ids):
        raise Illisible(f"une métrique du descripteur de projet n'a pas d'identifiant ({ids}) : métriques illisibles")
    return ids


def lire_manifeste(donnees):
    """Le manifeste de la PR avec ses clés internes (françaises), à ses trois niveaux. Mêlé : Illisible."""
    if not isinstance(donnees, dict):
        raise Illisible("le manifeste ne contient pas un objet YAML")
    niveaux = [(donnees, CLES_MANIFESTE)]
    niveaux += [(donnees[c], CLES_AGENT) for c in ("agent",) if isinstance(donnees.get(c), dict)]
    niveaux += [(donnees[c], CLES_MESURES) for c in ("mesures", "measurements") if isinstance(donnees.get(c), dict)]
    langue_manifeste = langue(niveaux, "le manifeste")
    manifeste = en_francais(donnees, CLES_MANIFESTE, langue_manifeste)
    for cle, carte in (("agent", CLES_AGENT), ("mesures", CLES_MESURES)):
        if isinstance(manifeste.get(cle), dict):
            manifeste[cle] = en_francais(manifeste[cle], carte, langue_manifeste)
    return manifeste
