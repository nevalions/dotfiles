"""Local advisory evaluator for sanitized evidence; not native enforcement."""
import hashlib
import json
import re
import sys

BINDING_KEYS = ('task', 'candidate', 'scope', 'models', 'stage_started_at', 'policy')
OUTCOMES = {'checkpoint', 'correction', 'changes_requested', 'review_requested',
            'approved', 'command_denied', 'capability_mismatch', 'blocked', 'stopped'}


def history_digest(history):
    return hashlib.sha256(json.dumps(history, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _result(reasons, stop=False):
    reasons = sorted(set(reasons))
    return {'decision': 'STOP' if stop else ('ESCALATE' if reasons else 'CONTINUE'),
            'reasons': reasons, 'route': 'Orchestrator', 'park_source': bool(reasons),
            'review_approved': False, 'native_enforcement': False}


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53 - 1


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 4096


def _validate(d):
    p, history = d['policy'], d['history']
    assert d['history_complete'] is True and type(d['stopped']) is bool
    assert _integer(d['expected_records']) and d['expected_records'] == len(history)
    assert isinstance(history, list)
    assert all(_text(d[k]) for k in ('task', 'candidate', 'scope'))
    assert d['candidate'].startswith('/')
    assert set(d['models']) == {'author', 'reviewer'}
    assert all(_text(v) for v in d['models'].values())
    assert _text(p['role']) and _integer(p['stage_wall_seconds'], 1)
    assert _integer(p['no_progress_limit'], 2)
    assert _integer(p.get('review_rejection_limit', 2), 1)
    assert isinstance(p['required_tests'], list) and p['required_tests']
    assert all(_text(n) for n in p['required_tests'])
    assert _integer(d['stage_started_at']) and _integer(d['now'])
    assert d['now'] >= d['stage_started_at']
    assert d.get('next_action', 'author') in ('author', 'review', 'handoff')
    for key in ('cycle_wall_seconds', 'total_token_budget', 'total_tool_budget'):
        if key in p:
            assert _integer(p[key], 1)
    if 'provider_window_ceiling_percent' in p:
        assert type(p['provider_window_ceiling_percent']) in (int, float)
        assert 0 < p['provider_window_ceiling_percent'] <= 100
    window = d.get('provider_window', {})
    if 'reported_percent' in window:
        assert type(window['reported_percent']) in (int, float)
        assert 0 <= window['reported_percent'] <= 100
    for key in ('before_expensive_phase', 'fresh_checkpoint'):
        assert type(d.get(key, False)) is bool
    previous = d['stage_started_at']
    for seq, r in enumerate(history, 1):
        assert type(r['seq']) is int and r['seq'] == seq
        assert _integer(r['run_id'], 1) and _integer(r['at'])
        assert previous <= r['at'] <= d['now']
        previous = r['at']
        assert r['role'] in ('author', 'reviewer') and r['outcome'] in OUTCOMES
        if r['outcome'] in ('changes_requested', 'approved'):
            assert r['role'] == 'reviewer'
        if r['outcome'] in ('correction', 'review_requested'):
            assert r['role'] == 'author'
        for key in ('diff_digest', 'evidence_digest'):
            if key in r:
                assert isinstance(r[key], str) and re.fullmatch('[0-9a-f]{64}', r[key])
        for issue in r.get('issues', []):
            assert re.fullmatch('[A-Z][A-Z0-9_]{0,63}', issue['code'])
            assert issue['severity'] in ('low', 'medium', 'high', 'critical')
        for usage_key in ('tokens_delta', 'tools_delta'):
            if usage_key in r and r[usage_key] is not None:
                assert _integer(r[usage_key])
        assert isinstance(r.get('tests', {}), dict)


def _signals(history, policy):
    """Return (sequence, reason) without copying external text."""
    signals, seen = [], {}
    corrections, previous, identical, rejections = 0, None, 0, 0
    for r in history:
        outcome, seq = r['outcome'], r['seq']
        if r['role'] == 'author' and outcome == 'correction':
            corrections += 1
        if outcome == 'changes_requested':
            rejections += 1
            if rejections >= policy.get('review_rejection_limit', 2):
                signals.append((seq, 'REVIEW_LIMIT'))
            for issue in r.get('issues', []):
                if issue['severity'] not in ('high', 'critical'):
                    continue
                code = issue['code']
                if code in seen and corrections > seen[code]:
                    signals.append((seq, 'ARCHITECTURE_REVIEW'))
                seen[code] = corrections
        if outcome in ('command_denied', 'capability_mismatch'):
            signals.append((seq, 'CAPABILITY_REPLAN'))
        if 'diff_digest' in r and 'evidence_digest' in r:
            pair = r['diff_digest'], r['evidence_digest']
            identical = identical + 1 if pair == previous else 1
            previous = pair
            if identical >= policy['no_progress_limit']:
                signals.append((seq, 'NO_PROGRESS'))
        if outcome in ('review_requested', 'approved'):
            for name in policy['required_tests']:
                test = r.get('tests', {}).get(name, {})
                if (test.get('status') != 'PASS' or type(test.get('exit_code')) is not int
                        or test['exit_code'] != 0 or not r.get('diff_digest')
                        or test.get('diff_digest') != r['diff_digest']):
                    signals.append((seq, 'REQUIRED_TESTS'))
    return signals


def _recovery(data, authority):
    """Separate, owner-supplied authority is evidence, NOT authentication."""
    try:
        old = {k: v for k, v in data.items() if k != 'recovery_phase'}
        historical = evaluate(old)
        phase = data['recovery_phase']
        assert isinstance(authority, dict)
        assert authority['actor'] == 'Orchestrator'
        assert authority['actor_kind'] == 'human-authorized-owner'
        assert authority['decision'] == 'APPROVED' and authority['revoked'] is False
        assert authority['action'] == 'corrective-author-phase'
        assert all(_text(authority[k]) and authority[k].strip() for k in
                   ('authorization_ref', 'reason', 'author_profile', 'reviewer_profile'))
        assert authority['author_profile'] != authority['reviewer_profile']
        assert authority['authorization_ref'] == phase['authorization_ref']
        assert authority['historical_digest'] == history_digest(old)
        assert historical['decision'] != 'CONTINUE'
        assert 'INVALID_INPUT' not in historical['reasons']
        assert set(authority['acknowledged_reasons']) == set(historical['reasons'])
        assert authority['binding'] == {k: phase[k] for k in BINDING_KEYS}
        assert all(phase[k] == old[k] for k in ('task', 'candidate', 'scope', 'models'))
        assert 'decision' not in phase and 'recovery_phase' not in phase
        assert authority['candidate_digest'] == phase.get('initial_candidate_digest', phase['candidate_digest'])
        if not phase['history']:
            assert phase['candidate_digest'] == authority['candidate_digest']
        assert re.fullmatch('[0-9a-f]{64}', phase['candidate_digest'])
        assert _integer(authority['issued_at']) and _integer(authority['expires_at'])
        assert old['now'] <= authority['issued_at'] == phase['stage_started_at'] <= phase['now']
        assert phase['now'] < authority['expires_at']
        max_phase_seconds = authority.get('max_phase_seconds', 480)
        assert _integer(max_phase_seconds, 1) and max_phase_seconds <= 3900
        assert authority['expires_at'] - authority['issued_at'] <= max_phase_seconds
        assert 0 < phase['policy']['stage_wall_seconds'] <= max_phase_seconds
        assert phase['policy']['stage_wall_seconds'] <= authority['expires_at'] - authority['issued_at']
        assert phase['policy'].get('review_rejection_limit') == 1
        assert phase['policy']['required_tests'] == old['policy']['required_tests']
        for key in ('total_tool_budget', 'total_token_budget', 'provider_window_ceiling_percent'):
            assert phase['policy'].get(key) == old['policy'].get(key)
        result = evaluate(phase)
        assert 'INVALID_INPUT' not in result['reasons']
    except (KeyError, TypeError, ValueError, AssertionError, AttributeError):
        return _result(['INVALID_RECOVERY'], True)
    result['historical'] = {'disposition': 'STOP', 'result': historical,
                            'snapshot_digest': authority['historical_digest']}
    records = phase['history']
    corrections = [r for r in records if r['outcome'] == 'correction']
    reasons = list(result['reasons'])
    stop = result['decision'] == 'STOP'
    if len(corrections) > 1 or (corrections and phase.get('next_action', 'author') == 'author'):
        reasons.append('CORRECTION_ALLOWANCE'); stop = True
    if any(r['outcome'] == 'changes_requested' for r in records):
        reasons.append('REVIEW_LIMIT'); stop = True
    for r in records:
        if r.get('profile') != authority[r['role'] + '_profile']:
            reasons.append('REVIEW_INDEPENDENCE'); stop = True
    if any(r.get('diff_digest') != phase['candidate_digest'] for r in records
           if r['outcome'] in ('review_requested', 'approved')):
        reasons.append('STALE_CANDIDATE'); stop = True
    action = phase.get('next_action', 'author')
    handoffs = [r for r in records if r['outcome'] == 'review_requested']
    approvals = [r for r in records if r['outcome'] == 'approved']
    ready = bool(corrections and handoffs and approvals
                 and corrections[0]['seq'] < handoffs[-1]['seq'] < approvals[-1]['seq']
                 and handoffs[-1]['run_id'] != approvals[-1]['run_id'])
    if action in ('review', 'handoff') and not (corrections and handoffs):
        reasons.append('FRESH_PHASE_TESTS'); stop = True
    if action == 'handoff' and not ready:
        reasons.append('INDEPENDENT_REVIEW_REQUIRED'); stop = True
    for key, usage, code in (('total_tool_budget', 'tools_delta', 'TOOL_BUDGET'),
                             ('total_token_budget', 'tokens_delta', 'TOKEN_BUDGET')):
        if key in phase['policy']:
            combined = old['history'] + records
            if any(r.get(usage) is None for r in combined):
                reasons.append('UNKNOWN_REQUIRED_USAGE'); stop = True
            elif sum(r[usage] for r in combined) >= phase['policy'][key]:
                reasons.append(code); stop = True
    if 'provider_window_ceiling_percent' in phase['policy']:
        percent = phase.get('provider_window', {}).get('reported_percent')
        if percent is None:
            reasons.append('UNKNOWN_REQUIRED_USAGE'); stop = True
    checked = _result(reasons, stop)
    result.update(checked)
    result['phase_ready_for_acceptance'] = ready and result['decision'] == 'CONTINUE'
    return result


def evaluate(data, recovery_authority=None):
    if __debug__ and isinstance(data, dict) and 'recovery_phase' in data:
        return _recovery(data, recovery_authority)
    # Validation uses assertions deliberately; refuse optimized interpreters.
    if not __debug__:
        return _result(['INVALID_INPUT'], True)
    try:
        _validate(data)
        history, policy = data['history'], data['policy']
        signals = _signals(history, policy)
    except (KeyError, TypeError, ValueError, AssertionError, AttributeError):
        return _result(['INVALID_INPUT'], True)
    reasons, stop, boundary = [], False, 0
    if data['stopped'] or any(r['outcome'] == 'stopped' for r in history):
        reasons.append('EXPLICIT_STOP'); stop = True
    if data['now'] - data['stage_started_at'] >= policy['stage_wall_seconds']:
        reasons.append('STAGE_WALL_BUDGET'); stop = True
    decision = data.get('decision')
    if decision is not None:
        try:
            boundary = decision['after_seq']
            assert _integer(boundary, 1) and boundary <= len(history)
            assert decision['actor'] == 'Orchestrator'
            assert _text(decision['authorization_ref']) and _text(decision['design_ref'])
            assert decision['binding'] == {k: data[k] for k in BINDING_KEYS}
            assert decision['history_digest'] == history_digest(history[:boundary])
            assert _integer(decision['remaining_corrections'], 1)
            acknowledged = decision['acknowledged_reasons']
            assert isinstance(acknowledged, list)
            assert set(acknowledged) == {reason for seq, reason in signals if seq <= boundary}
            # Acknowledgement cannot substitute for actually executing missing tests.
            assert 'REQUIRED_TESTS' not in acknowledged
            used = sum(r['outcome'] == 'correction' for r in history[boundary:])
            if used > decision['remaining_corrections'] or (
                    used == decision['remaining_corrections'] and data.get('next_action', 'author') == 'author'):
                reasons.append('CORRECTION_ALLOWANCE'); stop = True
        except (KeyError, TypeError, ValueError, AssertionError):
            return _result(reasons + ['INVALID_DECISION'], True)
    # History is retained. Explicit cycle decisions waive only acknowledged prefix
    # signals, not a recurrence after their boundary or any STOP condition.
    for seq, reason in signals:
        if seq > boundary and reason != 'REVIEW_LIMIT':
            reasons.append(reason)
    if sum(r['outcome'] == 'changes_requested' for r in history[boundary:]) >= policy.get('review_rejection_limit', 2):
        reasons.append('REVIEW_LIMIT')
    cycle_start = history[boundary - 1]['at'] if boundary else data['stage_started_at']
    if data['now'] - cycle_start >= policy.get('cycle_wall_seconds', policy['stage_wall_seconds']):
        reasons.append('CYCLE_WALL_BUDGET'); stop = True
    measured = sum(r.get('tokens_delta') or 0 for r in history)
    coverage = 'KNOWN' if history and all(r.get('tokens_delta') is not None for r in history) else 'UNKNOWN'
    if 'total_token_budget' in policy and measured >= policy['total_token_budget']:
        reasons.append('TOKEN_BUDGET'); stop = True
    percent = data.get('provider_window', {}).get('reported_percent')
    if percent is not None and percent >= policy.get('provider_window_ceiling_percent', 101):
        reasons.append('PROVIDER_WINDOW_BUDGET'); stop = True
    if data.get('before_expensive_phase') and not data.get('fresh_checkpoint'):
        reasons.append('CHECKPOINT_REQUIRED')
    tools = sum(r.get('tools_delta') or 0 for r in history)
    tools_known = bool(history) and all(r.get('tools_delta') is not None for r in history)
    if 'total_tool_budget' in policy and tools >= policy['total_tool_budget']:
        reasons.append('TOOL_BUDGET'); stop = True
    result = _result(reasons, stop)
    result['usage'] = {'measured_tokens': measured if coverage == 'KNOWN' else None,
                       'known_token_subtotal': measured, 'coverage': coverage,
                       'measured_tools': tools if tools_known else None,
                       'known_tool_subtotal': tools,
                       'tool_coverage': 'KNOWN' if tools_known else 'UNKNOWN',
                       'stage_elapsed_seconds': data['now'] - data['stage_started_at'],
                       'cycle_elapsed_seconds': data['now'] - cycle_start,
                       'provider_window': 'REPORTED' if percent is not None else 'UNKNOWN'}
    return result


def main():
    try:
        authority = None
        if len(sys.argv) == 3:
            with open(sys.argv[2], encoding='utf-8') as stream:
                authority = json.load(stream)
        elif len(sys.argv) != 2:
            raise ValueError('invalid arguments')
        with open(sys.argv[1], encoding='utf-8') as stream:
            result = evaluate(json.load(stream), recovery_authority=authority)
    except (OSError, ValueError, IndexError):
        result = _result(['INVALID_INPUT'], True)
    print(json.dumps(result, sort_keys=True))
    return {'CONTINUE': 0, 'ESCALATE': 2, 'STOP': 3}[result['decision']]


if __name__ == '__main__':
    sys.exit(main())
