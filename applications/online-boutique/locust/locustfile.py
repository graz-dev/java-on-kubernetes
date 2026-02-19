"""
Locust load test for Online Boutique (Google microservices-demo)

Simulates realistic e-commerce user behavior:
- Browse homepage and product catalog
- View individual product pages
- Add products to shopping cart
- Complete checkout process

This generates load across all microservices, with particular focus
on adservice (the JVM service being benchmarked).
"""

from locust import HttpUser, task, between
from random import randint, choice
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Product IDs from the Online Boutique catalog
PRODUCT_IDS = [
    "OLJCESPC7Z",  # Vintage Typewriter
    "66VCHSJNUP",  # Vintage Camera Lens
    "1YMWWN1N4O",  # Home Barista Kit
    "L9ECAV7KIM",  # Terrarium
    "2ZYFJ3GM2N",  # Film Camera
    "0PUK6V6EV0",  # Vintage Record Player
    "LS4PSXUNUM",  # Metal Camping Mug
    "9SIQT8TOJO",  # City Bike
    "6E92ZMYYFZ",  # Air Plant
]

# Currencies supported by the currency service
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD"]


class OnlineBoutiqueUser(HttpUser):
    """
    Simulates a user shopping on Online Boutique.

    Weight distribution of tasks models realistic e-commerce behavior:
    - Most users browse (high weight)
    - Fewer users add to cart (medium weight)
    - Even fewer complete checkout (low weight)
    """
    wait_time = between(1, 4)  # 1-4 seconds between requests (think time)

    def on_start(self):
        """Initialize user session by loading the homepage"""
        self.currency = choice(CURRENCIES)
        logger.info(f"User started shopping in {self.currency}")
        self.load_homepage()

    @task(10)
    def load_homepage(self):
        """
        Browse the homepage (high weight = most common action).
        Triggers: frontend, productcatalog, currency, recommendation, ad services
        """
        with self.client.get("/", catch_response=True, name="Homepage") as response:
            if response.status_code == 200 and "Online Boutique" in response.text:
                response.success()
            else:
                logger.error(f"Homepage failed: {response.status_code}")
                response.failure(f"Homepage returned {response.status_code}")

    @task(8)
    def view_product(self):
        """
        View a random product detail page.
        Triggers: frontend, productcatalog, currency, recommendation, ad services
        """
        product_id = choice(PRODUCT_IDS)
        with self.client.get(f"/product/{product_id}", catch_response=True, name="Product Page") as response:
            if response.status_code == 200 and product_id in response.text:
                response.success()
            else:
                logger.error(f"Product page {product_id} failed: {response.status_code}")
                response.failure(f"Product page returned {response.status_code}")

    @task(5)
    def add_to_cart(self):
        """
        Add a product to the shopping cart.
        Triggers: frontend, cartservice (C#), productcatalog, currency, recommendation
        """
        product_id = choice(PRODUCT_IDS)
        quantity = randint(1, 3)

        with self.client.post(
            "/cart",
            data={
                "product_id": product_id,
                "quantity": quantity
            },
            catch_response=True,
            name="Add to Cart"
        ) as response:
            if response.status_code == 200:
                logger.debug(f"Added {quantity}x {product_id} to cart")
                response.success()
            else:
                logger.error(f"Add to cart failed: {response.status_code}")
                response.failure(f"Add to cart returned {response.status_code}")

    @task(3)
    def view_cart(self):
        """
        View the shopping cart.
        Triggers: frontend, cartservice, productcatalog, currency, recommendation
        """
        with self.client.get("/cart", catch_response=True, name="View Cart") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"View cart returned {response.status_code}")

    @task(1)
    def checkout(self):
        """
        Complete the checkout process (least frequent action).
        Triggers: frontend, checkoutservice (orchestrator), cartservice,
                  payment, shipping, email, currency, productcatalog

        This is the most complex flow and exercises nearly all services.
        """
        # Step 1: Add at least one item to cart
        product_id = choice(PRODUCT_IDS)
        self.client.post("/cart", data={"product_id": product_id, "quantity": 1})

        # Step 2: Complete checkout
        checkout_data = {
            "email": f"test-{randint(1, 9999)}@example.com",
            "street_address": f"{randint(1, 999)} Main St",
            "zip_code": f"{randint(10000, 99999)}",
            "city": choice(["New York", "San Francisco", "Seattle", "Austin", "Boston"]),
            "state": choice(["NY", "CA", "WA", "TX", "MA"]),
            "country": "United States",
            "credit_card_number": "4432-8015-6152-0454",  # Test card number
            "credit_card_expiration_month": str(randint(1, 12)),
            "credit_card_expiration_year": str(randint(2024, 2030)),
            "credit_card_cvv": str(randint(100, 999)),
        }

        with self.client.post(
            "/cart/checkout",
            data=checkout_data,
            catch_response=True,
            name="Checkout"
        ) as response:
            if response.status_code == 200 and "Your order is complete" in response.text:
                logger.info(f"Checkout completed successfully")
                response.success()
            else:
                logger.error(f"Checkout failed: {response.status_code}")
                response.failure(f"Checkout returned {response.status_code}")

    @task(2)
    def set_currency(self):
        """
        Change the display currency (optional task).
        Triggers: frontend, currencyservice
        """
        new_currency = choice(CURRENCIES)
        with self.client.post(
            "/setCurrency",
            data={"currency_code": new_currency},
            catch_response=True,
            name="Set Currency"
        ) as response:
            if response.status_code == 200:
                self.currency = new_currency
                response.success()
            else:
                response.failure(f"Set currency returned {response.status_code}")


# Task weights summary:
# - load_homepage: 10 (most frequent)
# - view_product: 8
# - add_to_cart: 5
# - view_cart: 3
# - set_currency: 2
# - checkout: 1 (least frequent, most complex)
#
# This distribution models realistic e-commerce behavior where most users
# browse but few complete purchases (conversion funnel).
