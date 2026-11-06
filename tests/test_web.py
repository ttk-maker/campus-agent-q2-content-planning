from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from src.models import MockModel
from src.scenarios import scenario
from src.web import Application, make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Application(Path(self.temp.name)/"web.db")
        self.server=make_server(self.app,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def call(self,path,body=None,headers=None):
        h={"Content-Type":"application/json","X-CSRF-Token":self.app.token}
        h.update(headers or {})
        data=None if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
        req=urllib.request.Request(self.base+path,data=data,headers=h)
        try:
            with urllib.request.urlopen(req,timeout=3) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()

    def job(self,payload):
        status,raw=self.call("/api/jobs",payload);self.assertEqual(status,202)
        job_id=json.loads(raw)["job_id"]
        for _ in range(200):
            status,raw=self.call("/api/jobs/"+job_id);job=json.loads(raw)
            if job["state"]!="running":return job
            time.sleep(.01)
        self.fail("job did not finish")

    def test_pages_and_health(self):
        for path in ("/","/app.js","/style.css","/manual.html","/api/health","/api/bootstrap"):
            self.assertEqual(self.call(path)[0],200,path)

    def test_api_prefix_is_not_web_page(self):
        status,body=self.call("/v1");self.assertEqual(status,404)
        self.assertIn("127.0.0.1",body.decode())

    def test_actual_job_and_repeat(self):
        p=scenario("reference");first=self.job(p);last=self.job(p)
        self.assertEqual(first["result"]["actual_cost"],8)
        self.assertEqual(last["result"]["steps_used"],0)
        self.assertEqual(first["result"]["plan_id"],last["result"]["plan_id"])
        self.assertEqual(len(json.loads(self.call("/api/plans")[1])["plans"]),1)

    def test_resume_failure_uses_same_inputs(self):
        p=scenario("resume");first=self.job(p);last=self.job(p)
        self.assertEqual(first["result"]["status"],"failed")
        self.assertEqual(last["result"]["status"],"completed")
        self.assertEqual(last["result"]["steps"]["search_materials"]["attempts"],1)

    def test_changed_input_conflict_is_visible(self):
        p=scenario("reference");self.job(p);p["request"]["budget"]=20
        j=self.job(p);self.assertEqual(j["state"],"error")
        self.assertIn("idempotency_conflict",j["error"])

    def test_csrf_and_origin_guards(self):
        p=scenario("normal")
        self.assertEqual(self.call("/api/jobs",p,{"X-CSRF-Token":"wrong"})[0],403)
        self.assertEqual(self.call("/api/jobs",p,{"Origin":"https://example.com"})[0],403)

    def test_invalid_json_unknown_fields_nonfinite(self):
        for p in (b"{",b'{"x":NaN}',{"request":{}},dict(scenario("normal"),publish=True)):
            self.assertEqual(self.call("/api/jobs",p)[0],400)

    def test_malformed_catalog_is_bad_request(self):
        p=scenario("normal");p["catalog"]["tools"]=None
        self.assertEqual(self.call("/api/jobs",p)[0],400)

    def test_missing_inputs_not_completed(self):
        j=self.job(scenario("missing"))
        self.assertEqual(j["result"]["status"],"needs_information")
        self.assertEqual(j["result"]["steps_used"],0)

    def test_concurrent_job_returns_conflict(self):
        release=threading.Event();entered=threading.Event()
        class Slow(MockModel):
            def decide(self,context):entered.set();release.wait(3);return super().decide(context)
        self.app.model_factory=lambda mode:Slow()
        try:
            self.assertEqual(self.call("/api/jobs",scenario("normal"))[0],202)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.call("/api/jobs",scenario("reference"))[0],409)
        finally:
            release.set()
            for _ in range(200):
                if self.app.active is None:break
                time.sleep(.01)

    def test_restart_retains_business_state(self):
        p=scenario("reference");first=self.job(p)
        second=Application(self.app.store.path)
        job_id=second.start(p)["job_id"]
        for _ in range(200):
            j=second.job(job_id)
            if j["state"]!="running":break
            time.sleep(.01)
        self.assertEqual(j["result"]["plan_id"],first["result"]["plan_id"])
        self.assertEqual(j["result"]["steps_used"],0)

    def test_host_guard_and_path_traversal(self):
        self.assertEqual(self.call("/api/bootstrap",headers={"Host":"evil.example"})[0],403)
        self.assertEqual(self.call("/../src/store.py")[0],404)
