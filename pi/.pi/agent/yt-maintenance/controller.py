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
import importlib.util
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


def approved_source(config):
    source = config['source']
    module = signing_module()
    try:
        branch, contexts = module.source_policy(source['repo'])
    except ValueError as exc:
        raise Rejected('source repository is outside approved policy') from exc
    require(source['branch'] == branch and source['dockerfile'] == 'Dockerfile', 'source scope differs from immutable policy')
    return branch, contexts


def site_policy(config):
    repo = config.get('source', {}).get('repo')
    module = signing_module()
    if repo not in module.SITE_POLICIES:
        return None
    branch, app = module.SITE_POLICIES[repo]
    approved_source(config)
    expected = {'context': 'bay', 'flux_namespace': 'flux-system', 'kustomization': app,
                'namespace': app, 'deployment': app, 'container': 'nginx'}
    require(config['target'] == expected, 'site observer target differs from immutable policy')
    require(config['image_repository'].endswith('/library/' + app + '-frontend')
            and config['harbor']['repository'] == 'library/' + app + '-frontend', 'site image differs from immutable policy')
    require(config['gitops']['image_file'] == app + '/overlays/prod/kustomization.yaml', 'site overlay differs from immutable policy')
    require(config['platform'] == 'linux/amd64', 'site platform differs from approved policy')
    return app


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
    if config['source']['repo'] in signing_module().SITE_POLICIES:
        site_policy(config)
    elif config.get('signing_enabled') is True:
        approved_source(config)
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
                return payload if raw else (json.loads(payload) if payload else None)
        except (HTTPError, URLError, TimeoutError) as exc:
            code = getattr(exc, 'code', 'network')
            if code == 404:
                raise NotFound(f'{service} evidence not found') from exc
            raise Rejected(f'{service} request failed ({code})') from exc

    def forge(self, repo, suffix, body=None, method='GET'):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid repository scope')
        headers = None
        source = self.config['source']
        comment_read = (method == 'GET' and repo == source['repo'] and self.config.get('proposal_enabled') is True
                        and source.get('proposal_auth_command') and re.fullmatch(r'/issues/(?:[1-9][0-9]*/comments|comments/[1-9][0-9]*)', suffix) is not None)
        if method != 'GET' or comment_read:
            allowed = (method, suffix.split('?', 1)[0]) in {
                ('POST', '/branches'), ('POST', '/pulls'),
                ('PUT', '/contents/' + quote(source['dockerfile'], safe='/'))}
            allowed = allowed or comment_read
            allowed = allowed or (method == 'POST' and re.fullmatch(r'/issues/[1-9][0-9]*/comments', suffix) is not None)
            allowed = allowed or (method == 'PATCH' and re.fullmatch(r'/issues/comments/[1-9][0-9]*', suffix) is not None)
            allowed = allowed or (method == 'POST' and re.fullmatch(r'/pulls/[1-9][0-9]*/update\?style=rebase', suffix) is not None)
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
    app = site_policy(config)
    if app:
        command.append(app)
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
    for ref in (before, after):
        tree = run(command + ['ls-tree', ref, '--', path]).strip()
        require(re.fullmatch(r'100644 blob [0-9a-f]{40}\t' + re.escape(path), tree), 'proposal file must remain a regular nonexecutable Git blob')


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


