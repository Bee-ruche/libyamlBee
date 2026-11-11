# Bee evaluation tooling for libyaml

This `bee/` folder holds everything that **judges** the contributions to this fork: corpus, determinism
oracle, emitter round trip, measurement bench, differential fuzzing and the CI's scripts (`bee/ci/`, run by
`.github/workflows/bee-ci.yml`). The code of libyaml itself is not modified here. libyamlBee is an **independent fork** of [libyaml](https://github.com/yaml/libyaml), run by the
[Bee](https://github.com/Bee-ruche/registre) project; it is not affiliated with the original project.

## What a contribution must respect

An optimization makes parsing or emitting faster **without changing the result**: for each input,
libyaml must produce **exactly the same event stream** and the same status (success or parse
error). This is the invariant the oracle checks.

## Prerequisites

`gcc` (or `clang`), `make`, `python3` (3.8+). For profiling: `valgrind`. For libFuzzer:
`clang` with `libclang-rt`. libyaml builds without `config.h`; the tooling provides the version
macros and `YAML_DECLARE_STATIC` (see `bee/Makefile`).

## Sandbox: running the code without network or secrets

The contributions' code runs isolated (commandment 6). Without Docker, for example in a
disposable cloud session, on Linux:

```bash
bee/sandbox/sans-docker.sh make -C bee oracle    # one command
bee/sandbox/sans-docker.sh bash                  # a session
```

The script runs the command at the repository's root, without network, without seeing the machine's
processes (PID namespace, with its own `/proc`), without the user's environment variables
(tokens, proxy), with an empty home folder (`~/.config/gh` is hidden) and an empty `/tmp` of its own.
It requires user and PID namespaces (`unshare -r --pid`); if they are refused, it says so. The fork has
no Docker image yet (to be built by the hive, on the model of minizBee's `bee/sandbox/Dockerfile`).

## Determinism (correctness)

```bash
bee/tests/lancer.sh                 # builds the oracle, generates the corpus, compares with the fingerprints
bee/tests/lancer.sh --sans-empreintes   # for a task allowed to change the output
```

For each file of the corpus, `bee/tests/oracle.c` writes the canonical event stream (yaml-test-suite
format: `+STR`, `+MAP &anchor <tag>`, `=VAL`, `=ALI`, …). Its SHA-256 fingerprint and its status
are compared with `bee/tests/empreintes-reference.txt`, frozen at the base revision. The slightest
difference fails the tests.

The same script runs the emitter's round trip (`bee/tests/aller_retour.c`, libyaml-0003): each file is
parsed, its events are emitted again by libyaml's emitter, the output is parsed again and must give the
same event stream (the tolerated normalizations are listed at the top of `aller_retour.c`). The
fingerprint of the emitted text and the status are compared with `bee/tests/empreintes-aller-retour.txt`;
a failed round trip always fails, even with `--sans-empreintes`.

## Measurement bench

```bash
make -C bee banc
bee/construction/banc/banc --corpus bee/corpus/donnees --passes 3
python3 bee/bench/ab.py --base upstream/master --candidate HEAD --repetitions 10 --instructions
```

Four metrics: `parse_throughput` (event parser alone), `load_throughput`
(`yaml_parser_load`, document tree), `emit_throughput` (`yaml_emitter_dump`), `max_memory_kb`
(heap peak of a child process that loads and emits the whole corpus). `ab.py` compares two revisions in
strict alternation and decides what is beyond noise with a **sign test** on the interleaved pairs (at least
9 pairs won out of 10); with `--instructions`, it also counts instructions (Cachegrind): `instructions_parse`,
`instructions_load`, `instructions_emit`. YAML parsing is CPU-bound: a drop in instructions shows on the stopwatch.

The bench, `ab.py`'s JSON report and the CI's `verdict.json` are written in English (the registry's
`tools/migration/names.yaml`). Until the registry renames its metric ids (ruche-0149), its tasks and
`projects/libyaml.yaml` still say `debit_analyse`, `debit_chargement`, `debit_emission` and `memoire_max_ko`:
the CI reads both names, and `bee record-measurement` and `bee record-verdict` read both too.

## Corpus

`python3 bee/corpus/generer.py` writes a deterministic corpus in `bee/corpus/donnees/` and checks
`bee/corpus/SHA256SUMS`. It mixes varied synthetic documents (block maps and sequences, scalar
styles, varied depths) and fixed samples that cover the flow style, anchors and aliases,
multi-document streams, comments, literal and folded scalars, tags, and a few realistic
configurations (Kubernetes, CI). No data is downloaded.

## Differential fuzzing

```bash
bee/sandbox/sans-docker.sh bee/fuzz/lancer.sh 60     # 60 seconds, this repository's sources
```

`bee/fuzz/fuzz_parse.c` (libyaml-0002) parses arbitrary input under ASan and UBSan, whole or in chunks of k
bytes. With `--reference`, a second copy of libyaml (the base) is linked into the same binary, and the event
stream and error status of both must be identical; each faulty input is replayed on the base alone, to tell a
new discrepancy from a pre-existing one. libFuzzer with clang, otherwise a gcc fallback with a random driver.
The CI runs it for 600 seconds on x86-64, base against PR. `bee/fuzz/lancer.sh` without arguments prints its
options.

## Scope

The paths that judge the contributions (`bee/**`, `tests/**`, `.github/**`) cannot be
modified by an optimization task (commandment 3). The libyaml sources that are judged are `src/*.c`
and `include/yaml.h`.

## Known limits

- **Round trip.** Only the event API is covered (`yaml_emitter_emit`), with the emitter's default
  settings: the document API (`yaml_parser_load` then `yaml_emitter_dump`, `dumper.c`), which
  `emit_throughput` measures, and the non-default settings (canonical, unicode, width, indentation,
  line breaks) are not (manifestes/libyaml-0003.yaml).
- **Fuzzing.** Only the parser is fuzzed (`fuzz_parse.c`); the loader and the emitter are not.
- **Sandbox.** No Docker image yet: only `bee/sandbox/sans-docker.sh`, on Linux.
- **Not checked beyond this machine.** The first figures come from a single environment; the
  registry's distributed bench (`bee record-measurement`) will extend them to other configurations.
