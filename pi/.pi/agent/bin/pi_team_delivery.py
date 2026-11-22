"""Bounded opt-in Forgejo delivery continuation helpers."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

FORGEJO_HOST = 'git.butakov.su'
MAX_GRANT_TTL = timedelta(hours=24)

REV_RE = re.compile(r'^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$')
REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

REQUIRED_GRANT_KEYS = frozenset({
    'host',
    'repo',
    'pr',
    'head_sha',
    'base_sha',
    'base_ref',
    'pr_checks',
    'post_merge_checks',
    'expires_at',
})
OPTIONAL_GRANT_KEYS = frozenset({'head_ref'})


class DeliveryError(ValueError):
    """Validation or Forgejo delivery verification error."""


def _parse_utc(value: Any, label: str) -> datetime:
    """Parse a timezone-aware datetime or ISO-8601 UTC/offset string."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DeliveryError(f'{label} must include a timezone')
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise DeliveryError(f'{label} must be an ISO-8601 timestamp or aware datetime')
    text = value.strip()
    if not text or text != value:
        raise DeliveryError(f'{label} must be a non-empty trimmed ISO-8601 timestamp')
    if text.endswith(('Z', 'z')):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DeliveryError(f'invalid {label}: {value!r}') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DeliveryError(f'{label} must include a timezone offset or Z')
    return dt.astimezone(timezone.utc)


def _format_utc(dt: datetime) -> str:
    """Format a timezone-aware datetime as a UTC ISO-8601 string."""
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _resolve_now(now: Any) -> datetime:
    """Resolve an optional datetime, ISO string, or zero-arg clock callable."""
    if now is None:
        return datetime.now(timezone.utc)
    if callable(now):
        return _parse_utc(now(), 'now')
    return _parse_utc(now, 'now')


def _validate_sha(value: Any, label: str) -> str:
    """Validate and normalize a full 40- or 64-character hex commit SHA."""
    if not isinstance(value, str) or not REV_RE.fullmatch(value):
        raise DeliveryError(f'{label} must be a full 40- or 64-character hex SHA')
    return value.lower()


def _validate_ref(value: Any, label: str) -> str:
    """Validate a git branch ref name."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value != value.strip()
        or not value.isprintable()
        or any(ch.isspace() for ch in value)
        or '..' in value
        or '//' in value
        or value.startswith('/')
        or value.endswith(('/', '.lock'))
        or value == '@'
    ):
        raise DeliveryError(f'invalid {label}')
    return value


def _validate_checks(value: Any, label: str) -> list[str]:
    """Validate a non-empty sequence of exact check context names."""
    if not isinstance(value, (list, tuple)) or not value:
        raise DeliveryError(f'{label} must be a non-empty list of check contexts')
    for item in value:
        if (
            not isinstance(item, str)
            or not 1 <= len(item) <= 256
            or item != item.strip()
            or not item.isprintable()
        ):
            raise DeliveryError(f'invalid check context in {label}')
    return list(dict.fromkeys(value))


def _validate_grant_core(grant: Any, now_dt: datetime) -> tuple[dict[str, Any], datetime]:
    """Validate grant shape, fixed host, exact targets, and 24h TTL cap."""
    if not isinstance(grant, dict):
        raise DeliveryError('grant must be a dict')
    keys = set(grant.keys())
    missing = REQUIRED_GRANT_KEYS - keys
    extra = keys - (REQUIRED_GRANT_KEYS | OPTIONAL_GRANT_KEYS)
    if missing:
        raise DeliveryError(f'grant missing required keys: {", ".join(sorted(missing))}')
    if extra:
        raise DeliveryError(f'grant contains unsupported keys: {", ".join(sorted(extra))}')
    if grant['host'] != FORGEJO_HOST:
        raise DeliveryError(f'grant host must be {FORGEJO_HOST}')
    repo = grant['repo']
    if (
        not isinstance(repo, str)
        or not REPO_RE.fullmatch(repo)
        or any(part in ('.', '..') for part in repo.split('/'))
    ):
        raise DeliveryError('grant repo must be owner/name')
    pr = grant['pr']
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise DeliveryError('grant pr must be a positive integer')
    expires_dt = _parse_utc(grant['expires_at'], 'expires_at')
    if expires_dt - now_dt > MAX_GRANT_TTL:
        raise DeliveryError('grant expiry exceeds 24h maximum')

    normalized: dict[str, Any] = {
        'host': FORGEJO_HOST,
        'repo': repo,
        'pr': pr,
        'head_sha': _validate_sha(grant['head_sha'], 'head_sha'),
        'base_sha': _validate_sha(grant['base_sha'], 'base_sha'),
        'base_ref': _validate_ref(grant['base_ref'], 'base_ref'),
        'pr_checks': _validate_checks(grant['pr_checks'], 'pr_checks'),
        'post_merge_checks': _validate_checks(grant['post_merge_checks'], 'post_merge_checks'),
        'expires_at': _format_utc(expires_dt),
    }
    if grant.get('head_ref') is not None:
        normalized['head_ref'] = _validate_ref(grant['head_ref'], 'head_ref')
    return normalized, expires_dt


def validate_grant(
    grant: dict[str, Any],
    now: datetime | str | Callable[[], datetime | str] | None = None,
) -> dict[str, Any]:
    """Validate and normalize a bounded Forgejo delivery continuation grant."""
    now_dt = _resolve_now(now)
    normalized, expires_dt = _validate_grant_core(grant, now_dt)
    if expires_dt <= now_dt:
        raise DeliveryError('grant has expired')
    return normalized


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    """Ensure a Forgejo response object is a dict."""
    if not isinstance(value, dict):
        raise DeliveryError(f'invalid Forgejo {label} response')
    return value


def _result(
    grant: dict[str, Any],
    *,
    status: str,
    phase: str,
    reason: str,
    actual_head_sha: str | None = None,
    actual_base_sha: str | None = None,
    merge_commit_sha: str | None = None,
    merged: bool = False,
    pending_checks: Sequence[str] = (),
    failed_checks: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a compact status payload with exact revisions and no raw logs."""
    return {
        'status': status,
        'phase': phase,
        'reason': reason,
        'host': grant['host'],
        'repo': grant['repo'],
        'pr': grant['pr'],
        'head_sha': grant['head_sha'],
        'base_sha': grant['base_sha'],
        'base_ref': grant['base_ref'],
        'actual_head_sha': actual_head_sha,
        'actual_base_sha': actual_base_sha,
        'merge_commit_sha': merge_commit_sha,
        'merged': merged,
        'pending_checks': list(pending_checks),
        'failed_checks': list(failed_checks),
        'expires_at': grant['expires_at'],
    }


