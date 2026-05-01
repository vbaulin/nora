# Automatic Dataset Builder

Every monitor can also build the dataset needed to improve future skills. The board should save uncertainty, not just success.

## What It Collects

- Images where TPU confidence is low.
- Audio clips with unusual signatures.
- Before/after frames around events.
- Hard negatives that fooled a detector.
- Balanced examples across light, time, and weather.
- Metadata: timestamp, metrics, skill output, task id.

## Why It Is Powerful

The best training data is local. A generic model rarely knows this exact vine, machine, room, or lab setup. The board can curate examples from its real environment and picoClaw can use the LLM to label, cluster, or design new skills.

## Chain

```text
run normal monitor
-> detect uncertainty or anomaly
-> save evidence pack
-> cluster similar examples
-> picoClaw labels or requests more samples
-> validate new classifier on saved data
```

## Useful Skills

- `curate_observation_dataset`: stores image/audio with metadata.
- `hard_negative_miner`: saves confusing false positives.
- `active_sample_request`: asks for missing examples.
- `label_proposal`: suggests labels for picoClaw review.
- `dataset_balance_report`: shows under-sampled conditions.
- `model_eval_runner`: tests `.cvimodel` or skills on local examples.

## Example Real Change

The grape monitor repeatedly saves low-confidence frames at sunset. picoClaw clusters them, learns that glare causes false stress scores, and creates a `sunset_glare_filter`. Future monitors ignore that artifact.

