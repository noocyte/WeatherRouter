#!/usr/bin/env bash
set -euo pipefail

# WeatherRouter - Build, tag, and push container image
# Works with both Podman and Docker (auto-detects, prefers Podman).
#
# Usage:
#   ./docker-build-push.sh                       # build only
#   ./docker-build-push.sh --push                # build + push to Docker Hub
#   ./docker-build-push.sh --tag 2.1.0           # build with a specific version tag
#   ./docker-build-push.sh --tag 2.1.0 --push    # build + tag + push
#   ./docker-build-push.sh --engine docker       # force Docker instead of Podman
#
# Environment variables:
#   DOCKER_USERNAME   Docker Hub username (required for push)
#   IMAGE_NAME        Image name (default: weatherrouter)
#   CONTAINER_ENGINE  Container engine to use ("podman" or "docker")

# Defaults
IMAGE_NAME="${IMAGE_NAME:-weatherrouter}"
TAG=""
PUSH=false
ENGINE=""

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
        --engine)
            ENGINE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--tag VERSION] [--push] [--engine podman|docker]"
            echo ""
            echo "Options:"
            echo "  --tag VERSION          Version tag for the image (e.g. 2.1.0)"
            echo "  --push                 Push the image to Docker Hub after building"
            echo "  --engine podman|docker  Force a specific container engine"
            echo ""
            echo "Environment variables:"
            echo "  DOCKER_USERNAME   Docker Hub username (required for --push)"
            echo "  IMAGE_NAME        Image name (default: weatherrouter)"
            echo "  CONTAINER_ENGINE  Container engine (default: auto-detect)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run '$0 --help' for usage."
            exit 1
            ;;
    esac
done

# Auto-detect container engine: prefer podman, fall back to docker
if [[ -z "$ENGINE" ]]; then
    ENGINE="${CONTAINER_ENGINE:-}"
fi
if [[ -z "$ENGINE" ]]; then
    if command -v podman &>/dev/null; then
        ENGINE="podman"
    elif command -v docker &>/dev/null; then
        ENGINE="docker"
    else
        echo "ERROR: Neither podman nor docker found in PATH."
        exit 1
    fi
fi

# Validate engine exists
if ! command -v "$ENGINE" &>/dev/null; then
    echo "ERROR: '$ENGINE' is not installed or not in PATH."
    exit 1
fi

echo "Using container engine: $ENGINE"

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
$ENGINE build \
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

    # Tag for registry
    $ENGINE tag "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"
    $ENGINE tag "${LOCAL_LATEST}" "${REMOTE_LATEST}"

    # Push both tags
    $ENGINE push "${REMOTE_IMAGE}"
    $ENGINE push "${REMOTE_LATEST}"

    echo ""
    echo "Push complete:"
    echo "  ${REMOTE_IMAGE}"
    echo "  ${REMOTE_LATEST}"
fi

echo ""
echo "Done."