def _optional_bool(value: Any, label: str) -> bool:
    """Validate an optional boolean field (treating None as False)."""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise DeliveryError(f'invalid {label}')
    return value


def _fetch_pr(get: Callable[[str], Any], pr_num: int) -> dict[str, Any]:
    """Fetch and structurally validate a Forgejo pull request response."""
    pr_data = _require_dict(get(f'pulls/{pr_num}'), 'pull request')
    if 'number' in pr_data and (isinstance(pr_data['number'], bool) or pr_data['number'] != pr_num):
        raise DeliveryError('Forgejo PR number mismatch')
    _require_dict(pr_data.get('head'), 'PR head')
    _require_dict(pr_data.get('base'), 'PR base')
    return pr_data


def _fetch_base_tip(get: Callable[[str], Any], base_ref: str) -> str:
    """Fetch and validate the current tip SHA of the base branch."""
    branch = _require_dict(get(f'branches/{quote(base_ref, safe="")}'), 'base branch')
    if 'name' in branch and branch['name'] != base_ref:
        raise DeliveryError('Forgejo base branch name mismatch')
    if branch.get('protected') is not True:
        raise DeliveryError('delivery requires a server-protected base branch')
    commit = _require_dict(branch.get('commit'), 'base branch commit')
    cid = commit.get('id')
    csha = commit.get('sha')
    if cid is not None and csha is not None and str(cid).lower() != str(csha).lower():
        raise DeliveryError('conflicting base branch commit SHA')
    return _validate_sha(cid if cid is not None else csha, 'base tip sha')


