"""
Spring Framework PetClinic Load Test — CPU INTENSIVE VERSION

Optimised to generate high CPU load for HPA autoscaling validation.
Write-heavy operations (POST visits) create the most JVM CPU+GC pressure.

Weighted for maximum CPU utilisation:
- 70% POST new visit (DB insert, Hibernate transaction, OTel overhead)
- 20% GET owner details (JOIN query)
- 10% GET owners list  (DB query)

Key differences from standard version:
- 10x faster request rate (wait_time 0.1-0.5s instead of 1-3s)
- 70% writes instead of 20%
"""

import os
import random
from locust import HttpUser, task, between, events

# Pre-populated sample data from spring-framework-petclinic
OWNER_IDS = list(range(1, 11))       # owners 1-10
PET_OWNER_MAP = {
    1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 5,
    7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 10, 13: 10,
}
PET_IDS = list(PET_OWNER_MAP.keys())  # pets 1-13

VISIT_DESCRIPTIONS = [
    "Annual checkup",
    "Vaccination",
    "Dental cleaning",
    "Skin condition",
    "Follow-up examination",
    "Emergency visit",
    "Routine wellness check",
    "Blood work",
    "X-ray examination",
    "Post-operative checkup",
]


class PetClinicCPUIntensiveUser(HttpUser):
    # AGGRESSIVE: 10x faster than normal
    wait_time = between(0.1, 0.5)
    host = os.getenv("FRONTEND_URL", "http://petclinic:8080")

    @task(70)
    def add_visit(self):
        """Submit a new visit (PRIMARY HPA trigger — DB insert + OTel overhead)."""
        pet_id = random.choice(PET_IDS)
        owner_id = PET_OWNER_MAP[pet_id]
        self.client.post(
            f"/owners/{owner_id}/pets/{pet_id}/visits/new",
            data={
                "date": "2026-03-01",
                "description": random.choice(VISIT_DESCRIPTIONS),
            },
            name="/owners/{ownerId}/pets/{petId}/visits/new",
            allow_redirects=True,
        )

    @task(20)
    def view_owner_details(self):
        """View owner details (JOIN query: owner+pets+visits)."""
        owner_id = random.choice(OWNER_IDS)
        self.client.get(
            f"/owners/{owner_id}",
            name="/owners/{id}",
        )

    @task(10)
    def browse_owners(self):
        """Browse owners list (DB query + JSP render)."""
        self.client.get(
            "/owners?lastName=",
            name="/owners?lastName=",
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 80)
    print("Spring Framework PetClinic Load Test — CPU INTENSIVE VERSION")
    print("=" * 80)
    print(f"Target: {os.getenv('FRONTEND_URL', 'http://petclinic:8080')}")
    print("Wait time: 0.1-0.5s (10x faster than normal)")
    print("Workload:")
    print("  70%  POST .../visits/new   (write-heavy, CPU intensive) ← HPA trigger")
    print("  20%  GET /owners/{id}      (JOIN query)")
    print("  10%  GET /owners?lastName= (list query)")
    print("Goal: saturate petclinic pod CPU >70% to trigger HPA scale-out")
    print("=" * 80)
