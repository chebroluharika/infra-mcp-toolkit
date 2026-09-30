#!/bin/bash
# Push Docker images to your container registry
# Usage: ./docker-load-and-push.sh <version> [registry]

VERSION=${1:-latest}
REGISTRY=${2:-${DOCKER_REGISTRY:-"your-registry.example.com"}}

IMAGES=(
    "qe-dashboard-backend"
    "qe-dashboard-frontend"
    "qe-dashboard-streamlit"
)

for IMAGE in "${IMAGES[@]}"; do
    echo "Tagging and pushing $IMAGE:$VERSION..."
    docker tag "$IMAGE:$VERSION" "$REGISTRY/$IMAGE:$VERSION"
    docker push "$REGISTRY/$IMAGE:$VERSION"
done

echo "Done. Images pushed to $REGISTRY"
