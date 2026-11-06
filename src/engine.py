"""Business tools, durable steps and exact accounting; model cannot override facts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from .domain import cents, digest, instant


class Engine:
    def __init__(self, store, request_id, owner, clock=None):
        self.store,self.request_id,self.owner=store,request_id,owner
        self.clock=clock or (lambda: datetime.now(timezone.utc))

    def quote(self,state,package):
        catalog=state["catalog"]
        specs=[("search_materials",catalog["tools"]["search_materials"]),
               ("generate_script:"+package,{"cost":catalog["packages"][package]["script_cost"],
                                            "minutes":catalog["packages"][package]["script_minutes"]}),
               ("save_plan",catalog["tools"]["save_plan"])]
        remaining=[(key,rule) for key,rule in specs if state["steps"].get(key,{}).get("status")!="succeeded"]
        cost=state["spent_cents"]+sum(cents(rule["cost"]) for _,rule in remaining)
        minutes=sum(rule["minutes"] for _,rule in remaining)
        now=max(self.clock(),instant(state["created_at"])+timedelta(minutes=state["elapsed_minutes"]))
        finish=now+timedelta(minutes=minutes)
        deadline=instant(state["request"]["deadline"])
        budget=cents(state["request"]["budget"])
        return {"package":package,"estimated_total_cents":cost,"estimated_total":cost/100,
                "spent_cents":state["spent_cents"],"spent":state["spent_cents"]/100,
                "remaining_minutes":minutes,"projected_finish":finish.isoformat(),
                "budget_gap":max(0,cost-budget)/100,
                "deadline_gap_minutes":max(0,round((finish-deadline).total_seconds()/60,3)),
                "feasible":cost<=budget and finish<=deadline}

    def view(self):
        state=self.store.get(self.request_id)
        missing=[k for k in ("budget","deadline") if state["request"].get(k) in (None,"")]
        quotes=[] if missing else [self.quote(state,p) for p in state["catalog"]["packages"]]
        return {"request":state["request"],"selected_package":state["package"],
                "estimated_package":state["estimate_package"],
                "steps":state["steps"],"spent":state["spent_cents"]/100,
                "elapsed_minutes":state["elapsed_minutes"],"plan_id":state["plan_id"],
                "missing":missing,"options":quotes,
                "catalog":{"packages":state["catalog"]["packages"],"tools":state["catalog"]["tools"]}}

    def execute(self,action):
        if not isinstance(action,dict) or set(action)!={"tool","arguments","reason"} or not isinstance(action["arguments"],dict) or not isinstance(action["reason"],str):
            return {"status":"rejected","error":"invalid_action"}
        tool,args=action["tool"],action["arguments"]
        try:
            return self.store.mutate(self.request_id,self.owner,lambda s,db:self._apply(s,db,tool,args))
        except sqlite3.Error:
            # The failed write rolled back. Record failure separately without losing earlier successes.
            def record(state,db):
                self._failure(state,"save_plan" if tool=="save_plan" else str(tool),"storage_failure")
                return {"status":"failed","error":"storage_failure","saved":False}
            try:
                return self.store.mutate(self.request_id,self.owner,record)
            except sqlite3.Error:
                return {"status":"failed","error":"storage_unavailable","saved":False}

    def _failure(self,state,key,error):
        previous=state["steps"].get(key,{})
        attempts=previous.get("attempts",0)+1
        state["steps"][key]={"status":"failed","attempts":attempts,"result":None,"error":error}
        state["elapsed_minutes"]+=state["catalog"]["failure_minutes"]
        state["events"].append({"tool":key,"status":"failed","attempt":attempts,"cost_cents":0,"error":error})

    def _apply(self,state,db,tool,args):
        if state["plan_id"]:
            return {"status":"existing","plan_id":state["plan_id"],"operation_complete":True}
        missing=[k for k in ("budget","deadline") if state["request"].get(k) in (None,"")]
        if missing: return {"status":"rejected","error":"missing_inputs","missing":missing}
        if tool=="select_plan" and set(args)=={"package"}:
            package=args["package"]
            if not isinstance(package,str) or package not in state["catalog"]["packages"]:
                return {"status":"rejected","error":"unknown_package"}
            state["package"]=package
            state["estimate_package"]=None
            return {"status":"selected","package":package,"retained_successful_steps":
                    [k for k,v in state["steps"].items() if v["status"]=="succeeded"]}
        if tool not in ("search_materials","generate_script","estimate_cost","save_plan") or args:
            return {"status":"rejected","error":"invalid_tool_or_arguments",
                    "allowed_tools":["select_plan","estimate_cost","search_materials","generate_script","save_plan","finish"],
                    "expected_arguments":{} if tool in ("search_materials","generate_script","estimate_cost","save_plan") else None,
                    "detail":"These four tools take empty arguments. Package comes from select_plan; do not pass package again."}
        package=state["package"]
        if not package: return {"status":"rejected","error":"select_plan_first"}
        if tool=="estimate_cost":
            state["elapsed_minutes"]+=state["catalog"]["tools"][tool]["minutes"]
            state["estimate_package"]=package
            quote=self.quote(state,package)
            alternatives=[self.quote(state,p) for p in state["catalog"]["packages"] if p!=package]
            state["events"].append({"tool":tool,"status":"succeeded","cost_cents":0,"quote":quote})
            return {"status":"estimated",**quote,"alternatives":alternatives}
        key="generate_script:"+package if tool=="generate_script" else tool
        prior=state["steps"].get(key,{})
        if prior.get("status")=="succeeded":
            return {"status":"existing","step":key,"result":prior["result"],"charged":0}
        if state["estimate_package"]!=package:
            return {"status":"rejected","error":"estimate_current_plan_first"}
        quote=self.quote(state,package)
        if not quote["feasible"]:
            return {"status":"rejected","error":"constraints_exceeded",**quote,
                    "alternatives":[self.quote(state,p) for p in state["catalog"]["packages"]]}
        if tool in ("generate_script","save_plan") and state["steps"].get("search_materials",{}).get("status")!="succeeded":
            return {"status":"rejected","error":"search_dependency_required"}
        if tool=="save_plan" and state["steps"].get("generate_script:"+package,{}).get("status")!="succeeded":
            return {"status":"rejected","error":"script_dependency_required"}
        attempts=prior.get("attempts",0)
        if attempts<state["catalog"]["failures"].get(key,0):
            self._failure(state,key,"injected_tool_failure")
            return {"status":"failed","step":key,"error":"injected_tool_failure","charged":0,
                    "retained_successful_steps":[k for k,v in state["steps"].items() if v["status"]=="succeeded"]}
        if tool=="search_materials" and not state["catalog"]["materials"]:
            self._failure(state,key,"no_materials")
            return {"status":"failed","step":key,"error":"no_materials","charged":0}
        if tool=="search_materials":
            rule=state["catalog"]["tools"][tool]
            result={"topic":state["request"]["topic"],"materials":deepcopy(state["catalog"]["materials"])}
        elif tool=="generate_script":
            rule={"cost":state["catalog"]["packages"][package]["script_cost"],
                  "minutes":state["catalog"]["packages"][package]["script_minutes"]}
            materials=state["steps"]["search_materials"]["result"]["materials"]
            result={"package":package,"title":state["request"]["topic"]+" · 内容活动方案",
                    "script":[{"stage":"开场","text":"围绕主题介绍目标用户的场景与问题。"},
                              {"stage":"主体","text":"结合素材："+materials[0]["summary"]},
                              {"stage":"互动","text":"邀请读者分享体验，收集问题并整理答复。"}],
                    "material_ids":[m["id"] for m in materials],
                    "production_note":"本地合成脚本工具；真实模型负责规划决策，不宣称调用外部内容生产服务。"}
        else:
            rule=state["catalog"]["tools"][tool]
            plan_id="plan-"+digest(self.request_id)[:20]
            result={"plan_id":plan_id,"request_id":self.request_id,"topic":state["request"]["topic"],
                    "package":package,"task_plan":self.task_plan(state),
                    "script":state["steps"]["generate_script:"+package]["result"],
                    "total_cost":(state["spent_cents"]+cents(rule["cost"]))/100,
                    "deadline":state["request"]["deadline"],"projected_finish":quote["projected_finish"]}
            db.execute("INSERT INTO plans VALUES(?,?,?)",
                       (self.request_id,plan_id,json.dumps(result,ensure_ascii=False)))
            state["plan_id"]=plan_id
        amount=cents(rule["cost"])
        state["spent_cents"]+=amount
        state["elapsed_minutes"]+=rule["minutes"]
        state["steps"][key]={"status":"succeeded","attempts":attempts+1,"result":result,"error":None}
        state["events"].append({"tool":key,"status":"succeeded","attempt":attempts+1,"cost_cents":amount})
        return {"status":"saved" if tool=="save_plan" else "succeeded","step":key,"result":result,
                "charged":amount/100,"spent":state["spent_cents"]/100,
                "operation_complete":tool=="save_plan"}

    @staticmethod
    def task_plan(state):
        package=state["package"]
        return [{"step":"search_materials","depends_on":[]},
                {"step":"generate_script:"+str(package),"depends_on":["search_materials"]},
                {"step":"save_plan","depends_on":["generate_script:"+str(package)]}]

    def result(self,status,reason=None):
        state=self.store.get(self.request_id)
        missing=[k for k in ("budget","deadline") if state["request"].get(k) in (None,"")]
        options=[] if missing or state["plan_id"] else [self.quote(state,p) for p in state["catalog"]["packages"]]
        return {"request_id":self.request_id,"status":status,"reason":reason,
                "topic":state["request"]["topic"],"missing":missing,"package":state["package"],
                "task_plan":self.task_plan(state),"steps":state["steps"],"tool_events":state["events"],
                "actual_cost":state["spent_cents"]/100,"actual_cost_cents":state["spent_cents"],
                "simulated_elapsed_minutes":state["elapsed_minutes"],"plan_id":state["plan_id"],
                "save_status":"saved" if state["plan_id"] else "not_saved",
                "saved_plan":state["steps"].get("save_plan",{}).get("result"),
                "options":options,"published":False}
