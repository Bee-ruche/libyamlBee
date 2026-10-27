/* Oracle déterministe de Bee pour libyaml.

   Analyse le fichier passé en argument (ou stdin) et écrit sur la sortie standard le flux
   d'événements canonique de la yaml-test-suite (+STR, +DOC, +MAP &ancre <tag>, =VAL …, -SEQ, =ALI,
   etc.). Ce flux est une représentation fine et déterministe du résultat de l'analyse : une
   optimisation ne doit PAS le changer, ni changer le statut (succès / échec). bee/tests/lancer.sh
   compare l'empreinte SHA-256 de ce flux, fichier par fichier, entre la base et le candidat (et à
   une référence versionnée).

   Code de sortie : 0 si l'analyse réussit, 1 en cas d'erreur d'analyse (le message va sur stderr,
   pas sur stdout, pour ne pas polluer l'empreinte). Le format est volontairement identique à
   tests/run-parser-test-suite.c de libyaml, pour rester comparable à la yaml-test-suite. */

#include <yaml.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void print_escaped(const yaml_char_t *str, size_t length)
{
    size_t i;
    for (i = 0; i < length; i++) {
        unsigned char c = str[i];
        if (c == '\\') printf("\\\\");
        else if (c == '\0') printf("\\0");
        else if (c == '\b') printf("\\b");
        else if (c == '\n') printf("\\n");
        else if (c == '\r') printf("\\r");
        else if (c == '\t') printf("\\t");
        else printf("%c", c);
    }
}

int main(int argc, char *argv[])
{
    FILE *input = stdin;
    yaml_parser_t parser;
    yaml_event_t event;

    if (argc > 1) {
        input = fopen(argv[1], "rb");
        if (!input) {
            fprintf(stderr, "oracle : impossible d'ouvrir %s\n", argv[1]);
            return 2;
        }
    }
    if (!yaml_parser_initialize(&parser)) {
        fprintf(stderr, "oracle : initialisation du parseur impossible\n");
        return 2;
    }
    yaml_parser_set_input_file(&parser, input);

    for (;;) {
        yaml_event_type_t type;
        if (!yaml_parser_parse(&parser, &event)) {
            fprintf(stderr, "Parse error: %s\n", parser.problem ? parser.problem : "(inconnu)");
            yaml_parser_delete(&parser);
            if (input != stdin) fclose(input);
            fflush(stdout);
            return 1;
        }
        type = event.type;
        if (type == YAML_STREAM_START_EVENT) printf("+STR\n");
        else if (type == YAML_STREAM_END_EVENT) printf("-STR\n");
        else if (type == YAML_DOCUMENT_START_EVENT) {
            printf("+DOC");
            if (!event.data.document_start.implicit) printf(" ---");
            printf("\n");
        }
        else if (type == YAML_DOCUMENT_END_EVENT) {
            printf("-DOC");
            if (!event.data.document_end.implicit) printf(" ...");
            printf("\n");
        }
        else if (type == YAML_MAPPING_START_EVENT) {
            printf("+MAP");
            if (event.data.mapping_start.anchor) printf(" &%s", event.data.mapping_start.anchor);
            if (event.data.mapping_start.tag) printf(" <%s>", event.data.mapping_start.tag);
            printf("\n");
        }
        else if (type == YAML_MAPPING_END_EVENT) printf("-MAP\n");
        else if (type == YAML_SEQUENCE_START_EVENT) {
            printf("+SEQ");
            if (event.data.sequence_start.anchor) printf(" &%s", event.data.sequence_start.anchor);
            if (event.data.sequence_start.tag) printf(" <%s>", event.data.sequence_start.tag);
            printf("\n");
        }
        else if (type == YAML_SEQUENCE_END_EVENT) printf("-SEQ\n");
        else if (type == YAML_SCALAR_EVENT) {
            printf("=VAL");
            if (event.data.scalar.anchor) printf(" &%s", event.data.scalar.anchor);
            if (event.data.scalar.tag) printf(" <%s>", event.data.scalar.tag);
            switch (event.data.scalar.style) {
            case YAML_PLAIN_SCALAR_STYLE: printf(" :"); break;
            case YAML_SINGLE_QUOTED_SCALAR_STYLE: printf(" '"); break;
            case YAML_DOUBLE_QUOTED_SCALAR_STYLE: printf(" \""); break;
            case YAML_LITERAL_SCALAR_STYLE: printf(" |"); break;
            case YAML_FOLDED_SCALAR_STYLE: printf(" >"); break;
            default: printf(" ?"); break;
            }
            print_escaped(event.data.scalar.value, event.data.scalar.length);
            printf("\n");
        }
        else if (type == YAML_ALIAS_EVENT) printf("=ALI *%s\n", event.data.alias.anchor);
        else printf("???\n");

        yaml_event_delete(&event);
        if (type == YAML_STREAM_END_EVENT) break;
    }

    yaml_parser_delete(&parser);
    if (input != stdin) fclose(input);
    fflush(stdout);
    return 0;
}
