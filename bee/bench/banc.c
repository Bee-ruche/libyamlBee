/* Banc de mesure Bee pour libyaml.

   Sortie (stdout) : un objet JSON sur une ligne, avec exactement ces clés :
     debit_analyse      (Mo/s d'entrée : parseur d'événements seul, scanner + parser)
     debit_chargement   (Mo/s d'entrée : yaml_parser_load, construction de l'arbre du document)
     debit_emission     (Mo/s d'entrée : yaml_emitter_dump d'un document chargé)
     memoire_max_ko     (Ko, ru_maxrss d'un processus fils qui charge et émet tout le corpus)
   Une métrique non mesurée (option --scenario) vaut null.

   Méthode : le corpus est chargé en mémoire, puis traité fichier par fichier. Une « passe » traite
   tout le corpus ; le débit retenu est celui de la passe la plus rapide parmi k (meilleur de k,
   robuste au bruit d'une machine partagée). Pour l'émission, chaque document est d'abord chargé hors
   chronométrage, puis seul yaml_emitter_dump est mesuré (sortie jetée par un gestionnaire d'écriture).

   Usage : banc [--corpus DOSSIER] [--scenario tout|analyse|chargement|emission|memoire]
                [--passes K] [--prefixe N] [--sans-memoire] [--info]
   --prefixe N : ne garde que les N premiers octets de chaque fichier (sous-ensemble pour Cachegrind).
   --info : affiche les capacités du binaire et s'arrête. */

#include <yaml.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "corpus.h"

#ifdef BEE_AVEC_CACHEGRIND
#include <valgrind/cachegrind.h>
#define DEBUT_INSTRUMENTATION() CACHEGRIND_START_INSTRUMENTATION
#define FIN_INSTRUMENTATION() CACHEGRIND_STOP_INSTRUMENTATION
#else
#define DEBUT_INSTRUMENTATION() ((void)0)
#define FIN_INSTRUMENTATION() ((void)0)
#endif

#if defined(__GNUC__)
#define BEE_NOINLINE __attribute__((noinline))
#else
#define BEE_NOINLINE
#endif

