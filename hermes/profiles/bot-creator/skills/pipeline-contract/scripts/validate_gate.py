"""Validate supplied evidence only; callers must authenticate and enforce it."""
import argparse
import json
import re
from pathlib import Path

STAGES = ('plan', 'implement', 'deliver', 'close', 'cleanup', 'research')


def validate(data, stage):
    errors = []

    def require(ok, label):
        if not ok:
            errors.append(label)

    try:
        if stage not in STAGES or not isinstance(data, dict):
            return ['unknown stage or non-object evidence']
        if stage == 'research':
            record = data['research']
            phase = record['phase']
            require(phase in ('triage', 'diagnostic'), 'unknown research phase')
            ceiling = 300 if phase == 'triage' else 600
            call_ceiling = 12 if phase == 'triage' else 20
            if 'budget_limits' in record:
                limits = record['budget_limits']
                for key in ('seconds', 'calls'):
                    require(type(limits.get(key)) is int and limits[key] > 0,
                            'invalid scoped budget ' + key)
                for key in ('scope_ref', 'rationale'):
                    require(isinstance(limits.get(key), str) and bool(limits[key].strip()),
                            'missing scoped budget ' + key)
                if errors:
                    return errors
                ceiling, call_ceiling = limits['seconds'], limits['calls']
            for key, maximum in (('budget_seconds', ceiling), ('max_runtime_seconds', ceiling),
                                 ('tool_call_limit', call_ceiling),
                                 ('update_interval_seconds', 120)):
                require(type(record.get(key)) is int and 0 < record[key] <= maximum,
                        'invalid ' + key)
            require(record.get('max_runtime_seconds') == record.get('budget_seconds'),
                    'runtime cap must match phase budget')
            require(type(record.get('max_retries')) is int and record['max_retries'] == 1,
                    'first failure must stop redispatch')
            reserve = record.get('wrapup_reserve_seconds')
            require(type(reserve) is int and 60 <= reserve < record['budget_seconds'],
                    'invalid wrapup reserve')
            for key in ('runtime_evidence_ref', 'checkpoint_ref', 'prior_evidence_ref',
                        'stop_criteria', 'owner', 'final_acceptance_card'):
                require(isinstance(record.get(key), str) and bool(record[key].strip()),
                        'missing ' + key)
            require(record.get('auto_extend') is False, 'automatic extension forbidden')
            require(type(record.get('production_execution')) is bool, 'production scope missing')
            if phase == 'triage':
                require(record.get('production_execution') is False, 'triage cannot execute production probes')
            else:
                require(isinstance(record.get('authorization_ref'), str)
                        and bool(record['authorization_ref'].strip()), 'diagnostic authorization missing')
            if record.get('production_execution'):
                require(record.get('owner') != 'researcher', 'researcher cannot execute production probes')
                for key, maximum in (('command_timeout_seconds', 60), ('commands_per_test', 3),
                                     ('max_attempts', 2)):
                    require(type(record.get(key)) is int and 0 < record[key] <= maximum,
                            'invalid ' + key)
                require(isinstance(record.get('commands_ref'), str) and bool(record['commands_ref'].strip()),
                        'missing approved command list')
            return errors
        rank = STAGES.index(stage)
        identity = data['identity']
        for key in ('repo', 'worktree'):
            require(isinstance(identity[key], str) and Path(identity[key]).is_absolute(), 'invalid ' + key)
        for key in ('scope_digest', 'plan_digest', 'candidate_digest', 'policy_digest'):
            require(bool(re.fullmatch('[0-9a-f]{64}', identity[key])), 'invalid ' + key)
        require(bool(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', identity['base_sha'])), 'invalid base SHA')
        require(data['risk'] in ('low', 'medium', 'high'), 'unknown risk')
        require(type(data['browser_required']) is bool, 'browser requirement missing')
        preflight = data['preflight']
        require(preflight['status'] == 'PASS' and preflight['repo'] == identity['repo']
                and preflight['base_sha'] == identity['base_sha'], 'preflight missing or stale')

        def bound(record, label):
            require(record.get('binding') == identity, label + ': stale binding')
            require(isinstance(record.get('evidence_ref'), str) and bool(record['evidence_ref'].strip()), label + ': missing evidence')

        def approval(action):
            record = data['approvals'][action]
            bound(record, action + ' approval')
            require(record.get('decision') == 'APPROVED' and record.get('actor_kind') == 'human'
                    and bool(record.get('actor')) and record.get('action') == action,
                    action + ': missing human approval')

        def recovered_plan(record):
            require(record.get('native') is False and record.get('verdict') == 'APPROVED',
                    'recovery: must be approved non-native artifact review')
            recovery = record['recovery']
            for name in ('source', 'artifact', 'reviewer', 'idle', 'decision', 'authorization'):
                item = recovery[name]
                bound(item, 'recovery ' + name)
                require(item.get('verified') is True, 'recovery: unverified ' + name)
            source, artifact, reviewer, idle, decision, authorization = (
                recovery[n] for n in ('source', 'artifact', 'reviewer', 'idle', 'decision', 'authorization'))

            def text(item, *keys):
                for key in keys:
                    require(isinstance(item.get(key), str) and bool(item[key].strip()),
                            'recovery: missing ' + key)

            for item in (source, reviewer):
                text(item, 'card', 'run', 'profile')
            require(source['card'] == record.get('source_card') and source.get('status') == 'timed_out',
                    'recovery: source is not the timed-out author')
            require(all(reviewer[k] != source[k] for k in ('card', 'run', 'profile')),
                    'recovery: reviewer must be independent')
            require(reviewer.get('status') == 'completed' and reviewer.get('verdict') == 'APPROVED',
                    'recovery: actual completed approval required')
            require(isinstance(artifact.get('path'), str) and Path(artifact['path']).is_absolute(),
                    'recovery: absolute artifact path required')
            digest = artifact.get('sha256')
            require(isinstance(digest, str) and bool(re.fullmatch('[0-9a-f]{64}', digest)),
                    'recovery: invalid artifact hash')
            require(digest == identity['plan_digest'] == artifact.get('current_sha256')
                    == reviewer.get('artifact_sha256') == decision.get('artifact_sha256'),
                    'recovery: preserved/reviewed/current plan hashes differ')
            require(artifact.get('complete') is True and artifact.get('preserved') is True,
                    'recovery: complete preserved artifact required')
            text(idle, 'session')
            require(all(idle.get(k) == source[k] for k in ('card', 'run', 'profile'))
                    and idle.get('state') == 'idle' and idle.get('active_worker') is False,
                    'recovery: source worker not verified idle')
            for item in (decision, authorization):
                text(item, 'actor')
                require(item.get('decision') == 'APPROVED'
                        and item.get('source_card') == source['card']
                        and item.get('source_run') == source['run'],
                        'recovery: decision/authorization source mismatch or not approved')
            require(decision.get('actor_kind') == 'orchestrator'
                    and decision.get('action') == 'recover-plan-review'
                    and decision.get('review_card') == reviewer['card']
                    and decision.get('review_run') == reviewer['run']
                    and decision.get('authorization_ref') == authorization.get('evidence_ref'),
                    'recovery: missing scoped Orchestrator decision')
            require(authorization.get('actor_kind') == 'human'
                    and authorization.get('action') == 'workflow-recovery',
                    'recovery: user workflow-recovery authorization required')

        def review(name):
            record = data['reviews'][name]
            bound(record, name + ' review')
            if 'mode' in record or 'recovery' in record:
                require(name == 'plan' and record.get('mode') == 'recovered-artifact-review',
                        'recovery: only explicit recovered plan review supported')
                recovered_plan(record)
            else:
                require(record.get('verdict') == 'APPROVED' and record.get('native') is True
                        and bool(record.get('source_card')), name + ': native review not approved')

        if data['risk'] != 'low':
            approval('plan')
        if rank >= 1:
            review('plan')
            if data['risk'] != 'low':
                approval('implement')
        if rank >= 2:
            review('implementation')
            for name in ['tester'] + (['browser-tester'] if data['browser_required'] else []):
                record = data['tests'][name]
                bound(record, name)
                require(record.get('status') == 'PASS' and type(record.get('exit_code')) is int
                        and record['exit_code'] == 0, name + ': no PASS')
            for name in ('docs', 'acceptance', 'wiki'):
                bound(data[name], name)
                require(data[name].get('status') == 'PASS', name + ': not passed')
            require(data['wiki'].get('authorized') is True and data['wiki'].get('scope') == 'RW/task-summary', 'wiki scope not authorized')
            policy = data['delivery_policy']
            bound(policy, 'delivery policy')
            requested = data['requested_actions']
            require(isinstance(requested, list) and bool(requested) and
                    set(requested) <= set(policy['actions']) <= {'commit', 'push', 'pr', 'merge'}
                    and policy['repository'] == identity['repo'], 'delivery actions outside policy')
            approval('deliver')
        if rank >= 3:
            delivery = data['delivery']
            bound(delivery, 'delivery')
            sha = data['final_sha']
            require(bool(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', sha)), 'invalid final SHA')
            require(delivery['status'] == 'PASS' and delivery['result_sha'] == sha
                    and bool(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', delivery['delivered_sha'])), 'delivery/final SHA mismatch')
            ci = data['ci']
            if ci['status'] == 'EXEMPT':
                bound(ci, 'CI exemption')
                approval('ci-exemption')
                authorization = data['approvals']['ci-exemption']
                require(authorization.get('repository') == identity['repo']
                        and authorization.get('scope') == 'no-ci'
                        and authorization.get('sha') == sha == ci.get('sha'),
                        'CI exemption repository/scope/SHA mismatch')
                target = authorization.get('target')
                require(isinstance(target, str) and bool(target.strip())
                        and target == delivery.get('target') == ci.get('target'),
                        'CI exemption target mismatch')
                policy_ref = authorization.get('policy_ref')
                require(isinstance(policy_ref, str) and bool(policy_ref.strip()),
                        'CI exemption missing existing user policy evidence')
                require(ci.get('checks') == [] and ci.get('required_checks') == [],
                        'CI exemption cannot override required or observed checks')
            else:
                require(ci['sha'] == sha and ci['status'] == 'PASS' and bool(ci['evidence_ref'])
                        and ci['provider'] in ('forgejo', 'github', 'other'), 'missing/stale/failing CI')
                checks = ci['checks']
                required = ci['required_checks']
                require(isinstance(required, list) and bool(required) and isinstance(checks, list)
                        and bool(checks), 'CI has no required results')
                observed = {c['name']: c['status'] for c in checks}
                require(len(observed) == len(checks) and all(observed.get(n) == 'PASS' for n in required)
                        and all(c['status'] == 'PASS' for c in checks), 'CI missing/skipped/failing checks')
            beads = data['beads']
            require(type(beads['exists']) is bool, 'Beads presence unknown')
            if beads['exists']:
                require(bool(beads['actor']) and beads['owner'] == beads['actor'] and bool(beads['handoff']), 'Beads ownership handoff missing')
        if rank >= 4:
            approval('cleanup')
            clean = data['cleanup']
            bound(clean, 'cleanup')
            require(all(clean.get(k) is True for k in ('dry_run', 'clean', 'integrated')), 'cleanup checks failed')
            targets = clean['targets']
            require(isinstance(targets, list) and bool(targets) and targets == clean['approved_targets']
                    and targets == data['approvals']['cleanup'].get('targets')
                    and len(set(targets)) == len(targets), 'cleanup scope mismatch')
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append('missing or malformed required evidence')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('stage', choices=STAGES)
    args = parser.parse_args()
    ci_status = 'NOT_EVALUATED'
    try:
        data = json.loads(args.evidence.read_text())
        errors = validate(data, args.stage)
        if args.stage in ('close', 'cleanup'):
            ci_status = 'BLOCKED' if errors else data['ci']['status']
    except (OSError, UnicodeError, ValueError):
        errors = ['unreadable or invalid JSON evidence']
    status = 'BLOCKED' if errors else ('EXEMPT' if ci_status == 'EXEMPT' else 'PASS')
    print(json.dumps({'stage': args.stage, 'passed': not errors, 'status': status,
                      'ci_status': ci_status, 'errors': errors}))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
