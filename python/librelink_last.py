#!/usr/bin/env python3
"""
Unofficial LibreLinkUp (LLU) client using requests.

Includes fixes you hit:
- Region redirect on login (data.redirect + data.region -> api-eu.libreview.io)
- Minimum version enforcement (HTTP 403 + status 920 -> bump to data.minimumVersion and retry)
- Required header: account-id = sha256(login.data.user.id)
- Token extraction from multiple known locations
- Option 1: GET /llu/connections/{patientId}/graph and return the last reading from
  data.connection.glucoseMeasurement

Env vars:
  export LIBRELINK_EMAIL="you@example.com"
  export LIBRELINK_PASSWORD="your-password"

Run:
  python librelink_last.py
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

DEFAULT_BASE = "https://api.libreview.io"


@dataclass
class LibreLinkUpSession:
    base_url: str
    token: str
    account_id_hash: Optional[str]
    version: str


class LibreLinkUpClient:
    def __init__(
        self,
        email: str,
        password: str,
        base_url: str = DEFAULT_BASE,
        product: str = "llu.android",
        version: str = "4.16.0",
        timeout_s: int = 20,
    ) -> None:
        self.email = email
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.product = product
        self.version = version
        self.timeout_s = timeout_s

        self._http = requests.Session()
        self._token: Optional[str] = None
        self._account_id_hash: Optional[str] = None

    # ---------------- HTTP helpers ----------------

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {
            "accept-encoding": "gzip",
            "cache-control": "no-cache",
            "connection": "Keep-Alive",
            "content-type": "application/json",
            "product": self.product,
            "version": self.version,
        }
        if self._token:
            h["authorization"] = f"Bearer {self._token}"
        if self._account_id_hash:
            h["account-id"] = self._account_id_hash
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, *, json_body: Any | None = None) -> Dict[str, Any]:
        resp = self._http.request(
            method=method,
            url=self._url(path),
            headers=self._headers(),
            json=json_body,
            timeout=self.timeout_s,
        )
        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError(
                f"Non-JSON response ({resp.status_code}) {method} {path}: {resp.text[:500]}"
            )
        payload["_http_status"] = resp.status_code
        return payload

    # ---------------- Parsing helpers ----------------

    @staticmethod
    def _data_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
        d = payload.get("data")
        return d if isinstance(d, dict) else {}

    @staticmethod
    def _is_redirect(payload: Dict[str, Any]) -> bool:
        # observed: {"status":0,"data":{"redirect":true,"region":"eu"}}
        d = payload.get("data")
        return isinstance(d, dict) and d.get("redirect") is True

    @staticmethod
    def _region(payload: Dict[str, Any]) -> Optional[str]:
        d = LibreLinkUpClient._data_dict(payload)
        r = d.get("region") or payload.get("region")
        return str(r) if isinstance(r, str) else None

    @staticmethod
    def _minimum_version(payload: Dict[str, Any]) -> Optional[str]:
        # observed: HTTP 403 + {"status":920, "data":{"minimumVersion":"4.16.0"}}
        if payload.get("_http_status") == 403 and payload.get("status") == 920:
            d = LibreLinkUpClient._data_dict(payload)
            mv = d.get("minimumVersion")
            return str(mv) if isinstance(mv, str) else None
        return None

    @staticmethod
    def _extract_token(payload: Dict[str, Any]) -> Optional[str]:
        # token locations seen across responses:
        # - data.authTicket.token (login)
        # - ticket.token         (some endpoints)
        d = payload.get("data")
        if isinstance(d, dict):
            auth = d.get("authTicket")
            if isinstance(auth, dict) and auth.get("token"):
                return str(auth["token"])
            if d.get("token"):
                return str(d["token"])

        t = payload.get("ticket")
        if isinstance(t, dict) and t.get("token"):
            return str(t["token"])

        if payload.get("token"):
            return str(payload["token"])

        return None

    @staticmethod
    def _user_id_from_login(payload: Dict[str, Any]) -> Optional[str]:
        d = LibreLinkUpClient._data_dict(payload)
        user = d.get("user")
        if isinstance(user, dict) and user.get("id"):
            return str(user["id"])
        return None

    # ---------------- Core: auth + retries ----------------

    def login(self) -> LibreLinkUpSession:
        body = {"email": self.email, "password": self.password}

        payload = self._request("POST", "/llu/auth/login", json_body=body)

        # Redirect handling: switch base URL and retry
        if self._is_redirect(payload):
            region = self._region(payload)
            if not region:
                raise RuntimeError(f"Redirected but no region in payload: {payload}")
            self.base_url = f"https://api-{region.lower()}.libreview.io"
            payload = self._request("POST", "/llu/auth/login", json_body=body)

        http_status = payload.get("_http_status", 200)
        if http_status >= 400:
            raise RuntimeError(f"Login failed ({http_status}): {payload}")

        token = self._extract_token(payload)
        user_id = self._user_id_from_login(payload)

        if not token:
            raise RuntimeError(f"Login response missing token: {payload}")

        self._token = token

        # account-id required for data endpoints (if user.id is present)
        if user_id:
            self._account_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

        return LibreLinkUpSession(
            base_url=self.base_url,
            token=token,
            account_id_hash=self._account_id_hash,
            version=self.version,
        )

    def _call_with_min_version_retry(self, method: str, path: str, *, json_body: Any | None = None) -> Dict[str, Any]:
        payload = self._request(method, path, json_body=json_body)

        mv = self._minimum_version(payload)
        if mv:
            self.version = mv
            payload = self._request(method, path, json_body=json_body)

        # Some endpoints rotate a "ticket.token" – keep the newest token if provided
        new_token = self._extract_token(payload)
        if new_token:
            self._token = new_token

        return payload

    # ---------------- Public: connections + graph + last reading ----------------

    def connections(self) -> Dict[str, Any]:
        if not self._token:
            self.login()

        payload = self._call_with_min_version_retry("GET", "/llu/connections")
        status = payload.get("_http_status", 200)
        if status >= 400:
            raise RuntimeError(f"Connections failed ({status}): {payload}")
        return payload

    def first_patient_id(self) -> Optional[str]:
        payload = self.connections()
        conns = payload.get("data")

        # Your observed case: data=[]
        if isinstance(conns, list) and len(conns) == 0:
            return None

        if not isinstance(conns, list) or not conns:
            raise RuntimeError(f"Unexpected connections payload: {payload}")

        pid = conns[0].get("patientId") or conns[0].get("patient_id")
        return str(pid) if pid else None

    def graph(self, patient_id: str) -> Dict[str, Any]:
        if not self._token:
            self.login()

        payload = self._call_with_min_version_retry("GET", f"/llu/connections/{patient_id}/graph")
        status = payload.get("_http_status", 200)
        if status >= 400:
            raise RuntimeError(f"Graph failed ({status}): {payload}")
        return payload

    def last_reading(self) -> Dict[str, Any]:
        """
        Option 1:
        - Get first patientId from /llu/connections
        - Call /llu/connections/{patientId}/graph
        - Return data.connection.glucoseMeasurement (latest reading)
        """
        pid = self.first_patient_id()
        if not pid:
            raise RuntimeError(
                "No connections found (connections.data = []).\n"
                "You must share data from the LibreLink app to this LibreLinkUp account, "
                "then accept the invite in LibreLinkUp. After that, connections will contain patientId."
            )

        g = self.graph(pid)

        data = g.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected graph payload shape (data not dict): {g}")

        conn = data.get("connection") or {}
        if not isinstance(conn, dict):
            raise RuntimeError(f"Unexpected graph payload shape (connection not dict): {g}")

        latest = conn.get("glucoseMeasurement")
        if not latest:
            # Fallback: return whole graph so you can inspect keys
            raise RuntimeError(
                "Couldn't find data.connection.glucoseMeasurement in graph response.\n"
                f"Available keys under data.connection: {list(conn.keys())}"
            )

        return latest


def main() -> None:
    email = os.environ.get("LIBRELINK_EMAIL", "")
    password = os.environ.get("LIBRELINK_PASSWORD", "")
    if not email or not password:
        raise SystemExit("Set env vars LIBRELINK_EMAIL and LIBRELINK_PASSWORD")

    c = LibreLinkUpClient(email, password)

    sess = c.login()
    print(f"Logged in. Base URL: {sess.base_url}")
    print(f"Using version header: {c.version}")

    latest = c.last_reading()
    print("Latest reading (raw):", latest)

    # If the fields exist, print a friendly summary:
    val = latest.get("Value") or latest.get("value")
    ts = latest.get("Timestamp") or latest.get("timestamp")
    trend = latest.get("TrendArrow") or latest.get("trendArrow")
    if val is not None:
        print(f"Latest: value={val} trend={trend} time={ts}")


if __name__ == "__main__":
    main()

