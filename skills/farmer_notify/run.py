#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys


def slug(text):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()).strip("_")[:80] or "alert"


def short_caption(title, message, limit=900):
    lines = [line.strip("# ").strip() for line in message.splitlines() if line.strip()]
    selected = [title]
    for line in lines:
        if line == title:
            continue
        candidate = "\n".join(selected + [line])
        if len(candidate) > limit:
            break
        selected.append(line)
        if len(selected) >= 8:
            break
    caption = "\n".join(selected).strip()
    return caption[:limit].rstrip()


def dedupe_key_for(title, message, channel, media_sources):
    body = json.dumps(
        {
            "title": title,
            "message": message,
            "channel": channel,
            "media_sources": sorted(str(path or "") for path in media_sources if path),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def parse_created_at(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def find_recent_duplicate(outbox, dedupe_key, window_minutes):
    if not dedupe_key or not os.path.isdir(outbox):
        return None
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=window_minutes)
    for name in sorted(os.listdir(outbox), reverse=True):
        if not name.endswith(".json"):
            continue
        path = os.path.join(outbox, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        if payload.get("dedupe_key") != dedupe_key:
            continue
        if payload.get("status") not in {"pending", "sent"}:
            continue
        created_at = parse_created_at(payload.get("created_at"))
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=dt.timezone.utc)
        if created_at and created_at < cutoff:
            continue
        return path, payload
    return None


def main():
    params = json.load(sys.stdin)
    outbox = params.get("outbox_dir") or "/tmp/picoclaw_outbox"
    title = params.get("title") or "Vineyard alert"
    message = params.get("message") or ""
    caption = params.get("caption") or short_caption(title, message)
    text_after_photo = params.get("text_after_photo") or ""
    input_media = params.get("media") or params.get("attachments") or []
    plot_path = params.get("plot_path") or ""
    image_path = params.get("image_path") or plot_path
    channel = params.get("channel") or "picoclaw_telegram"
    meta_keys = (
        "delivery_group",
        "dispatch_role",
        "field",
        "field_scope",
        "disease",
        "has_alert",
        "alert_diseases",
        "alert_fields",
        "ok_fields",
        "notify_mode",
        "language",
    )
    meta = params.get("meta") if isinstance(params.get("meta"), dict) else {}
    meta = dict(meta)
    for key in meta_keys:
        if key in params:
            meta[key] = params.get(key)
    media_sources = [
        (item.get("source_path") or item.get("path"))
        for item in input_media
        if isinstance(item, dict)
    ]
    if image_path:
        media_sources.append(image_path)
    dedupe_key = dedupe_key_for(title, message, channel, media_sources)
    dedupe_minutes = int(params.get("dedupe_minutes") or os.environ.get("PICOCLAW_NOTIFY_DEDUPE_MINUTES", "360"))
    duplicate = find_recent_duplicate(outbox, dedupe_key, dedupe_minutes)
    if duplicate:
        duplicate_path, duplicate_payload = duplicate
        print(json.dumps({
            "status": "skipped_duplicate",
            "reason": "matching notification already exists in outbox",
            "outbox_json": duplicate_path,
            "channel": duplicate_payload.get("channel", channel),
            "plot_path": duplicate_payload.get("plot_path", plot_path),
            "image_path": duplicate_payload.get("image_path") or duplicate_payload.get("photo_path"),
            "source_image_path": duplicate_payload.get("source_image_path", image_path),
            "photo_path": duplicate_payload.get("photo_path"),
            "attachment_path": duplicate_payload.get("attachment_path"),
            "attachments": duplicate_payload.get("attachments") or [],
            "media": duplicate_payload.get("media") or [],
            "telegram": duplicate_payload.get("telegram") or {},
            "must_attach_image": bool(duplicate_payload.get("must_attach_image")),
            "must_send_text": bool(duplicate_payload.get("must_send_text")),
            "send_text": duplicate_payload.get("send_text") or duplicate_payload.get("message") or "",
            "caption": duplicate_payload.get("caption") or "",
            "dedupe_key": dedupe_key,
            "meta": duplicate_payload.get("meta") or {},
            **{key: duplicate_payload.get(key) for key in meta_keys if key in duplicate_payload},
        }))
        return
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{ts}_{slug(title)}"
    os.makedirs(outbox, exist_ok=True)
    json_path = os.path.join(outbox, base + ".json")
    md_path = os.path.join(outbox, base + ".md")
    media = []

    def copy_media_item(source_path, item_caption, index=0, item=None):
        if not source_path:
            return None
        attached_path = source_path
        if os.path.exists(source_path):
            ext = os.path.splitext(source_path)[1] or ".png"
            suffix = "" if index == 0 else f"_{index + 1}"
            attached_path = os.path.join(outbox, base + suffix + ext)
            if os.path.abspath(attached_path) != os.path.abspath(source_path):
                shutil.copyfile(source_path, attached_path)
        return {
            "type": "photo",
            "path": attached_path,
            "source_path": source_path,
            "caption": item_caption,
            "mime_type": (item or {}).get("mime_type") or ("image/png" if attached_path.lower().endswith(".png") else "image/jpeg"),
            "exists": os.path.exists(attached_path),
            **({"disease": item.get("disease")} if isinstance(item, dict) and item.get("disease") else {}),
        }

    if input_media:
        for index, item in enumerate(input_media):
            if not isinstance(item, dict):
                continue
            copied = copy_media_item(
                item.get("path") or item.get("source_path"),
                item.get("caption") or (caption if index == 0 else ""),
                index,
                item,
            )
            if copied:
                media.append(copied)
    elif image_path:
        copied = copy_media_item(image_path, caption, 0, {})
        if copied:
            media.append(copied)

    attached_image_path = media[0]["path"] if media else image_path
    method = "sendMediaGroup" if len(media) > 1 else "sendPhoto" if media else "sendMessage"
    payload = {
        "status": "pending",
        "channel": channel,
        "title": title,
        "message": message,
        "send_text": message,
        "caption": caption,
        "text_after_photo": text_after_photo,
        "plot_path": plot_path,
        "image_path": attached_image_path,
        "source_image_path": image_path,
        "photo_path": attached_image_path,
        "attachment_path": attached_image_path,
        "attachments": media,
        "media": media,
        "telegram": {
            "method": method,
            "photo": attached_image_path,
            "caption": caption,
            "text_after_photo": text_after_photo if image_path else "",
            "media": media,
        },
        "must_attach_image": bool(attached_image_path),
        "must_send_text": bool(message),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dedupe_key": dedupe_key,
        "meta": meta,
        **{key: meta.get(key) for key in meta_keys if key in meta},
    }
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(f"# {title}\n\n{message}\n")
        if attached_image_path:
            handle.write(f"\nImage attachment: {attached_image_path}\n")
            if image_path != attached_image_path:
                handle.write(f"Source image: {image_path}\n")
    print(json.dumps({
        "status": "success",
        "outbox_json": json_path,
        "outbox_md": md_path,
        "channel": channel,
        "plot_path": plot_path,
        "image_path": attached_image_path,
        "source_image_path": image_path,
        "photo_path": attached_image_path,
        "attachment_path": attached_image_path,
        "attachments": media,
        "media": media,
        "telegram": payload["telegram"],
        "must_attach_image": bool(attached_image_path),
        "must_send_text": bool(message),
        "send_text": message,
        "caption": caption,
        "text_after_photo": text_after_photo,
        "meta": meta,
        **{key: meta.get(key) for key in meta_keys if key in meta},
    }))


if __name__ == "__main__":
    main()
