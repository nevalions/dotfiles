"""Bounded offline-preview and verified-append batch engine for Honcho."""
from dataclasses import dataclass
import fcntl
import hashlib
import hmac
from http.client import HTTPException
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from urllib.error import URLError

_CLI_DIR = Path(__file__).resolve().parent


def _load_sibling(module_name, filename):
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    path = _CLI_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


gateway = _load_sibling("gateway", "gateway.py")

MAX_REPOS = 32
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PENDING_BYTES = 4096
PAGE_SIZE = 50
MAX_PAGES = 20
MAX_TOTAL_CONCLUSIONS = PAGE_SIZE * MAX_PAGES
MAX_READBACK_TEXT = 512 * 1024
REQUIRED_WORKSPACE = "hermes-personal"
REQUIRED_PEER = "pi-coordinator"
DISALLOWED_TARGETS = {"linroot", "pi-coordinator", "code-wide", "preferences"}
MANIFEST_KEYS = {"items"}
ITEM_KEYS = {"checkout", "grant", "scope", *gateway.FIELDS}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
UPSTREAM_ERRORS = (
    gateway.Denied,
    URLError,
    HTTPException,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RecursionError,
)


class BatchError(Exception):
    """Sanitized failure safe to surface without leaking paths, secrets, or raw replies."""


@dataclass(frozen=True)
class SnapshotItem:
    repo: str
    checkout: str
    checkout_realpath: str
    grant: str
    grant_realpath: str
    grant_raw_sha256: str
    grant_descriptor: dict
    scope: dict
    note: str
    note_sha256: str


@dataclass(frozen=True)
class Snapshot:
    pi_session_id: str
    digest: str
    items: tuple


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _safe_single_line(value, label):
    if not isinstance(value, str) or not value or not value.isprintable():
        raise BatchError(f"unsafe {label}")
    return value


def _validate_session_id(session_id):
    if (not isinstance(session_id, str) or not 1 <= len(session_id) <= 256
            or not session_id.isprintable() or any(ch.isspace() for ch in session_id)):
        raise BatchError("invalid session id")
    return session_id


def _validate_repo_id(repo):
    if (not isinstance(repo, str) or not gateway.ID.fullmatch(repo)
            or repo in DISALLOWED_TARGETS or repo.startswith("project-")
            or "*" in repo or "?" in repo):
        raise BatchError("disallowed repository route")
    return repo


def read_private_bytes(path, max_bytes):
    if not isinstance(path, str) or not os.path.isabs(path):
        raise BatchError("private file path must be absolute")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise BatchError("unreadable private file") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BatchError("expected an owner-only regular file")
        data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise BatchError("private file too large")
        return data


