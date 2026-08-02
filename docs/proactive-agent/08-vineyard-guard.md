---
title: Vineyard Guard as a Worked Adapter
summary: Connect fields, disease models, plots, Telegram, Supabase, and confirmed farmer feedback without changing the universal executor.
order: 8
eyebrow: Chapter 8
---

# Vineyard Guard as a Worked Adapter

Vineyard Guard is the complete field application, not the definition of
nano-os-agent. PicoClaw and nano-os-agent remain universal modules. The private
Goidanich repository supplies the disease-model application and local field
database.

## What the adapter contributes

- field definitions and stable covariates from YAML;
- current dashboard state and PNG evidence for independent disease families;
- fresh daily cache and regeneration rules;
- farmer-facing report and alert policy;
- catalog-checked treatment and inspection capture;
- treatment and operation history;
- Supabase board, field, neighbour, event, and model synchronization;
- proactive proposals grounded in released field evidence.

## Why copy the example manifest?

The repository file
[`config/vineyard-board.example.json`](https://github.com/vbaulin/nora/blob/main/config/vineyard-board.example.json)
is a generic, version-controlled template. It should remain free of a real
farm's GPS coordinates, identities, private notes, and credentials.

For a disposable tutorial run:

```bash
cp config/vineyard-board.example.json /tmp/my-board.json
```

Edit `/tmp/my-board.json`, not the template. This avoids leaking deployment
identity, creating accidental Git changes, or cloning one board's UUID inputs
onto another board. For a persistent operator manifest, store it outside the
checkout, for example:

```text
$HOME/.config/nano-os-agent/boards/my-board.json
```

## Provision a field identity

```bash
python3 scripts/provision_vineyard_sd.py \
  --manifest /tmp/my-board.json \
  --rootfs /Volumes/rootfs \
  --fetch-sigpac \
  --require-sigpac
```

The provisioner validates that the target is a Linux root filesystem, creates
stable board and field identities, requires critical variety/age parameters,
records language and timezone, and can retain official SIGPAC lookup
provenance. It refuses to overwrite an existing configuration unless the
operator explicitly uses the force path, which first creates a backup.

## Observe before proposing

A scheduled proactive cycle is deterministic:

```json
{"mode":"tick","notify":true,"research":false}
```

The adapter reads fresh disease artifacts, confirmed operations, farmer
feedback, and released nano-os-agent results. It creates no more than one new
proposal per field. A proposal can ask for scouting, a missing protection
record, a stable field parameter, or permission to investigate a sensor.

It cannot apply a treatment.

## Confirm informal farmer feedback

Suppose a farmer replies:

```text
PF-12: no symptoms; sulfur was applied yesterday.
```

The system first resolves `PF-12` without writing. Disease inspection and
treatment content is then sent to `farmer-feedback-capture` with
`confirmed=false`. The farmer receives a structured draft containing the
field, disease, date, product/catalog match, dose, area, water volume, and
method. Missing values become explicit questions. Only a corrected and
confirmed second call writes locally and synchronizes the event.

General operations such as pruning, mowing, soil work, irrigation,
fertilization, cover-crop work, harvest, planting, or sensor installation use
the proactive adapter's separate draft/confirm operation route.

## Independent disease evidence

Downy mildew, powdery mildew, and grapevine black rot are separate model
families. A low result in one family cannot suppress another family's warning
or replace its plot. The scheduled board briefing may combine concise summaries
to avoid flooding, but each disease retains its model identity, units,
forecast semantics, and evidence attachment.

## Continue with the operator guide

The full command-level workflow, state locations, safety checklist, and
Telegram packaging tests remain in the
[single-page proactive companion tutorial](../tutorial-proactive-field-companion.md).
Application details are documented in
[VINEYARD_GUARD.md](https://github.com/vbaulin/nora/blob/main/VINEYARD_GUARD.md)
and the
[disease-model contract](../applications/vineyard-disease-risk-models.md).
