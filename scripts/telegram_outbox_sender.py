#!/usr/bin/env python3
"""Deterministic Telegram sender for picoClaw outbox packages.

This bypasses any LLM rewriting. It reads farmer_notify JSON files and sends
exactly the declared Telegram payload.
"""

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def split_recipient_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        recipients = []
        for item in value:
            recipients.extend(split_recipient_values(item))
        return recipients
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(int(value))]
    return [part for part in re.split(r"[\s,;]+", str(value).strip()) if part]


def telegram_channel_configs(config):
    configs = []
    for key in ("channel_list", "channels"):
        channels = config.get(key)
        if isinstance(channels, dict):
            telegram = channels.get("telegram")
            if isinstance(telegram, dict):
                configs.append(telegram)
        elif isinstance(channels, list):
            for item in channels:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("type") or "").lower()
                if "telegram" in name:
                    configs.append(item)
    return configs


def configured_direct_recipients(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    recipients = []
    for channel in telegram_channel_configs(config):
        settings = channel.get("settings") if isinstance(channel.get("settings"), dict) else {}
        for value in (channel.get("allow_from"), settings.get("allow_from")):
            for recipient in split_recipient_values(value):
                # In a direct Telegram chat the numeric user id is also the chat id.
                # Usernames are valid allow-list entries but are not reliable proactive
                # destinations, so only numeric ids are inferred from allow_from.
                if re.fullmatch(r"\d+", recipient):
                    recipients.append(recipient)
    return recipients


def resolve_recipients(chat_id=None, chat_ids=None, config_path=None, include_allow_from=True):
    recipients = []
    recipients.extend(split_recipient_values(chat_id))
    recipients.extend(split_recipient_values(chat_ids))
    if include_allow_from and config_path:
        recipients.extend(configured_direct_recipients(config_path))
    unique = []
    seen = set()
    for recipient in recipients:
        normalized = str(recipient).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def encode_multipart(fields, files):
    boundary = "----picoclaw-" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    for name, path in files.items():
        filename = os.path.basename(path)
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            data = handle.read()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def call_telegram(token, method, fields, files=None, timeout=30):
    url = f"https://api.telegram.org/bot{token}/{method}"
    files = files or {}
    if files:
        body, content_type = encode_multipart(fields, files)
        request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    else:
        body = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def call_telegram_json(token, method, payload, timeout=30):
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def load_payload(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_payload(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp, path)


def send_payload(path, token, chat_id, dry_run=False, timeout=90, save_status=True):
    payload = load_payload(path)
    telegram = payload.get("telegram") or {}
    method = telegram.get("method") or ("sendPhoto" if payload.get("photo_path") else "sendMessage")
    caption = telegram.get("caption") or payload.get("message") or ""
    photo = telegram.get("photo") or payload.get("photo_path") or payload.get("attachment_path")
    media = telegram.get("media") or payload.get("media") or payload.get("attachments") or []
    if "text_after_photo" in telegram:
        text_after_photo = telegram.get("text_after_photo") or ""
    elif "text_after_photo" in payload:
        text_after_photo = payload.get("text_after_photo") or ""
    else:
        text_after_photo = ""
    results = []

    if method == "sendMediaGroup" and media:
        group = []
        files = {}
        for index, item in enumerate(media[:10]):
            item_path = item.get("path") if isinstance(item, dict) else str(item)
            if not item_path:
                continue
            if not os.path.exists(item_path):
                raise RuntimeError(f"{path}: media item does not exist: {item_path}")
            attach_name = f"photo{index}"
            media_item = {
                "type": "photo",
                "media": f"attach://{attach_name}",
            }
            item_caption = item.get("caption") if isinstance(item, dict) else ""
            if index == 0 and (caption or item_caption):
                media_item["caption"] = caption or item_caption
                if telegram.get("parse_mode"):
                    media_item["parse_mode"] = telegram["parse_mode"]
            group.append(media_item)
            files[attach_name] = item_path
        if not group:
            raise RuntimeError(f"{path}: sendMediaGroup requested but no usable media paths are present")
        fields = {"chat_id": chat_id, "media": json.dumps(group)}
        if dry_run:
            result = {"ok": True, "dry_run": True, "method": "sendMediaGroup", "media_count": len(group)}
        else:
            result = call_telegram(token, "sendMediaGroup", fields, files, timeout=timeout)
        results.append(result)
        if text_after_photo:
            fields = {"chat_id": chat_id, "text": text_after_photo}
            if telegram.get("parse_mode"):
                fields["parse_mode"] = telegram["parse_mode"]
            if dry_run:
                followup = {"ok": True, "dry_run": True, "method": "sendMessage", "text_after_photo": True}
            else:
                followup = call_telegram(token, "sendMessage", fields, timeout=timeout)
            results.append(followup)
    elif method == "sendPhoto":
        if not photo:
            raise RuntimeError(f"{path}: sendPhoto requested but no photo path is present")
        if not os.path.exists(photo):
            raise RuntimeError(f"{path}: photo does not exist: {photo}")
        fields = {"chat_id": chat_id, "caption": caption}
        if telegram.get("parse_mode"):
            fields["parse_mode"] = telegram["parse_mode"]
        if dry_run:
            result = {"ok": True, "dry_run": True, "method": "sendPhoto", "photo": photo}
        else:
            result = call_telegram(token, "sendPhoto", fields, {"photo": photo}, timeout=timeout)
        results.append(result)
        if text_after_photo and text_after_photo != caption:
            fields = {"chat_id": chat_id, "text": text_after_photo}
            if telegram.get("parse_mode"):
                fields["parse_mode"] = telegram["parse_mode"]
            if dry_run:
                followup = {"ok": True, "dry_run": True, "method": "sendMessage", "text_after_photo": True}
            else:
                followup = call_telegram(token, "sendMessage", fields, timeout=timeout)
            results.append(followup)
    else:
        text = telegram.get("text") or payload.get("message") or caption
        fields = {"chat_id": chat_id, "text": text}
        if telegram.get("parse_mode"):
            fields["parse_mode"] = telegram["parse_mode"]
        if dry_run:
            result = {"ok": True, "dry_run": True, "method": "sendMessage"}
        else:
            result = call_telegram(token, "sendMessage", fields, timeout=timeout)
        results.append(result)

    if not dry_run and save_status:
        payload["status"] = "sent" if all(result.get("ok") for result in results) else "error"
        payload["telegram_result"] = results[0] if len(results) == 1 else results
        save_payload(path, payload)
    else:
        payload["telegram_result"] = results[0] if len(results) == 1 else results
    return payload


def send_payload_to_recipients(path, token, recipients, dry_run=False, timeout=90):
    payload = load_payload(path)
    delivered = {str(value) for value in payload.get("delivered_chat_ids") or []}
    delivery_results = list(payload.get("telegram_results_by_chat") or [])
    attempted = []
    for chat_id in recipients:
        chat_id = str(chat_id)
        if chat_id in delivered:
            continue
        result_payload = send_payload(
            path,
            token,
            chat_id,
            dry_run=dry_run,
            timeout=timeout,
            save_status=False,
        )
        attempted.append(chat_id)
        if dry_run:
            continue
        telegram_result = result_payload.get("telegram_result")
        telegram_results = telegram_result if isinstance(telegram_result, list) else [telegram_result]
        if not telegram_results or not all(
            isinstance(result, dict) and result.get("ok") is True for result in telegram_results
        ):
            raise RuntimeError(f"Telegram rejected scheduled delivery to chat {chat_id}")
        delivered.add(chat_id)
        delivery_results.append({"chat_id": chat_id, "result": telegram_result})
        payload = load_payload(path)
        payload["status"] = "pending"
        payload["delivered_chat_ids"] = sorted(delivered)
        payload["telegram_results_by_chat"] = delivery_results
        save_payload(path, payload)
    if dry_run:
        payload["dry_run_recipients"] = attempted
        return payload
    payload = load_payload(path)
    payload["status"] = "sent"
    payload["delivered_chat_ids"] = sorted(delivered)
    payload["telegram_results_by_chat"] = delivery_results
    payload.pop("last_error", None)
    save_payload(path, payload)
    return payload


def record_send_error(path, payload, error):
    payload = dict(payload or load_payload(path))
    payload["status"] = "pending"
    payload["send_attempts"] = int(payload.get("send_attempts") or 0) + 1
    payload["last_error"] = str(error)
    payload["last_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_payload(path, payload)


def payload_created_timestamp(path, payload):
    created_at = payload.get("created_at")
    if created_at:
        try:
            created = dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            return created.timestamp()
        except ValueError:
            pass
    return os.path.getmtime(path)


def skip_stale_pending(outbox, max_age_hours, dry_run=False):
    if max_age_hours <= 0:
        return []
    cutoff = time.time() - (max_age_hours * 3600)
    skipped = []
    for path, payload in pending_payloads(outbox):
        if payload_created_timestamp(path, payload) >= cutoff:
            continue
        reason = f"pending payload older than {max_age_hours:g} hours"
        if dry_run:
            skipped.append({"path": path, "reason": reason, "dry_run": True})
        else:
            mark_skipped_by_gateway(path, payload, reason)
            skipped.append({"path": path, "reason": reason})
    return skipped


def iter_pending(outbox):
    names = sorted(
        (name for name in os.listdir(outbox) if name.endswith(".json")),
        key=lambda name: os.path.getmtime(os.path.join(outbox, name)),
        reverse=True,
    )
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(outbox, name)
        try:
            payload = load_payload(path)
        except Exception:
            continue
        if payload.get("status") == "pending":
            yield path


def pending_payloads(outbox):
    rows = []
    for name in sorted(
        (name for name in os.listdir(outbox) if name.endswith(".json")),
        key=lambda name: os.path.getmtime(os.path.join(outbox, name)),
        reverse=True,
    ):
        path = os.path.join(outbox, name)
        try:
            payload = load_payload(path)
        except Exception:
            continue
        if payload.get("status") == "pending":
            rows.append((path, payload))
    return rows


def role_of(payload):
    return payload.get("dispatch_role") or (payload.get("meta") or {}).get("dispatch_role") or ""


def delivery_group_of(payload):
    return payload.get("delivery_group") or (payload.get("meta") or {}).get("delivery_group") or ""


def mark_skipped_by_gateway(path, payload, reason):
    payload["status"] = "skipped_by_gateway"
    payload["gateway_reason"] = reason
    save_payload(path, payload)


def select_gateway_batch(outbox):
    pending = pending_payloads(outbox)
    if not pending:
        return [], []
    grouped = [(path, payload) for path, payload in pending if delivery_group_of(payload)]
    if not grouped:
        return [pending[0]], []
    group = delivery_group_of(grouped[0][1])
    batch = [(path, payload) for path, payload in pending if delivery_group_of(payload) == group]
    latest_mtime = max(os.path.getmtime(path) for path, _payload in batch)
    fresh_cutoff = latest_mtime - int(os.environ.get("PICOCLAW_OUTBOX_RUN_WINDOW_SECONDS", "600"))
    stale = [
        (path, payload, "stale pending payload from earlier run in same delivery group")
        for path, payload in batch
        if os.path.getmtime(path) < fresh_cutoff
    ]
    batch = [
        (path, payload)
        for path, payload in batch
        if os.path.getmtime(path) >= fresh_cutoff
    ]
    role_order = {"fleet_overview": 0, "field_alert": 1, "single_report": 2}
    selected = [
        item for item in batch
        if role_of(item[1]) in {"fleet_overview", "field_alert", "single_report"}
    ]
    overview_items = [item for item in selected if role_of(item[1]) == "fleet_overview"]
    if overview_items:
        selected = overview_items
        selected_paths = {path for path, _payload in selected}
        skipped = [
            (path, payload, "scheduled alert group: sent consolidated vineyard overview only")
            for path, payload in batch
            if path not in selected_paths
        ]
        skipped.extend(stale)
        return selected, skipped
    selected.sort(key=lambda item: (role_order.get(role_of(item[1]), 99), os.path.getmtime(item[0])))
    if not selected:
        selected = [batch[0]]
    selected_paths = {path for path, _payload in selected}
    skipped = [
        (path, payload, "delivery group has fleet overview/alert selection")
        for path, payload in batch
        if path not in selected_paths
    ]
    skipped.extend(stale)
    return selected, skipped


def main():
    parser = argparse.ArgumentParser(description="Send picoClaw Telegram outbox without LLM rewriting.")
    parser.add_argument("--outbox", default=os.environ.get("PICOCLAW_OUTBOX", "/tmp/picoclaw_outbox"))
    parser.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    parser.add_argument("--chat-ids", default=os.environ.get("TELEGRAM_CHAT_IDS"))
    parser.add_argument(
        "--config",
        default=os.environ.get("PICOCLAW_CONFIG")
        or os.path.join(os.environ.get("PICOCLAW_HOME", "/root/.picoclaw"), "config.json"),
    )
    parser.add_argument(
        "--no-config-recipients",
        action="store_true",
        help="do not add numeric Telegram allow_from users as direct recipients",
    )
    parser.add_argument("--once", action="store_true", help="send only the first pending payload")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("PICOCLAW_TELEGRAM_TIMEOUT_SECONDS", "90")),
        help="Telegram HTTP timeout in seconds",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=float(os.environ.get("PICOCLAW_OUTBOX_MAX_PENDING_AGE_HOURS", "18")),
        help="skip pending Vineyard Guard payloads older than this; 0 disables",
    )
    args = parser.parse_args()
    include_allow_from = not args.no_config_recipients and os.environ.get(
        "PICOCLAW_TELEGRAM_INCLUDE_ALLOW_FROM", "true"
    ).lower() not in {"0", "false", "no"}
    recipients = resolve_recipients(
        args.chat_id,
        args.chat_ids,
        args.config,
        include_allow_from=include_allow_from,
    )

    if not os.path.isdir(args.outbox):
        print(json.dumps({"ok": False, "error": f"outbox missing: {args.outbox}"}))
        return 1
    if not recipients:
        print(json.dumps({
            "ok": False,
            "error": "no Telegram recipients configured; set TELEGRAM_CHAT_ID/TELEGRAM_CHAT_IDS or numeric allow_from",
        }))
        return 1
    if not args.dry_run and not args.token:
        print(json.dumps({"ok": False, "error": "TELEGRAM_BOT_TOKEN is required"}))
        return 1

    sent = []
    errors = []
    skipped = skip_stale_pending(args.outbox, args.max_age_hours, args.dry_run)
    if args.once:
        selected, skipped_items = select_gateway_batch(args.outbox)
        for path, payload, reason in skipped_items:
            if args.dry_run:
                skipped.append({"path": path, "reason": reason, "dry_run": True})
            else:
                mark_skipped_by_gateway(path, payload, reason)
                skipped.append({"path": path, "reason": reason})
        for path, _payload in selected:
            try:
                sent.append(send_payload_to_recipients(
                    path, args.token, recipients, args.dry_run, timeout=args.timeout
                ))
            except Exception as exc:
                if not args.dry_run:
                    record_send_error(path, _payload, exc)
                errors.append({"path": path, "error": str(exc)})
    else:
        for path in iter_pending(args.outbox):
            try:
                sent.append(send_payload_to_recipients(
                    path, args.token, recipients, args.dry_run, timeout=args.timeout
                ))
            except Exception as exc:
                if not args.dry_run:
                    record_send_error(path, None, exc)
                errors.append({"path": path, "error": str(exc)})
    print(json.dumps({
        "ok": not errors,
        "sent": len(sent),
        "recipient_count": len(recipients),
        "skipped": skipped,
        "errors": errors,
    }, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
