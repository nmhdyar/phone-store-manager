import tempfile
import unittest
from pathlib import Path

import database
import app as webapp


class PhoneStoreAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temp_dir.name) / "test_phone_store.db"
        webapp.initialize_database()
        webapp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = webapp.app.test_client()

    def tearDown(self):
        database.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    def add_product(self, name="Pixel", price=120, cost=80, quantity=10, cost_known=1):
        with database.get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO phones(name, price, cost_price, cost_known, quantity)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, price, cost, cost_known, quantity),
            )
            return cursor.lastrowid

    def get_product(self, product_id):
        with database.get_connection() as connection:
            return connection.execute(
                "SELECT * FROM phones WHERE id=?", (product_id,)
            ).fetchone()

    def test_dashboard_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_all_pages_render(self):
        product_id = self.add_product()
        for path in ("/", "/add", "/sales", "/activity", "/settings",
                     f"/edit/{product_id}", f"/sell/{product_id}",
                     f"/restock/{product_id}", f"/delete/{product_id}"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_sale_updates_stock_and_snapshots_profit(self):
        product_id = self.add_product()
        response = self.client.post(
            f"/sell/{product_id}",
            data={"quantity": "2", "unit_price": "100"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.get_product(product_id)["quantity"], 8)
        with database.get_connection() as connection:
            sale = connection.execute("SELECT * FROM sales").fetchone()
        self.assertEqual(sale["total"], 200)
        self.assertEqual(sale["profit"], 40)
        self.assertEqual(sale["unit_cost"], 80)

    def test_overselling_is_rejected_without_mutation(self):
        product_id = self.add_product(quantity=10)
        response = self.client.post(
            f"/sell/{product_id}",
            data={"quantity": "11", "unit_price": "100"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get_product(product_id)["quantity"], 10)
        with database.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)

    def test_unknown_cost_keeps_profit_unknown(self):
        product_id = self.add_product(cost=0, cost_known=0)
        self.client.post(
            f"/sell/{product_id}",
            data={"quantity": "1", "unit_price": "100"},
        )
        with database.get_connection() as connection:
            sale = connection.execute("SELECT profit FROM sales").fetchone()
        self.assertIsNone(sale["profit"])

    def test_blank_edit_cost_preserves_existing_cost(self):
        product_id = self.add_product()
        self.client.post(
            f"/edit/{product_id}",
            data={"name": "Pixel Pro", "price": "130", "cost_price": "",
                  "quantity": "10"},
        )
        product = self.get_product(product_id)
        self.assertEqual(product["name"], "Pixel Pro")
        self.assertEqual(product["cost_known"], 1)
        self.assertEqual(product["cost_price"], 80)

    def test_restock_and_overflow_protection(self):
        product_id = self.add_product(quantity=10)
        self.client.post(f"/restock/{product_id}", data={"quantity": "5"})
        self.assertEqual(self.get_product(product_id)["quantity"], 15)

        with database.get_connection() as connection:
            connection.execute(
                "UPDATE phones SET quantity=? WHERE id=?",
                (webapp.MAX_QUANTITY, product_id),
            )
        response = self.client.post(f"/restock/{product_id}", data={"quantity": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get_product(product_id)["quantity"], webapp.MAX_QUANTITY)

    def test_invalid_money_is_rejected(self):
        with database.get_connection() as connection:
            initial_count = connection.execute("SELECT COUNT(*) FROM phones").fetchone()[0]
        response = self.client.post(
            "/add",
            data={"name": "Invalid", "price": "NaN", "quantity": "1"},
        )
        self.assertEqual(response.status_code, 200)
        with database.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM phones").fetchone()[0], initial_count)

    def test_delete_requires_post(self):
        product_id = self.add_product()
        self.assertEqual(self.client.get(f"/delete/{product_id}").status_code, 200)
        self.assertIsNotNone(self.get_product(product_id))
        self.client.post(f"/delete/{product_id}")
        self.assertIsNone(self.get_product(product_id))

    def test_csrf_protection_rejects_missing_token(self):
        webapp.app.config["WTF_CSRF_ENABLED"] = True
        response = self.client.post(
            "/add", data={"name": "No token", "price": "100", "quantity": "1"}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
