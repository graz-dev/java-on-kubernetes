"""
Spring Framework PetClinic Load Test

Simulates realistic user behaviour for the Spring MVC web UI.
Pre-populated H2 sample data: owners 1-10, pets 1-13.
No JSON parsing — all IDs are hard-coded from sample data.

Weighted by frequency:
- 40% browse owners list (DB query + JSP render)
- 30% view owner details (JOIN query: owner+pets+visits)
- 20% submit new visit (DB insert → 302 redirect)
- 10% browse vets (Spring Cache — very cheap)
"""

import os
import random
from locust import HttpUser, task, between, events

# Pre-populated sample data from spring-framework-petclinic
OWNER_IDS = list(range(1, 11))       # owners 1-10
# pet-to-owner mapping from sample data (petId: ownerId)
PET_OWNER_MAP = {
    1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 5,
    7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 10, 13: 10,
}
PET_IDS = list(PET_OWNER_MAP.keys())  # pets 1-13


class PetClinicUser(HttpUser):
    wait_time = between(1, 3)
    host = os.getenv("FRONTEND_URL", "http://petclinic:8080")

    @task(40)
    def browse_owners(self):
        """Browse all owners (search by empty lastName)."""
        self.client.get(
            "/owners?lastName=",
            name="/owners?lastName=",
        )

    @task(30)
    def view_owner_details(self):
        """View a specific owner with their pets and visits."""
        owner_id = random.choice(OWNER_IDS)
        self.client.get(
            f"/owners/{owner_id}",
            name="/owners/{id}",
        )

    @task(20)
    def add_visit(self):
        """Submit a new visit for a pet (POST form → 302 redirect)."""
        pet_id = random.choice(PET_IDS)
        owner_id = PET_OWNER_MAP[pet_id]
        self.client.post(
            f"/owners/{owner_id}/pets/{pet_id}/visits/new",
            data={
                "date": "2026-03-01",
                "description": "Routine checkup",
            },
            name="/owners/{ownerId}/pets/{petId}/visits/new",
            allow_redirects=True,
        )

    @task(10)
    def browse_vets(self):
        """Browse veterinarians (Spring Cache — very cheap)."""
        self.client.get("/vets", name="/vets")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("Spring Framework PetClinic Load Test")
    print("=" * 60)
    print(f"Target: {os.getenv('FRONTEND_URL', 'http://petclinic:8080')}")
    print("Workload:")
    print("  40%  GET /owners?lastName=       (DB query + JSP)")
    print("  30%  GET /owners/{id}            (JOIN query)")
    print("  20%  POST .../visits/new         (DB insert)")
    print("  10%  GET /vets                   (cached)")
    print("=" * 60)
