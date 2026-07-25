# Adversarial review and handoff

Status: Wave 5 TUI gate passed; release evidence to follow in Wave 6

## Independent review

A fresh read-only reviewer attacked the live two-door TUI candidate and
reproduced two material defects before promotion.

### Resolved high — symlink replacement safety

The initial TUI canonicalized the output path before invoking the producer.
That removed a symlink component and could bypass the producer's deliberate
symlinked-target refusal under `--force`. The reviewer demonstrated deletion
of a sentinel in the symlink target.

Repair:

- source, context, and output paths become lexical absolute paths without
  resolving symlink components;
- the producer receives the security-relevant path exactly;
- direct CLI and TUI both refuse the same symlinked output with exit `2`;
- the sentinel survives;
- no delivery is claimed.

### Resolved medium — Weave-only flag misrouting

With no `--door`, a Weave-only flag could formerly be ignored while legacy
routing selected Unravel. The router now rejects every Weave-only flag unless
`--door weave` is explicit. The exact former command exits `2` and writes no
output.

### Additional defense verified

- final claims require an `ok` `coursecraft.run/1` receipt, `manual_only`
  attachment state, in-bundle path, exact artifact role, size, and SHA-256;
- Weave logs use a controlled lane, randomized names, and exclusive
  no-follow creation before child launch;
- TUI imports no authoring, DOCX, builder, adapter, or D2L XML semantics;
- PTY Unravel and Weave journeys, Back/quit/Ctrl-C, plain and degraded
  terminals, state isolation, explicit fallbacks, named final approval, and
  fresh launcher decline are covered.

The reviewer reran the exact high and medium reproductions after repair and
returned PASS with no unresolved critical or high-severity finding.

## Wave 5 disposition

Accept the TUI candidate for commit and push. Unravel remains compatible;
Weave is additive and cannot be entered headlessly without an explicit door,
preflight-complete decisions, `--yes`, and `--approve-weave`.

Release handoff remains gated on the independent Weave capability manifest,
deterministic v1.1.0 asset and SBOM, checksum verification, and public release
evidence.
