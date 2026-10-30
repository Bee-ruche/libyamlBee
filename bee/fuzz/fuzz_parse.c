/* Harnais de fuzzing Bee pour l'analyseur de libyaml (compatible libFuzzer et bee/fuzz/pilote_aleatoire.c).

   Analyse une entrée arbitraire et consomme tous les événements, sous ASan et UBSan. Le premier octet
   choisit la lecture : 0 = yaml_parser_set_input_string (tout d'un coup), k > 0 = gestionnaire de
   lecture qui livre k octets à la fois (flux découpé : limites de tampon du lecteur). Le reste est le
   document YAML.

   Différentiel : bee/fuzz/lancer.sh --reference lie dans le même exécutable une seconde copie de
   libyaml (la base de la PR), dont tous les symboles yaml_* et bee_flux sont renommés ref_* (#define).
   Chaque entrée est analysée par les deux ; le flux sérialisé doit être identique octet pour octet :
   type, ancre, tag, valeur, style, indicateurs implicites, directives, encodage, marques de début et
   de fin de chaque événement, et en cas d'erreur son type, son message, son contexte et ses positions.
   Tout écart appelle abort(), que lancer.sh classe (nouveau ou préexistant).

   Compilations (voir lancer.sh) :
     -DBEE_FLUX_SEUL         ne définit que bee_flux (copie de référence, renommée à la compilation) ;
     -DBEE_SANS_REFERENCE    harnais simple, sans différentiel (pas de --reference, ou rejeu sur la base). */

#include <yaml.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct
{
    unsigned char *octets;
    size_t taille, capacite;
} bee_tampon;

int bee_flux(const uint8_t *donnees, size_t taille, bee_tampon *sortie);

static void ajouter(bee_tampon *t, const void *p, size_t n)
{
    if (t->taille + n > t->capacite)
    {
        size_t c = t->capacite ? t->capacite : 4096;
        while (c < t->taille + n)
            c *= 2;
        t->octets = (unsigned char *)realloc(t->octets, c);
        if (!t->octets)
            abort();
        t->capacite = c;
    }
    memcpy(t->octets + t->taille, p, n);
    t->taille += n;
}

static void ajouter_entier(bee_tampon *t, unsigned long long v)
{
    unsigned char o[8];
    int i;
    for (i = 0; i < 8; i++)
        o[i] = (unsigned char)(v >> (8 * i));
    ajouter(t, o, 8);
}

/* Chaîne d'octets, de longueur explicite ; NULL est distinct de la chaîne vide. */
static void ajouter_octets(bee_tampon *t, const void *p, size_t n)
{
    ajouter_entier(t, p ? (unsigned long long)n : ~0ull);
    if (p)
        ajouter(t, p, n);
}

static void ajouter_chaine(bee_tampon *t, const void *s)
{
    ajouter_octets(t, s, s ? strlen((const char *)s) : 0);
}

static void ajouter_marque(bee_tampon *t, yaml_mark_t m)
{
    ajouter_entier(t, m.index);
    ajouter_entier(t, m.line);
    ajouter_entier(t, m.column);
}

typedef struct
{
    const unsigned char *p;
    size_t reste, morceau;
} lecture_decoupee;

static int lire_par_morceaux(void *donnees, unsigned char *tampon, size_t taille, size_t *lu)
{
    lecture_decoupee *l = (lecture_decoupee *)donnees;
    size_t n = l->morceau < taille ? l->morceau : taille;
    if (n > l->reste)
        n = l->reste;
    memcpy(tampon, l->p, n);
    l->p += n;
    l->reste -= n;
    *lu = n;
    return 1;
}

