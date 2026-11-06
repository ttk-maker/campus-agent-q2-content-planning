"""Check final acceptance against actual outputs, retaining historical failed attempts."""
from pathlib import Path
import json
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding="utf-8"))

def main():
    checks={}
    reference=read("examples/real/reference/run-1-output.json")
    trace=[json.loads(line) for line in (ROOT/"examples/real/reference/run-1-trace.jsonl").read_text(encoding="utf-8").splitlines()]
    estimates=[s["observation"].get("estimated_total") for s in trace if s["action"]["tool"]=="estimate_cost"]
    checks["real_budget_replanning"]=reference["status"]=="completed" and reference["actual_cost"]==8 and estimates[:2]==[12,8]
    repeat=read("examples/real/reference/run-2-output.json")
    checks["real_idempotency"]=repeat["steps_used"]==0 and repeat["plan_id"]==reference["plan_id"] and repeat["tool_events"]==reference["tool_events"]
    failure=read("examples/real-tool-retest/tool_failure/run-1-output.json")
    checks["real_tool_failure_and_replan"]=failure["status"]=="completed" and failure["actual_cost"]==8 and failure["steps"]["generate_script:premium"]["status"]=="failed" and failure["steps"]["search_materials"]["attempts"]==1
    over=read("examples/real/over_budget/run-1-output.json")
    checks["real_no_feasible_plan"]=over["status"]=="infeasible" and over["actual_cost"]==0 and min(q["budget_gap"] for q in over["options"])==1
    missing=read("examples/real/missing/run-1-output.json")
    checks["missing_information_guard"]=missing["status"]=="needs_information" and missing["steps_used"]==0 and missing["actual_cost"]==0
    normal=read("examples/browser-real/job.json")["result"]
    checks["real_normal_web"]=normal["status"]=="completed" and normal["actual_cost"]==12 and normal["save_status"]=="saved" and normal["mode"]=="real"
    for name in ("mock","browser","browser-real","tests"):
        data=read("examples/"+name+("/acceptance.json" if name=="mock" else "/report.json"))
        checks[name+"_passed"]=data["passed"]
    checks["real_ledger_consistency"]=all(sum(e["cost_cents"] for e in r["tool_events"])==r["actual_cost_cents"] for r in (reference,repeat,failure,over,missing,normal))
    for name in ('mock','browser','real-deadline-retest'):
        checks['hardening_'+name]=read('examples/hardening/'+name+'/report.json')['passed']
    for name,package in (('custom_package','economy'),('deadline_forces_basic','basic')):
        folder='real-retest' if name=='custom_package' else 'real-deadline-retest'
        run=read('examples/hardening/'+folder+'/'+name+'/run-1.json');r=run['output']
        checks['hardening_real_'+name]=r['status']=='completed' and r['package']==package and r['actual_cost']==8 and run['stored_plan_count']==1 and sum(e['cost_cents'] for e in r['tool_events'])==r['actual_cost_cents']
        if name=='deadline_forces_basic':checks['real_observed_deadline_conflict']=any(t['action']['tool']=='estimate_cost' and t['observation'].get('deadline_gap_minutes',0)>0 for t in run['trace'])
    report={"verified_at":datetime.now(timezone.utc).isoformat(),"passed":all(checks.values()),"checks":checks,
            "historical_failures_retained":["examples/real-initial-failure","examples/real-compact-attempt","examples/real/tool_failure","examples/tests-before-http-fix","examples/hardening/before.txt","examples/hardening/real","examples/hardening/real-retest"],
            "note":"Initial real suite includes a failed tool-failure case; final corresponding evidence is real-tool-retest. No failure log has been rewritten."}
    (ROOT/"examples/acceptance.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report["passed"] else 1

if __name__=="__main__":raise SystemExit(main())
