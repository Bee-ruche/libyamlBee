# Construction de l'outillage Bee pour libyaml.
#
#   make -C bee oracle           harnais d'analyse (flux d'événements) — assertions actives
#   make -C bee aller-retour     aller-retour de l'émetteur (événements → YAML → événements) — assertions actives
#   make -C bee banc             banc de mesure (options « Release » : -O3 -DNDEBUG)
#   make -C bee fuzz-libfuzzer    harnais libFuzzer (clang complet requis)
#   make -C bee fuzz-gcc          mêmes harnais, pilote aléatoire + ASan/UBSan de gcc (repli local)
#
# Variables utiles :
#   SOURCE  dossier qui contient les sources de libyaml à juger (défaut : la racine du dépôt).
#           ab.py et la CI s'en servent pour compiler l'outillage d'une révision contre une autre.
#   CONSTR  dossier de construction (défaut : bee/construction/<cible>).
#   CC      compilateur C (défaut : cc).
#
# libyaml se compile sans config.h (il ne l'inclut que sous HAVE_CONFIG_H) : on fournit seulement
# les macros de version et YAML_DECLARE_STATIC pour l'édition de liens statique.

ICI     := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SOURCE  ?= $(abspath $(ICI)/..)
CONSTR  ?= $(ICI)/construction/$(if $(filter-out tout,$(firstword $(MAKECMDGOALS))),$(firstword $(MAKECMDGOALS)),commun)
CC      ?= cc
CLANG   ?= clang

YAML_SRC := $(wildcard $(SOURCE)/src/*.c)
YAML_H   := $(wildcard $(SOURCE)/include/*.h) $(wildcard $(SOURCE)/src/*.h)
COMMUN   := $(ICI)/commun/sha256.c $(ICI)/commun/corpus.c
COMMUN_H := $(wildcard $(ICI)/commun/*.h)

INCLUDES := -I$(SOURCE)/include -I$(ICI)/commun
AVERTISSEMENTS := -Wall -Wextra -Wno-unused-parameter
VERSION_DEFS := -DYAML_DECLARE_STATIC -DYAML_VERSION_MAJOR=0 -DYAML_VERSION_MINOR=2 \
                -DYAML_VERSION_PATCH=5 -DYAML_VERSION_STRING='"0.2.5"'

# Banc : options « Release » (libyaml se construit en -O2/-O3 sans assertions).
OPT_BANC  ?= -O3 -DNDEBUG
# Oracle et tests : -O2 avec assertions (assert de libyaml) actives, pour attraper une incohérence.
OPT_TESTS ?= -O2 -g

CACHEGRIND := $(shell printf '\043include <valgrind/cachegrind.h>\nint main(void){return 0;}\n' | $(CC) -x c - -o /dev/null 2>/dev/null && echo -DBEE_AVEC_CACHEGRIND)

.PHONY: oracle aller-retour banc fuzz-libfuzzer fuzz-gcc tout nettoyer

tout: oracle aller-retour banc

oracle: $(CONSTR)/oracle
aller-retour: $(CONSTR)/aller_retour
banc: $(CONSTR)/banc

$(CONSTR)/oracle: $(ICI)/tests/oracle.c $(YAML_SRC) $(YAML_H)
	@mkdir -p $(CONSTR)
	$(CC) $(OPT_TESTS) -std=gnu99 $(AVERTISSEMENTS) $(VERSION_DEFS) $(INCLUDES) \
	  $(ICI)/tests/oracle.c $(YAML_SRC) -o $@

$(CONSTR)/aller_retour: $(ICI)/tests/aller_retour.c $(ICI)/commun/sha256.c $(COMMUN_H) $(YAML_SRC) $(YAML_H)
	@mkdir -p $(CONSTR)
	$(CC) $(OPT_TESTS) -std=gnu99 $(AVERTISSEMENTS) $(VERSION_DEFS) $(INCLUDES) \
	  $(ICI)/tests/aller_retour.c $(ICI)/commun/sha256.c $(YAML_SRC) -o $@

# libyaml compilé seul avec ses options Release ; -g sert au profilage (cachegrind, callgrind).
OBJETS_YAML := $(patsubst $(SOURCE)/src/%.c,$(CONSTR)/banc-%.o,$(YAML_SRC))

$(CONSTR)/banc-%.o: $(SOURCE)/src/%.c $(YAML_H)
	@mkdir -p $(CONSTR)
	$(CC) $(OPT_BANC) -g -std=gnu99 $(VERSION_DEFS) $(INCLUDES) -c $< -o $@

$(CONSTR)/banc: $(ICI)/bench/banc.c $(COMMUN) $(COMMUN_H) $(OBJETS_YAML)
	$(CC) $(OPT_BANC) -g -std=gnu99 $(AVERTISSEMENTS) $(CACHEGRIND) $(VERSION_DEFS) $(INCLUDES) \
	  $(ICI)/bench/banc.c $(COMMUN) $(OBJETS_YAML) -o $@

# ------------------------------------------------------------------ fuzzing
HARNAIS := fuzz_parse
FUZZ_DRAPEAUX := -g -O1 -DNDEBUG -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=all

fuzz-libfuzzer: $(addprefix $(CONSTR)/libfuzzer-,$(HARNAIS))
fuzz-gcc: $(addprefix $(CONSTR)/gcc-,$(HARNAIS))

$(CONSTR)/libfuzzer-%: $(ICI)/fuzz/%.c $(YAML_SRC) $(YAML_H)
	@mkdir -p $(CONSTR)
	$(CLANG) $(FUZZ_DRAPEAUX) -fsanitize=fuzzer -std=gnu99 $(VERSION_DEFS) $(INCLUDES) \
	  $< $(YAML_SRC) -o $@

$(CONSTR)/gcc-%: $(ICI)/fuzz/%.c $(ICI)/fuzz/pilote_aleatoire.c $(YAML_SRC) $(YAML_H)
	@mkdir -p $(CONSTR)
	$(CC) $(FUZZ_DRAPEAUX) -std=gnu99 $(VERSION_DEFS) $(INCLUDES) \
	  $< $(ICI)/fuzz/pilote_aleatoire.c $(YAML_SRC) -o $@

nettoyer:
	rm -rf $(CONSTR)
