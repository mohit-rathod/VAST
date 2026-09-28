"""Compare tool/API outputs from two VAST repositories, without changing their data.

Example:
    python scripts/compare_repositories.py ../original-vast .
    python scripts/compare_repositories.py ../original-vast . --stub-openai
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('updated', type=Path)
    parser.add_argument('--stub-openai', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    probe = Path(__file__).with_name('probe_repository.py')
    results = []
    for root in (args.original, args.updated):
        command = [sys.executable, str(probe), str(root.resolve())]
        if args.stub_openai:
            command.append('--stub-openai')
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)
        except subprocess.CalledProcessError as error:
            parser.exit(2, f'Probe failed for {root}:\n{error.stderr}')
        except subprocess.TimeoutExpired:
            parser.exit(2, f'Probe timed out for {root}\n')
        results.append(json.loads(completed.stdout)['cases'])
    before, after = results
    mismatches = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
    report = dict(equivalent=not mismatches, cases_compared=len(before), mismatches=mismatches)
    text = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end='')
    raise SystemExit(1 if mismatches else 0)


if __name__ == '__main__':
    main()
