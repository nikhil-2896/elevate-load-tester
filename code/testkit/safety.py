"""Guards that stop the platform being turned into an attack tool.

* check_url      refuses addresses the server must never call (loopback,
                 private networks, cloud metadata) and odd schemes.
* Budget         hard caps on requests and wall-clock time per module.
* SafeClient     an HTTP client that applies both on every request and every
                 redirect hop.
* verify_ownership   proves the user controls the target before intrusive
                 modules (rate limiting, load) may run.

Known limit: the address is checked when we resolve the name, and the HTTP
library resolves it again when it connects. A hostile DNS server could answer
differently the second time ("DNS rebinding"). Closing that gap needs the
connection pinned to the checked address; it is listed as a refinement.
"""
import hmac
import ipaddress
import os
import secrets
import socket
import time
from urllib.parse import urljoin, urlparse

import requests

WELL_KNOWN_PATH = "/.well-known/testkit-verify"
_REDIRECT_CODES = (301, 302, 303, 307, 308)


class UnsafeTarget(ValueError):
    """The address or scheme may not be called."""


class BudgetExceeded(RuntimeError):
    """A module used up its request or time allowance."""


def _allow_private_default():
    return os.environ.get("TESTKIT_ALLOW_PRIVATE", "").strip().lower() == "true"


def _is_blocked(ip):
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (not ip.is_global) or ip.is_multicast


def check_url(url, allow_private=None, strict_dns=True, resolver=socket.getaddrinfo):
    """Returns the URL if it is safe to call; raises UnsafeTarget otherwise.

    allow_private: permit non-public addresses (local demos). Defaults to the
        TESTKIT_ALLOW_PRIVATE=true environment variable.
    strict_dns: when True a name that does not resolve is refused; when False
        it is let through (nothing internal can be reached through a name
        that resolves to nothing).
    """
    if allow_private is None:
        allow_private = _allow_private_default()
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        raise UnsafeTarget("malformed URL")
    if parsed.scheme not in ("http", "https") or not host:
        raise UnsafeTarget("only http(s) URLs with a host are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTarget("credentials in the URL are not allowed")

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = resolver(host, None)
        except OSError:
            if strict_dns:
                raise UnsafeTarget("host does not resolve")
            return url
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                raise UnsafeTarget("host resolved to an unreadable address")

    if not allow_private and any(_is_blocked(a) for a in addresses):
        raise UnsafeTarget("target is not a public address")
    return url


class Budget:
    """Caps the number of requests and the wall-clock time a module may use."""

    def __init__(self, max_requests, max_seconds, clock=time.monotonic):
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self._clock = clock
        self._start = clock()
        self.used = 0

    def spend(self):
        if self.used >= self.max_requests:
            raise BudgetExceeded(f"request budget of {self.max_requests} used up")
        if self._clock() - self._start > self.max_seconds:
            raise BudgetExceeded(f"time budget of {self.max_seconds}s used up")
        self.used += 1


class SafeClient:
    """HTTP client for test modules. Every request, and every redirect hop,
    is address-checked and charged to the budget."""

    def __init__(self, budget, allow_private=None, timeout=5.0, max_redirects=3,
                 session=None, resolver=socket.getaddrinfo):
        self.budget = budget
        self.allow_private = allow_private
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.session = session or requests.Session()
        self._resolver = resolver

    def request(self, method, url, **kwargs):
        for _ in range(self.max_redirects + 1):
            check_url(url, self.allow_private, strict_dns=True, resolver=self._resolver)
            self.budget.spend()
            resp = self.session.request(
                method, url, timeout=self.timeout, allow_redirects=False, **kwargs)
            location = resp.headers.get("Location")
            if resp.status_code in _REDIRECT_CODES and location:
                url = urljoin(url, location)
                if resp.status_code == 303 or (
                        resp.status_code in (301, 302) and method.upper() == "POST"):
                    method = "GET"
                    kwargs.pop("data", None)
                    kwargs.pop("json", None)
                continue
            return resp
        raise UnsafeTarget("too many redirects")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


def new_ownership_token():
    return "testkit-" + secrets.token_urlsafe(16)


def verify_ownership(base_url, token, client):
    """True if <base_url>/.well-known/testkit-verify serves exactly `token`.
    The user proves control by putting the token there."""
    if not token:
        return False
    try:
        resp = client.get(base_url.rstrip("/") + WELL_KNOWN_PATH)
    except (requests.exceptions.RequestException, UnsafeTarget, BudgetExceeded):
        return False
    return resp.status_code == 200 and hmac.compare_digest(
        resp.text.strip().encode(), token.encode())