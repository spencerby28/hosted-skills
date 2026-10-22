"""Offline tests for global-email cleanup and attachment helpers (no network, fake Gmail service)."""
import argparse
import json
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mail_bridge as mb  # noqa: E402


class Call:
    def __init__(self, result=None, record=None):
        self.result, self.record = result, record

    def execute(self, num_retries=0):
        if self.record:
            self.record()
        return self.result


class FakeMessages:
    def __init__(self, store, log):
        self.store, self.log = store, log

    def list(self, userId, q, maxResults, pageToken=None, includeSpamTrash=False):
        self.log.append(("list", q, includeSpamTrash))
        ids = sorted(self.store)
        start = int(pageToken or 0)
        page = ids[start : start + maxResults]
        nxt = start + maxResults
        return Call({"messages": [{"id": i} for i in page], **({"nextPageToken": str(nxt)} if nxt < len(ids) else {})})

    def get(self, userId, id, format, metadataHeaders):
        m = self.store[id]
        return Call({"id": id, "sizeEstimate": m["size"], "labelIds": m.get("labels", []),
                     "payload": {"headers": [{"name": "From", "value": m["from"]}]}})

    def trash(self, userId, id):
        return Call({"id": id}, lambda: self.log.append(("trash", id)))

    def untrash(self, userId, id):
        return Call({"id": id}, lambda: self.log.append(("untrash", id)))

    def batchDelete(self, userId, body):
        return Call({}, lambda: self.log.append(("batchDelete", len(body["ids"]))))

    def batchModify(self, userId, body):
        return Call({}, lambda: self.log.append(("batchModify", len(body["ids"]), body.get("removeLabelIds"))))


class FakeBatch:
    def __init__(self, callback):
        self.callback, self.items = callback, []

    def add(self, call, request_id):
        self.items.append((request_id, call))

    def execute(self):
        for rid, call in self.items:
            self.callback(rid, call.execute(), None)


class FakeService:
    def __init__(self, store):
        self.log = []
        self.msgs = FakeMessages(store, self.log)

    def users(self):
        return self

    def messages(self):
        return self.msgs

    def new_batch_http_request(self, callback):
        return FakeBatch(callback)


def make_store(n, sender="news@shop.example", size=1000):
    return {f"m{i:05d}": {"from": sender, "size": size} for i in range(n)}


def args(**kw):
    base = dict(query="category:promotions", action="trash", add_label=None, remove_label=None,
                protect_sender=None, protect_label=None, limit=0, size_sample=0, manifest=None, execute=False)
    base.update(kw)
    return argparse.Namespace(**base)


