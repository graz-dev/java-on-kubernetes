"""
Locust load test for [Application Name]

This file defines the user behavior for load testing the application.
It simulates realistic user journeys through the application.

Usage:
  This file is automatically loaded by the loadgenerator deployment when
  the application is selected via:
    ./setup.sh --app [app-name]

For custom scenarios, edit the test-scenario ConfigMap to control:
  - n_users: Number of concurrent users
  - spawn_rate: Users spawned per second
  - duration: How long the phase lasts (seconds)
"""

from locust import HttpUser, task, between
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ApplicationUser(HttpUser):
    """
    Simulates a user interacting with the application.

    The wait_time defines how long users wait between tasks (simulates
    think time). Use between(min, max) for realistic user pacing.
    """
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests

    def on_start(self):
        """
        Called when a simulated user starts. Use this for login or
        initialization tasks that happen once per user session.
        """
        logger.info(f"User {self.user_id} started")
        # Example: self.login()

    @task(3)
    def browse_homepage(self):
        """
        Example task: Browse the homepage
        Weight = 3, meaning this task is 3x more likely than weight=1 tasks
        """
        with self.client.get("/", catch_response=True) as response:
            if response.status_code == 200:
                logger.debug("Homepage loaded successfully")
                response.success()
            else:
                logger.error(f"Homepage failed: {response.status_code}")
                response.failure(f"Got status {response.status_code}")

    @task(2)
    def api_call_example(self):
        """
        Example task: Call an API endpoint
        Weight = 2
        """
        with self.client.get("/api/resource", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"API call failed: {response.status_code}")

    @task(1)
    def post_example(self):
        """
        Example task: POST data to an endpoint
        Weight = 1 (least frequent)
        """
        payload = {"key": "value", "data": "example"}
        with self.client.post("/api/resource", json=payload, catch_response=True) as response:
            if response.status_code in [200, 201]:
                response.success()
            else:
                response.failure(f"POST failed: {response.status_code}")

    def on_stop(self):
        """
        Called when a simulated user stops. Use this for cleanup or logout.
        """
        logger.info(f"User {self.user_id} stopped")
        # Example: self.logout()


# Alternative user class for different behavior patterns
class HeavyUser(HttpUser):
    """
    Example of a second user type with different behavior.
    Locust can spawn multiple user types with different weights.
    """
    weight = 1  # HeavyUser spawned 10% as often as ApplicationUser (default weight=10)
    wait_time = between(0.5, 1.5)  # Faster pacing

    @task
    def intensive_operation(self):
        """Heavy users do more intensive operations"""
        self.client.get("/api/heavy-operation")


# To use multiple user types, run Locust with both classes defined.
# Locust will distribute users across classes based on their weights.
