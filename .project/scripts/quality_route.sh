#!/usr/bin/env bash
# 2026-09-09: Phase 19+ uses current evidence, never text replacement or coordinator flags.
# Source this file, then call quality_route <action> <id>.
quality_route() {
  local action="$1" target="$2"
  if [[ "$target" =~ ^(ms|plan|task)-([0-9]+)\. ]] && (( 10#${BASH_REMATCH[2]} >= 19 )); then
    local quality_root
    quality_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    case "$action" in
      complete) exec python3 "$quality_root/quality.py" verify "$target" ;;
      test) exec python3 "$quality_root/quality.py" run "$target" ;;
      start|progress|review|snapshot|claim|fail)
        # These commands must not invent completion, erase evidence, or silently
        # write state to the historical coordinator. Show the computed status.
        exec python3 "$quality_root/quality.py" status "$target" ;;
      *) echo "Unsupported quality action: $action" >&2; exit 1 ;;
    esac
  fi
}
