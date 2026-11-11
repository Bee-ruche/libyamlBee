# Bee evaluation tooling for libyaml

This `bee/` folder holds everything that **judges** the contributions to this fork: corpus, determinism
oracle, measurement bench, and (to come) fuzzing and CI. The code of libyaml itself is not modified
here. libyamlBee is an **independent fork** of [libyaml](https://github.com/yaml/libyaml), run by the
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

## Measurement bench

```bash
make -C bee banc
bee/construction/banc/banc --corpus bee/corpus/donnees --passes 3
python3 bee/bench/ab.py --base upstream/master --candidate HEAD --repetitions 10 --instructions
```

Four metrics: `debit_analyse` (event parser alone), `debit_chargement`
(`yaml_parser_load`, document tree), `debit_emission` (`yaml_emitter_dump`), `memoire_max_ko`
(heap peak of a child process that loads and emits the whole corpus). `ab.py` compares two revisions in
strict alternation and decides what is beyond noise with a **sign test** on the interleaved pairs (at least
9 pairs won out of 10); with `--instructions`, it also counts instructions (Cachegrind).
YAML parsing is CPU-bound: a drop in instructions shows on the stopwatch.

## Corpus

`python3 bee/corpus/generer.py` writes a deterministic corpus in `bee/corpus/donnees/` and checks
`bee/corpus/SHA256SUMS`. It mixes varied synthetic documents (block maps and sequences, scalar
styles, varied depths) and fixed samples that cover the flow style, anchors and aliases,
multi-document streams, comments, literal and folded scalars, tags, and a few realistic
configurations (Kubernetes, CI). No data is downloaded.

## Scope

The paths that judge the contributions (`bee/**`, `tests/**`, `.github/**`) cannot be
modified by an optimization task (commandment 3). The libyaml sources that are judged are `src/*.c`
and `include/yaml.h`.

## Known limits

- **Emitter and round trip.** The oracle checks parsing. A round-trip check (events
  → YAML → identical events) for emitter optimizations remains to be added.
- **Fuzzing.** The parser's differential fuzzing harness (arbitrary input, ASan/UBSan)
  is not written yet: it is a good Bee task to harden the fork.
- **Sandbox.** The Dockerfile is not pinned by digest yet.
- **Not checked beyond this machine.** The first figures come from a single environment; the
  registry's distributed bench (`bee record-measurement`) will extend them to other configurations.
