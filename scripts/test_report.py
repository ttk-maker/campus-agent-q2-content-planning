"""Capture executable test names, durations and genuine failures."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import unittest

class Result(unittest.TextTestResult):
    def startTest(self,test):
        super().startTest(test);self.started=time.monotonic()
    def stopTest(self,test):
        self.records.append({"test":test.id(),"seconds":round(time.monotonic()-self.started,3)})
        super().stopTest(test)
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records=[]

if __name__=="__main__":
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.discover("tests"))
    folder=Path("examples/tests");folder.mkdir(parents=True,exist_ok=True)
    (folder/"unittest.txt").write_text(stream.getvalue(),encoding="utf-8")
    (folder/"report.json").write_text(json.dumps({"timestamp":datetime.now(timezone.utc).isoformat(),"count":result.testsRun,"passed":result.wasSuccessful(),"failures":[[str(t),e] for t,e in result.failures+result.errors],"tests":result.records},indent=2),encoding="utf-8")
    print(stream.getvalue());raise SystemExit(0 if result.wasSuccessful() else 1)
