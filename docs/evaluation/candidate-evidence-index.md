# Candidate evidence index

> **Current checkpoint: 2026-08-13.** Raw reports and wheels remain outside
> Git under the repository asset policy. This page records their identities,
> durable locators, results, and claim boundaries.

## Candidate identity

| Item | Identity |
| --- | --- |
| Pico product source | `fdc545c59657e12800eb5812be94d6f3bce27415` |
| Pico wheel | `pico_harness-0.1.7-py3-none-any.whl` |
| Pico wheel SHA-256 | `87ebc4f84731656d8fb3d00dabb426e461b4e2d5f87125a90e18c42721e60684` |
| Myna product source | `924436f565d8235f02a781d776e87ea4cc176475` |
| Myna wheel | `myna_memory-0.1.1rc3-py3-none-any.whl` |
| Myna wheel SHA-256 | `67985519c1dbb7b288ff9aee7f659c335d772d3594900dcfd81fbf4b1bb77339` |

Later commits through Pico `fdc545c` changed only checkout-only benchmarks;
later Myna commits through `23e21f99` changed evaluation contracts and
evidence. The installed product bytes above therefore stayed unchanged while
the experiment and evidence code moved forward.

The exact wheels and retained evidence are attached to the maintainer-only
Myna [`v0.1.1rc3` prerelease](https://github.com/Hackerismydream/myna/releases/tag/v0.1.1rc3).
Every release asset is bound by `SHA256SUMS.txt`. The private repository makes
this a maintainer artifact locator rather than a public package source.

The 2026-08-13 Pico evidence archives use a separate
`SHA256SUMS-PICO-20260813.txt` on the same prerelease:

| Archive | SHA-256 |
| --- | --- |
| `pico-call-efficiency-1df7029-formal.tar.gz` | `46b37c91b9cad21ffaef73f681fa4eb24e3157ccbf2b22711a1c968de45ad37e` |
| `pico-tracing-1df7029-formal.tar.gz` | `95a84c69e34ccda1471cf12d29b4458b42df6ef1ba5e7023d5eb32e43ebfebb9` |
| `pico-myna-agent-fdc545c-formal.tar.gz` | `bc9012c800b780e6ebca1b672b899f34305e2f63e1ba627abba568b604aab7a4` |
| `pico-scorecard-fdc545c-formal.tar.gz` | `40236ef749a94ac0a16f7bc5fb4342c45b05254711877dea141e287802aee209` |
| `pico-evolver-small-real-claude.tar.gz` | `250f4f6f382b83c837e4a565d146f80f61ac0932adf7e6d7724e1ce5b26a027e` |

## Result ledger

| Track | Scope | Result | Claim boundary |
| --- | --- | --- | --- |
| CallEfficiency | 36 pairs, 72 Trials, 504 live DeepSeek calls | both arms 36/36 passed; stable-prefix cache hit 74.0478 percent; estimated cost per verified success fell from USD 0.008356 to USD 0.002311; task-clustered reduction 72.0750 percent, 95 percent interval 68.8471 to 75.0961 percent | eligible for the frozen prefix-stability workload; Provider-owned automatic caching, estimated pricing, not invoices or universal production savings |
| Myna deterministic Memory | 72 pairs, 144 deterministic Trials | both arms 72/72 passed; repository reads fell 50.0 percent, 95 percent interval 29.166667 to 70.833333 percent; zero stale or cross-repository events | eligible frozen-workload efficiency result; no capability uplift |
| Myna real-Agent Memory | 24 pairs, 48 live DeepSeek Trials | 24/24 valid; control passed 5, treatment passed 10; delta 20.8333 points, 95 percent interval 0 to 41.6667; zero stale or cross-repository events | exploratory only; capability and positive Claim Gates failed because the interval includes zero; efficiency also failed |
| Context | 24 live DeepSeek pairs | Curator passed 7/24 versus FIFO 0/24, but only 15 pairs were efficiency-valid; nine FIFO pairs lacked complete comparable Usage | capability diagnostic only; measurement coverage and every positive efficiency Claim Gate failed |
| Tool disclosure | 24 live DeepSeek pairs | Schema tokens fell 92.8932 percent across all eight tasks, but task passes regressed from 24 to 23 and latency increased | positive claim rejected by the noninferiority Gate |
| Tracing | 1,000 deterministic pairs, 2,000 Turns | 100 percent trace correlation; 1,000 traces and 6,000 spans; 25,717.2 bytes per traced Turn; P95 rose from 2.912 to 5.157 ms, an absolute 2.245 ms | valid local overhead measurement; relative P95 interval crosses zero, so no low-overhead or production-latency claim |
| Evolver small-real | one real-model round and one candidate | candidate accepted as the next run baseline; train pass rate 40 to 60 percent and sealed test 25 to 50 percent; retention 1.25; zero integrity errors | exploratory four-case sealed test; not credited at two sigma and activation remains `pending_human` |
| Myna LoCoMo diagnostic | 200 live DeepSeek questions | 139/200 correct; natural-category-weighted accuracy 77.041558 percent; zero infrastructure failures; retrieval P95 3.626 s | failed the frozen 82 percent promotion Gate, so the 1,540-question run was not authorized and no headline LoCoMo score is eligible |

## Artifact digests

| Track | Manifest or summary SHA-256 | Aggregate SHA-256 | Inventory or verifier SHA-256 |
| --- | --- | --- | --- |
| CallEfficiency | manifest `727005674f4bea54bd11be03547bd438cd2e6c02570cb574cf968f731589080c` | `b905ec833231236a53959cf78b05c89ca9b72b4066055aa5b6e3c327df3e4337` | inventory `15088f2b8fe9fb344ff540b2f1ec5134f49f21687c5bbc85515d7d64b4020d89` |
| Myna real-Agent | manifest `8f207ada6c2130d7c539c3c97084160b7df6ed88614369bce887d4acc2b7c67a` | `501dd637e85e63b9fa68f2884df328ee534a32101e2dd38614bff6c2288b6f25` | inventory `ad67b53598aa738d448e68c6ef43783f425804885aabf60a266e580411e7da8f` |
| Tracing | manifest `5f4dea445c6710bb6fa55404cc9049545b87af960a61c637f6436fc4bd8a7786` | `29b855459d6039f7630f410a623875a37a7e454f4a978aae265330fb023cec65` | inventory `faee0b1e1b78d8aeb2c17dbf93aae9ab535948edfc31b1a4708e22f28530bc4e` |
| Context and Tool | manifest `6b6024ad79e14b5a4568cf042c48b18246463c5dcee9fc6d7a91a7b32b6546a2` | summary `7a241d8aa15534d635cd12d54fe7095e03c0ce3997758a835317ce9eb2b26734` | experiment `0f2ded19fc7d5cdb75129bf13f80476a42a35e745e5db413b33621a32f52b8a3` |
| LoCoMo diagnostic | manifest `cd46feb52da18519bd09c3f49f15281399b61f60584619576436a08abd2b9ba7` | checked-in aggregate `dd7576fa0d5a039c74734f897524ab9343223f1ce542cac0f93f0cc76bf50def` | checked-in raw inputs `73603cf489ff601c8e082ea980761df9b05a2c83fde341d5c93fe074223b32d6` |

The LoCoMo bundle is checked into Myna under
`evals/results/locomo-200-23e21f99/`. Its CI test reconstructs the aggregate
from 200 redacted raw outcome records and verifies the complete inventory.
Licensed question text and Provider answers are not retained in Git.

## Resume-safe interpretation

- Lead with CallEfficiency's 72.08 percent paired estimated cost reduction,
  not the older unavailable TokenWise report.
- Lead with the deterministic 50 percent Memory read reduction. The real-Agent
  20.83-point pass delta is an exploratory follow-up, not a general uplift.
- Use Tracing's 100 percent correlation and measured 2.245 ms P95 tax together;
  do not call the overhead negligible.
- Present Context, Tool disclosure, LoCoMo, and Evolver as evidence that the
  fail-closed evaluation system rejected attractive but unsupported claims.
