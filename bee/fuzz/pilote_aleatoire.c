/* Pilote de repli pour les harnais Bee quand libFuzzer n'est pas disponible (clang sans son runtime).

   Ce n'est PAS libFuzzer : pas de retour de couverture. Le pilote rejoue d'abord les fichiers donnés
   (graines, entrées fautives), puis génère pendant la durée demandée des entrées dérivées des graines
   par des mutations simples (bits inversés, octets remplacés, tranches copiées, troncatures, insertions)
   et des entrées entièrement aléatoires. Compilé avec gcc -fsanitize=address,undefined, il suffit à
   montrer que les harnais compilent et tournent ; la recherche sérieuse se fait en CI avec libFuzzer.

   Usage : gcc-<harnais> [-max_total_time=SECONDES] [-seed=N] [-artifact_prefix=DOSSIER/] [fichier|dossier]...
   (mêmes noms d'options que libFuzzer pour que bee/fuzz/lancer.sh appelle les deux de la même façon ;
   les autres options -xxx=yyy sont ignorées.)
   Une entrée qui fait échouer le harnais est écrite dans <artifact_prefix>crash-<numéro> avant l'abandon. */

#include <dirent.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

int LLVMFuzzerTestOneInput(const uint8_t *donnees, size_t taille);

#define TAILLE_MAX (64 * 1024)

typedef struct
{
    unsigned char *octets;
    size_t taille;
} entree;

static entree *graines = NULL;
static size_t nb_graines = 0;
static const unsigned char *entree_courante = NULL;
static size_t taille_courante = 0;
static char prefixe[1024] = "./";
static unsigned long long etat_alea = 0x9E3779B97F4A7C15ull;

static unsigned long long alea(void)
{
    /* xorshift64* : suffisant pour des mutations, reproductible avec -seed. */
    etat_alea ^= etat_alea >> 12;
    etat_alea ^= etat_alea << 25;
    etat_alea ^= etat_alea >> 27;
    return etat_alea * 2685821657736338717ull;
}

static void sauver_entree_fautive(int signal_recu)
{
    char chemin[1100];
    FILE *f;
    snprintf(chemin, sizeof(chemin), "%scrash-%ld", prefixe, (long)time(NULL));
    f = fopen(chemin, "wb");
    if (f && entree_courante)
    {
        fwrite(entree_courante, 1, taille_courante, f);
        fclose(f);
        fprintf(stderr, "pilote : entrée fautive (%zu octets) écrite dans %s\n", taille_courante, chemin);
    }
    signal(signal_recu, SIG_DFL);
    raise(signal_recu);
}

static void ajouter_graine(const unsigned char *p, size_t n)
{
    graines = (entree *)realloc(graines, (nb_graines + 1) * sizeof(entree));
    graines[nb_graines].octets = (unsigned char *)malloc(n ? n : 1);
    memcpy(graines[nb_graines].octets, p, n);
    graines[nb_graines].taille = n;
    nb_graines++;
}

static void lire_fichier(const char *chemin)
{
    FILE *f = fopen(chemin, "rb");
    unsigned char *tampon;
    size_t n;
    if (!f)
        return;
    tampon = (unsigned char *)malloc(TAILLE_MAX);
    n = fread(tampon, 1, TAILLE_MAX, f);
    fclose(f);
    ajouter_graine(tampon, n);
    free(tampon);
}

static void lire_chemin(const char *chemin)
{
    struct stat st;
    DIR *d;
    struct dirent *e;
    if (stat(chemin, &st) != 0)
        return;
    if (!S_ISDIR(st.st_mode))
    {
        lire_fichier(chemin);
        return;
    }
    d = opendir(chemin);
    if (!d)
        return;
    while ((e = readdir(d)) != NULL)
    {
        char complet[4096];
        if (e->d_name[0] == '.')
            continue;
        snprintf(complet, sizeof(complet), "%s/%s", chemin, e->d_name);
        lire_chemin(complet);
    }
    closedir(d);
}

