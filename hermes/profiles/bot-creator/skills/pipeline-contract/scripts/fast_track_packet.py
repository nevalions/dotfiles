"""Offline stage selection only; not an authority or admission validator."""
FIELDS = set('track reason kind known_cause bounded reversible risks unknowns required_stages same_card author reviewer tests delivery_mode authority estimate fallback scope_expansion_rule'.split())
STAGES = ['author_targeted_tests', 'independent_same_card_review', 'authorized_delivery']


def select(kind, known_cause, bounded, reversible, risks, unknowns):
    return 'fast' if (kind in ('typo', 'broken_link', 'isolated_fix')
                      and known_cause is True and bounded is True
                      and reversible is True and risks == [] and unknowns == []) else 'standard'


def validate(packet):
    if not isinstance(packet, dict) or set(packet) != FIELDS:
        return ['missing or unknown packet fields']
    errors = []
    for key in ('reason', 'kind', 'author', 'reviewer', 'authority', 'estimate', 'fallback', 'scope_expansion_rule'):
        if not isinstance(packet[key], str) or not packet[key].strip():
            errors.append('invalid ' + key)
    for key in ('known_cause', 'bounded', 'reversible', 'same_card'):
        if type(packet[key]) is not bool:
            errors.append('invalid ' + key)
    for key in ('risks', 'unknowns', 'tests'):
        if not isinstance(packet[key], list) or any(not isinstance(v, str) or not v.strip() for v in packet[key]):
            errors.append('invalid ' + key)
    if errors:
        return errors
    if packet['track'] != select(*(packet[k] for k in ('kind', 'known_cause', 'bounded', 'reversible', 'risks', 'unknowns'))):
        errors.append('track disagrees with conservative rubric')
    if packet['required_stages'] != STAGES or packet['same_card'] is not True:
        errors.append('same-card path required')
    if packet['author'] == packet['reviewer']:
        errors.append('independent reviewer required')
    if not packet['tests']:
        errors.append('required checks missing')
    if packet['delivery_mode'] not in ('local_only', 'gated'):
        errors.append('delivery outcome cannot be claimed by selection')
    return errors
