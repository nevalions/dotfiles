"""Short-lived, source-bound Ed25519 authorization for the isolated merge bot."""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


REQUIRED_CONTEXTS = (
    'CI / lint (pull_request)', 'CI / typecheck (pull_request)',
    'CI / test (pull_request)', 'CI / quality-gate (pull_request)',
    'security-pr / semgrep (pull_request)', 'security-pr / gitleaks (pull_request)',
    'security-pr / trivy-fs (pull_request)', 'security-pr / pip-audit (pull_request)')
SITE_POLICIES = {
    'nevalions/ochistka-musoroprovoda.ru': ('master', 'ochistka-musoroprovoda'),
    'nevalions/videooperator.su': ('master', 'videooperator-su'),
    'nevalions/videosemka.su': ('master', 'videosemka-su'),
}


def source_policy(repository):
    if repository == 'nevalions/yt-downloader':
        return 'main', REQUIRED_CONTEXTS
    need(repository in SITE_POLICIES, 'source repository is outside approved policy')
    return SITE_POLICIES[repository][0], ('CI / build (pull_request)',)


PROTECTION_FIELDS = frozenset(('repository', 'branch', 'base_sha', 'checked_at',
                               'apply_to_admins', 'block_on_outdated_branch',
                               'enable_status_check', 'status_check_contexts'))


class SigningError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise SigningError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def unique(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, 'duplicate signed JSON field')
        value[key] = item
    return value


