#!/usr/bin/env bash
# Advance only the already-registered schema8 chain.  A nonzero stage exits
# immediately, leaving its report and logs as the failure receipt.
set -euo pipefail

repo=/root/work_space/football
artifacts=/root/work_space/football-artifacts
python="$artifacts/runtime-20261020-a/venv/bin/python"
remaining="$artifacts/work-o23-midl-remaining-study-20261027-a"
assembled="$artifacts/work-o23-midl-assembled-20261027-a"
assembled_audit="$artifacts/work-o23-midl-assembled-audit-20261027-a"
confirmation="$artifacts/work-o23-midl-confirmation-20261027-a"
confirmation_audit="$artifacts/work-o23-midl-confirmation-audit-20261027-a"
quality="$artifacts/work-o23-midl-quality-20261026-a"
build="$artifacts/work-o23-midl-quality-build-20261026-a"
recovery="$artifacts/work-o23-midl-seed42-recovery-20261027-a"
recovery_audit="$artifacts/work-o23-midl-seed42-recovery-audit-20261027-a"

while [[ ! -f "$remaining/report.json" ]]; do
  sleep 30
done

"$python" - "$remaining/report.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
assert report['passed'], report.get('error')
PY

"$python" "$repo/.project/native-training/assemble_o23_midl_recovery_study.py" \
  --recovery "$recovery" --recovery-audit "$recovery_audit" --remaining "$remaining" \
  --quality "$quality" --build "$build" --output "$assembled"
"$python" "$repo/.project/native-training/audit_o23_midl_recovery_study.py" \
  --study "$assembled" --output "$assembled_audit"
"$python" "$repo/.project/native-training/confirm_o23_midl.py" prepare \
  --study "$assembled" --audit "$assembled_audit" --quality "$quality" --build "$build" \
  --output "$confirmation"
"$python" "$repo/.project/native-training/confirm_o23_midl.py" run --output "$confirmation"
"$python" "$repo/.project/native-training/audit_o23_midl_confirmation.py" \
  --assessment "$confirmation" --output "$confirmation_audit"
