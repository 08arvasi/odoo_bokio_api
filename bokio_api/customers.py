from __future__ import annotations


class CustomersMixin:
    """Bokio customer CRUD — mixed into BokioClient."""

    def list_customers(self) -> list[dict]:
        """Fetch all customers (1-indexed pagination, 25 per page)."""
        customers: list[dict] = []
        page = 1
        while True:
            resp = self._get("customers", params={"page": page})
            items = resp.get("items", [])
            customers.extend(items)
            total_pages = resp.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
        return customers

    def create_customer(self, payload: dict) -> dict:
        """Create a new customer. Returns the created customer object."""
        return self._post("customers", payload)

    def get_customer(self, customer_id: str) -> dict:
        """Fetch a single customer by Bokio UUID."""
        return self._get(f"customers/{customer_id}")

    def update_customer(self, customer_id: str, payload: dict) -> dict:
        """Update an existing customer by Bokio ID."""
        return self._put(f"customers/{customer_id}", payload)

    @staticmethod
    def build_payload(
        name: str,
        is_company: bool,
        *,
        org_number: str | None = None,
        vat: str | None = None,
        street: str | None = None,
        street2: str | None = None,
        zip_code: str | None = None,
        city: str | None = None,
        country: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        language: str = "sv",
    ) -> dict:
        """Build a Bokio customer payload from normalised Odoo fields."""
        payload: dict = {
            "name": name,
            "type": "company" if is_company else "private",
            "language": language,
        }
        if is_company:
            payload["companyname"] = name
        if org_number:
            payload["orgNumber"] = org_number
        if vat and is_company:
            payload["vatNumber"] = vat
        if street:
            payload["line1"] = street
        if street2:
            payload["line2"] = street2
        if zip_code:
            payload["postalCode"] = zip_code
        if city:
            payload["city"] = city
        if country:
            payload["country"] = country

        contact: dict = {"name": name, "isDefault": True}
        if email:
            contact["email"] = email
        if phone:
            contact["phone"] = phone
        if email or phone:
            payload["contactsDetails"] = [contact]

        return payload
