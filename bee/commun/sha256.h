/* SHA-256 (FIPS 180-4), implémentation directe et portable pour l'outillage Bee.
   Sert uniquement à calculer les empreintes des sorties compressées. */
#ifndef BEE_SHA256_H
#define BEE_SHA256_H

#include <stddef.h>
#include <stdint.h>

typedef struct
{
    uint32_t etat[8];
    uint64_t total;
    unsigned char bloc[64];
    size_t rempli;
} bee_sha256;

void bee_sha256_debut(bee_sha256 *c);
void bee_sha256_ajouter(bee_sha256 *c, const void *donnees, size_t taille);
void bee_sha256_fin(bee_sha256 *c, unsigned char resultat[32]);

/* Empreinte hexadécimale (64 caractères + zéro final) d'un tampon. */
void bee_sha256_hex(const void *donnees, size_t taille, char hex[65]);

#endif
