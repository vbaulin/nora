---
name: risk-alert-policy
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 20
parameters:
  - name: status
    type: object
  - name: memory_path
    type: string
    default: /tmp/vineyard_alert_memory.json
  - name: high_threshold
    type: number
    default: 70
  - name: watch_threshold
    type: number
    default: 50
  - name: delta_threshold
    type: number
    default: 15
  - name: cooldown_hours
    type: number
    default: 24
  - name: update_memory
    type: boolean
    default: true
returns:
  - status
  - notify
  - severity
  - reason
  - alerts
---
# risk-alert-policy

Deterministic farmer-notification policy for vineyard disease risk.

Use after `vineyard-disease-risk mode=current_status` or `mode=cron_daily`.
It decides whether risk is high enough, changed enough, and outside cooldown
before picoClaw sends an unsolicited farmer report.
