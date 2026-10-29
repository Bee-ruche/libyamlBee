/* Oracle d'aller-retour de l'émetteur de libyaml (Bee, tâche libyaml-0003).

   Pour chaque fichier passé en argument :
     1. analyse (yaml_parser_parse) : flux d'événements A, gardé en mémoire ;
     2. ré-émission de A par yaml_emitter_emit, avec les réglages PAR DÉFAUT de l'émetteur (ceux du
        banc, bee/bench/banc.c : ni canonique, ni unicode, indentation 2, largeur 80, sauts LN) : texte T ;
     3. analyse de T : flux B, comparé à A événement par événement, au fil de la lecture.

   Sortie standard, une ligne par fichier : « <sha256 de T>  <statut>  <nom> », où statut vaut
     ok      B est identique à A, aux seules normalisations N1 à N4 ci-dessous près ;
     rejete  l'entrée est invalide (erreur d'analyse à l'étape 1) : rien n'est émis, l'empreinte est
             celle du texte vide. Ce n'est pas un échec de l'émetteur : l'oracle d'analyse (oracle.c)
             juge déjà ces entrées ; on les compte, sans faux échec ;
     echec   l'émetteur refuse un événement, ou T ne s'analyse pas, ou B diffère de A (détail sur stderr).
   bee/tests/lancer.sh compare ces lignes à bee/tests/empreintes-aller-retour.txt, figé à la révision
   de base : l'empreinte de T repère TOUT changement de la sortie de l'émetteur (même un changement
   que la relecture tolère, comme une autre indentation) ; la comparaison A/B prouve que T relit la
   même chose. Bilan des normalisations utilisées sur la sortie d'erreur, en fin de passe.

   Comparé strictement : nombre, ordre et type des événements ; encodage du flux ; directives %YAML
   et %TAG (nombre, ordre, poignée, préfixe) ; indicateur implicite du début de document (l'analyseur
   ne le met qu'au premier document, sans directive, et l'émetteur l'y garde) ; ancres et alias ;
   étiquettes des collections et leur indicateur implicite ; style des collections (bloc ou flow) ;
   octets et longueur de chaque scalaire ; indicateurs plain_implicit et quoted_implicit des scalaires
   (ils décident de la résolution de l'étiquette : « 123 » nu est un entier, « '123' » une chaîne).

   Normalisations tolérées, et seulement elles (chacune vient d'une règle de src/emitter.c) :
     N1  Positions (start_mark, end_mark) ignorées : elles décrivent le texte source, qui change.
     N2  Style de scalaire, seulement dans le sens où yaml_emitter_select_scalar_style le change quand
         le style demandé est impossible à cet endroit : plain -> ' ou ", ' -> ", | ou > -> ".
         Jamais l'inverse, jamais | <-> >, jamais vers plain.
     N3  Étiquette de scalaire absente <-> « ! », seulement si plain_implicit vaut 1 des deux côtés :
         l'analyseur met plain_implicit à 1 pour un scalaire plain sans étiquette comme pour une
         étiquette « ! » ; l'émetteur écrit « ! » quand il doit mettre entre guillemets un tel
         scalaire, et l'omet quand il l'écrit plain.
     N4  Fin de document implicite -> explicite (« ... ») : l'émetteur l'écrit en fin de flux après un
         scalaire bloc qui garde ses lignes vides finales (open_ended == 2), et avant les directives du
         document suivant. L'inverse est un échec.

   Inspiré de compare_events() de tests/run-emitter.c (libyaml, licence MIT), qui ignore en plus tout
   style, l'encodage et les indicateurs de document dans les deux sens.

   Usage : aller_retour <fichier>...              une ligne par fichier (voir plus haut)
           aller_retour --internes [<fichier>...] ajoute les cas intégrés (INTERNES, plus bas), nommés
                                                  « interne/<cas> » ; lancer.sh s'en sert
           aller_retour --emis <fichier>          écrit seulement T sur la sortie standard (inspection)
   Code de sortie : 0 sans échec, 1 si au moins un document est en échec, 2 sur erreur d'usage ou système. */

