from __future__ import annotations
import time


class InvoicesMixin:

    def list_invoices(self, page_size: int = 100) -> list[dict]:
        """Fetch all invoices. Each item includes lineItems and creditNoteRefs."""
        results: list[dict] = []
        page = 1
        while True:
            data = self._get("invoices", params={"pageSize": page_size, "page": page})
            results.extend(data.get("items", []))
            if page >= data.get("totalPages", 1):
                break
            page += 1
        return results

    def get_invoice(self, invoice_id: str) -> dict:
        """Fetch a single invoice by Bokio UUID (full detail)."""
        return self._get(f"invoices/{invoice_id}")

    def download_invoice_pdf(self, invoice_id: str) -> bytes:
        """Download invoice PDF as raw bytes."""
        resp = self._session.get(self._url(f"invoices/{invoice_id}/download"))
        self._raise_for_status(resp)
        time.sleep(self._rate_limit_s)
        return resp.content
