    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}
log "=========================================="
log "Starting kubeconfig refresh..."
# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "ERROR: Container ${CONTAINER_NAME} is not running"
    exit 1
fi
# Clear old kubeconfigs from container
log "Clearing old kubeconfigs..."
if docker exec "$CONTAINER_NAME" rm -rf $KUBECONFIG_PATH 2>> "$LOGFILE"; then
    log "Old kubeconfigs cleared"
else
    log "WARNING: Failed to clear kubeconfigs (may not exist)"
fi
# Restart backend to trigger fresh kubeconfig download
log "Restarting backend container..."
cd "$PROJECT_DIR" && docker compose restart backend >> "$LOGFILE" 2>&1
# Wait for backend to be healthy
log "Waiting for backend to be healthy..."
sleep 30
# Verify backend is healthy
if curl -s http://localhost:8000/api/health | grep -q '"status":"healthy"'; then
    log "Backend is healthy"
else
    log "WARNING: Backend health check failed"
fi
# Check if new kubeconfigs were downloaded
KUBECONFIG_COUNT=$(docker exec "$CONTAINER_NAME" ls /home/appuser/.kube/rancher/ 2>/dev/null | wc -l)
log "Downloaded ${KUBECONFIG_COUNT} kubeconfig files"
log "Kubeconfig refresh completed"
log "=========================================="
