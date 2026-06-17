---
name: farmer-notify
exec_type: python
command: ./run.py
input_format: stdin
output_format: json
timeout: 20
parameters:
  - name: title
    type: string
  - name: message
    type: string
  - name: plot_path
    type: string
  - name: image_path
    type: string
  - name: outbox_dir
    type: string
    default: /tmp/picoclaw_outbox
  - name: channel
    type: string
    default: picoclaw_telegram
returns:
  - status
  - outbox_json
  - outbox_md
  - image_path
  - photo_path
  - attachment_path
  - attachments
  - telegram
---
# farmer-notify

Writes an unsolicited farmer notification package to an outbox for picoClaw's
existing Telegram transport. This skill does not talk to Telegram directly. It
creates the exact farmer-facing payload and artifact paths that picoClaw should
send, preserving a local audit trail even if WiFi is down. For Telegram, this
is a photo notification, not a text link: call `sendPhoto` with
`telegram.photo` or `photo_path`, and use `telegram.caption` / `message` as the
caption. Do not send the image path as plain text instead of attaching the file.
The skill copies the image into the outbox directory and returns that copied
file as `photo_path`, so the Telegram transport can upload a file located next
to the JSON package it is consuming.

Set `channel` to `picoclaw_telegram` for normal farmer alerts.
