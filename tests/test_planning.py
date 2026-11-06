from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.agent import Agent
from src.domain import cents,validate_request,validate_catalog
from src.engine import Engine
from src.models import MockModel,ModelError
from src.store import Store,StateError

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,6,8,0,tzinfo=timezone.utc)


def action(tool,**arguments):
    return {"tool":tool,"arguments":arguments,"reason":"Test evidence-based boundary."}


class Scripted:
    mode="test"
    name="adversarial-actions"
    def __init__(self,actions): self.actions=iter(actions)
    def decide(self,context): return next(self.actions,action("publish"))


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/"state.db")
        self.catalog=json.loads((ROOT/"data/catalog.json").read_text(encoding="utf-8"))
        self.request={"request_id":"case","topic":"秋季活动","budget":10,"deadline":(NOW+timedelta(hours=2)).isoformat()}

    def run_agent(self,model=None,steps=16):
        self.agent=Agent(model or MockModel(),self.store,self.catalog,steps,clock=lambda:NOW)
        return self.agent.run(self.request)

    def test_reference_replans_from_twelve_to_eight(self):
        r=self.run_agent()
        self.assertEqual(r["status"],"completed")
        estimates=[e["quote"]["estimated_total"] for e in r["tool_events"] if e["tool"]=="estimate_cost"]
        self.assertEqual(estimates[:2],[12,8]);self.assertEqual(r["actual_cost"],8)
        self.assertEqual(r["package"],"basic")
        self.assertEqual(len(self.store.saved()),1)

    def test_normal_premium_fits(self):
        self.request["budget"]=20
        r=self.run_agent();self.assertEqual(r["actual_cost"],12)
        self.assertEqual(r["package"],"premium")

    def test_missing_budget_has_no_paid_work(self):
        del self.request["budget"]
        r=self.run_agent();self.assertEqual(r["status"],"needs_information")
        self.assertEqual(r["actual_cost"],0);self.assertEqual(r["steps"],{})

    def test_missing_deadline_has_no_paid_work(self):
        self.request["deadline"]=None
        r=self.run_agent();self.assertEqual(r["missing"],["deadline"])
        self.assertIsNone(r["plan_id"])

    def test_no_feasible_budget_reports_gap(self):
        self.request["budget"]=7
        r=self.run_agent();self.assertEqual(r["status"],"infeasible")
        self.assertEqual(min(q["budget_gap"] for q in r["options"]),1)
        self.assertEqual(r["actual_cost"],0)

    def test_tool_failure_changes_plan_and_retains_search(self):
        self.request["budget"]=20
        self.catalog["failures"]={"generate_script:premium":1}
        r=self.run_agent();self.assertEqual(r["status"],"completed")
        self.assertEqual(r["steps"]["generate_script:premium"]["status"],"failed")
        self.assertEqual(r["steps"]["search_materials"]["attempts"],1)
        self.assertEqual(r["package"],"basic");self.assertEqual(r["actual_cost"],8)

    def test_repeat_is_zero_additional_work(self):
        first=self.run_agent();second=self.run_agent()
        self.assertEqual(first["plan_id"],second["plan_id"])
        self.assertEqual(second["steps_used"],0)
        self.assertEqual(first["tool_events"],second["tool_events"])

    def test_failed_step_resumes_from_new_store_instance(self):
        self.catalog["failures"]={"generate_script:basic":1}
        first=self.run_agent();self.assertEqual(first["status"],"failed")
        self.assertEqual(first["actual_cost"],2)
        search=first["steps"]["search_materials"]["result"]
        self.store=Store(self.store.path)
        second=self.run_agent();self.assertEqual(second["status"],"completed")
        self.assertEqual(second["actual_cost"],8)
        self.assertEqual(second["steps"]["search_materials"]["result"],search)
        self.assertEqual(second["steps"]["search_materials"]["attempts"],1)
        self.assertEqual(second["steps"]["generate_script:basic"]["attempts"],2)

    def test_save_failure_resume_preserves_script(self):
        self.catalog["failures"]={"save_plan":1}
        first=self.run_agent();self.assertEqual(first["status"],"failed")
        second=self.run_agent();self.assertEqual(second["status"],"completed")
        self.assertEqual(second["steps"]["generate_script:basic"]["attempts"],1)
        self.assertEqual(second["actual_cost"],8)

    def test_deadline_switches_to_faster_package(self):
        self.request["budget"]=20
        self.request["deadline"]=(NOW+timedelta(minutes=16)).isoformat()
        r=self.run_agent();self.assertEqual(r["package"],"basic")
        self.assertEqual(r["status"],"completed")

    def test_impossible_deadline_no_paid_work(self):
        self.request["deadline"]=(NOW+timedelta(minutes=3)).isoformat()
        r=self.run_agent();self.assertEqual(r["status"],"infeasible")
        self.assertGreater(min(q["deadline_gap_minutes"] for q in r["options"]),0)
        self.assertEqual(r["actual_cost"],0)

    def test_exact_budget_eight_is_allowed(self):
        self.request["budget"]=8
        self.assertEqual(self.run_agent()["status"],"completed")

    def test_one_cent_short_is_not_rounded_up(self):
        self.request["budget"]="7.99"
        r=self.run_agent();self.assertEqual(r["status"],"infeasible")
        self.assertEqual(min(q["budget_gap"] for q in r["options"]),.01)

    def test_invalid_money_is_rejected(self):
        for budget in (-1,True,"NaN","Infinity","0.001"):
            with self.subTest(budget=budget):
                self.request["budget"]=budget
                with self.assertRaises(ValueError):self.run_agent()

    def test_naive_time_is_rejected(self):
        self.request["deadline"]="2026-11-07T12:00:00"
        with self.assertRaises(ValueError):self.run_agent()

    def test_catalog_edit_cannot_reuse_old_state(self):
        self.run_agent()
        self.catalog["packages"]["basic"]["script_cost"]=1
        with self.assertRaisesRegex(StateError,"idempotency_conflict"):self.run_agent()

    def test_input_change_same_id_is_rejected(self):
        self.run_agent();self.request["budget"]=30
        with self.assertRaisesRegex(StateError,"idempotency_conflict"):self.run_agent()

    def test_skip_search_is_rejected(self):
        model=Scripted([action("select_plan",package="basic"),action("estimate_cost"),
                        action("generate_script"),action("save_plan")])
        r=self.run_agent(model,4)
        self.assertEqual(r["status"],"budget_exhausted")
        self.assertEqual(r["actual_cost"],0);self.assertIsNone(r["plan_id"])

    def test_model_cannot_fake_completion(self):
        r=self.run_agent(Scripted([action("finish",outcome="completed")]),1)
        self.assertEqual(r["status"],"budget_exhausted")
        self.assertIsNone(r["plan_id"])

    def test_model_cannot_change_budget_via_tool(self):
        r=self.run_agent(Scripted([action("select_plan",package="premium",budget=999),
                                   action("publish")]),2)
        self.assertEqual(r["actual_cost"],0);self.assertIsNone(r["plan_id"])

    def test_successful_abandoned_script_remains_in_cost(self):
        self.request["budget"]=20
        acts=[action("select_plan",package="premium"),action("estimate_cost"),action("search_materials"),
              action("generate_script"),action("select_plan",package="basic"),action("estimate_cost"),
              action("generate_script"),action("save_plan"),action("finish",outcome="completed")]
        r=self.run_agent(Scripted(acts));self.assertEqual(r["actual_cost"],16)
        self.assertEqual(r["status"],"completed")
        self.assertEqual(r["steps"]["generate_script:premium"]["status"],"succeeded")

    def test_budget_cannot_be_evaded_by_replanning(self):
        self.request["budget"]=12
        acts=[action("select_plan",package="premium"),action("estimate_cost"),action("search_materials"),
              action("generate_script"),action("select_plan",package="basic"),action("estimate_cost"),
              action("generate_script"),action("save_plan")]
        r=self.run_agent(Scripted(acts),8)
        self.assertEqual(r["actual_cost"],10);self.assertIsNone(r["plan_id"])

    def test_same_key_concurrent_lease_rejected(self):
        owner=self.store.acquire(self.request,self.catalog, NOW.isoformat())
        try:
            with self.assertRaisesRegex(StateError,"request_busy"):self.run_agent()
        finally:self.store.release(self.request["request_id"],owner)

    def test_expired_lease_recovered(self):
        old=self.store.acquire(self.request,self.catalog,NOW.isoformat())
        with self.store.connect() as db:db.execute("UPDATE requests SET lease_until=0")
        r=self.run_agent();self.assertEqual(r["status"],"completed")
        self.store.release(self.request["request_id"],old)
        self.assertIsNone(self.store.get(self.request["request_id"])["reason"])

    def test_sqlite_save_abort_keeps_successful_steps_and_no_plan(self):
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_plan BEFORE INSERT ON plans BEGIN SELECT RAISE(ABORT, 'write failure'); END")
        r=self.run_agent();self.assertEqual(r["status"],"failed")
        self.assertEqual(r["actual_cost"],6);self.assertEqual(self.store.saved(),[])
        self.assertEqual(r["steps"]["generate_script:basic"]["status"],"succeeded")
        with self.store.connect() as db:db.execute("DROP TRIGGER fail_plan")
        self.assertEqual(self.run_agent()["actual_cost"],8)

    def test_model_failure_after_search_preserves_paid_step(self):
        class Failing(MockModel):
            def decide(self,context):
                if context["snapshot"]["steps"].get("search_materials"):raise ModelError("test_failure")
                return super().decide(context)
        r=self.run_agent(Failing());self.assertEqual(r["status"],"failed")
        self.assertEqual(r["actual_cost"],2)
        self.assertEqual(self.run_agent()["actual_cost"],8)

    def test_empty_material_search_is_failed_not_success(self):
        self.catalog["materials"]=[]
        r=self.run_agent();self.assertEqual(r["status"],"failed")
        self.assertEqual(r["steps"]["search_materials"]["status"],"failed")
        self.assertEqual(r["actual_cost"],0)

    def test_deadline_can_expire_between_actions(self):
        owner=self.store.acquire(self.request,self.catalog,NOW.isoformat())
        moment=[NOW];engine=Engine(self.store,self.request["request_id"],owner,lambda:moment[0])
        try:
            engine.execute(action("select_plan",package="basic"));engine.execute(action("estimate_cost"))
            engine.execute(action("search_materials"))
            moment[0]=NOW+timedelta(days=1)
            self.assertEqual(engine.execute(action("generate_script"))["error"],"constraints_exceeded")
        finally:self.store.release(self.request["request_id"],owner)

    def test_step_limit_keeps_actual_partial_state(self):
        r=self.run_agent(steps=5)
        self.assertEqual(r["status"],"budget_exhausted")
        self.assertEqual(r["actual_cost"],2)
        self.assertEqual(self.run_agent()["status"],"completed")

    def test_fee_ledger_equals_total(self):
        r=self.run_agent()
        self.assertEqual(sum(e["cost_cents"] for e in r["tool_events"]),r["actual_cost_cents"])
        self.assertEqual(r["saved_plan"]["total_cost"],r["actual_cost"])

    def test_completed_historical_plan_can_be_read_after_deadline(self):
        first=self.run_agent()
        agent=Agent(MockModel(),self.store,self.catalog,clock=lambda:NOW+timedelta(days=3))
        second=agent.run(self.request)
        self.assertEqual(second["plan_id"],first["plan_id"]);self.assertEqual(second["steps_used"],0)

    def test_malformed_action_is_bounded(self):
        r=self.run_agent(Scripted([None,{},action("unknown")]),3)
        self.assertEqual(r["status"],"budget_exhausted");self.assertEqual(r["actual_cost"],0)