#include <yaml.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sha256.h"

enum { OK, REJETE, ECHEC, ERREUR };
static const char *const NOM_STATUT[] = {"ok", "rejete", "echec", "erreur"};

typedef struct { unsigned char *octets; size_t taille, capacite; } tampon;
typedef struct { yaml_event_t *ev; size_t nombre, capacite; } flux;
typedef struct { unsigned long evenements, style, etiquette, fin_doc; } bilan;

static const unsigned char VIDE[1] = {0};

static int ajouter(tampon *t, const unsigned char *octets, size_t n)
{
    if (n > t->capacite - t->taille) {
        size_t capacite = t->capacite ? t->capacite : 65536;
        unsigned char *p;
        while (capacite - t->taille < n) capacite *= 2;
        p = realloc(t->octets, capacite);
        if (!p) return 0;
        t->octets = p;
        t->capacite = capacite;
    }
    if (n) memcpy(t->octets + t->taille, octets, n);
    t->taille += n;
    return 1;
}

static int ecrire_tampon(void *donnee, unsigned char *octets, size_t taille)
{
    return ajouter((tampon *)donnee, octets, taille);
}

static int lire_fichier(const char *chemin, tampon *t)
{
    unsigned char bloc[65536];
    size_t lu;
    int ok = 1;
    FILE *f = fopen(chemin, "rb");
    if (!f) return 0;
    while (ok && (lu = fread(bloc, 1, sizeof bloc, f)) > 0) ok = ajouter(t, bloc, lu);
    if (ferror(f)) ok = 0;
    fclose(f);
    return ok;
}

/* Copie d'un événement analysé, à confier à l'émetteur (qui la détruit). Comme copy_event() de
   tests/run-emitter.c. Renvoie 0 si la copie est impossible. */
static int copier(yaml_event_t *vers, const yaml_event_t *de)
{
    switch (de->type) {
    case YAML_STREAM_START_EVENT:
        return yaml_stream_start_event_initialize(vers, de->data.stream_start.encoding);
    case YAML_STREAM_END_EVENT:
        return yaml_stream_end_event_initialize(vers);
    case YAML_DOCUMENT_START_EVENT:
        return yaml_document_start_event_initialize(vers, de->data.document_start.version_directive,
                de->data.document_start.tag_directives.start, de->data.document_start.tag_directives.end,
                de->data.document_start.implicit);
    case YAML_DOCUMENT_END_EVENT:
        return yaml_document_end_event_initialize(vers, de->data.document_end.implicit);
    case YAML_ALIAS_EVENT:
        return yaml_alias_event_initialize(vers, de->data.alias.anchor);
    case YAML_SCALAR_EVENT:
        return yaml_scalar_event_initialize(vers, de->data.scalar.anchor, de->data.scalar.tag,
                de->data.scalar.value, (int)de->data.scalar.length, de->data.scalar.plain_implicit,
                de->data.scalar.quoted_implicit, de->data.scalar.style);
    case YAML_SEQUENCE_START_EVENT:
        return yaml_sequence_start_event_initialize(vers, de->data.sequence_start.anchor,
                de->data.sequence_start.tag, de->data.sequence_start.implicit, de->data.sequence_start.style);
    case YAML_SEQUENCE_END_EVENT:
        return yaml_sequence_end_event_initialize(vers);
    case YAML_MAPPING_START_EVENT:
        return yaml_mapping_start_event_initialize(vers, de->data.mapping_start.anchor,
                de->data.mapping_start.tag, de->data.mapping_start.implicit, de->data.mapping_start.style);
    case YAML_MAPPING_END_EVENT:
        return yaml_mapping_end_event_initialize(vers);
    default:
        return 0;
    }
}

