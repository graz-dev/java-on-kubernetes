"""
Spring PetClinic Microservices Load Test

Simulates realistic user behavior for a veterinary clinic application:
- Browse owners and their pets
- View owner details
- Schedule vet visits
- Browse veterinarians

Weighted by frequency:
- 60% browse owners (read-heavy)
- 20% view owner details (moderate reads with pet data)
- 15% schedule visits (write operations)
- 5% browse vets (lightweight reads)
"""

import os
import random
from locust import HttpUser, task, between, events
from datetime import datetime, timedelta


class PetClinicUser(HttpUser):
    """
    Simulates a user of the PetClinic application.

    All requests go through the API Gateway, which routes to backend services:
    - /api/customer/* → customers-service
    - /api/visit/* → visits-service
    - /api/vet/* → vets-service
    """

    wait_time = between(1, 3)  # Wait 1-3 seconds between requests

    # Base URL from environment (set by Kubernetes ConfigMap)
    host = os.getenv("FRONTEND_URL", "http://api-gateway:8080")

    # Track known owner and pet IDs for realistic access patterns
    owner_ids = []
    pet_ids = []
    vet_ids = []

    def on_start(self):
        """
        Called when a simulated user starts.
        Initialize by fetching some initial data to warm up the services.
        """
        # Warm up: fetch initial data
        self.fetch_owners()
        self.fetch_vets()

    def fetch_owners(self):
        """Helper to fetch and cache owner IDs."""
        with self.client.get(
            "/api/customer/owners",
            catch_response=True,
            name="/api/customer/owners [fetch]"
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data and len(data) > 0:
                        # Cache owner IDs for future requests
                        self.owner_ids = [owner["id"] for owner in data if "id" in owner]
                        # Extract pet IDs from owners' pets
                        for owner in data:
                            if "pets" in owner and owner["pets"]:
                                self.pet_ids.extend([pet["id"] for pet in owner["pets"] if "id" in pet])
                    response.success()
                except Exception as e:
                    response.failure(f"Failed to parse owners: {e}")
            else:
                response.failure(f"Got status {response.status_code}")

    def fetch_vets(self):
        """Helper to fetch and cache vet IDs."""
        with self.client.get(
            "/api/vet/vets",
            catch_response=True,
            name="/api/vet/vets [fetch]"
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data and len(data) > 0:
                        self.vet_ids = [vet["id"] for vet in data if "id" in vet]
                    response.success()
                except Exception as e:
                    response.failure(f"Failed to parse vets: {e}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(60)
    def browse_owners(self):
        """
        Browse all owners (60% of traffic).

        READ-HEAVY workload targeting customers-service.
        Tests: Spring Data JPA query performance, serialization, response caching.
        """
        with self.client.get(
            "/api/customer/owners",
            catch_response=True,
            name="/api/customer/owners"
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Update cached owner and pet IDs
                    if data and len(data) > 0:
                        self.owner_ids = [owner["id"] for owner in data if "id" in owner]
                        for owner in data:
                            if "pets" in owner and owner["pets"]:
                                self.pet_ids.extend([pet["id"] for pet in owner["pets"] if "id" in pet])
                    response.success()
                except Exception as e:
                    response.failure(f"Failed to parse response: {e}")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(20)
    def view_owner_details(self):
        """
        View a specific owner with their pets (20% of traffic).

        MODERATE READ workload targeting customers-service.
        Tests: Entity relationships (pets), eager vs lazy loading, cache hits.
        """
        if not self.owner_ids:
            # No owners cached yet, fetch them first
            self.fetch_owners()
            if not self.owner_ids:
                # Still no owners, skip this request
                return

        owner_id = random.choice(self.owner_ids)
        with self.client.get(
            f"/api/customer/owners/{owner_id}",
            catch_response=True,
            name="/api/customer/owners/{id}"
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Update pet IDs if owner has pets
                    if "pets" in data and data["pets"]:
                        self.pet_ids.extend([pet["id"] for pet in data["pets"] if "id" in pet])
                    response.success()
                except Exception as e:
                    response.failure(f"Failed to parse owner details: {e}")
            elif response.status_code == 404:
                # Owner might have been deleted, remove from cache
                self.owner_ids.remove(owner_id)
                response.failure(f"Owner {owner_id} not found")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(15)
    def schedule_visit(self):
        """
        Schedule a new visit for a pet (15% of traffic).

        WRITE workload targeting visits-service.
        Tests: Transaction overhead, database inserts, connection pool usage, GC pressure.
        Creates the most garbage and CPU load among all tasks.
        """
        if not self.pet_ids:
            # No pets cached yet, try fetching owners first
            self.fetch_owners()
            if not self.pet_ids:
                # Still no pets, skip this request
                return

        pet_id = random.choice(self.pet_ids)

        # Generate a visit date within next 30 days
        visit_date = datetime.now() + timedelta(days=random.randint(1, 30))
        visit_description = random.choice([
            "Annual checkup",
            "Vaccination",
            "Dental cleaning",
            "Skin condition",
            "Follow-up examination",
            "Emergency visit",
            "Routine wellness check"
        ])

        payload = {
            "date": visit_date.strftime("%Y-%m-%d"),
            "description": visit_description,
            "petId": pet_id
        }

        with self.client.post(
            f"/api/visit/owners/*/pets/{pet_id}/visits",
            json=payload,
            catch_response=True,
            name="/api/visit/owners/*/pets/{petId}/visits"
        ) as response:
            if response.status_code in [200, 201]:
                response.success()
            elif response.status_code == 404:
                # Pet might not exist, remove from cache
                if pet_id in self.pet_ids:
                    self.pet_ids.remove(pet_id)
                response.failure(f"Pet {pet_id} not found")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(5)
    def browse_vets(self):
        """
        Browse all veterinarians (5% of traffic).

        LIGHTWEIGHT READ workload targeting vets-service.
        Tests: Caching effectiveness (vets rarely change), read-heavy optimization.
        Should have minimal GC impact due to caching.
        """
        with self.client.get(
            "/api/vet/vets",
            catch_response=True,
            name="/api/vet/vets"
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Update cached vet IDs
                    if data and len(data) > 0:
                        self.vet_ids = [vet["id"] for vet in data if "id" in vet]
                    response.success()
                except Exception as e:
                    response.failure(f"Failed to parse vets: {e}")
            else:
                response.failure(f"Got status {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """
    Called when the load test starts.
    Print configuration info.
    """
    print("=" * 60)
    print("Spring PetClinic Microservices Load Test")
    print("=" * 60)
    print(f"Target: {os.getenv('FRONTEND_URL', 'http://api-gateway:8080')}")
    print(f"Workload distribution:")
    print(f"  - 60% Browse owners (read-heavy)")
    print(f"  - 20% View owner details (moderate)")
    print(f"  - 15% Schedule visits (write-heavy)")
    print(f"  -  5% Browse vets (lightweight)")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    Called when the load test stops.
    Print summary.
    """
    print("=" * 60)
    print("Load test complete")
    print("=" * 60)
