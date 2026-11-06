from datetime import datetime, timezone

from .domain import validate_request,validate_catalog
from .engine import Engine
from .models import ModelError
from .store import StateError


class Agent:
    def __init__(self, model, store, catalog, max_steps=16, clock=None):
        if type(max_steps) is not int or not 1<=max_steps<=100: raise ValueError("max_steps must be 1..100")
        validate_catalog(catalog)
        self.model,self.store,self.catalog=model,store,catalog
        self.max_steps,self.clock=max_steps,clock
        self.trace=[]

    def run(self,request):
        missing=validate_request(request)
        self.trace=[]
        owner=self.store.acquire(request,self.catalog, self.clock().isoformat() if self.clock else None)
        engine=Engine(self.store,request["request_id"],owner,self.clock)
        status,reason="budget_exhausted","model_step_limit"
        try:
            state=self.store.get(request["request_id"])
            if missing:
                status,reason="needs_information","missing_required_inputs"
            elif state["plan_id"]:
                status,reason="completed","existing_plan_reused"
            else:
                history=[]
                for number in range(1,self.max_steps+1):
                    self.store.renew(request["request_id"],owner)
                    context={"request":request,"snapshot":engine.view(),"history":history}
                    try:
                        action=self.model.decide(context)
                    except ModelError as exc:
                        if history: history[-1]["next_action"]="model"
                        self.trace.append({"step":number,"action":{"tool":"model","arguments":{},"reason":"Model call failed"},
                                           "observation":{"status":"failed","error":str(exc)},"next_action":"stop:failed"})
                        status,reason="failed","model_unavailable"
                        break
                    valid=isinstance(action,dict) and set(action)=={"tool","arguments","reason"} and isinstance(action["arguments"],dict) and isinstance(action["reason"],str)
                    terminal=False
                    if valid and action["tool"]=="finish" and set(action["arguments"])=={"outcome"}:
                        outcome=action["arguments"]["outcome"]
                        view=engine.view()
                        allowed=[]
                        if view["plan_id"]: allowed=["completed"]
                        elif view["missing"]: allowed=["needs_information"]
                        elif view["options"] and not any(q["feasible"] for q in view["options"]): allowed=["infeasible"]
                        elif any(s["status"]=="failed" for s in view["steps"].values()): allowed=["failed"]
                        if outcome in allowed:
                            status,reason=outcome,("no_feasible_plan" if outcome=="infeasible" else None)
                            observation={"status":"finished","outcome":outcome}
                            terminal=True
                        else:
                            observation={"status":"rejected","error":"unsupported_finish","allowed_outcomes":allowed}
                    else:
                        observation=engine.execute(action)
                    safe={"tool":str(action.get("tool","invalid")) if isinstance(action,dict) else "invalid",
                          "arguments":action.get("arguments",{}) if isinstance(action,dict) else {},
                          "reason":str(action.get("reason",""))[:240] if isinstance(action,dict) else ""}
                    if history: history[-1]["next_action"]=safe["tool"]
                    record={"step":number,"action":safe,"observation":observation,"next_action":None}
                    history.append(record);self.trace.append(record)
                    if terminal: break
                if self.trace and self.trace[-1]["next_action"] is None:
                    self.trace[-1]["next_action"]="stop:"+status
            def finish(state,db):
                state["status"],state["reason"]=status,reason
            self.store.mutate(request["request_id"],owner,finish)
            result=engine.result(status,reason)
            result.update(mode=self.model.mode,model=self.model.name,steps_used=len(self.trace),max_steps=self.max_steps)
            return result
        finally:
            self.store.release(request["request_id"],owner)