/* Une ligne lisible qui décrit un événement (diagnostic d'échec seulement). */
static void decrire(const yaml_event_t *e)
{
    static const char STYLES[] = "?:'\"|>";
    const yaml_char_t *ancre = NULL, *etiquette = NULL;
    int implicite = 0;
    size_t i;
    switch (e->type) {
    case YAML_STREAM_START_EVENT: fprintf(stderr, "+STR (encodage %d)", e->data.stream_start.encoding); break;
    case YAML_STREAM_END_EVENT: fprintf(stderr, "-STR"); break;
    case YAML_DOCUMENT_START_EVENT:
        fprintf(stderr, "+DOC%s", e->data.document_start.implicit ? "" : " ---");
        if (e->data.document_start.version_directive)
            fprintf(stderr, " %%YAML %d.%d", e->data.document_start.version_directive->major,
                    e->data.document_start.version_directive->minor);
        fprintf(stderr, " (%ld %%TAG)", (long)(e->data.document_start.tag_directives.end
                    - e->data.document_start.tag_directives.start));
        break;
    case YAML_DOCUMENT_END_EVENT: fprintf(stderr, "-DOC%s", e->data.document_end.implicit ? "" : " ..."); break;
    case YAML_ALIAS_EVENT: fprintf(stderr, "=ALI *%s", e->data.alias.anchor); break;
    case YAML_SEQUENCE_END_EVENT: fprintf(stderr, "-SEQ"); break;
    case YAML_MAPPING_END_EVENT: fprintf(stderr, "-MAP"); break;
    case YAML_SEQUENCE_START_EVENT:
    case YAML_MAPPING_START_EVENT:
        if (e->type == YAML_SEQUENCE_START_EVENT) {
            fprintf(stderr, "+SEQ%s", e->data.sequence_start.style == YAML_FLOW_SEQUENCE_STYLE ? " []" : "");
            ancre = e->data.sequence_start.anchor; etiquette = e->data.sequence_start.tag;
            implicite = e->data.sequence_start.implicit;
        } else {
            fprintf(stderr, "+MAP%s", e->data.mapping_start.style == YAML_FLOW_MAPPING_STYLE ? " {}" : "");
            ancre = e->data.mapping_start.anchor; etiquette = e->data.mapping_start.tag;
            implicite = e->data.mapping_start.implicit;
        }
        if (ancre) fprintf(stderr, " &%s", ancre);
        if (etiquette) fprintf(stderr, " <%s>", etiquette);
        fprintf(stderr, " [implicit=%d]", implicite);
        break;
    case YAML_SCALAR_EVENT:
        fprintf(stderr, "=VAL");
        if (e->data.scalar.anchor) fprintf(stderr, " &%s", e->data.scalar.anchor);
        if (e->data.scalar.tag) fprintf(stderr, " <%s>", e->data.scalar.tag);
        fprintf(stderr, " %c", (unsigned)e->data.scalar.style < sizeof STYLES - 1 ? STYLES[e->data.scalar.style] : '?');
        for (i = 0; i < e->data.scalar.length && i < 60; i++) {
            unsigned char c = e->data.scalar.value[i];
            if (c == '\n') fprintf(stderr, "\\n");
            else if (c == '\\') fprintf(stderr, "\\\\");
            else if (c < 0x20 || c == 0x7f) fprintf(stderr, "\\x%02x", c);
            else fputc(c, stderr);
        }
        if (e->data.scalar.length > 60) fprintf(stderr, "… (%lu octets)", (unsigned long)e->data.scalar.length);
        fprintf(stderr, " [plain_implicit=%d quoted_implicit=%d]", e->data.scalar.plain_implicit,
                e->data.scalar.quoted_implicit);
        break;
    default: fprintf(stderr, "(événement de type %d)", (int)e->type); break;
    }
    fputc('\n', stderr);
}

static int memes(const yaml_char_t *a, const yaml_char_t *b)
{
    if (!a || !b) return a == b;
    return strcmp((const char *)a, (const char *)b) == 0;
}

static int absente_ou_bang(const yaml_char_t *etiquette)
{
    return !etiquette || strcmp((const char *)etiquette, "!") == 0;
}

