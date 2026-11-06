"""Create a fresh, future-dated request for reproducible CLI execution."""
import argparse
from pathlib import Path
from scripts.evaluate import dump
from src.scenarios import LABELS, scenario

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--scenario",choices=list(LABELS),default="reference")
    parser.add_argument("--directory",default="runtime/request")
    args=parser.parse_args();payload=scenario(args.scenario);folder=Path(args.directory)
    dump(folder/"input.json",payload["request"]);dump(folder/"catalog.json",payload["catalog"])
    print(f"Created {folder}/input.json and catalog.json; deadline is relative to now.")