def evidence_url(base_url, repo, value):
    require(isinstance(value, str) and value and not any(ord(char) <= 32 or ord(char) == 127 for char in value)
            and '\\' not in value, 'invalid CI evidence URL characters')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'invalid CI evidence repository')
    try:
        base = urlsplit(base_url)
        require(base.scheme == 'https' and base.hostname and not base.username and not base.password
                and base.path in ('', '/') and not base.query and not base.fragment, 'invalid trusted CI evidence URL origin')
        origin_port = 443 if base.port is None else base.port
        require(0 < origin_port <= 65535, 'invalid trusted CI evidence URL port')
        require(not value.startswith('//'), 'protocol-relative CI evidence URL refused')
        parsed = urlsplit(value)
        if value.startswith('/'):
            require(not parsed.scheme and not parsed.netloc, 'invalid root-relative CI evidence URL')
        else:
            require(parsed.scheme == 'https' and parsed.hostname == base.hostname and (443 if parsed.port is None else parsed.port) == origin_port
                    and not parsed.username and not parsed.password, 'CI evidence URL origin differs from trusted Forgejo')
        require(not parsed.query and not parsed.fragment, 'CI evidence URL query or fragment refused')
        require(re.fullmatch('/' + re.escape(repo) + r'/actions/runs/[1-9][0-9]*(?:/jobs/[0-9]+)?', parsed.path),
                'CI evidence URL is not the expected repository Actions path')
        host = '[' + base.hostname + ']' if ':' in base.hostname else base.hostname
        origin = 'https://' + host + (':' + str(origin_port) if origin_port != 443 else '')
        return origin + parsed.path
    except ValueError as exc:
        if isinstance(exc, Rejected):
            raise
        raise Rejected('invalid CI evidence URL syntax') from exc


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
        require(value.get('status') == 'success', f'required commit status {context!r} on {sha} is {value.get("status", "missing")}')
        url = evidence_url(api.config['forgejo']['url'], repo, value.get('target_url'))
        result.append({'context': context, 'status': 'success', 'sha': sha, 'url': url})
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
        require(status == 'success' or (status == 'completed' and value.get('conclusion') == 'success'),
                f'required workflow {workflow!r} ({event}) on {sha} is {status or "missing"}, conclusion {value.get("conclusion")}')
        url = evidence_url(api.config['forgejo']['url'], repo, value.get('html_url'))
        result.append({'context': 'workflow:' + str(workflow), 'status': 'success', 'sha': sha,
                       'url': url, 'run_id': value['id'], 'event': event})
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
    require(isinstance(gitops.get('post_status_contexts'), list) and gitops['post_status_contexts'], 'GitOps post-merge status policy missing')
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
    post_ci = success_statuses(api, repo, merge, gitops['post_status_contexts'])
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
    if config['source']['repo'] in signing_module().SITE_POLICIES:
        require(len(re.findall(r'^FROM nginxinc/nginx-unprivileged:[A-Za-z0-9_.-]*alpine3\.24(?:@sha256:[0-9a-f]{64})?$', contents, re.M)) == 1, 'source nginx Alpine base series drifted')
    else:
        require(len(re.findall(r'^ARG PYTHON_BASE_IMAGE=library/python:3\.14-alpine3\.24$', contents, re.M)) == 1, 'source Python base series drifted')
    contents = '\n'.join(line for line in contents.splitlines() if not line.lstrip().startswith('#'))
    if config['source']['repo'] in signing_module().SITE_POLICIES:
        require('[ "${VERSION_ID%.*}" = 3.24 ]' in contents, 'source lacks supported Alpine 3.24 runtime guard')
    else:
        require('"${VERSION_ID%.*}" = "3.24"' in contents, 'source lacks supported Alpine 3.24 runtime guard')
    require('apk list --installed libxml2' in contents
            and 'apk version -t "${installed#libxml2-}" 2.13.9-r3' in contents, 'source lacks supported installed libxml2 minimum guard')