def stamp(value):
    if type(value) in (int, float):
        return value
    need(isinstance(value, str), 'proof timestamp missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.tzinfo is not None, 'proof timestamp lacks timezone')
    return parsed.timestamp()


def recent(value, issued, age):
    need(0 <= issued - stamp(value) <= age, 'proof is stale or in the future')


def qualification_id(value):
    keys = ('runtime_manifest_digest', 'platform', 'branch', 'package', 'fixes')
    return hashlib.sha256(canonical({key: value[key] for key in keys})).hexdigest()


def validate_qualification(value, issued):
    need(isinstance(value.get('deployed_image'), str) and re.fullmatch(r'[^\s@]+:[A-Za-z0-9_][A-Za-z0-9_.-]*', value['deployed_image']), 'qualified deployed image tag invalid')
    need(value.get('platform') == 'linux/amd64' and value.get('branch') == 'v3.24'
         and value.get('package') == 'libxml2', 'qualification scope differs')
    for field in ('runtime_manifest_digest', 'manifest_digest', 'platform_manifest_digest'):
        need(isinstance(value.get(field), str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value[field]), 'qualification digest invalid')
    need(value['runtime_manifest_digest'] in (value['manifest_digest'], value['platform_manifest_digest']), 'runtime digest is unrelated to registry proof')
    for field in ('source_sha', 'source_blob'):
        need(isinstance(value.get(field), str) and re.fullmatch(r'[0-9a-f]{40}', value[field]), 'qualification source identity invalid')
    need(isinstance(value.get('scan_report_id'), str) and value['scan_report_id'], 'scan report identity missing')
    recent(value.get('scan_generated_at'), issued, 172800)
    recent(value.get('scan_end_time'), issued, 172800)
    need(stamp(value['scan_generated_at']) <= stamp(value['scan_end_time']), 'scan report time order invalid')
    expected_urls = {
        'apk_index': 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/APKINDEX.tar.gz',
        'secdb': 'https://secdb.alpinelinux.org/v3.24/main.json'}
    for field, url in expected_urls.items():
        proof = value.get(field, {})
        need(proof.get('url') == url and isinstance(proof.get('sha256'), str)
             and re.fullmatch(r'[0-9a-f]{64}', proof['sha256']), 'official package evidence invalid')
        recent(proof.get('fetched_at'), issued, 300)
    index = value['apk_index']
    need(index.get('architecture') == 'x86_64' and isinstance(index.get('versions'), list) and index['versions'], 'official index platform or versions missing')
    fixes = value.get('fixes')
    need(isinstance(fixes, list) and fixes, 'qualified fix queue is empty')
    for fix in fixes:
        need(isinstance(fix.get('id'), str) and re.fullmatch(r'CVE-[0-9]{4}-[0-9]{4,}', fix['id']), 'qualified CVE identity invalid')
        versions = [fix.get('installed'), fix.get('fixed')] + fix.get('available', [])
        need(set(fix.get('available', [])) <= set(index['versions']), 'available fix is absent from official index proof')
        need(fix.get('available') and all(isinstance(v, str) and re.fullmatch(r'[0-9][A-Za-z0-9_.+~:-]*', v) for v in versions), 'qualified APK versions invalid')
    need(value.get('qualification_id') == qualification_id(value), 'qualification identity mismatch')


def validate_source_qualification(value, repository):
    if repository in SITE_POLICIES:
        app = SITE_POLICIES[repository][1]
        image = value.get('deployed_image', '').rsplit(':', 1)[0]
        need(image.endswith('/library/' + app + '-frontend'), 'qualified image belongs to another source')


def validate_protection(value, base_sha, issued, repository='nevalions/yt-downloader'):
    branch, contexts = source_policy(repository)
    need(isinstance(value, dict) and set(value) == PROTECTION_FIELDS, 'signed protection fields missing or unexpected')
    need(value['repository'] == repository and value['branch'] == branch
         and value['base_sha'] == base_sha, 'signed protection source identity differs')
    need(all(value[field] is True for field in ('apply_to_admins', 'block_on_outdated_branch', 'enable_status_check')), 'signed protection enforcement flag is not true')
    need(value['status_check_contexts'] == sorted(contexts), 'signed protection contexts differ from exact policy checks')
    need(type(value['checked_at']) in (int, float), 'signed protection timestamp is not numeric')
    recent(value['checked_at'], issued, 900)


def epoch_change(before, after):
    def parse(contents):
        lines = contents.splitlines(keepends=True)
        rows = [(index, re.fullmatch(r'ARG APK_PATCH_EPOCH=(\d{4}-\d{2}-\d{2})(\n?)', line)) for index, line in enumerate(lines)]
        rows = [(index, match) for index, match in rows if match]
        need(len(rows) == 1, 'expected one exact source epoch')
        index, match = rows[0]
        parsed = date.fromisoformat(match[1])
        need(parsed.isoformat() == match[1], 'epoch date invalid')
        return lines, index, parsed, match[2]
    old, index, old_date, newline = parse(before)
    new, next_index, new_date, next_newline = parse(after)
    need(index == next_index and len(old) == len(new) and newline == next_newline and new_date > old_date, 'source epoch does not strictly advance')
    need(all(left == right for n, (left, right) in enumerate(zip(old, new)) if n != index), 'source diff changes another line')
    return old_date.isoformat(), new_date.isoformat()


def bound_payload(qualification, branch, base_sha, head_sha, pr_number, before, after, *, issued=None, lifetime=900, protection=None, repository='nevalions/yt-downloader'):
    target, contexts = source_policy(repository)
    issued = time.time() if issued is None else issued
    need(type(lifetime) is int and 0 < lifetime <= 900, 'signature lifetime exceeds policy')
    need(type(issued) in (int, float), 'signature issue time invalid')
    validate_qualification(qualification, issued)
    validate_source_qualification(qualification, repository)
    need(branch == 'maintenance/apk-' + qualification['qualification_id'][:20], 'proposal branch is not deterministic')
    need(all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{40}', v) for v in (base_sha, head_sha)), 'proposal commit identity invalid')
    need(type(pr_number) is int and pr_number > 0, 'proposal number invalid')
    validate_protection(protection, base_sha, issued, repository)
    old_epoch, new_epoch = epoch_change(before, after)
    need(new_epoch <= datetime.fromtimestamp(issued, timezone.utc).date().isoformat(), 'new epoch must not be a future UTC date')
    return {'schema_version': 1, 'type': 'yt-os-refresh', 'repository': repository, 'target': target,
            'base_sha': base_sha, 'head_sha': head_sha, 'pr_number': pr_number, 'path': 'Dockerfile',
            'before_sha256': hashlib.sha256(before.encode('utf-8')).hexdigest(),
            'after_sha256': hashlib.sha256(after.encode('utf-8')).hexdigest(), 'old_epoch': old_epoch, 'new_epoch': new_epoch,
            'issued_at': issued, 'expires_at': issued + lifetime, 'qualification': qualification, 'protection': protection}


def load_private(path, fingerprint):
    descriptor = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        need(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
             and not metadata.st_mode & 0o077, 'signing key must be user-owned private regular file')
        raw = source.read(8193)
        need(len(raw) <= 8192, 'signing key file oversized')
    key = serialization.load_pem_private_key(raw, password=None)
    need(isinstance(key, Ed25519PrivateKey), 'signing key is not Ed25519')
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    need(hashlib.sha256(public).hexdigest() == fingerprint, 'signing public fingerprint differs from pinned policy')
    return key


def signed_comment(payload, key):
    raw = canonical(payload)
    envelope = {'payload': base64.b64encode(raw).decode('ascii'), 'signature': base64.b64encode(key.sign(raw)).decode('ascii')}
    return '<!-- yt-os-refresh-v1\n' + canonical(envelope).decode('utf-8') + '\n-->'


def verify_comment(body, public_key, *, at=None, allow_expired=False, repository='nevalions/yt-downloader'):
    target, contexts = source_policy(repository)
    try:
        need(isinstance(body, str) and len(body.encode()) <= 65536, 'signature comment oversized')
        match = re.fullmatch(r'<!-- yt-os-refresh-v1\n([^\n]+)\n-->', body)
        need(match is not None, 'signature comment grammar invalid')
        envelope = json.loads(match[1], object_pairs_hook=unique)
        need(set(envelope) == {'payload', 'signature'}, 'signature envelope fields invalid')
        raw = base64.b64decode(envelope['payload'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
        need(len(signature) == 64, 'Ed25519 signature size invalid')
        public_key.verify(signature, raw)
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        current = time.time() if at is None else at
        need(payload.get('schema_version') == 1 and payload.get('type') == 'yt-os-refresh'
             and payload.get('repository') == repository and payload.get('target') == target
             and payload.get('path') == 'Dockerfile', 'signature payload scope invalid')
        need(type(payload.get('issued_at')) in (int, float) and type(payload.get('expires_at')) in (int, float)
             and payload['issued_at'] <= current and (allow_expired or current < payload['expires_at'])
             and 0 < payload['expires_at'] - payload['issued_at'] <= 900, 'signature expired or outside lifetime policy')
        validate_qualification(payload['qualification'], payload['issued_at'])
        validate_source_qualification(payload['qualification'], repository)
        validate_protection(payload.get('protection'), payload['base_sha'], payload['issued_at'], repository)
        if not allow_expired:
            recent(payload['protection']['checked_at'], current, 900)
        return payload
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SigningError):
            raise
        raise SigningError('invalid signed proposal') from exc
