"""Wait for the frozen Schema13 study and audit only a successful terminal report."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def write(path, value):
  path.write_text(json.dumps(value, indent=2) + '\n')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--pid', required=True, type=int)
  parser.add_argument('--study', required=True, type=Path)
  parser.add_argument('--auditor', required=True, type=Path)
  parser.add_argument('--audit-output', required=True, type=Path)
  parser.add_argument('--python', required=True, type=Path)
  parser.add_argument('--status-output', required=True, type=Path)
  args = parser.parse_args()
  status = {'pid': args.pid, 'study': str(args.study), 'audited': False, 'passed': False}
  try:
    while True:
      try:
        os.kill(args.pid, 0)
      except ProcessLookupError:
        break
      time.sleep(30)
    report_path = args.study / 'report.json'
    if not report_path.exists():
      status['error'] = 'study_process_exited_without_report'
    else:
      report = json.loads(report_path.read_text())
      status['study_report'] = str(report_path)
      status['study_passed'] = bool(report.get('passed'))
      if not report.get('passed'):
        status['error'] = report.get('error', 'study_report_not_passed')
      elif args.audit_output.exists():
        status['error'] = 'audit_output_already_exists'
      else:
        completed = subprocess.run(
            [args.python, args.auditor, '--study', args.study, '--output', args.audit_output],
            check=False,
        )
        status['audit_exit_code'] = completed.returncode
        audit_report = args.audit_output / 'report.json'
        if completed.returncode == 0 and audit_report.exists():
          audit = json.loads(audit_report.read_text())
          status['audited'] = True
          status['passed'] = bool(audit.get('passed'))
          if not status['passed']:
            status['error'] = audit.get('error', 'audit_report_not_passed')
        else:
          status['error'] = 'audit_process_failed'
  except BaseException as error:
    status['error'] = f'{type(error).__name__}: {error}'
  finally:
    write(args.status_output, status)
  return 0 if status['passed'] else 1


if __name__ == '__main__':
  raise SystemExit(main())