/* N2 : les seuls changements de style que fait yaml_emitter_select_scalar_style. */
static int style_tolere(yaml_scalar_style_t avant, yaml_scalar_style_t apres)
{
    switch (avant) {
    case YAML_PLAIN_SCALAR_STYLE:
        return apres == YAML_SINGLE_QUOTED_SCALAR_STYLE || apres == YAML_DOUBLE_QUOTED_SCALAR_STYLE;
    case YAML_SINGLE_QUOTED_SCALAR_STYLE:
    case YAML_LITERAL_SCALAR_STYLE:
    case YAML_FOLDED_SCALAR_STYLE:
        return apres == YAML_DOUBLE_QUOTED_SCALAR_STYLE;
    default:
        return 0;
    }
}

#define ECART(texte) do { *motif = (texte); return 0; } while (0)

/* Compare l'événement analysé a et l'événement relu b. Renvoie 1 s'ils sont équivalents (et compte
   les normalisations utilisées dans n), 0 sinon (motif renseigné). */
static int comparer(const yaml_event_t *a, const yaml_event_t *b, bilan *n, const char **motif)
{
    long k, nombre;
    if (a->type != b->type) ECART("type d'événement différent");
    switch (a->type) {
    case YAML_STREAM_START_EVENT:
        if (a->data.stream_start.encoding != b->data.stream_start.encoding) ECART("encodage différent");
        return 1;
    case YAML_DOCUMENT_START_EVENT: {
        const yaml_version_directive_t *va = a->data.document_start.version_directive;
        const yaml_version_directive_t *vb = b->data.document_start.version_directive;
        const yaml_tag_directive_t *da = a->data.document_start.tag_directives.start;
        const yaml_tag_directive_t *db = b->data.document_start.tag_directives.start;
        if (!va != !vb || (va && (va->major != vb->major || va->minor != vb->minor)))
            ECART("directive %YAML différente");
        nombre = (long)(a->data.document_start.tag_directives.end - da);
        if (nombre != (long)(b->data.document_start.tag_directives.end - db))
            ECART("nombre de directives %TAG différent");
        for (k = 0; k < nombre; k++)
            if (!memes(da[k].handle, db[k].handle) || !memes(da[k].prefix, db[k].prefix))
                ECART("directive %TAG différente");
        if (a->data.document_start.implicit != b->data.document_start.implicit)
            ECART("indicateur implicite du début de document différent");
        return 1;
    }
    case YAML_DOCUMENT_END_EVENT:
        if (a->data.document_end.implicit != b->data.document_end.implicit) {
            if (!a->data.document_end.implicit) ECART("fin de document devenue implicite");
            n->fin_doc++; /* N4 */
        }
        return 1;
    case YAML_ALIAS_EVENT:
        if (!memes(a->data.alias.anchor, b->data.alias.anchor)) ECART("alias différent");
        return 1;
    case YAML_SCALAR_EVENT:
        if (!memes(a->data.scalar.anchor, b->data.scalar.anchor)) ECART("ancre différente");
        if (a->data.scalar.length != b->data.scalar.length
                || memcmp(a->data.scalar.value, b->data.scalar.value, a->data.scalar.length) != 0)
            ECART("valeur du scalaire différente");
        if (a->data.scalar.plain_implicit != b->data.scalar.plain_implicit
                || a->data.scalar.quoted_implicit != b->data.scalar.quoted_implicit)
            ECART("indicateurs plain_implicit / quoted_implicit différents");
        if (!memes(a->data.scalar.tag, b->data.scalar.tag)) {
            if (!(a->data.scalar.plain_implicit && absente_ou_bang(a->data.scalar.tag)
                        && absente_ou_bang(b->data.scalar.tag)))
                ECART("étiquette du scalaire différente");
            n->etiquette++; /* N3 */
        }
        if (a->data.scalar.style != b->data.scalar.style) {
            if (!style_tolere(a->data.scalar.style, b->data.scalar.style))
                ECART("style du scalaire changé hors des cas tolérés (N2)");
            n->style++; /* N2 */
        }
        return 1;
    case YAML_SEQUENCE_START_EVENT:
        if (!memes(a->data.sequence_start.anchor, b->data.sequence_start.anchor)) ECART("ancre différente");
        if (!memes(a->data.sequence_start.tag, b->data.sequence_start.tag)) ECART("étiquette différente");
        if (a->data.sequence_start.implicit != b->data.sequence_start.implicit) ECART("indicateur implicite différent");
        if (a->data.sequence_start.style != b->data.sequence_start.style) ECART("style de séquence différent");
        return 1;
    case YAML_MAPPING_START_EVENT:
        if (!memes(a->data.mapping_start.anchor, b->data.mapping_start.anchor)) ECART("ancre différente");
        if (!memes(a->data.mapping_start.tag, b->data.mapping_start.tag)) ECART("étiquette différente");
        if (a->data.mapping_start.implicit != b->data.mapping_start.implicit) ECART("indicateur implicite différent");
        if (a->data.mapping_start.style != b->data.mapping_start.style) ECART("style de mapping différent");
        return 1;
    default:
        return 1;
    }
}

