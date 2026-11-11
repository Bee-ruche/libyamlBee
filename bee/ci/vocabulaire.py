"""The Bee registry's names, as libyamlBee reads them (bee/ci/tache.py, bee/ci/verdict.py).

The registry writes English since its switch (ruche-0145): tasks/, projects/, tools/, English keys and values. libyamlBee
reads only those, with one exception: metric ids. The registry still writes them in French until it renames its data
(ruche-0149), so they are read in either vocabulary, one per document, and brought to their English names, the ones
libyamlBee's bench writes (bee/bench/ab.py).

A PR's manifest is read in either vocabulary until the registry stops reading French manifests (bee's DATE_D,
2027-01-01): one vocabulary per manifest, brought to English keys. What cannot be read raises Illisible, never a
default value.
"""


class Illisible(ValueError):
    """Data from the registry or the PR that libyamlBee cannot read: the step fails with this message."""


# The metrics libyamlBee's bench measures (bee/bench/ab.py), in their English names: the ones verdict.py can judge.
METRIQUES = ["parse_throughput", "load_throughput", "emit_throughput", "max_memory_kb"]
# Their French names, and those of the instruction counts, as the registry writes them until ruche-0149 renames its data
# (tools/migration/names.yaml, domain metric_id).
METRIQUES_FR = {"debit_analyse": "parse_throughput", "debit_chargement": "load_throughput",
                "debit_emission": "emit_throughput", "memoire_max_ko": "max_memory_kb",
                "instructions_analyse": "instructions_parse", "instructions_chargement": "instructions_load",
                "instructions_emission": "instructions_emit"}
# Enumerated values of a task.
TYPES = ("optimization", "review", "measurement", "test", "split")
SORTIES = ("identical", "may_change")
# Keys of a manifest (the registry's schemas/manifest.schema.json), French -> English, per level; agent, client, machine
# and repetitions are the same in both. « metric » is not in the schema, but verdict.py reads it (local simulation
# without a task).
CLES_MANIFESTE = {"tache": "task", "utilisateur": "user", "resume": "summary", "changement": "change",
                  "mesures": "measurements", "teste": "tested", "non_teste": "untested", "doutes": "doubts",
                  "taille_reelle": "actual_size", "metrique": "metric"}
CLES_AGENT = {"modele": "model"}
CLES_MESURES = {"commande": "command", "avant": "before", "apres": "after"}


def metrique_anglaise(nom):
    """A metric id in its English name (a French id of METRIQUES_FR translated, any other value as it is)."""
    return METRIQUES_FR.get(nom, nom) if isinstance(nom, str) else nom


def vocabulaire_des_metriques(noms, quoi):
    """Refuses a document that names metrics in both vocabularies (Illisible)."""
    francais = sorted(n for n in noms if isinstance(n, str) and n in METRIQUES_FR)
    anglais = sorted(n for n in noms if isinstance(n, str) and n in METRIQUES_FR.values())
    if francais and anglais:
        raise Illisible(f"{quoi} mixes French metric ids ({', '.join(francais)}) and English ones ({', '.join(anglais)}): refused")


def metrique_de_la_tache(donnees, connues=METRIQUES):
    """The task's main metric, in its English name: an id of `connues`, or None if the task says explicitly that it has
    none (metric: null). Key missing, or metric unknown: Illisible (the verdict never picks its own)."""
    if not isinstance(donnees, dict):
        raise Illisible("the task does not contain a YAML object")
    if "metric" not in donnees:
        raise Illisible("key « metric » missing from the task: metric unreadable")
    if donnees["metric"] is None:
        return None
    metrique = metrique_anglaise(donnees["metric"])
    if not isinstance(metrique, str) or metrique not in connues:
        raise Illisible(f"metric « {donnees['metric']} » unknown (expected: {', '.join(sorted(connues))} or null)")
    return metrique


