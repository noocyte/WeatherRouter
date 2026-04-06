#!/usr/bin/env bash
set -euo pipefail

# WeatherRouter - Build, tag, and push Docker image to Docker Hub
#
# Usage:
#   ./docker-build-push.sh                       # build only
#   ./docker-build-push.sh --push                # build + push to Docker Hub
#   ./docker-build-push.sh --tag 2.1.0           # build with a specific version tag
#   ./docker-build-push.sh --tag 2.1.0 --push    # build + tag + push
#
# Environment variables:
#   DOCKER_USERNAME   Docker Hub username (required for push)
#   IMAGE_NAME        Image name (default: weatherrouter)

# Defaults
IMAGE_NAME="${IMAGE_NAME:-weatherrouter}"
TAG=""
PUSH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            TAG="$2"
            shift 2
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--tag VERSION] [--push]"
            echo ""
            echo "Options:"
            echo "  --tag VERSION   Version tag for the image (e.g. 2.1.0)"
            echo "  --push          Push the image to Docker Hub after building"
            echo ""
            echo "Environment variables:"
            echo "  DOCKER_USERNAME  Docker Hub username (required for --push)"
            echo "  IMAGE_NAME       Image name (default: weatherrouter)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run '$0 --help' for usage."
            exit 1
            ;;
    esac
done

# Resolve version tag
if [[ -z "$TAG" ]]; then
    GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    TAG="$(date +%Y%m%d)-${GIT_SHA}"
    echo "No --tag specified, using auto-generated tag: ${TAG}"
fi

# Resolve full image names
LOCAL_IMAGE="${IMAGE_NAME}:${TAG}"
LOCAL_LATEST="${IMAGE_NAME}:latest"

echo ""
echo "============================================="
echo "  Building: ${LOCAL_IMAGE}"
echo "============================================="
echo ""

# Build
docker build \
    --tag "${LOCAL_IMAGE}" \
    --tag "${LOCAL_LATEST}" \
    .

echo ""
echo "Build complete:"
echo "  ${LOCAL_IMAGE}"
echo "  ${LOCAL_LATEST}"

# Push (optional)
if [[ "$PUSH" == true ]]; then
    if [[ -z "${DOCKER_USERNAME:-}" ]]; then
        echo ""
        echo "ERROR: DOCKER_USERNAME is not set."
        echo "Run: export DOCKER_USERNAME=yourusername"
        exit 1
    fi

    REMOTE_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:${TAG}"
    REMOTE_LATEST="${DOCKER_USERNAME}/${IMAGE_NAME}:latest"

    echo ""
    echo "============================================="
    echo "  Pushing: ${REMOTE_IMAGE}"
    echo "============================================="
    echo ""

    # Tag for Docker Hub
    docker tag "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"
    docker tag "${LOCAL_LATEST}" "${REMOTE_LATEST}"

    # Push both tags
    docker push "${REMOTE_IMAGE}"
    docker push "${REMOTE_LATEST}"

    echo ""
    echo "Push complete:"
    echo "  ${REMOTE_IMAGE}"
    echo "  ${REMOTE_LATEST}"
fi

echo ""
echo "Done."
