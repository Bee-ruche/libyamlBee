/* Chargement du corpus de référence : tous les fichiers ordinaires d'un dossier,
   récursivement, triés par chemin relatif (ordre des octets, comme SHA256SUMS). */
#ifndef BEE_CORPUS_H
#define BEE_CORPUS_H

#include <stddef.h>

typedef struct
{
    char *nom;              /* chemin relatif au dossier du corpus, séparateur « / » */
    unsigned char *donnees; /* contenu (jamais NULL, même pour un fichier vide) */
    size_t taille;
} bee_fichier;

typedef struct
{
    bee_fichier *fichiers;
    size_t nombre;
    size_t total; /* somme des tailles */
} bee_corpus;

/* Charge le corpus. Renvoie 0 si tout va bien, sinon affiche la cause et renvoie -1. */
int bee_corpus_charger(const char *dossier, bee_corpus *corpus);

/* Liste seulement les chemins (sans lire les contenus). Même ordre que bee_corpus_charger. */
int bee_corpus_lister(const char *dossier, bee_corpus *corpus);

void bee_corpus_liberer(bee_corpus *corpus);

#endif
