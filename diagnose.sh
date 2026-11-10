#!/bin/bash
# Lead Agent health check. Collects machine, Ollama and last-run details into one text file
# so problems can be diagnosed remotely. It never reads keys.vault, .env or any API key.
#
#   bash diagnose.sh
cd "$(dirname "$0")" || exit 1
mkdir -p output
OUT="output/diagnose-$(date +%Y%m%d-%H%M%S).txt"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3

{
echo "=== LEAD AGENT DIAGNOSE  $(date '+%a %d %b %Y %H:%M:%S') ==="
echo
echo "--- 1. Mac ---"
echo "Chip:    $(sysctl -n machdep.cpu.brand_string 2>/dev/null) ($(uname -m))"
echo "RAM:     $(( $(sysctl -n hw.memsize) / 1073741824 )) GB"
echo "macOS:   $(sw_vers -productVersion)"
echo "Free disk: $(df -h . | awk 'NR==2{print $4}')"
memory_pressure 2>/dev/null | grep -i "free percentage" || true
echo
echo "--- 2. Lead Agent version ---"
git log --oneline -3 2>/dev/null || echo "not a git folder"
git status --short 2>/dev/null | grep -v '^??' | head -10
echo "Python:  $($PY --version 2>&1)"
echo
echo "--- 3. Running now ---"
ps ax -o pid,etime,%cpu,%mem,command | grep -E "run.py|dashboard.py|ollama" | grep -v grep || echo "nothing running"
echo
echo "--- 4. Ollama ---"
if curl -s -m 5 localhost:11434/api/tags >/dev/null; then
  echo "Ollama engine: RUNNING"
  curl -s localhost:11434/api/version; echo
  echo "Models installed:"
  curl -s localhost:11434/api/tags | python3 -c "import sys,json;[print('  ',m['name'],round(m['size']/1e9,1),'GB') for m in json.load(sys.stdin)['models']]"
  echo "Loaded in memory:"
  curl -s localhost:11434/api/ps | python3 -c "import sys,json;d=json.load(sys.stdin)['models'];[print('  ',m['name'],'GPU part:',round(m.get('size_vram',0)/1e9,1),'GB of',round(m['size']/1e9,1),'GB') for m in d] or print('   none')"
  echo
  echo "Speed test (one lead-sized AI answer, please wait up to 5 minutes)..."
  START=$(date +%s)
  curl -s -m 300 localhost:11434/api/generate -d '{"model":"qwen3:8b","prompt":"Reply ONLY with JSON {\"score\": <0-10>, \"reason\": \"<10 words>\"} for this lead: yoga teacher in Mumbai who sells online classes.","stream":false,"format":"json","think":false,"options":{"num_predict":60}}' \
    | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    if 'error' in d: print('  ERROR:', d['error']); raise SystemExit
    tps=d['eval_count']/(d['eval_duration']/1e9)
    print('  Answer:', d['response'].strip()[:120])
    print('  Model load time: %.1f s' % (d.get('load_duration',0)/1e9))
    print('  Total time for one lead: %.1f s' % (d['total_duration']/1e9))
    print('  Speed: %.1f tokens/s  (12+ good, 6-12 OK, under 6 slow)' % tps)
except (ValueError, KeyError) as e:
    print('  No answer from the model within 5 minutes or bad reply:', e)
"
  echo "  (wall clock: $(( $(date +%s) - START )) s)"
else
  echo "Ollama engine: NOT RUNNING  <-- open the Ollama app, then run this check again"
fi
echo
echo "--- 5. Last run log ---"
LAST=$(ls -t output/logs/*.log 2>/dev/null | head -1)
if [ -n "$LAST" ]; then
  echo "File: $LAST"
  tail -40 "$LAST"
else
  echo "no logs yet"
fi
echo
echo "--- 6. Last run report ---"
REP=$(ls -t output/run-*.csv 2>/dev/null | head -1)
if [ -n "$REP" ]; then
  echo "File: $REP"
  $PY -W ignore - "$REP" <<'EOF'
import csv, sys
from collections import Counter
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")))
print("Status counts:", dict(Counter(r["status"] for r in rows)))
for reason, n in Counter(r["reason"].split(":")[0] for r in rows if r["status"] == "Rejected").most_common(8):
    print(f"  {n:4}  {reason}")
notes = Counter(n.split(":")[0] for r in rows for n in r.get("notes", "").split(" | ") if "failed" in n)
if notes: print("AI failures:", dict(notes))
EOF
else
  echo "no reports yet"
fi
echo
echo "--- 7. Lead files waiting ---"
ls -la Leads/Incoming/*.csv 2>/dev/null || echo "none"
echo
echo "=== END ==="
} 2>&1 | tee "$OUT"

echo
echo "Saved to: $(pwd)/$OUT"
echo "Send this file (or a screenshot of everything above) to Mahaveer."
[ -z "$NO_REVEAL" ] && open -R "$OUT" 2>/dev/null
