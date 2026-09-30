# 🚀 Kubernetes Setup for Stack Monitoring

## Current Status
✅ **Backend is working**  
✅ **Monitoring API is operational**  
⚠️ **No Kubernetes contexts configured** (showing 0 deployments)

---

## What You Need

Your Stack Monitoring requires access to these Kubernetes clusters:

1. **QA01 Stack**: `stork-qa01-mp-npe-iad0-nc1`
2. **STG01 Stack**: `stork-stg01-mp-iad0-nc4`

These are the contexts defined in `backend/services/stack_monitoring.py`:

```python
CONTEXT_MAP = {
    "qa01": "stork-qa01-mp-npe-iad0-nc1",
    "stg01": "stork-stg01-mp-iad0-nc4"
}
```

---

## Option 1: Configure Kubernetes Access (Recommended)

### Step 1: Get Kubeconfig Files

You need the kubeconfig files from your infrastructure team. These files should provide access to:
- QA01 cluster
- STG01 cluster

### Step 2: Merge Contexts

If you receive separate kubeconfig files, merge them:

```bash
# Backup your current config
cp ~/.kube/config ~/.kube/config.backup

# Merge new configs
export KUBECONFIG=~/.kube/config:/path/to/qa01-config:/path/to/stg01-config   
kubectl config view --flatten > ~/.kube/config.merged
mv ~/.kube/config.merged ~/.kube/config
```

### Step 3: Verify Contexts

```bash
# List all contexts
kubectl config get-contexts

# Should show:
# - stork-qa01-mp-npe-iad0-nc1
# - stork-stg01-mp-iad0-nc4
```

### Step 4: Test Access

```bash
# Test QA01
kubectl --context=stork-qa01-mp-npe-iad0-nc1 get deployments -A

# Test STG01
kubectl --context=stork-stg01-mp-iad0-nc4 get deployments -A
```

### Step 5: Verify in Dashboard

1. Restart backend (if needed): `lsof -ti:8000 | xargs kill -9; cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000`
2. Refresh monitoring page
3. You should now see real deployment data!

---

## Option 2: Use Mock Data (For Demo/Testing)

If you don't have Kubernetes access yet, you can test with mock data:

### Update MonitoringSection.js

The component already has mock data built-in. Just ensure the fallback is working:

```javascript
// In fetchStackData(), if API fails, it uses:
setStackData({
  totalStacks: 8,
  healthyStacks: 7,
  warningStacks: 1,
  stacks: [
    { id: 'STG01', region: 'US-West', ... },
    { id: 'PROD01', region: 'US-East', ... },
    // ...
  ]
});
```

The page will automatically use mock data if Kubernetes is not available.

---

## Option 3: Configure Different Contexts

If your organization uses different context names, update `backend/services/stack_monitoring.py`:

```python
CONTEXT_MAP = {
    "qa01": "your-qa-context-name",    # Change this
    "stg01": "your-stg-context-name"   # Change this
}
```

Then restart the backend.

---

## Troubleshooting

### "0 deployments" shown in monitoring

**Cause**: No Kubernetes contexts configured  
**Solution**: Follow Option 1 above

### "Failed to fetch" error

**Cause**: Backend not running or `kubernetes` package not installed  
**Solution**: 
```bash
cd backend
source venv/bin/activate
pip install kubernetes pyyaml
uvicorn main:app --reload --port 8000
```

### "Unauthorized" or "Permission denied"

**Cause**: Kubeconfig doesn't have READ permissions  
**Solution**: Contact your DevOps team to grant `get`, `list` permissions for:
- `deployments` in all namespaces
- Across both qa01 and stg01 clusters

### "Context not found"

**Cause**: Context name mismatch  
**Solution**: 
1. Check available contexts: `kubectl config get-contexts`
2. Update `CONTEXT_MAP` in `stack_monitoring.py` to match your actual context names

---

## What Data is Collected

The monitoring service collects:

✅ **Read-only** deployment information:
- Deployment names
- Namespaces
- Container image versions
- Replica counts
- Status (healthy/unhealthy)

❌ **Does NOT**:
- Modify any resources
- Access secrets or sensitive data
- Require cluster-admin permissions
- Make any writes to the cluster

**Permissions needed**: `get`, `list` on `deployments` resource

---

## Test the API Directly

```bash
# Stack monitoring (full data)
curl http://localhost:8000/api/monitoring/stack | python3 -m json.tool

# Summary only
curl http://localhost:8000/api/monitoring/stack/summary | python3 -m json.tool

# Version mismatches
curl http://localhost:8000/api/monitoring/stack/mismatches | python3 -m json.tool
```

**Expected response** (with K8s configured):
```json
{
  "status": "operational",
  "timestamp": "2025-12-31...",
  "summary": {
    "qa01": { "total": 23, "healthy": 22, "warning": 1 },
    "stg01": { "total": 23, "healthy": 23, "warning": 0 }
  },
  "deployments": [...],
  "total_deployments": 46
}
```

**Current response** (without K8s):
```json
{
  "status": "operational",
  "summary": {
    "qa01": { "total": 0, "healthy": 0, "warning": 0 },
    "stg01": { "total": 0, "healthy": 0, "warning": 0 }
  },
  "deployments": [],
  "total_deployments": 0
}
```

---

## Next Steps

**To get real Stack Monitoring data:**

1. **Contact your DevOps/Infrastructure team** and request:
   - Kubeconfig access to `qa01` and `stg01` clusters
   - READ-ONLY permissions for deployments
   - Context names should match `stork-qa01-mp-npe-iad0-nc1` and `stork-stg01-mp-iad0-nc4`

2. **Once you have the kubeconfig**:
   - Merge it into `~/.kube/config`
   - Verify: `kubectl config get-contexts`
   - Test: `kubectl --context=stork-qa01-mp-npe-iad0-nc1 get deployments -A`

3. **Refresh the monitoring page**:
   - The backend will automatically detect the contexts
   - Deployments will appear immediately
   - No code changes needed!

---

## Summary

| Component | Status | Action Needed |
|-----------|--------|---------------|
| kubectl installed | ✅ v1.34.2 | None |
| Backend running | ✅ Port 8000 | None |
| Monitoring API | ✅ Working | None |
| kubernetes package | ✅ Installed | None |
| K8s contexts | ❌ Not configured | **Request from DevOps team** |

**The monitoring feature is fully implemented and ready to use. It's just waiting for Kubernetes access!** 🚀

---

## For Demo Purposes

If you want to show the feature working **right now** without waiting for K8s access, you can temporarily use the mock data by modifying the frontend to always use it. But for production use, you'll want the real Kubernetes integration.

Let me know if you need help with any of these steps!

