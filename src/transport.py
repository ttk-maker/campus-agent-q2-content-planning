"""Real HTTP adapter and explicitly non-model offline flow simulator."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ModelError(Exception):
    pass


class HTTPTransport:
    mode = "real"

    def __init__(self, prompt):
        self.prompt = prompt
        self.key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base = os.environ.get("MODEL_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        self.name = os.environ.get("MODEL_NAME") or os.environ.get("OPENAI_MODEL")
        if not all((self.base, self.name)):
            raise ModelError("Set MODEL_BASE_URL and MODEL_NAME; remote services also need MODEL_API_KEY.")
        parsed = urllib.parse.urlsplit(self.base)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if not local and not self.key:
            raise ModelError("Remote services require MODEL_API_KEY.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("Base URL must not contain credentials, query or fragment.")
        if parsed.scheme != "https" and not (
                parsed.scheme == "http" and local):
            raise ModelError("Use HTTPS, or HTTP for a local model endpoint.")

    def decide(self, context):
        # Small local models have limited context. Full artifacts stay in SQLite/Trace;
        # the planner receives authoritative status/cost facts without duplicate scripts.
        state = dict(context["snapshot"])
        state["steps"] = {key: {"status": value["status"], "attempts": value["attempts"],
                               "error": value.get("error")}
                          for key, value in state["steps"].items()}
        if state["estimated_package"] is None:
            state["options"] = []  # Obtain a quote through the estimation tool first.
        history = []
        for step in context["history"][-2:]:
            observation = {key: value for key, value in step["observation"].items()
                           if key not in ("result", "alternatives")}
            history.append({"action": step["action"], "observation": observation})
        messages = [{"role": "system", "content": self.prompt},
                    {"role": "user", "content": json.dumps({"recent_observations": history, "CURRENT_STATE": state},
                                                            ensure_ascii=False, separators=(",", ":"))}]
        payload = json.dumps({"model": self.name, "messages": messages, "temperature": 0, "max_tokens": 256,
                              "response_format": getattr(self, "response_format", {"type": "json_object"})}).encode()
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.base.rstrip("/") + "/chat/completions",
                                         data=payload, method="POST", headers=headers)
        # Redirects are refused so Authorization cannot reach a different host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=90) as response:
                data = json.load(response)
            action = json.loads(data["choices"][0]["message"]["content"])
            if not isinstance(action, dict):
                raise ValueError("action must be an object")
            return action
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            # Never echo response bodies or headers that could contain credentials.
            raise ModelError("model_request_failed:" + type(exc).__name__) from None


