"""Validate and count the exact publisher note locally, without publication authority."""
import argparse
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import stat
import sys


def load_gateway(path):
    spec = importlib.util.spec_from_file_location('honcho_preflight_gateway', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Capture:
    def __init__(self):
        self.note = None

    def prepare_session(self, scope):
        pass

    def call(self, name, arguments):
        if name != 'create_conclusions' or self.note is not None:
            raise ValueError('Unexpected renderer operation')
        notes = arguments['conclusions']
        if len(notes) != 1 or not isinstance(notes[0], str):
            raise ValueError('Unexpected renderer result')
        self.note = notes[0]


def render(gateway, payload):
    scope = payload.get('scope') if isinstance(payload, dict) else None
    if (not isinstance(scope, dict) or set(scope) != set(gateway.SCOPE)
            or not all(isinstance(value, str) and gateway.ID.fullmatch(value)
                       for value in scope.values())):
        raise ValueError('Invalid scope shape')
    capture = Capture()
    gateway.call('publish_verified', payload, scope, capture)
    if capture.note is None:
        raise ValueError('No rendered note')
    return capture.note


def count_tokens(note, encoding):
    if importlib.metadata.version('tiktoken') != '0.12.0':
        raise ValueError('Use tiktoken 0.12.0')
    import tiktoken
    import tiktoken.load

    def offline_only(*args, **kwargs):
        raise ValueError('Tokenizer cache unavailable; prepare it without any payload first')

    tiktoken.load.read_file = offline_only
    return len(tiktoken.get_encoding(encoding).encode(note))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('--gateway', type=Path, default=Path.home() / '.codex/honcho/gateway.py')
    parser.add_argument('--encoding', default='o200k_base')
    parser.add_argument('--max-tokens', type=int, default=512)
    args = parser.parse_args()
    try:
        if args.max_tokens <= 0:
            raise ValueError('Invalid token limit')
        gateway = load_gateway(args.gateway)
        path = args.payload
        if stat.S_IMODE(path.lstat().st_mode) != 0o600:
            raise ValueError('Payload must have mode 0600')
        payload = json.loads(gateway.private_text(str(path)))
        note = render(gateway, payload)
        tokens = count_tokens(note, args.encoding)
        passed = tokens <= args.max_tokens
        print(json.dumps({'tokens': tokens, 'limit': args.max_tokens,
                          'result': 'pass' if passed else 'fail'}))
        return 0 if passed else 1
    except Exception:
        print('Preflight failed: check private payload, gateway contract, pinned tokenizer and offline cache.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