class CleanTests(unittest.TestCase):
    def account(self, scopes):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"scopes": scopes}, tmp)
        tmp.close()
        return {"id": "gmail-test", "provider": "gmail", "token_path": tmp.name,
                "protected_senders": ["bank@example.com"]}

    def test_query_wraps_and_excludes_protected(self):
        q = mb.clean_query("older_than:1y OR larger:5M", ["bank@example.com"], ["STARRED", "Receipts"], "trash")
        self.assertEqual(q, "(older_than:1y OR larger:5M) -from:bank@example.com -is:starred -label:Receipts")

    def test_empty_query_refused(self):
        with self.assertRaises(mb.BridgeError):
            mb.clean_query("  ", [], [], "trash")

    def test_dry_run_counts_sizes_and_changes_nothing(self):
        svc = FakeService(make_store(120, size=2000))
        res = mb.gmail_clean(self.account([mb.GMAIL_READONLY_SCOPE]), args(size_sample=60), svc)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["matched"], 120)
        self.assertEqual(res["size_bytes_estimated"], 240000)
        self.assertTrue(res["size_is_estimate"])
        self.assertIn("-from:bank@example.com", res["query"])
        self.assertFalse([e for e in svc.log if e[0] != "list"])

    def test_execute_trash_requires_modify_scope(self):
        svc = FakeService(make_store(3))
        with self.assertRaises(mb.BridgeError) as ctx:
            mb.gmail_clean(self.account([mb.GMAIL_READONLY_SCOPE, mb.GMAIL_COMPOSE_SCOPE]), args(execute=True), svc)
        self.assertIn("--scope-set modify", str(ctx.exception))
        self.assertEqual(svc.log, [])

    def test_execute_trash_and_manifest(self):
        svc = FakeService(make_store(130))
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / "m.jsonl"
            res = mb.gmail_clean(self.account([mb.GMAIL_MODIFY_SCOPE]),
                                 args(execute=True, manifest=str(manifest), size_sample=10), svc)
            self.assertEqual(res["applied"], 130)
            self.assertEqual(res["failed"], 0)
            self.assertEqual(len([e for e in svc.log if e[0] == "trash"]), 130)
            self.assertEqual(len(manifest.read_text().splitlines()), 130)
        self.assertIn("count toward storage", res["note"])

    def test_delete_requires_full_scope_and_chunks(self):
        svc = FakeService(make_store(2500))
        with self.assertRaises(mb.BridgeError) as ctx:
            mb.gmail_clean(self.account([mb.GMAIL_MODIFY_SCOPE]), args(action="delete", execute=True), svc)
        self.assertIn("--scope-set full", str(ctx.exception))
        res = mb.gmail_clean(self.account([mb.GMAIL_FULL_SCOPE]),
                             args(action="delete", execute=True, query="in:trash", size_sample=5), svc)
        self.assertEqual(res["applied"], 2500)
        self.assertEqual([e[1] for e in svc.log if e[0] == "batchDelete"], [1000, 1000, 500])
        self.assertTrue(all(e[2] for e in svc.log if e[0] == "list"), "delete must list with includeSpamTrash")

    def test_archive_uses_batch_modify(self):
        svc = FakeService(make_store(5))
        res = mb.gmail_clean(self.account([mb.GMAIL_FULL_SCOPE]), args(action="archive", execute=True), svc)
        self.assertEqual(res["applied"], 5)
        self.assertIn(("batchModify", 5, ["INBOX"]), svc.log)

    def test_guard_trips_before_any_change(self):
        store = make_store(10)
        store["m00003"]["from"] = "Bank <bank@example.com>"  # query exclusion failed to filter it
        svc = FakeService(store)
        with self.assertRaises(mb.BridgeError):
            mb.gmail_clean(self.account([mb.GMAIL_MODIFY_SCOPE]), args(execute=True), svc)
        self.assertFalse([e for e in svc.log if e[0] == "trash"])

    def test_limit_caps(self):
        svc = FakeService(make_store(900))
        res = mb.gmail_clean(self.account([mb.GMAIL_READONLY_SCOPE]), args(limit=600, size_sample=1), svc)
        self.assertEqual(res["matched"], 600)
        self.assertTrue(res["matched_is_capped"])

    def test_scope_sets(self):
        self.assertEqual(mb.GMAIL_SCOPE_SETS["full"], ["https://mail.google.com/"])
        self.assertEqual(mb.GMAIL_SCOPE_SETS["modify"], [mb.GMAIL_MODIFY_SCOPE])


class AttachmentTests(unittest.TestCase):
    def test_traversal_names_stay_inside_dir(self):
        msg = EmailMessage()
        msg.set_content("hi")
        msg.add_attachment(b"A", maintype="application", subtype="octet-stream", filename="../../escape.txt")
        msg.add_attachment(b"B", maintype="application", subtype="octet-stream", filename="../../escape.txt")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            saved = mb.save_attachments(mb.email_message_attachments(msg), str(out), False)
            self.assertEqual([Path(s["path"]).name for s in saved], ["escape.txt", "escape-1.txt"])
            self.assertTrue(all(Path(s["path"]).parent == out for s in saved))
            self.assertFalse((Path(d) / "escape.txt").exists())

    def test_metadata_only_without_dir(self):
        msg = EmailMessage()
        msg.set_content("hi")
        msg.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="a.pdf")
        listed = mb.save_attachments(mb.email_message_attachments(msg), None, False)
        self.assertEqual(listed, [{"index": 0, "filename": "a.pdf", "content_type": "application/pdf", "size": 4}])


if __name__ == "__main__":
    unittest.main()
