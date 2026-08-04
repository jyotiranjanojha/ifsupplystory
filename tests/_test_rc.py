import sys, os, json, time
sys.path.insert(0, 'webapp')
os.environ.setdefault('OLLAMA_MODEL', 'gemma3:latest')
from pathlib import Path
from app.analyzer import _compute_rc_deep_evidence, run_root_cause, _ollama_chat_with_model

base = Path('.')
raw = run_root_cause(base, None, None, '100000000008', {})
ds = raw.get('Demand and Supply Summary', {})
demand_qty = float(ds.get('demand_qty_total') or 0)
sched_qty  = float(ds.get('scheduled_qty_total') or 0)
fill_rate  = round(sched_qty / demand_qty * 100, 1) if demand_qty else 0

deep = _compute_rc_deep_evidence(base, '100000000008', '202547', 'CONSTRAINED', None)

pb = deep.get('period_balance', [])
worst = sorted(pb, key=lambda r: r.get('gap', 0), reverse=True)[:8]
period_table_lines = ['| Period | Demand | Sched | Gap | Fill% |', '|--------|--------|-------|-----|-------|']
for r in worst:
    period_table_lines.append(
        f"| {r['period']} | {r.get('demand_qty',0):.0f} | {r.get('sched_qty',0):.0f} | {r.get('gap',0):.0f} | {r.get('fill_pct',0):.1f}% |"
    )
period_table = '\n'.join(period_table_lines)

lat = deep.get('lateness_analysis') or {}
lateness_text = (
    f"Late rows: {lat.get('late_rows',0)}, Avg: {lat.get('avg_days','N/A')} days, "
    f"Max: {lat.get('max_days','N/A')} days, >30d: {lat.get('gt_30_days',0)}"
)
signals = '\n'.join(f"- {s}" for s in deep.get('supply_constraint_signals', []))
res_lines = [
    f"- {r['resource']}: total={r.get('total_load',0):.0f}, cust={r.get('customer_load',0):.0f}"
    for r in deep.get('top_resource_loads', [])[:5]
]
exc_lines = [
    f"- {e['exception']} ({e['descr']}) at {e['loc']} on {e.get('when','N/A')}"
    for e in deep.get('exception_detail', [])[:5]
]

brief = f"""ITEM: 100000000008 | WEEK: 202547 | SCENARIO: CONSTRAINED | FILL RATE: {fill_rate}%
Demand: {demand_qty:.0f} | Sched: {sched_qty:.0f} | Unmet: {demand_qty-sched_qty:.0f}
Late qty: {ds.get('late_scheduled_qty',0):.0f} | On-time: {ds.get('on_time_scheduled_qty',0):.0f}
First need: {ds.get('first_need_date','N/A')} | First sched: {ds.get('first_sched_date','N/A')}

PERIOD GAPS (worst first):
{period_table}

LATENESS: {lateness_text}

SUPPLY CONSTRAINTS:
{signals}

TOP RESOURCES:
{chr(10).join(res_lines)}

EXCEPTIONS:
{chr(10).join(exc_lines) if exc_lines else 'None'}

ROOT CAUSES: {json.dumps(raw.get('Root Causes', []))}
"""

user_prompt = (
    "Analyze this BY ESP planning data and write a concise root cause analysis.\n"
    "Use these sections: ### Executive Summary / ### Confirmed Root Causes / "
    "### Supply Constraint Details / ### Recommended Next Steps\n\n"
    f"DATA:\n{brief}"
)

system_prompt = (
    "You are an Intel Foundry supply planning expert. "
    "Be concise and specific. Cite exact numbers from the data. "
    "Use markdown headers (###) and bullet lists (-)."
)

print(f"Prompt length: {len(user_prompt)} chars (~{len(user_prompt)//4} tokens)")
print("Sending to LLM...")

t0 = time.time()
reply = _ollama_chat_with_model(user_prompt, system_prompt, 'gemma3:latest')
elapsed = time.time() - t0

print(f"Reply length: {len(reply) if reply else 0} chars  ({elapsed:.1f}s)")
print("LLM used:", bool(reply))
if reply:
    print("\n=== REPLY ===")
    print(reply)
else:
    print("ERROR: LLM returned None (timed out or empty)")
