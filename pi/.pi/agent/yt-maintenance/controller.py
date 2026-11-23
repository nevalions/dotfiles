#!/usr/bin/env python3
"""Deterministic trusted-host Alpine rebuild qualification and rollout handoff."""
from __future__ import annotations

import argparse
import base64
import difflib
from datetime import date, datetime, timezone
import fcntl
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


class Rejected(ValueError):
    pass


class NotFound(Rejected):
    pass


def require(ok, message):
    if not ok:
        raise Rejected(message)


def now():
    return time.time()


def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    require(isinstance(value, str), 'timestamp missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'evidence timestamp lacks timezone')
    return parsed.timestamp()


def fresh(value, age):
    elapsed = now() - timestamp(value)
    require(0 <= elapsed <= age, 'evidence is stale or in the future')


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
        temporary = Path(out.name)
        json.dump(value, out, sort_keys=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def run(argv, data=None, timeout=180, allow_failure=False, return_status=False):
    require(isinstance(argv, list) and argv and all(isinstance(x, str) and x for x in argv), 'invalid command argv')
    try:
        result = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=timeout, check=False, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Rejected('trusted helper unavailable or timed out') from exc
    require(allow_failure or result.returncode == 0, 'trusted helper failed')
    require(len(result.stdout) <= 16 * 1024 * 1024, 'helper response exceeds limit')
    return (result.returncode, result.stdout) if return_status else result.stdout


def apk_less(left, right, command):
    require(all(isinstance(v, str) and re.fullmatch(r'[0-9][A-Za-z0-9_.+~:-]*', v) for v in (left, right)), 'invalid APK version')
    relation = run(command + ['version', '-t', left, right]).strip()
    require(relation in ('<', '=', '>'), 'apk-tools comparison failed')
    return relation == '<'


def apk_versions(index, package, arch):
    found = []
    for block in index.split('\n\n'):
        fields = {}
        for line in block.splitlines():
            if len(line) > 2 and line[1] == ':':
                fields[line[0]] = line[2:]
        if fields.get('P') == package and fields.get('A') == arch and fields.get('V'):
            found.append(fields['V'])
    return found


def epoch_line(contents):
    lines = contents.splitlines(keepends=True)
    matches = [(i, re.fullmatch(r'ARG APK_PATCH_EPOCH=(\d{4}-\d{2}-\d{2})(\n?)', line)) for i, line in enumerate(lines)]
    matches = [(i, match) for i, match in matches if match]
    require(len(matches) == 1, 'expected one anchored APK_PATCH_EPOCH date')
    i, match = matches[0]
    try:
        parsed = date.fromisoformat(match[1])
    except ValueError as exc:
        raise Rejected('invalid epoch date') from exc
    require(parsed.isoformat() == match[1], 'invalid epoch date')
    return lines, i, parsed, match[2]


def epoch_only(before, after):
    old, index, old_date, newline = epoch_line(before)
    new, next_index, new_date, next_newline = epoch_line(after)
    require(index == next_index and newline == next_newline and len(old) == len(new), 'proposal changes source shape')
    require(new_date > old_date, 'epoch must strictly increase')
    require(all(a == b for n, (a, b) in enumerate(zip(old, new)) if n != index), 'proposal changes another line')
    return True


def advance_epoch(contents, value):
    lines, index, previous, newline = epoch_line(contents)
    proposed = date.fromisoformat(value)
    require(proposed.isoformat() == value and proposed > previous, 'no later valid epoch available')
    lines[index] = 'ARG APK_PATCH_EPOCH=' + value + newline
    result = ''.join(lines)
    epoch_only(contents, result)
    return result


def verify_receipt(receipt, candidate, started):
    require(receipt.get('status') == 'verified' and receipt.get('verified_release') is True, 'rollout has not verified; retry on next tick')
    require(receipt.get('candidate') == candidate and receipt.get('candidate_id') == identity(candidate), 'receipt candidate mismatch')
    require(started <= timestamp(receipt.get('observed_at')) <= now() + 5, 'receipt is not from this invocation')


def load_config(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077, 'config must be user-owned regular mode 0600 file')
    config = json.loads(path.read_text())
    require(config.get('schema_version') == 1, 'config schema_version must be 1')
    for service in ('forgejo', 'harbor'):
        parsed = urlsplit(config[service]['url'])
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, 'service URL must be credential-free HTTPS')
    require(config['platform'] in ('linux/amd64', 'linux/arm64'), 'unsupported target platform')
    require(config['alpine_branch'] == 'v3.24', 'only supported Alpine 3.24 qualification is enabled')
    require(config['package'] == 'libxml2', 'only libxml2 qualification is enabled')
    require(config['source']['dockerfile'] == 'Dockerfile', 'source path must be Dockerfile')
    require(type(config.get('scan_max_age_seconds', 172800)) is int and 0 < config.get('scan_max_age_seconds', 172800) <= 172800, 'scan freshness policy may not exceed 48 hours')
    require(config['gitops']['branch'] == 'master', 'observer currently supports master revision grammar')
    return config


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Rejected('HTTP redirect refused')


class HTTP:
    def __init__(self, config):
        self.config = config

    def request(self, service, path, body=None, method='GET', raw=False, headers=None):
        cfg = self.config[service]
        require(path.startswith('/') and not path.startswith('//'), 'invalid API path')
        request_headers = {'Accept': 'application/json', **(headers or {})}
        if cfg.get('auth_command') and 'Authorization' not in request_headers:
            value = run(cfg['auth_command']).strip()
            require(value and '\n' not in value and '\r' not in value, 'invalid authorization helper result')
            request_headers['Authorization'] = value
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        request = Request(cfg['url'].rstrip('/') + path, data=data, headers=request_headers, method=method)
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
                require(len(payload) <= 16 * 1024 * 1024, 'HTTP response exceeds limit')
                return payload if raw else json.loads(payload)
        except (HTTPError, URLError, TimeoutError) as exc:
            code = getattr(exc, 'code', 'network')
            if code == 404:
                raise NotFound(f'{service} evidence not found') from exc
            raise Rejected(f'{service} request failed ({code})') from exc

    def forge(self, repo, suffix, body=None, method='GET'):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid repository scope')
        headers = None
        if method != 'GET':
            source = self.config['source']
            allowed = (method, suffix.split('?', 1)[0]) in {
                ('POST', '/branches'), ('POST', '/pulls'),
                ('PUT', '/contents/' + quote(source['dockerfile'], safe='/'))}
            require(repo == source['repo'] and allowed and self.config.get('proposal_enabled') is True,
                    'Forgejo write exceeds proposal policy')
            require(source.get('proposal_auth_command'), 'a separately authorized repository-scoped proposal credential is required')
            value = run(source['proposal_auth_command']).strip()
            require(value and '\n' not in value and '\r' not in value, 'invalid proposal authorization')
            headers = {'Authorization': value}
        return self.request('forgejo', '/api/v1/repos/' + repo + suffix, body, method, headers=headers)

    def iter_pages(self, repo, suffix, key=None):
        for page in range(1, 21):
            sep = '&' if '?' in suffix else '?'
            value = self.forge(repo, suffix + sep + urlencode({'limit': 50, 'page': page}))
            values = value[key] if key else value
            require(isinstance(values, list), 'invalid paginated response')
            yield from values
            if len(values) < 50:
                return
        raise Rejected('API pagination bound exceeded')

    def pages(self, repo, suffix, key=None):
        return list(self.iter_pages(repo, suffix, key))

    def contents(self, repo, path, ref):
        value = self.forge(repo, '/contents/' + quote(path, safe='/') + '?' + urlencode({'ref': ref}))
        require(value.get('encoding') == 'base64' and value.get('type') == 'file', 'source is not a regular file')
        return base64.b64decode(value['content']).decode(), value['sha']


def observe(config, candidate=None):
    command = config['transport_command'] + ['observe' if candidate is None else 'verify']
    code, payload = run(command, None if candidate is None else json.dumps(candidate), timeout=300, allow_failure=True, return_status=True)
    value = json.loads(payload)
    require(code == 0 or (candidate is not None and value.get('verified_release') is False), 'transport process failed despite success receipt')
    target = {key: config['target'][key] for key in ('flux_namespace', 'kustomization', 'namespace', 'deployment', 'container')}
    require(value.get('target') == target and value.get('context') == config['target']['context'], 'transport target differs')
    fresh(value.get('observed_at'), 360)
    if candidate is None:
        require(value.get('status') in ('observed', 'verified'), 'deployed workload is not healthy')
        require('observation' in value, 'healthy observation missing')
    return value


def harbor_artifact(api, config, reference):
    project, repository = config['harbor']['repository'].split('/', 1)
    path = '/api/v2.0/projects/' + quote(project, safe='') + '/repositories/' + quote(quote(repository, safe=''), safe='') + '/artifacts/' + quote(reference, safe='')
    artifact = api.request('harbor', path + '?with_scan_overview=true')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', '')), 'Harbor artifact has no immutable digest')
    if reference.startswith('sha256:'):
        require(artifact['digest'] == reference, 'Harbor returned another immutable digest')
    return artifact, path


def platform_artifact(api, config, reference):
    parent, path = harbor_artifact(api, config, reference)
    manifest = registry_document(api, config, parent['digest'])
    if not reference.startswith('sha256:'):
        require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', reference), 'registry tag invalid')
        tagged = api.request('harbor', '/v2/' + config['harbor']['repository'] + '/manifests/' + reference, raw=True, headers=registry_headers(api, config))
        require('sha256:' + hashlib.sha256(tagged).hexdigest() == parent['digest'], 'registry tag bytes differ from Harbor digest')
    if 'manifests' in manifest:
        require(manifest.get('mediaType') in ('application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'), 'registry index media type invalid')
        runnable = []
        attestations = []
        for descriptor in manifest['manifests']:
            platform = descriptor.get('platform', {})
            if platform.get('os') == 'unknown' and platform.get('architecture') == 'unknown':
                require(descriptor.get('annotations', {}).get('vnd.docker.reference.type') == 'attestation-manifest', 'unknown platform is not a proven attestation')
                attestations.append(descriptor)
            else:
                runnable.append(descriptor)
        require(len(runnable) == 1, 'runtime index must contain exactly one runnable platform')
        selected = runnable[0]
        platform = selected.get('platform', {})
        require(platform.get('os', '') + '/' + platform.get('architecture', '') == config['platform'] and not platform.get('variant'), 'sole registry platform differs from target')
        require(all(v['annotations'].get('vnd.docker.reference.digest') == selected['digest'] for v in attestations), 'attestation is for another platform digest')
        child, child_path = harbor_artifact(api, config, selected['digest'])
        require(child['digest'] == selected['digest'], 'Harbor platform descriptor digest differs')
    else:
        child, child_path = parent, path
    image_config = registry_config(api, config, child['digest'])
    require(image_config.get('os', '') + '/' + image_config.get('architecture', '') == config['platform'], 'registry platform differs from target')
    child['_image_config'] = image_config
    return parent, child, child_path


def read_apk_index(config):
    arch = {'linux/amd64': 'x86_64', 'linux/arm64': 'aarch64'}[config['platform']]
    url = 'https://dl-cdn.alpinelinux.org/alpine/' + config['alpine_branch'] + '/main/' + arch + '/APKINDEX.tar.gz'
    try:
        with build_opener(NoRedirect()).open(url, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        require(len(data) <= 8 * 1024 * 1024, 'APKINDEX archive exceeds limit')
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            members = [v for v in archive.getmembers() if v.name == 'APKINDEX' and v.isfile()]
            require(len(members) == 1 and members[0].size <= 32 * 1024 * 1024, 'APKINDEX missing or oversized')
            index = archive.extractfile(members[0]).read().decode()
    except (OSError, tarfile.TarError, URLError) as exc:
        raise Rejected('official APKINDEX unavailable') from exc
    versions = apk_versions(index, config['package'], arch)
    require(versions, 'package is absent from same-branch official APKINDEX')
    return {'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'versions': versions, 'architecture': arch, 'fetched_at': now()}


def registry_headers(api, config):
    if not getattr(api, '_registry_token', None):
        repository = config['harbor']['repository']
        token = api.request('harbor', '/service/token?' + urlencode({'service': 'harbor-registry', 'scope': 'repository:' + repository + ':pull'}))
        bearer = token.get('token') or token.get('access_token')
        require(isinstance(bearer, str) and bearer, 'registry pull token missing')
        api._registry_token = bearer
    return {'Authorization': 'Bearer ' + api._registry_token,
            'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'}


def registry_document(api, config, digest):
    repository = config['harbor']['repository']
    data = api.request('harbor', '/v2/' + repository + '/manifests/' + digest, raw=True, headers=registry_headers(api, config))
    require('sha256:' + hashlib.sha256(data).hexdigest() == digest, 'registry manifest bytes differ from digest')
    return json.loads(data)


def registry_config(api, config, digest):
    manifest = registry_document(api, config, digest)
    require(manifest.get('mediaType') in ('application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'), 'platform object is not an image manifest')
    config_digest = manifest.get('config', {}).get('digest', '')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', config_digest), 'image config descriptor invalid')
    repository = config['harbor']['repository']
    data = api.request('harbor', '/v2/' + repository + '/blobs/' + config_digest, raw=True, headers=registry_headers(api, config))
    require('sha256:' + hashlib.sha256(data).hexdigest() == config_digest, 'image config bytes differ from digest')
    return json.loads(data)


def official_secdb(config):
    url = 'https://secdb.alpinelinux.org/' + config['alpine_branch'] + '/main.json'
    try:
        with build_opener(NoRedirect()).open(url, timeout=30) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        require(len(data) <= 16 * 1024 * 1024, 'official secdb exceeds limit')
        value = json.loads(data)
    except (URLError, OSError, ValueError) as exc:
        raise Rejected('official same-branch secdb unavailable') from exc
    packages = [v['pkg'] for v in value.get('packages', []) if v.get('pkg', {}).get('name') == config['package']]
    require(len(packages) == 1, 'official secdb package missing or ambiguous')
    return packages[0].get('secfixes', {}), {'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'fetched_at': now()}


def source_revision(config, artifact, allow_legacy=False):
    labels = artifact.get('_image_config', {}).get('config', {}).get('Labels', {})
    revision = labels.get('org.opencontainers.image.revision', '')
    if not revision and allow_legacy:
        legacy = config.get('legacy_baseline', {})
        require(artifact['digest'] == legacy.get('runtime_manifest_digest'), 'legacy source mapping does not match deployed digest')
        revision = legacy.get('source_sha', '')
    require(re.fullmatch(r'[0-9a-f]{40}', revision), 'immutable OCI source revision missing')
    return revision


def qualify(api, config, receipt):
    observation = receipt['observation']
    image = observation['deployment']['image']
    require(image.rsplit(':', 1)[0] == config['image_repository'], 'deployed repository differs')
    require(len(observation['digests']) == 1, 'deployed runtime digest ambiguous')
    runtime_digest = observation['digests'][0]
    parent, child, path = platform_artifact(api, config, runtime_digest)
    require(runtime_digest in (parent['digest'], child['digest']), 'deployed digest does not identify verified platform')
    digest = child['digest']
    for pod in observation['pods']:
        require(pod['image_id'].split('://')[-1] == config['image_repository'] + '@' + runtime_digest, 'runtime imageID cannot prove registry repository/digest')
    source_sha = source_revision(config, child, allow_legacy=True)
    dockerfile, blob = api.contents(config['source']['repo'], config['source']['dockerfile'], source_sha)
    legacy = config.get('legacy_baseline', {})
    if digest == legacy.get('runtime_manifest_digest') and source_sha == legacy.get('source_sha'):
        require(legacy.get('alpine_version', '').startswith('3.24.') and str(legacy.get('evidence_url', '')).startswith('https://'), 'legacy Alpine documentary evidence missing')
    else:
        strict_source(config, dockerfile)
    overview = list(child.get('scan_overview', {}).values())
    require(len(overview) == 1, 'expected exactly one latest scan report')
    summary = overview[0]
    require(summary.get('scan_status') == 'Success' and summary.get('report_id') and summary.get('complete_percent') == 100, 'latest registry scan did not succeed')
    fresh(summary.get('end_time'), config.get('scan_max_age_seconds', 172800))
    require(timestamp(summary['end_time']) >= timestamp(summary['start_time']), 'scan time ordering invalid')
    reports = api.request('harbor', path + '/additions/vulnerabilities', headers={'X-Accept-Vulnerabilities': 'application/vnd.security.vulnerability.report; version=1.1'})
    reports = [r for key, r in reports.items() if key == 'application/vnd.security.vulnerability.report; version=1.1']
    require(len(reports) == 1, 'scanner vulnerability report missing or ambiguous')
    report = reports[0]
    require(report.get('scanner', {}).get('name') == 'Trivy', 'unsupported vulnerability scanner')
    after, _ = harbor_artifact(api, config, digest)
    require(after.get('scan_overview') == child.get('scan_overview'), 'latest scan changed during collection')
    generated = report.get('generated_at')
    fresh(generated, config.get('scan_max_age_seconds', 172800))
    require(timestamp(summary['start_time']) <= timestamp(generated) <= timestamp(summary['end_time']) + 60, 'report is not from latest successful scan')
    rows = [item for item in report.get('vulnerabilities', []) if item.get('package') == config['package']
            and str(item.get('severity', '')).upper() in ('HIGH', 'CRITICAL') and item.get('fix_version')]
    if not rows:
        return None
    index = read_apk_index(config)
    secfixes, secdb = official_secdb(config)
    fixes = []
    for item in rows:
        require(item.get('artifact_digests') == [digest], 'vulnerability row does not bind exact deployed digest')
        installed, fixed = item.get('version'), item.get('fix_version')
        if not fixed:
            continue
        require(isinstance(fixed, str) and ',' not in fixed and ' ' not in fixed, 'ambiguous fixed APK version')
        require(item.get('id') in secfixes.get(fixed, []), 'official same-branch secdb does not confirm reported OS package fix')
        require(apk_less(installed, fixed, config['apk_command']), 'report fix is not newer than installed APK')
        available = [v for v in index['versions'] if not apk_less(v, fixed, config['apk_command'])]
        require(available, 'reported fix unavailable in official same-branch APKINDEX')
        fixes.append({'id': item['id'], 'installed': installed, 'fixed': fixed, 'available': sorted(available)})
    if not fixes:
        return None
    result = {'deployed_image': image, 'runtime_manifest_digest': runtime_digest, 'platform_manifest_digest': digest, 'manifest_digest': parent['digest'], 'platform': config['platform'],
              'source_sha': source_sha, 'source_blob': blob, 'branch': config['alpine_branch'], 'package': config['package'],
              'scan_report_id': summary['report_id'], 'scan_generated_at': generated,
              'scan_end_time': summary['end_time'], 'scan_url': config['harbor']['url'] + path + '/additions/vulnerabilities',
              'fixes': sorted(fixes, key=lambda v: v['id']), 'apk_index': index, 'secdb': secdb}
    result['qualification_id'] = identity({k: result[k] for k in ('runtime_manifest_digest', 'platform', 'branch', 'package', 'fixes')})
    return result


def git_prepare(config, section, branch=None):
    scope = config[section]
    directory = Path(scope['mirror_path']).expanduser()
    require(directory.is_dir(), 'trusted bare mirror is missing')
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(directory)]
    require(run(command + ['rev-parse', '--is-bare-repository']).strip() == 'true', 'trusted mirror must be bare')
    require(run(command + ['remote', 'get-url', 'origin']).strip() == scope['remote_url'], 'trusted mirror origin differs')
    reference = branch or scope['branch']
    require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', reference) and '..' not in reference, 'invalid trusted fetch ref')
    run(command + ['fetch', '--no-tags', 'origin', 'refs/heads/' + reference])
    return command


def git_ancestor(command, ancestor, descendant):
    require(all(re.fullmatch(r'[0-9a-f]{40}', v) for v in (ancestor, descendant)), 'ancestry SHA invalid')
    base = run(command + ['merge-base', '--all', ancestor, descendant]).strip()
    require(base == ancestor, 'accepted revision is not a proven release descendant')
    return 'identical' if ancestor == descendant else 'ahead'


def only_source_file(command, before, after, path):
    require(all(re.fullmatch(r'[0-9a-f]{40}', v) for v in (before, after)), 'source comparison SHA invalid')
    files = run(command + ['diff', '--no-ext-diff', '--no-textconv', '--name-only', '--no-renames', before, after, '--']).splitlines()
    require(files == [path], 'proposal branch changes another file')


def pin(api, config, ref):
    import yaml
    contents, blob = api.contents(config['gitops']['repo'], config['gitops']['image_file'], ref)
    value = yaml.safe_load(contents)
    matches = [v for v in value.get('images', []) if v.get('newName') == config['image_repository']]
    require(len(matches) == 1, 'expected one Kustomize image pin')
    tag = matches[0].get('newTag')
    require(isinstance(tag, str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', tag), 'GitOps image tag is not exact')
    require('digest' not in matches[0], 'ambiguous tag/digest Kustomize pin')
    return config['image_repository'] + ':' + tag, blob


def workflow_policy(api, repo, ref, branch, event, expected):
    import yaml
    listing = api.forge(repo, '/contents/.forgejo/workflows?' + urlencode({'ref': ref}))
    require(isinstance(listing, list), 'workflow directory missing')
    applicable = set()
    for entry in listing:
        if entry.get('type') != 'file' or not entry.get('name', '').endswith(('.yaml', '.yml')):
            continue
        contents, _ = api.contents(repo, '.forgejo/workflows/' + entry['name'], ref)
        value = yaml.load(contents, Loader=yaml.BaseLoader)
        triggers = value.get('on', {})
        if isinstance(triggers, str):
            triggers = {triggers: {}}
        elif isinstance(triggers, list):
            triggers = {name: {} for name in triggers}
        require(isinstance(triggers, dict), 'workflow triggers invalid')
        if event not in triggers:
            continue
        options = triggers[event] or {}
        require(isinstance(options, dict), 'workflow trigger options invalid')
        if event == 'push' and ('tags' in options or 'tags-ignore' in options) and 'branches' not in options and 'branches-ignore' not in options:
            continue
        included, excluded = options.get('branches', ['*']), options.get('branches-ignore', [])
        if not any(fnmatch.fnmatchcase(branch, pattern) for pattern in included) or any(fnmatch.fnmatchcase(branch, pattern) for pattern in excluded):
            continue
        # Path-filtered workflows are conservatively required: an operator may
        # widen the expected list but cannot silently omit an applicable gate.
        applicable.add(entry['name'])
    require(applicable and applicable == {Path(v).name for v in expected}, 'workflow policy changed; review expected checks before continuing')


def success_statuses(api, repo, sha, required):
    combined = api.forge(repo, '/commits/' + sha + '/status')
    require(combined.get('sha', sha) == sha, 'combined status is for another SHA')
    statuses = api.pages(repo, '/commits/' + sha + '/statuses')
    selected = {}
    for value in statuses:
        require(value.get('sha', sha) == sha, 'status is for another SHA')
        context = value.get('context')
        if context not in selected or value.get('id', 0) > selected[context].get('id', 0):
            selected[context] = value
    result = []
    for context in required:
        value = selected.get(context, {})
        require(value.get('status') == 'success' and str(value.get('target_url', '')).startswith('https://'), 'required commit status is not successful')
        result.append({'context': context, 'status': 'success', 'sha': sha, 'url': value['target_url']})
    return result


def success_runs(api, repo, sha, event, workflows):
    require(isinstance(workflows, list) and workflows, 'expected workflow list is empty')
    runs = api.pages(repo, '/actions/runs?' + urlencode({'head_sha': sha}), 'workflow_runs')
    selected = {}
    for run_value in runs:
        require(run_value.get('commit_sha') == sha, 'Actions returned a different SHA')
        if run_value.get('event') != event:
            continue
        key = Path(str(run_value.get('workflow_id'))).name
        if key not in selected or run_value['id'] > selected[key]['id']:
            selected[key] = run_value
    result = []
    for workflow in workflows:
        value = selected.get(Path(str(workflow)).name, {})
        status = value.get('status')
        require(status == 'success' or (status == 'completed' and value.get('conclusion') == 'success'), 'required workflow is missing or not successful')
        require(str(value.get('html_url', '')).startswith('https://'), 'workflow evidence URL missing')
        result.append({'context': 'workflow:' + str(workflow), 'status': 'success', 'sha': sha,
                       'url': value['html_url'], 'run_id': value['id'], 'event': event})
    return result


def merged_pr(api, repo, sha, branch):
    try:
        value = api.forge(repo, '/commits/' + sha + '/pull')
    except NotFound:
        return None
    require(value.get('merged') is True and value.get('merge_commit_sha') == sha
            and value.get('base', {}).get('ref') == branch, 'associated PR does not prove exact merged source/target')
    return value


def release_candidate(api, config, receipt):
    gitops = config['gitops']
    repo, branch = gitops['repo'], gitops['branch']
    observed_revision = receipt['observation']['flux']['revision']
    require(re.fullmatch(re.escape(branch) + r'@sha1:[0-9a-f]{40}', observed_revision), 'observed GitOps revision invalid')
    applied = observed_revision.rsplit(':', 1)[1]
    applied_image, _ = pin(api, config, applied)
    default = api.forge(repo, '/branches/' + quote(branch, safe=''))['commit']['id']
    desired, _ = pin(api, config, default)
    accepted = applied if applied_image == desired else default
    desired, accepted_blob = pin(api, config, accepted)
    git_command = git_prepare(config, 'gitops')
    git_ancestor(git_command, accepted, default)
    changes = api.iter_pages(repo, '/commits?' + urlencode({'sha': accepted, 'path': gitops['image_file']}))
    release = None
    for commit in changes:
        sha = commit['sha']
        image, _ = pin(api, config, sha)
        if image != desired:
            break
        details = api.forge(repo, '/git/commits/' + sha)
        parents = details.get('parents', [])
        require(parents, 'pin commit parent missing')
        previous, _ = pin(api, config, parents[0]['sha'])
        if previous == image:
            continue
        release = merged_pr(api, repo, sha, branch)
        require(release is not None, 'pin-changing commit has no merged PR evidence')
        break
    if release is None:
        return None
    source, merge = release['head']['sha'], release['merge_commit_sha']
    require(release.get('merged') is True and release['base']['ref'] == branch, 'release PR is not merged into expected branch')
    source_image, _ = pin(api, config, source)
    require(source_image == desired, 'PR source image does not bind deployed pin')
    relation = git_ancestor(git_command, merge, accepted)
    protection = api.forge(repo, '/branch_protections/' + quote(branch, safe=''))
    require(protection.get('enable_status_check') is True, 'GitOps branch status protection is disabled')
    required = protection.get('status_check_contexts', [])
    require(required and set(required) <= set(gitops['pr_status_contexts']), 'configured checks do not cover branch protection')
    workflow_policy(api, repo, source, branch, 'pull_request', gitops['pr_workflows'])
    workflow_policy(api, repo, merge, branch, 'push', gitops['post_workflows'])
    pr_ci = success_statuses(api, repo, source, sorted(set(required) | set(gitops['pr_status_contexts'])))
    pr_ci += success_runs(api, repo, source, 'pull_request', gitops['pr_workflows'])
    post_ci = success_statuses(api, repo, merge, gitops.get('post_status_contexts', []))
    post_ci += success_runs(api, repo, merge, 'push', gitops['post_workflows'])
    top, child, artifact_path = platform_artifact(api, config, desired.rsplit(':', 1)[1])
    producer_sha = source_revision(config, child)
    runtime_digest = top['digest']
    if receipt['observation']['digests'] == [child['digest']]:
        runtime_digest = child['digest']
    producer = config['source']
    producer_pr = merged_pr(api, producer['repo'], producer_sha, producer['branch'])
    require(producer_pr is not None, 'published producer revision has no exact merged PR')
    producer_protection = api.forge(producer['repo'], '/branch_protections/' + quote(producer['branch'], safe=''))
    require(producer_protection.get('enable_status_check') is True, 'producer branch protection is disabled')
    producer_required = producer_protection.get('status_check_contexts', [])
    require(producer_required and set(producer_required) <= set(producer['pr_status_contexts']), 'producer check configuration omits protected checks')
    workflow_policy(api, producer['repo'], producer_pr['head']['sha'], producer['branch'], 'pull_request', producer['pr_workflows'])
    workflow_policy(api, producer['repo'], producer_sha, producer['branch'], 'push', producer['post_workflows'])
    producer_checks = success_statuses(api, producer['repo'], producer_pr['head']['sha'], sorted(set(producer_required) | set(producer['pr_status_contexts'])))
    producer_checks += success_runs(api, producer['repo'], producer_pr['head']['sha'], 'pull_request', producer['pr_workflows'])
    require(producer.get('post_status_contexts'), 'producer publication status policy missing')
    producer_checks += success_statuses(api, producer['repo'], producer_sha, producer['post_status_contexts'])
    producer_checks += success_runs(api, producer['repo'], producer_sha, 'push', producer['post_workflows'])
    candidate = {'schema_version': 1, 'target': config['target'], 'expected_revision': branch + '@sha1:' + accepted,
                 'desired_image': desired, 'release': {'pr': release['number'], 'source_sha': source, 'merge_sha': merge,
                 'gitops_revision_sha': accepted, 'required_ci': post_ci, 'pr_ci': pr_ci,
                 'protection': {'required_contexts': required, 'checked_at': now()}},
                 'registry_evidence': {'tag_ref': desired, 'manifest_digest': top['digest'], 'runtime_manifest_digest': runtime_digest, 'platform_manifest_digest': child['digest'],
                 'url': config['harbor']['url'] + artifact_path},
                 'producer_evidence': {'revision_sha': producer_sha, 'pr': producer_pr['number'], 'checks': producer_checks,
                 'protection': {'required_contexts': producer_required, 'checked_at': now()}},
                 'revision_evidence': {'release_merge_sha': merge, 'revision_sha': accepted, 'relation': relation, 'method': 'git-merge-base',
                 'compare_url': config['forgejo']['url'] + '/' + repo + '/compare/' + merge + '...' + accepted,
                 'desired_image': desired, 'file': gitops['image_file'], 'blob_sha': accepted_blob}}
    return candidate


def strict_source(config, contents):
    epoch_line(contents)
    require(len(re.findall(r'^ARG PYTHON_BASE_IMAGE=library/python:3\.14-alpine3\.24$', contents, re.M)) == 1, 'source Python base series drifted')
    contents = '\n'.join(line for line in contents.splitlines() if not line.lstrip().startswith('#'))
    require('"${VERSION_ID%.*}" = "3.24"' in contents, 'source lacks supported Alpine 3.24 runtime guard')
    require('apk list --installed libxml2' in contents
            and 'apk version -t "${installed#libxml2-}" 2.13.9-r3' in contents, 'source lacks supported installed libxml2 minimum guard')


def propose(api, config, qualification, state, write=False):
    source = config['source']
    repo, path = source['repo'], source['dockerfile']
    head = api.forge(repo, '/branches/' + quote(source['branch'], safe=''))['commit']['id']
    contents, blob = api.contents(repo, path, head)
    bootstrap_pr = config.get('legacy_baseline', {}).get('producer_pr')
    if bootstrap_pr and qualification['platform_manifest_digest'] == config['legacy_baseline']['runtime_manifest_digest']:
        pr = api.forge(repo, '/pulls/' + str(bootstrap_pr))
        require(pr['base']['ref'] == source['branch'], 'bootstrap PR target differs')
        bootstrap_source, _ = api.contents(repo, path, pr['head']['sha'])
        strict_source(config, bootstrap_source)
        if pr.get('state') == 'open':
            return {'status': 'covered-by-bootstrap-pr', 'pr': bootstrap_pr, 'url': pr['html_url'], 'head_sha': pr['head']['sha']}
        require(pr.get('merged') is True, 'bootstrap producer PR was closed without merge')
        return {'status': 'bootstrap-merged-awaiting-rollout', 'pr': bootstrap_pr, 'url': pr['html_url'], 'head_sha': pr['head']['sha']}
    strict_source(config, contents)
    key = qualification['qualification_id']
    branch = 'maintenance/apk-' + key[:20]
    open_prs = api.pages(repo, '/pulls?state=open')
    for pr in open_prs:
        if pr['base']['ref'] != source['branch']:
            continue
        files = api.pages(repo, '/pulls/' + str(pr['number']) + '/files')
        if len(files) != 1 or files[0].get('filename') != path or files[0].get('status') not in ('modified', 'changed'):
            continue
        proposed, _ = api.contents(repo, path, pr['head']['sha'])
        try:
            epoch_only(contents, proposed)
        except (Rejected, ValueError):
            continue
        state['proposals'][key] = {'status': 'existing', 'pr': pr['number'], 'url': pr['html_url'], 'head_sha': pr['head']['sha']}
        return state['proposals'][key]
    if key in state['proposals']:
        return state['proposals'][key]
    proposed = advance_epoch(contents, date.today().isoformat())
    decision = {'status': 'qualified', 'branch': branch, 'base_sha': head, 'file': path, 'old_blob': blob,
                'new_content_sha256': hashlib.sha256(proposed.encode()).hexdigest(), 'qualification_id': key,
                'content': proposed, 'diff': ''.join(difflib.unified_diff(contents.splitlines(keepends=True), proposed.splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path))}
    if not write:
        return decision
    if config.get('proposal_enabled') is not True or not source.get('proposal_auth_command'):
        decision.update(status='awaiting-authorization', reason='separately authorized repository-scoped proposal write grant missing')
        state.setdefault('decisions', {})[key] = decision
        return decision
    # The only write endpoints: a deterministic source branch, its one Dockerfile,
    # and a PR. No merge, protection, secrets, settings or arbitrary file writes.
    author = source.get('commit_author', {})
    require(isinstance(author.get('name'), str) and author['name'] and isinstance(author.get('email'), str) and '@' in author['email'], 'source commit author is missing')
    branches = api.pages(repo, '/branches')
    existing = [b for b in branches if b['name'] == branch]
    git_prepare(config, 'source')
    if existing:
        branch_sha = existing[0]['commit']['id']
        on_branch, _ = api.contents(repo, path, branch_sha)
        git_command = git_prepare(config, 'source', branch)
        if branch_sha != head:
            only_source_file(git_command, head, branch_sha, path)
        if branch_sha == head:
            update = api.forge(repo, '/contents/' + quote(path, safe='/'),
                               {'branch': branch, 'sha': blob, 'author': author, 'committer': author, 'content': base64.b64encode(proposed.encode()).decode(),
                                'message': 'chore: refresh qualified Alpine OS packages'}, 'PUT')
            branch_sha = update['commit']['sha']
            on_branch, _ = api.contents(repo, path, branch_sha)
            git_command = git_prepare(config, 'source', branch)
            only_source_file(git_command, head, branch_sha, path)
        epoch_only(contents, on_branch)
        proposed = on_branch
    else:
        # Check base again immediately before creating the branch.
        require(api.forge(repo, '/branches/' + quote(source['branch'], safe=''))['commit']['id'] == head, 'source base changed')
        api.forge(repo, '/branches', {'new_branch_name': branch, 'old_ref_name': head}, 'POST')
        update = api.forge(repo, '/contents/' + quote(path, safe='/'),
                           {'branch': branch, 'sha': blob, 'author': author, 'committer': author, 'content': base64.b64encode(proposed.encode()).decode(),
                            'message': 'chore: refresh qualified Alpine OS packages'}, 'PUT')
        branch_sha = update['commit']['sha']
        verified, _ = api.contents(repo, path, branch_sha)
        epoch_only(contents, verified)
        git_command = git_prepare(config, 'source', branch)
        only_source_file(git_command, head, branch_sha, path)
    body = ('Qualified immutable deployed image: `' + qualification['runtime_manifest_digest'] + '` (' + qualification['platform'] + ').\n\n'
            'Successful fresh Harbor report: `' + qualification['scan_report_id'] + '`. Official same-branch index: ' + qualification['apk_index']['url'] + '.\n\n'
            'Only the anchored APK_PATCH_EPOCH date advances. Source merging requires operator approval; this controller cannot merge.\n\n'
            'Qualification: `' + key + '`.')
    result = api.forge(repo, '/pulls', {'base': source['branch'], 'head': branch, 'title': 'chore: refresh qualified Alpine libxml2 fix', 'body': body}, 'POST')
    decision.update(status='opened', pr=result['number'], url=result['html_url'], head_sha=branch_sha)
    state['proposals'][key] = decision
    return decision


def registry_unchanged(api, config, candidate):
    tag = candidate['desired_image'].rsplit(':', 1)[1]
    parent, child, _ = platform_artifact(api, config, tag)
    require(parent['digest'] == candidate['registry_evidence']['manifest_digest']
            and child['digest'] == candidate['registry_evidence']['platform_manifest_digest'], 'registry tag changed during handoff')


def same_deployment(first, second):
    keys = ('flux', 'deployment', 'digests')
    require(all(first['observation'][key] == second['observation'][key] for key in keys), 'deployed release changed during qualification')


def tick(config, state_path, check=False, qualification_only=False):
    state = json.loads(state_path.read_text()) if state_path.exists() else {'schema_version': 1, 'proposals': {}, 'verified': {}}
    require(state.get('schema_version') == 1, 'state schema invalid')
    api = HTTP(config)
    output = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(), 'mode': 'check' if check else 'once'}
    observation = observe(config)
    qualification_error = None
    try:
        qualification = qualify(api, config, observation)
        output['qualification'] = qualification
        if qualification:
            same_deployment(observation, observe(config))
            output['proposal'] = propose(api, config, qualification, state, write=not check)
    except (Rejected, KeyError, ValueError, TypeError, AttributeError) as exc:
        qualification_error = str(exc)
        output['qualification_error'] = qualification_error
    if not qualification_only:
        try:
            candidate = release_candidate(api, config, observation)
            if candidate:
                # Volatile timestamps are audit evidence, not candidate identity.
                key = identity({'revision': candidate['expected_revision'], 'image': candidate['desired_image'],
                                'registry': candidate['registry_evidence'], 'source': candidate['producer_evidence']['revision_sha']})
                output['release_id'] = key
                current = observation.get('observation', {})
                still_current = (current.get('flux', {}).get('revision') == candidate['expected_revision']
                                 and current.get('deployment', {}).get('image') == candidate['desired_image']
                                 and current.get('digests') == [candidate['registry_evidence']['runtime_manifest_digest']])
                if key in state['verified'] and still_current:
                    output['handoff'] = 'already-verified'
                elif check:
                    output.update(handoff='ready', candidate=candidate)
                else:
                    state['pending'] = {'release_id': key, 'candidate': candidate}
                    atomic_json(state_path, state)
                    registry_unchanged(api, config, candidate)
                    started = now()
                    receipt = observe(config, candidate)
                    verify_receipt(receipt, candidate, started)
                    registry_unchanged(api, config, candidate)
                    receipt_path = state_path.parent / 'verified' / (key + '.json')
                    atomic_json(receipt_path, receipt)
                    require(json.loads(receipt_path.read_text()) == receipt, 'receipt readback failed')
                    state['verified'][key] = {'candidate_id': identity(candidate), 'receipt': str(receipt_path), 'verified_at': receipt['observed_at']}
                    state.pop('pending', None)
                    output['handoff'] = 'verified'
            else:
                output['handoff'] = 'no-app-release'
        except (Rejected, KeyError, ValueError, TypeError, AttributeError) as exc:
            output['handoff'] = 'pending'
            output['handoff_error'] = str(exc)
    if not check:
        state['latest'] = output
        atomic_json(state_path, state)
    output['status'] = 'blocked' if qualification_error or output.get('handoff_error') else 'ok'
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='fresh read-only qualification/release preview; no proposal, transport verify or state mutation')
    action.add_argument('--once', action='store_true', help='one bounded scheduled pass; failures retry on next invocation')
    parser.add_argument('--qualify-only', action='store_true', help='skip release verification')
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'pi-yt-maintenance/config.json')
    parser.add_argument('--state-dir', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'pi-yt-maintenance')
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.check:
            output = tick(config, args.state_dir / 'state.json', check=True, qualification_only=args.qualify_only)
        else:
            args.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            with (args.state_dir / 'controller.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    print(json.dumps({'schema_version': 1, 'status': 'busy'}))
                    return 0
                output = tick(config, args.state_dir / 'state.json', qualification_only=args.qualify_only)
        print(json.dumps(output, sort_keys=True))
        return 0 if output['status'] == 'ok' else 1
    except (Rejected, OSError, KeyError, ValueError, TypeError, AttributeError, ImportError) as exc:
        # Helpers' stderr/auth material are never included in reports.
        print(json.dumps({'schema_version': 1, 'status': 'blocked', 'error': str(exc) if isinstance(exc, Rejected) else type(exc).__name__}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
