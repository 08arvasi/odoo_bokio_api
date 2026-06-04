from __future__ import annotations

import time
import requests

from .customers import CustomersMixin
from .invoices import InvoicesMixin
from .exceptions import BokioAPIError


class BokioClient(CustomersMixin, InvoicesMixin):
    """
    Authenticated Bokio REST API client.

    Usage:
        client = BokioClient(token="...", company_id="...")
        customers = client.list_customers()
        invoices = client.list_invoices()
    """

    BASE = "https://api.bokio.se/v1"

    def __init__(self, token: str, company_id: str, rate_limit_ms: int = 500):
        self.token = token
        self.company_id = company_id
        self._rate_limit_s = rate_limit_ms / 1000
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _url(self, path: str) -> str:
        return f"{self.BASE}/companies/{self.company_id}/{path.lstrip('/')}"

    def _raise_for_status(self, resp: requests.Response) -> None:
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise BokioAPIError(resp.status_code, str(detail))

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._session.get(self._url(path), params=params)
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._session.post(self._url(path), json=payload)
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
        return resp.json()

    def _put(self, path: str, payload: dict) -> dict:
        resp = self._session.put(self._url(path), json=payload)
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = self._session.delete(self._url(path))
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
