# Vineyard Board And SD-Card Provisioning

## Scope

`scripts/provision_vineyard_sd.py` creates Vineyard Guard identity and field
configuration on an existing LicheeRV Nano Linux root filesystem. It is safe
for an offline-mounted SD card because it does not partition, format, or edit
the boot filesystem.

The provisioner writes:

```text
/root/.picoclaw/workspace/goidanich/agent_config.yaml
/root/.picoclaw/workspace/goidanich/board_manifest.json
/root/.picoclaw/board_inventory.json
```

`agent_config.yaml` is the runtime configuration. `board_manifest.json`
preserves the operator input. `board_inventory.json` is a compact,
non-secret provenance record for diagnostics and the web UI.

## Required Evidence

Every field requires:

| Property | Reason |
|---|---|
| unique field id | local database, reports, and Supabase agent identity |
| display name and location | farmer-facing reports |
| latitude and longitude | forecast, nearest-station, neighbours, and SIGPAC |
| variety | disease-model training context |
| planting year or vine age | disease-model training context |

The following should be recorded when known:

| Property | Use |
|---|---|
| management | organic, conventional, regenerative, or another explicit regime |
| water management and irrigation | dryland/irrigated context |
| station code | observed meteorology; it is independent of SIGPAC |
| municipality identifiers | Meteocat and administrative lookup |
| training system and row orientation | canopy and sensor interpretation |
| phenology dates | seasonal model gates and berry susceptibility |
| grapevine black-rot inoculum status | separates weather suitability for *Guignardia bidwellii* from field disease evidence |
| secondary bunch-rot evidence | records concerns such as *Aspergillus* separately from the black-rot model |
| leaf-wetness sensor | determines whether grapevine black-rot wetness is measured or proxied |
| other sensors | hardware capability inventory |

Do not invent absent values. Use `not_reported` only after an explicit review
of regional or field records found no report; this still does not assert
biological absence. Use `unknown` when presence has not been assessed. A
farmer's or expert's lack of personal observation is provenance, not a regional
absence assessment, and therefore remains `unknown`.
Secondary bunch rots must be recorded under their own metadata and must never
set `black_rot_inoculum_present`.

## Manifest

Start from:

```bash
cp config/vineyard-board.example.json /tmp/my-board.json
```

The file conforms to
[`config/vineyard-board.schema.json`](../config/vineyard-board.schema.json).
Use a different `board.id` for every physical board and a different `field.id`
for every logical field. The provisioner generates UUIDv5 values with the same
namespaces used by Goidanich:

```text
board UUID = uuid5(DNS, "goidanich-board:<board.id>")
field UUID = uuid5(DNS, "goidanich:<field.id>")
```

This makes repeated provisioning idempotent while preventing a cloned SD card
from impersonating the source board after its manifest is changed.

## SIGPAC Resolution

The official MAPA/FEGA WMS publishes the queryable
`AU.Sigpac:recinto` layer. The lookup utility sends an OGC WMS 1.3.0
`GetFeatureInfo` request in `CRS:84`:

```bash
python3 scripts/sigpac_lookup.py \
  --latitude 41.2 \
  --longitude 1.5 \
  --expected-use-code VI \
  --strict
```

For a vineyard, `VI` is the expected SIGPAC use code. The returned record can
contain:

- province and municipality codes/names;
- aggregate, zone, polygon, parcel, and recinto;
- SIGPAC use;
- surface in hectares;
- slope;
- irrigation coefficient;
- admissibility/incidents;
- region;
- altitude;
- a direct official-viewer URL.

A point close to a border may return more than one recinto. The lookup selects
one record only when exactly one candidate matches the expected use code.
Otherwise it returns `ambiguous`, `not_found`, or `use_code_mismatch`.
`--require-sigpac` converts any unresolved field into a provisioning error.
When an expected-use filter selects one result from several spatial
candidates, the inventory retains every candidate and sets
`review_required=true`.

The WMS data are orientative and non-binding according to MAPA. Retain the
service endpoint and retrieval timestamp, and verify parcel identity against
the competent authority's official record.

Official sources:

- [MAPA SIGPAC WMS catalogue](https://www.mapa.gob.es/es/cartografia-y-sig/ide/directorio_datos_servicios/agricultura/servicios-wms-sigpac/wms_sigpac)
- [SIGPAC viewer manual](https://sigpac.mapa.gob.es/fega/visor/help/Manual%20de%20Usuario.html)
- [MAPA WMS service conditions](https://www.mapa.gob.es/es/cartografia-y-sig/ide/directorio_datos_servicios/caracteristicas_wms)

## Offline SD-Card Workflow

1. Mount the Linux rootfs partition. Do not use the boot partition as
   `--rootfs`. The script requires Linux `/etc` and `/root` directories and
   rejects a boot-only volume.
2. Preview the generated configuration:

   ```bash
   python3 scripts/provision_vineyard_sd.py \
     --manifest /tmp/my-board.json \
     --rootfs /Volumes/rootfs \
     --dry-run
   ```

3. Resolve SIGPAC and write:

   ```bash
   python3 scripts/provision_vineyard_sd.py \
     --manifest /tmp/my-board.json \
     --rootfs /Volumes/rootfs \
     --fetch-sigpac \
     --require-sigpac
   ```

4. If replacing an existing configuration, use `--force`. The previous
   `agent_config.yaml` is copied to a timestamped `.bak` file first.
5. Unmount the card cleanly before removing it.

The SIGPAC request needs host Internet access. For a fully offline workflow,
place a reviewed reference in each field's `sigpac.reference` block. The
provisioner then records it without a network request.

## Live-Board Workflow

On the board:

```bash
python3 /root/nano-os-agent/scripts/provision_vineyard_sd.py \
  --manifest /root/board.json \
  --rootfs / \
  --fetch-sigpac \
  --require-sigpac \
  --force
```

Restart Vineyard Guard only after reviewing the generated configuration.
Then verify that all fields parse:

```bash
cd /root/.picoclaw/workspace/goidanich
python3 -c 'from field_config import load_board_and_fields; c,b,f=load_board_and_fields(); print(b["id"], [x["id"] for x in f])'
```

Run one Supabase registration/sync after provisioning so the new board and
field UUIDs are registered. Do not place the Supabase service-role key on the
board.

## Secrets

The manifest and inventory contain no Telegram token or Supabase credential.
The provisioner rejects common secret-key fields if they are embedded in the
manifest.
Copy secrets separately:

```text
/root/.picoclaw/workspace/goidanich/.env
/root/.picoclaw/telegram.env
```

Use mode `0600`. A board may use the common project URL and publishable/anon
key, while its identity remains unique through `agent_config.yaml`. Never
commit either secret file.

## Grapevine Black-Rot Sensor Consequence

The *Guignardia bidwellii* black-rot model requires leaf wetness. If the inventory says that no
leaf-wetness sensor is installed, Vineyard Guard labels rain or `RH >=95%` as a
proxy and treats `RH 90-<95%` only as an uncertainty watch. SIGPAC parcel
attributes do not resolve this measurement limitation.

This sensor rule does not apply automatically to secondary bunch rots caused
by *Aspergillus*, *Penicillium*, or other opportunistic fungi. Those conditions
need a separately selected and validated model.