def _check_statuses(
    get: Callable[[str], Any],
    sha: str,
    required: list[str],
) -> tuple[list[str], list[str]]:
    """Fetch Forgejo commit status for an exact SHA and classify required checks."""
    payload = _require_dict(get(f'commits/{quote(sha, safe="")}/status'), 'commit status')
    if _validate_sha(payload.get('sha'), 'commit status sha') != sha:
        raise DeliveryError('Forgejo status response does not match expected revision')
    raw_statuses = payload.get('statuses')
    if raw_statuses is None:
        raw_statuses = []
    if not isinstance(raw_statuses, list):
        raise DeliveryError('invalid Forgejo statuses list')
    by_context: dict[str, str] = {}
    for entry in raw_statuses:
        if not isinstance(entry, dict):
            raise DeliveryError('invalid Forgejo status entry')
        ctx = entry.get('context')
        state = entry.get('status')
        if not isinstance(ctx, str) or not isinstance(state, str):
            raise DeliveryError('invalid Forgejo status entry fields')
        if ctx in by_context and by_context[ctx] != state and ctx in required:
            raise DeliveryError('conflicting required status entries; refresh Forgejo checks')
        by_context[ctx] = state
    pending = [name for name in required if by_context.get(name) in (None, 'pending', 'running')]
    failed = [name for name in required if name not in pending and by_context[name] != 'success']
    return pending, failed


def _verify_post_merge(
    grant: dict[str, Any],
    get: Callable[[str], Any],
    merge_commit_sha: str,
    actual_head_sha: str,
    actual_base_sha: str | None,
) -> dict[str, Any]:
    """Verify exact-SHA post-merge checks on a merge commit."""
    commit = _require_dict(get(f'git/commits/{merge_commit_sha}'), 'merge commit')
    if _validate_sha(commit.get('sha'), 'merge commit sha') != merge_commit_sha:
        raise DeliveryError('merge commit response does not match expected revision')
    parents = commit.get('parents')
    if not isinstance(parents, list) or len(parents) != 1 or not isinstance(parents[0], dict) \
            or parents[0].get('sha') != grant['base_sha']:
        raise DeliveryError('actual squash parent differs from approved base; stop and review the merged result')
    pending, failed = _check_statuses(get, merge_commit_sha, grant['post_merge_checks'])
    common = {
        'actual_head_sha': actual_head_sha,
        'actual_base_sha': actual_base_sha,
        'merge_commit_sha': merge_commit_sha,
        'merged': True,
    }
    if failed:
        return _result(
            grant,
            status='blocked',
            phase='post_merge',
            reason='post_merge_checks_failed',
            failed_checks=failed,
            pending_checks=pending,
            **common,
        )
    if pending:
        return _result(
            grant,
            status='pending',
            phase='post_merge',
            reason='post_merge_checks_pending',
            pending_checks=pending,
            **common,
        )
    return _result(
        grant,
        status='verified',
        phase='post_merge',
        reason='post_merge_checks_passed',
        **common,
    )


def _verify_merged_pr(
    grant: dict[str, Any],
    get: Callable[[str], Any],
    pr_data: dict[str, Any],
) -> dict[str, Any]:
    """Verify an already-merged PR against grant refs/head and post-merge checks."""
    head = pr_data['head']
    base = pr_data['base']
    actual_head_sha = _validate_sha(head.get('sha'), 'PR head sha')
    actual_base_ref = base.get('ref')
    if not isinstance(actual_base_ref, str) or not actual_base_ref:
        raise DeliveryError('PR base ref must be a non-empty string')
    actual_base_sha = _validate_sha(base.get('sha'), 'PR base sha') if base.get('sha') is not None else None
    if actual_head_sha != grant['head_sha']:
        return _result(
            grant,
            status='blocked',
            phase='pr',
            reason='head_sha_mismatch',
            actual_head_sha=actual_head_sha,
            actual_base_sha=actual_base_sha,
            merged=True,
        )
    if actual_base_ref != grant['base_ref']:
        return _result(
            grant,
            status='blocked',
            phase='pr',
            reason='base_ref_mismatch',
            actual_head_sha=actual_head_sha,
            actual_base_sha=actual_base_sha,
            merged=True,
        )
    if 'head_ref' in grant and head.get('ref') != grant['head_ref']:
        return _result(
            grant,
            status='blocked',
            phase='pr',
            reason='head_ref_mismatch',
            actual_head_sha=actual_head_sha,
            actual_base_sha=actual_base_sha,
            merged=True,
        )
    merge_commit_sha = _validate_sha(pr_data.get('merge_commit_sha'), 'PR merge_commit_sha')
    return _verify_post_merge(grant, get, merge_commit_sha, actual_head_sha, actual_base_sha)