def signing_module():
    path = Path(__file__).resolve().parent / 'proposal_signing.py'
    spec = importlib.util.spec_from_file_location('pi_yt_proposal_signing', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proposal_scope(config, pr, branch, record):
    source = config['source']
    approved_source(config)
    require(record.get('owned') is True and record.get('pr') == pr['number'] and record.get('branch') == branch,
            'PR was not created and recorded by this controller')
    require(pr.get('state') == 'open' and pr.get('merged') is not True, 'signed PR is no longer open')
    require(pr.get('user', {}).get('login') == source.get('proposal_actor') and source.get('proposal_actor') and source['proposal_actor'] != 'linroot', 'PR author is not the dedicated proposal actor')
    require(pr['base']['ref'] == source['branch'] and pr['base']['repo']['full_name'] == source['repo']
            and pr['head']['ref'] == branch and pr['head']['repo']['full_name'] == source['repo'], 'PR source/target repository or branch differs')
    require(pr['head']['sha'] == record.get('head_sha'), 'PR head changed outside this controller')


def recover_proposal(api, config, qualification, intent, pr, checkpoint):
    source = config['source']
    repo = source['repo']
    branch = 'maintenance/apk-' + qualification['qualification_id'][:20]
    require(intent.get('intent') is True and intent.get('post_ready') is True
            and intent.get('repository') == repo and intent.get('proposal_actor') == source.get('proposal_actor')
            and intent.get('branch') == branch, 'proposal intent does not prove controller creation')
    require(pr['head']['sha'] == intent.get('head_sha') and pr['base'].get('sha') == intent.get('base_sha')
            and api.forge(repo, '/branches/' + source['branch'])['commit']['id'] == intent['base_sha'], 'interrupted proposal no longer matches exact intended base/head')
    record = dict(intent, owned=True, pr=pr['number'], url=pr['html_url'], status='recovered', signed=False)
    proposal_scope(config, pr, branch, record)
    before, _ = api.contents(repo, 'Dockerfile', intent['base_sha'])
    after, _ = api.contents(repo, 'Dockerfile', intent['head_sha'])
    require(hashlib.sha256(after.encode()).hexdigest() == intent.get('proposed_sha256'), 'interrupted proposal bytes differ from persisted intent')
    epoch_only(before, after)
    command = git_prepare(config, 'source', branch)
    git_prepare(config, 'source')
    only_source_file(command, intent['base_sha'], intent['head_sha'], 'Dockerfile')
    files = api.pages(repo, '/pulls/' + str(pr['number']) + '/files')
    require(len(files) == 1 and files[0].get('filename') == 'Dockerfile'
            and files[0].get('status') in ('modified', 'changed'), 'interrupted proposal file scope differs')
    first = observe(config)
    fresh_qualification = qualify(api, config, first)
    require(fresh_qualification is not None and fresh_qualification['qualification_id'] == qualification['qualification_id'], 'production fix changed before ownership recovery')
    same_deployment(first, observe(config))
    require(api.forge(repo, '/pulls/' + str(pr['number']))['head']['sha'] == intent['head_sha']
            and api.forge(repo, '/branches/' + source['branch'])['commit']['id'] == intent['base_sha'], 'proposal moved during ownership recovery')
    return record


def matching_signed_comment(module, key, comment, payload, actor):
    if comment.get('user', {}).get('login') != actor:
        return False
    try:
        previous = module.verify_comment(comment.get('body'), key.public_key(), at=now(), allow_expired=True, repository=payload['repository'])
    except (ValueError, TypeError, KeyError):
        return False
    fields = ('repository', 'target', 'pr_number', 'base_sha', 'head_sha', 'path',
              'before_sha256', 'after_sha256', 'old_epoch', 'new_epoch')
    return (all(previous.get(field) == payload[field] for field in fields)
            and previous['qualification']['qualification_id'] == payload['qualification']['qualification_id'])


def protection_snapshot(api, config, base_sha):
    source = config['source']
    branch, contexts_policy = approved_source(config)
    module = signing_module()
    repo = source['repo']
    first = api.forge(repo, '/branches/' + source['branch'])
    fields = ('name', 'protected', 'enable_status_check', 'effective_branch_protection_name', 'status_check_contexts')
    require(first.get('name') == branch and first.get('protected') is True
            and first.get('enable_status_check') is True and first.get('effective_branch_protection_name') == branch
            and first.get('commit', {}).get('id') == base_sha, 'live effective default-branch protection/base is missing or differs')
    contexts = first.get('status_check_contexts')
    require(isinstance(contexts, list) and len(contexts) == len(contexts_policy) and set(contexts) == set(contexts_policy), 'live branch protection does not expose exact policy contexts')
    rule = api.forge(repo, '/branch_protections/' + source['branch'])
    require(rule.get('branch_name') == branch and rule.get('rule_name', branch) == branch, 'authoritative protection rule is not the exact default branch')
    required = rule.get('status_check_contexts')
    require(isinstance(required, list) and len(required) == len(contexts_policy) and set(required) == set(contexts_policy), 'authoritative protection contexts differ from exact policy checks')
    flags = ('apply_to_admins', 'block_on_outdated_branch', 'enable_status_check')
    require(all(rule.get(field) is True for field in flags), 'authoritative default-branch protection enforcement flags are not all true')
    second = api.forge(repo, '/branches/' + source['branch'])
    require(all(first.get(field) == second.get(field) for field in fields)
            and second.get('commit', {}).get('id') == base_sha, 'default-branch protection/base changed during authoritative read')
    result = {'repository': repo, 'branch': branch, 'base_sha': base_sha, 'checked_at': now(),
              'status_check_contexts': sorted(required), **{field: rule[field] for field in flags}}
    module.validate_protection(result, base_sha, now(), repo)
    return result


def refresh_proof(api, config, qualification, record, checkpoint):
    source, repo = config['source'], config['source']['repo']
    module = signing_module()
    require(source.get('signing_key_file') and source.get('signing_public_key_sha256'), 'trusted workstation signing key policy missing')
    require(config.get('signing_enabled') is True, 'source automatic merge signing is disabled')
    pr = api.forge(repo, '/pulls/' + str(record['pr']))
    branch = 'maintenance/apk-' + qualification['qualification_id'][:20]
    proposal_scope(config, pr, branch, record)
    current = api.forge(repo, '/branches/' + source['branch'])['commit']['id']
    before, _ = api.contents(repo, 'Dockerfile', current)
    strict_source(config, before)
    after, _ = api.contents(repo, 'Dockerfile', pr['head']['sha'])
    previous_base = record['base_sha']
    previous, _ = api.contents(repo, 'Dockerfile', previous_base)
    epoch_only(previous, after)
    command = git_prepare(config, 'source', branch)
    git_prepare(config, 'source')
    only_source_file(command, previous_base, pr['head']['sha'], 'Dockerfile')
    if previous_base != current:
        git_ancestor(command, previous_base, current)
        if epoch_line(before)[2] >= epoch_line(after)[2]:
            record.update(status='obsolete-awaiting-rollout', signed=False)
            checkpoint()
            return record
        expected_after = advance_epoch(before, epoch_line(after)[2].isoformat())
        require(api.forge(repo, '/pulls/' + str(record['pr']))['head']['sha'] == pr['head']['sha'], 'PR changed before rebase')
        require(api.forge(repo, '/branches/' + source['branch'])['commit']['id'] == current, 'source base changed before rebase')
        api.forge(repo, '/pulls/' + str(record['pr']) + '/update?style=rebase', None, 'POST')
        pr = api.forge(repo, '/pulls/' + str(record['pr']))
        record.update(head_sha=pr['head']['sha'], base_sha=current, signed=False)
        checkpoint()
        proposal_scope(config, pr, branch, record)
        command = git_prepare(config, 'source', branch)
        after, _ = api.contents(repo, 'Dockerfile', pr['head']['sha'])
        require(after == expected_after, 'rebased proposal content differs from exact original epoch refresh')
    epoch_only(before, after)
    only_source_file(command, current, pr['head']['sha'], 'Dockerfile')
    files = api.pages(repo, '/pulls/' + str(record['pr']) + '/files')
    require(len(files) == 1 and files[0].get('filename') == 'Dockerfile'
            and files[0].get('status') in ('modified', 'changed'), 'PR file scope differs before signing')
    # Signing is a second independent production qualification, not a cache hit.
    first = observe(config)
    fresh_qualification = qualify(api, config, first)
    require(fresh_qualification is not None and fresh_qualification['qualification_id'] == qualification['qualification_id'], 'production fix changed before signing')
    same_deployment(first, observe(config))
    require(api.forge(repo, '/branches/' + source['branch'])['commit']['id'] == current, 'source base changed before signing')
    final_pr = api.forge(repo, '/pulls/' + str(record['pr']))
    proposal_scope(config, final_pr, branch, record)
    protection = protection_snapshot(api, config, current)
    key = module.load_private(source['signing_key_file'], source['signing_public_key_sha256'])
    payload = module.bound_payload(fresh_qualification, branch, current, final_pr['head']['sha'], record['pr'], before, after, issued=now(), protection=protection, repository=repo)
    body = module.signed_comment(payload, key)
    comment = None
    if record.get('comment_id'):
        try:
            comment = api.forge(repo, '/issues/comments/' + str(record['comment_id']))
        except NotFound:
            pass
        if comment is not None:
            require(matching_signed_comment(module, key, comment, payload, source['proposal_actor']), 'recorded signature comment is not authentic matching controller proof')
    if comment is None:
        comments = api.forge(repo, '/issues/' + str(record['pr']) + '/comments')
        require(isinstance(comments, list) and len(comments) <= 1000, 'signature comment recovery response exceeds bound')
        matching = [value for value in comments if matching_signed_comment(module, key, value, payload, source['proposal_actor'])]
        if matching:
            comment = max(matching, key=lambda value: value['id'])
            record.update(comment_id=comment['id'], comment_body=comment['body'])
            checkpoint()
    record['pending_comment_body'] = body
    checkpoint()
    if comment is None:
        comment = api.forge(repo, '/issues/' + str(record['pr']) + '/comments', {'body': body}, 'POST')
    else:
        comment = api.forge(repo, '/issues/comments/' + str(comment['id']), {'body': body}, 'PATCH')
    comment_id = comment['id']
    readback = api.forge(repo, '/issues/comments/' + str(comment_id))
    require(readback.get('body') == body and readback.get('user', {}).get('login') == source['proposal_actor'], 'signed comment readback differs')
    require(module.verify_comment(body, key.public_key(), at=now(), repository=repo) == payload, 'signed payload readback differs')
    record.pop('pending_comment_body', None)
    record.update(status='signed', signed=True, comment_id=comment_id, comment_body=body,
                  issued_at=payload['issued_at'], expires_at=payload['expires_at'], base_sha=current, head_sha=final_pr['head']['sha'])
    checkpoint()
    require(api.forge(repo, '/branches/' + source['branch'])['commit']['id'] == current
            and api.forge(repo, '/pulls/' + str(record['pr']))['head']['sha'] == final_pr['head']['sha'], 'source moved after signing; proof cannot authorize current merge')
    return record


def propose(api, config, qualification, state, write=False, checkpoint=None):
    checkpoint = checkpoint or (lambda: None)
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
            return {'status': 'covered-by-bootstrap-pr', 'pr': bootstrap_pr, 'url': pr['html_url'], 'head_sha': pr['head']['sha'], 'signed': False}
        require(pr.get('merged') is True, 'bootstrap producer PR was closed without merge')
        return {'status': 'bootstrap-merged-awaiting-rollout', 'pr': bootstrap_pr, 'url': pr['html_url'], 'head_sha': pr['head']['sha'], 'signed': False}
    strict_source(config, contents)
    key = qualification['qualification_id']
    branch = 'maintenance/apk-' + key[:20]
    owned = state['proposals'].get(key, {})
    open_prs = api.pages(repo, '/pulls?state=open')
    for pr in open_prs:
        if pr['base']['ref'] != source['branch']:
            continue
        if pr['head'].get('ref') == branch and owned.get('post_ready') is True and owned.get('owned') is not True:
            if not write:
                return {'status': 'recoverable-intended-proposal', 'pr': pr['number'], 'signed': False}
            recovered = recover_proposal(api, config, qualification, owned, pr, checkpoint)
            state['proposals'][key] = recovered
            checkpoint()
            if config.get('signing_enabled') is True:
                return refresh_proof(api, config, qualification, recovered, checkpoint)
            return recovered
        if pr['head'].get('ref') == branch and owned.get('owned') is True and owned.get('pr') == pr['number']:
            if write and config.get('signing_enabled') is True:
                return refresh_proof(api, config, qualification, owned, checkpoint)
            return dict(owned, status='owned-awaiting-refresh')
        files = api.pages(repo, '/pulls/' + str(pr['number']) + '/files')
        if len(files) != 1 or files[0].get('filename') != path or files[0].get('status') not in ('modified', 'changed'):
            continue
        proposed, _ = api.contents(repo, path, pr['head']['sha'])
        try:
            epoch_only(contents, proposed)
        except (Rejected, ValueError):
            continue
        return {'status': 'existing-unowned', 'pr': pr['number'], 'url': pr['html_url'], 'head_sha': pr['head']['sha'], 'signed': False}
    if owned.get('pr'):
        return dict(owned, status='previous-proposal-closed', signed=False)
    proposed = advance_epoch(contents, datetime.now(timezone.utc).date().isoformat())
    decision = {'status': 'qualified', 'branch': branch, 'base_sha': head, 'file': path, 'old_blob': blob,
                'new_content_sha256': hashlib.sha256(proposed.encode()).hexdigest(), 'qualification_id': key,
                'content': proposed, 'diff': ''.join(difflib.unified_diff(contents.splitlines(keepends=True), proposed.splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path))}
    if not write:
        return decision
    if config.get('proposal_enabled') is not True or not source.get('proposal_auth_command'):
        decision.update(status='awaiting-authorization', reason='separately authorized repository-scoped proposal write grant missing')
        state.setdefault('decisions', {})[key] = decision
        checkpoint()
        return decision
    if config.get('signing_enabled') is True:
        approved_source(config)
        require(source.get('proposal_actor') and source['proposal_actor'] != 'linroot', 'automatic signing requires dedicated pilot actor and scope')
        module = signing_module()
        module.validate_qualification(qualification, now())
        module.load_private(source['signing_key_file'], source['signing_public_key_sha256'])
    author = source.get('commit_author', {})
    require(isinstance(author.get('name'), str) and author['name'] and isinstance(author.get('email'), str) and '@' in author['email'], 'source commit author is missing')
    branches = api.pages(repo, '/branches')
    existing = [b for b in branches if b['name'] == branch]
    git_prepare(config, 'source')
    if existing:
        require(owned.get('intent') is True and owned.get('branch') == branch, 'existing branch has no controller ownership intent')
        branch_sha = existing[0]['commit']['id']
        on_branch, _ = api.contents(repo, path, branch_sha)
        command = git_prepare(config, 'source', branch)
        if branch_sha != head:
            old_base = owned['base_sha']
            old_contents, _ = api.contents(repo, path, old_base)
            git_ancestor(command, old_base, head)
            only_source_file(command, old_base, branch_sha, path)
            epoch_only(old_contents, on_branch)
            proposed = on_branch
    else:
        state['proposals'][key] = {'intent': True, 'branch': branch, 'base_sha': head}
        checkpoint()
        require(api.forge(repo, '/branches/' + quote(source['branch'], safe=''))['commit']['id'] == head, 'source base changed')
        api.forge(repo, '/branches', {'new_branch_name': branch, 'old_ref_name': head}, 'POST')
        branch_sha = head
    if branch_sha == head:
        update = api.forge(repo, '/contents/' + quote(path, safe='/'),
                           {'branch': branch, 'sha': blob, 'author': author, 'committer': author, 'content': base64.b64encode(proposed.encode()).decode(),
                            'message': 'chore: refresh qualified Alpine OS packages'}, 'PUT')
        branch_sha = update['commit']['sha']
        verified, _ = api.contents(repo, path, branch_sha)
        epoch_only(contents, verified)
        command = git_prepare(config, 'source', branch)
        only_source_file(command, head, branch_sha, path)
    body = ('Qualified immutable deployed image: `' + qualification['runtime_manifest_digest'] + '` (' + qualification['platform'] + ').\n\n'
            'Only the anchored APK_PATCH_EPOCH date advances. The independent merge bot requires a fresh signed issue comment, exact current source diff and successful current-head checks.\n\n'
            'Qualification: `' + key + '`.')
    creation_base = owned['base_sha'] if existing and branch_sha != head else head
    state['proposals'][key] = {'intent': True, 'post_ready': True, 'branch': branch,
                              'base_sha': creation_base, 'head_sha': branch_sha,
                              'repository': repo, 'proposal_actor': source.get('proposal_actor'),
                              'proposed_sha256': hashlib.sha256(proposed.encode()).hexdigest()}
    checkpoint()
    result = api.forge(repo, '/pulls', {'base': source['branch'], 'head': branch, 'title': 'chore: refresh qualified Alpine libxml2 fix', 'body': body}, 'POST')
    record = {'owned': True, 'status': 'opened', 'branch': branch, 'base_sha': head, 'head_sha': branch_sha,
              'pr': result['number'], 'url': result['html_url'], 'qualification_id': key, 'signed': False}
    if existing and branch_sha != head:
        record['base_sha'] = owned['base_sha']
    state['proposals'][key] = record
    checkpoint()
    if config.get('signing_enabled') is True:
        return refresh_proof(api, config, qualification, record, checkpoint)
    return record


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
    app = site_policy(config)
    if app or 'scope' in state:
        binding = identity({'repository': config['source']['repo'], 'target': config['target']})
        require(state.get('scope', binding) == binding, 'state belongs to another site')
        require('scope' in state or not state.get('proposals') and not state.get('verified') and not state.get('pending') and not state.get('decisions'), 'unbound site state is not empty')
        state['scope'] = binding
    api = HTTP(config)
    output = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(), 'mode': 'check' if check else 'once'}
    observation = observe(config)
    qualification_error = None
    try:
        qualification = qualify(api, config, observation)
        output['qualification'] = qualification
        if qualification:
            same_deployment(observation, observe(config))
            output['proposal'] = propose(api, config, qualification, state, write=not check, checkpoint=(lambda: atomic_json(state_path, state)) if not check else None)
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
    parser.add_argument('--site', choices=('ochistka-musoroprovoda', 'videooperator-su', 'videosemka-su'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--state-dir', type=Path)
    args = parser.parse_args()
    config_root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'pi-yt-maintenance'
    state_root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'pi-yt-maintenance'
    if args.site:
        config_root = config_root / 'sites' / args.site
        state_root = state_root / 'sites' / args.site
    args.config = args.config or config_root / 'config.json'
    args.state_dir = args.state_dir or state_root
    try:
        config = load_config(args.config)
        if args.site:
            require(site_policy(config) == args.site, 'selected site differs from config policy')
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