/* Étape 1. Renvoie 1 si l'analyse réussit, 0 si l'entrée est invalide, -1 sur manque de mémoire. */
static int analyser(const tampon *entree, flux *a, const char *nom)
{
    yaml_parser_t p;
    if (!yaml_parser_initialize(&p)) return -1;
    yaml_parser_set_input_string(&p, entree->taille ? entree->octets : VIDE, entree->taille);
    for (;;) {
        yaml_event_t e;
        if (a->nombre == a->capacite) {
            size_t capacite = a->capacite ? 2 * a->capacite : 1024;
            yaml_event_t *ev = realloc(a->ev, capacite * sizeof *ev);
            if (!ev) { yaml_parser_delete(&p); return -1; }
            a->ev = ev;
            a->capacite = capacite;
        }
        if (!yaml_parser_parse(&p, &e)) {
            int memoire = p.error == YAML_MEMORY_ERROR;
            if (!memoire)
                fprintf(stderr, "%s : entrée invalide, rejetée par l'analyseur : %s (ligne %lu, colonne %lu)\n",
                        nom, p.problem ? p.problem : "?", (unsigned long)p.problem_mark.line + 1,
                        (unsigned long)p.problem_mark.column + 1);
            yaml_parser_delete(&p);
            return memoire ? -1 : 0;
        }
        a->ev[a->nombre++] = e;
        if (e.type == YAML_STREAM_END_EVENT) break;
    }
    yaml_parser_delete(&p);
    return 1;
}

/* Étape 2. Renvoie 1 si l'émetteur accepte tout le flux. */
static int emettre(const flux *a, tampon *t, const char *nom)
{
    yaml_emitter_t em;
    size_t i;
    if (!yaml_emitter_initialize(&em)) return 0;
    yaml_emitter_set_output(&em, ecrire_tampon, t);
    for (i = 0; i < a->nombre; i++) {
        yaml_event_t copie;
        if (!copier(&copie, &a->ev[i])) {
            fprintf(stderr, "%s : ÉCHEC, copie de l'événement n° %lu impossible\n", nom, (unsigned long)i + 1);
            yaml_emitter_delete(&em);
            return 0;
        }
        /* L'émetteur prend possession de la copie et la libère, même en cas d'échec. */
        if (!yaml_emitter_emit(&em, &copie)) {
            fprintf(stderr, "%s : ÉCHEC, l'émetteur refuse l'événement n° %lu : %s\n", nom,
                    (unsigned long)i + 1, em.problem ? em.problem : "?");
            fprintf(stderr, "  analysé : ");
            decrire(&a->ev[i]);
            yaml_emitter_delete(&em);
            return 0;
        }
    }
    yaml_emitter_delete(&em);
    return 1;
}

