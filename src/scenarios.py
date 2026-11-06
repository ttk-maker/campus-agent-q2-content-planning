from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"reference": "预算 10 · 超限后重规划", "normal": "正常完成 · 预算 20",
          "missing": "缺少预算与截止时间", "tool_failure": "高级脚本失败 · 保留检索",
          "over_budget": "预算 7 · 无可行方案", "deadline": "仅剩 3 分钟",
          "resume": "基础脚本失败一次 · 续跑", "save_failure": "保存失败一次 · 续跑"}


def scenario(name):
    if name not in LABELS: raise ValueError("unknown scenario")
    catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    request = {"request_id": name + "-" + uuid.uuid4().hex[:12], "topic": "秋季新品内容活动",
               "budget": 10, "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    if name in ("normal", "tool_failure"): request["budget"] = 20
    if name == "missing": request.update(budget=None, deadline=None)
    if name == "over_budget": request["budget"] = 7
    if name == "deadline": request["deadline"] = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
    if name == "tool_failure": catalog["failures"] = {"generate_script:premium": 1}
    if name == "resume": catalog["failures"] = {"generate_script:basic": 1}
    if name == "save_failure": catalog["failures"] = {"save_plan": 1}
    return {"request": request, "catalog": catalog, "mode": "mock", "max_steps": 16}
