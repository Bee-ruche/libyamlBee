/* Voir corpus.h. */
#include "corpus.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

typedef struct
{
    char **noms;
    size_t nombre, capacite;
} liste_noms;

static int ajouter_nom(liste_noms *l, const char *nom)
{
    if (l->nombre == l->capacite)
    {
        size_t c = l->capacite ? 2 * l->capacite : 64;
        char **n = (char **)realloc(l->noms, c * sizeof(char *));
        if (!n)
            return -1;
        l->noms = n;
        l->capacite = c;
    }
    l->noms[l->nombre] = strdup(nom);
    if (!l->noms[l->nombre])
        return -1;
    l->nombre++;
    return 0;
}

static int parcourir(const char *racine, const char *relatif, liste_noms *l)
{
    char chemin[4096];
    DIR *d;
    struct dirent *e;
    snprintf(chemin, sizeof(chemin), "%s%s%s", racine, *relatif ? "/" : "", relatif);
    d = opendir(chemin);
    if (!d)
    {
        fprintf(stderr, "corpus : impossible d'ouvrir le dossier %s\n", chemin);
        return -1;
    }
    while ((e = readdir(d)) != NULL)
    {
        char rel[4096], complet[8192];
        struct stat st;
        if (e->d_name[0] == '.')
            continue; /* ignore ., .. et les fichiers cachés */
        snprintf(rel, sizeof(rel), "%s%s%s", relatif, *relatif ? "/" : "", e->d_name);
        snprintf(complet, sizeof(complet), "%s/%s", racine, rel);
        if (stat(complet, &st) != 0)
            continue;
        if (S_ISDIR(st.st_mode))
        {
            if (parcourir(racine, rel, l) != 0)
            {
                closedir(d);
                return -1;
            }
        }
        else if (S_ISREG(st.st_mode))
        {
            if (ajouter_nom(l, rel) != 0)
            {
                closedir(d);
                return -1;
            }
        }
    }
    closedir(d);
    return 0;
}

static int comparer_noms(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static int construire(const char *dossier, bee_corpus *corpus, int lire)
{
    liste_noms l = { NULL, 0, 0 };
    size_t i;
    memset(corpus, 0, sizeof(*corpus));
    if (parcourir(dossier, "", &l) != 0)
        goto echec;
    if (l.nombre == 0)
    {
        fprintf(stderr, "corpus : aucun fichier dans %s (lancez python3 bee/corpus/generer.py)\n", dossier);
        goto echec;
    }
    qsort(l.noms, l.nombre, sizeof(char *), comparer_noms);
    corpus->fichiers = (bee_fichier *)calloc(l.nombre, sizeof(bee_fichier));
    if (!corpus->fichiers)
        goto echec;
    corpus->nombre = l.nombre;
    for (i = 0; i < l.nombre; i++)
    {
        bee_fichier *f = &corpus->fichiers[i];
        char chemin[8192];
        FILE *fp;
        long taille;
        f->nom = l.noms[i];
        l.noms[i] = NULL;
        if (!lire)
            continue;
        snprintf(chemin, sizeof(chemin), "%s/%s", dossier, f->nom);
        fp = fopen(chemin, "rb");
        if (!fp || fseek(fp, 0, SEEK_END) != 0 || (taille = ftell(fp)) < 0 || fseek(fp, 0, SEEK_SET) != 0)
        {
            fprintf(stderr, "corpus : lecture impossible de %s\n", chemin);
            if (fp)
                fclose(fp);
            goto echec;
        }
        f->taille = (size_t)taille;
        f->donnees = (unsigned char *)malloc(f->taille ? f->taille : 1);
        if (!f->donnees || (f->taille && fread(f->donnees, 1, f->taille, fp) != f->taille))
        {
            fprintf(stderr, "corpus : lecture incomplète de %s\n", chemin);
            fclose(fp);
            goto echec;
        }
        fclose(fp);
        corpus->total += f->taille;
    }
    free(l.noms);
    return 0;
echec:
    for (i = 0; i < l.nombre; i++)
        free(l.noms[i]);
    free(l.noms);
    bee_corpus_liberer(corpus);
    return -1;
}

int bee_corpus_charger(const char *dossier, bee_corpus *corpus)
{
    return construire(dossier, corpus, 1);
}

int bee_corpus_lister(const char *dossier, bee_corpus *corpus)
{
    return construire(dossier, corpus, 0);
}

void bee_corpus_liberer(bee_corpus *corpus)
{
    size_t i;
    if (corpus->fichiers)
    {
        for (i = 0; i < corpus->nombre; i++)
        {
            free(corpus->fichiers[i].nom);
            free(corpus->fichiers[i].donnees);
        }
        free(corpus->fichiers);
    }
    memset(corpus, 0, sizeof(*corpus));
}
