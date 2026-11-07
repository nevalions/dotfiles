"""Regression suite for vault-ro-guard.py. Run: python3 vault-ro-guard-tests.py"""
import json
import subprocess

HOOK = "/home/linroot/.hermes/agent-hooks/vault-ro-guard.py"
V = "/home/linroot/vault/linroot-wiki-code"
RO = V + "/RO"

TOOL_CASES = [
    # (name, tool, args, expect_block)
    ("write_file abs RO", "write_file", {"path": RO + "/x.md"}, True),
    ("write_file rel RO", "write_file", {"path": "RO/x.md", "cwd": V}, True),
    ("write_file RW", "write_file", {"path": V + "/RW/x.md"}, False),
    ("write_file no cwd", "write_file", {"path": RO + "/y.md"}, True),
    ("patch RO", "patch", {"path": RO + "/x.md", "old_string": "a", "new_string": "b"}, True),
    ("read RO", "read_file", {"path": RO + "/x.md"}, False),
    ("search RO", "search_files", {"path": RO, "pattern": "*.md"}, False),
    ("cat RO", "terminal", {"command": f"cat {RO}/a.md"}, False),
    ("grep RO", "terminal", {"command": f"grep -rn foo {RO}"}, False),
    ("ls RO", "terminal", {"command": f"ls -la {RO}"}, False),
    ("redirect into RO", "terminal", {"command": f"echo hi > {RO}/a.md"}, False if False else True),
    ("append into RO", "terminal", {"command": f"echo hi >> {RO}/a.md"}, True),
    ("tee into RO", "terminal", {"command": f"echo x | tee {RO}/a.md"}, True),
    ("rm RO glob", "terminal", {"command": f"rm -f {RO}/*.md"}, True),
    ("touch rel in RO", "terminal", {"command": "touch new.md", "cwd": RO}, True),
    ("ls rel in RO", "terminal", {"command": "ls -la", "cwd": RO}, False),
    ("echo rel in RO", "terminal", {"command": "echo hi > a.md", "cwd": RO}, True),
    ("mv into RO", "terminal", {"command": f"mv /tmp/a.md {RO}/"}, True),
    ("sed -i RO", "terminal", {"command": f"sed -i 's/a/b/' {RO}/a.md"}, True),
    ("git status RO", "terminal", {"command": "git status --porcelain RO", "cwd": V}, False),
    ("git checkout RO", "terminal", {"command": "git checkout -- RO/", "cwd": V}, True),
    ("git add -A", "terminal", {"command": "git add -A", "cwd": V}, False),
    ("RW rm", "terminal", {"command": f"rm {V}/RW/x.md"}, False),
    ("plain /tmp", "terminal", {"command": "touch /tmp/x"}, False),
]

CODE_CASES = [
    ("code read open", f"print(open('{RO}/a.md').read())", False),
    ("code read_text", f"from pathlib import Path; print(Path('{RO}/a.md').read_text())", False),
    ("code listdir", f"import os; print(os.listdir('{RO}'))", False),
    ("code subprocess cat", f"import subprocess; print(subprocess.run(['cat','{RO}/a.md'],capture_output=True))", False),
    ("code os.system ls", f"import os; os.system('ls {RO}')", False),
    ("code write mode", f"open('{RO}/a.md','w').write('x')", True),
    ("code append mode", f"open('{RO}/a.md','a').write('x')", True),
    ("code write_text", f"from pathlib import Path; Path('{RO}/a.md').write_text('x')", True),
    ("code os.remove", f"import os; os.remove('{RO}/a.md')", True),
    ("code rmtree", f"import shutil; shutil.rmtree('{RO}')", True),
    ("code rename", f"import os; os.rename('{RO}/a.md','/tmp/x')", True),
    ("code shell write", f"import subprocess; subprocess.run('echo hi > {RO}/a.md', shell=True)", True),
    ("code shell rm", f"import subprocess; subprocess.run('rm {RO}/a.md', shell=True)", True),
    ("code var target", f"import os; p = os.path.join('{V}','RO','a.md'); open(p,'w').write('x')", True),
    ("code unknown mode", f"m='w'; open('{RO}/a.md', m).write('x')", True),
    ("code exec dynamic", f"exec('open(\"{RO}/a.md\",\"w\")')", True),
    ("code unparseable", f"open('{RO}/a.md','w'", True),
    ("code /tmp write", "open('/tmp/ok.txt','w').write('x')", False),
    ("code RW write", f"open('{V}/RW/a.md','w').write('x')", False),
]


def run(tool, args):
    payload = json.dumps({"tool_name": tool, "tool_input": args, "session_id": "t"})
    out = subprocess.run(["python3", HOOK], input=payload, capture_output=True, text=True, timeout=20)
    return json.loads(out.stdout or "{}").get("decision") == "block"


def main():
    total = fails = 0
    for name, tool, args, expect in TOOL_CASES:
        total += 1
        got = run(tool, args)
        if got != expect:
            fails += 1
            print(f"FAIL {name}: blocked={got} expected={expect}")
    for name, code, expect in CODE_CASES:
        total += 1
        got = run("execute_code", {"code": code})
        if got != expect:
            fails += 1
            print(f"FAIL {name}: blocked={got} expected={expect}")
    print(f"{total - fails}/{total} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
