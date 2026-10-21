"""Sends one probe request and records what came back."""
import time
from dataclasses import dataclass

import requests


@dataclass
class Probe:
    label: str
    method: str
    path: str
    status: int = None      # None when there was no HTTP response at all
    elapsed: float = 0.0
    body: str = ""
    content_type: str = ""
    error: str = ""         # exception class name when there was no response

    @property
    def is_error_response(self):
        return self.status is not None and self.status >= 400


class Prober:
    """Wraps a SafeClient. UnsafeTarget and BudgetExceeded are deliberately
    not caught here: they end the whole module."""

    def __init__(self, client, base_url, token=""):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.log = []

    def send(self, label, method, path, auth="default", headers=None, **kwargs):
        """auth: "default" sends the target's token (if any), "none" sends no
        Authorization header, any other string is sent as the bearer token."""
        hdrs = dict(headers or {})
        if auth == "default":
            if self.token:
                hdrs["Authorization"] = f"Bearer {self.token}"
        elif auth != "none":
            hdrs["Authorization"] = f"Bearer {auth}"

        probe = Probe(label=label, method=method, path=path)
        started = time.monotonic()
        try:
            resp = self.client.request(method, self.base_url + path, headers=hdrs, **kwargs)
            probe.status = resp.status_code
            probe.body = resp.text[:4000]
            probe.content_type = resp.headers.get("Content-Type", "")
        except requests.exceptions.RequestException as e:
            probe.error = type(e).__name__
        probe.elapsed = time.monotonic() - started
        self.log.append(probe)
        return probe