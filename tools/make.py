#!/usr/bin/env python3
"""make 가 없는 환경(Windows 등)용 대체 실행기 — Makefile 과 같은 타깃을 같은 명령으로 실행한다.

  python tools/make.py validate data build check      # = make validate && make data && make build && make check
  타깃: data · laws · build · check · fetch · validate · shots · all(= data build check) · clean
한 타깃이 실패하면 거기서 멈추고 그 종료 코드로 끝난다. 콘솔 인코딩과 무관하게 한글이 깨지지 않도록 PYTHONUTF8=1 로 실행한다.
"""
import glob, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TPL, OUT = 'src/design-d.html', 'output/casebook.html'
TARGETS = {
    'data': [[PY, 'tools/build_data.py']],
    'laws': [[PY, 'tools/build_laws.py', 'data/laws_md']],
    'build': [[PY, 'tools/build.py', TPL, OUT]],
    'web': [[PY, 'tools/build_web.py']],
    'webcheck': [[PY, 'tools/test_web.py']],
    'check': [[PY, 'tools/sweep.py', OUT]],
    'fetch': [[PY, 'tools/fetch_lawgo.py', '--all-missing']],
    'validate': [[PY, 'tools/add_cases.py', 'validate']],
    'shots': [[PY, 'tools/shot.py', OUT, 'shots/final']],
}
ALIASES = {'all': ['data', 'build', 'check']}


def run(target):
    if target == 'clean':
        for f in glob.glob(os.path.join(ROOT, 'output', '*.html')) + glob.glob(os.path.join(ROOT, 'shots', '*.png')):
            os.remove(f)
        print('clean: output/*.html shots/*.png 삭제 (dist 백업 보존)')
        return 0
    if target not in TARGETS:
        print(f'알 수 없는 타깃: {target} (가능: {", ".join(list(TARGETS) + list(ALIASES) + ["clean"])})')
        return 2
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    for cmd in TARGETS[target]:
        print(f'[{target}] ' + ' '.join(('python' if c == PY else c) for c in cmd), flush=True)   # 인터프리터가 다른 드라이브에 있어도 됨
        rc = subprocess.call(cmd, cwd=ROOT, env=env)
        if rc:
            print(f'[{target}] 실패 (exit {rc})')
            return rc
    return 0


def main(argv):
    targets = argv or ['all']
    expanded = []
    for t in targets:
        expanded.extend(ALIASES.get(t, [t]))
    for t in expanded:
        rc = run(t)
        if rc:
            sys.exit(rc)


if __name__ == '__main__':
    main(sys.argv[1:])
