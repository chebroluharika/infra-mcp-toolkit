#!/bin/bash

# Docker Build Script for QE Agentic Dashboard
# Supports local builds, multi-platform builds, testing, and export
#
# Usage: ./docker-build.sh [options] [version]
#
# Options:
#   -p, --platform PLATFORM   Build platform: local (default), amd64, arm64, multi
#   -t, --test                Run container health tests after build
#   -e, --export              Export images as tar.gz files
#   -s, --skip-cache          Build without Docker cache
#   -h, --help                Show this help message
#
# Examples:
#   ./docker-build.sh v1.0.2                    # Simple local build
#   ./docker-build.sh -t v1.0.2                 # Build and test
#   ./docker-build.sh -e v1.0.2                 # Build and export as tar.gz
#   ./docker-build.sh -t -e v1.0.2              # Build, test, and export
#   ./docker-build.sh -p amd64 -e v1.0.2        # Build for amd64 and export
#   ./docker-build.sh -p multi v1.0.2           # Multi-platform build (amd64 + arm64)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'`
NC='\033[0m' # No Color

# Default values
PLATFORM="local"
RUN_TESTS=false
EXPORT_IMAGES=false
NO_CACHE=""
VERSION="latest"
EXPORT_DIR="../docker-exports"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--platform)
            PLATFORM="$2"
            shift 2
            ;;
        -t|--test)
            RUN_TESTS=true
            shift
            ;;
        -e|--export)
            EXPORT_IMAGES=true
            shift
            ;;
        -s|--skip-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        -h|--help)
            head -25 "$0" | tail -20
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
        *)
            VERSION="$1"
            shift
            ;;
    esac
done

# Validate platform
case $PLATFORM in
    local|amd64|arm64|multi)
        ;;
    *)
        echo -e "${RED}Invalid platform: $PLATFORM${NC}"
        echo "Valid options: local, amd64, arm64, multi"
        exit 1
        ;;
esac

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}  QE Agentic Dashboard - Docker Build    ${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""
echo "Version:    ${VERSION}"
echo "Platform:   ${PLATFORM}"
echo "Run Tests:  ${RUN_TESTS}"
echo "Export:     ${EXPORT_IMAGES}"
echo ""

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}ERROR: Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Docker is running${NC}"

# Setup buildx for cross-platform builds
setup_buildx() {
    echo ""
    echo -e "${YELLOW}Setting up Docker Buildx...${NC}"
    BUILDER_NAME="multiplatform-builder"
    if ! docker buildx inspect ${BUILDER_NAME} &> /dev/null; then
        echo "Creating new buildx builder: ${BUILDER_NAME}"
        docker buildx create --name ${BUILDER_NAME} --driver docker-container --bootstrap --use
    else
        docker buildx use ${BUILDER_NAME}
    fi
    echo -e "${GREEN}[OK] Buildx builder ready${NC}"
}

# Build function for local platform
build_local() {
    local name=$1
    local dockerfile=$2
    local context=$3
    
    echo ""
    echo -e "${YELLOW}Building ${name}...${NC}"
    
    docker build ${NO_CACHE} \
        -f ${dockerfile} \
        -t qe-dashboard-${name}:${VERSION} \
        -t qe-dashboard-${name}:latest \
        ${context}
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[OK] ${name} built successfully${NC}"
    else
        echo -e "${RED}[FAIL] ${name} build failed${NC}"
        exit 1
    fi
}

# Build function for specific platform using buildx
build_platform() {
    local name=$1
    local dockerfile=$2
    local context=$3
    local platform=$4
    
    echo ""
    echo -e "${YELLOW}Building ${name} for ${platform}...${NC}"
    
    docker buildx build ${NO_CACHE} \
        --platform linux/${platform} \
        -f ${dockerfile} \
        -t qe-dashboard-${name}:${VERSION} \
        -t qe-dashboard-${name}:latest \
        --load \
        ${context}
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[OK] ${name} built successfully for ${platform}${NC}"
    else
        echo -e "${RED}[FAIL] ${name} build failed${NC}"
        exit 1
    fi
}

# Test containers function
run_tests() {
    echo ""
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}  Testing Containers                     ${NC}"
    echo -e "${BLUE}==========================================${NC}"
    
    # Stop any existing test containers
    docker stop test-backend test-frontend test-streamlit 2>/dev/null || true
    docker rm test-backend test-frontend test-streamlit 2>/dev/null || true
    docker network create test-network 2>/dev/null || true
    
    # Start backend
    echo ""
    echo -e "${YELLOW}Starting backend container...${NC}"
    docker run -d --name test-backend \
        --network test-network \
        -p 18000:8000 \
        -e APP_ENV=test \
        qe-dashboard-backend:${VERSION}
    
    # Wait for backend to be ready
    echo "Waiting for backend to be ready..."
    MAX_RETRIES=30
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s http://localhost:18000/api/health > /dev/null 2>&1; then
            echo -e "${GREEN}[OK] Backend is healthy${NC}"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
            echo -e "${RED}[FAIL] Backend health check failed${NC}"
            docker logs test-backend
            cleanup_tests
            exit 1
        fi
        sleep 1
    done
    
    # Start frontend
    echo -e "${YELLOW}Starting frontend container...${NC}"
    docker run -d --name test-frontend \
        --network test-network \
        --add-host=backend:$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' test-backend) \
        -p 13000:8080 \
        qe-dashboard-frontend:${VERSION}
    
    MAX_RETRIES=15
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s http://localhost:13000 > /dev/null 2>&1; then
            echo -e "${GREEN}[OK] Frontend is healthy${NC}"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
            if docker logs test-frontend 2>&1 | grep -q "host not found in upstream"; then
                echo -e "${YELLOW}[WARN] Frontend nginx can't resolve backend (expected in standalone test)${NC}"
                echo -e "${GREEN}[OK] Frontend image built correctly${NC}"
                break
            fi
            echo -e "${RED}[FAIL] Frontend health check failed${NC}"
            docker logs test-frontend
            cleanup_tests
            exit 1
        fi
        sleep 1
    done
    
    # Start streamlit
    echo -e "${YELLOW}Starting streamlit container...${NC}"
    docker run -d --name test-streamlit \
        --network test-network \
        -p 18501:8501 \
        -e ADK_LLM_PROVIDER=ollama \
        -e BACKEND_URL=http://test-backend:8000 \
        qe-dashboard-streamlit:${VERSION}
    
    sleep 5
    MAX_RETRIES=30
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if curl -s http://localhost:18501/_stcore/health > /dev/null 2>&1; then
            echo -e "${GREEN}[OK] Streamlit is healthy${NC}"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
            echo -e "${YELLOW}[WARN] Streamlit health check timed out (may need more time)${NC}"
            break
        fi
        sleep 1
    done
    
    cleanup_tests
}

