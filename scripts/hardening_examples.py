"""Actual edge scenario inputs, outputs and traces, separated by decision mode."""
import argparse
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
from scripts.evaluate import dump
from src.agent import Agent
from src.models import MockModel,HTTPModel
from src.scenarios import scenario
from src.store import Store

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['mock','real'],default='mock')
    p.add_argument('--output',default='examples/hardening/mock')
    p.add_argument('--case',choices=['custom_package','deadline_forces_basic']);args=p.parse_args()
    cases=['custom_package','deadline_forces_basic'] if args.mode=='real' else ['custom_package','deadline_forces_basic','blank_constraints','decimal_attack','one_cent_short','save_resume','expired_resume','free_tools']
    if args.case:cases=[args.case]
    report={'mode':args.mode,'cases':[],'passed':True}
    for name in cases:
        with tempfile.TemporaryDirectory() as temp:
            payload=scenario('reference');req,cat=payload['request'],payload['catalog'];req['request_id']=name;payload['mode']=args.mode
            now=datetime.now(timezone.utc);expected='completed';run_count=1
            if name=='custom_package':cat['packages']={'economy':cat['packages']['basic']}
            if name=='deadline_forces_basic':req.update(budget=20,deadline=(now+timedelta(minutes=23)).isoformat())
            if name=='blank_constraints':req.update(budget='  ',deadline='\t');expected='needs_information'
            if name=='decimal_attack':req['budget']='7.999999999999999999999999999999';expected='input_rejected'
            if name=='one_cent_short':req['budget']='7.99';expected='infeasible'
            if name in ('save_resume','expired_resume'):cat['failures']={'save_plan':1};run_count=2
            if name=='expired_resume':expected='infeasible'
            if name=='free_tools':
                req['budget']=0
                for package in cat['packages'].values():package['script_cost']=0
                for tool in cat['tools'].values():tool['cost']=0
            folder=Path(args.output)/name;dump(folder/'input.json',payload)
            results=[]
            for i in range(run_count):
                moment=now+timedelta(days=2) if name=='expired_resume' and i else now
                store=Store(Path(temp)/'state.db')
                agent=Agent(HTTPModel() if args.mode=='real' else MockModel(),store,cat,16,clock=None if args.mode=='real' else lambda:moment)
                try:r=agent.run(req)
                except ValueError:r={'status':'input_rejected','error':'invalid_input'}
                results.append(r);dump(folder/f'run-{i+1}.json',{'output':r,'trace':agent.trace,'stored_plan_count':len(store.saved()),'mode':args.mode})
            last=results[-1];checks={'expected_terminal':last['status']==expected}
            if expected=='completed':checks['actual_save']=last['save_status']=='saved'
            if name=='custom_package':checks['catalog_package']=last.get('package')=='economy'
            if name=='deadline_forces_basic':
                checks['faster_alternative']=last.get('package')=='basic'
                if args.mode=='real':
                    checks['observed_deadline_conflict']=any(t['action']['tool']=='estimate_cost' and t['observation'].get('deadline_gap_minutes',0)>0 for t in agent.trace)
            if name=='save_resume':checks['retained_script']=results[0]['steps']['generate_script:basic']==last['steps']['generate_script:basic'] and last['actual_cost']==8
            if name=='expired_resume':checks['no_charge_after_deadline']=last['actual_cost']==6 and last['save_status']=='not_saved'
            case={'name':name,'checks':checks,'passed':all(checks.values())};report['cases'].append(case);report['passed'] &= case['passed']
            dump(Path(args.output)/'report.json',report);print(name,last['status'],case['passed'],flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