static double maintenant(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

/* Gestionnaire d'écriture qui jette la sortie (pour mesurer l'émission sans coût d'allocation). */
static int ecrire_jeter(void *data, unsigned char *buffer, size_t size)
{
    (void)buffer;
    *(size_t *)data += size;
    return 1;
}

/* Analyse : flux d'événements seul. Renvoie le nombre d'événements (anti-élimination). */
static BEE_NOINLINE unsigned long bee_passe_analyse(const bee_corpus *c)
{
    unsigned long total = 0;
    size_t i;
    for (i = 0; i < c->nombre; i++) {
        yaml_parser_t parser;
        yaml_event_t event;
        int fini = 0;
        if (!yaml_parser_initialize(&parser)) continue;
        yaml_parser_set_input_string(&parser, c->fichiers[i].donnees, c->fichiers[i].taille);
        while (!fini) {
            if (!yaml_parser_parse(&parser, &event)) break;
            if (event.type == YAML_STREAM_END_EVENT) fini = 1;
            total++;
            yaml_event_delete(&event);
        }
        yaml_parser_delete(&parser);
    }
    return total;
}

/* Chargement : arbre complet du document. Renvoie une somme (anti-élimination). */
static BEE_NOINLINE unsigned long bee_passe_chargement(const bee_corpus *c)
{
    unsigned long total = 0;
    size_t i;
    for (i = 0; i < c->nombre; i++) {
        yaml_parser_t parser;
        yaml_document_t document;
        if (!yaml_parser_initialize(&parser)) continue;
        yaml_parser_set_input_string(&parser, c->fichiers[i].donnees, c->fichiers[i].taille);
        while (1) {
            if (!yaml_parser_load(&parser, &document)) break;
            if (!yaml_document_get_root_node(&document)) { yaml_document_delete(&document); break; }
            total++;
            yaml_document_delete(&document);
        }
        yaml_parser_delete(&parser);
    }
    return total;
}

/* Émission : charge chaque document hors chronométrage, puis mesure seulement yaml_emitter_dump. */
static BEE_NOINLINE double bee_passe_emission(const bee_corpus *c, unsigned long *jetons)
{
    double temps = 0;
    size_t i, octets = 0;
    for (i = 0; i < c->nombre; i++) {
        yaml_parser_t parser;
        if (!yaml_parser_initialize(&parser)) continue;
        yaml_parser_set_input_string(&parser, c->fichiers[i].donnees, c->fichiers[i].taille);
        while (1) {
            yaml_document_t document;
            yaml_emitter_t emitter;
            double t0;
            if (!yaml_parser_load(&parser, &document)) break;
            if (!yaml_document_get_root_node(&document)) { yaml_document_delete(&document); break; }
            if (!yaml_emitter_initialize(&emitter)) { yaml_document_delete(&document); break; }
            yaml_emitter_set_output(&emitter, ecrire_jeter, &octets);
            t0 = maintenant();
            /* yaml_emitter_dump prend possession du document et le libère. */
            yaml_emitter_dump(&emitter, &document);
            temps += maintenant() - t0;
            yaml_emitter_delete(&emitter);
        }
        yaml_parser_delete(&parser);
    }
    *jetons = (unsigned long)octets;
    return temps;
}

static double meilleur_debit(const bee_corpus *c, const char *scenario, int passes)
{
    double meilleur = 0;
    int p;
    for (p = 0; p < passes; p++) {
        double t0, dt, debit;
        unsigned long jetons = 0;
        if (!strcmp(scenario, "emission")) {
            DEBUT_INSTRUMENTATION();
            dt = bee_passe_emission(c, &jetons);
            FIN_INSTRUMENTATION();
        } else {
            t0 = maintenant();
            DEBUT_INSTRUMENTATION();
            if (!strcmp(scenario, "analyse")) jetons = bee_passe_analyse(c);
            else jetons = bee_passe_chargement(c);
            FIN_INSTRUMENTATION();
            dt = maintenant() - t0;
        }
        (void)jetons;
        debit = dt > 0 ? (c->total / 1e6) / dt : 0;
        if (debit > meilleur) meilleur = debit;
    }
    return meilleur;
}

static long memoire_corpus(const char *dossier, size_t prefixe)
{
    pid_t fils = fork();
    if (fils < 0) return -1;
    if (fils == 0) {
        bee_corpus c;
        unsigned long j = 0;
        if (bee_corpus_charger(dossier, &c) != 0) _exit(1);
        if (prefixe) { size_t i; for (i = 0; i < c.nombre; i++) if (c.fichiers[i].taille > prefixe) c.fichiers[i].taille = prefixe; }
        bee_passe_chargement(&c);
        bee_passe_emission(&c, &j);
        _exit(0);
    }
    {
        int statut;
        struct rusage ru;
        if (wait4(fils, &statut, 0, &ru) < 0) return -1;
        return ru.ru_maxrss; /* Ko sous Linux */
    }
}

static void imprimer(double v) { if (v < 0) printf("null"); else printf("%.4f", v); }

int main(int argc, char *argv[])
{
    const char *dossier = "bee/corpus/donnees";
    const char *scenario = "tout";
    int passes = 3;
    size_t prefixe = 0;
    int sans_memoire = 0;
    int i;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--corpus") && i + 1 < argc) dossier = argv[++i];
        else if (!strcmp(argv[i], "--scenario") && i + 1 < argc) scenario = argv[++i];
        else if (!strcmp(argv[i], "--passes") && i + 1 < argc) passes = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--prefixe") && i + 1 < argc) prefixe = (size_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--sans-memoire")) sans_memoire = 1;
        else if (!strcmp(argv[i], "--info")) {
#ifdef BEE_AVEC_CACHEGRIND
            printf("{\"cachegrind_requetes_client\": true}\n");
#else
            printf("{\"cachegrind_requetes_client\": false}\n");
#endif
            return 0;
        }
        else { fprintf(stderr, "option inconnue : %s\n", argv[i]); return 2; }
    }
    if (passes < 1) passes = 1;

    bee_corpus c;
    if (bee_corpus_charger(dossier, &c) != 0) return 1;
    if (prefixe) { size_t k; for (k = 0; k < c.nombre; k++) if (c.fichiers[k].taille > prefixe) c.fichiers[k].taille = prefixe; c.total = 0; for (k = 0; k < c.nombre; k++) c.total += c.fichiers[k].taille; }

    double d_analyse = -1, d_chargement = -1, d_emission = -1;
    long mem = -1;
    int tout = !strcmp(scenario, "tout");
    if (tout || !strcmp(scenario, "analyse")) d_analyse = meilleur_debit(&c, "analyse", passes);
    if (tout || !strcmp(scenario, "chargement")) d_chargement = meilleur_debit(&c, "chargement", passes);
    if (tout || !strcmp(scenario, "emission")) d_emission = meilleur_debit(&c, "emission", passes);
    if ((tout || !strcmp(scenario, "memoire")) && !sans_memoire) mem = memoire_corpus(dossier, prefixe);

    printf("{\"debit_analyse\": "); imprimer(d_analyse);
    printf(", \"debit_chargement\": "); imprimer(d_chargement);
    printf(", \"debit_emission\": "); imprimer(d_emission);
    printf(", \"memoire_max_ko\": "); imprimer(mem < 0 ? -1 : (double)mem);
    printf("}\n");

    bee_corpus_liberer(&c);
    return 0;
}