def _verify_open_pr(
    grant: dict[str, Any],
    get: Callable[[str], Any],
    pr_data: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Verify an open ready PR and current base branch tip, or handle closed/merged states."""
    state = pr_data.get('state')
    merged = _optional_bool(pr_data.get('merged'), 'PR merged')
    if state == 'closed':
        if merged:
            return _verify_merged_pr(grant, get, pr_data), None
        actual_head = _validate_sha(pr_data['head'].get('sha'), 'PR head sha')
        raw_base = pr_data['base'].get('sha')
        actual_base = _validate_sha(raw_base, 'PR base sha') if raw_base is not None else None
        return _result(
            grant,
            status='blocked',
            phase='pr',
            reason='pr_closed',
            actual_head_sha=actual_head,
            actual_base_sha=actual_base,
        ), None
    if state != 'open' or merged:
        raise DeliveryError(f'unexpected PR state {state!r} (merged={merged!r})')

    head = pr_data['head']
    base = pr_data['base']
    actual_head_sha = _validate_sha(head.get('sha'), 'PR head sha')
    actual_base_sha = _validate_sha(base.get('sha'), 'PR base sha')
    actual_base_ref = base.get('ref')
    if not isinstance(actual_base_ref, str) or not actual_base_ref:
        raise DeliveryError('PR base ref must be a non-empty string')

    def blocked(reason: str, tip_sha: str | None = actual_base_sha) -> tuple[dict[str, Any], None]:
        return _result(
            grant,
            status='blocked',
            phase='pr',
            reason=reason,
            actual_head_sha=actual_head_sha,
            actual_base_sha=tip_sha,
        ), None

    if _optional_bool(pr_data.get('draft'), 'PR draft'):
        return blocked('pr_draft')
    if actual_head_sha != grant['head_sha']:
        return blocked('head_sha_mismatch')
    if actual_base_ref != grant['base_ref']:
        return blocked('base_ref_mismatch')
    if 'head_ref' in grant and head.get('ref') != grant['head_ref']:
        return blocked('head_ref_mismatch')
    if actual_base_sha != grant['base_sha']:
        return blocked('base_sha_mismatch')

    base_tip_sha = _fetch_base_tip(get, grant['base_ref'])
    if base_tip_sha != grant['base_sha']:
        return blocked('base_tip_mismatch', base_tip_sha)
    return None, base_tip_sha


def advance(
    grant: dict[str, Any],
    get: Callable[[str], Any],
    merge: Callable[[str, dict[str, Any]], Any],
    now: datetime | str | Callable[[], datetime | str] | None = None,
) -> dict[str, Any]:
    """Advance a bounded opt-in Forgejo PR delivery grant without ever deploying."""
    if not callable(get) or not callable(merge):
        raise DeliveryError('get and merge must be callable')
    now_dt = _resolve_now(now)
    norm, expires_dt = _validate_grant_core(grant, now_dt)
    if expires_dt <= now_dt:
        return _result(norm, status='blocked', phase='grant', reason='grant_expired')

    pr_data = _fetch_pr(get, norm['pr'])
    early, base_tip = _verify_open_pr(norm, get, pr_data)
    if early is not None:
        return early

    pending, failed = _check_statuses(get, norm['head_sha'], norm['pr_checks'])
    if failed:
        return _result(
            norm,
            status='blocked',
            phase='pr_checks',
            reason='pr_checks_failed',
            actual_head_sha=norm['head_sha'],
            actual_base_sha=base_tip,
            failed_checks=failed,
            pending_checks=pending,
        )
    if pending:
        return _result(
            norm,
            status='pending',
            phase='pr_checks',
            reason='pr_checks_pending',
            actual_head_sha=norm['head_sha'],
            actual_base_sha=base_tip,
            pending_checks=pending,
        )

    if _resolve_now(now) >= expires_dt:
        return _result(
            norm,
            status='blocked',
            phase='grant',
            reason='grant_expired',
            actual_head_sha=norm['head_sha'],
            actual_base_sha=base_tip,
        )

    pr_data = _fetch_pr(get, norm['pr'])
    early, base_tip = _verify_open_pr(norm, get, pr_data)
    if early is not None:
        return early

    if _resolve_now(now) >= expires_dt:
        return _result(
            norm,
            status='blocked',
            phase='grant',
            reason='grant_expired',
            actual_head_sha=norm['head_sha'],
            actual_base_sha=base_tip,
        )

    pending, failed = _check_statuses(get, norm['head_sha'], norm['pr_checks'])
    if pending or failed:
        return _result(norm, status='blocked' if failed else 'pending', phase='pr_checks',
                       reason='pr_checks_changed_before_merge', pending_checks=pending, failed_checks=failed)
    if _resolve_now(now) >= expires_dt:
        return _result(norm, status='blocked', phase='grant', reason='grant_expired')

    merge_payload = {
        'Do': 'squash',
        'head_commit_id': norm['head_sha'],
        'delete_branch_after_merge': False,
    }
    merge_res = merge(f'pulls/{norm["pr"]}/merge', merge_payload)

    merge_commit_sha: str | None = None
    if isinstance(merge_res, dict):
        raw_sha = merge_res.get('merge_commit_sha') or merge_res.get('sha')
        if raw_sha is not None:
            merge_commit_sha = _validate_sha(raw_sha, 'merge_commit_sha')
    if merge_commit_sha is None:
        post_pr = _fetch_pr(get, norm['pr'])
        if post_pr.get('state') != 'closed' or not _optional_bool(post_pr.get('merged'), 'PR merged'):
            raise DeliveryError('PR was not merged after squash merge call')
        return _verify_merged_pr(norm, get, post_pr)

    return _verify_post_merge(norm, get, merge_commit_sha, norm['head_sha'], base_tip)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_private_file(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DeliveryError('delivery configuration must be a private regular file owned by this user')
        if info.st_size > 65536:
            raise DeliveryError('delivery configuration exceeds size limit')
        return stream.read(65537)


def run_delivery(run_id: str) -> int:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise DeliveryError('invalid delivery id')
    settings = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'pi-team'
    directory = settings / 'delivery'
    grant_file = directory / f'{run_id}.json'
    grant = validate_grant(json.loads(read_private_file(grant_file)))
    token = read_private_file(settings / 'delivery-token').strip()
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]+', token):
        raise DeliveryError('invalid dedicated delivery token')
    allowed = read_private_file(settings / 'delivery-pilot-repos').splitlines()
    if grant['repo'] not in {line.strip() for line in allowed}:
        raise DeliveryError('repository not enabled for the delivery pilot')

    opener = build_opener(NoRedirect())
    root = f'https://{FORGEJO_HOST}/api/v1/repos/{grant["repo"]}'

    def request(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = Request(f'{root}/{path}', data=body, headers={
            'Authorization': f'token {token}', 'Accept': 'application/json', 'Content-Type': 'application/json',
        })
        with opener.open(req, timeout=8) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise DeliveryError('Forgejo response exceeds size limit')
            return json.loads(raw) if raw else None

    os.umask(0o077)
    owner, repo = grant['repo'].lower().split('/')
    lock_name = f'{len(owner)}-{owner}-{repo}-{grant["pr"]}.lock'
    lock = os.open(directory / lock_name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, 'w') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeliveryError('delivery already running') from None
        def merge_if_still_granted(path, payload):
            if validate_grant(json.loads(read_private_file(grant_file))) != grant:
                raise DeliveryError('grant changed before merge')
            if grant['repo'] not in read_private_file(settings / 'delivery-pilot-repos').split():
                raise DeliveryError('repository removed from the delivery pilot')
            return request(path, payload)

        previous = None
        transient = 0
        while True:
            if validate_grant(json.loads(read_private_file(grant_file))) != grant:
                raise DeliveryError('grant changed during delivery')
            try:
                result = advance(grant, request, merge_if_still_granted)
                transient = 0
            except HTTPError as exc:
                if exc.code not in (409, 429, 500, 502, 503, 504):
                    raise DeliveryError(f'Forgejo delivery request failed (HTTP {exc.code})') from None
                transient += 1
                result = {'status': 'pending', 'reason': f'forgejo_http_{exc.code}'}
            except (URLError, TimeoutError):
                transient += 1
                result = {'status': 'pending', 'reason': 'forgejo_transport_error'}
            if result != previous:
                print(json.dumps(result, sort_keys=True), flush=True)
                previous = result
            if result['status'] != 'pending':
                return 0 if result['status'] == 'verified' else 1
            if transient >= 3:
                raise DeliveryError('Forgejo unavailable after three attempts; recheck PR status before resuming')
            deadline = _parse_utc(grant['expires_at'], 'expires_at')
            time.sleep(max(0, min(30, (deadline - datetime.now(timezone.utc)).total_seconds())))


def main() -> int:
    parser = argparse.ArgumentParser(description='Continue one explicitly granted Forgejo pilot PR; never deploys directly.')
    parser.add_argument('delivery_id')
    args = parser.parse_args()
    try:
        return run_delivery(args.delivery_id)
    except DeliveryError as exc:
        print(f'delivery blocked: {exc}', file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError):
        print('delivery blocked: missing or invalid private configuration or Forgejo evidence', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
