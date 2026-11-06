"""Generate evidence from execution, never from expected text. Run as python -m scripts.evaluate."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from src.agent import Agent
from src.models import MockModel, HTTPModel
from src.scenarios import scenario
from src.store import Store


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mock","real"), default="mock")
    parser.add_argument("--output", default="examples/mock")
    parser.add_argument("--cases", nargs="+", default=["normal","reference","missing","tool_failure","over_budget","deadline","resume","save_failure"])
    args=parser.parse_args();out=Path(args.output)
    report={"mode":args.mode,"started_at":datetime.now(timezone.utc).isoformat(),"cases":[],"passed":True}
    for name in args.cases:
        with tempfile.TemporaryDirectory() as temp:
            payload=scenario(name);payload["mode"]=args.mode
            folder=out/name;dump(folder/"input.json",payload)
            results=[];traces=[]
            runs=2 if name in ("reference","resume","save_failure") else 1
            for index in range(runs):
                start=time.monotonic();model=HTTPModel() if args.mode=="real" else MockModel()
                # New Store/Agent on every run proves all continuation state is durable.
                store=Store(Path(temp)/"state.db")
                agent=Agent(model,store,payload["catalog"],payload["max_steps"])
                result=agent.run(payload["request"])
                results.append(result);traces.append(agent.trace)
                dump(folder/f"run-{index+1}-output.json",result)
                (folder/f"run-{index+1}-trace.jsonl").write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in agent.trace),encoding="utf-8")
                dump(folder/f"run-{index+1}-meta.json",{"timestamp":datetime.now(timezone.utc).isoformat(),"seconds":round(time.monotonic()-start,2),"mode":model.mode,"model":model.name,"saved_plan_count":len(store.saved())})
                print(f"{args.mode}/{name}/{index+1}: {result['status']} cost={result['actual_cost']} steps={result['steps_used']}",flush=True)
            first,last=results[0],results[-1]
            checks={"ledger_exact":all(sum(e["cost_cents"] for e in r["tool_events"])==r["actual_cost_cents"] for r in results),
                    "within_budget":all(r["actual_cost"]<=float(payload["request"].get("budget") or 0) for r in results),
                    "no_fake_save":all((r["save_status"]=="saved")==bool(r["saved_plan"]) for r in results)}
            if name in ("normal","reference","tool_failure","resume","save_failure"):
                checks.update(completed=last["status"]=="completed",unique_plan=len(store.saved())==1)
            if name=="reference":
                estimates=[s["observation"].get("estimated_total") for s in traces[0] if s["action"]["tool"]=="estimate_cost"]
                checks.update(observed_twelve_then_eight=estimates[:2]==[12,8],cost_eight=last["actual_cost"]==8,
                              repeated_no_work=last["steps_used"]==0 and first["tool_events"]==last["tool_events"])
            if name=="missing":checks.update(no_work=first["status"]=="needs_information" and first["steps_used"]==0 and first["actual_cost"]==0)
            if name in ("over_budget","deadline"):checks.update(infeasible=first["status"]=="infeasible",no_spending=first["actual_cost"]==0)
            if name=="tool_failure":
                checks.update(actual_failure=any(e["status"]=="failed" for e in last["tool_events"]),retained_search=last["steps"].get("search_materials",{}).get("attempts")==1)
            if name in ("resume","save_failure"):
                checks.update(actual_failure=any(e["status"]=="failed" for e in last["tool_events"]),retained_search=last["steps"].get("search_materials",{}).get("attempts")==1,cost_eight=last["actual_cost"]==8)
                if args.mode=="mock":checks["separate_run_resume"]=first["status"]=="failed" and last["status"]=="completed"
            case={"name":name,"checks":checks,"passed":all(checks.values()),"states":[r["status"] for r in results]}
            report["cases"].append(case);report["passed"] &= case["passed"]
            dump(out/"acceptance.json",report)
    report["finished_at"]=datetime.now(timezone.utc).isoformat();dump(out/"acceptance.json",report)
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
