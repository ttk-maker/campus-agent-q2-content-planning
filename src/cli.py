import argparse
import json
from pathlib import Path

from .agent import Agent
from .domain import validate_catalog,validate_request
from .models import HTTPModel,MockModel,ModelError
from .store import Store,StateError


def main():
    parser=argparse.ArgumentParser(description="Budget-aware content plan agent")
    parser.add_argument("--request",required=True)
    parser.add_argument("--catalog",default="data/catalog.json")
    parser.add_argument("--db",default="runtime/plans.db")
    parser.add_argument("--mode",choices=("mock","real"),default="mock")
    parser.add_argument("--max-steps",type=int,default=16)
    parser.add_argument("--output",default="runtime/output.json")
    parser.add_argument("--trace",default="runtime/trace.jsonl")
    args=parser.parse_args()
    try:
        request=json.loads(Path(args.request).read_text(encoding="utf-8"))
        catalog=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        validate_request(request);validate_catalog(catalog)
        agent=Agent(HTTPModel() if args.mode=="real" else MockModel(),Store(args.db),catalog,args.max_steps)
        result=agent.run(request)
        for filename,text in [(args.output,json.dumps(result,ensure_ascii=False,indent=2)+"\n"),
                              (args.trace,"".join(json.dumps(s,ensure_ascii=False)+"\n" for s in agent.trace))]:
            path=Path(filename);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result["status"]=="completed" else 2
    except (ValueError,KeyError,OSError,ModelError,StateError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,
                          "error":str(exc) if isinstance(exc,StateError) else "Check inputs, storage and model configuration."}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
