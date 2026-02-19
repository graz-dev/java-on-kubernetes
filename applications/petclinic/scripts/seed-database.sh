#!/bin/bash

# Seed PetClinic database with test data
# Creates owners and pets for load testing

set -e

NAMESPACE="${NAMESPACE:-microservices-demo}"
NUM_OWNERS="${NUM_OWNERS:-50}"

echo "========================================"
echo "PetClinic Database Seeding Script"
echo "========================================"
echo "Namespace: $NAMESPACE"
echo "Owners to create: $NUM_OWNERS"
echo "========================================"
echo ""

# Check if customers-service is available
if ! kubectl get svc customers-service -n "$NAMESPACE" &>/dev/null; then
    echo "❌ Error: customers-service not found in namespace $NAMESPACE"
    exit 1
fi

echo "Creating $NUM_OWNERS owners with 2 pets each..."

# Run seeding pod
kubectl run petclinic-seeder --image=curlimages/curl --rm -i --restart=Never -n "$NAMESPACE" -- sh -c "
BASE=\"http://customers-service:8081\"
echo \"Seeding database...\"

for i in \$(seq 1 $NUM_OWNERS); do
  # Create owner
  OWNER_JSON=\"{\\\"firstName\\\":\\\"Owner\$i\\\",\\\"lastName\\\":\\\"Test\\\",\\\"address\\\":\\\"\${i} Main St\\\",\\\"city\\\":\\\"Boston\\\",\\\"telephone\\\":\\\"617000\$(printf \\\"%04d\\\" \$i)\\\"}\";
  OWNER_ID=\$(curl -s -X POST \"\$BASE/owners\" -H \"Content-Type: application/json\" -d \"\$OWNER_JSON\" | grep -o '\\\"id\\\":[0-9]*' | cut -d: -f2)

  # Add 2 pets to each owner
  if [ -n \"\$OWNER_ID\" ]; then
    curl -s -X POST \"\$BASE/owners/\$OWNER_ID/pets\" -H \"Content-Type: application/json\" \
      -d \"{\\\"name\\\":\\\"Pet\${i}A\\\",\\\"birthDate\\\":\\\"2020-01-15\\\",\\\"type\\\":{\\\"name\\\":\\\"dog\\\"}}\" > /dev/null
    curl -s -X POST \"\$BASE/owners/\$OWNER_ID/pets\" -H \"Content-Type: application/json\" \
      -d \"{\\\"name\\\":\\\"Pet\${i}B\\\",\\\"birthDate\\\":\\\"2021-06-20\\\",\\\"type\\\":{\\\"name\\\":\\\"cat\\\"}}\" > /dev/null
  fi

  if [ \$((i % 10)) -eq 0 ]; then
    echo \"Created \$i owners...\";
  fi
done

echo \"\"
echo \"Verifying database...\"
OWNER_COUNT=\$(curl -s \"\$BASE/owners\" | grep -o '\\\"id\\\"' | wc -l | tr -d ' ')
echo \"Total entries in database: \$OWNER_COUNT\"
echo \"Expected: ~\$((NUM_OWNERS * 3)) (owners + pets)\"
" 2>&1 | grep -v "command prompt"

echo ""
echo "✅ Database seeding complete!"
echo ""
echo "To verify, run:"
echo "  kubectl run test --image=curlimages/curl --rm -i --restart=Never -n $NAMESPACE \\"
echo "    -- curl -s http://customers-service:8081/owners | head -c 500"
