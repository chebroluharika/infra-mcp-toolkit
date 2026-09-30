import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../../../services/api';

/**
 * Calculate restart rate per pod per month from total restarts and age
 * @param {number} restarts - Total restart count
 * @param {string} age - Age string like "29mo", "15d", "3h"
 * @param {number} replicas - Number of replicas (pods)
 * @returns {object} { rate: number, rateDisplay: string, isHigh: boolean }
 */
const calculateRestartRate = (restarts, age, replicas = 1) => {
  if (!restarts || restarts === 0) {
    return { rate: 0, rateDisplay: null, isHigh: false };
  }
  
  // Parse age string to get actual months
  let actualMonths = 1; // Default to 1 month minimum
  if (age && age !== 'unknown') {
    const match = age.match(/^(\d+)(mo|d|h|m)$/);
    if (match) {
      const value = parseInt(match[1], 10);
      const unit = match[2];
      switch (unit) {
        case 'mo':
          actualMonths = value;
          break;
        case 'd':
          actualMonths = Math.max(value / 30, 0.1); // Convert days to months
          break;
        case 'h':
          actualMonths = Math.max(value / 720, 0.01); // Convert hours to months (30*24=720)
          break;
        case 'm':
          actualMonths = Math.max(value / 43200, 0.001); // Convert minutes to months
          break;
        default:
          actualMonths = 1;
      }
    }
  }
  
  // For actionable issues, cap age at 1 month to show recent restart activity
  // This means we treat all restarts as if they happened in the past month
  // This makes old deployments with accumulated restarts show up as issues
  const monthsForRate = Math.min(actualMonths, 1);
  
  // Calculate rate per pod per month (using capped months)
  const effectiveReplicas = Math.max(replicas, 1);
  const rate = restarts / effectiveReplicas / monthsForRate;
  
  // Determine if rate is high (more than 1 restart per pod per week = ~4.3/month)
  // Using capped 1-month window, so any deployment with >4 restarts/pod shows as high
  const isHigh = rate > 4;
  
  // Format display string
  let rateDisplay;
  if (rate >= 10) {
    rateDisplay = `${Math.round(rate)}/mo`;
  } else if (rate >= 1) {
    rateDisplay = `${rate.toFixed(1)}/mo`;
  } else if (rate >= 0.1) {
    rateDisplay = `${rate.toFixed(2)}/mo`;
  } else {
    rateDisplay = '<0.1/mo';
  }
  
  return { rate, rateDisplay, isHigh };
};

/**
 * Custom hook for Stack Monitoring data fetching and state management.
 * Centralizes all API calls and data transformation logic.
 */
