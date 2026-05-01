# Self-Improving Field and Lab Observer

This is the unifying application: the board observes a place long enough to become specialized to it.

## What It Does

- Runs long monitors without LLM supervision.
- Detects repeated patterns, uncertainty, and anomalies.
- Saves local evidence packs.
- Lets picoClaw ask the LLM for hypotheses only when needed.
- Creates draft skills from those hypotheses.
- Validates and promotes skills that work.
- Updates future monitors with sharper measurements.

## Why It Is Powerful

The board starts generic but becomes local. It learns this vine, this field, this machine, this lab bench. The intelligence is not only in the LLM; it is in the growing set of validated skills and journals tied to the physical environment.

## Chain

```text
observe for days
-> detect a new pattern
-> picoClaw asks for hypothesis
-> draft skill
-> validate on local evidence
-> promote
-> update monitor
-> observe with sharper measurement
```

## Useful Skills

- `monitor_summary`: compact trend evidence.
- `validate_skill`: checks draft skill structure and safety.
- `promote_skill`: installs trusted learned skills.
- `dataset_balance_report`: tells picoClaw what data is missing.
- `model_eval_runner`: tests a model or skill before promotion.
- `experiment_outcome_judge`: decides whether a new measurement improved the task.

## Example Real Change

A field monitor notices that a pest-like visual pattern appears only after rain. picoClaw creates a draft pest-pattern detector from saved frames, validates it against hard negatives, promotes it, and adds it to the vineyard monitor. The board now tracks a site-specific biological event it did not know at deployment.