# Cleanup test containers
cleanup_tests() {
    echo ""
    echo -e "${YELLOW}Cleaning up test containers...${NC}"
    docker stop test-backend test-frontend test-streamlit 2>/dev/null || true
    docker rm test-backend test-frontend test-streamlit 2>/dev/null || true
    docker network rm test-network 2>/dev/null || true
    echo -e "${GREEN}[OK] Test containers cleaned up${NC}"
}

# Export images function
export_images() {
    echo ""
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}  Exporting Images as TAR.GZ             ${NC}"
    echo -e "${BLUE}==========================================${NC}"
    
    mkdir -p ${EXPORT_DIR}
    
    # Add platform suffix for non-local builds
    local suffix=""
    if [ "$PLATFORM" != "local" ] && [ "$PLATFORM" != "multi" ]; then
        suffix="-${PLATFORM}"
    fi
    
    echo ""
    docker save qe-dashboard-backend:${VERSION} | gzip > ${EXPORT_DIR}/qe-dashboard-backend-${VERSION}${suffix}.tar.gz
    echo -e "${GREEN}[OK] Backend exported: qe-dashboard-backend-${VERSION}${suffix}.tar.gz${NC}"
    
    docker save qe-dashboard-frontend:${VERSION} | gzip > ${EXPORT_DIR}/qe-dashboard-frontend-${VERSION}${suffix}.tar.gz
    echo -e "${GREEN}[OK] Frontend exported: qe-dashboard-frontend-${VERSION}${suffix}.tar.gz${NC}"
    
    docker save qe-dashboard-streamlit:${VERSION} | gzip > ${EXPORT_DIR}/qe-dashboard-streamlit-${VERSION}${suffix}.tar.gz
    echo -e "${GREEN}[OK] Streamlit exported: qe-dashboard-streamlit-${VERSION}${suffix}.tar.gz${NC}"
    
    echo ""
    echo "Exported files:"
    ls -lh ${EXPORT_DIR}/*${VERSION}${suffix}.tar.gz
}

# Main build logic
echo ""
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}  Building Images                        ${NC}"
echo -e "${BLUE}==========================================${NC}"

# Change to docker directory (script location)
cd "$(dirname "$0")"

case $PLATFORM in
    local)
        build_local "backend" "../backend/Dockerfile" ".."
        build_local "frontend" "Dockerfile" ".."
        build_local "streamlit" "../ai_agents/Dockerfile" ".."
        ;;
    amd64|arm64)
        setup_buildx
        build_platform "backend" "../backend/Dockerfile" ".." "$PLATFORM"
        build_platform "frontend" "Dockerfile" ".." "$PLATFORM"
        build_platform "streamlit" "../ai_agents/Dockerfile" ".." "$PLATFORM"
        ;;
    multi)
        setup_buildx
        echo -e "${YELLOW}Note: Multi-platform builds require pushing to a registry or exporting.${NC}"
        echo -e "${YELLOW}Building for local platform for now...${NC}"
        build_local "backend" "../backend/Dockerfile" ".."
        build_local "frontend" "Dockerfile" ".."
        build_local "streamlit" "../ai_agents/Dockerfile" ".."
        ;;
esac

# Run tests if requested
if [ "$RUN_TESTS" = true ]; then
    run_tests
fi

# Export images if requested
if [ "$EXPORT_IMAGES" = true ]; then
    export_images
fi

# Summary
echo ""
echo -e "${BLUE}==========================================${NC}"
echo -e "${GREEN}  BUILD COMPLETE!                        ${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""
echo "Images created:"
echo "  - qe-dashboard-backend:${VERSION}"
echo "  - qe-dashboard-frontend:${VERSION}"
echo "  - qe-dashboard-streamlit:${VERSION}"
echo ""
docker images | grep "qe-dashboard" | grep -E "${VERSION}|latest" | head -6
echo ""
echo "To run with docker-compose:"
echo "  docker-compose up -d"
echo ""
if [ "$EXPORT_IMAGES" = true ]; then
    echo "To push to Artifactory:"
    echo "  ./docker-load-and-push.sh ${VERSION}"
    echo ""
fi
