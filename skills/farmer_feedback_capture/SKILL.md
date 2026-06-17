---
name: farmer-feedback-capture
exec_type: shell
command: ./run.sh
input_format: env
output_format: json
timeout: 60
parameters:
  - name: raw_text
    type: string
  - name: confirmed
    type: boolean
    default: false
  - name: repo_path
    type: string
    default: /root/.picoclaw/workspace/goidanich
  - name: disease
    type: string
    default: downy_mildew
  - name: field
    type: string
  - name: feedback_type
    type: string
  - name: grade
    type: integer
  - name: severity
    type: string
  - name: notes
    type: string
  - name: observed_at
    type: string
  - name: product
    type: string
  - name: product_number
    type: string
  - name: lot
    type: string
  - name: dose
    type: string
  - name: water_volume
    type: string
  - name: area
    type: string
  - name: method
    type: string
  - name: target
    type: string
  - name: treatment_type
    type: string
  - name: products_json
    type: string
  - name: skip_supabase
    type: boolean
    default: false
  - name: skip_dashboard_update
    type: boolean
    default: false
returns:
  - status
  - result
---
# farmer-feedback-capture

Farmer-facing feedback capture for Telegram and local chat. Use this when the
farmer replies to an alert with inspection/treatment outcome, especially when
the message is sloppy natural language.

## Two-step confirmation contract

Never write a treatment/inspection event from an unconfirmed free-text farmer
message.

1. First call this skill with `raw_text=<farmer message>` and
   `confirmed=false`.
2. Read the returned `draft`, `missing`, and `confirmation_question`.
3. Ask the farmer the `confirmation_question` in the language they used.
4. Only when the farmer confirms or corrects it, call this skill again with
   `raw_text=<corrected/full message>` and `confirmed=true`.

In confirmed mode the wrapper records feedback locally via
`vineyard-disease-risk mode=record_feedback`, refreshes the disease-specific
dashboard, and pushes the event to Supabase unless `skip_supabase=true`.

## Treatment normalization

For treatments, this skill extracts a structured `products` list and converts
product quantities to per-hectare values when the treated area is present.
Example farmer text:

`I sprayed 0.8 ha with 2 kg copper and 1.5 L sulfur`

Normalized draft includes:

- `area_ha: 0.8`
- product `copper`: `2.5 kg/ha`
- product `sulfur`: `1.875 L/ha`

If product names, quantities, treated area, disease/target, or field are
missing, the skill returns `status=needs_confirmation` and does not write.