export const useStackMonitoring = () => {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [stackData, setStackData] = useState(null);
  
  // Side panel state
  const [sidePanelOpen, setSidePanelOpen] = useState(false);
  const [selectedDeployment, setSelectedDeployment] = useState(null);
  const [deploymentDetails, setDeploymentDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsError, setDetailsError] = useState(null);
  const [podLogs, setPodLogs] = useState(null);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [selectedPodForLogs, setSelectedPodForLogs] = useState(null);
  const [stackHistory, setStackHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  
  // Release compliance state
  const [releaseCompliance, setReleaseCompliance] = useState(null);
  const [loadingCompliance, setLoadingCompliance] = useState(false);
  
  // Track if restart data is still loading (lite mode -> full mode transition)
  const [loadingRestarts, setLoadingRestarts] = useState(false);
  
  // Track sent alerts to avoid duplicates
  const sentAlertKeys = useRef(new Set());

  /**
   * Transform backend API data to frontend format
   */
  const transformStackData = useCallback((backendData) => {
    const { 
      deployments = [], 
      timestamp, 
      stacks_meta = {},
      events_by_stack = {},
      total_restarts = 0,
      crash_loop_count = 0,
      auth_status = {},
      initializing = false,
    } = backendData;
    
    const stacksData = {};
    
    deployments.forEach(dep => {
      Object.entries(dep.stacks).forEach(([stack, data]) => {
        if (!stacksData[stack]) {
          stacksData[stack] = { deployments: [], healthy: 0, warning: 0, critical: 0, notFound: 0 };
        }
        
        // Skip NOT_FOUND deployments from display (per plan)
        if (data.status === 'not_found') {
          stacksData[stack].notFound++;
          return; // Don't add to deployments list
        }
        
        // Calculate restart rate for this deployment
        const restarts = data.restarts || 0;
        const replicas = data.replicas?.desired || 1;
        const age = data.age || 'unknown';
        const restartRateInfo = calculateRestartRate(restarts, age, replicas);
        
        stacksData[stack].deployments.push({
          namespace: dep.namespace,
          namespaceFull: data.namespace_full || dep.namespace,
          deployment: dep.deployment,
          version: data.version,
          status: data.status,
          replicas: data.replicas || { desired: 0, ready: 0, available: 0, unavailable: 0 },
          age: age,
          lastUpdated: data.last_updated || null,
          image: data.image || null,
          restarts: restarts,
          restartRate: restartRateInfo.rate,
          restartRateDisplay: restartRateInfo.rateDisplay,
          restartRateHigh: restartRateInfo.isHigh,
          crashLoop: data.crash_loop || false,
          errorReason: data.error_reason || null,
          errorMessage: data.error_message || null,
          errorOccurredAt: data.error_occurred_at || null,  // Actual timestamp when error occurred (crash/OOM)
          statusChangedAt: data.status_changed_at || null,  // When status transitioned (for unhealthy)
        });
        
        // Count status (excluding not_found)
        // CrashLoopBackOff deployments are critical regardless of status
        if (data.crash_loop) {
          stacksData[stack].critical++;
        } else if (data.status === 'healthy') {
          stacksData[stack].healthy++;
        } else if (data.status?.includes('unhealthy') || data.status?.includes('error')) {
          stacksData[stack].critical++;
        } else {
          stacksData[stack].warning++;
        }
      });
    });
    
    // Include all configured stacks from stacks_meta
    Object.keys(stacks_meta).forEach(stackId => {
      if (!stacksData[stackId]) {
        const stackAuthStatus = auth_status[stackId];
        const hasAuthError = stackAuthStatus && stackAuthStatus.status !== 'ok';
        
        stacksData[stackId] = { 
          deployments: [], 
          healthy: 0, 
          warning: 0, 
          critical: 0,
          notFound: 0,
          connectionError: hasAuthError,
          errorMessage: stackAuthStatus?.message || 'No deployment data available'
        };
      }
    });
    
    // Build frontend stacks array
    const stacks = Object.entries(stacksData).map(([stackId, stackInfo]) => {
      const totalDeps = stackInfo.deployments.length;
      const healthPct = totalDeps > 0 ? Math.round((stackInfo.healthy / totalDeps) * 100) : 0;
      const meta = stacks_meta[stackId] || {};
      
      // Calculate aggregate stats
      const totalPodsDesired = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.desired || 0), 0);
      const totalPodsReady = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.ready || 0), 0);
      const totalPodsUnavailable = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.unavailable || 0), 0);
      
      const stackRestarts = stackInfo.deployments.reduce((sum, d) => sum + (d.restarts || 0), 0);
      
      const stackCrashLoops = stackInfo.deployments.filter(d => d.crashLoop).length;
      
      // Count deployments with high restart rates (>4 per pod per month)
      const highRestartRateCount = stackInfo.deployments.filter(d => d.restartRateHigh).length;
      
      // Calculate average restart rate across stack
      const deploymentsWithRestarts = stackInfo.deployments.filter(d => d.restarts > 0);
      const avgRestartRate = deploymentsWithRestarts.length > 0
        ? deploymentsWithRestarts.reduce((sum, d) => sum + (d.restartRate || 0), 0) / deploymentsWithRestarts.length
        : 0;
      
      let stackStatus;
      if (stackInfo.connectionError) {
        stackStatus = 'error';
      } else if (totalDeps === 0 && initializing) {
        stackStatus = 'initializing';
      } else if (totalDeps === 0) {
        stackStatus = 'unknown';
      } else if (stackInfo.critical > 0 || stackCrashLoops > 0) {
        stackStatus = 'critical';
      } else if (stackInfo.warning > 0 || highRestartRateCount > 0) {
        // Use high restart RATE count instead of raw restart count
        stackStatus = 'warning';
      } else {
        stackStatus = 'healthy';
      }
      
      return {
        id: stackId,
        name: meta.description || `${stackId.toUpperCase()} Stack`,
        region: meta.region || 'Unknown',
        status: stackStatus,
        components: stackInfo.deployments,
        totalDeployments: totalDeps,
        healthPercent: healthPct,
        metrics: {
          healthy: stackInfo.healthy,
          warning: stackInfo.warning,
          critical: stackInfo.critical
        },
        pods: {
          desired: totalPodsDesired,
          ready: totalPodsReady,
          unavailable: totalPodsUnavailable,
        },
        restarts: stackRestarts,
        highRestartRateCount,
        avgRestartRate,
        crashLoops: stackCrashLoops,
        notFoundCount: stackInfo.notFound,
        events: events_by_stack[stackId] || [],
        lastCheck: timestamp,
        connectionError: stackInfo.connectionError || false,
        errorMessage: stackInfo.errorMessage || null
      };
    });
    
    // Calculate totals
    const totalHealthy = Object.values(stacksData).reduce((sum, s) => sum + s.healthy, 0);
    const totalWarning = Object.values(stacksData).reduce((sum, s) => sum + s.warning, 0);
    const totalCritical = Object.values(stacksData).reduce((sum, s) => sum + s.critical, 0);
    const total = totalHealthy + totalWarning + totalCritical;
    
    
    const globalPodsDesired = stacks.reduce((sum, s) => sum + (s.pods?.desired || 0), 0);
    const globalPodsReady = stacks.reduce((sum, s) => sum + (s.pods?.ready || 0), 0);
    
    return {
      status: totalCritical > 0 ? 'critical' : totalWarning > 0 ? 'warning' : 'operational',
      uptime: total > 0 ? `${Math.round((totalHealthy / total) * 100)}%` : '0%',
      totalStacks: stacks.length,
      healthyStacks: stacks.filter(s => s.status === 'healthy').length,
      warningStacks: stacks.filter(s => s.status === 'warning').length,
      criticalStacks: stacks.filter(s => s.status === 'critical').length,
      initializingStacks: stacks.filter(s => s.status === 'initializing').length,
      stacks,
      totalPods: { desired: globalPodsDesired, ready: globalPodsReady },
      totalDeployments: total,
      totalRestarts: total_restarts,
      totalCrashLoops: crash_loop_count,
      initializing,
      lastUpdated: timestamp || new Date().toISOString(),
    };
  }, []);

  // Track if we have data to avoid showing loading spinner on background refreshes
  const hasDataRef = useRef(false);
  
  // Track if we're currently polling for initialization
  const initPollingRef = useRef(false);

  /**
   * Fetch stack monitoring data
   */
  const fetchStackMonitoring = useCallback(async (forceRefresh = false, useLiteMode = false) => {
    // Only show loading spinner on initial load (no data yet)
    if (!hasDataRef.current) {
      setLoading(true);
    }
    // Show refreshing state for manual refresh (when we already have data)
    if (forceRefresh && hasDataRef.current) {
      setRefreshing(true);
    }
    setError(null);
    
    try {
      const data = await api.getStackMonitoring(
        null,
        forceRefresh,
        useLiteMode,
        !forceRefresh
      );
      
      if (data.source === 'error') {
        console.warn('Stack Monitoring: K8s unavailable:', data.message);
        setError(data.message);
      } else {
        const transformedData = transformStackData(data);
        
        if (data.cache_age_seconds !== undefined) {
          transformedData.cacheAge = data.cache_age_seconds;
          transformedData.cached = data.cached;
        }
        
        if (data.fromLocalCache) {
          transformedData.fromLocalCache = true;
          transformedData.localCacheAge = data.cacheAge;
        }
        
        setStackData(transformedData);
        hasDataRef.current = true;
        
        // If lite mode, fetch full data in background (restart data will be loaded)
        if (useLiteMode && !forceRefresh) {
          setLoadingRestarts(true);
          setTimeout(() => {
            fetchStackMonitoring(false, false);
          }, 100);
        } else {
          // Full data loaded, restarts are available
          setLoadingRestarts(false);
        }

        // If backend is still initializing (kubeconfigs downloading),
        // poll again in 5s so we pick up the data once it's ready
        // Use refresh=true to bypass nginx cache and get fresh data
        if (data.initializing && !initPollingRef.current) {
          initPollingRef.current = true;
          const pollForReady = async () => {
            try {
              const freshData = await api.getStackMonitoring(null, true, false, false);
              if (!freshData.initializing) {
                initPollingRef.current = false;
                const transformed = transformStackData(freshData);
                if (freshData.cache_age_seconds !== undefined) {
                  transformed.cacheAge = freshData.cache_age_seconds;
                  transformed.cached = freshData.cached;
                }
                setStackData(transformed);
              } else {
                // Keep polling every 3s until ready
                setTimeout(pollForReady, 3000);
              }
            } catch (err) {
              console.warn('Init polling error:', err);
              initPollingRef.current = false;
            }
          };
          setTimeout(pollForReady, 3000);
        }
        
        // Fetch release compliance data in background
        fetchReleaseCompliance();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [transformStackData]);

  /**
   * Fetch release compliance data
   * Checks if stacks have the expected version based on release milestones
   */
  const fetchReleaseCompliance = useCallback(async () => {
    setLoadingCompliance(true);
    try {
      const data = await api.getReleaseCompliance();
      setReleaseCompliance(data);
    } catch (err) {
      console.warn('Failed to fetch release compliance:', err);
      setReleaseCompliance(null);
    } finally {
      setLoadingCompliance(false);
    }
  }, []);

  /**
   * Open deployment details side panel
   * @param {string} namespace - Namespace key (e.g., "--provisioner-pycore--branding") - used for history API
   * @param {string} deployment - Deployment name
   * @param {string} stack - Stack ID
   * @param {string} namespaceFull - Full K8s namespace (e.g., "mp-am2--provisioner-pycore--branding") - used for pod details API
   */
  const openDeploymentDetails = useCallback(async (namespace, deployment, stack, namespaceFull = null) => {
    // namespace = namespace key for history API matching
    // namespaceFull = actual k8s namespace for kubectl/pod API calls (defaults to namespace if not provided)
    console.log('[Details] Opening deployment details:', { namespace, deployment, stack, namespaceFull });
    setSelectedDeployment({ namespace, deployment, stack, namespaceFull: namespaceFull || namespace });
    setSidePanelOpen(true);
    setLoadingDetails(true);
    setDetailsError(null);
    setDeploymentDetails(null);
    setPodLogs(null);
    setSelectedPodForLogs(null);
    setStackHistory(null);  // Reset history when selecting a new deployment
    
    try {
      const deploymentName = deployment.includes('/') ? deployment.split('/')[0] : deployment;
      // Use namespaceFull for pod/details API calls (actual K8s namespace)
      const nsForApi = namespaceFull || namespace;
      
      // Progressive loading: lite first, then full
      const liteDetails = await api.getDeploymentDetails(nsForApi, deploymentName, stack, true);
      
      if (liteDetails.error) {
        setDetailsError(liteDetails.error);
        setLoadingDetails(false);
        return;
      }
      
      setDeploymentDetails({ ...liteDetails, isLite: true });
      setLoadingDetails(false);
      
      if (liteDetails.pods && liteDetails.pods.length > 0) {
        setSelectedPodForLogs(liteDetails.pods[0].name);
      }
      
      // Fetch full details in background
      try {
        const fullDetails = await api.getDeploymentDetails(namespace, deploymentName, stack, false);
        if (!fullDetails.error) {
          setDeploymentDetails({ ...fullDetails, isLite: false });
        }
      } catch (bgErr) {
        console.warn('Background fetch for full details failed:', bgErr);
        setDeploymentDetails(prev => prev ? { ...prev, isLite: false } : prev);
      }
    } catch (err) {
      setDetailsError(err.message);
      setLoadingDetails(false);
    }
  }, []);

  /**
   * Close side panel
   */
  const closeSidePanel = useCallback(() => {
    setSidePanelOpen(false);
    setSelectedDeployment(null);
    setDeploymentDetails(null);
    setPodLogs(null);
    setDetailsError(null);
  }, []);

  /**
   * Fetch pod logs
   */
  const fetchPodLogs = useCallback(async (podName, lines = 50) => {
    if (!selectedDeployment || !podName) return;
    
    setLoadingLogs(true);
    setPodLogs(null);
    setSelectedPodForLogs(podName);
    
    try {
      const { namespaceFull, stack } = selectedDeployment;
      const logs = await api.getPodLogs(namespaceFull, podName, stack, null, lines);
      
      if (logs.error) {
        setPodLogs({ error: logs.error });
      } else {
        setPodLogs(logs);
      }
    } catch (err) {
      setPodLogs({ error: err.message });
    } finally {
      setLoadingLogs(false);
    }
  }, [selectedDeployment]);

  /**
   * Fetch global stack history for trends (used by StackHealthSignals)
   */
  const fetchStackHistory = useCallback(async (hours = 24) => {
    setLoadingHistory(true);
    
    try {
      const history = await api.getStackHistory(hours);
      setStackHistory(history);
    } catch (err) {
      console.error('Failed to fetch stack history:', err);
      setStackHistory({ error: err.message, history: [] });
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  /**
   * Fetch deployment-specific history for the detail panel History tab
   * Includes guard against duplicate/concurrent fetches
   */
  const fetchingHistoryRef = useRef(false);
  
  const fetchDeploymentHistory = useCallback(async (hours = 24) => {
    if (!selectedDeployment) return;
    
    // Guard against concurrent fetches
    if (fetchingHistoryRef.current) {
      console.log('[History] Fetch already in progress, skipping');
      return;
    }
    
    fetchingHistoryRef.current = true;
    setLoadingHistory(true);
    
    try {
      const { namespace, deployment, stack } = selectedDeployment;
      const deploymentName = deployment.includes('/') ? deployment.split('/')[0] : deployment;
      
      console.log('[History] Fetching deployment history:', { namespace, deploymentName, stack, hours });
      
      const history = await api.getDeploymentHistory(namespace, deploymentName, stack, hours);
      
      console.log('[History] Response:', {
        namespace: history.namespace,
        deployment: history.deployment,
        dataPoints: history.summary?.data_points || 0,
        avgHealthy: history.summary?.avg_healthy,
        totalRestarts: history.summary?.total_restarts
      });
      
      // Warn if namespace doesn't match (indicates potential data mismatch)
      if (history.summary?.data_points === 0) {
        console.warn('[History] No data found for this namespace/deployment/stack combination. ' +
          'The namespace key may not match snapshot data.');
      }
      
      setStackHistory(history);
    } catch (err) {
      console.error('Failed to fetch deployment history:', err);
      setStackHistory({ error: err.message, history: [] });
    } finally {
      setLoadingHistory(false);
      fetchingHistoryRef.current = false;
    }
  }, [selectedDeployment]);

  /**
   * Calculate health score based on stack status distribution
   * 
   * Formula: Score = (Healthy × 100 + Warning × 50 + Critical × 0) / Total Stacks
   * 
   * - All healthy stacks → Score = 100
   * - All warning stacks → Score = 50
   * - All critical stacks → Score = 0
   * - Mixed → Weighted average
   */
  const calculateHealthScore = useCallback(() => {
    if (!stackData) return { score: 0, healthy: 0, warning: 0, critical: 0, total: 0 };
    
    const healthy = stackData.healthyStacks || 0;
    const warning = stackData.warningStacks || 0;
    const critical = stackData.criticalStacks || 0;
    const total = healthy + warning + critical;
    
    // Avoid division by zero
    if (total === 0) {
      return { score: 0, healthy: 0, warning: 0, critical: 0, total: 0 };
    }
    
    // Weighted average: Healthy=100pts, Warning=50pts, Critical=0pts
    const score = Math.round((healthy * 100 + warning * 50 + critical * 0) / total);
    
    return {
      score,
      healthy,
      warning,
      critical,
      total
    };
  }, [stackData]);

  /**
   * Get prioritized actionable issues
   */
  const getActionableIssues = useCallback(() => {
    if (!stackData?.stacks) return [];
    
    const issues = [];
    const processedDeployments = new Set();
    
    // Helper to format error message
    const formatErrorMessage = (c) => {
      if (c.errorMessage) {
        if (c.errorMessage.includes('manifest')) return 'Image not found in registry';
        if (c.errorMessage.includes('pulling image')) return 'Failed to pull image';
        if (c.errorMessage.length > 60) return c.errorMessage.substring(0, 57) + '...';
        return c.errorMessage;
      }
      return c.errorReason || null;
    };
    
    // Priority 1: ImagePullBackOff / ErrImagePull (Critical - pods can't start)
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => 
        c.errorReason === 'ImagePullBackOff' || c.errorReason === 'ErrImagePull'
      ).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        issues.push({
          id: `imagepull-${stack.id}-${c.deployment}`,
          severity: 'high',
          type: 'imagePull',
          title: c.errorReason,
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: formatErrorMessage(c) || 'Image pull failed',
          errorDetails: c.errorMessage,
          timestamp: c.errorOccurredAt || c.lastUpdated,  // Use actual error time if available
          lastUpdated: c.lastUpdated,
          actions: ['viewDetails', 'viewLogs', 'copyKubectl']
        });
      });
    });
    
    // Priority 2: CrashLoopBackOff
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => c.crashLoop).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        issues.push({
          id: `crash-${stack.id}-${c.deployment}`,
          severity: 'high',
          type: 'crashLoop',
          title: `CrashLoopBackOff`,
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: `${c.restarts} restarts`,
          timestamp: c.errorOccurredAt || c.lastUpdated,  // Use actual crash time if available
          lastUpdated: c.lastUpdated,  // Keep original for reference
          actions: ['viewLogs', 'viewPod', 'copyKubectl']
        });
      });
    });
    
    // Priority 2b: OOMKilled - Out of Memory errors
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => 
        c.errorReason === 'OOMKilled' || c.errorMessage?.includes('OOMKilled')
      ).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        issues.push({
          id: `oom-${stack.id}-${c.deployment}`,
          severity: 'high',
          type: 'oomKilled',
          title: 'OOMKilled',
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: 'Container killed due to memory limit',
          errorDetails: c.errorMessage,
          timestamp: c.errorOccurredAt || c.lastUpdated,  // Use actual OOM time if available
          lastUpdated: c.lastUpdated,  // Keep original for reference
          actions: ['viewLogs', 'viewPod', 'copyKubectl']
        });
      });
    });
    
    // Priority 2c: Pending pods - stuck in pending state
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => 
        c.status === 'Pending' || c.errorReason === 'Pending'
      ).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        issues.push({
          id: `pending-${stack.id}-${c.deployment}`,
          severity: 'medium',
          type: 'pending',
          title: 'Pending',
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: c.errorMessage || 'Pod stuck in pending state',
          errorDetails: c.errorMessage,
          timestamp: c.errorOccurredAt || c.lastUpdated,  // Use actual error time if available
          lastUpdated: c.lastUpdated,
          actions: ['viewDetails', 'copyKubectl']
        });
      });
    });
    
    // Priority 3: Unhealthy deployments (with error info if available)
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => 
        c.status?.includes('unhealthy') || c.status?.includes('error')
      ).filter(c => !c.crashLoop).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        const errorMsg = formatErrorMessage(c);
        issues.push({
          id: `unhealthy-${stack.id}-${c.deployment}`,
          severity: 'medium',
          type: 'unhealthy',
          title: c.errorReason || c.status,
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: errorMsg || `${c.replicas?.ready || 0}/${c.replicas?.desired || 0} replicas ready`,
          errorDetails: c.errorMessage,
          // Use statusChangedAt (last_transition_time) for when it became unhealthy
          // Falls back to lastUpdated if statusChangedAt not available
          timestamp: c.statusChangedAt || c.lastUpdated,
          lastUpdated: c.lastUpdated,
          actions: ['viewDetails', 'viewLogs', 'copyKubectl']
        });
      });
    });
    
    // Priority 4: High restart RATE (not raw count)
    // Only flag deployments with genuinely high restart rates (>4 per pod per month)
    stackData.stacks.forEach(stack => {
      stack.components?.filter(c => c.restartRateHigh && !c.crashLoop).forEach(c => {
        const key = `${stack.id}-${c.deployment}`;
        if (processedDeployments.has(key)) return;
        processedDeployments.add(key);
        
        issues.push({
          id: `restarts-${stack.id}-${c.deployment}`,
          severity: 'medium',
          type: 'restarts',
          title: 'High Restart Rate',
          stack: stack.id,
          stackName: stack.name,
          service: c.deployment,
          namespace: c.namespace,  // Namespace key for history API
          namespaceFull: c.namespaceFull || c.namespace,  // Full K8s namespace for kubectl/logs
          message: `${c.restartRateDisplay} per pod (${c.restarts} total)`,
          restarts: c.restarts,  // Explicit restart count for aggregation
          timestamp: c.lastUpdated,
          actions: ['viewLogs', 'viewDetails']
        });
      });
    });
    
    // Priority 4: Release compliance alerts (High)
    // Stacks not matching expected version based on release milestones
    releaseCompliance?.compliance_alerts?.forEach(alert => {
      issues.push({
        id: alert.id,
        severity: alert.severity,
        type: 'releaseCompliance',
        title: 'Release Version Mismatch',
        stack: alert.stack,
        stackName: alert.stackName,
        stackCategory: alert.stack_category,
        milestone: alert.milestone,
        milestoneDate: alert.milestone_date,
        expectedVersion: alert.expected_version,
        releaseName: alert.release_name,
        nonCompliantServices: alert.non_compliant_services,
        compliantServices: alert.compliant_services,
        complianceRatio: alert.compliance_ratio,
        message: alert.message,
        actions: ['viewDetails']
      });
    });
    
    // Sort issues: HIGH severity first, then MEDIUM
    const severityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    issues.sort((a, b) => (severityOrder[a.severity] || 99) - (severityOrder[b.severity] || 99));
    
    return issues;
  }, [stackData, releaseCompliance]);

  // Initial fetch on mount
  useEffect(() => {
    fetchStackMonitoring(false, true); // Use lite mode for faster initial load
  }, []);

  return {
    // Data state
    loading,
    refreshing,
    error,
    stackData,
    
    // Side panel state
    sidePanelOpen,
    selectedDeployment,
    deploymentDetails,
    loadingDetails,
    detailsError,
    podLogs,
    loadingLogs,
    selectedPodForLogs,
    stackHistory,
    loadingHistory,
    
    // Release compliance state
    releaseCompliance,
    loadingCompliance,
    
    // Restart data loading state (true during lite->full transition)
    loadingRestarts,
    
    // Actions
    fetchStackMonitoring,
    openDeploymentDetails,
    closeSidePanel,
    fetchPodLogs,
    fetchStackHistory,
    fetchDeploymentHistory,
    setSelectedPodForLogs,
    fetchReleaseCompliance,
    
    // Computed values
    calculateHealthScore,
    getActionableIssues,
  };
};

export default useStackMonitoring;
