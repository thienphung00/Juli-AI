#!/usr/bin/env bash
# Obs 1, bullet 4 — beat tasks complete a cycle without a scoping error.
set -uo pipefail
SINCE="$(systemctl show -p ActiveEnterTimestamp --value juli-celery-worker | sed 's/^[A-Za-z]* //; s/ UTC$//')"
echo "worker restarted at : $SINCE"
echo "release            : $(readlink -f /root/releases/current | xargs basename)"
echo
echo "== per-task outcomes since that restart =="
journalctl -u juli-celery-worker --since "$SINCE" --no-pager 2>/dev/null \
  | grep -E "succeeded in|raised unexpected" \
  | sed -E "s/.*Task //; s/\[[^]]*\]//; s/ in [0-9.]+s.*//; s/: .*//" \
  | sort | uniq -c
echo
echo "== scoping errors (MUST be 0) =="
journalctl -u juli-celery-worker --since "$SINCE" --no-pager 2>/dev/null \
  | grep -icE "row-level security|InsufficientPrivilege|permission denied|TenantContextRequired" \
  | sed 's/^/  count: /'
echo
echo "== the five named in Obs 1 bullet 4 =="
for t in mock_analytics_hourly_reconcile analytics_backfill_topup daily_impact_reader \
         reap_abandoned_workflow_runs credential_refresh_beat; do
  ok=$(journalctl -u juli-celery-worker --since "$SINCE" --no-pager 2>/dev/null | grep -c "$t.*succeeded in")
  bad=$(journalctl -u juli-celery-worker --since "$SINCE" --no-pager 2>/dev/null | grep -c "$t.*raised unexpected")
  if   [ "$bad" -gt 0 ]; then st="FAILED ($bad)"
  elif [ "$ok"  -gt 0 ]; then st="ok ($ok)"
  else st="NOT YET RUN"; fi
  printf "  %-34s %s\n" "$t" "$st"
done
