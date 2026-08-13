# Candidate evidence index

> **Current checkpoint: 2026-08-13.** This page records durable artifact
> identity and claim boundaries. Raw reports and wheels remain outside Git in
> accordance with repository asset policy.

The index distinguishes code that is installed, evidence that can currently be
replayed, historical summaries whose source artifact is unavailable, and work
that has never been run.

## Current Pico and Myna candidate

| Item | Identity |
| --- | --- |
| Pico source | `7c9655a82dfd1d84872fb4f0c2aecd5835ff6ef9` |
| Pico wheel | `pico_harness-0.1.7-py3-none-any.whl` |
| Pico wheel SHA-256 | `87ebc4f84731656d8fb3d00dabb426e461b4e2d5f87125a90e18c42721e60684` |
| Myna source | `924436f565d8235f02a781d776e87ea4cc176475` |
| Myna wheel | `myna_memory-0.1.1rc3-py3-none-any.whl` |
| Myna wheel SHA-256 | `67985519c1dbb7b288ff9aee7f659c335d772d3594900dcfd81fbf4b1bb77339` |

The exact wheels, current calibration and formal records, and the preserved PR
#97 candidate are attached to the maintainer-only Myna
[`v0.1.1rc3` prerelease](https://github.com/Hackerismydream/myna/releases/tag/v0.1.1rc3).
`SHA256SUMS.txt` was downloaded with every release asset and verified locally;
all 15 listed assets matched. The Myna repository is private, so this link is
an artifact locator for maintainers rather than a public download path.

## Myna deterministic task-effect evidence

The current formal run used the installed wheels above, a deterministic local
Provider, 24 tasks, three repetitions, and two arms. Network Provider calls
were forbidden and paid Provider calls were zero.

| Gate | Result |
| --- | --- |
| Trial and Pair completion | 144/144 Trials; 72/72 valid Pairs |
| Task success | control 72/72; Myna 72/72 |
| Treatment axis and lifecycle | valid and complete |
| Repository-read reduction | 50.0 percent |
| Task-clustered 95 percent interval | 29.166667 to 70.833333 percent |
| Safety | zero stale-memory regressions; zero cross-repository events |
| Capability uplift | 0 percentage points; claim ineligible |
| Frozen-workload efficiency | claim eligible |

The strongest honest statement is that the Myna-enabled Pico Memory path
reduced repository reads on this frozen deterministic Pack while preserving
task success. It is not evidence that Myna improves general coding-Agent
capability, production latency, or arbitrary repositories.

The formal artifact digests are:

| Artifact | SHA-256 |
| --- | --- |
| `current-formal-manifest.json` | `c5852a929c09ba3918efd3b4822acb4b25e6c01dd82d156b01950cb62584f159` |
| `current-formal-raw-outcomes.jsonl` | `bdf1db532b7d14dedad932bed49a6b59c651f4c4650b3f7ff337d87a593bbeae` |
| `current-formal-aggregate.json` | `ea7157561cea8ad5df48323340325b0190fd6597a8000261a04c7008955081bf` |
| `current-formal-verifier-report.json` | `37c351d1f69a84016d8189a1668fce5baa961e8ffd911c9e2c4cbc574629a561` |
| `current-formal-claim-eligibility.json` | `f0375d2135e81729b0bc4a2c63cb697071a43a5f02d84c8de222ca9ec67c4926` |
| `current-formal-inventory.json` | `5c39385ad113f0ee48da8edecfd9937377b6bf519897a3995c7d595f56602094` |

The credential-free verifier reinstalled the same wheel identities and rebuilt
the accepted aggregate. The v1 raw Trial schema retains status, read counts,
operation names, and safety booleans rather than every successful artifact,
Tool, and Recall receipt. It can rebuild the recorded summary but cannot
independently reconstruct every successful workspace observation. Claims stay
within that receipt boundary.

The lightweight real-Agent subtrack has implementation and failure-class
coverage, but no authorized paid run exists. It supports no result claim.

## CallEfficiency and historical TokenWise evidence

Current CallEfficiency Runtime assembly, Provider wrapping, retry/fallback
accounting, ledger persistence, and shutdown ordering have deterministic and
contract coverage. No paid post-integration canary has run, so there is no
current live cache-hit or cost-reduction claim for CallEfficiency.

The historical DeepSeek TokenWise summary records 36 valid Comparison Blocks,
75.19 percent conservative cache hit rate for stable prefixes, and 73.44
percent lower estimated cost per verified success. Its declared source report
digest is
`fcde99b98c8bc46d0852015d7a92c01a0de6a4e4216f773045375f2f06e75aec`.
That exact `report.json` is not present in the current evidence store or a
durable release asset. The offline replay therefore cannot presently run.

The historical summary remains useful only with that explicit availability
gap. Recovering the exact source artifact and verifying its digest would
restore replayability; a new paid campaign would be a separate result and
requires separate authorization.
