from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event
import unittest
from unittest.mock import patch
from tests import test_planning as base
from src.agent import Agent
from src.domain import cents, validate_catalog
from src.models import MockModel, HTTPModel
from src.transport import HTTPTransport
from src.store import StateError

class HardeningTests(unittest.TestCase):
    setUp = base.PlanningTests.setUp
    run_agent = base.PlanningTests.run_agent

    def schema_run(self):
        model=HTTPModel.__new__(HTTPModel);model.name='schema-test';observed=[]
        def choose(instance,context):
            action=MockModel().decide(context)
            variants=instance.response_format['json_schema']['schema']['anyOf']
            allowed={v['properties']['tool']['enum'][0]:v for v in variants}
            self.assertIn(action['tool'],allowed)
            for key,value in action['arguments'].items():
                self.assertIn(value,allowed[action['tool']]['properties']['arguments']['properties'][key]['enum'])
            observed.append(context['snapshot']['available_actions'])
            return action
        with patch.object(HTTPTransport,'decide',choose):result=self.run_agent(model)
        return result,observed

    def test_custom_schema_progresses_to_save_without_repeating_success(self):
        self.catalog['packages']={'economy':self.catalog['packages']['basic']}
        result,observed=self.schema_run()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(observed,[['select_plan'],['estimate_cost'],['search_materials'],['generate_script'],['save_plan'],['finish']])

    def test_schema_preserves_budget_replan_and_failure_stop_choices(self):
        self.catalog['failures']={'generate_script:basic':1}
        result,observed=self.schema_run()
        self.assertEqual(result['status'],'failed')
        self.assertIn(['select_plan'],observed)
        self.assertEqual(set(observed[-1]),{'generate_script','select_plan','finish'})

    def test_long_decimal_cannot_round_into_budget(self):
        for value in ('7.999999999999999999999999999999', '10.000000000000000000000000000001'):
            with self.subTest(value=value), self.assertRaises(ValueError): cents(value)

    def test_tiny_nonzero_amount_not_rounded_to_zero(self):
        with self.assertRaises(ValueError): cents('1e-1000000')

    def test_blank_constraints_return_missing_without_work(self):
        self.request.update(budget='  ', deadline='\t')
        r=self.run_agent()
        self.assertEqual(r['status'],'needs_information')
        self.assertEqual(r['actual_cost'],0)
        self.assertEqual(set(r['missing']),{'budget','deadline'})

    def test_malformed_price_table_has_validation_error(self):
        for bad in (None, [], {'script_minutes':1}, {'script_cost':1}):
            c=deepcopy(self.catalog);c['packages']['basic']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_catalog(c)

    def test_failed_save_resume_after_deadline_preserves_script(self):
        self.catalog['failures']={'save_plan':1}
        first=self.run_agent();self.assertEqual(first['actual_cost'],6)
        second=Agent(MockModel(),self.store,self.catalog,clock=lambda:base.NOW+timedelta(days=1)).run(self.request)
        self.assertEqual(second['status'],'infeasible')
        self.assertEqual(second['actual_cost'],6)
        self.assertEqual(second['steps']['generate_script:basic'],first['steps']['generate_script:basic'])
        self.assertIsNone(second['plan_id'])

    def test_two_real_threads_same_key_only_one_writer(self):
        entered=Event();release=Event()
        class Slow(MockModel):
            def decide(self,context):entered.set();release.wait(5);return super().decide(context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(Agent(Slow(),self.store,self.catalog,clock=lambda:base.NOW).run,self.request)
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaisesRegex(StateError,'request_busy'):self.run_agent()
            finally:release.set()
            self.assertEqual(future.result(timeout=10)['status'],'completed')
        self.assertEqual(len(self.store.saved()),1)

    def test_different_request_keys_do_not_share_failure_counter(self):
        self.catalog['failures']={'save_plan':1}
        first=self.run_agent();self.request['request_id']='second'
        second=self.run_agent()
        self.assertEqual((first['status'],second['status']),('failed','failed'))
        self.assertEqual(second['steps']['save_plan']['attempts'],1)

    def test_custom_package_names_complete(self):
        self.catalog['packages']={'economy':self.catalog['packages']['basic']}
        r=self.run_agent();self.assertEqual(r['status'],'completed');self.assertEqual(r['package'],'economy')

    def test_zero_cost_catalog_keeps_exact_ledger(self):
        self.request['budget']=0
        for p in self.catalog['packages'].values():p['script_cost']=0
        for t in self.catalog['tools'].values():t['cost']=0
        r=self.run_agent();self.assertEqual(r['status'],'completed');self.assertEqual(r['actual_cost_cents'],0)

    def test_budget_one_cent_below_plan_no_paid_execution(self):
        self.request['budget']='7.99';r=self.run_agent()
        self.assertEqual(r['status'],'infeasible');self.assertEqual(r['actual_cost'],0)
        self.assertEqual(min(q['budget_gap'] for q in r['options']),.01)