/* Étape 3. Renvoie 1 si la relecture de t redonne le flux a (aux normalisations près). */
static int relire(const tampon *t, const flux *a, bilan *n, const char *nom)
{
    yaml_parser_t p;
    size_t i = 0;
    int fini = 0;
    if (!yaml_parser_initialize(&p)) return 0;
    yaml_parser_set_input_string(&p, t->taille ? t->octets : VIDE, t->taille);
    while (!fini) {
        yaml_event_t e;
        const char *motif = "la relecture produit plus d'événements que l'analyse";
        if (!yaml_parser_parse(&p, &e)) {
            fprintf(stderr, "%s : ÉCHEC, la sortie émise ne s'analyse pas (événement n° %lu) : %s (ligne %lu, colonne %lu)\n",
                    nom, (unsigned long)i + 1, p.problem ? p.problem : "?",
                    (unsigned long)p.problem_mark.line + 1, (unsigned long)p.problem_mark.column + 1);
            yaml_parser_delete(&p);
            return 0;
        }
        if (i >= a->nombre || !comparer(&a->ev[i], &e, n, &motif)) {
            fprintf(stderr, "%s : ÉCHEC à l'événement n° %lu : %s\n", nom, (unsigned long)i + 1, motif);
            if (i < a->nombre) { fprintf(stderr, "  analysé : "); decrire(&a->ev[i]); }
            fprintf(stderr, "  relu    : ");
            decrire(&e);
            yaml_event_delete(&e);
            yaml_parser_delete(&p);
            return 0;
        }
        fini = e.type == YAML_STREAM_END_EVENT;
        yaml_event_delete(&e);
        i++;
    }
    yaml_parser_delete(&p);
    if (i != a->nombre) {
        fprintf(stderr, "%s : ÉCHEC, la relecture donne %lu événements, l'analyse %lu\n", nom,
                (unsigned long)i, (unsigned long)a->nombre);
        return 0;
    }
    n->evenements += i;
    return 1;
}

/* Cas intégrés (option --internes) : le corpus de référence ne fait jouer aucune normalisation et ne
   contient aucune entrée invalide. Ces petits documents exercent les choix de style de l'émetteur (N2 à
   N4), les directives, l'UTF-16, les clés longues et le repli des lignes, et le statut « rejete ». */
#define CAS(nom, texte) {nom, (const unsigned char *)(texte), sizeof(texte) - 1}
#define DIX "0123456789"
static const struct { const char *nom; const unsigned char *texte; size_t taille; } INTERNES[] = {
    CAS("n2-plain-multiligne", "a: x\n\n  y\n"),
    CAS("n2-simple-tabulation", "k: 'a\tb'\n"),
    CAS("n2-litteral-espace-final", "k: |\n  a  \n  b\n"),
    CAS("n2-plie-espace-final", "k: >\n  a  \n\n  b\n"),
    CAS("n2-non-ascii", "k: \xc3\xa9t\xc3\xa9\n"),
    CAS("n2-vide-en-flow", "{a: , b: c}\n"),
    CAS("n2-cle-vide", "k:\n? \n: v\n"),
    CAS("n3-etiquette-bang", "k: ! x\nq: ! \"y\"\n"),
    CAS("n4-bloc-garde-en-fin", "k: >+\n  a\n\n"),
    CAS("n4-directive-apres-document-implicite", "[a]\n%YAML 1.1\n---\nb\n"),
    CAS("directives", "%YAML 1.1\n%TAG !e! tag:example.com,2000:\n---\n!e!foo bar\n"),
    CAS("etiquettes", "- !!binary |\n  R0lG\n- !local {x: 1}\n- &a !!seq [*a]\n"),
    CAS("ancre-vide-alias-en-cle", "a: &x\nb: *x\n*x : c\n"),
    CAS("cle-longue", DIX DIX DIX DIX DIX DIX DIX DIX DIX DIX DIX DIX DIX ": v\n"),
    CAS("plain-long", "k: " DIX " " DIX " " DIX " " DIX " " DIX " " DIX " " DIX " " DIX " " DIX "\n"),
    CAS("utf16le", "\xff\xfe" "a\0:\0 \0b\0\n\0"),
    CAS("commentaire-seul", "# rien\n"),
    CAS("vide", ""),
    CAS("invalide-crochet", "a: [b\n"),
    CAS("invalide-deux-points", "a: b: c\n"),
    CAS("invalide-tabulation", "\t- x\n"),
    CAS("invalide-document-sans-debut", "a\n...\nb\n"),
};