static void serialiser_evenement(bee_tampon *t, const yaml_event_t *e)
{
    yaml_tag_directive_t *d;
    ajouter_entier(t, e->type);
    ajouter_marque(t, e->start_mark);
    ajouter_marque(t, e->end_mark);
    switch (e->type)
    {
    case YAML_STREAM_START_EVENT:
        ajouter_entier(t, e->data.stream_start.encoding);
        break;
    case YAML_DOCUMENT_START_EVENT:
        ajouter_entier(t, e->data.document_start.version_directive != NULL);
        if (e->data.document_start.version_directive)
        {
            ajouter_entier(t, (unsigned long long)e->data.document_start.version_directive->major);
            ajouter_entier(t, (unsigned long long)e->data.document_start.version_directive->minor);
        }
        for (d = e->data.document_start.tag_directives.start; d && d != e->data.document_start.tag_directives.end; d++)
        {
            ajouter_chaine(t, d->handle);
            ajouter_chaine(t, d->prefix);
        }
        ajouter_entier(t, (unsigned long long)e->data.document_start.implicit);
        break;
    case YAML_DOCUMENT_END_EVENT:
        ajouter_entier(t, (unsigned long long)e->data.document_end.implicit);
        break;
    case YAML_ALIAS_EVENT:
        ajouter_chaine(t, e->data.alias.anchor);
        break;
    case YAML_SCALAR_EVENT:
        ajouter_chaine(t, e->data.scalar.anchor);
        ajouter_chaine(t, e->data.scalar.tag);
        ajouter_octets(t, e->data.scalar.value, e->data.scalar.length);
        ajouter_entier(t, (unsigned long long)e->data.scalar.plain_implicit);
        ajouter_entier(t, (unsigned long long)e->data.scalar.quoted_implicit);
        ajouter_entier(t, e->data.scalar.style);
        break;
    case YAML_SEQUENCE_START_EVENT:
        ajouter_chaine(t, e->data.sequence_start.anchor);
        ajouter_chaine(t, e->data.sequence_start.tag);
        ajouter_entier(t, (unsigned long long)e->data.sequence_start.implicit);
        ajouter_entier(t, e->data.sequence_start.style);
        break;
    case YAML_MAPPING_START_EVENT:
        ajouter_chaine(t, e->data.mapping_start.anchor);
        ajouter_chaine(t, e->data.mapping_start.tag);
        ajouter_entier(t, (unsigned long long)e->data.mapping_start.implicit);
        ajouter_entier(t, e->data.mapping_start.style);
        break;
    default:
        break;
    }
}

/* Analyse l'entrée, sérialise le flux dans *sortie. Renvoie 0 (succès), 1 (erreur d'analyse) ou 2
   (initialisation impossible). */
int bee_flux(const uint8_t *donnees, size_t taille, bee_tampon *sortie)
{
    yaml_parser_t parser;
    yaml_event_t evenement;
    lecture_decoupee lecture;
    unsigned char mode = taille ? donnees[0] : 0;
    int statut = 0;

    if (taille)
        donnees++, taille--;
    if (!yaml_parser_initialize(&parser))
        return 2;
    if (mode == 0)
        yaml_parser_set_input_string(&parser, donnees, taille);
    else
    {
        lecture.p = donnees;
        lecture.reste = taille;
        lecture.morceau = mode;
        yaml_parser_set_input(&parser, lire_par_morceaux, &lecture);
    }
    for (;;)
    {
        yaml_event_type_t type;
        if (!yaml_parser_parse(&parser, &evenement))
        {
            statut = 1;
            ajouter_entier(sortie, 0xEEEEEEEEull);
            ajouter_entier(sortie, parser.error);
            ajouter_chaine(sortie, parser.problem);
            ajouter_entier(sortie, parser.problem_offset);
            ajouter_entier(sortie, (unsigned long long)(long long)parser.problem_value);
            ajouter_marque(sortie, parser.problem_mark);
            ajouter_chaine(sortie, parser.context);
            ajouter_marque(sortie, parser.context_mark);
            break;
        }
        serialiser_evenement(sortie, &evenement);
        type = evenement.type;
        yaml_event_delete(&evenement);
        if (type == YAML_STREAM_END_EVENT)
            break;
    }
    yaml_parser_delete(&parser);
    return statut;
}

#ifndef BEE_FLUX_SEUL

#ifndef BEE_SANS_REFERENCE
int ref_bee_flux(const uint8_t *donnees, size_t taille, bee_tampon *sortie);

static void signaler_ecart(int sa, int sb, const bee_tampon *a, const bee_tampon *b)
{
    size_t i = 0, n = a->taille < b->taille ? a->taille : b->taille;
    while (i < n && a->octets[i] == b->octets[i])
        i++;
    /* Pas de contenu de l'entrée ici : seulement des positions (lancer.sh masque tout en mode discret). */
    fprintf(stderr, "fuzz_parse : ÉCART base/candidat : statut %d contre %d, flux de %zu contre %zu octets, "
                    "premier octet différent à %zu.\n", sb, sa, b->taille, a->taille, i);
}
#endif

int LLVMFuzzerTestOneInput(const uint8_t *donnees, size_t taille)
{
    bee_tampon a = { NULL, 0, 0 };
    int sa = bee_flux(donnees, taille, &a);
#ifndef BEE_SANS_REFERENCE
    bee_tampon b = { NULL, 0, 0 };
    int sb = ref_bee_flux(donnees, taille, &b);
    if (sa != sb || a.taille != b.taille || (a.taille && memcmp(a.octets, b.octets, a.taille) != 0))
    {
        signaler_ecart(sa, sb, &a, &b);
        abort();
    }
    free(b.octets);
#else
    (void)sa;
#endif
    free(a.octets);
    return 0;
}

#endif
