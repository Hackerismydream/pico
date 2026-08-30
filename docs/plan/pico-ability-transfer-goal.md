# Pico Ability Transfer Goal

Status: authorized for implementation and Provider-backed evaluation. This
experiment is separate from `skill_transfer_v1` and `skill_transfer_v2`; it
uses new task identities, fixtures, manifests, and claims.

## Objective

Measure whether Pico can reuse repository-private operating knowledge captured
by Myna on held-out maintenance tasks. The benchmark must make the knowledge
transfer problem real: every test task shares one verified Pico Ability with
training tasks, while exact functions, prompts, fixtures, and verifier cases
remain disjoint.

The product method remains:

```text
ordinary Pico Turns
  -> Myna captures verified task experience
  -> Myna derives a repository-scoped Skill candidate
  -> Pico recalls the candidate for a later task
  -> Pico's fail-closed Gate decides whether it may enter context
  -> an independent verifier measures the held-out result
```

## Repository-private Abilities

The first release contains six Abilities grounded in current Pico contracts:

1. verification receipt integrity;
2. derived-Skill admission;
3. checkpoint activation policy;
4. Skill-source failure isolation;
5. delivery outcome accounting; and
6. Evolver activation governance.

Each Ability has three learning instances, four held-out implementation
instances, and four confusing negatives. Learning and test identities are
disjoint. A held-out fixture exposes the function interface and one public
smoke example; the independent verifier owns the remaining policy cases.

These tasks intentionally target repository conventions rather than generic
Python algorithms. A model may know how to parse a command or combine lists,
but it cannot infer Pico's exact fail-closed, delivery, checkpoint, or
activation policy from pretraining alone.

## Frozen stages

### Stage A: learned-content effect

Run 24 held-out tasks with two repetitions and two arms:

- `no_skill`: the normal Agent without learned knowledge;
- `automatic_skill_oracle`: the exact Myna-derived Ability card for the known
  Ability.

The oracle Ability label is diagnostic and unavailable to the deployable
method. It removes retrieval error so Stage A isolates whether Myna's automatic
Skill compilation preserves useful repository policy before Recall and Gate
quality are introduced.

Continue when:

- all 96 Trials are complete and measurable;
- `automatic_skill_oracle - no_skill` has a task-clustered 95 percent interval with a
  lower bound above zero;
- every Ability has at least one NoSkill failure and one Skill success; and
- no arm modifies the smoke fixture or creates unrelated files.

Stage A hard cap: CNY 5.

### Stage B: automatic Pico + Myna path

Run the same held-out tasks with three repetitions:

- `no_memory`;
- `myna_shadow`, which recalls and Gates but injects nothing; and
- `myna_gate`, which injects only an exact candidate selected by Pico.

The primary contrasts are `myna_gate - no_memory` and selected-task
`myna_gate - myna_shadow`. Gate failures and invalid responses abstain.

Run all 24 confusing negatives through Recall and Gate. A positive automatic
claim requires:

- complete, identity-disjoint Trials and provenance;
- task-clustered 95 percent lower bound above zero for end-to-end task effect;
- zero incorrect injection on obvious negatives and at most one on confusing
  negatives;
- no Ability below a -12.5 percentage-point non-inferiority floor; and
- complete offline reconstruction of results, resources, Gate receipts,
  budgets, and inventory.

Stage B hard cap: CNY 10.

## Evidence boundary

Stage A proves only that the automatically compiled content can transfer when
Ability routing is known. Only Stage B can support an automatic Pico + Myna
self-evolution claim. Skill injection is exposure evidence; the independent
verifier determines task success.

The final campus-recruiting narrative is produced as a separate artifact. It
contains the user problem, architecture, method, and eligible result. It does
not narrate discarded experiments, intermediate failures, or research diary
details.
