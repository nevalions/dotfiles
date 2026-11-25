"""Offline unit and CLI tests for the Pi Honcho batch publisher."""
import errno
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "pi" / ".pi" / "agent" / "honcho-cli"
BATCH_PATH = CLI_DIR / "batch.py"


def _load_module(name, path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gateway = _load_module("gateway", CLI_DIR / "gateway.py")
batch = _load_module("batch", BATCH_PATH)


def _write_private(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)
    return path


def _make_scope(repo="repo-alpha", session_id="sess-alpha-1", task="survey-1",
                workspace_id="hermes-personal", peer_id="pi-coordinator"):
    return {
        "workspace_id": workspace_id,
        "peer_id": peer_id,
        "target_peer_id": repo,
        "session_id": session_id,
        "task": task,
    }


def _make_item(checkout, grant, scope, *, candidate="rev-1", checks="pytest ok",
               verification="reviewed", conclusion="Verified repo alpha."):
    return {
        "checkout": str(checkout),
        "grant": str(grant),
        "scope": dict(scope),
        "candidate": candidate,
        "checks": checks,
        "verification": verification,
        "conclusion": conclusion,
    }


def _mcp_text_result(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


class FakeRemote:
    def __init__(self):
        self.pages_by_session = {}
        self.calls = []
        self.list_hook = None
        self.create_hook = None

    def key(self, args):
        return (
            args["workspace_id"],
            args["peer_id"],
            args["target_peer_id"],
            args["session_id"],
        )

    def seed_pages(self, scope, pages):
        self.pages_by_session[self.key(scope)] = [list(page) for page in pages]

    def add_row(self, scope, row_id, content, *, observer_id=None, observed_id=None, session_id=None):
        k = self.key(scope)
        pages = self.pages_by_session.setdefault(k, [])
        if not pages or len(pages[-1]) >= batch.PAGE_SIZE:
            pages.append([])
        pages[-1].append({
            "id": row_id,
            "content": content,
            "observer_id": scope["peer_id"] if observer_id is None else observer_id,
            "observed_id": scope["target_peer_id"] if observed_id is None else observed_id,
            "session_id": scope["session_id"] if session_id is None else session_id,
        })

    def call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "list_conclusions":
            if self.list_hook is not None:
                custom = self.list_hook(args)
                if custom is not None:
                    return custom
            pages = self.pages_by_session.get(self.key(args), [])
            total = sum(len(p) for p in pages)
            if total == 0:
                return _mcp_text_result({"conclusions": [], "page": 1, "pages": 0, "total": 0})
            page_num = args["page"]
            rows = pages[page_num - 1] if 1 <= page_num <= len(pages) else []
            return _mcp_text_result({
                "conclusions": rows,
                "page": page_num,
                "pages": len(pages),
                "total": total,
            })
        if name == "create_conclusions":
            if self.create_hook is not None:
                self.create_hook(args)
            for idx, note in enumerate(args["conclusions"]):
                self.add_row(args, f"c-{len(self.calls)}-{idx}", note)
            return _mcp_text_result({"ok": True})
        raise AssertionError(f"unexpected tool {name}")


class LoopbackMCPServer:
    def __init__(self, remote):
        self.remote = remote
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests.append((self.headers.get("Authorization"), body))
                method = body.get("method")
                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    result = {"protocolVersion": "2025-03-26", "capabilities": {}}
                elif method == "tools/call":
                    params = body["params"]
                    result = outer.remote.call(params["name"], params["arguments"])
                else:
                    result = {}
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class BatchEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.state_dir = self.root / "state"
        self.checkouts = self.root / "checkouts"
        self.checkouts.mkdir()
        self.routes = {}

    def _checkout(self, name, route):
        path = self.checkouts / name
        path.mkdir(parents=True, exist_ok=True)
        self.routes[str(path)] = route
        return path

    def _route_resolver(self, checkout):
        return self.routes[checkout]

    def _grant(self, name, scope, *, url="https://honcho.example/mcp", token="tok-secret-value-123",
               create_token=True, allow_tailnet_http=False):
        token_path = self.private / f"{name}.token"
        if create_token:
            _write_private(token_path, token + "\n")
        grant_obj = {
            "url": url,
            "token_file": str(token_path),
            "scope": dict(scope),
        }
        if allow_tailnet_http:
            grant_obj["allow_tailnet_http"] = True
        grant_path = self.private / f"{name}.grant.json"
        _write_private(grant_path, json.dumps(grant_obj))
        return grant_path, token_path

    def _manifest(self, items, name="manifest.json"):
        path = self.private / name
        _write_private(path, json.dumps({"items": items}))
        return path

    def _pending_files(self):
        if not self.state_dir.exists():
            return []
        return sorted(p.name for p in self.state_dir.iterdir() if p.name.endswith(".pending.json"))

    def test_preview_contract_and_missing_token_allowed(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, token_path = self._grant("alpha", scope, token="SUPER_SECRET_TOKEN", create_token=False)
        item = _make_item(checkout, grant, scope, candidate="abc1234")
        manifest = self._manifest([item])

        res = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)
        self.assertRegex(res["digest"], r"^[0-9a-f]{64}$")
        preview = res["preview"]
        self.assertIn("https://honcho.example/mcp", preview)
        for field_val in scope.values():
            self.assertIn(field_val, preview)
        expected_note = gateway.format_note(scope, item)
        self.assertIn(expected_note, preview)
        self.assertNotIn(str(token_path), preview)
        self.assertNotIn(str(grant), preview)
        self.assertNotIn("SUPER_SECRET_TOKEN", preview)

    def test_validation_rejects_bad_scope_routes_duplicates_and_permissions(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)

        bad_cases = [
            _make_scope("repo-alpha", workspace_id="other-ws"),
            _make_scope("repo-alpha", peer_id="other-peer"),
            _make_scope("repo-beta"),
        ]
        for bad_scope in bad_cases:
            bad_grant, _ = self._grant("bad", bad_scope)
            manifest = self._manifest([_make_item(checkout, bad_grant, bad_scope)], "bad.json")
            with self.assertRaises(batch.BatchError):
                batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)

        mismatched = _make_scope("repo-alpha", task="other-task")
        manifest = self._manifest([_make_item(checkout, grant, mismatched)], "mismatch.json")
        with self.assertRaises(batch.BatchError):
            batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)

        for disallowed in ("code-wide", "project-cluster-infra", "preferences", "pi-coordinator", "repo-*"):
            c_bad = self._checkout(f"bad-{disallowed.replace('*', 'star')}", disallowed)
            s_bad = _make_scope(disallowed if "*" not in disallowed else "repo-star")
            g_bad, _ = self._grant("disallowed", s_bad)
            m_bad = self._manifest([_make_item(c_bad, g_bad, s_bad)], "disallowed.json")
            with self.assertRaises(batch.BatchError):
                batch.preview(str(m_bad), "pi-sess-1", route_resolver=self._route_resolver)

        dup_manifest = self.private / "dup.json"
        _write_private(dup_manifest, '{"items": [], "items": []}')
        with self.assertRaises(batch.BatchError):
            batch.preview(str(dup_manifest), "pi-sess-1", route_resolver=self._route_resolver)

        empty_manifest = self._manifest([], "empty.json")
        with self.assertRaises(batch.BatchError):
            batch.preview(str(empty_manifest), "pi-sess-1", route_resolver=self._route_resolver)

        many_items = []
        for idx in range(33):
            name = f"repo-{idx}"
            sc = _make_scope(name, session_id=f"sess-{idx}")
            co = self._checkout(name, name)
            gr, _ = self._grant(name, sc)
            many_items.append(_make_item(co, gr, sc))
        over_manifest = self._manifest(many_items, "over.json")
        with self.assertRaises(batch.BatchError):
            batch.preview(str(over_manifest), "pi-sess-1", route_resolver=self._route_resolver)

        co1 = self._checkout("dup-a", "repo-dup")
        co2 = self._checkout("dup-b", "repo-dup")
        s1 = _make_scope("repo-dup", session_id="s1")
        s2 = _make_scope("repo-dup", session_id="s2")
        g1, _ = self._grant("d1", s1)
        g2, _ = self._grant("d2", s2)
        dup_repo_manifest = self._manifest([_make_item(co1, g1, s1), _make_item(co2, g2, s2)], "duprepo.json")
        with self.assertRaises(batch.BatchError):
            batch.preview(str(dup_repo_manifest), "pi-sess-1", route_resolver=self._route_resolver)

        perm_manifest = self._manifest([_make_item(checkout, grant, scope)], "perm.json")
        os.chmod(perm_manifest, 0o644)
        with self.assertRaises(batch.BatchError):
            batch.preview(str(perm_manifest), "pi-sess-1", route_resolver=self._route_resolver)
        link_manifest = self.private / "link.json"
        link_manifest.symlink_to(self._manifest([_make_item(checkout, grant, scope)], "real.json"))
        with self.assertRaises(batch.BatchError):
            batch.preview(str(link_manifest), "pi-sess-1", route_resolver=self._route_resolver)

    def test_stale_digest_grant_substitution_and_no_reopen_after_validation(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, token_path = self._grant("alpha", scope, token="token-v1")
        manifest = self._manifest([_make_item(checkout, grant, scope)])

        prev = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)
        remote = FakeRemote()
        calls = []

        def fail_if_called(_desc):
            calls.append(_desc)
            return remote

        with self.assertRaises(batch.BatchError):
            batch.apply(str(manifest), "pi-sess-other", prev["digest"],
                        state_dir=self.state_dir, route_resolver=self._route_resolver,
                        client_factory=fail_if_called)
        self.assertEqual(calls, [])

        self._grant("alpha", scope, url="https://evil.example/mcp")
        with self.assertRaises(batch.BatchError):
            batch.apply(str(manifest), "pi-sess-1", prev["digest"],
                        state_dir=self.state_dir, route_resolver=self._route_resolver,
                        client_factory=fail_if_called)
        self.assertEqual(calls, [])

        self._grant("alpha", scope, url="https://honcho.example/mcp", token="token-v2")
        def factory_unlinking_grant(desc):
            grant.unlink()
            self.assertEqual(desc["url"], "https://honcho.example/mcp")
            return remote

        out = batch.apply(str(manifest), "pi-sess-1", prev["digest"],
                          state_dir=self.state_dir, route_resolver=self._route_resolver,
                          client_factory=factory_unlinking_grant)
        self.assertEqual(out["results"][0]["status"], "verified")

    def test_malformed_and_wrong_binding_readback_blocks_without_append(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        manifest = self._manifest([_make_item(checkout, grant, scope)])
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        remote = FakeRemote()
        remote.add_row(scope, "r1", "unrelated", session_id="wrong-session")
        out = batch.apply(str(manifest), "pi-sess-1", digest,
                          state_dir=self.state_dir, route_resolver=self._route_resolver,
                          client_factory=lambda _d: remote)
        self.assertEqual(out["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote.calls))
        self.assertEqual(self._pending_files(), [])

        remote2 = FakeRemote()
        remote2.add_row(scope, "r1", "unrelated", observer_id="wrong-observer")
        out2 = batch.apply(str(manifest), "pi-sess-1", digest,
                           state_dir=self.state_dir, route_resolver=self._route_resolver,
                           client_factory=lambda _d: remote2)
        self.assertEqual(out2["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote2.calls))

        remote3 = FakeRemote()
        page1_rows = [
            {"id": f"u-{i}", "content": f"c-{i}", "observer_id": scope["peer_id"],
             "observed_id": scope["target_peer_id"], "session_id": scope["session_id"]}
            for i in range(batch.PAGE_SIZE)
        ]
        def unstable(args):
            if args["page"] == 1:
                return _mcp_text_result({
                    "conclusions": page1_rows,
                    "page": 1, "pages": 2, "total": batch.PAGE_SIZE + 1,
                })
            return _mcp_text_result({
                "conclusions": [{"id": "u-last", "content": "b", "observer_id": scope["peer_id"],
                                 "observed_id": scope["target_peer_id"], "session_id": scope["session_id"]}],
                "page": 2, "pages": 2, "total": batch.PAGE_SIZE + 2,
            })
        remote3.list_hook = unstable
        out3 = batch.apply(str(manifest), "pi-sess-1", digest,
                           state_dir=self.state_dir, route_resolver=self._route_resolver,
                           client_factory=lambda _d: remote3)
        self.assertEqual(out3["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote3.calls))

        remote4 = FakeRemote()
        dup_row = {"id": "dup-id", "content": "x", "observer_id": scope["peer_id"],
                   "observed_id": scope["target_peer_id"], "session_id": scope["session_id"]}
        p1_dup = [dup_row] + [
            {"id": f"p1-{i}", "content": f"x-{i}", "observer_id": scope["peer_id"],
             "observed_id": scope["target_peer_id"], "session_id": scope["session_id"]}
            for i in range(batch.PAGE_SIZE - 1)
        ]
        remote4.seed_pages(scope, [p1_dup, [dup_row]])
        out4 = batch.apply(str(manifest), "pi-sess-1", digest,
                           state_dir=self.state_dir, route_resolver=self._route_resolver,
                           client_factory=lambda _d: remote4)
        self.assertEqual(out4["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote4.calls))

    def test_later_page_exact_duplicate_and_substring_does_not_match(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        item = _make_item(checkout, grant, scope)
        manifest = self._manifest([item])
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]
        note = gateway.format_note(scope, item)

        remote_sub = FakeRemote()
        remote_sub.add_row(scope, "sub-1", f"prefix {note} suffix")
        out_sub = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_sub)
        self.assertEqual(out_sub["results"][0]["status"], "verified")
        self.assertEqual(sum(1 for name, _ in remote_sub.calls if name == "create_conclusions"), 1)

        remote_dup = FakeRemote()
        for idx in range(batch.PAGE_SIZE):
            remote_dup.add_row(scope, f"p1-{idx}", f"other note {idx}")
        remote_dup.add_row(scope, "p2", note)
        out_dup = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_dup)
        self.assertEqual(out_dup["results"][0]["status"], "already present")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_dup.calls))

    def test_ambiguous_append_recover_never_retry_and_persistence(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        item = _make_item(checkout, grant, scope, candidate="cand-1")
        manifest = self._manifest([item])
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]
        note = gateway.format_note(scope, item)

        remote_recover = FakeRemote()
        def store_then_fail(args):
            remote_recover.add_row(args, "stored-1", args["conclusions"][0])
            raise TimeoutError("connection reset after write")
        remote_recover.create_hook = store_then_fail
        out_rec = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_recover)
        self.assertEqual(out_rec["results"][0]["status"], "verified")
        self.assertEqual(self._pending_files(), [])

        remote_recover.calls.clear()
        out_rerun = batch.apply(str(manifest), "pi-sess-1", digest,
                                state_dir=self.state_dir, route_resolver=self._route_resolver,
                                client_factory=lambda _d: remote_recover)
        self.assertEqual(out_rerun["results"][0]["status"], "already present")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_recover.calls))

        state2 = self.root / "state2"
        remote_fail = FakeRemote()
        def fail_without_storing(_args):
            raise OSError("network dropped")
        remote_fail.create_hook = fail_without_storing
        out_fail = batch.apply(str(manifest), "pi-sess-1", digest,
                               state_dir=state2, route_resolver=self._route_resolver,
                               client_factory=lambda _d: remote_fail)
        self.assertEqual(out_fail["results"][0]["status"], "blocked")
        pending_list = [p.name for p in state2.iterdir() if p.name.endswith(".pending.json")]
        self.assertEqual(len(pending_list), 1)

        remote_fail.calls.clear()
        out_fail_rerun = batch.apply(str(manifest), "pi-sess-1", digest,
                                     state_dir=state2, route_resolver=self._route_resolver,
                                     client_factory=lambda _d: remote_fail)
        self.assertEqual(out_fail_rerun["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_fail.calls))

        scope_changed = _make_scope("repo-alpha", task="survey-2")
        grant_alias, _ = self._grant("alias", scope_changed, url="https://alias.example/mcp")
        item_changed = _make_item(checkout, grant_alias, scope_changed, candidate="cand-2")
        manifest_changed = self._manifest([item_changed], "changed.json")
        digest_changed = batch.preview(str(manifest_changed), "pi-sess-1",
                                       route_resolver=self._route_resolver)["digest"]
        note_changed = gateway.format_note(scope_changed, item_changed)
        remote_fail.add_row(scope_changed, "other-existing", note_changed)
        remote_fail.calls.clear()
        out_changed = batch.apply(str(manifest_changed), "pi-sess-1", digest_changed,
                                  state_dir=state2, route_resolver=self._route_resolver,
                                  client_factory=lambda _d: remote_fail)
        self.assertEqual(out_changed["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_fail.calls))
        self.assertEqual(len([p for p in state2.iterdir() if p.name.endswith(".pending.json")]), 1)

        remote_fail.add_row(scope, "delayed-1", note)
        remote_fail.calls.clear()
        out_recovered = batch.apply(str(manifest), "pi-sess-1", digest,
                                    state_dir=state2, route_resolver=self._route_resolver,
                                    client_factory=lambda _d: remote_fail)
        self.assertEqual(out_recovered["results"][0]["status"], "verified")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_fail.calls))
        self.assertEqual([p for p in state2.iterdir() if p.name.endswith(".pending.json")], [])

    def test_independent_repo_progress_and_sanitized_reasons(self):
        s1 = _make_scope("repo-alpha", session_id="sess-1")
        s2 = _make_scope("repo-beta", session_id="sess-2")
        c1 = self._checkout("repo-alpha", "repo-alpha")
        c2 = self._checkout("repo-beta", "repo-beta")
        g1, t1 = self._grant("alpha", s1, create_token=False)
        g2, _ = self._grant("beta", s2, token="SECRET_BETA_TOKEN")
        i1 = _make_item(c1, g1, s1, conclusion="Alpha secret note")
        i2 = _make_item(c2, g2, s2, conclusion="Beta note")
        manifest = self._manifest([i1, i2])

        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]
        remote = FakeRemote()

        def factory(desc):
            gateway.open_grant_client(desc)
            return remote

        out = batch.apply(str(manifest), "pi-sess-1", digest,
                          state_dir=self.state_dir, route_resolver=self._route_resolver,
                          client_factory=factory)
        self.assertEqual([r["repo"] for r in out["results"]], ["repo-alpha", "repo-beta"])
        self.assertEqual(out["results"][0]["status"], "blocked")
        self.assertEqual(out["results"][1]["status"], "verified")
        serialized = json.dumps(out)
        self.assertNotIn(str(t1), serialized)
        self.assertNotIn(str(g1), serialized)
        self.assertNotIn("SECRET_BETA_TOKEN", serialized)
        self.assertNotIn("Alpha secret note", serialized)

    def test_duplicate_workspace_session_across_different_targets_rejected_before_network(self):
        s1 = _make_scope("repo-alpha", session_id="shared-sess-1")
        s2 = _make_scope("repo-beta", session_id="shared-sess-1")
        self.assertNotEqual(batch._binding_key(s1), batch._binding_key(s2))
        c1 = self._checkout("repo-alpha", "repo-alpha")
        c2 = self._checkout("repo-beta", "repo-beta")
        g1, _ = self._grant("alpha", s1)
        g2, _ = self._grant("beta", s2)
        manifest = self._manifest([_make_item(c1, g1, s1), _make_item(c2, g2, s2)], "dup-session.json")

        with self.assertRaises(batch.BatchError):
            batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)

        calls = []
        with self.assertRaises(batch.BatchError):
            batch.apply(str(manifest), "pi-sess-1", "a" * 64,
                        state_dir=self.state_dir, route_resolver=self._route_resolver,
                        client_factory=lambda d: calls.append(d))
        self.assertEqual(calls, [])

    def test_state_dir_parent_sync_ordering_fault_and_no_symlink_following(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        manifest = self._manifest([_make_item(checkout, grant, scope)])
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        nested_state = self.root / "nested" / "sub" / "state"
        remote = FakeRemote()
        real_fsync = os.fsync
        synced_before_create = []

        def recording_fsync(fd):
            st = os.fstat(fd)
            if not any(name == "create_conclusions" for name, _ in remote.calls):
                synced_before_create.append((st.st_dev, st.st_ino))
            return real_fsync(fd)

        with mock.patch("os.fsync", side_effect=recording_fsync):
            out = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=nested_state, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote)
        self.assertEqual(out["results"][0]["status"], "verified")
        for path in (nested_state, nested_state.parent, nested_state.parent.parent, self.root):
            st = os.stat(path)
            self.assertIn((st.st_dev, st.st_ino), synced_before_create)
        self.assertEqual(os.stat(nested_state).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(nested_state.parent).st_mode & 0o777, 0o700)

        fault_state = self.root / "fault_a" / "fault_b" / "state"
        remote_fault = FakeRemote()

        def fail_on_parent_sync(fd):
            st = os.fstat(fd)
            fault_a = self.root / "fault_a"
            if fault_a.exists():
                ast = os.stat(fault_a)
                if (st.st_dev, st.st_ino) == (ast.st_dev, ast.st_ino):
                    raise OSError("simulated parent sync failure")
            return real_fsync(fd)

        with mock.patch("os.fsync", side_effect=fail_on_parent_sync):
            with self.assertRaises(batch.BatchError):
                batch.apply(str(manifest), "pi-sess-1", digest,
                            state_dir=fault_state, route_resolver=self._route_resolver,
                            client_factory=lambda _d: remote_fault)
        self.assertEqual(remote_fault.calls, [])

        real_target = self.root / "real_state"
        real_target.mkdir(mode=0o700)
        sym_state = self.root / "sym_state"
        sym_state.symlink_to(real_target)
        remote_sym = FakeRemote()
        with self.assertRaises(batch.BatchError):
            batch.apply(str(manifest), "pi-sess-1", digest,
                        state_dir=sym_state, route_resolver=self._route_resolver,
                        client_factory=lambda _d: remote_sym)
        self.assertEqual(remote_sym.calls, [])

    def test_symlink_ancestor_canonicalized_syncs_actual_parent_and_rejects_dangling(self):
        scope = _make_scope("repo-alpha")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        manifest = self._manifest([_make_item(checkout, grant, scope)], "sym-ancestor.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        real_fsync = os.fsync
        real_lstat = os.lstat

        real_parent = self.root / "real_private_parent"
        real_parent.mkdir(mode=0o700)
        real_state = real_parent / "state"
        real_state.mkdir(mode=0o700)
        sym_parent = self.root / "sym_parent"
        sym_parent.symlink_to(real_parent)

        remote_same_dev = FakeRemote()
        synced_same_dev = []

        def record_same_dev(fd):
            st = os.fstat(fd)
            if not any(name == "create_conclusions" for name, _ in remote_same_dev.calls):
                synced_same_dev.append((st.st_dev, st.st_ino))
            return real_fsync(fd)

        with mock.patch("os.fsync", side_effect=record_same_dev):
            out = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=sym_parent / "state", route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_same_dev)
        self.assertEqual(out["results"][0]["status"], "verified")
        for path in (real_state, real_parent, self.root):
            st = os.stat(path)
            self.assertIn((st.st_dev, st.st_ino), synced_same_dev)

        real_parent2 = self.root / "real_private_parent2"
        real_parent2.mkdir(mode=0o700)
        real_state2 = real_parent2 / "state"
        real_state2.mkdir(mode=0o700)
        sym_parent2 = self.root / "sym_parent2"
        sym_parent2.symlink_to(real_parent2)
        real_dev = os.stat(real_parent2).st_dev

        remote_diff_dev = FakeRemote()
        synced_diff_dev = []

        def fake_lstat(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            if not args and not kwargs and Path(path) == sym_parent2:
                return os.stat_result((
                    st.st_mode, st.st_ino, real_dev + 1, st.st_nlink,
                    st.st_uid, st.st_gid, st.st_size,
                    st.st_atime, st.st_mtime, st.st_ctime,
                ))
            return st

        def record_diff_dev(fd):
            st = os.fstat(fd)
            if not any(name == "create_conclusions" for name, _ in remote_diff_dev.calls):
                synced_diff_dev.append((st.st_dev, st.st_ino))
            return real_fsync(fd)

        with mock.patch("os.lstat", side_effect=fake_lstat), \
                mock.patch("os.fsync", side_effect=record_diff_dev):
            out2 = batch.apply(str(manifest), "pi-sess-1", digest,
                               state_dir=sym_parent2 / "state", route_resolver=self._route_resolver,
                               client_factory=lambda _d: remote_diff_dev)
        self.assertEqual(out2["results"][0]["status"], "verified")
        for path in (real_state2, real_parent2):
            st = os.stat(path)
            self.assertIn((st.st_dev, st.st_ino), synced_diff_dev)

        real_parent3 = self.root / "real_private_parent3"
        real_parent3.mkdir(mode=0o700)
        sym_parent3 = self.root / "sym_parent3"
        sym_parent3.symlink_to(real_parent3)
        nested_via_sym = sym_parent3 / "sub" / "state"
        remote_nested = FakeRemote()
        synced_nested = []

        def record_nested(fd):
            st = os.fstat(fd)
            if not any(name == "create_conclusions" for name, _ in remote_nested.calls):
                synced_nested.append((st.st_dev, st.st_ino))
            return real_fsync(fd)

        with mock.patch("os.fsync", side_effect=record_nested):
            out3 = batch.apply(str(manifest), "pi-sess-1", digest,
                               state_dir=nested_via_sym, route_resolver=self._route_resolver,
                               client_factory=lambda _d: remote_nested)
        self.assertEqual(out3["results"][0]["status"], "verified")
        for path in (real_parent3 / "sub" / "state", real_parent3 / "sub", real_parent3, self.root):
            st = os.stat(path)
            self.assertIn((st.st_dev, st.st_ino), synced_nested)

        dangling_parent = self.root / "dangling_parent"
        dangling_parent.symlink_to(self.root / "nonexistent_target")
        remote_dangling = FakeRemote()
        with self.assertRaises(batch.BatchError):
            batch.apply(str(manifest), "pi-sess-1", digest,
                        state_dir=dangling_parent / "state", route_resolver=self._route_resolver,
                        client_factory=lambda _d: remote_dangling)
        self.assertEqual(remote_dangling.calls, [])

    def test_corrupted_or_unreadable_pending_marker_blocks_without_fd_leak_and_continues(self):
        s1 = _make_scope("repo-alpha", session_id="sess-pend-1")
        s2 = _make_scope("repo-beta", session_id="sess-pend-2")
        c1 = self._checkout("repo-alpha", "repo-alpha")
        c2 = self._checkout("repo-beta", "repo-beta")
        g1, _ = self._grant("alpha", s1)
        g2, _ = self._grant("beta", s2)
        manifest = self._manifest([_make_item(c1, g1, s1), _make_item(c2, g2, s2)], "pending-dir.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        pending1_name = f"{batch._binding_key(s1)}.pending.json"
        state_dir_marker = self.root / "state_dir_marker"
        fd = batch.open_state_dir(state_dir_marker)
        os.close(fd)
        marker_dir = state_dir_marker / pending1_name
        marker_dir.mkdir(mode=0o700)
        marker_sentinel = marker_dir / "keep"
        marker_sentinel.write_text("preserved", encoding="utf-8")

        remote_dir = FakeRemote()
        out_dir = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=state_dir_marker, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_dir)
        self.assertEqual([r["repo"] for r in out_dir["results"]], ["repo-alpha", "repo-beta"])
        self.assertEqual(out_dir["results"][0]["status"], "blocked")
        self.assertEqual(out_dir["results"][1]["status"], "verified")
        self.assertFalse(any(args["target_peer_id"] == "repo-alpha" and name == "create_conclusions"
                             for name, args in remote_dir.calls))
        self.assertEqual(sum(1 for name, args in remote_dir.calls
                             if name == "create_conclusions" and args["target_peer_id"] == "repo-beta"), 1)
        self.assertTrue(marker_dir.is_dir())
        self.assertEqual(marker_sentinel.read_text(encoding="utf-8"), "preserved")
        self.assertNotIn(str(state_dir_marker), json.dumps(out_dir))

        real_open = os.open
        real_fstat = os.fstat
        real_fdopen = os.fdopen
        marker_bytes = b'{"version":1}'

        for mode in ("fstat", "fdopen", "read"):
            state_fail = self.root / f"state_fail_{mode}"
            sfd = batch.open_state_dir(state_fail)
            try:
                marker_file = _write_private(state_fail / pending1_name, marker_bytes.decode("utf-8"))
                captured_fds = []

                def tracking_open(path, *args, **kwargs):
                    opened = real_open(path, *args, **kwargs)
                    if path == pending1_name:
                        captured_fds.append(opened)
                    return opened

                def failing_fstat(target_fd):
                    if mode == "fstat" and target_fd in captured_fds:
                        raise OSError("simulated fstat failure")
                    return real_fstat(target_fd)

                def failing_fdopen(target_fd, *args, **kwargs):
                    if target_fd in captured_fds:
                        if mode == "fdopen":
                            raise OSError("simulated fdopen failure")
                        if mode == "read":
                            real_stream = real_fdopen(target_fd, *args, **kwargs)

                            class ReadFailingStream:
                                def fileno(self):
                                    return real_stream.fileno()

                                def read(self, *_a, **_kw):
                                    raise IsADirectoryError("simulated read failure")

                                def close(self):
                                    real_stream.close()

                            return ReadFailingStream()
                    return real_fdopen(target_fd, *args, **kwargs)

                with mock.patch("os.open", side_effect=tracking_open), \
                        mock.patch("os.fstat", side_effect=failing_fstat), \
                        mock.patch("os.fdopen", side_effect=failing_fdopen):
                    with self.assertRaises(batch.BatchError) as err_cm:
                        batch._read_pending_marker(sfd, pending1_name, gateway.bound_scope(s1))
                self.assertEqual(len(captured_fds), 1)
                with self.assertRaises(OSError) as cm:
                    real_fstat(captured_fds[0])
                self.assertEqual(cm.exception.errno, errno.EBADF)
                self.assertEqual(str(err_cm.exception), "unreadable pending marker")
                self.assertEqual(marker_file.read_bytes(), marker_bytes)
            finally:
                os.close(sfd)

    def test_deeply_nested_pending_marker_and_upstream_json_block_per_item(self):
        nested_json = ("[" * 1500) + ("]" * 1500)
        self.assertLessEqual(len(nested_json.encode("utf-8")), batch.MAX_PENDING_BYTES)

        s1 = _make_scope("repo-alpha", session_id="sess-nest-1")
        s2 = _make_scope("repo-beta", session_id="sess-nest-2")
        c1 = self._checkout("repo-alpha", "repo-alpha")
        c2 = self._checkout("repo-beta", "repo-beta")
        g1, _ = self._grant("alpha", s1)
        g2, _ = self._grant("beta", s2)
        manifest = self._manifest([_make_item(c1, g1, s1), _make_item(c2, g2, s2)], "nested-marker.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        pending1_name = f"{batch._binding_key(s1)}.pending.json"
        sfd = batch.open_state_dir(self.state_dir)
        os.close(sfd)
        marker_file = _write_private(self.state_dir / pending1_name, nested_json)

        remote = FakeRemote()
        real_parse = gateway.parse_json_unique

        def recursion_fault(text):
            if text == nested_json:
                raise RecursionError("synthetic decoder recursion")
            return real_parse(text)

        with mock.patch.object(gateway, "parse_json_unique", side_effect=recursion_fault):
            out = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote)
        self.assertEqual([r["repo"] for r in out["results"]], ["repo-alpha", "repo-beta"])
        self.assertEqual(out["results"][0]["status"], "blocked")
        self.assertEqual(out["results"][0]["reason"], "malformed pending marker")
        self.assertEqual(out["results"][1]["status"], "verified")
        self.assertFalse(any(args["target_peer_id"] == "repo-alpha" and name == "create_conclusions"
                             for name, args in remote.calls))
        self.assertEqual(sum(1 for name, args in remote.calls
                             if name == "create_conclusions" and args["target_peer_id"] == "repo-beta"), 1)
        self.assertTrue(marker_file.is_file())
        self.assertEqual(marker_file.read_text(encoding="utf-8"), nested_json)
        self.assertEqual(os.stat(marker_file).st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.state_dir), json.dumps(out))

        state_upstream = self.root / "state_nested_upstream"
        remote_upstream = FakeRemote()

        def nested_upstream_hook(args):
            if args["target_peer_id"] == "repo-alpha":
                return {"content": [{"type": "text", "text": nested_json}]}
            return None

        remote_upstream.list_hook = nested_upstream_hook
        with mock.patch.object(gateway, "parse_json_unique", side_effect=recursion_fault):
            out_upstream = batch.apply(str(manifest), "pi-sess-1", digest,
                                       state_dir=state_upstream, route_resolver=self._route_resolver,
                                       client_factory=lambda _d: remote_upstream)
        self.assertEqual([r["repo"] for r in out_upstream["results"]], ["repo-alpha", "repo-beta"])
        self.assertEqual(out_upstream["results"][0]["status"], "blocked")
        self.assertEqual(out_upstream["results"][0]["reason"], "pre-read failed or unproven")
        self.assertEqual(out_upstream["results"][1]["status"], "verified")
        self.assertFalse(any(args["target_peer_id"] == "repo-alpha" and name == "create_conclusions"
                             for name, args in remote_upstream.calls))
        self.assertEqual(sum(1 for name, args in remote_upstream.calls
                             if name == "create_conclusions" and args["target_peer_id"] == "repo-beta"), 1)

    def test_write_pending_marker_fdopen_and_stream_failures_close_once_and_clean_temp(self):
        scope = _make_scope("repo-alpha", session_id="sess-write-fault-1")
        bound = gateway.bound_scope(scope)
        pending_name = f"{batch._binding_key(scope)}.pending.json"
        note_sha256 = hashlib.sha256(b"note").hexdigest()

        real_open = os.open
        real_fstat = os.fstat
        real_fdopen = os.fdopen
        real_close = os.close
        real_fsync = os.fsync

        for mode in ("fdopen", "write", "fsync"):
            state_dir = self.root / f"state_write_fail_{mode}"
            sfd = batch.open_state_dir(state_dir)
            try:
                captured_fds = []
                closed_raw_fds = []

                def tracking_open(path, *args, **kwargs):
                    opened = real_open(path, *args, **kwargs)
                    if isinstance(path, str) and path.startswith(f"{pending_name}.tmp."):
                        captured_fds.append(opened)
                    return opened

                def tracking_close(target_fd):
                    if target_fd in captured_fds:
                        closed_raw_fds.append(target_fd)
                    return real_close(target_fd)

                def failing_fdopen(target_fd, *args, **kwargs):
                    if target_fd in captured_fds:
                        if mode == "fdopen":
                            raise OSError("simulated fdopen failure")
                        if mode == "write":
                            real_stream = real_fdopen(target_fd, *args, **kwargs)

                            class WriteFailingStream:
                                def __enter__(self):
                                    return self

                                def __exit__(self, exc_type, exc, tb):
                                    self.close()
                                    return False

                                def fileno(self):
                                    return real_stream.fileno()

                                def write(self, *_a, **_kw):
                                    raise OSError("simulated write failure")

                                def flush(self):
                                    real_stream.flush()

                                def close(self):
                                    real_stream.close()

                            return WriteFailingStream()
                    return real_fdopen(target_fd, *args, **kwargs)

                def failing_fsync(target_fd):
                    if mode == "fsync" and target_fd in captured_fds:
                        raise OSError("simulated fsync failure")
                    return real_fsync(target_fd)

                with mock.patch("os.open", side_effect=tracking_open), \
                        mock.patch("os.fdopen", side_effect=failing_fdopen), \
                        mock.patch("os.fsync", side_effect=failing_fsync), \
                        mock.patch("os.close", side_effect=tracking_close):
                    with self.assertRaises(batch.BatchError) as err_cm:
                        batch._write_pending_marker(sfd, pending_name, bound, note_sha256)

                self.assertEqual(len(captured_fds), 1)
                with self.assertRaises(OSError) as fstat_cm:
                    real_fstat(captured_fds[0])
                self.assertEqual(fstat_cm.exception.errno, errno.EBADF)
                if mode == "fdopen":
                    self.assertEqual(closed_raw_fds, [captured_fds[0]])
                else:
                    self.assertEqual(closed_raw_fds, [])
                self.assertEqual(str(err_cm.exception), "unable to persist pending marker")
                self.assertEqual(list(state_dir.iterdir()), [])
            finally:
                real_close(sfd)

        ok_state = self.root / "state_write_ok"
        ok_sfd = batch.open_state_dir(ok_state)
        try:
            fsynced_fds = []
            temp_fds = []

            def rec_open(path, *args, **kwargs):
                opened = real_open(path, *args, **kwargs)
                if isinstance(path, str) and path.startswith(f"{pending_name}.tmp."):
                    temp_fds.append(opened)
                return opened

            def rec_fsync(target_fd):
                fsynced_fds.append(target_fd)
                return real_fsync(target_fd)

            with mock.patch("os.open", side_effect=rec_open), \
                    mock.patch("os.fsync", side_effect=rec_fsync):
                batch._write_pending_marker(ok_sfd, pending_name, bound, note_sha256)
            self.assertEqual(len(temp_fds), 1)
            self.assertEqual(fsynced_fds, [temp_fds[0], ok_sfd])
            self.assertEqual([p.name for p in ok_state.iterdir()], [pending_name])
        finally:
            real_close(ok_sfd)

    def test_nonblocking_flock_contention_and_lock_failure_preserve_first_writer_and_continue(self):
        s1 = _make_scope("repo-alpha", session_id="sess-lock-1")
        s2 = _make_scope("repo-beta", session_id="sess-lock-2")
        c1 = self._checkout("repo-alpha", "repo-alpha")
        c2 = self._checkout("repo-beta", "repo-beta")
        g1, _ = self._grant("alpha", s1)
        g2, _ = self._grant("beta", s2)
        manifest = self._manifest([_make_item(c1, g1, s1), _make_item(c2, g2, s2)], "lock-test.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        fd = batch.open_state_dir(self.state_dir)
        os.close(fd)
        lock_path = self.state_dir / f"{batch._binding_key(s1)}.lock"
        holder_script = (
            "import fcntl, os, sys; "
            "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600); "
            "fcntl.flock(fd, fcntl.LOCK_EX); "
            "print('LOCKED', flush=True); "
            "sys.stdin.read()"
        )
        proc = subprocess.Popen(
            ["/usr/bin/python3", "-I", "-B", "-c", holder_script, str(lock_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        try:
            deadline = time.monotonic() + 5.0
            ready_chunks = []
            timed_out = False
            while True:
                remaining = deadline - time.monotonic()
                readable = []
                if remaining > 0:
                    readable, _, _ = select.select([proc.stdout], [], [], remaining)
                if not readable:
                    timed_out = True
                    break
                chunk = os.read(proc.stdout.fileno(), 64)
                if not chunk:
                    break
                ready_chunks.append(chunk)
                if b"\n" in chunk:
                    break
            ready = b"".join(ready_chunks).decode("utf-8", errors="replace").strip()
            if timed_out or ready != "LOCKED":
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                err = ""
                if proc.stderr is not None and select.select([proc.stderr], [], [], 0.2)[0]:
                    err = os.read(proc.stderr.fileno(), 4096).decode("utf-8", errors="replace")
                reason = "timed out waiting for LOCKED" if timed_out else f"failed to lock (got {ready!r})"
                self.fail(f"lock holder {reason}: {err}")
            remote = FakeRemote()
            out = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote)
            self.assertEqual(out["results"][0]["repo"], "repo-alpha")
            self.assertEqual(out["results"][0]["status"], "blocked")
            self.assertEqual(out["results"][1]["repo"], "repo-beta")
            self.assertEqual(out["results"][1]["status"], "verified")
            alpha_calls = [args for _, args in remote.calls if args["target_peer_id"] == "repo-alpha"]
            self.assertEqual(alpha_calls, [])
        finally:
            try:
                if proc.stdin is not None and not proc.stdin.closed:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            finally:
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe is not None and not pipe.closed:
                        try:
                            pipe.close()
                        except OSError:
                            pass
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)

        bad_state = self.root / "bad_lock_state"
        bfd = batch.open_state_dir(bad_state)
        os.close(bfd)
        (bad_state / f"{batch._binding_key(s1)}.lock").symlink_to(self.root / "nonexistent")
        remote2 = FakeRemote()
        out2 = batch.apply(str(manifest), "pi-sess-1", digest,
                           state_dir=bad_state, route_resolver=self._route_resolver,
                           client_factory=lambda _d: remote2)
        self.assertEqual(out2["results"][0]["status"], "blocked")
        self.assertEqual(out2["results"][1]["status"], "verified")

    def test_capacity_limit_duplicate_absent_and_just_below(self):
        scope = _make_scope("repo-alpha", session_id="sess-cap-1")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        item = _make_item(checkout, grant, scope)
        manifest = self._manifest([item], "cap.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]
        note = gateway.format_note(scope, item)

        remote_full_absent = FakeRemote()
        for idx in range(batch.MAX_TOTAL_CONCLUSIONS):
            remote_full_absent.add_row(scope, f"f-{idx}", f"existing note {idx}")
        out_absent = batch.apply(str(manifest), "pi-sess-1", digest,
                                 state_dir=self.state_dir, route_resolver=self._route_resolver,
                                 client_factory=lambda _d: remote_full_absent)
        self.assertEqual(out_absent["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_full_absent.calls))
        self.assertEqual(self._pending_files(), [])

        remote_full_dup = FakeRemote()
        for idx in range(batch.MAX_TOTAL_CONCLUSIONS - 1):
            remote_full_dup.add_row(scope, f"d-{idx}", f"existing note {idx}")
        remote_full_dup.add_row(scope, "d-last", note)
        out_dup = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote_full_dup)
        self.assertEqual(out_dup["results"][0]["status"], "already present")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_full_dup.calls))
        self.assertEqual(self._pending_files(), [])

        remote_just_below = FakeRemote()
        for idx in range(batch.MAX_TOTAL_CONCLUSIONS - 1):
            remote_just_below.add_row(scope, f"b-{idx}", f"existing note {idx}")
        out_ok = batch.apply(str(manifest), "pi-sess-1", digest,
                             state_dir=self.state_dir, route_resolver=self._route_resolver,
                             client_factory=lambda _d: remote_just_below)
        self.assertEqual(out_ok["results"][0]["status"], "verified")
        self.assertEqual(sum(1 for name, _ in remote_just_below.calls if name == "create_conclusions"), 1)
        self.assertEqual(self._pending_files(), [])

    def test_inconsistent_pagination_and_malformed_oversized_envelope_block(self):
        scope = _make_scope("repo-alpha", session_id="sess-pag-1")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope)
        manifest = self._manifest([_make_item(checkout, grant, scope)], "pag.json")
        digest = batch.preview(str(manifest), "pi-sess-1", route_resolver=self._route_resolver)["digest"]

        valid_row = lambda idx: {
            "id": f"r-{idx}", "content": f"note {idx}",
            "observer_id": scope["peer_id"],
            "observed_id": scope["target_peer_id"],
            "session_id": scope["session_id"],
        }

        bad_responses = [
            _mcp_text_result({"conclusions": [valid_row(i) for i in range(batch.PAGE_SIZE)],
                              "page": 1, "pages": 1, "total": batch.PAGE_SIZE + 1}),
            _mcp_text_result({"conclusions": [valid_row(i) for i in range(10)],
                              "page": 1, "pages": 2, "total": batch.PAGE_SIZE + 1}),
            {"content": []},
            {"content": [{"type": "image", "text": "{}"}]},
            {"content": [{"type": "text", "text": "x" * (batch.MAX_READBACK_TEXT + 1)}]},
        ]
        for bad_resp in bad_responses:
            remote = FakeRemote()
            remote.list_hook = lambda _args, resp=bad_resp: resp
            out = batch.apply(str(manifest), "pi-sess-1", digest,
                              state_dir=self.state_dir, route_resolver=self._route_resolver,
                              client_factory=lambda _d: remote)
            self.assertEqual(out["results"][0]["status"], "blocked")
            self.assertFalse(any(name == "create_conclusions" for name, _ in remote.calls))

        remote_tail = FakeRemote()
        def bad_tail_length(args):
            if args["page"] == 1:
                return _mcp_text_result({
                    "conclusions": [valid_row(i) for i in range(batch.PAGE_SIZE)],
                    "page": 1, "pages": 2, "total": batch.PAGE_SIZE + 1,
                })
            return _mcp_text_result({
                "conclusions": [valid_row(100), valid_row(101)],
                "page": 2, "pages": 2, "total": batch.PAGE_SIZE + 1,
            })
        remote_tail.list_hook = bad_tail_length
        out_tail = batch.apply(str(manifest), "pi-sess-1", digest,
                               state_dir=self.state_dir, route_resolver=self._route_resolver,
                               client_factory=lambda _d: remote_tail)
        self.assertEqual(out_tail["results"][0]["status"], "blocked")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote_tail.calls))


class BatchCLISubprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.private = self.home / "private"
        self.private.mkdir(mode=0o700)
        self.state = self.home / "state"
        self.remote = FakeRemote()
        self.server = LoopbackMCPServer(self.remote)
        self.addCleanup(self.server.close)

    def _git(self, cwd, *args):
        subprocess.run(
            ["/usr/bin/git", *args],
            cwd=str(cwd),
            env={"HOME": str(self.home), "PATH": "/usr/bin", "LC_ALL": "C",
                 "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.com"},
            check=True,
            capture_output=True,
            text=True,
        )

    def _run_cli(self, *args):
        return subprocess.run(
            ["/usr/bin/python3", "-I", "-B", str(BATCH_PATH), *args],
            env={"HOME": str(self.home), "XDG_STATE_HOME": str(self.state), "PATH": "/usr/bin"},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_isolated_worktree_preview_and_apply(self):
        main_repo = self.home / "dotfiles"
        main_repo.mkdir()
        self._git(main_repo, "init")
        (main_repo / "README.md").write_text("hi\n", encoding="utf-8")
        self._git(main_repo, "add", "README.md")
        self._git(main_repo, "commit", "-m", "init")

        wt_dir = self.home / "code" / ".worktrees" / "dotfiles-wt"
        wt_dir.parent.mkdir(parents=True)
        self._git(main_repo, "worktree", "add", "-b", "wt-branch", str(wt_dir))

        scope = _make_scope("dotfiles", session_id="sess-dotfiles-1")
        token_path = _write_private(self.private / "dotfiles.token", "loopback-token-xyz\n")
        grant_path = _write_private(self.private / "dotfiles.grant.json", json.dumps({
            "url": self.server.url,
            "token_file": str(token_path),
            "scope": scope,
        }))
        manifest_path = _write_private(self.private / "manifest.json", json.dumps({
            "items": [_make_item(wt_dir, grant_path, scope)]
        }))

        prev_proc = self._run_cli("preview", str(manifest_path), "pi-cli-1")
        self.assertEqual(prev_proc.returncode, 0, prev_proc.stderr)
        prev_data = json.loads(prev_proc.stdout)
        self.assertEqual(self.server.requests, [])
        self.assertIn("target_peer_id=dotfiles", prev_data["preview"])
        self.assertNotIn(str(token_path), prev_data["preview"])

        bad_apply = self._run_cli("apply", str(manifest_path), "pi-cli-1", "0" * 64)
        self.assertNotEqual(bad_apply.returncode, 0)
        self.assertEqual(self.server.requests, [])
        self.assertNotIn("Traceback", bad_apply.stderr)
        self.assertNotIn(str(manifest_path), bad_apply.stderr)

        ok_apply = self._run_cli("apply", str(manifest_path), "pi-cli-1", prev_data["digest"])
        self.assertEqual(ok_apply.returncode, 0, ok_apply.stderr)
        apply_data = json.loads(ok_apply.stdout)
        self.assertEqual(apply_data["digest"], prev_data["digest"])
        self.assertEqual(apply_data["results"][0]["repo"], "dotfiles")
        self.assertEqual(apply_data["results"][0]["status"], "verified")

        subdir = wt_dir / "sub"
        subdir.mkdir()
        sub_manifest = _write_private(self.private / "sub.json", json.dumps({
            "items": [_make_item(subdir, grant_path, scope)]
        }))
        sub_proc = self._run_cli("preview", str(sub_manifest), "pi-cli-1")
        self.assertNotEqual(sub_proc.returncode, 0)
        self.assertNotIn(str(subdir), sub_proc.stderr)


class CapacityLimitedMCPServer:
    def __init__(self, remote, *, max_active_sessions=1, expected_workspace="hermes-personal",
                 valid_tokens=None, stateless=False):
        self.remote = remote
        self.max_active_sessions = max_active_sessions
        self.expected_workspace = expected_workspace
        self.valid_tokens = set(valid_tokens or [])
        self.stateless = stateless
        self.lock = threading.Lock()
        self.next_session_num = 0
        self.active_sessions = {}
        self.post_requests = []
        self.delete_requests = []
        self.pre_init_response = None
        self.tool_http_error_hook = None
        self.delete_status = 200
        self.delete_delay = 0.0
        self.delete_completed = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send_raw(self, status, body, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                auth = self.headers.get("Authorization")
                workspace = self.headers.get("X-Honcho-Workspace-ID")
                sid = self.headers.get("Mcp-Session-Id")
                proto = self.headers.get("MCP-Protocol-Version")
                method = body.get("method")
                with outer.lock:
                    outer.post_requests.append({
                        "method": method,
                        "auth": auth,
                        "workspace": workspace,
                        "session_id": sid,
                        "protocol": proto,
                    })

                expected_auth_ok = (
                    isinstance(auth, str)
                    and auth.startswith("Bearer ")
                    and (not outer.valid_tokens or auth[7:] in outer.valid_tokens)
                )
                if not expected_auth_ok or workspace != outer.expected_workspace:
                    self._send_raw(403, b"forbidden")
                    return

                if method == "initialize":
                    if outer.pre_init_response is not None:
                        status, err_body = outer.pre_init_response
                        self._send_raw(status, err_body)
                        return
                    with outer.lock:
                        if len(outer.active_sessions) >= outer.max_active_sessions:
                            self._send_raw(503, b'{"error":"too many active sessions"}')
                            return
                        issued_sid = None
                        if not outer.stateless:
                            outer.next_session_num += 1
                            issued_sid = f"cap-sess-{outer.next_session_num}"
                            outer.active_sessions[issued_sid] = {
                                "auth": auth,
                                "workspace": workspace,
                                "protocol": "2025-03-26",
                            }
                    payload = json.dumps({
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
                    }).encode("utf-8")
                    self.send_response(200)
                    if issued_sid is not None:
                        self.send_header("Mcp-Session-Id", issued_sid)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if not outer.stateless:
                    with outer.lock:
                        session = outer.active_sessions.get(sid)
                    if (session is None or session["auth"] != auth
                            or session["workspace"] != workspace
                            or session["protocol"] != proto):
                        self._send_raw(403, b"invalid session")
                        return

                if method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return

                if method == "tools/call":
                    params = body["params"]
                    if outer.tool_http_error_hook is not None:
                        err = outer.tool_http_error_hook(params["name"], params["arguments"])
                        if err is not None:
                            self._send_raw(err[0], err[1])
                            return
                    result = outer.remote.call(params["name"], params["arguments"])
                else:
                    result = {}

                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode("utf-8")
                self._send_raw(200, payload)

            def do_DELETE(self):
                auth = self.headers.get("Authorization")
                workspace = self.headers.get("X-Honcho-Workspace-ID")
                sid = self.headers.get("Mcp-Session-Id")
                proto = self.headers.get("MCP-Protocol-Version")
                delay = outer.delete_delay
                if delay > 0:
                    time.sleep(delay)
                try:
                    with outer.lock:
                        outer.delete_requests.append({
                            "auth": auth,
                            "workspace": workspace,
                            "session_id": sid,
                            "protocol": proto,
                        })
                        session = outer.active_sessions.get(sid)
                        valid = (
                            session is not None
                            and session["auth"] == auth
                            and session["workspace"] == workspace
                            and session["protocol"] == proto
                        )
                        if valid and outer.delete_status in (200, 202, 204):
                            del outer.active_sessions[sid]
                    try:
                        if outer.delete_status not in (200, 202, 204):
                            self._send_raw(outer.delete_status, b"delete status")
                            return
                        if not valid:
                            self._send_raw(404, b"unknown session")
                            return
                        self._send_raw(outer.delete_status, b"")
                    except (BrokenPipeError, ConnectionResetError):
                        if delay <= 0:
                            raise
                finally:
                    outer.delete_completed.set()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class BatchCapacityAndCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.state_dir = self.root / "state"
        self.checkouts = self.root / "checkouts"
        self.checkouts.mkdir()
        self.routes = {}

    def _checkout(self, name, route):
        path = self.checkouts / name
        path.mkdir(parents=True, exist_ok=True)
        self.routes[str(path)] = route
        return path

    def _route_resolver(self, checkout):
        return self.routes[checkout]

    def _grant(self, name, scope, url, token):
        token_path = _write_private(self.private / f"{name}.token", token + "\n")
        grant_path = _write_private(self.private / f"{name}.grant.json", json.dumps({
            "url": url,
            "token_file": str(token_path),
            "scope": dict(scope),
        }))
        return grant_path, token_path

    def _manifest(self, items, name="manifest.json"):
        path = self.private / name
        _write_private(path, json.dumps({"items": items}))
        return path

    def _pending_files(self):
        if not self.state_dir.exists():
            return []
        return sorted(p.name for p in self.state_dir.iterdir() if p.name.endswith(".pending.json"))

    def test_capacity_limited_server_enforces_single_session_across_sequential_batch(self):
        remote = FakeRemote()
        tokens = [f"tok-repo-{idx}" for idx in range(5)]
        server = CapacityLimitedMCPServer(remote, max_active_sessions=1, valid_tokens=tokens)
        self.addCleanup(server.close)

        items = []
        for idx in range(5):
            repo = f"repo-{idx}"
            scope = _make_scope(repo, session_id=f"sess-{idx}", task=f"task-{idx}")
            checkout = self._checkout(repo, repo)
            grant, _ = self._grant(repo, scope, server.url, tokens[idx])
            item = _make_item(checkout, grant, scope, conclusion=f"Verified {repo}.")
            items.append(item)
            if idx == 1:
                remote.add_row(scope, "existing-1", gateway.format_note(scope, item))

        def fail_repo2_readback(args):
            if args["target_peer_id"] == "repo-2":
                return {"content": [{"type": "text", "text": "{bad"}]}
            return None

        remote.list_hook = fail_repo2_readback
        manifest = self._manifest(items)
        digest = batch.preview(str(manifest), "pi-sess-cap", route_resolver=self._route_resolver)["digest"]

        out = batch.apply(
            str(manifest),
            "pi-sess-cap",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        statuses = [(r["repo"], r["status"]) for r in out["results"]]
        self.assertEqual(statuses, [
            ("repo-0", "verified"),
            ("repo-1", "already present"),
            ("repo-2", "blocked"),
            ("repo-3", "verified"),
            ("repo-4", "verified"),
        ])
        self.assertEqual(server.active_sessions, {})
        self.assertEqual(len(server.delete_requests), 5)
        for idx, delete_req in enumerate(server.delete_requests):
            self.assertEqual(delete_req["auth"], f"Bearer {tokens[idx]}")
            self.assertEqual(delete_req["workspace"], batch.REQUIRED_WORKSPACE)
            self.assertEqual(delete_req["protocol"], "2025-03-26")
            self.assertTrue(delete_req["session_id"].startswith("cap-sess-"))
        self.assertEqual(len({req["session_id"] for req in server.delete_requests}), 5)
        serialized = json.dumps(out)
        for token in tokens:
            self.assertNotIn(token, serialized)

    def test_capacity_503_generic_503_and_429_block_before_append_without_retry(self):
        remote = FakeRemote()
        server = CapacityLimitedMCPServer(remote, max_active_sessions=1, valid_tokens={"tok-a"})
        self.addCleanup(server.close)

        scope = _make_scope("repo-alpha", session_id="sess-cap-err")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, token_path = self._grant("alpha", scope, server.url, "tok-a")
        manifest = self._manifest([_make_item(checkout, grant, scope)])
        digest = batch.preview(str(manifest), "pi-sess-err", route_resolver=self._route_resolver)["digest"]

        with server.lock:
            server.active_sessions["held-elsewhere"] = {
                "auth": "Bearer other",
                "workspace": batch.REQUIRED_WORKSPACE,
                "protocol": "2025-03-26",
            }
        out_cap = batch.apply(
            str(manifest),
            "pi-sess-err",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_cap["results"][0]["status"], "blocked")
        self.assertIn("too many active sessions", out_cap["results"][0]["reason"])
        self.assertIn("503", out_cap["results"][0]["reason"])
        self.assertEqual(len(server.post_requests), 1)
        self.assertEqual(server.delete_requests, [])
        self.assertEqual(remote.calls, [])
        self.assertEqual(self._pending_files(), [])

        with server.lock:
            server.active_sessions.clear()
        server.post_requests.clear()
        server.pre_init_response = (503, b"RAW_GATEWAY_503_BODY /secret/path")
        out_503 = batch.apply(
            str(manifest),
            "pi-sess-err",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_503["results"][0]["status"], "blocked")
        self.assertIn("503", out_503["results"][0]["reason"])
        self.assertNotIn("too many active sessions", out_503["results"][0]["reason"])
        serialized_503 = json.dumps(out_503)
        self.assertNotIn("RAW_GATEWAY_503_BODY", serialized_503)
        self.assertNotIn("/secret/path", serialized_503)
        self.assertNotIn(str(token_path), serialized_503)
        self.assertEqual(len(server.post_requests), 1)
        self.assertEqual(self._pending_files(), [])

        server.post_requests.clear()
        server.pre_init_response = (429, b"RAW_RATE_LIMIT_BODY secret-quota")
        out_429 = batch.apply(
            str(manifest),
            "pi-sess-err",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_429["results"][0]["status"], "blocked")
        self.assertIn("429", out_429["results"][0]["reason"])
        serialized_429 = json.dumps(out_429)
        self.assertNotIn("RAW_RATE_LIMIT_BODY", serialized_429)
        self.assertNotIn("secret-quota", serialized_429)
        self.assertEqual(len(server.post_requests), 1)
        self.assertEqual(self._pending_files(), [])

    def test_ambiguous_503_retains_pending_marker_cleans_session_and_never_retries(self):
        remote = FakeRemote()
        server = CapacityLimitedMCPServer(remote, max_active_sessions=1, valid_tokens={"tok-amb"})
        self.addCleanup(server.close)

        scope = _make_scope("repo-alpha", session_id="sess-amb-503")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha", scope, server.url, "tok-amb")
        item = _make_item(checkout, grant, scope)
        manifest = self._manifest([item])
        digest = batch.preview(str(manifest), "pi-sess-amb", route_resolver=self._route_resolver)["digest"]

        def fail_create_with_503(name, _args):
            if name == "create_conclusions":
                return (503, b"too many active sessions")
            return None

        server.tool_http_error_hook = fail_create_with_503
        out1 = batch.apply(
            str(manifest),
            "pi-sess-amb",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out1["results"][0]["status"], "blocked")
        self.assertIn("too many active sessions", out1["results"][0]["reason"])
        self.assertIn("pending marker retained", out1["results"][0]["reason"])
        self.assertEqual(len(self._pending_files()), 1)
        self.assertEqual(server.active_sessions, {})
        self.assertEqual(len(server.delete_requests), 1)

        server.tool_http_error_hook = None
        remote.calls.clear()
        out2 = batch.apply(
            str(manifest),
            "pi-sess-amb",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out2["results"][0]["status"], "blocked")
        self.assertEqual(out2["results"][0]["reason"], "pending conclusion absent on readback; automatic retry disabled")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote.calls))
        self.assertEqual(len(self._pending_files()), 1)
        self.assertEqual(server.active_sessions, {})
        self.assertEqual(len(server.delete_requests), 2)

        remote.add_row(scope, "recovered-1", gateway.format_note(scope, item))
        remote.calls.clear()
        out3 = batch.apply(
            str(manifest),
            "pi-sess-amb",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out3["results"][0]["status"], "verified")
        self.assertFalse(any(name == "create_conclusions" for name, _ in remote.calls))
        self.assertEqual(self._pending_files(), [])
        self.assertEqual(server.active_sessions, {})
        self.assertEqual(len(server.delete_requests), 3)

    def test_stateless_405_and_timeout_cleanup_nonfatal_and_releases_lock(self):
        remote = FakeRemote()
        server_405 = CapacityLimitedMCPServer(remote, max_active_sessions=1, valid_tokens={"tok-405"})
        server_405.delete_status = 405
        self.addCleanup(server_405.close)

        scope = _make_scope("repo-alpha", session_id="sess-405")
        checkout = self._checkout("repo-alpha", "repo-alpha")
        grant, _ = self._grant("alpha-405", scope, server_405.url, "tok-405")
        manifest = self._manifest([_make_item(checkout, grant, scope)], "m405.json")
        digest = batch.preview(str(manifest), "pi-sess-nf", route_resolver=self._route_resolver)["digest"]

        out_405 = batch.apply(
            str(manifest),
            "pi-sess-nf",
            digest,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_405["results"][0]["status"], "verified")
        self.assertEqual(len(server_405.delete_requests), 1)
        self.assertEqual(self._pending_files(), [])

        server_stateless = CapacityLimitedMCPServer(
            FakeRemote(), max_active_sessions=1, valid_tokens={"tok-sl"}, stateless=True
        )
        self.addCleanup(server_stateless.close)
        scope_sl = _make_scope("repo-beta", session_id="sess-sl")
        co_sl = self._checkout("repo-beta", "repo-beta")
        gr_sl, _ = self._grant("beta-sl", scope_sl, server_stateless.url, "tok-sl")
        m_sl = self._manifest([_make_item(co_sl, gr_sl, scope_sl)], "msl.json")
        d_sl = batch.preview(str(m_sl), "pi-sess-nf", route_resolver=self._route_resolver)["digest"]
        out_sl = batch.apply(
            str(m_sl),
            "pi-sess-nf",
            d_sl,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_sl["results"][0]["status"], "verified")
        self.assertEqual(server_stateless.delete_requests, [])

        server_slow = CapacityLimitedMCPServer(FakeRemote(), max_active_sessions=1, valid_tokens={"tok-slow"})
        server_slow.delete_delay = 0.25
        self.addCleanup(server_slow.close)
        scope_slow = _make_scope("repo-gamma", session_id="sess-slow")
        co_slow = self._checkout("repo-gamma", "repo-gamma")
        gr_slow, _ = self._grant("gamma-slow", scope_slow, server_slow.url, "tok-slow")
        m_slow = self._manifest([_make_item(co_slow, gr_slow, scope_slow)], "mslow.json")
        d_slow = batch.preview(str(m_slow), "pi-sess-nf", route_resolver=self._route_resolver)["digest"]

        with mock.patch.object(gateway, "CLOSE_TIMEOUT", 0.05):
            out_slow = batch.apply(
                str(m_slow),
                "pi-sess-nf",
                d_slow,
                state_dir=self.state_dir,
                route_resolver=self._route_resolver,
            )
        self.assertEqual(out_slow["results"][0]["status"], "verified")
        self.assertEqual(self._pending_files(), [])
        self.assertTrue(server_slow.delete_completed.wait(timeout=2.0))
        self.assertEqual(server_slow.active_sessions, {})

        server_slow.delete_delay = 0.0
        server_slow.delete_completed.clear()
        out_rerun = batch.apply(
            str(m_slow),
            "pi-sess-nf",
            d_slow,
            state_dir=self.state_dir,
            route_resolver=self._route_resolver,
        )
        self.assertEqual(out_rerun["results"][0]["status"], "already present")
        self.assertTrue(server_slow.delete_completed.wait(timeout=2.0))
        self.assertEqual(server_slow.active_sessions, {})


if __name__ == "__main__":
    unittest.main()
