from __future__ import annotations
import time


class InvoicesMixin:

    def list_invoices(self, page_size: int = 100) -> list[dict]:
        results: list[dict] = []
        page = 1
        while True:
            data = self._get("invoices", params={"pageSize": page_size, "page": page})
            results.extend(data.get("items", []))
            if page >= data.get("totalPages", 1):
                break
            page += 1
        return results

    def download_invoice_pdf(self, invoice_id: str) -> bytes:
        resp = self._session.get(self._url(f"invoices/{invoice_id}/download"))
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
        return resp.content
