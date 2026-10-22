#!/usr/bin/env python3
"""Read-first mail bridge for the global-email skill."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import email
from email.message import EmailMessage
import html
import imaplib
import json
import os
from pathlib import Path
import re
import shlex
import smtplib
import subprocess
import sys
from typing import Any, Iterable


CONFIG_PATH = Path(
    os.environ.get("GLOBAL_EMAIL_CONFIG", "~/.codex/global-email/accounts.json")
).expanduser()

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID"]
# Read calls retry 429/5xx/rateLimitExceeded with jittered exponential backoff (rand * 2**n s).
# The Gmail per-user bucket is shared by every process using the same account + OAuth project,
# so a bulk scan elsewhere can exhaust it. Sends and draft creation are never retried.
GMAIL_READ_RETRIES = int(os.environ.get("GLOBAL_EMAIL_GMAIL_RETRIES", "6"))


class BridgeError(Exception):
    """Expected bridge failure that should be shown without a traceback."""


def json_print(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BridgeError(
            f"Config not found: {path}. Run `mail_bridge.py config-template > {path}` "
            "and then edit account IDs and credential paths."
        )
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Invalid JSON config at {path}: {exc}") from exc


def accounts_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    accounts = config.get("accounts", [])
    if not isinstance(accounts, list):
        raise BridgeError("Config field `accounts` must be a list.")
    return accounts


def account_id(account: dict[str, Any]) -> str:
    return str(account.get("id") or account.get("email") or "unknown")


def select_accounts(config: dict[str, Any], wanted: list[str] | None) -> list[dict[str, Any]]:
    accounts = accounts_from_config(config)
    if not wanted:
        return accounts
    wanted_set = set(wanted)
    selected = [a for a in accounts if account_id(a) in wanted_set or a.get("email") in wanted_set]
    missing = sorted(wanted_set - {account_id(a) for a in selected} - {a.get("email") for a in selected})
    if missing:
        raise BridgeError(f"No configured account matched: {', '.join(missing)}")
    return selected


def parse_since(args: argparse.Namespace) -> dt.date | None:
    if getattr(args, "since", None):
        try:
            return dt.date.fromisoformat(args.since)
        except ValueError as exc:
            raise BridgeError("--since must be YYYY-MM-DD") from exc
    if getattr(args, "days", None):
        return dt.date.today() - dt.timedelta(days=args.days)
    return None


def normalize_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(value)))
    except Exception:
        return value


def headers_from_message(msg: email.message.Message) -> dict[str, str]:
    return {
        "from": normalize_header(msg.get("From")),
        "to": normalize_header(msg.get("To")),
        "cc": normalize_header(msg.get("Cc")),
        "bcc": normalize_header(msg.get("Bcc")),
        "subject": normalize_header(msg.get("Subject")),
        "date": normalize_header(msg.get("Date")),
        "message_id_header": normalize_header(msg.get("Message-ID")),
    }


def parsed_date(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.isoformat()


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n", value)
    value = re.sub(r"(?s)<.*?>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def body_from_email_message(msg: email.message.Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(text.strip())
        else:
            html_parts.append(strip_html(text))
    return "\n\n".join(p for p in plain_parts if p) or "\n\n".join(p for p in html_parts if p)


def email_message_attachments(msg: email.message.Message) -> list[tuple[dict[str, Any], bytes]]:
    """Return (metadata, payload) for each named or attachment-disposition leaf part."""
    found: list[tuple[dict[str, Any], bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = normalize_header(part.get_filename()) if part.get_filename() else ""
        if not filename and part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        meta = {
            "index": len(found),
            "filename": filename,
            "content_type": part.get_content_type(),
            "size": len(payload),
        }
        found.append((meta, payload))
    return found


def safe_attachment_name(meta: dict[str, Any]) -> str:
    # Attachment names come from the sender: keep only a plain basename.
    name = Path(str(meta.get("filename") or "").replace("\\", "/")).name
    name = re.sub(r"[^\w.()+\- ]", "_", name).strip(" .")
    if not name:
        subtype = str(meta.get("content_type") or "application/octet-stream").split("/")[-1]
        name = f"attachment-{meta['index']}.{re.sub(r'[^A-Za-z0-9]', '', subtype) or 'bin'}"
    suffix = Path(name).suffix[:20]
    return name[: 200 - len(suffix)] + suffix if len(name) > 200 else name


def save_attachments(
    attachments: list[tuple[dict[str, Any], bytes]], save_dir: str | None, pdf_text: bool
) -> list[dict[str, Any]]:
    """Write payloads to save_dir (never overwriting) and return the metadata list."""
    if not save_dir:
        return [meta for meta, _ in attachments]
    directory = Path(save_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for meta, payload in attachments:
        name = safe_attachment_name(meta)
        target = directory / name
        counter = 1
        while target.exists():
            target = directory / f"{Path(name).stem}-{counter}{Path(name).suffix}"
            counter += 1
        target.write_bytes(payload)
        saved = {**meta, "path": str(target)}
        is_pdf = meta.get("content_type") == "application/pdf" or target.suffix.lower() == ".pdf"
        if pdf_text and is_pdf:
            text_path = target.with_suffix(".txt")
            try:
                subprocess.run(
                    ["pdftotext", "-layout", str(target), str(text_path)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
                saved["text_path"] = str(text_path)
            except FileNotFoundError:
                saved["text_error"] = "pdftotext not installed"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                saved["text_error"] = f"pdftotext failed: {exc}"
        results.append(saved)
    return results


def snippet(text: str, limit: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def arg_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def gmail_query_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.%+\-@=]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def internal_date_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        timestamp = int(value) / 1000
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat()


def message_sort_key(message: dict[str, Any]) -> str:
    return str(message.get("date_iso") or message.get("date") or "")


def normalized_subject(value: str | None) -> str:
    subject = re.sub(r"\s+", " ", value or "").strip().lower()
    while True:
        cleaned = re.sub(r"^(re|fw|fwd):\s*", "", subject).strip()
        if cleaned == subject:
            return cleaned
        subject = cleaned


def message_participants(message: dict[str, Any]) -> list[str]:
    values = [
        str(message.get("from") or ""),
        str(message.get("to") or ""),
        str(message.get("cc") or ""),
        str(message.get("bcc") or ""),
    ]
    found: list[str] = []
    for name, addr in email.utils.getaddresses(values):
        participant = addr or name
        if participant and participant not in found:
            found.append(participant)
    return found


def thread_participants(messages: list[dict[str, Any]]) -> list[str]:
    participants: list[str] = []
    for message in messages:
        for participant in message_participants(message):
            if participant not in participants:
                participants.append(participant)
    return participants


def context_message(message: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "message_id",
        "thread_id",
        "date",
        "date_iso",
        "from",
        "to",
        "cc",
        "bcc",
        "subject",
        "snippet",
        "labels",
        "mailbox",
    ]
    return {key: message.get(key) for key in allowed if key in message}


def thread_summary(
    *,
    account: dict[str, Any],
    provider: str,
    thread_id: str,
    messages: list[dict[str, Any]],
    messages_per_thread: int,
    approximate: bool = False,
) -> dict[str, Any]:
    if not messages:
        raise BridgeError("Cannot summarize an empty thread.")
    newest_first = sorted(messages, key=message_sort_key, reverse=True)
    latest = newest_first[0]
    selected = sorted(newest_first[:messages_per_thread], key=message_sort_key)
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": provider,
        "thread_id": thread_id,
        "approximate_thread": approximate,
        "subject": latest.get("subject") or "",
        "latest_date": latest.get("date") or "",
        "latest_date_iso": latest.get("date_iso"),
        "participants": thread_participants(newest_first),
        "message_count": len(messages),
        "context": [context_message(message) for message in selected],
    }


def require_google_libs():
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise BridgeError(
            "Missing Gmail API libraries. Install with: "
            "python3 -m pip install --user google-api-python-client "
            "google-auth-oauthlib google-auth-httplib2"
        ) from exc
    return Credentials, Request, InstalledAppFlow, build


def gmail_service(account: dict[str, Any]):
    Credentials, Request, _, build = require_google_libs()
    token_path = Path(str(account.get("token_path") or "")).expanduser()
    client_secret_path = Path(str(account.get("client_secret_path") or "")).expanduser()
    if not token_path.exists():
        raise BridgeError(f"{account_id(account)} Gmail token missing: {token_path}")
    scopes = account.get("scopes")
    if scopes is not None and not isinstance(scopes, list):
        raise BridgeError(f"{account_id(account)} scopes must be a list.")
    try:
        token_data = json.loads(token_path.read_text())
    except json.JSONDecodeError as exc:
        raise BridgeError(f"{account_id(account)} Gmail token is not valid JSON: {token_path}") from exc
    if "client_id" in token_data and "client_secret" in token_data:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    else:
        if not client_secret_path.exists():
            raise BridgeError(f"{account_id(account)} Gmail client secret missing: {client_secret_path}")
        client_data = json.loads(client_secret_path.read_text())
        installed = client_data.get("installed") or client_data.get("web") or client_data
        client_id = installed.get("client_id")
        client_secret = installed.get("client_secret")
        token_uri = installed.get("token_uri") or "https://oauth2.googleapis.com/token"
        if not client_id or not client_secret:
            raise BridgeError(f"{account_id(account)} Gmail client file lacks client_id/client_secret.")
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes or token_data.get("scopes"),
        )
    if (creds.expired or not creds.valid) and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    if not creds.valid:
        raise BridgeError(f"{account_id(account)} Gmail token is invalid; rerun setup-gmail.")
    return build("gmail", "v1", credentials=creds)


def gmail_headers(payload: dict[str, Any]) -> dict[str, str]:
    raw_headers = payload.get("headers", [])
    by_name = {h.get("name", "").lower(): h.get("value", "") for h in raw_headers}
    return {
        "from": normalize_header(by_name.get("from")),
        "to": normalize_header(by_name.get("to")),
        "cc": normalize_header(by_name.get("cc")),
        "bcc": normalize_header(by_name.get("bcc")),
        "subject": normalize_header(by_name.get("subject")),
        "date": normalize_header(by_name.get("date")),
        "message_id_header": normalize_header(by_name.get("message-id")),
    }


def build_gmail_query(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if getattr(args, "query", None):
        parts.append(args.query)
    if getattr(args, "sender", None):
        parts.append(f"from:{gmail_query_value(args.sender)}")
    if getattr(args, "subject", None):
        parts.append(f"subject:{gmail_query_value(args.subject)}")
    recipient_terms: list[str] = []
    for recipient in arg_values(getattr(args, "recipient", None)):
        value = gmail_query_value(recipient)
        recipient_terms.extend([f"to:{value}", f"cc:{value}", f"bcc:{value}"])
    if recipient_terms:
        parts.append("{" + " ".join(recipient_terms) + "}")
    since = parse_since(args)
    if since:
        parts.append("after:" + since.strftime("%Y/%m/%d"))
    if getattr(args, "unread", False):
        parts.append("is:unread")
    return " ".join(parts)


def gmail_metadata_message(account: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    headers = gmail_headers(detail.get("payload", {}))
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": "gmail",
        "message_id": detail.get("id"),
        "thread_id": detail.get("threadId"),
        "date": headers["date"],
        "date_iso": parsed_date(headers["date"]) or internal_date_iso(detail.get("internalDate")),
        "from": headers["from"],
        "to": headers["to"],
        "cc": headers["cc"],
        "bcc": headers["bcc"],
        "subject": headers["subject"],
        "snippet": detail.get("snippet", ""),
        "labels": detail.get("labelIds", []),
    }


def gmail_search(account: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    service = gmail_service(account)
    query = build_gmail_query(args)
    limit = args.limit
    found: list[dict[str, Any]] = []
    page_token = None
    while len(found) < limit:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(100, limit - len(found)), pageToken=page_token)
            .execute(num_retries=GMAIL_READ_RETRIES)
        )
        messages = response.get("messages", [])
        if not messages:
            break
        for item in messages:
            detail = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=GMAIL_METADATA_HEADERS,
                )
                .execute(num_retries=GMAIL_READ_RETRIES)
            )
            found.append(gmail_metadata_message(account, detail))
            if len(found) >= limit:
                break
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return found


def gmail_recent_threads(account: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    service = gmail_service(account)
    query = build_gmail_query(args)
    scan_limit = max(args.limit, args.scan_limit)
    seen: set[str] = set()
    thread_ids: list[str] = []
    page_token = None
    scanned = 0
    while len(thread_ids) < args.limit and scanned < scan_limit:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=min(100, scan_limit - scanned),
                pageToken=page_token,
            )
            .execute(num_retries=GMAIL_READ_RETRIES)
        )
        messages = response.get("messages", [])
        if not messages:
            break
        for item in messages:
            scanned += 1
            thread_id = item.get("threadId")
            if thread_id and thread_id not in seen:
                seen.add(thread_id)
                thread_ids.append(thread_id)
                if len(thread_ids) >= args.limit:
                    break
            if scanned >= scan_limit:
                break
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    summaries: list[dict[str, Any]] = []
    for thread_id in thread_ids:
        thread = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=GMAIL_METADATA_HEADERS,
            )
            .execute(num_retries=GMAIL_READ_RETRIES)
        )
        messages = [gmail_metadata_message(account, item) for item in thread.get("messages", [])]
        if messages:
            summaries.append(
                thread_summary(
                    account=account,
                    provider="gmail",
                    thread_id=thread_id,
                    messages=messages,
                    messages_per_thread=args.messages_per_thread,
                )
            )
    return summaries


def gmail_payload_text(payload: dict[str, Any]) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if body_data and mime_type in {"text/plain", "text/html"}:
            padding = "=" * (-len(body_data) % 4)
            decoded = base64.urlsafe_b64decode((body_data + padding).encode())
            text = decoded.decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                plain_parts.append(text.strip())
            else:
                html_parts.append(strip_html(text))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n\n".join(p for p in plain_parts if p), "\n\n".join(p for p in html_parts if p)


def gmail_attachments(service: Any, message_id: str, payload: dict[str, Any]) -> list[tuple[dict[str, Any], bytes]]:
    found: list[tuple[dict[str, Any], bytes]] = []

    def decode(data: str) -> bytes:
        return base64.urlsafe_b64decode((data + "=" * (-len(data) % 4)).encode())

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body", {}) or {}
        filename = part.get("filename") or ""
        if (filename or body.get("attachmentId")) and not part.get("parts"):
            if body.get("data"):
                data = decode(body["data"])
            else:
                fetched = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=body["attachmentId"])
                    .execute(num_retries=GMAIL_READ_RETRIES)
                )
                data = decode(fetched.get("data", ""))
            meta = {
                "index": len(found),
                "filename": filename,
                "content_type": part.get("mimeType", ""),
                "size": len(data),
            }
            found.append((meta, data))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return found


def gmail_read(
    account: dict[str, Any], message_id: str, save_dir: str | None = None, pdf_text: bool = False
) -> dict[str, Any]:
    service = gmail_service(account)
    detail = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute(num_retries=GMAIL_READ_RETRIES)
    )
    headers = gmail_headers(detail.get("payload", {}))
    plain, html_text = gmail_payload_text(detail.get("payload", {}))
    body = plain or html_text
    attachments = gmail_attachments(service, detail.get("id") or message_id, detail.get("payload", {}))
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": "gmail",
        "message_id": detail.get("id"),
        "thread_id": detail.get("threadId"),
        "date": headers["date"],
        "date_iso": parsed_date(headers["date"]),
        "from": headers["from"],
        "to": headers["to"],
        "cc": headers["cc"],
        "bcc": headers["bcc"],
        "subject": headers["subject"],
        "snippet": detail.get("snippet", ""),
        "labels": detail.get("labelIds", []),
        "body": body,
        "attachments": save_attachments(attachments, save_dir, pdf_text),
    }


def split_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def read_body_arg(args: argparse.Namespace) -> str:
    if args.body_file:
        if args.body_file == "-":
            return sys.stdin.read()
        return Path(args.body_file).expanduser().read_text()
    return args.body or ""


def build_plain_message(
    *,
    from_addr: str | None,
    to: str | None,
    cc: str | None,
    bcc: str | None,
    subject: str,
    body: str,
    reply_to_message_id: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    if from_addr:
        message["From"] = from_addr
    if to:
        message["To"] = ", ".join(split_addresses(to))
    if cc:
        message["Cc"] = ", ".join(split_addresses(cc))
    if bcc:
        message["Bcc"] = ", ".join(split_addresses(bcc))
    message["Subject"] = subject
    if reply_to_message_id:
        message["In-Reply-To"] = reply_to_message_id
        message["References"] = f"{references} {reply_to_message_id}".strip() if references else reply_to_message_id
    message["Date"] = email.utils.formatdate(localtime=True)
    message.set_content(body)
    return message


def gmail_create_draft(account: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not args.body and not args.body_file:
        raise BridgeError("create-draft requires --body or --body-file.")
    if not args.to and not args.reply_message_id:
        raise BridgeError("create-draft requires --to unless --reply-message-id is provided.")

    service = gmail_service(account)
    message = build_plain_message(
        from_addr=args.from_addr,
        to=args.to,
        cc=args.cc,
        bcc=args.bcc,
        subject=args.subject,
        body=read_body_arg(args),
    )

    thread_id = args.thread_id
    if args.reply_message_id:
        source = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=args.reply_message_id,
                format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject"],
            )
            .execute(num_retries=GMAIL_READ_RETRIES)
        )
        thread_id = thread_id or source.get("threadId")
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in source.get("payload", {}).get("headers", [])
        }
        source_message_id = headers.get("message-id")
        if source_message_id:
            refs = headers.get("references")
            message.replace_header("In-Reply-To", source_message_id) if message.get("In-Reply-To") else message.__setitem__("In-Reply-To", source_message_id)
            message.replace_header("References", f"{refs} {source_message_id}".strip() if refs else source_message_id) if message.get("References") else message.__setitem__("References", f"{refs} {source_message_id}".strip() if refs else source_message_id)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft_body: dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id
    draft = service.users().drafts().create(userId="me", body=draft_body).execute()
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": "gmail",
        "draft_id": draft.get("id"),
        "message_id": draft.get("message", {}).get("id"),
        "thread_id": draft.get("message", {}).get("threadId"),
        "to": args.to,
        "cc": args.cc,
        "bcc": args.bcc,
        "subject": args.subject,
    }


def gmail_send(account: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not args.body and not args.body_file:
        raise BridgeError("send requires --body or --body-file.")
    if not args.to:
        raise BridgeError("send requires --to.")
    service = gmail_service(account)
    message = build_plain_message(
        from_addr=args.from_addr,
        to=args.to,
        cc=args.cc,
        bcc=args.bcc,
        subject=args.subject,
        body=read_body_arg(args),
    )

    thread_id = getattr(args, "thread_id", None)
    reply_message_id = getattr(args, "reply_message_id", None)
    if reply_message_id:
        source = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=reply_message_id,
                format="metadata",
                metadataHeaders=["Message-ID", "References", "Subject"],
            )
            .execute(num_retries=GMAIL_READ_RETRIES)
        )
        thread_id = thread_id or source.get("threadId")
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in source.get("payload", {}).get("headers", [])
        }
        source_message_id = headers.get("message-id")
        if source_message_id:
            refs = headers.get("references")
            if message.get("In-Reply-To"):
                message.replace_header("In-Reply-To", source_message_id)
            else:
                message["In-Reply-To"] = source_message_id
            ref_value = f"{refs} {source_message_id}".strip() if refs else source_message_id
            if message.get("References"):
                message.replace_header("References", ref_value)
            else:
                message["References"] = ref_value

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    send_body: dict[str, Any] = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id
    sent = service.users().messages().send(userId="me", body=send_body).execute()
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": "gmail",
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "to": args.to,
        "cc": args.cc,
        "bcc": args.bcc,
        "subject": args.subject,
    }


def password_for_imap(account: dict[str, Any]) -> str:
    if account.get("password_env"):
        value = os.environ.get(str(account["password_env"]))
        if value:
            return value
        raise BridgeError(f"{account_id(account)} password_env is unset: {account['password_env']}")
    if account.get("password_command"):
        try:
            value = subprocess.check_output(
                shlex.split(str(account["password_command"])),
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception as exc:
            raise BridgeError(f"{account_id(account)} password_command failed.") from exc
        if not value:
            raise BridgeError(f"{account_id(account)} password_command returned no password.")
        return value
    raise BridgeError(f"{account_id(account)} needs password_env or password_command.")


def imap_connect(account: dict[str, Any], *, select: bool = True, readonly: bool = True) -> imaplib.IMAP4_SSL:
    host = str(account.get("imap_host") or "imap.mail.me.com")
    port = int(account.get("imap_port") or 993)
    username = str(account.get("username") or account.get("email") or "")
    if not username:
        raise BridgeError(f"{account_id(account)} IMAP account needs username or email.")
    password = password_for_imap(account)
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(username, password)
    except imaplib.IMAP4.error as exc:
        raise BridgeError(f"{account_id(account)} IMAP authentication failed for {username}.") from exc
    if select:
        mailbox = str(account.get("mailbox") or "INBOX")
        status, _ = conn.select(mailbox, readonly=readonly)
        if status != "OK":
            raise BridgeError(f"{account_id(account)} could not select mailbox {mailbox}.")
    return conn


def imap_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def imap_criteria(args: argparse.Namespace) -> list[str]:
    criteria: list[str] = ["UNSEEN" if args.unread else "ALL"]
    since = parse_since(args)
    if since:
        criteria.extend(["SINCE", since.strftime("%d-%b-%Y")])
    if args.query:
        criteria.extend(["TEXT", imap_quote(args.query)])
    if args.sender:
        criteria.extend(["FROM", imap_quote(args.sender)])
    if args.subject:
        criteria.extend(["SUBJECT", imap_quote(args.subject)])
    recipient_terms: list[list[str]] = []
    for recipient in arg_values(getattr(args, "recipient", None)):
        quoted = imap_quote(recipient)
        recipient_terms.extend([["TO", quoted], ["CC", quoted], ["BCC", quoted]])
    if recipient_terms:
        criteria.extend(imap_or(recipient_terms))
    return criteria


def imap_or(terms: list[list[str]]) -> list[str]:
    if not terms:
        return []
    if len(terms) == 1:
        return terms[0]
    return ["OR"] + terms[0] + imap_or(terms[1:])


def imap_fetch_header(conn: imaplib.IMAP4_SSL, uid: bytes) -> email.message.Message:
    status, data = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO CC BCC SUBJECT DATE MESSAGE-ID)] FLAGS)")
    if status != "OK":
        raise BridgeError(f"Could not fetch IMAP header for UID {uid.decode()}.")
    for item in data:
        if isinstance(item, tuple):
            return email.message_from_bytes(item[1])
    raise BridgeError(f"Malformed IMAP header response for UID {uid.decode()}.")


def imap_search(account: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    conn = imap_connect(account)
    try:
        status, data = conn.uid("SEARCH", None, *imap_criteria(args))
        if status != "OK":
            raise BridgeError(f"{account_id(account)} IMAP search failed.")
        uids = (data[0] or b"").split()
        uids = list(reversed(uids))[: args.limit]
        results: list[dict[str, Any]] = []
        for uid in uids:
            msg = imap_fetch_header(conn, uid)
            headers = headers_from_message(msg)
            results.append(
                {
                    "account": account_id(account),
                    "account_email": account.get("email"),
                    "provider": "imap",
                    "message_id": uid.decode(),
                    "date": headers["date"],
                    "date_iso": parsed_date(headers["date"]),
                    "from": headers["from"],
                    "to": headers["to"],
                    "cc": headers["cc"],
                    "bcc": headers["bcc"],
                    "subject": headers["subject"],
                    "snippet": "",
                    "mailbox": account.get("mailbox") or "INBOX",
                }
            )
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def imap_read(
    account: dict[str, Any], message_id: str, save_dir: str | None = None, pdf_text: bool = False
) -> dict[str, Any]:
    conn = imap_connect(account)
    try:
        status, data = conn.uid("FETCH", message_id.encode(), "(BODY.PEEK[])")
        if status != "OK":
            raise BridgeError(f"{account_id(account)} could not fetch IMAP UID {message_id}.")
        raw = None
        for item in data:
            if isinstance(item, tuple):
                raw = item[1]
                break
        if raw is None:
            raise BridgeError(f"Malformed IMAP read response for UID {message_id}.")
        msg = email.message_from_bytes(raw)
        headers = headers_from_message(msg)
        body = body_from_email_message(msg)
        return {
            "account": account_id(account),
            "account_email": account.get("email"),
            "provider": "imap",
            "message_id": message_id,
            "date": headers["date"],
            "date_iso": parsed_date(headers["date"]),
            "from": headers["from"],
            "to": headers["to"],
            "cc": headers["cc"],
            "bcc": headers["bcc"],
            "subject": headers["subject"],
            "snippet": snippet(body),
            "mailbox": account.get("mailbox") or "INBOX",
            "body": body,
            "attachments": save_attachments(email_message_attachments(msg), save_dir, pdf_text),
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def imap_recent_threads(account: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    scan_args = argparse.Namespace(**vars(args))
    scan_args.limit = max(args.scan_limit, args.limit * args.messages_per_thread)
    messages = imap_search(account, scan_args)
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for message in messages:
        subject_key = normalized_subject(message.get("subject"))
        key = f"subject:{subject_key}" if subject_key else f"uid:{message.get('message_id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(message)

    summaries: list[dict[str, Any]] = []
    for key in order[: args.limit]:
        group = groups[key]
        hydrated: list[dict[str, Any]] = []
        for message in sorted(group, key=message_sort_key, reverse=True)[: args.messages_per_thread]:
            try:
                hydrated_message = imap_read(account, str(message["message_id"]))
                hydrated_message.pop("body", None)
                hydrated.append(hydrated_message)
            except BridgeError:
                hydrated.append(message)
        all_messages_by_id = {str(message.get("message_id")): message for message in group}
        for hydrated_message in hydrated:
            all_messages_by_id[str(hydrated_message.get("message_id"))] = hydrated_message
        summaries.append(
            thread_summary(
                account=account,
                provider="imap",
                thread_id=key,
                messages=list(all_messages_by_id.values()),
                messages_per_thread=args.messages_per_thread,
                approximate=True,
            )
        )
    return summaries


def imap_create_draft(account: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not args.body and not args.body_file:
        raise BridgeError("create-draft requires --body or --body-file.")
    if not args.to:
        raise BridgeError("create-draft requires --to for iCloud/IMAP accounts.")
    from_addr = args.from_addr or account.get("email")
    message = build_plain_message(
        from_addr=from_addr,
        to=args.to,
        cc=args.cc,
        bcc=args.bcc,
        subject=args.subject,
        body=read_body_arg(args),
    )
    mailbox = str(account.get("drafts_mailbox") or "Drafts")
    conn = imap_connect(account, select=False)
    try:
        status, data = conn.append(mailbox, None, imaplib.Time2Internaldate(dt.datetime.now().astimezone()), message.as_bytes())
        if status != "OK":
            detail = data[0].decode(errors="replace") if data else "unknown error"
            raise BridgeError(f"{account_id(account)} could not append draft to {mailbox}: {detail}")
        append_uid = ""
        if data and data[0]:
            append_uid = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
        return {
            "account": account_id(account),
            "account_email": account.get("email"),
            "provider": "imap",
            "draft_mailbox": mailbox,
            "append_uid": append_uid,
            "to": args.to,
            "cc": args.cc,
            "bcc": args.bcc,
            "subject": args.subject,
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def smtp_username(account: dict[str, Any]) -> str:
    explicit = account.get("smtp_username")
    if explicit:
        return str(explicit)
    username = str(account.get("username") or account.get("email") or "")
    if "@" in username:
        return username
    return f"{username}@icloud.com"


def smtp_send(account: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if not args.body and not args.body_file:
        raise BridgeError("send requires --body or --body-file.")
    if not args.to:
        raise BridgeError("send requires --to.")
    from_addr = args.from_addr or account.get("email")

    reply_to_mid: str | None = None
    references: str | None = None
    reply_message_id = getattr(args, "reply_message_id", None)
    if reply_message_id:
        conn = imap_connect(account)
        try:
            status, data = conn.uid("FETCH", reply_message_id.encode(), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES)])")
            if status == "OK":
                for item in data:
                    if isinstance(item, tuple):
                        hdr = email.message_from_bytes(item[1])
                        reply_to_mid = normalize_header(hdr.get("Message-ID"))
                        references = normalize_header(hdr.get("References"))
                        break
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    message = build_plain_message(
        from_addr=from_addr,
        to=args.to,
        cc=args.cc,
        bcc=args.bcc,
        subject=args.subject,
        body=read_body_arg(args),
        reply_to_message_id=reply_to_mid,
        references=references,
    )
    host = str(account.get("smtp_host") or "smtp.mail.me.com")
    port = int(account.get("smtp_port") or 587)
    username = smtp_username(account)
    password = password_for_imap(account)
    recipients = split_addresses(args.to) + split_addresses(args.cc) + split_addresses(args.bcc)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message, from_addr=from_addr, to_addrs=recipients)
    except smtplib.SMTPException as exc:
        raise BridgeError(f"{account_id(account)} SMTP send failed via {host}:{port} as {username}: {exc}") from exc
    return {
        "account": account_id(account),
        "account_email": account.get("email"),
        "provider": "smtp",
        "smtp_host": host,
        "smtp_username": username,
        "from": from_addr,
        "to": args.to,
        "cc": args.cc,
        "bcc": args.bcc,
        "subject": args.subject,
    }


def provider_status(account: dict[str, Any]) -> dict[str, Any]:
    provider = str(account.get("provider") or "").lower()
    status: dict[str, Any] = {
        "id": account_id(account),
        "email": account.get("email"),
        "provider": provider,
    }
    if provider == "gmail":
        token_path = Path(str(account.get("token_path") or "")).expanduser()
        client_secret_path = Path(str(account.get("client_secret_path") or "")).expanduser()
        status.update(
            {
                "token_path": str(token_path) if str(token_path) != "." else "",
                "token_exists": token_path.exists(),
                "client_secret_exists": client_secret_path.exists(),
                "ready": token_path.exists() and client_secret_path.exists(),
            }
        )
    elif provider == "imap":
        status.update(
            {
                "imap_host": account.get("imap_host") or "imap.mail.me.com",
                "mailbox": account.get("mailbox") or "INBOX",
                "has_password_env": bool(account.get("password_env")),
                "has_password_command": bool(account.get("password_command")),
                "ready": bool(account.get("password_env") or account.get("password_command")),
            }
        )
    else:
        status.update({"ready": False, "error": "Unsupported provider"})
    return status


def cmd_accounts(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, args.account)
    json_print({"ok": True, "accounts": [provider_status(a) for a in selected]})


def cmd_config_template(_: argparse.Namespace) -> None:
    json_print(
        {
            "accounts": [
                {
                    "id": "gmail-primary",
                    "provider": "gmail",
                    "email": "primary@example.com",
                    "client_secret_path": "~/.codex/global-email/google-oauth-client.json",
                    "token_path": "~/.codex/global-email/tokens/gmail-primary.json",
                },
                {
                    "id": "gmail-secondary",
                    "provider": "gmail",
                    "email": "secondary@example.com",
                    "client_secret_path": "~/.codex/global-email/google-oauth-client.json",
                    "token_path": "~/.codex/global-email/tokens/gmail-secondary.json",
                },
                {
                    "id": "icloud",
                    "provider": "imap",
                    "email": "name@icloud.com",
                    "username": "name@icloud.com",
                    "imap_host": "imap.mail.me.com",
                    "imap_port": 993,
                    "mailbox": "INBOX",
                    "drafts_mailbox": "Drafts",
                    "sent_mailbox": "Sent Messages",
                    "smtp_host": "smtp.mail.me.com",
                    "smtp_port": 587,
                    "smtp_username": "name@icloud.com",
                    "password_command": "security find-generic-password -a name@icloud.com -s global-email-icloud -w",
                },
            ]
        }
    )


def account_error(account: dict[str, Any], exc: Exception) -> dict[str, str]:
    if isinstance(exc, BridgeError):
        error = str(exc)
    else:
        error = f"{type(exc).__name__}: {exc}"
    error = " ".join(error.split())
    if len(error) > 500:
        error = error[:497].rstrip() + "..."
    return {"account": account_id(account), "error": error}


def cmd_search(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, args.account)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for account in selected:
        provider = str(account.get("provider") or "").lower()
        try:
            if provider == "gmail":
                results.extend(gmail_search(account, args))
            elif provider == "imap":
                results.extend(imap_search(account, args))
            else:
                raise BridgeError(f"Unsupported provider: {provider}")
        except Exception as exc:
            errors.append(account_error(account, exc))
    results.sort(key=lambda item: item.get("date_iso") or item.get("date") or "", reverse=True)
    json_print({"ok": not errors, "results": results[: args.limit], "errors": errors})


def cmd_recent(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, args.account)
    threads: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for account in selected:
        provider = str(account.get("provider") or "").lower()
        try:
            if provider == "gmail":
                threads.extend(gmail_recent_threads(account, args))
            elif provider == "imap":
                threads.extend(imap_recent_threads(account, args))
            else:
                raise BridgeError(f"Unsupported provider: {provider}")
        except Exception as exc:
            errors.append(account_error(account, exc))
    threads.sort(key=lambda item: item.get("latest_date_iso") or item.get("latest_date") or "", reverse=True)
    json_print({"ok": not errors, "threads": threads[: args.limit], "errors": errors})


def cmd_read(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, [args.account])
    if len(selected) != 1:
        raise BridgeError("read requires exactly one account.")
    account = selected[0]
    provider = str(account.get("provider") or "").lower()
    if args.pdf_text and not args.save_attachments:
        raise BridgeError("--pdf-text requires --save-attachments DIR.")
    if provider == "gmail":
        result = gmail_read(account, args.message_id, args.save_attachments, args.pdf_text)
    elif provider == "imap":
        result = imap_read(account, args.message_id, args.save_attachments, args.pdf_text)
    else:
        raise BridgeError(f"Unsupported provider: {provider}")
    json_print({"ok": True, "message": result})


def cmd_create_draft(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, [args.account])
    if len(selected) != 1:
        raise BridgeError("create-draft requires exactly one account.")
    account = selected[0]
    provider = str(account.get("provider") or "").lower()
    if provider == "gmail":
        result = gmail_create_draft(account, args)
    elif provider == "imap":
        result = imap_create_draft(account, args)
    else:
        raise BridgeError(f"Unsupported provider: {provider}")
    json_print({"ok": True, "draft": result})


def cmd_send(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).expanduser())
    selected = select_accounts(config, [args.account])
    if len(selected) != 1:
        raise BridgeError("send requires exactly one account.")
    account = selected[0]
    provider = str(account.get("provider") or "").lower()
    if provider == "gmail":
        result = gmail_send(account, args)
    elif provider == "imap":
        result = smtp_send(account, args)
    else:
        raise BridgeError(f"Unsupported provider: {provider}")
    json_print({"ok": True, "sent": result})


def cmd_setup_gmail(args: argparse.Namespace) -> None:
    _, _, InstalledAppFlow, _ = require_google_libs()
    client_secret = Path(args.client_secret).expanduser()
    token_path = Path(args.token_path).expanduser()
    if not client_secret.exists():
        raise BridgeError(f"Client secret JSON not found: {client_secret}")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if args.scope_set == "readonly":
        scopes = [GMAIL_READONLY_SCOPE]
    elif args.scope_set == "compose":
        scopes = [GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE]
    else:
        scopes = [GMAIL_MODIFY_SCOPE]
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes)
    creds = flow.run_local_server(port=0, open_browser=not args.no_browser)
    token_path.write_text(creds.to_json())
    json_print({"ok": True, "token_path": str(token_path), "scopes": scopes})


def add_common_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(CONFIG_PATH), help=f"Config JSON path (default: {CONFIG_PATH})")


def add_search_filter_args(parser: argparse.ArgumentParser, *, recipient_required: bool = False) -> None:
    parser.add_argument("--account", action="append", help="Account id or email. Repeat to query several.")
    parser.add_argument("--query", help="Gmail query string or IMAP text search.")
    parser.add_argument("--sender", help="Filter by sender email/name.")
    parser.add_argument(
        "--recipient",
        action="append",
        required=recipient_required,
        help="Filter by direct recipient in To/Cc/Bcc. Repeat for several.",
    )
    parser.add_argument("--subject", help="Filter by subject text.")
    parser.add_argument("--since", help="Start date YYYY-MM-DD.")
    parser.add_argument("--days", type=int, help="Search back this many days.")
    parser.add_argument("--unread", action="store_true", help="Only unread messages.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-first multi-account mail bridge.")
    sub = parser.add_subparsers(dest="command", required=True)

    config_template = sub.add_parser("config-template", help="Print a starter account config JSON.")
    config_template.set_defaults(func=cmd_config_template)

    accounts = sub.add_parser("accounts", help="List configured accounts without exposing secrets.")
    add_common_config_arg(accounts)
    accounts.add_argument("--account", action="append", help="Filter by account id or email.")
    accounts.set_defaults(func=cmd_accounts)

    search = sub.add_parser("search", help="Search configured accounts and return message metadata.")
    add_common_config_arg(search)
    add_search_filter_args(search)
    search.add_argument("--limit", type=int, default=25, help="Maximum combined results.")
    search.set_defaults(func=cmd_search)

    recipient_search = sub.add_parser("recipient-search", help="Search messages by To/Cc/Bcc recipient.")
    add_common_config_arg(recipient_search)
    add_search_filter_args(recipient_search, recipient_required=True)
    recipient_search.add_argument("--limit", type=int, default=25, help="Maximum combined results.")
    recipient_search.set_defaults(func=cmd_search)

    recent = sub.add_parser("recent", help="Show recent thread summaries with context messages.")
    add_common_config_arg(recent)
    add_search_filter_args(recent)
    recent.add_argument("--limit", type=int, default=10, help="Maximum combined threads.")
    recent.add_argument("--messages-per-thread", type=int, default=3, help="Context messages to include per thread.")
    recent.add_argument("--scan-limit", type=int, default=100, help="Messages to scan while finding recent threads.")
    recent.set_defaults(func=cmd_recent)

    read = sub.add_parser("read", help="Read one message body.")
    add_common_config_arg(read)
    read.add_argument("--account", required=True, help="Account id or email.")
    read.add_argument("--message-id", required=True, help="Gmail message id or IMAP UID from search results.")
    read.add_argument(
        "--save-attachments",
        metavar="DIR",
        help="Write attachments into DIR (created if missing; existing files are never overwritten).",
    )
    read.add_argument(
        "--pdf-text",
        action="store_true",
        help="With --save-attachments, also write a pdftotext -layout .txt beside each saved PDF.",
    )
    read.set_defaults(func=cmd_read)

    create_draft = sub.add_parser("create-draft", help="Create a Gmail or iCloud draft.")
    add_common_config_arg(create_draft)
    create_draft.add_argument("--account", required=True, help="Account id or email.")
    create_draft.add_argument("--to", help="Comma-separated recipients.")
    create_draft.add_argument("--cc", help="Comma-separated CC recipients.")
    create_draft.add_argument("--bcc", help="Comma-separated BCC recipients.")
    create_draft.add_argument("--subject", required=True, help="Draft subject.")
    create_draft.add_argument("--body", help="Plain text body.")
    create_draft.add_argument("--body-file", help="Plain text body file, or '-' for stdin.")
    create_draft.add_argument("--reply-message-id", help="Gmail message id to draft a threaded reply.")
    create_draft.add_argument("--thread-id", help="Existing Gmail thread id.")
    create_draft.add_argument("--from", dest="from_addr", help="From address or verified send-as alias.")
    create_draft.set_defaults(func=cmd_create_draft)

    send = sub.add_parser("send", help="Send an email through Gmail API or iCloud SMTP.")
    add_common_config_arg(send)
    send.add_argument("--account", required=True, help="Account id or email.")
    send.add_argument("--to", required=True, help="Comma-separated recipients.")
    send.add_argument("--cc", help="Comma-separated CC recipients.")
    send.add_argument("--bcc", help="Comma-separated BCC recipients.")
    send.add_argument("--subject", required=True, help="Subject.")
    send.add_argument("--body", help="Plain text body.")
    send.add_argument("--body-file", help="Plain text body file, or '-' for stdin.")
    send.add_argument("--reply-message-id", help="Gmail message id or IMAP UID to reply to (sets In-Reply-To/References headers and thread).")
    send.add_argument("--thread-id", help="Existing Gmail thread id.")
    send.add_argument("--from", dest="from_addr", help="From address or verified send-as alias.")
    send.set_defaults(func=cmd_send)

    setup_gmail = sub.add_parser("setup-gmail", help="Create a Gmail OAuth token.")
    setup_gmail.add_argument("--client-secret", required=True, help="Google OAuth desktop client JSON.")
    setup_gmail.add_argument("--token-path", required=True, help="Where to write the account token JSON.")
    setup_gmail.add_argument(
        "--scope-set",
        choices=["readonly", "compose", "modify"],
        default="compose",
        help="OAuth scopes to request. Default compose supports search/read and draft creation.",
    )
    setup_gmail.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening the system browser.",
    )
    setup_gmail.set_defaults(func=cmd_setup_gmail)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except BridgeError as exc:
        json_print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