def resolve_checkout_route(checkout):
    if not isinstance(checkout, str) or not os.path.isabs(checkout):
        raise BatchError("checkout path must be absolute")
    if os.path.islink(checkout) or not os.path.isdir(checkout):
        raise BatchError("invalid checkout directory")
    try:
        checkout_resolved = Path(checkout).resolve(strict=True)
    except OSError as exc:
        raise BatchError("invalid checkout directory") from exc
    home = Path.home()
    git_env = {"HOME": str(home), "PATH": "/usr/bin", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            [
                "/usr/bin/git",
                "-C",
                str(checkout_resolved),
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
            ],
            cwd=str(checkout_resolved),
            env=git_env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BatchError("unable to resolve checkout git repository") from exc
    if proc.returncode != 0:
        raise BatchError("checkout is not a git repository")
    lines = proc.stdout.splitlines()
    if len(lines) != 2:
        raise BatchError("unexpected git repository layout")
    try:
        toplevel = Path(lines[0]).resolve(strict=True)
        common = Path(lines[1]).resolve(strict=True)
    except OSError as exc:
        raise BatchError("invalid git repository paths") from exc
    if toplevel != checkout_resolved:
        raise BatchError("checkout must be a git repository root")
    recall_scopes = _load_sibling("recall_scopes", "recall-scopes.py")
    recall_scopes.HOME = home
    routes = recall_scopes.targets(common)
    if not isinstance(routes, list) or not routes:
        raise BatchError("checkout has no allowed repository route")
    return str(checkout_resolved), _validate_repo_id(routes[0])


def _validate_scope(scope, grant_scope, expected_repo):
    if not isinstance(scope, dict) or set(scope.keys()) != set(gateway.SCOPE):
        raise BatchError("invalid item scope")
    for value in scope.values():
        if not isinstance(value, str) or not gateway.ID.fullmatch(value):
            raise BatchError("invalid item scope identifier")
    if scope["workspace_id"] != REQUIRED_WORKSPACE:
        raise BatchError("invalid workspace binding")
    if scope["peer_id"] != REQUIRED_PEER:
        raise BatchError("invalid coordinator peer binding")
    if scope["target_peer_id"] != expected_repo:
        raise BatchError("scope target does not match checkout route")
    if scope != grant_scope:
        raise BatchError("manifest scope does not match grant scope")


def load_snapshot(manifest_path, pi_session_id, *, route_resolver=None):
    session = _validate_session_id(pi_session_id)
    manifest_bytes = read_private_bytes(manifest_path, MAX_MANIFEST_BYTES)
    try:
        manifest_text = manifest_bytes.decode("utf-8")
        manifest_data = gateway.parse_json_unique(manifest_text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BatchError("malformed manifest JSON or duplicate keys") from exc
    if not isinstance(manifest_data, dict) or set(manifest_data.keys()) != MANIFEST_KEYS:
        raise BatchError("invalid manifest top-level structure")
    raw_items = manifest_data["items"]
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_REPOS:
        raise BatchError("manifest items must be nonempty and at most 32 items")

    seen_checkouts = set()
    seen_grants = set()
    seen_repos = set()
    seen_sessions = set()
    seen_bindings = set()
    snapshot_items = []
    canonical_items = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item.keys()) != ITEM_KEYS:
            raise BatchError("invalid manifest item structure")

        checkout = raw_item["checkout"]
        if route_resolver is None:
            checkout_realpath, repo = resolve_checkout_route(checkout)
        else:
            if not isinstance(checkout, str) or not os.path.isabs(checkout) or os.path.islink(checkout):
                raise BatchError("invalid checkout path")
            checkout_realpath = os.path.realpath(checkout)
            repo = _validate_repo_id(route_resolver(checkout))

        grant_path = raw_item["grant"]
        if not isinstance(grant_path, str) or not os.path.isabs(grant_path):
            raise BatchError("invalid grant path")
        try:
            grant_raw_text, grant_descriptor = gateway.load_grant_descriptor(grant_path)
        except (OSError, ValueError, TypeError) as exc:
            raise BatchError("invalid or unreadable private grant") from exc
        grant_realpath = os.path.realpath(grant_path)
        grant_raw_sha256 = _sha256_hex(grant_raw_text)

        scope = raw_item["scope"]
        _validate_scope(scope, grant_descriptor["scope"], repo)

        evidence = {field: raw_item[field] for field in gateway.FIELDS}
        try:
            note = gateway.format_note(scope, evidence)
        except gateway.Denied as exc:
            raise BatchError("invalid note evidence") from exc

        bound = gateway.bound_scope(scope)
        session_tuple = (bound["workspace_id"], bound["session_id"])
        binding_tuple = tuple(bound[key] for key in ("workspace_id", "peer_id", "target_peer_id", "session_id"))

        if checkout_realpath in seen_checkouts:
            raise BatchError("duplicate checkout binding in manifest")
        if grant_realpath in seen_grants:
            raise BatchError("duplicate grant binding in manifest")
        if repo in seen_repos:
            raise BatchError("duplicate repository binding in manifest")
        if session_tuple in seen_sessions:
            raise BatchError("duplicate upstream session in manifest")
        if binding_tuple in seen_bindings:
            raise BatchError("duplicate upstream session binding in manifest")

        seen_checkouts.add(checkout_realpath)
        seen_grants.add(grant_realpath)
        seen_repos.add(repo)
        seen_sessions.add(session_tuple)
        seen_bindings.add(binding_tuple)

        item = SnapshotItem(
            repo=repo,
            checkout=checkout,
            checkout_realpath=checkout_realpath,
            grant=grant_path,
            grant_realpath=grant_realpath,
            grant_raw_sha256=grant_raw_sha256,
            grant_descriptor=grant_descriptor,
            scope=dict(scope),
            note=note,
            note_sha256=_sha256_hex(note),
        )
        snapshot_items.append(item)
        canonical_items.append({
            "checkout": checkout,
            "checkout_realpath": checkout_realpath,
            "route": repo,
            "grant": grant_path,
            "grant_realpath": grant_realpath,
            "grant_raw_sha256": grant_raw_sha256,
            "grant_descriptor": grant_descriptor,
            "note": note,
        })

    canonical_snapshot = {
        "version": 1,
        "pi_session_id": session,
        "manifest_sha256": _sha256_hex(manifest_bytes),
        "manifest": manifest_data,
        "items": canonical_items,
    }
    digest = _sha256_hex(_canonical_json(canonical_snapshot))
    return Snapshot(pi_session_id=session, digest=digest, items=tuple(snapshot_items))


def format_preview(snapshot):
    lines = [
        f"Honcho batch preview (pi_session_id={_safe_single_line(snapshot.pi_session_id, 'session id')}, "
        f"items={len(snapshot.items)})",
    ]
    for index, item in enumerate(snapshot.items, start=1):
        destination = _safe_single_line(item.grant_descriptor["url"], "destination")
        repo = _safe_single_line(item.repo, "repo")
        scope_parts = " ".join(
            f"{key}={_safe_single_line(item.scope[key], key)}"
            for key in gateway.SCOPE
        )
        note = _safe_single_line(item.note, "note")
        lines.append(f"[{index}] repo={repo} destination={destination}")
        lines.append(f"    scope: {scope_parts}")
        lines.append(f"    note: {note}")
    return "\n".join(lines)


def preview(manifest_path, pi_session_id, *, route_resolver=None):
    snapshot = load_snapshot(manifest_path, pi_session_id, route_resolver=route_resolver)
    return {"digest": snapshot.digest, "preview": format_preview(snapshot)}


def default_state_dir():
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if isinstance(xdg_state, str) and os.path.isabs(xdg_state):
        return Path(xdg_state) / "pi-honcho-batch"
    return Path.home() / ".local" / "state" / "pi-honcho-batch"


def _open_dir_fd(path, *, nofollow=False, dir_fd=None):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NONBLOCK
    if nofollow:
        flags |= os.O_NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def _sync_parent_chain(start_path, target_dev):
    uid = os.getuid()
    cur = start_path
    while True:
        try:
            info = os.lstat(cur)
        except OSError as exc:
            raise BatchError("unable to inspect state parent directory") from exc
        if info.st_dev != target_dev:
            break
        is_foreign = info.st_uid != uid
        if is_foreign and cur != start_path and (info.st_mode & 0o022) == 0:
            break
        fd = _open_dir_fd(cur, nofollow=True)
        try:
            finfo = os.fstat(fd)
            if finfo.st_dev != target_dev:
                break
            os.fsync(fd)
        finally:
            os.close(fd)
        if is_foreign or cur == cur.parent:
            break
        cur = cur.parent


def open_state_dir(state_dir=None):
    target = Path(default_state_dir() if state_dir is None else state_dir)
    if not target.is_absolute() or ".." in target.parts or not target.name or target == Path("/"):
        raise BatchError("state directory must be absolute")

    try:
        target_lstat = os.lstat(target)
    except FileNotFoundError:
        target_lstat = None
    except OSError as exc:
        raise BatchError("unable to inspect state directory") from exc

    if target_lstat is not None:
        if stat.S_ISLNK(target_lstat.st_mode) or not stat.S_ISDIR(target_lstat.st_mode):
            raise BatchError("unable to prepare private state directory")
        try:
            resolved_parent = target.parent.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BatchError("unable to resolve state directory ancestor") from exc
        base_fd = None
        dir_fd = None
        try:
            base_fd = _open_dir_fd(resolved_parent, nofollow=True)
            dir_fd = _open_dir_fd(target.name, nofollow=True, dir_fd=base_fd)
        except OSError as exc:
            if dir_fd is not None:
                try:
                    os.close(dir_fd)
                except OSError:
                    pass
            raise BatchError("unable to prepare private state directory") from exc
        finally:
            if base_fd is not None:
                try:
                    os.close(base_fd)
                except OSError:
                    pass
        parent_to_sync = resolved_parent
    else:
        missing_parts = [target.name]
        cur = target.parent
        while True:
            try:
                os.lstat(cur)
                break
            except FileNotFoundError:
                if cur == cur.parent:
                    raise BatchError("unable to resolve state directory ancestor")
                missing_parts.append(cur.name)
                cur = cur.parent
            except OSError as exc:
                raise BatchError("unable to inspect state directory") from exc

        try:
            resolved_base = cur.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BatchError("unable to resolve state directory ancestor") from exc

        rel_parts = list(reversed(missing_parts))
        cur_fd = None
        try:
            cur_fd = _open_dir_fd(resolved_base, nofollow=True)
            for part in rel_parts:
                try:
                    os.mkdir(part, 0o700, dir_fd=cur_fd)
                except FileExistsError:
                    pass
                os.fsync(cur_fd)
                next_fd = _open_dir_fd(part, nofollow=True, dir_fd=cur_fd)
                os.close(cur_fd)
                cur_fd = next_fd
            dir_fd = cur_fd
            cur_fd = None
        except OSError as exc:
            if cur_fd is not None:
                try:
                    os.close(cur_fd)
                except OSError:
                    pass
            raise BatchError("unable to prepare private state directory") from exc
        parent_to_sync = resolved_base.parent if resolved_base != resolved_base.parent else None

    try:
        info = os.fstat(dir_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BatchError("state directory must be owner-only")
        os.fsync(dir_fd)
        if parent_to_sync is not None:
            _sync_parent_chain(parent_to_sync, info.st_dev)
    except BatchError:
        os.close(dir_fd)
        raise
    except OSError as exc:
        os.close(dir_fd)
        raise BatchError("unable to sync state directory") from exc
    return dir_fd


def _binding_key(scope):
    return _sha256_hex(_canonical_json(gateway.bound_scope(scope)))


def _read_pending_marker(dir_fd, pending_name, expected_binding):
    try:
        fd = os.open(pending_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BatchError("unreadable pending marker") from exc
    stream = None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BatchError("invalid pending marker permissions")
        stream = os.fdopen(fd, "rb")
        raw = stream.read(MAX_PENDING_BYTES + 1)
    except OSError as exc:
        raise BatchError("unreadable pending marker") from exc
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        else:
            try:
                os.close(fd)
            except OSError:
                pass
    if len(raw) > MAX_PENDING_BYTES:
        raise BatchError("pending marker too large")
    try:
        data = gateway.parse_json_unique(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise BatchError("malformed pending marker") from exc
    if (not isinstance(data, dict)
            or set(data.keys()) != {"version", "binding", "note_sha256"}
            or data["version"] != 1
            or data["binding"] != expected_binding
            or not isinstance(data["note_sha256"], str)
            or not SHA256_RE.fullmatch(data["note_sha256"])):
        raise BatchError("invalid pending marker contents")
    return data["note_sha256"]


def _write_pending_marker(dir_fd, pending_name, binding, note_sha256):
    payload = _canonical_json({
        "version": 1,
        "binding": binding,
        "note_sha256": note_sha256,
    }).encode("utf-8")
    tmp_name = f"{pending_name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
    except OSError as exc:
        raise BatchError("unable to create pending marker") from exc
    try:
        try:
            stream = os.fdopen(fd, "wb")
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, pending_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    except Exception as exc:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        raise BatchError("unable to persist pending marker") from exc


def _clear_pending_marker(dir_fd, pending_name):
    try:
        os.unlink(pending_name, dir_fd=dir_fd)
        os.fsync(dir_fd)
    except OSError as exc:
        raise BatchError("unable to clear pending marker") from exc


def _parse_list_page(result, expected_page, scope):
    if not isinstance(result, dict):
        raise ValueError("invalid list_conclusions result")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ValueError("invalid list_conclusions content")
    part = content[0]
    if not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str):
        raise ValueError("invalid list_conclusions text block")
    text = part["text"]
    if len(text) > MAX_READBACK_TEXT:
        raise ValueError("list_conclusions response too large")
    inner = gateway.parse_json_unique(text)
    if not isinstance(inner, dict) or set(inner.keys()) != {"conclusions", "page", "pages", "total"}:
        raise ValueError("invalid list_conclusions JSON shape")
    page = inner["page"]
    pages = inner["pages"]
    total = inner["total"]
    rows = inner["conclusions"]
    if not (_is_int(page) and _is_int(pages) and _is_int(total)) or not isinstance(rows, list):
        raise ValueError("invalid list_conclusions field types")
    if page != expected_page or not 0 <= pages <= MAX_PAGES or not 0 <= total <= MAX_TOTAL_CONCLUSIONS:
        raise ValueError("list_conclusions pagination out of bounds")
    expected_pages_for_total = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if pages != expected_pages_for_total:
        raise ValueError("inconsistent list_conclusions page count")
    if total == 0:
        if page != 1 or pages != 0 or rows:
            raise ValueError("invalid empty list_conclusions page")
        return pages, total, []
    if pages < 1 or page > pages:
        raise ValueError("invalid non-empty list_conclusions page")
    expected_len = PAGE_SIZE if page < pages else total - (pages - 1) * PAGE_SIZE
    if len(rows) != expected_len or not 1 <= len(rows) <= PAGE_SIZE:
        raise ValueError("inconsistent list_conclusions page length")
    parsed_rows = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid conclusion row")
        required = ("id", "content", "observer_id", "observed_id", "session_id")
        if not all(key in row and isinstance(row[key], str) for key in required):
            raise ValueError("missing conclusion row fields")
        if not row["id"]:
            raise ValueError("empty conclusion id")
        if (row["observer_id"] != scope["peer_id"]
                or row["observed_id"] != scope["target_peer_id"]
                or row["session_id"] != scope["session_id"]):
            raise ValueError("conclusion row scope mismatch")
        parsed_rows.append((row["id"], row["content"]))
    return pages, total, parsed_rows


def readback_conclusions(client, scope):
    bound = gateway.bound_scope(scope)
    page = 1
    expected_pages = None
    expected_total = None
    seen_ids = set()
    contents = []
    while True:
        result = client.call("list_conclusions", {**bound, "page": page, "size": PAGE_SIZE})
        pages, total, parsed_rows = _parse_list_page(result, page, scope)
        if expected_pages is None:
            expected_pages = pages
            expected_total = total
        elif pages != expected_pages or total != expected_total:
            raise ValueError("unstable list_conclusions pagination")
        if total == 0:
            return []
        for row_id, row_content in parsed_rows:
            if row_id in seen_ids:
                raise ValueError("duplicate conclusion id across readback")
            seen_ids.add(row_id)
            contents.append(row_content)
        if page >= expected_pages:
            break
        page += 1
    if len(contents) != expected_total:
        raise ValueError("incomplete list_conclusions readback")
    return contents


def _result(repo, status, reason):
    return {"repo": repo, "status": status, "reason": reason}


def apply_item(item, dir_fd, *, client_factory=None):
    bound = gateway.bound_scope(item.scope)
    key = _binding_key(item.scope)
    lock_name = f"{key}.lock"
    pending_name = f"{key}.pending.json"
    open_client = gateway.open_grant_client if client_factory is None else client_factory

    try:
        lock_fd = os.open(
            lock_name,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=dir_fd,
        )
    except OSError:
        return _result(item.repo, "blocked", "unable to open session lock")

    lock_acquired = False
    client = None
    try:
        try:
            info = os.fstat(lock_fd)
        except OSError:
            return _result(item.repo, "blocked", "unable to validate session lock")
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return _result(item.repo, "blocked", "invalid session lock permissions")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_acquired = True
        except BlockingIOError:
            return _result(item.repo, "blocked", "session lock busy")
        except OSError:
            return _result(item.repo, "blocked", "unable to acquire session lock")

        try:
            client = open_client(item.grant_descriptor)
        except gateway.Denied:
            return _result(item.repo, "blocked", "tailnet route unavailable")
        except (OSError, ValueError, TypeError):
            return _result(item.repo, "blocked", "credential unavailable")

        try:
            pending_digest = _read_pending_marker(dir_fd, pending_name, bound)
        except BatchError as exc:
            return _result(item.repo, "blocked", str(exc))

        if pending_digest is not None:
            if pending_digest != item.note_sha256:
                return _result(item.repo, "blocked", "different conclusion pending for upstream session")
            try:
                existing = readback_conclusions(client, item.scope)
            except gateway.UpstreamHTTPStatus as exc:
                return _result(item.repo, "blocked", f"pending conclusion readback failed ({exc.reason})")
            except UPSTREAM_ERRORS:
                return _result(item.repo, "blocked", "pending conclusion readback failed or inconclusive")
            if any(entry == item.note for entry in existing):
                try:
                    _clear_pending_marker(dir_fd, pending_name)
                except BatchError as exc:
                    return _result(item.repo, "blocked", str(exc))
                return _result(item.repo, "verified", "recovered pending conclusion via readback")
            return _result(item.repo, "blocked", "pending conclusion absent on readback; automatic retry disabled")

        try:
            existing = readback_conclusions(client, item.scope)
        except gateway.UpstreamHTTPStatus as exc:
            return _result(item.repo, "blocked", f"pre-read failed ({exc.reason})")
        except UPSTREAM_ERRORS:
            return _result(item.repo, "blocked", "pre-read failed or unproven")

        if any(entry == item.note for entry in existing):
            return _result(item.repo, "already present", "exact conclusion already present")

        if len(existing) >= MAX_TOTAL_CONCLUSIONS:
            return _result(item.repo, "blocked", "upstream session conclusion limit reached")

        try:
            _write_pending_marker(dir_fd, pending_name, bound, item.note_sha256)
        except BatchError as exc:
            return _result(item.repo, "blocked", str(exc))

        append_failed = False
        append_status_reason = None
        try:
            client.call("create_conclusions", {**bound, "conclusions": [item.note]})
        except gateway.UpstreamHTTPStatus as exc:
            append_failed = True
            append_status_reason = exc.reason
        except UPSTREAM_ERRORS:
            append_failed = True

        try:
            after = readback_conclusions(client, item.scope)
        except gateway.UpstreamHTTPStatus as exc:
            return _result(
                item.repo,
                "blocked",
                f"post-append readback failed ({exc.reason}); pending marker retained",
            )
        except UPSTREAM_ERRORS:
            if append_status_reason is not None:
                return _result(
                    item.repo,
                    "blocked",
                    f"post-append readback failed after {append_status_reason}; pending marker retained",
                )
            return _result(item.repo, "blocked", "post-append readback failed or unproven; pending marker retained")

        if any(entry == item.note for entry in after):
            try:
                _clear_pending_marker(dir_fd, pending_name)
            except BatchError as exc:
                return _result(item.repo, "blocked", str(exc))
            if append_failed:
                return _result(item.repo, "verified", "recovered pending conclusion via readback")
            return _result(item.repo, "verified", "conclusion verified via readback")

        if append_status_reason is not None:
            return _result(
                item.repo,
                "blocked",
                f"conclusion absent on readback after {append_status_reason}; pending marker retained",
            )
        return _result(item.repo, "blocked", "conclusion absent on readback; pending marker retained")
    finally:
        try:
            if client is not None:
                close_client = getattr(client, "close", None)
                if callable(close_client):
                    try:
                        close_client()
                    except Exception:
                        pass
        finally:
            if lock_acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                os.close(lock_fd)
            except OSError:
                pass


def apply(manifest_path, pi_session_id, approved_sha256, *, state_dir=None, route_resolver=None, client_factory=None):
    if not isinstance(approved_sha256, str) or not SHA256_RE.fullmatch(approved_sha256):
        raise BatchError("invalid approval digest")
    snapshot = load_snapshot(manifest_path, pi_session_id, route_resolver=route_resolver)
    if not hmac.compare_digest(snapshot.digest, approved_sha256):
        raise BatchError("approval digest mismatch")
    dir_fd = open_state_dir(state_dir)
    try:
        results = [
            apply_item(item, dir_fd, client_factory=client_factory)
            for item in snapshot.items
        ]
    finally:
        os.close(dir_fd)
    return {"digest": snapshot.digest, "results": results}


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        if not args:
            raise BatchError("invalid CLI arguments")
        command = args[0]
        if command == "preview" and len(args) == 3:
            output = preview(args[1], args[2])
        elif command == "apply" and len(args) == 4:
            output = apply(args[1], args[2], args[3])
        else:
            raise BatchError("invalid CLI arguments")
    except BatchError as exc:
        print(f"Honcho batch: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Honcho batch: unexpected internal failure", file=sys.stderr)
        return 1
    print(json.dumps(output), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
