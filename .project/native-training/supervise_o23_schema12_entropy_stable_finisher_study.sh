#!/bin/sh
# Wait for the already-running serial study, then create its independent audit.
set -u
exec >> /root/work_space/football-artifacts/work-o23-schema12-entropy-stable-finisher-study-supervisor-20261028-a.log 2>&1
study_pid="$1"
study="$2"
audit_output="$3"
auditor="/root/work_space/football/.project/native-training/audit_o23_schema12_entropy_stable_finisher_study.py"
python="/root/work_space/football-artifacts/schema9-quality-venv/bin/python3"

while kill -0 "$study_pid" 2>/dev/null; do
  sleep 30
done

if [ ! -f "$study/report.json" ]; then
  printf '%s\n' "study process ended without report.json; no audit was run" >&2
  exit 2
fi

exec "$python" "$auditor" --study "$study" --output "$audit_output"
