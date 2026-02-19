"""
Spring PetClinic Microservices Load Test - CPU INTENSIVE VERSION

This version is optimized to generate high CPU load for autoscaling validation.
Focus on write-heavy operations (schedule_visit) which create the most CPU and GC pressure.

Weighted for maximum CPU utilization:
- 70% schedule visits (write-heavy, CPU intensive)
- 15% view owner details (moderate reads)
- 10% browse owners (read-heavy, for data availability)
- 5% browse vets (lightweight reads)

Key differences from standard version:
- 10x faster request rate (wait_time: 0.1-0.5s instead of 1-3s)
- 70% writes instead of 15% (inverted ratio for CPU stress)
- Targets visits-service specifically for HPA scaling
"""

import os
import random
from locust import HttpUser, task, between, events
from datetime import datetime, timedelta


class PetClinicCPUIntensiveUser(HttpUser):
    """
    Simulates an aggressive user generating high CPU load on visits-service.

    Designed to trigger HPA autoscaling by maximizing write operations
    that create garbage collection pressure and CPU utilization.
    """

    # AGGRESSIVE: 10x faster than normal (0.1-0.5s instead of 1-3s)
    wait_time = between(0.1, 0.5)

    # Base URL - hitting services directly since API gateway has routing issues
    host = "http://customers-service.microservices-demo.svc.cluster.local:8081"
    visits_host = "http://visits-service.microservices-demo.svc.cluster.local:8082"
    vets_host = "http://vets-service.microservices-demo.svc.cluster.local:8083"

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
            "/owners",
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
            "http://vets-service.microservices-demo.svc.cluster.local:8083/vets",
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

    @task(70)
    def schedule_visit(self):
        """
        Schedule a new visit for a pet (70% of traffic - INCREASED FROM 15%).

        WRITE-HEAVY workload targeting visits-service.
        Tests: Transaction overhead, database inserts, connection pool usage, GC pressure.
        Creates the most garbage and CPU load among all tasks.

        This is the PRIMARY task for triggering CPU-based HPA autoscaling.
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
            "Routine wellness check",
            "Blood work",
            "X-ray examination",
            "Surgery consultation",
            "Post-operative checkup",
            "Prescription refill",
            "Behavioral assessment",
            "Nutrition consultation"
        ])

        payload = {
            "date": visit_date.strftime("%Y-%m-%d"),
            "description": visit_description,
            "petId": pet_id
        }

        with self.client.post(
            f"http://visits-service.microservices-demo.svc.cluster.local:8082/owners/*/pets/{pet_id}/visits",
            json=payload,
            catch_response=True,
            name="/owners/*/pets/{petId}/visits [visits-service]"
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

    @task(15)
    def view_owner_details(self):
        """
        View a specific owner with their pets (15% of traffic - REDUCED FROM 20%).

        MODERATE READ workload targeting customers-service.
        Kept to ensure we have fresh pet IDs for schedule_visit operations.
        """
        if not self.owner_ids:
            # No owners cached yet, fetch them first
            self.fetch_owners()
            if not self.owner_ids:
                # Still no owners, skip this request
                return

        owner_id = random.choice(self.owner_ids)
        with self.client.get(
            f"/owners/{owner_id}",
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

    @task(10)
    def browse_owners(self):
        """
        Browse all owners (10% of traffic - REDUCED FROM 60%).

        READ-HEAVY workload targeting customers-service.
        Kept minimal to ensure we have owner/pet data for write operations.
        """
        with self.client.get(
            "/owners",
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

    @task(5)
    def browse_vets(self):
        """
        Browse all veterinarians (5% of traffic - UNCHANGED).

        LIGHTWEIGHT READ workload targeting vets-service.
        Kept for realism but minimal impact on CPU.
        """
        with self.client.get(
            "http://vets-service.microservices-demo.svc.cluster.local:8083/vets",
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
    print("=" * 80)
    print("Spring PetClinic Microservices Load Test - CPU INTENSIVE VERSION")
    print("=" * 80)
    print(f"Target: {os.getenv('FRONTEND_URL', 'http://api-gateway:8080')}")
    print(f"Wait time: 0.1-0.5s (10x faster than normal)")
    print(f"Workload distribution:")
    print(f"  - 70% Schedule visits (write-heavy, CPU intensive) ← PRIMARY TARGET")
    print(f"  - 15% View owner details (moderate)")
    print(f"  - 10% Browse owners (read-heavy)")
    print(f"  -  5% Browse vets (lightweight)")
    print(f"")
    print(f"Goal: Generate high CPU load on visits-service to trigger HPA autoscaling")
    print("=" * 80)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """
    Called when the load test stops.
    Print summary.
    """
    print("=" * 80)
    print("CPU Intensive Load Test Complete")
    print("=" * 80)