/* Traite un document : celui du fichier chemin, ou (chemin NULL) le texte donné. */
static int traiter(const char *nom, const char *chemin, const unsigned char *texte, size_t taille,
        int montrer, bilan *total)
{
    tampon entree = {0}, sortie = {0};
    flux a = {0};
    bilan local = {0};
    int statut = OK, r;
    size_t i;

    if (chemin ? !lire_fichier(chemin, &entree) : !ajouter(&entree, texte, taille)) {
        fprintf(stderr, "aller_retour : lecture impossible : %s\n", chemin ? chemin : nom);
        statut = ERREUR;
    } else if ((r = analyser(&entree, &a, nom)) <= 0) {
        statut = r < 0 ? ERREUR : REJETE;
        if (r < 0) fprintf(stderr, "aller_retour : %s : mémoire insuffisante\n", nom);
        sortie.taille = 0; /* rien n'est émis pour une entrée invalide */
    } else if (!emettre(&a, &sortie, nom) || !relire(&sortie, &a, &local, nom)) {
        statut = ECHEC;
    } else {
        total->evenements += local.evenements;
        total->style += local.style;
        total->etiquette += local.etiquette;
        total->fin_doc += local.fin_doc;
    }

    if (statut != ERREUR) {
        char hex[65];
        bee_sha256_hex(sortie.taille ? sortie.octets : VIDE, sortie.taille, hex);
        if (montrer) {
            if (sortie.taille) fwrite(sortie.octets, 1, sortie.taille, stdout);
            fprintf(stderr, "%s  %s  %s\n", hex, NOM_STATUT[statut], nom);
        } else {
            printf("%s  %s  %s\n", hex, NOM_STATUT[statut], nom);
        }
    }
    for (i = 0; i < a.nombre; i++) yaml_event_delete(&a.ev[i]);
    free(a.ev);
    free(entree.octets);
    free(sortie.octets);
    return statut;
}

int main(int argc, char *argv[])
{
    unsigned long compte[4] = {0, 0, 0, 0}, nombre = 0;
    bilan total = {0, 0, 0, 0};
    int i, premier = 1, montrer = 0, internes = 0;
    size_t k;

    if (argc > 1 && strcmp(argv[1], "--emis") == 0) montrer = 1, premier = 2;
    else if (argc > 1 && strcmp(argv[1], "--internes") == 0) internes = 1, premier = 2;
    if ((!internes && premier >= argc) || (montrer && argc != 3)) {
        fprintf(stderr, "usage : %s [--internes] <fichier>...  |  %s --internes  |  %s --emis <fichier>\n",
                argv[0], argv[0], argv[0]);
        return 2;
    }
    for (i = premier; i < argc; i++, nombre++) {
        const char *nom = strrchr(argv[i], '/') ? strrchr(argv[i], '/') + 1 : argv[i];
        compte[traiter(nom, argv[i], NULL, 0, montrer, &total)]++;
    }
    for (k = 0; internes && k < sizeof INTERNES / sizeof INTERNES[0]; k++, nombre++) {
        char nom[96];
        snprintf(nom, sizeof nom, "interne/%s", INTERNES[k].nom);
        compte[traiter(nom, NULL, INTERNES[k].texte, INTERNES[k].taille, 0, &total)]++;
    }
    fflush(stdout);

    fprintf(stderr, "Aller-retour : %lu documents : %lu ok, %lu rejetés (entrée invalide), %lu en échec",
            nombre, compte[OK], compte[REJETE], compte[ECHEC]);
    if (compte[ERREUR]) fprintf(stderr, ", %lu illisibles", compte[ERREUR]);
    fprintf(stderr, ".\n  %lu événements comparés ; normalisations tolérées : %lu styles de scalaire (N2), "
            "%lu étiquettes « ! » (N3), %lu fins de document rendues explicites (N4).\n",
            total.evenements, total.style, total.etiquette, total.fin_doc);
    if (compte[ERREUR]) return 2;
    return compte[ECHEC] ? 1 : 0;
}
