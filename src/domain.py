from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def instant(value):
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("deadline must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("invalid timestamp or missing timezone") from None


def cents(value):
    if isinstance(value, bool) or len(str(value)) > 80:
        raise ValueError("budget must be a number")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 100000 or amount != amount.quantize(Decimal('0.01')):
            raise ValueError("amount must be nonnegative with at most two decimals")
        return int(amount * 100)
    except InvalidOperation:
        raise ValueError("invalid amount") from None


def is_missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def validate_request(request):
    if not isinstance(request, dict) or set(request) - {"request_id","topic","budget","deadline"}:
        raise ValueError("unexpected request fields")
    if not isinstance(request.get("request_id"), str) or not 1 <= len(request["request_id"].strip()) <= 128:
        raise ValueError("request_id must be 1..128 characters")
    if not isinstance(request.get("topic"), str) or not 1 <= len(request["topic"].strip()) <= 1000:
        raise ValueError("topic is required (1..1000 characters)")
    missing = [key for key in ("budget", "deadline") if is_missing(request.get(key))]
    if "budget" not in missing:
        cents(request["budget"])
    if "deadline" not in missing:
        instant(request["deadline"])
    return missing


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or not {"version","materials","packages","tools","failure_minutes","failures"} <= set(catalog):
        raise ValueError("incomplete catalog")
    if not isinstance(catalog["version"], str) or not 1 <= len(catalog["version"]) <= 100:
        raise ValueError("invalid catalog version")
    if not isinstance(catalog["materials"], list) or len(catalog["materials"]) > 100:
        raise ValueError("materials must be a list of at most 100")
    seen=set()
    for material in catalog["materials"]:
        if not isinstance(material,dict) or set(material)!={"id","title","summary"}:
            raise ValueError("invalid material")
        if any(not isinstance(v,str) or not v.strip() or len(v)>3000 for v in material.values()):
            raise ValueError("invalid material text")
        if material["id"] in seen: raise ValueError("duplicate material ID")
        seen.add(material["id"])
    packages=catalog["packages"]
    if not isinstance(packages,dict) or not 1 <= len(packages) <= 5:
        raise ValueError("1..5 packages required")
    if not isinstance(catalog["tools"],dict) or set(catalog["tools"])!={"search_materials","estimate_cost","save_plan"}:
        raise ValueError("invalid tool cost table")
    for name, package in packages.items():
        if not isinstance(name,str) or not 1<=len(name)<=40 or not isinstance(package,dict):
            raise ValueError("invalid package")
        if not {"script_cost","script_minutes"} <= set(package):raise ValueError("incomplete package price table")
        cents(package["script_cost"])
        if type(package["script_minutes"]) is not int or not 1<=package["script_minutes"]<=1440:
            raise ValueError("invalid script duration")
    for tool in catalog["tools"].values():
        if not isinstance(tool,dict) or not {"cost","minutes"} <= set(tool):raise ValueError("incomplete tool price table")
        cents(tool["cost"])
        if type(tool["minutes"]) is not int or not 0<=tool["minutes"]<=1440:
            raise ValueError("invalid tool duration")
    if cents(catalog["tools"]["estimate_cost"]["cost"]) != 0:
        raise ValueError("estimation must be free in this implementation")
    if type(catalog["failure_minutes"]) is not int or not 1<=catalog["failure_minutes"]<=1440:
        raise ValueError("invalid failure duration")
    failures=catalog["failures"]
    allowed={"search_materials","save_plan"}|{"generate_script:"+p for p in packages}
    if not isinstance(failures,dict) or set(failures)-allowed:
        raise ValueError("unknown failure tool")
    if any(type(n) is not int or not 0<=n<=10 for n in failures.values()):
        raise ValueError("failure counts must be integers 0..10")
    return catalog


def fingerprint(request, catalog):
    normalized=dict(request)
    if not is_missing(request.get("budget")): normalized["budget"]=cents(request["budget"])
    if not is_missing(request.get("deadline")): normalized["deadline"]=instant(request["deadline"]).isoformat()
    return digest([normalized,catalog])