static size_t muter(unsigned char *t, size_t n)
{
    int k, nb = 1 + (int)(alea() % 8);
    for (k = 0; k < nb; k++)
    {
        unsigned long long r = alea();
        switch (r % 6)
        {
        case 0: /* bit inversé */
            if (n)
                t[(r >> 8) % n] ^= (unsigned char)(1u << ((r >> 4) & 7));
            break;
        case 1: /* octet remplacé, valeur « intéressante » ou aléatoire */
            if (n)
            {
                static const unsigned char speciaux[] = { 0, 1, 0x7f, 0x80, 0xff, 0x78, 0x9c, 0x01, 0xda };
                t[(r >> 8) % n] = (r & 0x100) ? speciaux[(r >> 16) % sizeof(speciaux)] : (unsigned char)(r >> 24);
            }
            break;
        case 2: /* tranche copiée ailleurs */
            if (n > 2)
            {
                size_t de = (r >> 8) % n, vers = (r >> 24) % n, l = 1 + (r >> 40) % 64;
                if (de + l > n)
                    l = n - de;
                if (vers + l > n)
                    l = n - vers;
                memmove(t + vers, t + de, l);
            }
            break;
        case 3: /* troncature */
            if (n)
                n = (r >> 8) % (n + 1);
            break;
        case 4: /* insertion d'octets aléatoires */
        {
            size_t l = 1 + (r >> 8) % 32, ou = n ? (r >> 20) % n : 0, i;
            if (n + l > TAILLE_MAX)
                break;
            memmove(t + ou + l, t + ou, n - ou);
            for (i = 0; i < l; i++)
                t[ou + i] = (unsigned char)alea();
            n += l;
            break;
        }
        default: /* deux premiers octets (choix du mode dans les harnais) */
            if (n)
                t[0] = (unsigned char)(r >> 8);
            if (n > 1)
                t[1] = (unsigned char)(r >> 16);
            break;
        }
    }
    return n;
}

int main(int argc, char **argv)
{
    long duree = 10, iterations = 0;
    unsigned char *tampon = (unsigned char *)malloc(TAILLE_MAX);
    time_t debut, fin;
    int a;
    size_t i;

    for (a = 1; a < argc; a++)
    {
        if (!strncmp(argv[a], "-max_total_time=", 16))
            duree = atol(argv[a] + 16);
        else if (!strncmp(argv[a], "-seed=", 6))
            etat_alea = strtoull(argv[a] + 6, NULL, 10) * 2654435761ull + 1;
        else if (!strncmp(argv[a], "-artifact_prefix=", 17))
            snprintf(prefixe, sizeof(prefixe), "%s", argv[a] + 17);
        else if (argv[a][0] == '-')
            continue; /* option libFuzzer sans équivalent ici */
        else
            lire_chemin(argv[a]);
    }
    signal(SIGABRT, sauver_entree_fautive);
    signal(SIGSEGV, sauver_entree_fautive);

    /* Graines d'abord, telles quelles. */
    for (i = 0; i < nb_graines; i++)
    {
        entree_courante = graines[i].octets;
        taille_courante = graines[i].taille;
        LLVMFuzzerTestOneInput(graines[i].octets, graines[i].taille);
    }
    fprintf(stderr, "pilote : %zu graines rejouées, mutations aléatoires pendant %ld s\n", nb_graines, duree);

    debut = time(NULL);
    fin = debut + duree;
    while (time(NULL) < fin)
    {
        int k;
        for (k = 0; k < 64; k++)
        {
            size_t n;
            if (nb_graines && (alea() % 8) != 0)
            {
                const entree *g = &graines[alea() % nb_graines];
                n = g->taille;
                memcpy(tampon, g->octets, n);
            }
            else
            {
                size_t j;
                n = alea() % 2048;
                for (j = 0; j < n; j++)
                    tampon[j] = (unsigned char)alea();
            }
            n = muter(tampon, n);
            entree_courante = tampon;
            taille_courante = n;
            LLVMFuzzerTestOneInput(tampon, n);
            iterations++;
        }
    }
    fprintf(stderr, "pilote : terminé, %ld entrées en %ld s, aucun écart.\n", iterations, (long)(time(NULL) - debut));
    for (i = 0; i < nb_graines; i++)
        free(graines[i].octets);
    free(graines);
    free(tampon);
    return 0;
}