def valeur(tache, cle, valeurs):
    """An enumerated value of the task; a value outside `valeurs`, or missing: Illisible."""
    v = tache.get(cle)
    if not isinstance(v, str) or v not in valeurs:
        raise Illisible(f"{cle} « {v} » unreadable in the task (expected: {', '.join(sorted(valeurs))})")
    return v


def lire_tache(donnees, connues):
    """type, metric and compressed_output of the task; `connues`: the project's metrics (English names). A missing
    compressed_output means « identical », the strictest check; present, it must be readable. An optimization without
    a metric (metric: null) is unreadable: R4 would have nothing to judge."""
    metrique = metrique_de_la_tache(donnees, connues)
    sortie = valeur(donnees, "compressed_output", SORTIES) if "compressed_output" in donnees else "identical"
    type_tache = valeur(donnees, "type", TYPES)
    if type_tache == "optimization" and metrique is None:
        raise Illisible("an optimization task without a metric (metric: null): unreadable, R4 would have nothing to judge")
    return {"type": type_tache, "metric": metrique, "compressed_output": sortie}


def metriques_du_projet(donnees):
    """The metric ids of the project descriptor, in their English names. Without the key metrics, an empty list, a metric
    without an id, or ids in both vocabularies: Illisible, never an empty list."""
    if not isinstance(donnees, dict):
        raise Illisible("the project descriptor does not contain a YAML object")
    liste = donnees.get("metrics")
    if not isinstance(liste, list) or not liste:
        raise Illisible("key « metrics » missing, empty or not a list in the project descriptor: metrics unreadable")
    ids = [m.get("id") if isinstance(m, dict) else None for m in liste]
    if not all(isinstance(i, str) and i for i in ids):
        raise Illisible(f"a metric of the project descriptor has no id ({ids}): metrics unreadable")
    vocabulaire_des_metriques(ids + [m.get("instructions") for m in liste], "the project descriptor")
    return [metrique_anglaise(i) for i in ids]


def langue(niveaux, quoi):
    """« fr », « en » or None (no key specific to either) for (mapping, map) pairs of one document."""
    francais = sorted(k for d, carte in niveaux for k in d if k in carte)
    anglais = sorted(k for d, carte in niveaux for k in d if k in carte.values())
    if francais and anglais:
        raise Illisible(f"{quoi} mixes both vocabularies (French keys {francais}, English keys {anglais}): refused")
    return "en" if anglais else ("fr" if francais else None)


def en_anglais(d, carte, langue_document):
    return {carte.get(k, k): v for k, v in d.items()} if langue_document == "fr" else dict(d)


def lire_manifeste(donnees):
    """The PR's manifest with English keys, at its three levels; its metric ids in English. Mixed: Illisible."""
    if not isinstance(donnees, dict):
        raise Illisible("the manifest does not contain a YAML object")
    niveaux = [(donnees, CLES_MANIFESTE)]
    niveaux += [(donnees[c], CLES_AGENT) for c in ("agent",) if isinstance(donnees.get(c), dict)]
    niveaux += [(donnees[c], CLES_MESURES) for c in ("mesures", "measurements") if isinstance(donnees.get(c), dict)]
    langue_manifeste = langue(niveaux, "the manifest")
    manifeste = en_anglais(donnees, CLES_MANIFESTE, langue_manifeste)
    for cle, carte in (("agent", CLES_AGENT), ("measurements", CLES_MESURES)):
        if isinstance(manifeste.get(cle), dict):
            manifeste[cle] = en_anglais(manifeste[cle], carte, langue_manifeste)
    mesures = manifeste.get("measurements") if isinstance(manifeste.get("measurements"), dict) else {}
    cotes = [mesures[c] for c in ("before", "after") if isinstance(mesures.get(c), dict)]
    vocabulaire_des_metriques([manifeste.get("metric")] + [n for d in cotes for n in d], "the manifest")
    if "metric" in manifeste:
        manifeste["metric"] = metrique_anglaise(manifeste["metric"])
    for c in ("before", "after"):
        if isinstance(mesures.get(c), dict):
            mesures[c] = {metrique_anglaise(n): v for n, v in mesures[c].items()}
    return manifeste
