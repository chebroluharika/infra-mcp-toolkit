/**
 * MonitoringSection - PDV Monitoring Component
 * 
 * NOTE: This component now primarily handles PDV (Post-Deployment Validation) monitoring.
 * 
 * STACK MONITORING has been moved to a separate, refactored component:
 * - See: src/components/sections/StackMonitoringPage.js
 * - See: src/components/stack-monitoring/* for modular components
 * 
 * The stack monitoring code in this file is DEPRECATED and kept for reference.
 * The 'stack' defaultView is no longer used - App.js routes to StackMonitoringPage instead.
 * 
 * @deprecated Stack monitoring code - use StackMonitoringPage instead
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Activity,
  Server,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Layers,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Lightbulb,
  FileWarning,
  Loader,
  X,
  Microscope,
  TrendingUp,
  Timer,
  RotateCcw,
  ExternalLink,
  Search,
  Info,
  Bell,
  Cpu,
  HardDrive,
  FileText,
  Heart,
  BarChart3,
  Terminal,
  Award,
  Shield,
  Zap
} from 'lucide-react';
import api from '../../services/api';
import { TfaModal } from '../shared/PipelineComponents';

const MonitoringSection = ({ selectedRelease, defaultView = 'pdv' }) => {
  const viewMode = defaultView; // 'pdv' or 'stack' - determined by route
  const [pdvSubView, setPdvSubView] = useState('backend'); // 'backend' or 'endpoint' - for PDV monitoring tabs
  const [loading, setLoading] = useState(false);
  const [pdvData, setPdvData] = useState(null);
  const [endpointPdvData, setEndpointPdvData] = useState(null); // Endpoint PDV runs data
  const [loadingEndpointPdv, setLoadingEndpointPdv] = useState(false);
  const [stackData, setStackData] = useState(null);
  const [error, setError] = useState(null);
  const [expandedStacks, setExpandedStacks] = useState({}); // Track which stacks show all deployments
  const [collapsedStackCards, setCollapsedStackCards] = useState({}); // Track which stack cards are fully collapsed
  
  // Stack Monitoring - Search, Filter, and View options
  const [stackSearchQuery, setStackSearchQuery] = useState('');
  const [stackStatusFilter, setStackStatusFilter] = useState('all'); // 'all', 'healthy', 'warning', 'critical'
  const [stackEnvFilter, setStackEnvFilter] = useState('all'); // 'all', 'npe', 'production'
  const [stackViewMode, setStackViewMode] = useState('dashboard'); // 'dashboard', 'grid', or 'comparison'
  const [copiedCommand, setCopiedCommand] = useState(null); // Track which command was copied
  // eslint-disable-next-line no-unused-vars
  const [selectedStackTab, setSelectedStackTab] = useState({}); // Track active tab per stack card (reserved for future use)
  // eslint-disable-next-line no-unused-vars
  const [showOnlyIssues, setShowOnlyIssues] = useState(false); // Filter to show only problematic deployments (reserved for future use)
  const [issuesPanelCollapsed, setIssuesPanelCollapsed] = useState(false); // Collapse issues panel
  const [alertsPanelCollapsed, setAlertsPanelCollapsed] = useState(true); // Collapse alerts panel (collapsed by default)
  
  // Side Panel State - for deployment detail view
  const [sidePanelOpen, setSidePanelOpen] = useState(false);
  const [selectedDeployment, setSelectedDeployment] = useState(null); // {namespace, deployment, stack}
  const [deploymentDetails, setDeploymentDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsError, setDetailsError] = useState(null);
  const [podLogs, setPodLogs] = useState(null);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [selectedPodForLogs, setSelectedPodForLogs] = useState(null);
  const [stackHistory, setStackHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [detailActiveTab, setDetailActiveTab] = useState('overview'); // 'overview', 'pods', 'logs', 'history'
  
  const [expandedPipelines, setExpandedPipelines] = useState({});
  const [pipelineBuilds, setPipelineBuilds] = useState({});
  // eslint-disable-next-line no-unused-vars
  const [loadingBuilds, setLoadingBuilds] = useState({}); // Reserved for future loading states
  const [tfaData, setTfaData] = useState(null);
  const [loadingTfa, setLoadingTfa] = useState(false);
  const [selectedPipelineForTfa, setSelectedPipelineForTfa] = useState(null);
  const [backendPdvRecentBuilds, setBackendPdvRecentBuilds] = useState([]);
  const [endpointPdvRecentBuilds, setEndpointPdvRecentBuilds] = useState([]);
  
  // Backend PDV by Stack - new state
  const [backendPdvByStack, setBackendPdvByStack] = useState(null);
  const [pdvGroupBy, setPdvGroupBy] = useState('stack'); // 'stack' or 'pipeline'
  const [selectedStackFilter, setSelectedStackFilter] = useState('all'); // 'all' or specific stack name
  
  // Endpoint PDV view state - reuse same pattern as Backend PDV
  const [endpointGroupBy, setEndpointGroupBy] = useState('stack'); // 'stack' or 'builds'
  const [endpointStackFilter, setEndpointStackFilter] = useState('all'); // 'all' or specific stack name
  
  // Track sent alerts to avoid duplicates (using a ref to persist across renders)
  const sentAlertKeys = useRef(new Set());

  // Send stack alerts to Slack (reserved for future Slack integration)
  // eslint-disable-next-line no-unused-vars
  const sendStackAlertsToSlack = async (alerts) => {
    if (!alerts || alerts.length === 0) return;
    
    // Filter out already-sent alerts (use stack + message as unique key)
    const newAlerts = alerts.filter(alert => {
      const key = `${alert.stack}-${alert.message}`;
      if (sentAlertKeys.current.has(key)) {
        return false;
      }
      sentAlertKeys.current.add(key);
      return true;
    });
    
    if (newAlerts.length === 0) return;
    
    try {
      const response = await fetch('/api/slack/stack-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alerts: newAlerts })
      });
      
      if (response.ok) {
        console.log(`Sent ${newAlerts.length} stack alert(s) to Slack`);
      } else {
        console.warn('Failed to send stack alerts to Slack:', await response.text());
      }
    } catch (err) {
      console.warn('Error sending stack alerts to Slack:', err.message);
    }
  };

  useEffect(() => {
    if (viewMode === 'pdv') {
      if (pdvSubView === 'backend') {
        fetchBackendPDVByStack();
      } else {
        fetchEndpointPDVData();
      }
    } else {
      // Use lite mode on initial load for faster page display
      // Full data (with events/restarts) will be fetched in background
      fetchStackMonitoring(false, true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, selectedRelease, pdvSubView]);

  // Fetch Backend PDV by Stack - NEW unified fetch
  const fetchBackendPDVByStack = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    
    if (forceRefresh) {
      setBackendPdvByStack(null);
      setPipelineBuilds({});
      setBackendPdvRecentBuilds([]);
    }
    
    try {
      // Fetch builds for stack coverage - balance between data and performance
      // 15 builds provides good coverage while keeping load time reasonable
      const byStackUrl = `/api/jenkins/backend-pdv-by-stack?num_builds=15${forceRefresh ? '&force_refresh=true' : ''}`;
      
      const byStackResponse = await fetch(byStackUrl);
      
      if (byStackResponse.ok) {
        const data = await byStackResponse.json();
        setBackendPdvByStack(data);
        
        // Also set pdvData for backward compatibility with existing helper functions
        const pipelines = [];
        Object.values(data.byPipeline || {}).forEach(pipelineInfo => {
          Object.entries(pipelineInfo.stacks || {}).forEach(([stack, stackInfo]) => {
            if (stackInfo.latestBuild) {
              pipelines.push({
                ...stackInfo.latestBuild,
                name: pipelineInfo.displayName,
                fullName: pipelineInfo.name,
                stack: stack,
                status: stackInfo.latestStatus,
                recentBuilds: stackInfo.builds || []
              });
            }
          });
        });
        
        setPdvData({
          pipelines,
          summary: {
            total: data.summary?.totalPipelines || 0,
            success: data.summary?.totalPassed || 0,
            failed: data.summary?.totalFailed || 0,
            unstable: 0
          }
        });
        
        // Populate pipelineBuilds cache
        const newBuildsCache = {};
        Object.values(data.byPipeline || {}).forEach(pipelineInfo => {
          newBuildsCache[pipelineInfo.name] = pipelineInfo.allBuilds || [];
        });
        setPipelineBuilds(prev => ({ ...prev, ...newBuildsCache }));
        
        // Construct recent builds from byStack data (no separate API call needed)
        // Collect all builds from all stacks, sort by timestamp, take top 30
        const allBuilds = [];
        Object.entries(data.byStack || {}).forEach(([stack, stackInfo]) => {
          (stackInfo.allBuilds || []).forEach(build => {
            allBuilds.push({
              ...build,
              stack: stack,
              jobName: build.pipelineDisplayName || build.pipelineKey,
              fullName: build.pipelineKey
            });
          });
        });
        
        // Sort by timestamp (most recent first) and take top 30
        const sortedBuilds = allBuilds.sort((a, b) => {
          const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
          const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
          return timeB - timeA;
        }).slice(0, 30);
        
        setBackendPdvRecentBuilds(sortedBuilds);

        // Persist summary for Overview page to read (avoids stale overview cache)
        try {
          const existing = JSON.parse(localStorage.getItem('pdv_health_cache') || '{}');
          localStorage.setItem('pdv_health_cache', JSON.stringify({
            ...existing,
            backend: {
              total_stacks: data.summary?.stacksList?.length || 0,
              failed_stacks: data.summary?.failedStacks || 0,
              total_builds: data.summary?.totalRuns || 0,
              builds_passed: data.summary?.totalPassed || 0,
              success_rate: data.summary?.overallPassRate || 0,
            },
            timestamp: Date.now()
          }));
        } catch (e) { /* ignore */ }
      } else {
        const errorData = await byStackResponse.json().catch(() => ({}));
        setBackendPdvByStack({ error: errorData.detail || 'Failed to fetch data' });
        setPdvData({ status: 'error', pipelines: [], summary: { total: 0, success: 0, failed: 0, unstable: 0 } });
      }
    } catch (err) {
      console.error('Failed to fetch Backend PDV by Stack:', err);
      setBackendPdvByStack({ error: err.message || 'Network error' });
      setPdvData({ status: 'error', pipelines: [], summary: { total: 0, success: 0, failed: 0, unstable: 0 } });
    } finally {
      setLoading(false);
    }
  };

  // Fetch Endpoint PDV Runs data (Golden Regression)
  const fetchEndpointPDVData = async (forceRefresh = false) => {
    setLoadingEndpointPdv(true);
    setError(null);
    
    // Clear cached builds when force refreshing
    if (forceRefresh) {
      setEndpointPdvRecentBuilds([]);
    }
    
    try {
      // Fetch endpoint data and recent builds in parallel
      const endpointUrl = `/api/jenkins/golden-regression?num_builds=10${forceRefresh ? '&force_refresh=true' : ''}`;
      const recentBuildsUrl = `/api/jenkins/recent-builds?pipeline_type=endpoint-pdv&limit=30${forceRefresh ? '&force_refresh=true' : ''}`;
      
      const [endpointResponse, recentBuildsResponse] = await Promise.all([
        fetch(endpointUrl),
        fetch(recentBuildsUrl)
      ]);
      
      if (endpointResponse.ok) {
        const data = await endpointResponse.json();
        if (data.error) {
          console.error('Endpoint PDV API error:', data.error);
          setEndpointPdvData({ error: data.error });
        } else {
          setEndpointPdvData(data);

          // Persist summary for Overview page (avoids stale overview cache)
          try {
            const stackGroups = data.stackGroups || {};
            const totalStacks = Object.keys(stackGroups).length;
            const failedStacks = Object.entries(stackGroups).filter(([, builds]) =>
              builds.length > 0 && builds[0]?.status !== 'success'
            ).length;
            const totalBuilds = Object.values(stackGroups).reduce((s, b) => s + b.length, 0);
            const buildsPassed = Object.values(stackGroups).reduce((s, b) =>
              s + b.filter(x => x.status === 'success').length, 0);

            const existing = JSON.parse(localStorage.getItem('pdv_health_cache') || '{}');
            localStorage.setItem('pdv_health_cache', JSON.stringify({
              ...existing,
              endpoint: {
                total_stacks: totalStacks,
                failed_stacks: failedStacks,
                total_builds: totalBuilds,
                builds_passed: buildsPassed,
                success_rate: totalBuilds > 0 ? Math.round((buildsPassed / totalBuilds) * 100) : 0,
              },
              timestamp: Date.now()
            }));
          } catch (e) { /* ignore */ }
        }
      } else {
        const errorData = await endpointResponse.json().catch(() => ({}));
        console.error('Endpoint PDV fetch failed:', endpointResponse.status, errorData);
        setEndpointPdvData({ 
          error: errorData.detail || `Failed to fetch: HTTP ${endpointResponse.status}` 
        });
      }
      
      // Set recent builds from dedicated endpoint (already sorted and aggregated by backend)
      if (recentBuildsResponse.ok) {
        const recentData = await recentBuildsResponse.json();
        setEndpointPdvRecentBuilds(recentData.builds || []);
      }
    } catch (err) {
      console.error('Failed to fetch Endpoint PDV data:', err);
      setEndpointPdvData({ error: err.message || 'Network error' });
    } finally {
      setLoadingEndpointPdv(false);
    }
  };

  // Helper: Parse duration string to minutes
  const parseDuration = (durationStr) => {
    if (!durationStr) return 0;
    const str = durationStr.toLowerCase();
    let minutes = 0;
    const hourMatch = str.match(/(\d+)\s*h/);
    const minMatch = str.match(/(\d+)\s*m/);
    const secMatch = str.match(/(\d+)\s*s/);
    if (hourMatch) minutes += parseInt(hourMatch[1]) * 60;
    if (minMatch) minutes += parseInt(minMatch[1]);
    if (secMatch) minutes += parseInt(secMatch[1]) / 60;
    return Math.round(minutes);
  };

  // Get Endpoint PDV failed builds
  const getEndpointFailedBuilds = () => {
    if (!endpointPdvData?.stackGroups) return [];
    const failed = [];
    Object.entries(endpointPdvData.stackGroups).forEach(([stack, builds]) => {
      builds.forEach(b => {
        if (b.status === 'failed' || b.status === 'aborted' || b.status === 'unstable') {
          failed.push({ ...b, stack });
        }
      });
    });
    return failed.sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
  };

  // Get Endpoint PDV stack success rates (sorted descending)
  const getEndpointStackSuccessRates = () => {
    if (!endpointPdvData?.stackGroups) return [];
    return Object.entries(endpointPdvData.stackGroups).map(([stackName, builds]) => {
      const total = builds.length;
      const success = builds.filter(b => b.status === 'success').length;
      const failed = builds.filter(b => b.status === 'failed').length;
      const rate = total > 0 ? Math.round((success / total) * 100) : 0;
      return { stack: stackName.toLowerCase(), successRate: rate, Failed: failed, total };
    }).sort((a, b) => b.successRate - a.successRate); // Sort descending (100% first)
  };

  // Get Endpoint PDV failure reasons
  const getEndpointFailureReasons = () => {
    if (!endpointPdvData?.stackGroups) return { reasons: [], recurring: [] };
    
    const reasonCounts = {};
    Object.entries(endpointPdvData.stackGroups).forEach(([stack, builds]) => {
      builds.forEach(build => {
        if (build.status === 'failed' || build.status === 'aborted') {
          const reason = build.failureReason || `Build failed on ${stack}`;
          if (!reasonCounts[reason]) {
            reasonCounts[reason] = { count: 0, stacks: new Set() };
          }
          reasonCounts[reason].count++;
          reasonCounts[reason].stacks.add(stack);
        }
      });
    });
    
    const reasons = Object.entries(reasonCounts)
      .map(([reason, data]) => ({
        reason: reason.length > 60 ? reason.substring(0, 60) + '...' : reason,
        fullReason: reason,
        count: data.count,
        stacks: Array.from(data.stacks),
        isRecurring: data.count >= 2
      }))
      .sort((a, b) => b.count - a.count);
    
    const recurring = reasons.filter(r => r.isRecurring).slice(0, 5);
    return { reasons: reasons.slice(0, 10), recurring };
  };

  // Get Endpoint PDV execution times
  const getEndpointExecutionTimes = () => {
    if (!endpointPdvData?.stackGroups) return [];
    
    const stackTimes = {};
    Object.entries(endpointPdvData.stackGroups).forEach(([stack, builds]) => {
      builds.forEach(build => {
        const duration = parseDuration(build.duration);
        if (!stackTimes[stack]) {
          stackTimes[stack] = { totalDuration: 0, count: 0 };
        }
        stackTimes[stack].totalDuration += duration;
        stackTimes[stack].count++;
      });
    });
    
    return Object.entries(stackTimes)
      .map(([stack, data]) => ({
        stack,
        avgDuration: data.count > 0 ? Math.round(data.totalDuration / data.count) : 0,
        runCount: data.count
      }))
      .sort((a, b) => b.avgDuration - a.avgDuration)
      .slice(0, 8);
  };

  // Get Endpoint PDV action items
  const getEndpointActionItems = () => {
    if (!endpointPdvData) return [];
    
    const actions = [];
    const failedBuilds = getEndpointFailedBuilds();
    const stackSuccessRates = getEndpointStackSuccessRates();
    const { recurring } = getEndpointFailureReasons();
    const stackGroups = endpointPdvData.stackGroups || {};
    const sortedStacks = endpointPdvData.sortedStacks || [];
    
    // Collect all builds for analysis
    const allBuilds = [];
    Object.entries(stackGroups).forEach(([stack, builds]) => {
      (builds || []).forEach(build => {
        allBuilds.push({ ...build, stack });
      });
    });
    
    // 1. Critical: Failed builds
    if (failedBuilds.length > 0) {
      actions.push({
        priority: failedBuilds.length >= 3 ? 'critical' : 'warning',
        title: `${failedBuilds.length} failed build(s)`,
        description: `Stacks: ${[...new Set(failedBuilds.map(b => b.stack))].slice(0, 3).join(', ')}`,
        action: 'Investigate and fix failures'
      });
    }
    
    // 2. Critical: Consecutive failures (stack failing 3+ times in a row)
    const consecutiveFailures = [];
    Object.entries(stackGroups).forEach(([stack, builds]) => {
      const sortedBuilds = (builds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
      let consecutiveCount = 0;
      for (const build of sortedBuilds) {
        if (build.status === 'failed' || build.status === 'aborted') {
          consecutiveCount++;
        } else {
          break;
        }
      }
      if (consecutiveCount >= 3) {
        consecutiveFailures.push({ stack, count: consecutiveCount });
      }
    });
    if (consecutiveFailures.length > 0) {
      actions.push({
        priority: 'critical',
        title: `${consecutiveFailures.length} stack(s) failing consecutively`,
        description: consecutiveFailures.slice(0, 2).map(s => `${s.stack}: ${s.count}x`).join(', '),
        action: 'Urgent: Check infrastructure'
      });
    }
    
    // 3. Critical: New regression (previously passing, now failing)
    const newRegressions = [];
    Object.entries(stackGroups).forEach(([stack, builds]) => {
      const sortedBuilds = (builds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
      if (sortedBuilds.length >= 2) {
        const latest = sortedBuilds[0];
        const previous = sortedBuilds[1];
        if (latest.status !== 'success' && previous.status === 'success') {
          newRegressions.push({ stack, buildNumber: latest.buildNumber });
        }
      }
    });
    if (newRegressions.length > 0) {
      actions.push({
        priority: 'critical',
        title: `${newRegressions.length} new regression(s)`,
        description: newRegressions.slice(0, 3).map(r => `${r.stack} (#${r.buildNumber})`).join(', '),
        action: 'Recent change broke tests'
      });
    }
    
    // 4. Warning: Low success rate stacks
    const lowSuccessStacks = stackSuccessRates.filter(s => s.successRate < 70);
    if (lowSuccessStacks.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${lowSuccessStacks.length} stack(s) below 70%`,
        description: lowSuccessStacks.slice(0, 3).map(s => `${s.stack}: ${s.successRate}%`).join(', '),
        action: 'Review test stability'
      });
    }
    
    // 5. Warning: Aborted builds spike
    const abortedBuilds = allBuilds.filter(b => b.status === 'aborted');
    const abortedPercent = allBuilds.length > 0 ? Math.round((abortedBuilds.length / allBuilds.length) * 100) : 0;
    if (abortedBuilds.length >= 3 || abortedPercent >= 10) {
      const uniqueStacks = [...new Set(abortedBuilds.map(b => b.stack))];
      actions.push({
        priority: 'warning',
        title: `${abortedBuilds.length} aborted build(s) (${abortedPercent}%)`,
        description: `Stacks: ${uniqueStacks.slice(0, 3).join(', ')}`,
        action: 'Check infrastructure/timeouts'
      });
    }
    
    // 6. Warning: Flapping tests (alternating pass/fail)
    const flappingStacks = [];
    Object.entries(stackGroups).forEach(([stack, builds]) => {
      const sortedBuilds = (builds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
      if (sortedBuilds.length >= 4) {
        let alternations = 0;
        for (let i = 0; i < sortedBuilds.length - 1 && i < 4; i++) {
          const current = sortedBuilds[i].status === 'success';
          const next = sortedBuilds[i + 1].status === 'success';
          if (current !== next) alternations++;
        }
        if (alternations >= 3) {
          flappingStacks.push(stack);
        }
      }
    });
    if (flappingStacks.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${flappingStacks.length} flapping stack(s)`,
        description: flappingStacks.slice(0, 3).join(', '),
        action: 'Tests are unstable - investigate'
      });
    }
    
    // 7. Warning: Recurring failures
    if (recurring.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${recurring.length} recurring issue(s)`,
        description: recurring[0]?.reason || 'Multiple failures detected',
        action: 'Address root cause'
      });
    }
    
    // 8. Info: Stacks with 100% success rate (highlight good performers)
    const perfectStacks = stackSuccessRates.filter(s => s.successRate === 100);
    if (perfectStacks.length > 0 && perfectStacks.length < sortedStacks.length) {
      actions.push({
        priority: 'info',
        title: `${perfectStacks.length} stack(s) at 100%`,
        description: perfectStacks.slice(0, 4).map(s => s.stack).join(', '),
        action: 'Top performers'
      });
    }
    
    // 9. Info: Long-running builds (> 30 minutes average)
    const executionTimes = getEndpointExecutionTimes();
    const longRunningStacks = executionTimes.filter(s => s.avgDuration > 30);
    if (longRunningStacks.length > 0) {
      actions.push({
        priority: 'info',
        title: `${longRunningStacks.length} slow stack(s)`,
        description: longRunningStacks.slice(0, 2).map(s => `${s.stack}: ${s.avgDuration}m`).join(', '),
        action: 'Optimize test execution'
      });
    }
    
    // 10. Info: No recent activity
    const mostRecentBuild = allBuilds.reduce((latest, build) => {
      const buildTime = build.timestampMs || 0;
      return buildTime > (latest?.timestampMs || 0) ? build : latest;
    }, null);
    if (mostRecentBuild) {
      const hoursSinceLastBuild = Math.round((Date.now() - mostRecentBuild.timestampMs) / (1000 * 60 * 60));
      if (hoursSinceLastBuild >= 24) {
        actions.push({
          priority: 'info',
          title: `No builds in ${hoursSinceLastBuild}h`,
          description: `Last: ${mostRecentBuild.stack} at ${mostRecentBuild.timestamp || 'Unknown'}`,
          action: 'Check if pipeline is running'
        });
      }
    }
    
    // Success: All healthy
    if (actions.length === 0) {
      actions.push({
        priority: 'success',
        title: 'All stacks healthy',
        description: `${endpointPdvData.summary?.totalStacks || 0} stacks passing`,
        action: 'Continue monitoring'
      });
    }
    
    // Sort by priority: critical > warning > info > success
    const priorityOrder = { critical: 0, warning: 1, info: 2, success: 3 };
    actions.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
    
    return actions;
  };

  // ============ REUSABLE STACK HEALTH MATRIX COMPONENT ============
  // This component can render a stack health matrix for both Backend PDV (stacks × pipelines) 
  // and Endpoint PDV (stacks × recent builds)
  const renderStackHealthMatrix = ({
    stacks,           // Array of stack names (rows)
    columns,          // Array of column keys (pipelines or build indices)
    getStatus,        // Function(stack, colKey) => 'success' | 'failed' | 'unstable' | null
    getColumnLabel,   // Function(colKey) => string (short label for column header)
    getColumnTitle,   // Function(colKey) => string (full name for legend)
    getCellTitle,     // Function(stack, colKey, status) => string (tooltip)
    maxHeight = '260px'
  }) => {
    if (!stacks?.length || !columns?.length) {
      return (
        <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
          <Server size={24} style={{ color: 'var(--text-muted)', marginBottom: '8px' }} />
          <div style={{ fontSize: '12px' }}>No matrix data available</div>
        </div>
      );
    }

    return (
      <div style={{ padding: '14px', maxHeight, overflowY: 'auto', display: 'flex', gap: '14px' }}>
        {/* Matrix Table */}
        <div style={{ flex: '0 0 auto' }}>
          {/* Matrix Header */}
          <div style={{ display: 'flex', gap: '5px', marginBottom: '10px', paddingLeft: '55px' }}>
            {columns.map(colKey => (
              <div key={colKey} style={{ 
                width: '28px', fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center',
                overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: '600'
              }} title={getColumnTitle(colKey)}>
                {getColumnLabel(colKey)}
              </div>
            ))}
          </div>
          {/* Matrix Rows */}
          {stacks.map(stack => (
            <div key={stack} style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '6px' }}>
              <span style={{ 
                width: '50px', fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'
              }}>{stack.toUpperCase()}</span>
              {columns.map(colKey => {
                const status = getStatus(stack, colKey);
                return (
                  <div 
                    key={colKey} 
                    style={{ 
                      width: '28px', height: '24px', borderRadius: '4px',
                      background: status === 'success' ? 'rgba(76, 175, 80, 0.2)' :
                                 status === 'failed' ? 'rgba(244, 67, 54, 0.2)' :
                                 status === 'unstable' ? 'rgba(255, 193, 7, 0.2)' : 
                                 status === 'aborted' ? 'rgba(158, 158, 158, 0.2)' : 'var(--bg-tertiary)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center'
                    }}
                    title={getCellTitle(stack, colKey, status)}
                  >
                    {status === 'success' && <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />}
                    {status === 'failed' && <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                    {status === 'unstable' && <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />}
                    {status === 'aborted' && <XCircle size={14} style={{ color: 'var(--text-muted)' }} />}
                    {!status && <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>-</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {/* Legend - Right Side */}
        <div style={{ 
          flex: '1 1 auto', paddingLeft: '12px', borderLeft: '1px solid var(--border-color)',
          display: 'flex', flexDirection: 'column', gap: '6px', justifyContent: 'center'
        }}>
          {columns.map(colKey => (
            <div key={colKey} style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ 
                fontWeight: '700', color: 'var(--text-primary)', 
                background: 'var(--bg-tertiary)', padding: '3px 6px', borderRadius: '4px',
                minWidth: '24px', textAlign: 'center', fontSize: '10px'
              }}>{getColumnLabel(colKey)}</span>
              <span style={{ color: 'var(--text-secondary)' }}>{getColumnTitle(colKey)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ============ BACKEND PDV ANALYTICS HELPERS ============
  
  // Get Backend PDV stack success rates (from backendPdvByStack data)
  const getBackendPDVStackSuccessRates = () => {
    if (!backendPdvByStack?.byStack) return [];
    
    return Object.entries(backendPdvByStack.byStack).map(([stackName, stackInfo]) => {
      const summary = stackInfo.summary || {};
      const total = summary.total || 0;
      const passed = summary.passed || 0;
      const failed = summary.failed || 0;
      const rate = total > 0 ? Math.round((passed / total) * 100) : 0;
      return { stack: stackName, successRate: rate, failed: failed, total };
    }).sort((a, b) => b.successRate - a.successRate);
  };
  
  // Get Backend PDV recent failures (from backendPdvByStack data)
  const getBackendPDVRecentFailures = () => {
    if (!backendPdvByStack?.byStack) return [];
    
    const failures = [];
    Object.entries(backendPdvByStack.byStack).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        if (build.status === 'failed' || build.status === 'unstable' || build.status === 'aborted') {
          failures.push({
            ...build,
            stack: stack
          });
        }
      });
    });
    
    // Sort by timestamp (most recent first)
    return failures.sort((a, b) => {
      const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      return timeB - timeA;
    }).slice(0, 10);
  };
  
  // Get Backend PDV failure reasons (from backendPdvByStack data)
  const getBackendPDVFailureReasons = () => {
    if (!backendPdvByStack?.byStack) return { reasons: [], recurring: [] };
    
    const reasonCounts = {};
    Object.entries(backendPdvByStack.byStack).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        if (build.status === 'failed' || build.status === 'aborted') {
          const pipeline = build.pipelineDisplayName || build.pipelineKey || 'Unknown';
          const reason = `${pipeline} failed on ${stack.toUpperCase()}`;
          if (!reasonCounts[reason]) {
            reasonCounts[reason] = { count: 0, stacks: new Set(), pipeline };
          }
          reasonCounts[reason].count++;
          reasonCounts[reason].stacks.add(stack);
        }
      });
    });
    
    const reasons = Object.entries(reasonCounts)
      .map(([reason, data]) => ({
        reason: reason.length > 50 ? reason.substring(0, 50) + '...' : reason,
        fullReason: reason,
        count: data.count,
        stacks: Array.from(data.stacks),
        isRecurring: data.count >= 2
      }))
      .sort((a, b) => b.count - a.count);
    
    const recurring = reasons.filter(r => r.isRecurring).slice(0, 5);
    return { reasons: reasons.slice(0, 8), recurring };
  };
  
  // Get Backend PDV execution times per stack (from backendPdvByStack data)
  const getBackendPDVExecutionTimes = () => {
    if (!backendPdvByStack?.byStack) return [];
    
    const stackTimes = {};
    Object.entries(backendPdvByStack.byStack).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        const duration = parseDuration(build.duration);
        if (!stackTimes[stack]) {
          stackTimes[stack] = { totalDuration: 0, count: 0 };
        }
        stackTimes[stack].totalDuration += duration;
        stackTimes[stack].count++;
      });
    });
    
    return Object.entries(stackTimes)
      .map(([stack, data]) => ({
        stack,
        avgDuration: data.count > 0 ? Math.round(data.totalDuration / data.count) : 0,
        runCount: data.count
      }))
      .sort((a, b) => b.avgDuration - a.avgDuration)
      .slice(0, 10);
  };
  
  // Get Backend PDV action items
  const getBackendPDVActionItems = () => {
    if (!backendPdvByStack) return [];
    
    const actions = [];
    const failedBuilds = getBackendPDVRecentFailures();
    const stackSuccessRates = getBackendPDVStackSuccessRates();
    const { recurring } = getBackendPDVFailureReasons();
    const executionTimes = getBackendPDVExecutionTimes();
    
    // Collect all builds for analysis
    const allBuilds = [];
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      (stackInfo.allBuilds || []).forEach(build => {
        allBuilds.push({ ...build, stack });
      });
    });
    
    // 1. Critical: Failed builds
    if (failedBuilds.length > 0) {
      const failedDetails = failedBuilds.slice(0, 5).map(b => 
        `• ${b.pipelineKey || 'Unknown'} on ${(b.stack || 'N/A').toUpperCase()} (Build #${b.buildNumber})`
      ).join('\n');
      actions.push({
        priority: failedBuilds.length >= 3 ? 'critical' : 'warning',
        title: `${failedBuilds.length} failed build(s)`,
        description: `Stacks: ${[...new Set(failedBuilds.map(b => b.stack))].slice(0, 3).map(s => s.toUpperCase()).join(', ')}`,
        action: 'Investigate and fix failures',
        tooltip: `Failed Builds:\n${failedDetails}${failedBuilds.length > 5 ? `\n... and ${failedBuilds.length - 5} more` : ''}`
      });
    }
    
    // 2. Warning: Unstable builds (not failed, but unstable status)
    const unstableBuilds = allBuilds.filter(b => b.status === 'unstable');
    if (unstableBuilds.length > 0) {
      const uniqueStacks = [...new Set(unstableBuilds.map(b => b.stack))];
      const unstableDetails = unstableBuilds.slice(0, 5).map(b => 
        `• ${b.pipelineKey || 'Unknown'} on ${(b.stack || 'N/A').toUpperCase()} (Build #${b.buildNumber})`
      ).join('\n');
      actions.push({
        priority: 'warning',
        title: `${unstableBuilds.length} unstable build(s)`,
        description: `Flaky tests on ${uniqueStacks.slice(0, 2).map(s => s.toUpperCase()).join(', ')}${uniqueStacks.length > 2 ? '...' : ''}`,
        action: 'Review test stability',
        tooltip: `Unstable Builds (some tests passed, some failed):\n${unstableDetails}${unstableBuilds.length > 5 ? `\n... and ${unstableBuilds.length - 5} more` : ''}`
      });
    }
    
    // 3. Warning: Long-running builds (> 45 minutes average)
    const longRunningStacks = executionTimes.filter(s => s.avgDuration > 45);
    if (longRunningStacks.length > 0) {
      actions.push({
        priority: 'info',
        title: `${longRunningStacks.length} slow stack(s)`,
        description: longRunningStacks.slice(0, 2).map(s => `${s.stack.toUpperCase()}: ${s.avgDuration}m`).join(', '),
        action: 'Optimize test execution'
      });
    }
    
    // 4. Critical: Consecutive failures (same stack failing 3+ times in a row)
    const consecutiveFailures = [];
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      const builds = (stackInfo.allBuilds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
      let consecutiveCount = 0;
      for (const build of builds) {
        if (build.status === 'failed' || build.status === 'aborted') {
          consecutiveCount++;
        } else {
          break;
        }
      }
      if (consecutiveCount >= 3) {
        consecutiveFailures.push({ stack, count: consecutiveCount });
      }
    });
    if (consecutiveFailures.length > 0) {
      actions.push({
        priority: 'critical',
        title: `${consecutiveFailures.length} stack(s) failing consecutively`,
        description: consecutiveFailures.slice(0, 2).map(s => `${s.stack.toUpperCase()}: ${s.count}x`).join(', '),
        action: 'Urgent: Check infrastructure'
      });
    }
    
    // 5. Info: Stacks not tested recently (no builds in the dataset)
    // These variables are available for future use when we add more detailed diagnostics
    // const allStacksList = backendPdvByStack.summary?.stacksList || [];
    // const stacksWithBuilds = new Set(Object.keys(backendPdvByStack.byStack || {}));
    // const allPipelines = backendPdvByStack.summary?.pipelinesList || [];
    
    // Check for stacks that have very few runs (< 2 runs total)
    const lowActivityStacks = [];
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      const totalBuilds = (stackInfo.allBuilds || []).length;
      if (totalBuilds < 2) {
        lowActivityStacks.push({ stack, runs: totalBuilds });
      }
    });
    if (lowActivityStacks.length > 0) {
      const lowActivityDetails = lowActivityStacks.map(s => `• ${s.stack.toUpperCase()}: ${s.runs} run(s)`).join('\n');
      actions.push({
        priority: 'info',
        title: `${lowActivityStacks.length} stack(s) rarely tested`,
        description: lowActivityStacks.slice(0, 3).map(s => `${s.stack.toUpperCase()}: ${s.runs} run(s)`).join(', '),
        action: 'Increase test coverage',
        tooltip: `Stacks with low test activity:\n${lowActivityDetails}`
      });
    }
    
    // 6. Warning: Low success rate stacks
    const lowSuccessStacks = stackSuccessRates.filter(s => s.successRate < 70);
    if (lowSuccessStacks.length > 0) {
      const lowSuccessDetails = lowSuccessStacks.map(s => 
        `• ${s.stack.toUpperCase()}: ${s.successRate}% (${s.failed} failed out of ${s.total} runs)`
      ).join('\n');
      actions.push({
        priority: 'warning',
        title: `${lowSuccessStacks.length} stack(s) below 70%`,
        description: lowSuccessStacks.slice(0, 3).map(s => `${s.stack.toUpperCase()}: ${s.successRate}%`).join(', '),
        action: 'Review test stability',
        tooltip: `Stacks with low success rate:\n${lowSuccessDetails}`
      });
    }
    
    // 7. Warning: Recurring failures
    if (recurring.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${recurring.length} recurring issue(s)`,
        description: recurring[0]?.reason || 'Multiple failures detected',
        action: 'Address root cause'
      });
    }
    
    // 8. Critical: Service failing across multiple stacks (indicates service-level bug)
    const serviceFailures = {};
    Object.entries(backendPdvByStack.byPipeline || {}).forEach(([pipelineKey, pipelineInfo]) => {
      const failingStacks = [];
      Object.entries(pipelineInfo.stacks || {}).forEach(([stack, stackInfo]) => {
        if (stackInfo.latestStatus && stackInfo.latestStatus !== 'success') {
          failingStacks.push({ stack, status: stackInfo.latestStatus });
        }
      });
      if (failingStacks.length >= 2) {
        serviceFailures[pipelineKey] = {
          displayName: pipelineInfo.displayName || pipelineKey,
          failingStacks
        };
      }
    });
    const serviceFailureCount = Object.keys(serviceFailures).length;
    if (serviceFailureCount > 0) {
      const firstService = Object.values(serviceFailures)[0];
      const serviceDetails = Object.entries(serviceFailures).map(([key, svc]) => 
        `${svc.displayName}:\n${svc.failingStacks.map(s => `  • ${s.stack.toUpperCase()} (${s.status})`).join('\n')}`
      ).join('\n\n');
      actions.push({
        priority: 'critical',
        title: `${serviceFailureCount} service(s) failing across stacks`,
        description: `${firstService.displayName} failing on ${firstService.failingStacks.length} stacks: ${firstService.failingStacks.slice(0, 3).map(s => s.stack.toUpperCase()).join(', ')}`,
        action: 'Service-level bug - investigate code',
        tooltip: `Services failing on multiple stacks:\n\n${serviceDetails}`
      });
    }
    
    // 9. Critical: New regression (previously passing, now failing)
    const newRegressions = [];
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      Object.entries(stackInfo.pipelines || {}).forEach(([pipelineKey, pipelineData]) => {
        const builds = (pipelineData.builds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
        if (builds.length >= 2) {
          const latest = builds[0];
          const previous = builds[1];
          // New regression: latest is failing but previous was passing
          if (latest.status !== 'success' && previous.status === 'success') {
            newRegressions.push({
              stack,
              pipeline: pipelineData.displayName || pipelineKey,
              pipelineKey,
              buildNumber: latest.buildNumber,
              status: latest.status
            });
          }
        }
      });
    });
    if (newRegressions.length > 0) {
      // Build detailed tooltip with all regression info
      const tooltipDetails = newRegressions.map(r => 
        `${r.pipeline} on ${r.stack.toUpperCase()} (Build #${r.buildNumber}, ${r.status})`
      ).join('\n');
      actions.push({
        priority: 'critical',
        title: `${newRegressions.length} new regression(s)`,
        description: newRegressions.slice(0, 2).map(r => `${r.pipeline} on ${r.stack.toUpperCase()}`).join(', '),
        action: 'Recent change broke tests',
        tooltip: tooltipDetails
      });
    }
    
    // 10. Warning: Aborted builds spike (infrastructure/timeout issues)
    const abortedBuilds = allBuilds.filter(b => b.status === 'aborted');
    const abortedPercent = allBuilds.length > 0 ? Math.round((abortedBuilds.length / allBuilds.length) * 100) : 0;
    if (abortedBuilds.length >= 3 || abortedPercent >= 10) {
      const uniqueStacks = [...new Set(abortedBuilds.map(b => b.stack))];
      actions.push({
        priority: 'warning',
        title: `${abortedBuilds.length} aborted build(s) (${abortedPercent}%)`,
        description: `Stacks: ${uniqueStacks.slice(0, 3).map(s => s.toUpperCase()).join(', ')}`,
        action: 'Check infrastructure/timeouts'
      });
    }
    
    // 11. Warning: Single stack all failures (environment issue)
    const stackFailureCounts = {};
    let totalFailures = 0;
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      const failures = (stackInfo.allBuilds || []).filter(b => 
        b.status === 'failed' || b.status === 'unstable' || b.status === 'aborted'
      ).length;
      if (failures > 0) {
        stackFailureCounts[stack] = failures;
        totalFailures += failures;
      }
    });
    const stacksWithFailures = Object.keys(stackFailureCounts);
    if (stacksWithFailures.length === 1 && totalFailures >= 3) {
      const singleStack = stacksWithFailures[0];
      actions.push({
        priority: 'warning',
        title: `All ${totalFailures} failures on ${singleStack.toUpperCase()}`,
        description: 'Single stack failing - likely environment issue',
        action: 'Check stack infrastructure'
      });
    }
    
    // 12. Info: Service coverage gap (some services not tested on certain stacks)
    const allPipelines = backendPdvByStack.stackMatrix?.pipelines || [];
    const allStacksList = backendPdvByStack.stackMatrix?.stacks || [];
    const coverageGaps = [];
    allStacksList.forEach(stack => {
      const stackPipelines = Object.keys(backendPdvByStack.byStack?.[stack]?.pipelines || {});
      const missingPipelines = allPipelines.filter(p => !stackPipelines.includes(p));
      if (missingPipelines.length > 0) {
        coverageGaps.push({ stack, missing: missingPipelines });
      }
    });
    if (coverageGaps.length > 0) {
      const totalMissing = coverageGaps.reduce((sum, g) => sum + g.missing.length, 0);
      const pipelineDisplayNames = backendPdvByStack.stackMatrix?.pipelineDisplayNames || {};
      const coverageDetails = coverageGaps.map(g => 
        `• ${g.stack.toUpperCase()}: missing ${g.missing.map(p => pipelineDisplayNames[p] || p).join(', ')}`
      ).join('\n');
      actions.push({
        priority: 'info',
        title: `${totalMissing} coverage gap(s)`,
        description: `${coverageGaps.length} stack(s) missing some services`,
        action: 'Review test coverage',
        tooltip: `Stacks missing service coverage:\n${coverageDetails}`
      });
    }
    
    // 13. Warning: Flapping tests (alternating pass/fail pattern)
    const flappingServices = [];
    Object.entries(backendPdvByStack.byStack || {}).forEach(([stack, stackInfo]) => {
      Object.entries(stackInfo.pipelines || {}).forEach(([pipelineKey, pipelineData]) => {
        const builds = (pipelineData.builds || []).sort((a, b) => (b.buildNumber || 0) - (a.buildNumber || 0));
        if (builds.length >= 4) {
          // Check for alternating pattern in last 4 builds
          let alternations = 0;
          for (let i = 0; i < builds.length - 1 && i < 4; i++) {
            const current = builds[i].status === 'success';
            const next = builds[i + 1].status === 'success';
            if (current !== next) alternations++;
          }
          // If 3+ alternations in 4 builds, it's flapping
          if (alternations >= 3) {
            flappingServices.push({
              stack,
              pipeline: pipelineData.displayName || pipelineKey
            });
          }
        }
      });
    });
    if (flappingServices.length > 0) {
      actions.push({
        priority: 'warning',
        title: `${flappingServices.length} flapping test(s)`,
        description: flappingServices.slice(0, 2).map(f => `${f.pipeline} on ${f.stack.toUpperCase()}`).join(', '),
        action: 'Tests are unstable - investigate'
      });
    }
    
    // 14. Info: No recent activity (stale data - builds are old)
    const mostRecentBuild = allBuilds.reduce((latest, build) => {
      const buildTime = build.timestampMs || 0;
      return buildTime > (latest?.timestampMs || 0) ? build : latest;
    }, null);
    if (mostRecentBuild) {
      const hoursSinceLastBuild = Math.round((Date.now() - mostRecentBuild.timestampMs) / (1000 * 60 * 60));
      if (hoursSinceLastBuild >= 24) {
        actions.push({
          priority: 'info',
          title: `No builds in ${hoursSinceLastBuild}h`,
          description: `Last build: ${mostRecentBuild.timestamp || 'Unknown'}`,
          action: 'Check if pipelines are running'
        });
      }
    }
    
    // Success: All healthy
    if (actions.length === 0) {
      actions.push({
        priority: 'success',
        title: 'All stacks healthy',
        description: `${backendPdvByStack.summary?.stacksList?.length || 0} stacks passing`,
        action: 'Continue monitoring'
      });
    }
    
    // Sort by priority: critical > warning > info > success
    const priorityOrder = { critical: 0, warning: 1, info: 2, success: 3 };
    actions.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
    
    return actions;
  };

  // TFA Functions
  // isEndpointPdv: true for Endpoint PDV runs (Golden Regression), false for Backend PDV pipelines
  // source: 'main' (default), 'backend-pdv' for Backend PDV pipelines, 'dev' for Dev pipelines
  const fetchTFA = async (pipeline, buildNumber = null, isEndpointPdv = false, source = 'main') => {
    const buildNum = buildNumber || pipeline.lastBuild?.number || pipeline.buildNumber;
    
    // Set loading state and show modal immediately
    setLoadingTfa(true);
    setSelectedPipelineForTfa(pipeline);
    setTfaData({ 
      job: pipeline.name, 
      buildNumber: buildNum,
      loading: true,
      summary: null,
      failedTests: [],
      rootCauses: [],
      recommendations: []
    });
    
    try {
      let endpoint;
      
      // Only use golden-regression endpoint for Endpoint PDV runs (explicit isEndpointPdv=true)
      // DO NOT use pipeline.stack as a condition - Backend PDV pipelines also have stack now
      // The isEndpointPdv flag is the authoritative indicator for which endpoint to use
      if (isEndpointPdv) {
        // Use Golden Regression TFA endpoint for Endpoint PDV runs
        endpoint = `/api/jenkins/golden-regression/${buildNum}/tfa`;
      } else {
        // Use regular TFA endpoint for Backend PDV pipelines and all other pipelines
        const jobName = pipeline.fullName || pipeline.name;
        // Add source parameter for Backend PDV or other sources
        const sourceParam = source !== 'main' ? `?source=${source}` : '';
        endpoint = `/api/jenkins/tfa/${encodeURIComponent(jobName)}/${buildNum}${sourceParam}`;
      }
      
      const response = await fetch(endpoint);
      if (response.ok) {
        const data = await response.json();
        setTfaData({ ...data, job: pipeline.name, buildNumber: buildNum });
      } else {
        // Handle error - extract detailed message from backend
        let errorMessage = 'Failed to fetch test failure analysis';
        let errorType = 'unknown';
        let recommendations = ['Please check if the build has test results.'];
        
        try {
          const errorData = await response.json();
          if (errorData.detail) {
            errorMessage = errorData.detail;
            
            // Determine error type and provide specific recommendations
            if (errorMessage.includes('No test report or console output')) {
              errorType = 'no_data';
              recommendations = [
                'This build has no test report or console output available.',
                'The build may have been aborted before producing any output.',
                'Check the build in Jenkins for more details.'
              ];
            } else if (errorMessage.includes('No test report found')) {
              errorType = 'no_test_report';
              recommendations = [
                'No JUnit test report was found for this build.',
                'The build may have failed before tests could run.',
                'Check if the pipeline is configured to publish test results.'
              ];
            } else if (errorMessage.includes('not configured')) {
              errorType = 'not_configured';
              recommendations = [
                'Jenkins is not properly configured.',
                'Check JENKINS_URL, JENKINS_USER, and JENKINS_TOKEN environment variables.'
              ];
            }
          }
        } catch (parseErr) {
          console.warn('Could not parse error response:', parseErr);
        }
        
        console.error('TFA fetch failed:', response.status, errorMessage);
        setTfaData({ 
          job: pipeline.name, 
          buildNumber: buildNum,
          error: errorMessage,
          errorType: errorType,
          failedTests: [],
          summary: { totalTests: 0, passed: 0, failed: 0, skipped: 0 },
          rootCauses: [],
          recommendations: recommendations
        });
      }
    } catch (err) {
      console.error('TFA fetch failed:', err);
      setTfaData({ 
        job: pipeline.name, 
        buildNumber: buildNum,
        error: 'Unable to connect to the server',
        errorType: 'connection',
        failedTests: [],
        summary: { totalTests: 0, passed: 0, failed: 0, skipped: 0 },
        rootCauses: [],
        recommendations: [
          'Could not connect to the backend server.',
          'Please check if the server is running and try again.'
        ]
      });
    } finally {
      setLoadingTfa(false);
    }
  };

  const closeTFA = () => {
    setTfaData(null);
    setSelectedPipelineForTfa(null);
  };

  // Fetch builds for a specific pipeline
  const fetchPipelineBuilds = async (jobName, numBuilds = 10) => {
    if (pipelineBuilds[jobName]) return; // Already cached
    
    setLoadingBuilds(prev => ({ ...prev, [jobName]: true }));
    try {
      const response = await fetch(
        `/api/jenkins/pipelines/${encodeURIComponent(jobName)}/builds?num_builds=${numBuilds}`
      );
      if (response.ok) {
        const data = await response.json();
        setPipelineBuilds(prev => ({ ...prev, [jobName]: data.builds || [] }));
      }
    } catch (error) {
      console.error(`Failed to fetch builds for ${jobName}:`, error);
    } finally {
      setLoadingBuilds(prev => ({ ...prev, [jobName]: false }));
    }
  };

  // Auto-fetch builds for all PDV pipelines when data is loaded
  useEffect(() => {
    if (viewMode === 'pdv' && pdvSubView === 'backend' && pdvData?.pipelines?.length > 0) {
      pdvData.pipelines.forEach(pipeline => {
        if (pipeline.fullName && !pipelineBuilds[pipeline.fullName]) {
          fetchPipelineBuilds(pipeline.fullName);
        }
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdvData?.pipelines, pdvSubView]);

  // Handle refresh - force fresh data from Jenkins (bypass cache)
  const handleRefresh = () => {
    if (viewMode === 'pdv') {
      if (pdvSubView === 'backend') {
        fetchBackendPDVByStack(true);  // Force refresh bypasses cache
      } else {
        fetchEndpointPDVData(true);  // Force refresh bypasses cache
      }
    } else {
      fetchStackMonitoring(true, false);  // Force refresh with full mode (not lite)
    }
  };

  const fetchStackMonitoring = async (forceRefresh = false, useLiteMode = false) => {
    // For initial load, try to show cached data instantly (no loading spinner)
    const hasExistingData = stackData !== null;
    if (!hasExistingData) {
      setLoading(true);
    }
    setError(null);
    
    // Callback to update UI when fresh data arrives from background fetch
    const handleFreshData = (freshData) => {
      if (freshData && freshData.source !== 'error') {
        const transformedData = transformStackData(freshData);
        if (freshData.cache_age_seconds !== undefined) {
          transformedData.cacheAge = freshData.cache_age_seconds;
          transformedData.cached = freshData.cached;
        }
        transformedData.fromBackgroundRefresh = true;
        setStackData(transformedData);
        console.log('UI updated with fresh background data (restarts:', freshData.total_restarts, ')');
      }
    };
    
    try {
      // Use API service with performance optimizations:
      // - lite mode: skips events/restarts for faster initial load
      // - localStorage caching: instant display on page reload
      // - stale_ok: returns stale data immediately, refreshes in background
      // - onFreshData callback: updates UI when background fetch completes
      const data = await api.getStackMonitoring(
        null,  // stacks - fetch all
        forceRefresh,  // refresh
        useLiteMode,  // lite mode for faster initial load
        !forceRefresh,  // use localStorage cache unless forcing refresh
        handleFreshData  // callback to update UI with fresh data
      );
      
      if (data.source === 'error') {
        // Show error info but fallback to mock data for demo purposes
        console.warn('Stack Monitoring: K8s unavailable, using demo data. Error:', data.message);
        const mockData = getMockStackData();
        mockData.k8sError = data.message;  // Store error for info display
        mockData.isDemo = true;
        setStackData(mockData);
      } else {
        // Transform backend data to frontend format
        const transformedData = transformStackData(data);
        
        // Add cache metadata
        if (data.cache_age_seconds !== undefined) {
          transformedData.cacheAge = data.cache_age_seconds;
          transformedData.cached = data.cached;
        }
        
        // Track if data came from localStorage cache
        if (data.fromLocalCache) {
          transformedData.fromLocalCache = true;
          transformedData.localCacheAge = data.cacheAge;
        }
        
        setStackData(transformedData);
        
        // Stack alerts to Slack - DISABLED (was sending to test_pavan channel)
        // To re-enable, uncomment the following:
        // if (transformedData.alerts && transformedData.alerts.length > 0) {
        //   sendStackAlertsToSlack(transformedData.alerts);
        // }
        
        // If we used lite mode, fetch full data in background
        if (useLiteMode && !forceRefresh) {
          setTimeout(() => {
            fetchStackMonitoring(false, false);  // Full fetch in background
          }, 100);
        }
      }
    } catch (err) {
      setError(err.message);
      // Fallback to mock data on error
      setStackData(getMockStackData());
    } finally {
      setLoading(false);
    }
  };

  // ============ SIDE PANEL FUNCTIONS ============
  
  // Open side panel with deployment details
  // namespace = namespace key for history API matching
  // namespaceFull = actual k8s namespace for kubectl/pod API calls (defaults to namespace if not provided)
  const openDeploymentDetails = useCallback(async (namespace, deployment, stack, namespaceFull = null) => {
    setSelectedDeployment({ namespace, deployment, stack, namespaceFull: namespaceFull || namespace });
    setSidePanelOpen(true);
    setLoadingDetails(true);
    setDetailsError(null);
    setDeploymentDetails(null);
    setPodLogs(null);
    setSelectedPodForLogs(null);
    setStackHistory(null);  // Reset history when selecting a new deployment
    setDetailActiveTab('overview');
    
    try {
      // Extract just the deployment name (remove namespace prefix if present)
      const deploymentName = deployment.includes('/') ? deployment.split('/')[0] : deployment;
      // Use namespaceFull for pod/details API calls (actual K8s namespace)
      const nsForApi = namespaceFull || namespace;
      
      // Progressive loading: First fetch lite data (faster), then full data
      const liteDetails = await api.getDeploymentDetails(nsForApi, deploymentName, stack, true);
      
      if (liteDetails.error) {
        setDetailsError(liteDetails.error);
        setLoadingDetails(false);
        return;
      }
      
      // Show lite data immediately
      setDeploymentDetails({ ...liteDetails, isLite: true });
      setLoadingDetails(false);
      
      // Auto-select first pod for logs if available
      if (liteDetails.pods && liteDetails.pods.length > 0) {
        setSelectedPodForLogs(liteDetails.pods[0].name);
      }
      
      // Fetch full details in background (metrics, events)
      try {
        const fullDetails = await api.getDeploymentDetails(namespace, deploymentName, stack, false);
        if (!fullDetails.error) {
          setDeploymentDetails({ ...fullDetails, isLite: false });
        }
      } catch (bgErr) {
        console.warn('Background fetch for full details failed:', bgErr);
        // Keep lite data, just mark as complete
        setDeploymentDetails(prev => prev ? { ...prev, isLite: false } : prev);
      }
    } catch (err) {
      setDetailsError(err.message);
      setLoadingDetails(false);
    }
  }, []);

  // Close side panel
  const closeSidePanel = useCallback(() => {
    setSidePanelOpen(false);
    setSelectedDeployment(null);
    setDeploymentDetails(null);
    setPodLogs(null);
    setDetailsError(null);
  }, []);

  // Fetch pod logs
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

  // Fetch deployment-specific history for the detail panel
  const fetchDeploymentHistory = useCallback(async (hours = 24) => {
    if (!selectedDeployment) return;
    
    setLoadingHistory(true);
    
    try {
      const { namespace, deployment, stack } = selectedDeployment;
      const deploymentName = deployment.includes('/') ? deployment.split('/')[0] : deployment;
      const history = await api.getDeploymentHistory(namespace, deploymentName, stack, hours);
      setStackHistory(history);
    } catch (err) {
      console.error('Failed to fetch deployment history:', err);
      setStackHistory({ error: err.message, history: [] });
    } finally {
      setLoadingHistory(false);
    }
  }, [selectedDeployment]);

  // Load history when switching to history tab
  useEffect(() => {
    if (detailActiveTab === 'history' && selectedDeployment && !stackHistory && !loadingHistory) {
      fetchDeploymentHistory(24);
    }
  }, [detailActiveTab, selectedDeployment, stackHistory, loadingHistory, fetchDeploymentHistory]);

  // Load logs when switching to logs tab
  useEffect(() => {
    if (detailActiveTab === 'logs' && selectedPodForLogs && !podLogs && !loadingLogs) {
      fetchPodLogs(selectedPodForLogs);
    }
  }, [detailActiveTab, selectedPodForLogs, podLogs, loadingLogs, fetchPodLogs]);

  const getMockStackData = () => {
    return {
        status: 'operational',
        uptime: '99.9%',
        totalStacks: 8,
        healthyStacks: 7,
        warningStacks: 1,
        criticalStacks: 0,
        stacks: [
          {
            id: 'stg01',
            name: 'STG01 Stack',
            region: 'US-West',
            status: 'healthy',
            components: {
              database: { status: 'healthy', responseTime: '5ms' },
              api: { status: 'healthy', responseTime: '12ms' },
              cache: { status: 'healthy', hitRate: '98%' },
              queue: { status: 'healthy', depth: 12 }
            },
            metrics: {
              cpu: 42,
              memory: 58,
              disk: 45,
              network: 'stable'
            },
            lastCheck: '1 min ago'
          },
          {
            id: 'stg02',
            name: 'STG02 Stack',
            region: 'US-East',
            status: 'healthy',
            components: {
              database: { status: 'healthy', responseTime: '6ms' },
              api: { status: 'healthy', responseTime: '15ms' },
              cache: { status: 'healthy', hitRate: '97%' },
              queue: { status: 'healthy', depth: 8 }
            },
            metrics: {
              cpu: 38,
              memory: 52,
              disk: 41,
              network: 'stable'
            },
            lastCheck: '2 min ago'
          },
          {
            id: 'prod01',
            name: 'PROD01 Stack',
            region: 'US-Central',
            status: 'warning',
            components: {
              database: { status: 'healthy', responseTime: '8ms' },
              api: { status: 'warning', responseTime: '85ms' },
              cache: { status: 'healthy', hitRate: '95%' },
              queue: { status: 'healthy', depth: 45 }
            },
            metrics: {
              cpu: 75,
              memory: 82,
              disk: 68,
              network: 'degraded'
            },
            lastCheck: '30 sec ago'
          }
        ],
        alerts: [
          { time: '5 min ago', stack: 'PROD01', severity: 'warning', message: 'API response time increased' },
          { time: '15 min ago', stack: 'STG03', severity: 'info', message: 'Scheduled maintenance completed' }
        ]
      };
  };

  const transformStackData = (backendData) => {
    /**
     * Transform backend data format to frontend format
     * Backend: deployments array with namespace, deployment, stacks
     * Frontend: stacks array with nested components
     * 
     * Now dynamically detects stacks from backend data instead of hardcoding!
     * Also includes stacks from stacks_meta that may not have deployment data
     * (e.g., stacks with connection errors or missing kubeconfig).
     */
    const { 
      deployments = [], 
      timestamp, 
      stacks_meta = {},
      events_by_stack = {},
      total_restarts = 0,
      crash_loop_count = 0,
      auth_status = {},
    } = backendData;
    
    // Dynamically build stacksData from deployments
    // This auto-discovers all stacks present in the data
    const stacksData = {};
    
    deployments.forEach(dep => {
      Object.entries(dep.stacks).forEach(([stack, data]) => {
        // Auto-initialize stack if not seen before
        if (!stacksData[stack]) {
          stacksData[stack] = { deployments: [], healthy: 0, warning: 0, critical: 0 };
        }
        
        stacksData[stack].deployments.push({
          namespace: dep.namespace,
          namespaceFull: data.namespace_full || dep.namespace, // Full namespace for K8s API calls
          deployment: dep.deployment,
          version: data.version,
          status: data.status,
          // New rich data fields
          replicas: data.replicas || { desired: 0, ready: 0, available: 0, unavailable: 0 },
          age: data.age || 'unknown',
          lastUpdated: data.last_updated || null,
          image: data.image || null,
          // Phase 3: Restart counts and crash loop status
          restarts: data.restarts || 0,
          crashLoop: data.crash_loop || false,
        });
        
        // Count status
        if (data.status === 'healthy') {
          stacksData[stack].healthy++;
        } else if (data.status.includes('unhealthy') || data.status.includes('error')) {
          stacksData[stack].critical++;
        } else {
          stacksData[stack].warning++;
        }
      });
    });
    
    // Include ALL configured stacks from stacks_meta, even those without deployment data
    // This ensures stacks with connection errors or missing kubeconfig are shown in comparison view
    Object.keys(stacks_meta).forEach(stackId => {
      if (!stacksData[stackId]) {
        // Stack is configured but has no deployment data (likely connection/auth issue)
        const stackAuthStatus = auth_status[stackId];
        const hasAuthError = stackAuthStatus && stackAuthStatus.status !== 'ok';
        
        stacksData[stackId] = { 
          deployments: [], 
          healthy: 0, 
          warning: 0, 
          critical: 0,
          // Mark as having connection issues if auth status indicates an error
          connectionError: hasAuthError,
          errorMessage: stackAuthStatus?.message || 'No deployment data available'
        };
      }
    });
    
    // Build frontend stacks array with metadata from backend
    const stacks = Object.entries(stacksData).map(([stackId, stackInfo]) => {
      const totalDeps = stackInfo.deployments.length;
      const healthPct = totalDeps > 0 ? Math.round((stackInfo.healthy / totalDeps) * 100) : 0;
      
      // Get metadata from backend (region, description) or use defaults
      const meta = stacks_meta[stackId] || {};
      
      // Calculate aggregate replica stats
      const totalPodsDesired = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.desired || 0), 0);
      const totalPodsReady = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.ready || 0), 0);
      const totalPodsUnavailable = stackInfo.deployments.reduce((sum, d) => sum + (d.replicas?.unavailable || 0), 0);
      
      // Calculate restart stats for this stack
      const stackRestarts = stackInfo.deployments.reduce((sum, d) => sum + (d.restarts || 0), 0);
      const stackCrashLoops = stackInfo.deployments.filter(d => d.crashLoop).length;
      
      // Determine status: connection error takes precedence, then deployment health
      let stackStatus;
      if (stackInfo.connectionError) {
        stackStatus = 'error'; // Stack has connection/auth issues
      } else if (totalDeps === 0) {
        stackStatus = 'unknown'; // Stack is configured but has no deployments
      } else if (stackInfo.critical > 0) {
        stackStatus = 'critical';
      } else if (stackInfo.warning > 0) {
        stackStatus = 'warning';
      } else {
        stackStatus = 'healthy';
      }
      
      return {
        id: stackId,
        name: meta.description || `${stackId.toUpperCase()} Stack`,
        region: meta.region || 'Unknown',
        status: stackStatus,
        components: stackInfo.deployments, // Show all deployments
        totalDeployments: totalDeps,
        healthPercent: healthPct,
        metrics: {
          healthy: stackInfo.healthy,
          warning: stackInfo.warning,
          critical: stackInfo.critical
        },
        // Aggregate pod stats
        pods: {
          desired: totalPodsDesired,
          ready: totalPodsReady,
          unavailable: totalPodsUnavailable,
        },
        // Phase 3: Restart and crash loop stats
        restarts: stackRestarts,
        crashLoops: stackCrashLoops,
        events: events_by_stack[stackId] || [],
        lastCheck: timestamp,
        // Connection error info for UI display
        connectionError: stackInfo.connectionError || false,
        errorMessage: stackInfo.errorMessage || null
      };
    });
    
    // Calculate total stats
    const totalHealthy = Object.values(stacksData).reduce((sum, s) => sum + s.healthy, 0);
    const totalWarning = Object.values(stacksData).reduce((sum, s) => sum + s.warning, 0);
    const totalCritical = Object.values(stacksData).reduce((sum, s) => sum + s.critical, 0);
    const total = totalHealthy + totalWarning + totalCritical;
    
    // Calculate global pod stats
    const globalPodsDesired = stacks.reduce((sum, s) => sum + (s.pods?.desired || 0), 0);
    const globalPodsReady = stacks.reduce((sum, s) => sum + (s.pods?.ready || 0), 0);
    
    return {
      status: totalCritical > 0 ? 'critical' : totalWarning > 0 ? 'warning' : 'operational',
      uptime: total > 0 ? `${Math.round((totalHealthy / total) * 100)}%` : '0%',
      totalStacks: stacks.length,
      healthyStacks: stacks.filter(s => s.status === 'healthy').length,
      warningStacks: stacks.filter(s => s.status === 'warning').length,
      criticalStacks: stacks.filter(s => s.status === 'critical').length,
      stacks: stacks,
      // Global pod stats
      totalPods: {
        desired: globalPodsDesired,
        ready: globalPodsReady,
      },
      totalDeployments: total,
      // Phase 3: Global restart and crash loop stats
      totalRestarts: total_restarts,
      totalCrashLoops: crash_loop_count,
      alerts: (() => {
        const alertsList = [];
        
        // Add crash loop alerts (critical)
        stacks.filter(s => s.crashLoops > 0).slice(0, 3).forEach(s => {
          alertsList.push({
            time: 'Recent',
            stack: s.name,
            severity: 'critical',
            message: `${s.crashLoops} pod(s) in CrashLoopBackOff`
          });
        });
        
        // Add high restart alerts (warning)
        stacks.filter(s => s.totalRestarts > 10).slice(0, 3).forEach(s => {
          alertsList.push({
            time: 'Last hour',
            stack: s.name,
            severity: 'warning',
            message: `High restart count: ${s.totalRestarts} restarts`
          });
        });
        
        // Add critical stack alerts
        stacks.filter(s => s.status === 'critical').slice(0, 3).forEach(s => {
          // Only add if not already covered by crash loops
          if (s.crashLoops === 0) {
            alertsList.push({
              time: 'Recent',
              stack: s.name,
              severity: 'critical',
              message: `${s.critical} deployment(s) unhealthy`
            });
          }
        });
        
        // Add events-based alerts from events_by_stack
        Object.entries(events_by_stack).slice(0, 2).forEach(([stackId, events]) => {
          if (events && events.length > 0) {
            const recentEvents = events.filter(e => 
              e.type === 'Warning' || e.reason === 'BackOff' || e.reason === 'Failed'
            ).slice(0, 2);
            recentEvents.forEach(event => {
              alertsList.push({
                time: event.age || 'Recent',
                stack: stackId.toUpperCase(),
                severity: event.type === 'Warning' ? 'warning' : 'info',
                message: `${event.reason}: ${event.message?.substring(0, 60) || 'Pod event'}`
              });
            });
          }
        });
        
        // If no issues, add a success alert
        if (alertsList.length === 0) {
          const healthyCount = stacks.filter(s => s.status === 'healthy').length;
          alertsList.push({
            time: 'Now',
            stack: 'All Stacks',
            severity: 'success',
            message: `All systems operational - ${healthyCount} stack${healthyCount !== 1 ? 's' : ''} healthy, versions in sync`
          });
        }
        
        return alertsList.slice(0, 10); // Limit to 10 alerts
      })()
    };
  };

  const toggleStackExpansion = (stackId) => {
    setExpandedStacks(prev => ({
      ...prev,
      [stackId]: !prev[stackId]
    }));
  };

  // Toggle collapse/expand for entire stack card
  const toggleStackCardCollapse = (stackId) => {
    setCollapsedStackCards(prev => ({
      ...prev,
      [stackId]: !prev[stackId]
    }));
  };

  // Collapse all stack cards
  const collapseAllStacks = () => {
    if (!stackData?.stacks) return;
    const collapsed = {};
    stackData.stacks.forEach(stack => {
      collapsed[stack.id] = true;
    });
    setCollapsedStackCards(collapsed);
  };

  // Expand all stack cards
  const expandAllStacks = () => {
    setCollapsedStackCards({});
  };

  // Check if all stacks are collapsed
  const areAllStacksCollapsed = () => {
    if (!stackData?.stacks) return false;
    return stackData.stacks.every(stack => collapsedStackCards[stack.id]);
  };

  // Determine if a stack is Production (PE) or Non-Production (NPE)
  const isProductionStack = (stackId) => {
    if (!stackId) return false;
    const id = stackId.toLowerCase();
    // PE stacks start with specific prefixes or are in the PE list
    const pePatterns = ['pe-', 'sjc', 'fra', 'lon', 'sin', 'am2', 'fr4', 'sv5', 'zur', 'mel', 'dfw', 'ruh', 'bom'];
    return pePatterns.some(pattern => id.startsWith(pattern) || id.includes(pattern));
  };

  // Filter stacks based on environment filter (NPE vs Production)
  const filterStacksByEnvironment = (stacks) => {
    if (!stacks || stackEnvFilter === 'all') return stacks;
    
    return stacks.filter(stack => {
      const isProd = isProductionStack(stack.id);
      if (stackEnvFilter === 'production') return isProd;
      if (stackEnvFilter === 'npe') return !isProd;
      return true;
    });
  };

  // Filter deployments based on search query and status filter
  const filterStackDeployments = (components) => {
    if (!components) return [];
    
    return components.filter(comp => {
      // Search filter - match namespace, deployment, or version
      const searchMatch = !stackSearchQuery || 
        comp.namespace?.toLowerCase().includes(stackSearchQuery.toLowerCase()) ||
        comp.deployment?.toLowerCase().includes(stackSearchQuery.toLowerCase()) ||
        comp.version?.toLowerCase().includes(stackSearchQuery.toLowerCase());
      
      // Status filter
      const statusMatch = stackStatusFilter === 'all' || 
        (stackStatusFilter === 'healthy' && comp.status === 'healthy') ||
        (stackStatusFilter === 'warning' && !['healthy', 'critical'].includes(normalizeStatus(comp.status)) && comp.status !== 'healthy') ||
        (stackStatusFilter === 'critical' && (comp.status?.includes('unhealthy') || comp.status?.includes('error')));
      
      return searchMatch && statusMatch;
    });
  };

  // Map stack IDs to actual Kubernetes context names
  const STACK_CONTEXTS = {
    'qa01': 'stork-qa01-mp-npe-iad0-nc1',
    'stg01': 'stork-stg01-mp-iad0-nc4',
    'stg01_mplegacy': 'stork-stg01-mp-iad0-nc4'
  };

  // Copy kubectl command to clipboard
  const copyKubectlCommand = (e, deployment, namespace, stackId) => {
    e.stopPropagation();
    const deploymentName = deployment.split('/')[0];
    const context = STACK_CONTEXTS[stackId] || stackId;
    const command = `kubectl get deployment ${deploymentName} -n ${namespace} -o wide --context=${context}`;
    navigator.clipboard.writeText(command).then(() => {
      setCopiedCommand(`${deployment}-${stackId}`);
      setTimeout(() => setCopiedCommand(null), 2000);
    }).catch(err => {
      console.error('Failed to copy:', err);
      // Fallback: show command in alert
      alert(`Copy this command:\n${command}`);
    });
  };

  // Copy logs command to clipboard
  const copyLogsCommand = (e, deployment, namespace, stackId) => {
    e.stopPropagation();
    const deploymentName = deployment.split('/')[0];
    const context = STACK_CONTEXTS[stackId] || stackId;
    const command = `kubectl logs -l app=${deploymentName} -n ${namespace} --context=${context} --tail=100`;
    navigator.clipboard.writeText(command).then(() => {
      setCopiedCommand(`logs-${deployment}-${stackId}`);
      setTimeout(() => setCopiedCommand(null), 2000);
    }).catch(err => {
      console.error('Failed to copy:', err);
      // Fallback: show command in alert
      alert(`Copy this command:\n${command}`);
    });
  };

  // Get all unique deployments across all stacks for comparison view
  const getComparisonData = () => {
    if (!stackData?.stacks) return [];
    
    const deploymentMap = {};
    
    stackData.stacks.forEach(stack => {
      const filteredComponents = filterStackDeployments(stack.components);
      filteredComponents.forEach(comp => {
        const key = `${comp.namespace}|${comp.deployment}`;
        if (!deploymentMap[key]) {
          deploymentMap[key] = {
            namespace: comp.namespace,
            deployment: comp.deployment,
            stacks: {}
          };
        }
        deploymentMap[key].stacks[stack.id] = {
          version: comp.version,
          status: comp.status,
          replicas: comp.replicas,
          age: comp.age,
        };
      });
    });
    
    return Object.values(deploymentMap);
  };

  // Check if versions match across all stacks
  const hasVersionMismatch = (stacksData) => {
    const versions = Object.values(stacksData).map(s => s.version).filter(v => v && v !== 'error');
    const uniqueVersions = [...new Set(versions)];
    return uniqueVersions.length > 1;
  };

  // Get all issues across stacks for issues-first view
  const getAllIssues = () => {
    if (!stackData?.stacks) return { crashLoops: [], unhealthy: [], events: [] };
    
    const issues = { crashLoops: [], unhealthy: [], events: [] };
    
    stackData.stacks.forEach(stack => {
      // Crash loops
      stack.components?.filter(c => c.crashLoop).forEach(c => {
        issues.crashLoops.push({ ...c, stackId: stack.id, stackName: stack.name });
      });
      
      // Unhealthy deployments
      stack.components?.filter(c => c.status?.includes('unhealthy') || c.status?.includes('error')).forEach(c => {
        issues.unhealthy.push({ ...c, stackId: stack.id, stackName: stack.name });
      });
      
      // Events
      stack.events?.forEach(e => {
        issues.events.push({ ...e, stackId: stack.id, stackName: stack.name });
      });
    });
    
    return issues;
  };

  // Calculate health percentage for progress bar
  const getHealthPercentage = () => {
    if (!stackData) return 0;
    const total = stackData.totalDeployments || 0;
    const healthy = stackData.stacks?.reduce((sum, s) => sum + s.metrics.healthy, 0) || 0;
    return total > 0 ? Math.round((healthy / total) * 100) : 0;
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />;
      case 'warning':
        return <AlertTriangle size={18} style={{ color: 'var(--accent-orange)' }} />;
      case 'critical':
        return <XCircle size={18} style={{ color: 'var(--accent-red)' }} />;
      case 'error':
        return <XCircle size={18} style={{ color: 'var(--text-muted)' }} />;
      case 'unknown':
        return <Activity size={18} style={{ color: 'var(--text-muted)' }} />;
      default:
        return <Activity size={18} style={{ color: 'var(--text-muted)' }} />;
    }
  };

  // Normalize status string to CSS class name (healthy, warning, critical, error, unknown)
  const normalizeStatus = (status) => {
    if (!status) return 'unknown';
    const lowerStatus = status.toLowerCase();
    if (lowerStatus === 'healthy') return 'healthy';
    if (lowerStatus === 'error' || lowerStatus === 'unknown') return lowerStatus;
    if (lowerStatus.includes('unhealthy') || lowerStatus.includes('error') || lowerStatus.includes('critical')) {
      return 'critical';
    }
    if (lowerStatus.includes('warning')) return 'warning';
    return 'warning'; // Default unknown statuses to warning
  };


  const renderPDVMonitoring = () => {
    // Use new backendPdvByStack data
    const data = backendPdvByStack;
    
    // Check if no data or error
    if (!data || data.error) {
      const errorMsg = data?.error || '';
      const isConnectionError = errorMsg.toLowerCase().includes('connection') || 
                                errorMsg.toLowerCase().includes('nodename') ||
                                errorMsg.toLowerCase().includes('network') ||
                                errorMsg.toLowerCase().includes('timeout');
      const isConfigError = errorMsg.toLowerCase().includes('not configured') ||
                           errorMsg.toLowerCase().includes('environment');
      
      return (
        <div className="monitoring-content">
          <div className="info-banner" style={{ 
            background: isConnectionError ? 'rgba(244, 67, 54, 0.1)' : 'rgba(255, 193, 7, 0.1)', 
            border: `1px solid ${isConnectionError ? 'rgba(244, 67, 54, 0.3)' : 'rgba(255, 193, 7, 0.3)'}`, 
            padding: '24px', borderRadius: '12px', textAlign: 'center' 
          }}>
            <AlertTriangle size={40} style={{ color: isConnectionError ? 'var(--accent-red)' : 'var(--accent-orange)', marginBottom: '16px' }} />
            <h3 style={{ margin: '0 0 8px 0', color: 'var(--text-primary)' }}>
              {isConnectionError ? 'Cannot Connect to Jenkins' : 
               isConfigError ? 'Jenkins Not Configured' : 
               'No Backend PDV Pipelines Found'}
            </h3>
            <p style={{ margin: '0 0 16px 0', color: 'var(--text-secondary)', maxWidth: '500px', marginLeft: 'auto', marginRight: 'auto' }}>
              {errorMsg || 'No PDV pipelines found in Jenkins. Check Jenkins connection.'}
            </p>
            {isConnectionError && (
              <div style={{ 
                background: 'var(--bg-secondary)', borderRadius: '8px', padding: '16px', 
                textAlign: 'left', maxWidth: '400px', margin: '0 auto',
                border: '1px solid var(--border-color)'
              }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: '13px', fontWeight: '600' }}>Troubleshooting:</h4>
                <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.8' }}>
                  <li>Check if you're connected to the VPN</li>
                  <li>Verify Jenkins server is accessible from your network</li>
                  <li>Try: <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px' }}>ping jenkins03-int.stg01-mp.nc4.iad0.nsscloud.net</code></li>
                </ul>
              </div>
            )}
          </div>
        </div>
      );
    }

    const { byStack, byPipeline, stackMatrix, summary } = data;
    const sortedStacks = summary?.stacksList || [];
    const sortedPipelines = summary?.pipelinesList || [];
    const overallPassRate = summary?.overallPassRate || 0;
    
    // Filter stacks if a specific stack is selected
    const filteredStacks = selectedStackFilter === 'all' 
      ? sortedStacks 
      : sortedStacks.filter(s => s === selectedStackFilter);

    return (
      <div className="monitoring-content" style={{ padding: '0' }}>
        {/* TFA Modal - Using shared component */}
        <TfaModal
          isOpen={!!tfaData}
          onClose={closeTFA}
          loading={loadingTfa}
          data={tfaData}
          error={tfaData?.error}
          selectedPipeline={selectedPipelineForTfa}
          buildNumber={tfaData?.buildNumber}
        />

        {/* ============ SUMMARY SECTION WITH ACTION ITEMS & RECENT ACTIVITY ============ */}
        {(() => {
          const actionItems = getBackendPDVActionItems();
          const hasCritical = actionItems.some(a => a.priority === 'critical');
          const allHealthy = actionItems.every(a => a.priority === 'success');
          
          return (
            <div style={{ marginBottom: '20px' }}>
              <div style={{ 
                background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)',
                padding: '16px', marginBottom: '16px'
              }}>
                {/* Top Row: Stats + Action Items */}
                <div style={{ display: 'flex', gap: '24px', marginBottom: '16px' }}>
                  {/* Stats Cards - Matching Endpoint PDV style */}
                  <div style={{ display: 'flex', gap: '12px', flexShrink: 0 }}>
                    <div 
                      style={{ 
                        background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.12), rgba(76, 175, 80, 0.04))', 
                        border: '1px solid rgba(76, 175, 80, 0.2)',
                        borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '75px',
                        cursor: 'help'
                      }}
                      title={`${overallPassRate}% = ${summary?.totalPassed || 0} passed / ${summary?.totalRuns || 0} total runs`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-green)' }}>{overallPassRate}%</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Success</div>
                    </div>
                    <div style={{ 
                      background: 'var(--bg-tertiary)', 
                      border: '1px solid var(--border-color)',
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px',
                      cursor: 'help'
                    }}
                    title={`Total build runs across all services and stacks`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-blue)' }}>{summary?.totalRuns || 0}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Runs</div>
                    </div>
                    <div style={{ 
                      background: (summary?.totalFailed || 0) > 0 ? 'linear-gradient(135deg, rgba(244, 67, 54, 0.12), rgba(244, 67, 54, 0.04))' : 'var(--bg-tertiary)', 
                      border: `1px solid ${(summary?.totalFailed || 0) > 0 ? 'rgba(244, 67, 54, 0.2)' : 'var(--border-color)'}`,
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '75px',
                      cursor: 'help'
                    }}
                    title={`${summary?.totalFailed || 0} individual build runs failed out of ${summary?.totalRuns || 0} total`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: (summary?.totalFailed || 0) > 0 ? 'var(--accent-red)' : 'var(--text-muted)' }}>{summary?.totalFailed || 0}</div>
                      <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500', lineHeight: '1.2' }}>Builds<br/>Failed</div>
                    </div>
                    <div style={{ 
                      background: (summary?.failedStacks || 0) > 0 ? 'linear-gradient(135deg, rgba(255, 152, 0, 0.12), rgba(255, 152, 0, 0.04))' : 'var(--bg-tertiary)', 
                      border: `1px solid ${(summary?.failedStacks || 0) > 0 ? 'rgba(255, 152, 0, 0.3)' : 'var(--border-color)'}`,
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '75px',
                      cursor: 'help'
                    }}
                    title={`${summary?.failedStacks || 0} stacks have at least one service with a failing latest build`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: (summary?.failedStacks || 0) > 0 ? 'var(--accent-orange)' : 'var(--text-muted)' }}>{summary?.failedStacks || 0}</div>
                      <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500', lineHeight: '1.2' }}>Stacks<br/>Failing</div>
                    </div>
                    <div style={{ 
                      background: 'var(--bg-tertiary)', 
                      border: '1px solid var(--border-color)',
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px',
                      cursor: 'help'
                    }}
                    title={`Stacks: ${sortedStacks.join(', ').toUpperCase()}`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-purple)' }}>{sortedStacks.length}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Stacks</div>
                    </div>
                    <div style={{ 
                      background: 'var(--bg-tertiary)', 
                      border: '1px solid var(--border-color)',
                      borderRadius: '10px', padding: '10px 16px', textAlign: 'center', minWidth: '65px',
                      cursor: 'help'
                    }}
                    title={`Services: ${(backendPdvByStack?.stackMatrix?.pipelineDisplayNames ? 
                      Object.values(backendPdvByStack.stackMatrix.pipelineDisplayNames).join(', ') : 
                      (summary?.pipelinesList || []).join(', ')) || 'N/A'}`}
                    >
                      <div style={{ fontSize: '22px', fontWeight: '700', color: 'var(--accent-cyan, #00bcd4)' }}>{summary?.totalPipelines || 0}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '500' }}>Services</div>
                    </div>
                  </div>
                  
                  {/* Divider */}
                  <div style={{ width: '1px', background: 'var(--border-color)', alignSelf: 'stretch' }} />
                  
                  {/* Action Items */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                      {allHealthy ? (
                        <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
                      ) : hasCritical ? (
                        <AlertTriangle size={16} style={{ color: 'var(--accent-red)' }} />
                      ) : (
                        <AlertTriangle size={16} style={{ color: 'var(--accent-orange)' }} />
                      )}
                      <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                        Action Items
                      </span>
                      {!allHealthy && (
                        <span style={{ 
                          fontSize: '11px', padding: '3px 8px', borderRadius: '4px', 
                          background: hasCritical ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                          color: hasCritical ? 'var(--accent-red)' : 'var(--accent-orange)',
                          fontWeight: '600'
                        }}>
                          {actionItems.filter(a => a.priority !== 'success').length} issues
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                      {actionItems.map((item, idx) => (
                        <div 
                          key={idx} 
                          style={{ 
                            display: 'flex', alignItems: 'center', gap: '8px', 
                            padding: '8px 12px', borderRadius: '8px',
                            background: item.priority === 'critical' ? 'rgba(244, 67, 54, 0.1)' :
                                       item.priority === 'warning' ? 'rgba(255, 193, 7, 0.1)' :
                                       item.priority === 'info' ? 'rgba(33, 150, 243, 0.1)' :
                                       'rgba(76, 175, 80, 0.1)',
                            border: `1px solid ${item.priority === 'critical' ? 'rgba(244, 67, 54, 0.3)' :
                                                item.priority === 'warning' ? 'rgba(255, 193, 7, 0.3)' :
                                                item.priority === 'info' ? 'rgba(33, 150, 243, 0.3)' :
                                                'rgba(76, 175, 80, 0.3)'}`,
                            cursor: 'help'
                          }}
                          title={item.tooltip || `${item.title}\n${item.description}\n\nAction: ${item.action}`}
                        >
                          {item.priority === 'critical' && <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                          {item.priority === 'warning' && <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />}
                          {item.priority === 'info' && <Info size={14} style={{ color: 'var(--accent-blue)' }} />}
                          {item.priority === 'success' && <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />}
                          <div>
                            <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)' }}>{item.title}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.description}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                
                {/* Bottom Row: Recent Activity Timeline */}
                <div style={{ 
                  borderTop: '1px solid var(--border-color)', paddingTop: '14px',
                  display: 'flex', flexDirection: 'column'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                    <Clock size={16} style={{ color: 'var(--accent-blue)' }} />
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>Recent Activity</span>
                    <div style={{ display: 'flex', gap: '12px', marginLeft: 'auto', fontSize: '11px', color: 'var(--text-muted)' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: '#4CAF50' }} /> Pass
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: '#F44336' }} /> Fail
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: '#FF9800' }} /> Unstable
                      </span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '3px', flexWrap: 'wrap' }}>
                    {backendPdvRecentBuilds.slice(0, 50).map((build, idx) => (
                      <div 
                        key={build.buildNumber || idx}
                        style={{
                          width: '14px', height: '20px', borderRadius: '3px',
                          background: build.status === 'success' ? '#4CAF50' :
                                     build.status === 'failed' ? '#F44336' :
                                     build.status === 'unstable' ? '#FF9800' : '#9E9E9E',
                          cursor: 'pointer', opacity: 0.85,
                          transition: 'transform 0.15s ease'
                        }}
                        title={`${build.jobName || build.name} #${build.buildNumber}\nStack: ${(build.stack || 'N/A').toUpperCase()}\nStatus: ${build.status?.toUpperCase()}`}
                        onClick={() => build.url && window.open(build.url, '_blank')}
                        onMouseEnter={(e) => { e.target.style.transform = 'scaleY(1.3)'; e.target.style.opacity = '1'; }}
                        onMouseLeave={(e) => { e.target.style.transform = 'scale(1)'; e.target.style.opacity = '0.85'; }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* ============ ANALYSIS GRID - 3 columns ============ */}
        {(() => {
          const backendStackSuccessRates = getBackendPDVStackSuccessRates();
          const backendExecutionTimes = getBackendPDVExecutionTimes();
          
          return (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '16px' }}>
              {/* Stack Health Matrix */}
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Server size={16} style={{ color: 'var(--accent-purple)' }} /> Stack Health Matrix
                  </h4>
                </div>
                {renderStackHealthMatrix({
                  stacks: sortedStacks,
                  columns: sortedPipelines,
                  getStatus: (stack, pKey) => stackMatrix?.matrix?.[stack]?.[pKey],
                  getColumnLabel: (pKey) => pKey.substring(0, 2).toUpperCase(),
                  getColumnTitle: (pKey) => stackMatrix?.pipelineDisplayNames?.[pKey] || pKey,
                  getCellTitle: (stack, pKey, status) => 
                    `${stack.toUpperCase()} - ${stackMatrix?.pipelineDisplayNames?.[pKey] || pKey}: ${status || 'No data'}`
                })}
              </div>

              {/* Stack Success Rates */}
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <TrendingUp size={16} style={{ color: 'var(--accent-green)' }} /> Stack Success Rate
                  </h4>
                </div>
                <div style={{ padding: '10px', maxHeight: '260px', overflowY: 'auto' }}>
                  {backendStackSuccessRates.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                      <div style={{ fontSize: '13px' }}>No data available</div>
                    </div>
                  ) : (
                    backendStackSuccessRates.map(({ stack, successRate, failed }) => (
                      <div key={stack} style={{
                        display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px',
                        borderRadius: '6px', marginBottom: '6px',
                        background: failed > 0 ? 'rgba(244, 67, 54, 0.05)' : 'transparent'
                      }}>
                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', 
                          background: successRate === 100 ? 'var(--accent-green)' : successRate >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)' 
                        }} />
                        <span style={{ fontSize: '13px', fontWeight: '500', flex: 1, textTransform: 'uppercase' }}>{stack}</span>
                        <div style={{ width: '60px', height: '6px', background: 'var(--bg-tertiary)', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{ width: `${successRate}%`, height: '100%', background: 'var(--accent-green)', borderRadius: '3px' }} />
                        </div>
                        <span style={{ fontSize: '12px', fontWeight: '600', minWidth: '38px', textAlign: 'right',
                          color: successRate === 100 ? 'var(--accent-green)' : successRate >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)'
                        }}>{successRate}%</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Execution Time per Stack */}
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Timer size={16} style={{ color: 'var(--accent-blue)' }} /> Execution Time
                  </h4>
                </div>
                <div style={{ padding: '10px', maxHeight: '260px', overflowY: 'auto' }}>
                  {backendExecutionTimes.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                      <Clock size={26} style={{ color: 'var(--text-muted)', marginBottom: '8px' }} />
                      <div style={{ fontSize: '13px' }}>No execution data</div>
                    </div>
                  ) : (
                    backendExecutionTimes.map((item, idx) => {
                      const maxDuration = backendExecutionTimes[0]?.avgDuration || 1;
                      const barWidth = (item.avgDuration / maxDuration) * 100;
                      return (
                        <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 8px' }}>
                          <span style={{ fontSize: '12px', fontWeight: '500', width: '60px', textTransform: 'uppercase' }}>{item.stack}</span>
                          <div style={{ flex: 1, height: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
                            <div style={{ width: `${barWidth}%`, height: '100%', borderRadius: '4px',
                              background: item.avgDuration > 30 ? 'var(--accent-orange)' : 'var(--accent-blue)'
                            }} />
                          </div>
                          <span style={{ fontSize: '12px', fontWeight: '600', minWidth: '36px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                            {item.avgDuration}m
                          </span>
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)', minWidth: '50px' }}>
                            ({item.runCount})
                          </span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {/* ============ DETAILS GRID - 2 columns ============ */}
        {(() => {
          const backendRecentFailures = getBackendPDVRecentFailures();
          const { reasons: backendFailureReasons, recurring: backendRecurringFailures } = getBackendPDVFailureReasons();
          
          return (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
              {/* Recent Failures */}
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <XCircle size={16} style={{ color: 'var(--accent-red)' }} /> Recent Failures
                    {backendRecentFailures.length > 0 && (
                      <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '4px', background: 'rgba(244, 67, 54, 0.15)', color: 'var(--accent-red)' }}>
                        {backendRecentFailures.length}
                      </span>
                    )}
                  </h4>
                </div>
                <div style={{ padding: '10px', maxHeight: '220px', overflowY: 'auto' }}>
                  {backendRecentFailures.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                      <CheckCircle size={28} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                      <div style={{ fontSize: '13px' }}>All passing!</div>
                    </div>
                  ) : (
                    backendRecentFailures.slice(0, 6).map((build, idx) => (
                      <div key={idx} style={{ 
                        display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px',
                        background: 'var(--bg-tertiary)', borderRadius: '8px', marginBottom: '8px',
                        cursor: build.url ? 'pointer' : 'default'
                      }} onClick={() => build.url && window.open(build.url, '_blank')}>
                        <XCircle size={16} style={{ color: build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)', flexShrink: 0 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: '13px', fontWeight: '500', textTransform: 'uppercase' }}>{build.stack}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {build.pipelineDisplayName || build.pipelineKey} #{build.buildNumber} • {build.duration || 'N/A'}
                          </div>
                        </div>
                        <span style={{ 
                          fontSize: '10px', padding: '3px 8px', borderRadius: '4px',
                          background: build.status === 'failed' ? 'rgba(244, 67, 54, 0.1)' : 'rgba(255, 152, 0, 0.1)',
                          color: build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)',
                          textTransform: 'uppercase', fontWeight: '600'
                        }}>{build.status}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Failure Reasons */}
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <FileWarning size={16} style={{ color: 'var(--accent-orange)' }} /> Failure Reasons
                    {backendRecurringFailures.length > 0 && (
                      <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '4px', background: 'rgba(244, 67, 54, 0.15)', color: 'var(--accent-red)' }}>
                        {backendRecurringFailures.length} recurring
                      </span>
                    )}
                  </h4>
                </div>
                <div style={{ padding: '10px', maxHeight: '220px', overflowY: 'auto' }}>
                  {backendFailureReasons.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                      <CheckCircle size={28} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                      <div style={{ fontSize: '13px' }}>No failure reasons</div>
                    </div>
                  ) : (
                    backendFailureReasons.slice(0, 5).map((item, idx) => (
                      <div key={idx} style={{ 
                        padding: '10px 12px', background: 'var(--bg-tertiary)', borderRadius: '8px', marginBottom: '8px',
                        borderLeft: item.isRecurring ? '4px solid var(--accent-red)' : '4px solid var(--border-color)'
                      }} title={item.fullReason}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                          {item.isRecurring && <RotateCcw size={13} style={{ color: 'var(--accent-red)' }} />}
                          <span style={{ fontSize: '13px', fontWeight: '500', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.reason}</span>
                          <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '4px',
                            background: item.count >= 3 ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                            color: item.count >= 3 ? 'var(--accent-red)' : 'var(--accent-orange)', fontWeight: '600'
                          }}>×{item.count}</span>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          Affected: {item.stacks.slice(0, 3).map(s => s.toUpperCase()).join(', ')}
                          {item.stacks.length > 3 && ` +${item.stacks.length - 3}`}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {/* ============ VIEW CONTROLS ============ */}
        <div style={{ 
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', 
          marginBottom: '16px', padding: '12px 16px',
          background: 'var(--bg-secondary)', borderRadius: '10px', border: '1px solid var(--border-color)'
        }}>
          {/* View By Toggle */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>View By:</span>
            <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-tertiary)', borderRadius: '8px', padding: '3px' }}>
              <button
                onClick={() => setPdvGroupBy('stack')}
                style={{
                  padding: '6px 14px', borderRadius: '6px', border: 'none',
                  background: pdvGroupBy === 'stack' ? 'var(--accent-purple)' : 'transparent',
                  color: pdvGroupBy === 'stack' ? 'white' : 'var(--text-secondary)',
                  fontSize: '12px', fontWeight: '500', cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                <Server size={12} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                Stack
              </button>
              <button
                onClick={() => setPdvGroupBy('pipeline')}
                style={{
                  padding: '6px 14px', borderRadius: '6px', border: 'none',
                  background: pdvGroupBy === 'pipeline' ? 'var(--accent-blue)' : 'transparent',
                  color: pdvGroupBy === 'pipeline' ? 'white' : 'var(--text-secondary)',
                  fontSize: '12px', fontWeight: '500', cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                <Layers size={12} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                Pipeline
              </button>
            </div>
          </div>

          {/* Stack Filter (only when viewing by stack) */}
          {pdvGroupBy === 'stack' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Filter:</span>
              <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                <button
                  onClick={() => setSelectedStackFilter('all')}
                  style={{
                    padding: '4px 10px', borderRadius: '4px', border: 'none',
                    background: selectedStackFilter === 'all' ? 'var(--accent-purple)' : 'var(--bg-tertiary)',
                    color: selectedStackFilter === 'all' ? 'white' : 'var(--text-secondary)',
                    fontSize: '11px', fontWeight: '500', cursor: 'pointer'
                  }}
                >All</button>
                {sortedStacks.slice(0, 6).map(stack => (
                  <button
                    key={stack}
                    onClick={() => setSelectedStackFilter(stack)}
                    style={{
                      padding: '4px 10px', borderRadius: '4px', border: 'none',
                      background: selectedStackFilter === stack ? 'var(--accent-purple)' : 'var(--bg-tertiary)',
                      color: selectedStackFilter === stack ? 'white' : 'var(--text-secondary)',
                      fontSize: '11px', fontWeight: '500', cursor: 'pointer'
                    }}
                  >{stack.toUpperCase()}</button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ============ VIEW BY STACK ============ */}
        {pdvGroupBy === 'stack' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px' }}>
                <Server size={20} style={{ color: 'var(--accent-purple)' }} /> Backend PDV by Stack
              </h3>
              <button
                onClick={() => {
                  const collapsed = {};
                  filteredStacks.forEach(stack => { collapsed[stack] = false; });
                  setExpandedStacks(collapsed);
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '6px 12px', borderRadius: '6px',
                  background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)', fontSize: '12px', fontWeight: '500',
                  cursor: 'pointer'
                }}
              >
                <ChevronUp size={14} /> Collapse All
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {filteredStacks.map(stackName => {
              const stackData = byStack?.[stackName];
              if (!stackData) return null;
              
              const isStackExpanded = expandedStacks[stackName] !== false;
              const pipelines = Object.values(stackData.pipelines || {});
              const stackSummary = stackData.summary || {};
              
              return (
                <div key={stackName} style={{ 
                  background: 'var(--bg-secondary)', borderRadius: '12px', 
                  border: `1px solid ${stackSummary.failed > 0 ? 'rgba(244, 67, 54, 0.3)' : 'var(--border-color)'}`,
                  overflow: 'hidden'
                }}>
                  {/* Stack Header */}
                  <div 
                    onClick={() => setExpandedStacks(prev => ({ ...prev, [stackName]: !isStackExpanded }))}
                    style={{ 
                      padding: '14px 18px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: stackSummary.failed > 0 ? 'rgba(244, 67, 54, 0.05)' : 'var(--bg-tertiary)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {isStackExpanded ? <ChevronDown size={18} /> : <ChevronUp size={18} style={{ transform: 'rotate(180deg)' }} />}
                      <Server size={18} style={{ color: 'var(--accent-purple)' }} />
                      <span style={{ fontSize: '16px', fontWeight: '600' }}>{stackName.toUpperCase()}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {stackSummary.passed}/{stackSummary.total} Passing
                      </span>
                      <div style={{ 
                        padding: '4px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: '600',
                        background: stackSummary.passRate >= 80 ? 'rgba(76, 175, 80, 0.15)' : 
                                   stackSummary.passRate >= 50 ? 'rgba(255, 193, 7, 0.15)' : 'rgba(244, 67, 54, 0.15)',
                        color: stackSummary.passRate >= 80 ? 'var(--accent-green)' : 
                               stackSummary.passRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)'
                      }}>
                        {stackSummary.passRate}%
                      </div>
                    </div>
                  </div>

                  {/* Stack Content */}
                  {isStackExpanded && (
                    <div style={{ padding: '16px' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            <th style={{ textAlign: 'left', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Pipeline</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Status</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Build #</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Duration</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Last Run</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>History</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pipelines.map((pipeline, idx) => {
                            const latestBuild = pipeline.latestBuild;
                            const builds = pipeline.builds || [];
                            return (
                              <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                                <td style={{ padding: '12px', fontSize: '13px', fontWeight: '500' }}>{pipeline.displayName}</td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  {pipeline.latestStatus === 'success' && <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />}
                                  {pipeline.latestStatus === 'failed' && <XCircle size={18} style={{ color: 'var(--accent-red)' }} />}
                                  {pipeline.latestStatus === 'unstable' && <AlertTriangle size={18} style={{ color: 'var(--accent-orange)' }} />}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  #{latestBuild?.buildNumber || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.duration || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.timestamp || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                                    {builds.slice(0, 5).map((b, i) => (
                                      <div 
                                        key={i}
                                        style={{
                                          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                          padding: '4px', borderRadius: '4px',
                                          background: b.status === 'success' ? 'rgba(76, 175, 80, 0.15)' :
                                                     b.status === 'failed' ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 152, 0, 0.15)',
                                          border: `1px solid ${b.status === 'success' ? 'var(--accent-green)' :
                                                  b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                                          minWidth: '36px'
                                        }}
                                      >
                                        {/* Build number as link */}
                                        <a 
                                          href={b.url || b.buildUrl || `${pipeline.url}/${b.buildNumber}/`}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          style={{ 
                                            fontSize: '9px', fontWeight: '600', textDecoration: 'none',
                                            color: b.status === 'success' ? 'var(--accent-green)' :
                                                   b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'
                                          }}
                                          title={`#${b.buildNumber} - ${b.status} - Click to open in Jenkins`}
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          #{b.buildNumber}
                                        </a>
                                        {/* Action buttons */}
                                        <div style={{ display: 'flex', gap: '2px', flexWrap: 'wrap', justifyContent: 'center' }}>
                                          {/* Open in Jenkins button */}
                                          <a
                                            href={b.url || b.buildUrl || `${pipeline.url}/${b.buildNumber}/`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            style={{
                                              padding: '2px 3px', borderRadius: '3px', border: 'none',
                                              background: 'rgba(33, 150, 243, 0.2)', color: 'var(--accent-blue)',
                                              fontSize: '7px', fontWeight: '600', textDecoration: 'none',
                                              display: 'flex', alignItems: 'center'
                                            }}
                                            title="Open in Jenkins"
                                          >
                                            <ExternalLink size={7} />
                                          </a>
                                          {/* TFA button for failed/unstable builds (not aborted - they don't have test reports) */}
                                          {(b.status === 'failed' || b.status === 'unstable') && b.hasTestReport !== false && (
                                            <button
                                              onClick={(e) => { e.stopPropagation(); fetchTFA({ name: pipeline.displayName, fullName: pipeline.name, ...b }, b.buildNumber, false, 'backend-pdv'); }}
                                              style={{
                                                padding: '2px 3px', borderRadius: '3px', border: 'none',
                                                background: 'rgba(244, 67, 54, 0.2)', color: 'var(--accent-red)',
                                                fontSize: '7px', fontWeight: '600', cursor: 'pointer',
                                                display: 'flex', alignItems: 'center', gap: '1px'
                                              }}
                                              title="Analyze test failures"
                                            >
                                              <Microscope size={7} /> TFA
                                            </button>
                                          )}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
            </div>
          </div>
        )}

        {/* ============ VIEW BY PIPELINE ============ */}
        {pdvGroupBy === 'pipeline' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px' }}>
                <Layers size={20} style={{ color: 'var(--accent-blue)' }} /> Backend PDV by Pipeline
              </h3>
              <button
                onClick={() => {
                  const collapsed = {};
                  sortedPipelines.forEach(pipeline => { collapsed[pipeline] = false; });
                  setExpandedPipelines(collapsed);
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '6px 12px', borderRadius: '6px',
                  background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)', fontSize: '12px', fontWeight: '500',
                  cursor: 'pointer'
                }}
              >
                <ChevronUp size={14} /> Collapse All
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {sortedPipelines.map(pipelineKey => {
                const pipelineData = byPipeline?.[pipelineKey];
                if (!pipelineData) return null;
                
                const isPipelineExpanded = expandedPipelines[pipelineKey] !== false;
                const stacks = Object.entries(pipelineData.stacks || {});
                const pipelineSummary = pipelineData.summary || {};
                
                return (
                  <div key={pipelineKey} style={{ 
                    background: 'var(--bg-secondary)', borderRadius: '12px', 
                    border: `1px solid ${pipelineSummary.failingStacks > 0 ? 'rgba(244, 67, 54, 0.3)' : 'var(--border-color)'}`,
                    overflow: 'hidden'
                  }}>
                  {/* Pipeline Header */}
                  <div 
                    onClick={() => setExpandedPipelines(prev => ({ ...prev, [pipelineKey]: !isPipelineExpanded }))}
                    style={{ 
                      padding: '14px 18px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: pipelineSummary.failingStacks > 0 ? 'rgba(244, 67, 54, 0.05)' : 'var(--bg-tertiary)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {isPipelineExpanded ? <ChevronDown size={18} /> : <ChevronUp size={18} style={{ transform: 'rotate(180deg)' }} />}
                      <Layers size={18} style={{ color: 'var(--accent-blue)' }} />
                      <span style={{ fontSize: '16px', fontWeight: '600' }}>{pipelineData.displayName}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        {pipelineSummary.passingStacks}/{pipelineSummary.totalStacks} Stacks Passing
                      </span>
                      <div style={{ 
                        padding: '4px 12px', borderRadius: '6px', fontSize: '13px', fontWeight: '600',
                        background: pipelineSummary.passRate >= 80 ? 'rgba(76, 175, 80, 0.15)' : 
                                   pipelineSummary.passRate >= 50 ? 'rgba(255, 193, 7, 0.15)' : 'rgba(244, 67, 54, 0.15)',
                        color: pipelineSummary.passRate >= 80 ? 'var(--accent-green)' : 
                               pipelineSummary.passRate >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)'
                      }}>
                        {pipelineSummary.passRate}%
                      </div>
                    </div>
                  </div>

                  {/* Pipeline Content */}
                  {isPipelineExpanded && (
                    <div style={{ padding: '16px' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            <th style={{ textAlign: 'left', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Stack</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Status</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Build #</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Duration</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Last Run</th>
                            <th style={{ textAlign: 'center', padding: '8px 12px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>History</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stacks.map(([stackName, stackInfo], idx) => {
                            const latestBuild = stackInfo.latestBuild;
                            const builds = stackInfo.builds || [];
                            return (
                              <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)' }}>
                                <td style={{ padding: '12px', fontSize: '13px', fontWeight: '600' }}>{stackName.toUpperCase()}</td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  {stackInfo.latestStatus === 'success' && <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />}
                                  {stackInfo.latestStatus === 'failed' && <XCircle size={18} style={{ color: 'var(--accent-red)' }} />}
                                  {stackInfo.latestStatus === 'unstable' && <AlertTriangle size={18} style={{ color: 'var(--accent-orange)' }} />}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  #{latestBuild?.buildNumber || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.duration || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                  {latestBuild?.timestamp || '-'}
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                                    {builds.slice(0, 5).map((b, i) => (
                                      <div 
                                        key={i}
                                        style={{
                                          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                          padding: '4px', borderRadius: '4px',
                                          background: b.status === 'success' ? 'rgba(76, 175, 80, 0.15)' :
                                                     b.status === 'failed' ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 152, 0, 0.15)',
                                          border: `1px solid ${b.status === 'success' ? 'var(--accent-green)' :
                                                  b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                                          minWidth: '36px'
                                        }}
                                      >
                                        {/* Build number as link */}
                                      <a 
                                        href={b.url || b.buildUrl || `${pipelineData.url}/${b.buildNumber}/`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{ 
                                          fontSize: '9px', fontWeight: '600', textDecoration: 'none',
                                          color: b.status === 'success' ? 'var(--accent-green)' :
                                                 b.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'
                                        }}
                                        title={`#${b.buildNumber} - ${b.status} - Click to open in Jenkins`}
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        #{b.buildNumber}
                                      </a>
                                      {/* Action buttons */}
                                      <div style={{ display: 'flex', gap: '2px', flexWrap: 'wrap', justifyContent: 'center' }}>
                                        {/* Open in Jenkins button */}
                                        <a
                                          href={b.url || b.buildUrl || `${pipelineData.url}/${b.buildNumber}/`}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          onClick={(e) => e.stopPropagation()}
                                          style={{
                                            padding: '2px 3px', borderRadius: '3px', border: 'none',
                                            background: 'rgba(33, 150, 243, 0.2)', color: 'var(--accent-blue)',
                                            fontSize: '7px', fontWeight: '600', textDecoration: 'none',
                                            display: 'flex', alignItems: 'center'
                                          }}
                                          title="Open in Jenkins"
                                        >
                                          <ExternalLink size={7} />
                                        </a>
                                        {/* TFA button for failed/unstable builds (not aborted - they don't have test reports) */}
                                        {(b.status === 'failed' || b.status === 'unstable') && b.hasTestReport !== false && (
                                          <button
                                            onClick={(e) => { e.stopPropagation(); fetchTFA({ name: pipelineData.displayName, fullName: pipelineData.name, ...b }, b.buildNumber, false, 'backend-pdv'); }}
                                            style={{
                                              padding: '2px 3px', borderRadius: '3px', border: 'none',
                                              background: 'rgba(244, 67, 54, 0.2)', color: 'var(--accent-red)',
                                              fontSize: '7px', fontWeight: '600', cursor: 'pointer',
                                              display: 'flex', alignItems: 'center', gap: '1px'
                                            }}
                                            title="Analyze test failures"
                                          >
                                            <Microscope size={7} /> TFA
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
            </div>
          </div>
        )}
      </div>
    );
  };

  // Render Endpoint PDV Monitoring
  const renderEndpointPDVMonitoring = () => {
    if (loadingEndpointPdv) {
      return (
        <div className="loading-state" style={{ padding: '60px', textAlign: 'center' }}>
          <RefreshCw size={48} className="spinning" style={{ margin: '0 auto 20px' }} />
          <p>Loading Endpoint PDV Runs data...</p>
        </div>
      );
    }

    if (!endpointPdvData || endpointPdvData.error || (!endpointPdvData.sortedStacks?.length && !endpointPdvData.builds?.length)) {
      const errorMessage = endpointPdvData?.error || 'No Endpoint PDV runs found.';
      const isConfigError = errorMessage.toLowerCase().includes('not configured') || 
                            errorMessage.toLowerCase().includes('environment variable');
      
      return (
        <div className="info-banner" style={{ 
          background: isConfigError ? 'rgba(244, 67, 54, 0.1)' : 'rgba(255, 193, 7, 0.1)', 
          border: `1px solid ${isConfigError ? 'rgba(244, 67, 54, 0.3)' : 'rgba(255, 193, 7, 0.3)'}`, 
          padding: '24px', 
          borderRadius: '12px', 
          textAlign: 'center' 
        }}>
          <AlertTriangle size={40} style={{ color: isConfigError ? 'var(--accent-red)' : 'var(--accent-orange)', marginBottom: '16px' }} />
          <h3 style={{ margin: '0 0 8px 0', color: 'var(--text-primary)' }}>
            {isConfigError ? 'Configuration Required' : 'No Endpoint PDV Data'}
          </h3>
          <p style={{ margin: '0 0 12px 0', color: 'var(--text-secondary)' }}>
            {errorMessage}
          </p>
          {isConfigError && (
            <p style={{ margin: '0', fontSize: '12px', color: 'var(--text-muted)' }}>
              Set the <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px' }}>JENKINS_GOLDEN_REGRESSION_URL</code> environment variable in your backend configuration.
            </p>
          )}
        </div>
      );
    }

    const failedBuilds = getEndpointFailedBuilds();
    const stackSuccessRates = getEndpointStackSuccessRates();
    const actionItems = getEndpointActionItems();
    const { reasons: failureReasons, recurring: recurringFailures } = getEndpointFailureReasons();
    const executionTimes = getEndpointExecutionTimes();
    
    // Endpoint PDV recent builds are fetched via /api/jenkins/recent-builds?pipeline_type=endpoint-pdv
    // and stored in endpointPdvRecentBuilds state (already sorted and aggregated by backend)

    return (
      <div className="monitoring-content" style={{ padding: '0' }}>
        {/* TFA Modal - Using shared component */}
        <TfaModal
          isOpen={!!tfaData}
          onClose={closeTFA}
          loading={loadingTfa}
          data={tfaData}
          error={tfaData?.error}
          selectedPipeline={selectedPipelineForTfa}
          buildNumber={tfaData?.buildNumber}
        />
        
        {/* Top Bar: Action Items + Recent Builds + Summary Stats */}
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'auto 1fr', 
          gap: '12px', 
          marginBottom: '12px',
          alignItems: 'stretch'
        }}>
          {/* Action Items - Compact horizontal chips */}
          <div style={{ 
            background: 'var(--bg-secondary)', 
            borderRadius: '10px', 
            border: '1px solid var(--border-color)',
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            minWidth: '280px'
          }}>
            <Lightbulb size={14} style={{ color: 'var(--accent-yellow)', flexShrink: 0 }} />
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {actionItems.map((item, idx) => (
                <span 
                  key={idx}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: '4px',
                    padding: '4px 8px', borderRadius: '6px', fontSize: '11px', fontWeight: '500',
                    background: item.priority === 'critical' ? 'rgba(244, 67, 54, 0.15)' :
                               item.priority === 'warning' ? 'rgba(255, 193, 7, 0.15)' :
                               item.priority === 'info' ? 'rgba(33, 150, 243, 0.15)' : 'rgba(76, 175, 80, 0.15)',
                    color: item.priority === 'critical' ? 'var(--accent-red)' :
                           item.priority === 'warning' ? 'var(--accent-orange)' :
                           item.priority === 'info' ? 'var(--accent-blue)' : 'var(--accent-green)',
                    cursor: 'help'
                  }}
                  title={`${item.description}\n→ ${item.action}`}
                >
                  {item.priority === 'critical' && <AlertTriangle size={10} />}
                  {item.priority === 'warning' && <AlertTriangle size={10} />}
                  {item.priority === 'info' && <Info size={10} />}
                  {item.priority === 'success' && <CheckCircle size={10} />}
                  {item.title}
                </span>
              ))}
            </div>
          </div>

          {/* Summary Stats */}
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {/* Recent Builds Mini Bar */}
            <div style={{ 
              background: 'var(--bg-secondary)', 
              borderRadius: '10px', 
              border: '1px solid var(--border-color)',
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              flex: 1
            }}>
              <Clock size={14} style={{ color: 'var(--accent-blue)', flexShrink: 0 }} />
              <div style={{ display: 'flex', gap: '2px', flex: 1 }}>
                {endpointPdvRecentBuilds.map((build, idx) => (
                  <div 
                    key={build.buildNumber || idx}
                    className="build-dot-mini"
                    style={{
                      width: '14px', height: '20px', borderRadius: '3px',
                      background: build.status === 'success' ? '#4CAF50' :
                                 build.status === 'failed' ? '#F44336' :
                                 build.status === 'aborted' ? '#FF9800' : '#9E9E9E',
                      cursor: 'pointer',
                      transition: 'transform 0.2s ease, box-shadow 0.2s ease',
                      opacity: 0.85
                    }}
                    title={`Build #${build.buildNumber}\nStack: ${build.stack || 'N/A'}\nStatus: ${build.status?.toUpperCase()}\nTime: ${build.timestamp || 'N/A'}\nDuration: ${build.duration || 'N/A'}\n\nClick to open in Jenkins`}
                    onClick={() => {
                      const url = build.buildUrl || build.url;
                      if (url) window.open(url, '_blank');
                    }}
                    onMouseEnter={(e) => {
                      e.target.style.transform = 'scaleY(1.3) scaleX(1.1)';
                      e.target.style.opacity = '1';
                      e.target.style.boxShadow = '0 0 6px currentColor';
                    }}
                    onMouseLeave={(e) => {
                      e.target.style.transform = 'scale(1)';
                      e.target.style.opacity = '0.85';
                      e.target.style.boxShadow = 'none';
                    }}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', gap: '8px', fontSize: '9px', color: 'var(--text-muted)', flexShrink: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '2px', background: '#4CAF50' }} />P
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '2px', background: '#F44336' }} />F
                </span>
              </div>
            </div>

            {/* Mini Summary Cards - Same style as Backend PDV */}
            <div 
              style={{ 
                background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.12), rgba(76, 175, 80, 0.04))', 
                border: '1px solid rgba(76, 175, 80, 0.2)',
                borderRadius: '10px', padding: '8px 14px', textAlign: 'center', minWidth: '70px',
                cursor: 'help'
              }}
              title={`${endpointPdvData.summary?.successRate || 0}% = ${endpointPdvData.summary?.successCount || endpointPdvData.summary?.successfulBuilds || 0} passed / ${endpointPdvData.summary?.totalBuilds || 0} total runs`}
            >
              <div style={{ fontSize: '18px', fontWeight: '700', color: 'var(--accent-green)' }}>{endpointPdvData.summary?.successRate || 0}%</div>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Success</div>
            </div>
            <div style={{ 
              background: 'var(--bg-secondary)', 
              border: '1px solid var(--border-color)',
              borderRadius: '10px', padding: '8px 14px', textAlign: 'center', minWidth: '60px',
              cursor: 'help'
            }}
            title={`Total build runs across all stacks`}
            >
              <div style={{ fontSize: '18px', fontWeight: '700', color: 'var(--accent-blue)' }}>{endpointPdvData.summary?.totalBuilds || 0}</div>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Runs</div>
            </div>
            <div style={{ 
              background: failedBuilds.length > 0 ? 'linear-gradient(135deg, rgba(244, 67, 54, 0.12), rgba(244, 67, 54, 0.04))' : 'var(--bg-secondary)', 
              border: `1px solid ${failedBuilds.length > 0 ? 'rgba(244, 67, 54, 0.2)' : 'var(--border-color)'}`,
              borderRadius: '10px', padding: '8px 14px', textAlign: 'center', minWidth: '70px',
              cursor: 'help'
            }}
            title={`${failedBuilds.length} individual build runs failed out of ${endpointPdvData.summary?.totalBuilds || 0} total`}
            >
              <div style={{ fontSize: '18px', fontWeight: '700', color: failedBuilds.length > 0 ? 'var(--accent-red)' : 'var(--text-muted)' }}>{failedBuilds.length}</div>
              <div style={{ fontSize: '8px', color: 'var(--text-muted)', textTransform: 'uppercase', lineHeight: '1.2' }}>Builds<br/>Failed</div>
            </div>
            {(() => {
              // Calculate failing stacks count for Endpoint PDV
              const failingStacksCount = endpointPdvData.sortedStacks?.filter(stackName => {
                const builds = endpointPdvData.stackGroups?.[stackName] || [];
                return builds.length > 0 && builds[0]?.status !== 'success';
              }).length || 0;
              // Get names of failing stacks for tooltip
              const failingStackNames = endpointPdvData.sortedStacks?.filter(stackName => {
                const builds = endpointPdvData.stackGroups?.[stackName] || [];
                return builds.length > 0 && builds[0]?.status !== 'success';
              }) || [];
              return (
                <div style={{ 
                  background: failingStacksCount > 0 ? 'linear-gradient(135deg, rgba(255, 152, 0, 0.12), rgba(255, 152, 0, 0.04))' : 'var(--bg-secondary)', 
                  border: `1px solid ${failingStacksCount > 0 ? 'rgba(255, 152, 0, 0.3)' : 'var(--border-color)'}`,
                  borderRadius: '10px', padding: '8px 14px', textAlign: 'center', minWidth: '70px',
                  cursor: 'help'
                }}
                title={failingStacksCount > 0 
                  ? `${failingStacksCount} stacks have a failing latest build: ${failingStackNames.join(', ').toUpperCase()}`
                  : 'All stacks have passing latest builds'}
                >
                  <div style={{ fontSize: '18px', fontWeight: '700', color: failingStacksCount > 0 ? 'var(--accent-orange)' : 'var(--text-muted)' }}>{failingStacksCount}</div>
                  <div style={{ fontSize: '8px', color: 'var(--text-muted)', textTransform: 'uppercase', lineHeight: '1.2' }}>Stacks<br/>Failing</div>
                </div>
              );
            })()}
            <div style={{ 
              background: 'var(--bg-secondary)', 
              border: '1px solid var(--border-color)',
              borderRadius: '10px', padding: '8px 14px', textAlign: 'center', minWidth: '60px',
              cursor: 'help'
            }}
            title={`Stacks: ${(endpointPdvData.sortedStacks || []).join(', ').toUpperCase()}`}
            >
              <div style={{ fontSize: '18px', fontWeight: '700', color: 'var(--accent-purple)' }}>{endpointPdvData.summary?.totalStacks || 0}</div>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Stacks</div>
            </div>
          </div>
        </div>

        {/* Stack Health Matrix - Full width */}
        {(() => {
          // Build endpoint stack health matrix data
          const endpointStacks = endpointPdvData.sortedStacks || [];
          const maxBuildsPerStack = Math.min(
            Math.max(...endpointStacks.map(s => (endpointPdvData.stackGroups?.[s]?.length || 0))),
            10 // Limit to 10 columns max
          );
          const buildIndices = Array.from({ length: maxBuildsPerStack }, (_, i) => i);
          
          // Get the most common build number at each column index for header
          const getMostCommonBuildAtIndex = (idx) => {
            const buildCounts = {};
            endpointStacks.forEach(stack => {
              const builds = endpointPdvData.stackGroups?.[stack] || [];
              if (builds[idx]?.buildNumber) {
                const bn = builds[idx].buildNumber;
                buildCounts[bn] = (buildCounts[bn] || 0) + 1;
              }
            });
            // Return the most common build number
            const sorted = Object.entries(buildCounts).sort((a, b) => b[1] - a[1]);
            return sorted[0] ? parseInt(sorted[0][0]) : null;
          };
          
          return (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
                <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
                  <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Server size={16} style={{ color: 'var(--accent-purple)' }} /> Stack Health Matrix
                  </h4>
                </div>
                {renderStackHealthMatrix({
                  stacks: endpointStacks,
                  columns: buildIndices,
                  getStatus: (stack, buildIdx) => {
                    const builds = endpointPdvData.stackGroups?.[stack] || [];
                    return builds[buildIdx]?.status || null;
                  },
                  getColumnLabel: (buildIdx) => {
                    // Show actual build number from first stack that has data at this index
                    for (const stack of endpointStacks) {
                      const builds = endpointPdvData.stackGroups?.[stack] || [];
                      if (builds[buildIdx]?.buildNumber) {
                        return `#${builds[buildIdx].buildNumber}`;
                      }
                    }
                    return `#${buildIdx + 1}`;
                  },
                  getColumnTitle: (buildIdx) => {
                    const buildNum = getMostCommonBuildAtIndex(buildIdx);
                    return buildNum ? `Build #${buildNum}` : `Column ${buildIdx + 1}`;
                  },
                  getCellTitle: (stack, buildIdx, status) => {
                    const builds = endpointPdvData.stackGroups?.[stack] || [];
                    const build = builds[buildIdx];
                    if (!build) return `${stack.toUpperCase()} - No build`;
                    return `${stack.toUpperCase()} - Build #${build.buildNumber}\nStatus: ${(status || 'unknown').toUpperCase()}\nDuration: ${build.duration || 'N/A'}\nTime: ${build.timestamp || 'N/A'}`;
                  }
                })}
              </div>
            </div>
          );
        })()}

        {/* Stack Insights Row - Quick diagnostic stats */}
        {(() => {
          const stackGroups = endpointPdvData.stackGroups || {};
          const sortedStacks = endpointPdvData.sortedStacks || [];
          
          // Calculate insights
          const stackMetrics = sortedStacks.map(stack => {
            const builds = stackGroups[stack] || [];
            const passedCount = builds.filter(b => b.status === 'success').length;
            const failedCount = builds.filter(b => b.status === 'failed' || b.status === 'unstable').length;
            const successRate = builds.length > 0 ? Math.round((passedCount / builds.length) * 100) : 0;
            
            // Calculate average duration
            const durations = builds
              .map(b => {
                if (!b.duration) return null;
                const match = b.duration.match(/(\d+)/);
                return match ? parseInt(match[1]) : null;
              })
              .filter(d => d !== null);
            const avgDuration = durations.length > 0 ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0;
            
            // Find time since last failure
            const lastFailure = builds.find(b => b.status === 'failed' || b.status === 'unstable');
            const timeSinceFailure = lastFailure?.timestampMs 
              ? Math.round((Date.now() - lastFailure.timestampMs) / (1000 * 60 * 60)) 
              : null;
            
            // Calculate volatility (number of status changes)
            let volatility = 0;
            for (let i = 0; i < builds.length - 1; i++) {
              if (builds[i].status !== builds[i + 1].status) volatility++;
            }
            
            // Streak: consecutive passes or failures
            let currentStreak = 0;
            let streakType = null;
            for (const build of builds) {
              if (streakType === null) {
                streakType = build.status === 'success' ? 'pass' : 'fail';
                currentStreak = 1;
              } else if ((build.status === 'success' && streakType === 'pass') || 
                         (build.status !== 'success' && streakType === 'fail')) {
                currentStreak++;
              } else {
                break;
              }
            }
            
            return {
              stack,
              builds: builds.length,
              successRate,
              avgDuration,
              timeSinceFailure,
              volatility,
              streak: { count: currentStreak, type: streakType },
              lastBuildTime: builds[0]?.timestampMs || 0
            };
          });
          
          // Find top performers
          const bestStack = stackMetrics.reduce((best, curr) => 
            curr.successRate > (best?.successRate || 0) ? curr : best, null);
          const worstStack = stackMetrics.reduce((worst, curr) => 
            curr.successRate < (worst?.successRate || 100) && curr.builds > 0 ? curr : worst, null);
          const fastestStack = stackMetrics.reduce((fastest, curr) => 
            curr.avgDuration > 0 && curr.avgDuration < (fastest?.avgDuration || 999) ? curr : fastest, null);
          const slowestStack = stackMetrics.reduce((slowest, curr) => 
            curr.avgDuration > (slowest?.avgDuration || 0) ? curr : slowest, null);
          const mostStable = stackMetrics.reduce((stable, curr) => 
            curr.volatility < (stable?.volatility || 999) && curr.builds >= 3 ? curr : stable, null);
          const mostVolatile = stackMetrics.reduce((volatile, curr) => 
            curr.volatility > (volatile?.volatility || 0) ? curr : volatile, null);
          
          // Longest passing streak
          const longestPassStreak = stackMetrics
            .filter(m => m.streak.type === 'pass')
            .reduce((best, curr) => curr.streak.count > (best?.streak?.count || 0) ? curr : best, null);
          
          // Calculate build velocity (builds in last 24h)
          const last24h = Date.now() - (24 * 60 * 60 * 1000);
          let buildsLast24h = 0;
          Object.values(stackGroups).forEach(builds => {
            buildsLast24h += (builds || []).filter(b => (b.timestampMs || 0) > last24h).length;
          });
          
          // Overall health score
          const overallSuccessRate = stackMetrics.length > 0
            ? Math.round(stackMetrics.reduce((sum, m) => sum + m.successRate, 0) / stackMetrics.length)
            : 0;
          
          return (
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(4, 1fr)', 
              gap: '12px', 
              marginBottom: '16px' 
            }}>
              {/* Build Velocity */}
              <div style={{ 
                background: 'linear-gradient(135deg, rgba(33, 150, 243, 0.1), rgba(33, 150, 243, 0.02))', 
                borderRadius: '12px', 
                border: '1px solid rgba(33, 150, 243, 0.2)',
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Activity size={16} style={{ color: 'var(--accent-blue)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Build Velocity</span>
                </div>
                <div style={{ fontSize: '28px', fontWeight: '700', color: 'var(--accent-blue)', marginBottom: '4px' }}>
                  {buildsLast24h}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>builds in last 24h</div>
              </div>
              
              {/* Best Performer */}
              <div style={{ 
                background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.1), rgba(76, 175, 80, 0.02))', 
                borderRadius: '12px', 
                border: '1px solid rgba(76, 175, 80, 0.2)',
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Award size={16} style={{ color: 'var(--accent-green)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Best Performer</span>
                </div>
                <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--accent-green)', textTransform: 'uppercase', marginBottom: '4px' }}>
                  {bestStack?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {bestStack ? `${bestStack.successRate}% success rate` : 'No data'}
                </div>
              </div>
              
              {/* Needs Attention */}
              <div style={{ 
                background: worstStack && worstStack.successRate < 70 
                  ? 'linear-gradient(135deg, rgba(244, 67, 54, 0.1), rgba(244, 67, 54, 0.02))' 
                  : 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: `1px solid ${worstStack && worstStack.successRate < 70 ? 'rgba(244, 67, 54, 0.2)' : 'var(--border-color)'}`,
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <AlertTriangle size={16} style={{ color: worstStack && worstStack.successRate < 70 ? 'var(--accent-red)' : 'var(--text-muted)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Needs Attention</span>
                </div>
                <div style={{ 
                  fontSize: '16px', fontWeight: '700', textTransform: 'uppercase', marginBottom: '4px',
                  color: worstStack && worstStack.successRate < 70 ? 'var(--accent-red)' : 'var(--text-muted)'
                }}>
                  {worstStack && worstStack.successRate < 100 ? worstStack.stack : 'None'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {worstStack && worstStack.successRate < 100 ? `${worstStack.successRate}% success rate` : 'All stacks healthy'}
                </div>
              </div>
              
              {/* Winning Streak */}
              <div style={{ 
                background: longestPassStreak && longestPassStreak.streak.count >= 5
                  ? 'linear-gradient(135deg, rgba(156, 39, 176, 0.1), rgba(156, 39, 176, 0.02))' 
                  : 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: `1px solid ${longestPassStreak && longestPassStreak.streak.count >= 5 ? 'rgba(156, 39, 176, 0.2)' : 'var(--border-color)'}`,
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Zap size={16} style={{ color: longestPassStreak ? 'var(--accent-purple)' : 'var(--text-muted)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Winning Streak</span>
                </div>
                <div style={{ 
                  fontSize: '16px', fontWeight: '700', textTransform: 'uppercase', marginBottom: '4px',
                  color: longestPassStreak ? 'var(--accent-purple)' : 'var(--text-muted)'
                }}>
                  {longestPassStreak?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {longestPassStreak ? `${longestPassStreak.streak.count} consecutive passes` : 'No streak'}
                </div>
              </div>
              
              {/* Fastest Stack */}
              <div style={{ 
                background: 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: '1px solid var(--border-color)',
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Zap size={16} style={{ color: 'var(--accent-green)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Fastest Stack</span>
                </div>
                <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--accent-green)', textTransform: 'uppercase', marginBottom: '4px' }}>
                  {fastestStack?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {fastestStack ? `~${fastestStack.avgDuration}m avg` : 'No data'}
                </div>
              </div>
              
              {/* Slowest Stack */}
              <div style={{ 
                background: slowestStack && slowestStack.avgDuration > 30
                  ? 'linear-gradient(135deg, rgba(255, 152, 0, 0.1), rgba(255, 152, 0, 0.02))' 
                  : 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: `1px solid ${slowestStack && slowestStack.avgDuration > 30 ? 'rgba(255, 152, 0, 0.2)' : 'var(--border-color)'}`,
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Clock size={16} style={{ color: slowestStack && slowestStack.avgDuration > 30 ? 'var(--accent-orange)' : 'var(--text-muted)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Slowest Stack</span>
                </div>
                <div style={{ 
                  fontSize: '16px', fontWeight: '700', textTransform: 'uppercase', marginBottom: '4px',
                  color: slowestStack && slowestStack.avgDuration > 30 ? 'var(--accent-orange)' : 'var(--text-muted)'
                }}>
                  {slowestStack?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {slowestStack ? `~${slowestStack.avgDuration}m avg` : 'No data'}
                </div>
              </div>
              
              {/* Most Stable */}
              <div style={{ 
                background: 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: '1px solid var(--border-color)',
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Shield size={16} style={{ color: 'var(--accent-blue)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Most Stable</span>
                </div>
                <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--accent-blue)', textTransform: 'uppercase', marginBottom: '4px' }}>
                  {mostStable?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {mostStable ? `${mostStable.volatility} status changes` : 'No data'}
                </div>
              </div>
              
              {/* Most Volatile */}
              <div style={{ 
                background: mostVolatile && mostVolatile.volatility >= 4
                  ? 'linear-gradient(135deg, rgba(255, 193, 7, 0.1), rgba(255, 193, 7, 0.02))' 
                  : 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: `1px solid ${mostVolatile && mostVolatile.volatility >= 4 ? 'rgba(255, 193, 7, 0.2)' : 'var(--border-color)'}`,
                padding: '14px 16px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <Activity size={16} style={{ color: mostVolatile && mostVolatile.volatility >= 4 ? 'var(--accent-yellow)' : 'var(--text-muted)' }} />
                  <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-secondary)' }}>Most Volatile</span>
                </div>
                <div style={{ 
                  fontSize: '16px', fontWeight: '700', textTransform: 'uppercase', marginBottom: '4px',
                  color: mostVolatile && mostVolatile.volatility >= 4 ? 'var(--accent-yellow)' : 'var(--text-muted)'
                }}>
                  {mostVolatile?.stack || 'N/A'}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {mostVolatile ? `${mostVolatile.volatility} status changes` : 'No data'}
                </div>
              </div>
            </div>
          );
        })()}

        {/* Second Row - Stack Success Rates + Execution Time */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
          {/* Stack Success Rates */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
              <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <BarChart3 size={16} style={{ color: 'var(--accent-green)' }} /> Stack Success Rates
              </h4>
            </div>
            <div style={{ padding: '10px', maxHeight: '260px', overflowY: 'auto' }}>
              {stackSuccessRates.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                  <BarChart3 size={26} style={{ color: 'var(--text-muted)', marginBottom: '8px' }} />
                  <div style={{ fontSize: '13px' }}>No stack data</div>
                </div>
              ) : (
                stackSuccessRates.map(({ stack, successRate, passed, failed }, idx) => (
                  <div key={idx} style={{
                    display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px',
                    borderRadius: '6px', marginBottom: '6px',
                    background: failed > 0 ? 'rgba(244, 67, 54, 0.05)' : 'transparent'
                  }}>
                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', 
                      background: successRate === 100 ? 'var(--accent-green)' : successRate >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)' 
                    }} />
                    <span style={{ fontSize: '13px', fontWeight: '500', flex: 1, textTransform: 'uppercase' }}>{stack}</span>
                    <div style={{ width: '60px', height: '6px', background: 'var(--bg-tertiary)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: `${successRate}%`, height: '100%', background: 'var(--accent-green)', borderRadius: '3px' }} />
                    </div>
                    <span style={{ fontSize: '12px', fontWeight: '600', minWidth: '38px', textAlign: 'right',
                      color: successRate === 100 ? 'var(--accent-green)' : successRate >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)'
                    }}>{successRate}%</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Execution Time per Stack */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
              <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Timer size={16} style={{ color: 'var(--accent-blue)' }} /> Execution Time
              </h4>
            </div>
            <div style={{ padding: '10px', maxHeight: '260px', overflowY: 'auto' }}>
              {executionTimes.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                  <Clock size={26} style={{ color: 'var(--text-muted)', marginBottom: '8px' }} />
                  <div style={{ fontSize: '13px' }}>No execution data</div>
                </div>
              ) : (
                executionTimes.map((item, idx) => {
                  const maxDuration = executionTimes[0]?.avgDuration || 1;
                  const barWidth = (item.avgDuration / maxDuration) * 100;
                  return (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '500', width: '60px', textTransform: 'uppercase' }}>{item.stack}</span>
                      <div style={{ flex: 1, height: '8px', background: 'var(--bg-tertiary)', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: `${barWidth}%`, height: '100%', borderRadius: '4px',
                          background: item.avgDuration > 30 ? 'var(--accent-orange)' : 'var(--accent-blue)'
                        }} />
                      </div>
                      <span style={{ fontSize: '12px', fontWeight: '600', minWidth: '36px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                        {item.avgDuration}m
                      </span>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', minWidth: '50px' }}>
                        ({item.runCount})
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Third Row - Recent Failures and Failure Reasons */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
          {/* Recent Failures */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
              <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <XCircle size={16} style={{ color: 'var(--accent-red)' }} /> Recent Failures
              </h4>
            </div>
            <div style={{ padding: '10px', maxHeight: '220px', overflowY: 'auto' }}>
              {failedBuilds.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                  <CheckCircle size={24} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                  <div style={{ fontSize: '12px' }}>All passing!</div>
                </div>
              ) : (
                failedBuilds.slice(0, 8).map((build, idx) => (
                  <div key={idx} style={{ 
                    display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 10px',
                    background: 'var(--bg-tertiary)', borderRadius: '6px', marginBottom: '6px',
                    cursor: build.url ? 'pointer' : 'default'
                  }} onClick={() => build.url && window.open(build.url, '_blank')}>
                    <XCircle size={14} style={{ color: build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)', flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '12px', fontWeight: '500', textTransform: 'uppercase' }}>{build.stack}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>#{build.buildNumber} • {build.duration || 'N/A'}</div>
                    </div>
                    <span style={{ 
                      fontSize: '9px', padding: '2px 6px', borderRadius: '4px',
                      background: build.status === 'failed' ? 'rgba(244, 67, 54, 0.1)' : 'rgba(255, 152, 0, 0.1)',
                      color: build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)',
                      textTransform: 'uppercase', fontWeight: '600'
                    }}>{build.status}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Failure Reasons */}
          <div style={{ background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)', overflow: 'hidden' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-tertiary)' }}>
              <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileWarning size={16} style={{ color: 'var(--accent-orange)' }} /> Failure Reasons
                {recurringFailures.length > 0 && (
                  <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(244, 67, 54, 0.15)', color: 'var(--accent-red)' }}>
                    {recurringFailures.length} recurring
                  </span>
                )}
              </h4>
            </div>
            <div style={{ padding: '10px', maxHeight: '220px', overflowY: 'auto' }}>
              {failureReasons.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--text-muted)' }}>
                  <CheckCircle size={24} style={{ color: 'var(--accent-green)', marginBottom: '8px' }} />
                  <div style={{ fontSize: '12px' }}>No failure reasons</div>
                </div>
              ) : (
                failureReasons.slice(0, 6).map((item, idx) => (
                  <div key={idx} style={{ 
                    padding: '8px 10px', background: 'var(--bg-tertiary)', borderRadius: '6px', marginBottom: '6px',
                    borderLeft: item.isRecurring ? '3px solid var(--accent-red)' : '3px solid var(--border-color)'
                  }} title={item.fullReason}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                      {item.isRecurring && <RotateCcw size={11} style={{ color: 'var(--accent-red)' }} />}
                      <span style={{ fontSize: '11px', fontWeight: '500', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.reason}</span>
                      <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px',
                        background: item.count >= 3 ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                        color: item.count >= 3 ? 'var(--accent-red)' : 'var(--accent-orange)', fontWeight: '600'
                      }}>×{item.count}</span>
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                      Affected: {item.stacks.slice(0, 3).map(s => s.toUpperCase()).join(', ')}
                      {item.stacks.length > 3 && ` +${item.stacks.length - 3}`}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* View By Toggle and Filter - Same as Backend PDV */}
        {endpointPdvData.sortedStacks && endpointPdvData.sortedStacks.length > 0 && (
          <div style={{ 
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', 
            marginTop: '16px', marginBottom: '16px', padding: '12px 16px',
            background: 'var(--bg-secondary)', borderRadius: '10px', border: '1px solid var(--border-color)'
          }}>
            {/* View By Toggle */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>View By:</span>
              <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-tertiary)', borderRadius: '8px', padding: '3px' }}>
                <button
                  onClick={() => setEndpointGroupBy('stack')}
                  style={{
                    padding: '6px 14px', borderRadius: '6px', border: 'none',
                    background: endpointGroupBy === 'stack' ? 'var(--accent-purple)' : 'transparent',
                    color: endpointGroupBy === 'stack' ? 'white' : 'var(--text-secondary)',
                    fontSize: '12px', fontWeight: '500', cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <Server size={12} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                  Stack
                </button>
                <button
                  onClick={() => setEndpointGroupBy('builds')}
                  style={{
                    padding: '6px 14px', borderRadius: '6px', border: 'none',
                    background: endpointGroupBy === 'builds' ? 'var(--accent-blue)' : 'transparent',
                    color: endpointGroupBy === 'builds' ? 'white' : 'var(--text-secondary)',
                    fontSize: '12px', fontWeight: '500', cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <Layers size={12} style={{ marginRight: '6px', verticalAlign: 'middle' }} />
                  All Builds
                </button>
              </div>
            </div>

            {/* Stack Filter */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Filter:</span>
              <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                <button
                  onClick={() => setEndpointStackFilter('all')}
                  style={{
                    padding: '4px 10px', borderRadius: '4px', border: 'none',
                    background: endpointStackFilter === 'all' ? 'var(--accent-purple)' : 'var(--bg-tertiary)',
                    color: endpointStackFilter === 'all' ? 'white' : 'var(--text-secondary)',
                    fontSize: '11px', fontWeight: '500', cursor: 'pointer'
                  }}
                >All</button>
                {endpointPdvData.sortedStacks.slice(0, 7).map(stack => (
                  <button
                    key={stack}
                    onClick={() => setEndpointStackFilter(stack)}
                    style={{
                      padding: '4px 10px', borderRadius: '4px', border: 'none',
                      background: endpointStackFilter === stack ? 'var(--accent-purple)' : 'var(--bg-tertiary)',
                      color: endpointStackFilter === stack ? 'white' : 'var(--text-secondary)',
                      fontSize: '11px', fontWeight: '500', cursor: 'pointer'
                    }}
                  >{stack}</button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ============ VIEW BY STACK ============ */}
        {endpointGroupBy === 'stack' && endpointPdvData.sortedStacks && endpointPdvData.sortedStacks.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px' }}>
                <Layers size={20} style={{ color: 'var(--accent-purple)' }} /> Endpoint PDV Runs by Stack
              </h3>
              <button
                onClick={() => {
                  const collapsed = {};
                  endpointPdvData.sortedStacks.forEach(stack => { collapsed[stack] = false; });
                  setExpandedStacks(collapsed);
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '6px 12px', borderRadius: '6px',
                  background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)', fontSize: '12px', fontWeight: '500',
                  cursor: 'pointer'
                }}
              >
                <ChevronUp size={14} /> Collapse All
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {endpointPdvData.sortedStacks
                .filter(stackName => endpointStackFilter === 'all' || stackName === endpointStackFilter)
                .map(stackName => {
                const stackBuilds = endpointPdvData.stackGroups?.[stackName] || [];
                const isExpanded = expandedStacks[stackName] !== false;
                const successCount = stackBuilds.filter(b => b.status === 'success').length;
                const failedCount = stackBuilds.filter(b => b.status === 'failed' || b.status === 'unstable' || b.status === 'aborted').length;
                
                return (
                  <div key={stackName} style={{
                    background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
                    borderRadius: '10px', overflow: 'hidden'
                  }}>
                    <div 
                      onClick={() => setExpandedStacks(prev => ({ ...prev, [stackName]: !isExpanded }))}
                      style={{
                        padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        cursor: 'pointer', background: failedCount > 0 ? 'rgba(244, 67, 54, 0.05)' : 'rgba(76, 175, 80, 0.05)'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                        <span style={{ fontWeight: '600', fontSize: '13px' }}>{stackName}</span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>({stackBuilds.length} runs)</span>
                      </div>
                      <div style={{ display: 'flex', gap: '10px' }}>
                        <span style={{ color: 'var(--accent-green)', fontSize: '12px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <CheckCircle size={14} />{successCount}
                        </span>
                        {failedCount > 0 && (
                          <span style={{ color: 'var(--accent-red)', fontSize: '12px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <XCircle size={14} />{failedCount}
                          </span>
                        )}
                      </div>
                    </div>
                    {isExpanded && stackBuilds.length > 0 && (
                      <div style={{ padding: '10px', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '8px' }}>
                        {stackBuilds.slice(0, 10).map((build, idx) => (
                          <div 
                            key={idx} 
                            style={{
                              background: build.status === 'success' ? 'rgba(76, 175, 80, 0.15)' :
                                         build.status === 'failed' ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 152, 0, 0.15)',
                              border: `2px solid ${build.status === 'success' ? 'var(--accent-green)' :
                                      build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                              borderRadius: '8px', padding: '10px', textAlign: 'center',
                              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px'
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              {build.status === 'success' && <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />}
                              {build.status === 'failed' && <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                              {(build.status === 'aborted' || build.status === 'unstable') && <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />}
                              <a 
                                href={build.buildUrl || build.url} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-primary)', textDecoration: 'none' }}
                                onClick={(e) => e.stopPropagation()}
                              >
                                #{build.buildNumber}
                              </a>
                            </div>
                            <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{build.duration || 'N/A'}</div>
                            {/* Action buttons */}
                            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', justifyContent: 'center' }}>
                              {/* Open in Jenkins button - always visible */}
                              {(build.buildUrl || (endpointPdvData?.jenkinsUrl && build.buildNumber)) && (
                                <a
                                  href={build.buildUrl || `${endpointPdvData.jenkinsUrl}/${build.buildNumber}/`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                  style={{
                                    display: 'flex', alignItems: 'center', gap: '3px',
                                    padding: '3px 6px', borderRadius: '4px', border: 'none',
                                    background: 'rgba(33, 150, 243, 0.15)',
                                    color: 'var(--accent-blue)',
                                    fontSize: '9px', fontWeight: '600',
                                    textDecoration: 'none'
                                  }}
                                  title="Open in Jenkins"
                                >
                                  <ExternalLink size={9} /> Jenkins
                                </a>
                              )}
                              {/* Analyze button for failed/unstable builds with test reports */}
                              {(build.status === 'failed' || build.status === 'unstable') && build.hasTestReport && (
                                <button
                                  disabled={loadingTfa && tfaData?.buildNumber === build.buildNumber}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    fetchTFA({ name: `Endpoint PDV - ${stackName}`, stack: stackName, url: endpointPdvData?.jenkinsUrl }, build.buildNumber, true);
                                  }}
                                  style={{
                                    display: 'flex', alignItems: 'center', gap: '3px',
                                    padding: '3px 6px', borderRadius: '4px', border: 'none',
                                    background: 'rgba(244, 67, 54, 0.2)',
                                    color: 'var(--accent-red)',
                                    cursor: loadingTfa && tfaData?.buildNumber === build.buildNumber ? 'wait' : 'pointer',
                                    fontSize: '9px', fontWeight: '600',
                                    opacity: loadingTfa && tfaData?.buildNumber === build.buildNumber ? 0.7 : 1
                                  }}
                                >
                                  {loadingTfa && tfaData?.buildNumber === build.buildNumber ? (
                                    <><Loader size={9} className="spin" /> ...</>
                                  ) : (
                                    <><Search size={9} /> TFA</>
                                  )}
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ============ VIEW BY ALL BUILDS ============ */}
        {endpointGroupBy === 'builds' && endpointPdvData.sortedStacks && endpointPdvData.sortedStacks.length > 0 && (() => {
          // Collect all builds from all stacks, filter by selected stack if needed
          const allBuilds = [];
          endpointPdvData.sortedStacks
            .filter(stackName => endpointStackFilter === 'all' || stackName === endpointStackFilter)
            .forEach(stackName => {
              const stackBuilds = endpointPdvData.stackGroups?.[stackName] || [];
              stackBuilds.forEach(build => {
                allBuilds.push({ ...build, stackName });
              });
            });
          // Sort by timestamp (most recent first)
          allBuilds.sort((a, b) => (b.timestampMs || 0) - (a.timestampMs || 0));
          
          const successCount = allBuilds.filter(b => b.status === 'success').length;
          const passRate = allBuilds.length > 0 ? Math.round((successCount / allBuilds.length) * 100) : 0;
          
          return (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px' }}>
                  <Layers size={20} style={{ color: 'var(--accent-blue)' }} /> 
                  All Builds {endpointStackFilter !== 'all' && `(${endpointStackFilter})`}
                </h3>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                    {successCount}/{allBuilds.length} Passing
                  </span>
                  <span style={{ 
                    fontSize: '14px', fontWeight: '700',
                    color: passRate >= 90 ? 'var(--accent-green)' : passRate >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)'
                  }}>
                    {passRate}%
                  </span>
                </div>
              </div>
              
              {/* Builds Grid */}
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', 
                gap: '10px',
                background: 'var(--bg-secondary)', 
                borderRadius: '12px', 
                border: '1px solid var(--border-color)',
                padding: '16px'
              }}>
                {allBuilds.slice(0, 50).map((build, idx) => (
                  <div 
                    key={`${build.stackName}-${build.buildNumber}-${idx}`}
                    style={{
                      background: build.status === 'success' ? 'rgba(76, 175, 80, 0.12)' :
                                 build.status === 'failed' ? 'rgba(244, 67, 54, 0.12)' : 'rgba(255, 152, 0, 0.12)',
                      border: `2px solid ${build.status === 'success' ? 'var(--accent-green)' :
                              build.status === 'failed' ? 'var(--accent-red)' : 'var(--accent-orange)'}`,
                      borderRadius: '10px', padding: '12px', textAlign: 'center',
                      display: 'flex', flexDirection: 'column', gap: '8px'
                    }}
                  >
                    {/* Stack Name */}
                    <div style={{ 
                      fontSize: '11px', fontWeight: '700', color: 'var(--accent-purple)',
                      background: 'rgba(156, 39, 176, 0.1)', padding: '3px 8px', borderRadius: '4px'
                    }}>
                      {build.stackName}
                    </div>
                    
                    {/* Build Number with Status Icon */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                      {build.status === 'success' && <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />}
                      {build.status === 'failed' && <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                      {(build.status === 'aborted' || build.status === 'unstable') && <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />}
                      <a 
                        href={build.buildUrl || build.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', textDecoration: 'none' }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        #{build.buildNumber}
                      </a>
                    </div>
                    
                    {/* Duration & Timestamp */}
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                      {build.duration || 'N/A'}
                    </div>
                    
                    {/* Action buttons */}
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'center' }}>
                      {/* Open in Jenkins button - always visible */}
                      {(build.buildUrl || (endpointPdvData?.jenkinsUrl && build.buildNumber)) && (
                        <a
                          href={build.buildUrl || `${endpointPdvData.jenkinsUrl}/${build.buildNumber}/`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          style={{
                            display: 'flex', alignItems: 'center', gap: '4px',
                            padding: '4px 8px', borderRadius: '4px', border: 'none',
                            background: 'rgba(33, 150, 243, 0.15)',
                            color: 'var(--accent-blue)',
                            fontSize: '10px', fontWeight: '600',
                            textDecoration: 'none'
                          }}
                          title="Open in Jenkins"
                        >
                          <ExternalLink size={10} /> Jenkins
                        </a>
                      )}
                      {/* Analyze button for failed/unstable builds with test reports */}
                      {(build.status === 'failed' || build.status === 'unstable') && build.hasTestReport && (
                        <button
                          disabled={loadingTfa && tfaData?.buildNumber === build.buildNumber}
                          onClick={(e) => {
                            e.stopPropagation();
                            fetchTFA({ name: `Endpoint PDV - ${build.stackName}`, stack: build.stackName, url: endpointPdvData?.jenkinsUrl }, build.buildNumber, true);
                          }}
                          style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px',
                            padding: '4px 8px', borderRadius: '4px', border: 'none',
                            background: 'rgba(244, 67, 54, 0.2)',
                            color: 'var(--accent-red)',
                            cursor: loadingTfa && tfaData?.buildNumber === build.buildNumber ? 'wait' : 'pointer',
                            fontSize: '10px', fontWeight: '600',
                            opacity: loadingTfa && tfaData?.buildNumber === build.buildNumber ? 0.7 : 1
                          }}
                        >
                          {loadingTfa && tfaData?.buildNumber === build.buildNumber ? (
                            <><Loader size={10} className="spin" /> ...</>
                          ) : (
                            <><Search size={10} /> TFA</>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              
              {allBuilds.length > 50 && (
                <div style={{ textAlign: 'center', marginTop: '12px', color: 'var(--text-muted)', fontSize: '12px' }}>
                  Showing 50 of {allBuilds.length} builds
                </div>
              )}
            </div>
          );
        })()}
      </div>
    );
  };

  const renderStackMonitoring = () => {
    if (!stackData) return null;

    const issues = getAllIssues();
    const totalIssues = issues.crashLoops.length + issues.unhealthy.length;
    const healthPercent = getHealthPercentage();

    return (
      <div className="monitoring-content">
        {/* Demo Mode Banner - Only show for demo data */}
        {stackData.isDemo && (
          <div style={{ 
            display: 'flex', 
            gap: '12px', 
            marginBottom: '16px',
            fontSize: '12px',
            alignItems: 'center'
          }}>
            <span style={{ 
              padding: '4px 10px', 
              background: 'rgba(255, 193, 7, 0.15)', 
              borderRadius: '4px',
              color: 'var(--accent-orange)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <AlertTriangle size={12} /> Demo Mode
            </span>
          </div>
        )}

        {/* ===== HEALTH DASHBOARD ===== */}
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'minmax(280px, 1fr) 2fr', 
          gap: '20px', 
          marginBottom: '24px' 
        }}>
          {/* Left: Health Score Card */}
          <div style={{ 
            background: 'var(--card-bg)', 
            borderRadius: '16px', 
            padding: '24px',
            border: '1px solid var(--border-color)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            {/* Circular Progress */}
            <div style={{ position: 'relative', width: '140px', height: '140px', marginBottom: '16px' }}>
              <svg viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
                <circle
                  cx="50" cy="50" r="42"
                  fill="none"
                  stroke="var(--border-color)"
                  strokeWidth="8"
                />
                <circle
                  cx="50" cy="50" r="42"
                  fill="none"
                  stroke={healthPercent >= 90 ? 'var(--accent-green)' : healthPercent >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)'}
                  strokeWidth="8"
                  strokeDasharray={`${healthPercent * 2.64} 264`}
                  strokeLinecap="round"
                />
              </svg>
              <div style={{ 
                position: 'absolute', 
                inset: 0, 
                display: 'flex', 
                flexDirection: 'column',
                alignItems: 'center', 
                justifyContent: 'center' 
              }}>
                <span style={{ fontSize: '32px', fontWeight: '700', color: 'var(--text-primary)' }}>
                  {healthPercent}%
                </span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Health</span>
              </div>
            </div>
            
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '14px', fontWeight: '600', marginBottom: '4px' }}>
                {healthPercent >= 90 ? 'All Systems Operational' : 
                 healthPercent >= 70 ? 'Minor Issues Detected' : 'Attention Required'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                {stackData.totalDeployments} deployments across {stackData.totalStacks} stacks
              </div>
            </div>
          </div>

          {/* Right: Quick Stats Grid - Compact */}
          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', 
            gap: '10px' 
          }}>
            {/* Healthy */}
            <div style={{ 
              background: 'linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%)',
              borderRadius: '10px',
              padding: '10px 12px',
              border: '1px solid rgba(76, 175, 80, 0.2)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Healthy</span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: 'var(--accent-green)' }}>
                {stackData.stacks?.reduce((sum, s) => sum + s.metrics.healthy, 0) || 0}
              </div>
            </div>

            {/* Warnings */}
            <div style={{ 
              background: 'linear-gradient(135deg, rgba(255, 193, 7, 0.1) 0%, rgba(255, 193, 7, 0.05) 100%)',
              borderRadius: '10px',
              padding: '10px 12px',
              border: '1px solid rgba(255, 193, 7, 0.2)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Warnings</span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: 'var(--accent-orange)' }}>
                {stackData.stacks?.reduce((sum, s) => sum + s.metrics.warning, 0) || 0}
              </div>
            </div>

            {/* Critical */}
            <div style={{ 
              background: 'linear-gradient(135deg, rgba(244, 67, 54, 0.1) 0%, rgba(244, 67, 54, 0.05) 100%)',
              borderRadius: '10px',
              padding: '10px 12px',
              border: '1px solid rgba(244, 67, 54, 0.2)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <XCircle size={14} style={{ color: 'var(--accent-red)' }} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Critical</span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: 'var(--accent-red)' }}>
                {stackData.stacks?.reduce((sum, s) => sum + s.metrics.critical, 0) || 0}
              </div>
            </div>

            {/* Pods */}
            <div style={{ 
              background: 'linear-gradient(135deg, rgba(33, 150, 243, 0.1) 0%, rgba(33, 150, 243, 0.05) 100%)',
              borderRadius: '10px',
              padding: '10px 12px',
              border: '1px solid rgba(33, 150, 243, 0.2)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <Server size={14} style={{ color: 'var(--accent-cyan)' }} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Pods Ready</span>
              </div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: 'var(--accent-cyan)' }}>
                {stackData.totalPods?.ready || 0}/{stackData.totalPods?.desired || 0}
              </div>
            </div>

            {/* Restarts */}
            {stackData.totalRestarts > 0 && (
              <div style={{ 
                background: 'linear-gradient(135deg, rgba(156, 39, 176, 0.1) 0%, rgba(156, 39, 176, 0.05) 100%)',
                borderRadius: '10px',
                padding: '10px 12px',
                border: '1px solid rgba(156, 39, 176, 0.2)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                  <RotateCcw size={14} style={{ color: '#9c27b0' }} />
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Restarts</span>
                </div>
                <div style={{ fontSize: '20px', fontWeight: '700', color: '#9c27b0' }}>
                  {stackData.totalRestarts}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ===== ISSUES PANEL (if any issues exist) ===== */}
        {totalIssues > 0 && (
          <div style={{ 
            background: 'linear-gradient(135deg, rgba(244, 67, 54, 0.05) 0%, rgba(255, 193, 7, 0.05) 100%)',
            borderRadius: '16px',
            padding: '20px',
            marginBottom: '24px',
            border: '1px solid rgba(244, 67, 54, 0.2)'
          }}>
            <div 
              style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                marginBottom: issuesPanelCollapsed ? '0' : '16px',
                cursor: 'pointer'
              }}
              onClick={() => setIssuesPanelCollapsed(!issuesPanelCollapsed)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ 
                  width: '36px', 
                  height: '36px', 
                  borderRadius: '10px',
                  background: 'rgba(244, 67, 54, 0.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  <AlertTriangle size={20} style={{ color: 'var(--accent-red)' }} />
                </div>
                <div>
                  <div style={{ fontWeight: '600', fontSize: '16px' }}>Issues Requiring Attention</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {totalIssues} issue{totalIssues !== 1 ? 's' : ''} detected across your stacks
                  </div>
                </div>
              </div>
              <button
                style={{
                  background: 'rgba(244, 67, 54, 0.1)',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '8px 12px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  color: 'var(--text-secondary)',
                  fontSize: '13px',
                  fontWeight: '500',
                  transition: 'all 0.2s ease'
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setIssuesPanelCollapsed(!issuesPanelCollapsed);
                }}
              >
                {issuesPanelCollapsed ? 'Show' : 'Hide'}
                {issuesPanelCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
              </button>
            </div>

            {!issuesPanelCollapsed && (
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', 
              gap: '16px',
              maxHeight: '280px',
              overflowY: 'auto',
              paddingRight: '8px'
            }}>
              {/* CrashLoopBackOff */}
              {issues.crashLoops.length > 0 && (
                <div style={{ 
                  background: 'var(--card-bg)', 
                  borderRadius: '12px', 
                  padding: '16px',
                  border: '1px solid var(--border-color)'
                }}>
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '8px', 
                    marginBottom: '12px',
                    color: 'var(--accent-red)',
                    fontWeight: '600',
                    fontSize: '13px'
                  }}>
                    <XCircle size={16} />
                    CrashLoopBackOff ({issues.crashLoops.length})
                  </div>
                  {issues.crashLoops.slice(0, 3).map((item, idx) => (
                    <div key={idx} style={{ 
                      padding: '8px 10px', 
                      background: 'rgba(244, 67, 54, 0.05)',
                      borderRadius: '6px',
                      marginBottom: '6px',
                      fontSize: '12px'
                    }}>
                      <div style={{ fontWeight: '500' }}>{item.deployment?.split('/')[0]}</div>
                      <div style={{ color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                        <span>{item.namespace}</span>
                        <span>{item.stackName}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Unhealthy Deployments */}
              {issues.unhealthy.length > 0 && (
                <div style={{ 
                  background: 'var(--card-bg)', 
                  borderRadius: '12px', 
                  padding: '16px',
                  border: '1px solid var(--border-color)'
                }}>
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '8px', 
                    marginBottom: '12px',
                    color: 'var(--accent-orange)',
                    fontWeight: '600',
                    fontSize: '13px'
                  }}>
                    <AlertTriangle size={16} />
                    Unhealthy Deployments ({issues.unhealthy.length})
                  </div>
                  {issues.unhealthy.slice(0, 3).map((item, idx) => (
                    <div key={idx} style={{ 
                      padding: '8px 10px', 
                      background: 'rgba(255, 193, 7, 0.05)',
                      borderRadius: '6px',
                      marginBottom: '6px',
                      fontSize: '12px'
                    }}>
                      <div style={{ fontWeight: '500' }}>{item.deployment?.split('/')[0]}</div>
                      <div style={{ color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                        <span>{item.status}</span>
                        <span>{item.stackName}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Recent Events */}
              {issues.events.length > 0 && (
                <div style={{ 
                  background: 'var(--card-bg)', 
                  borderRadius: '12px', 
                  padding: '16px',
                  border: '1px solid var(--border-color)'
                }}>
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '8px', 
                    marginBottom: '12px',
                    color: 'var(--accent-orange)',
                    fontWeight: '600',
                    fontSize: '13px'
                  }}>
                    <Clock size={16} />
                    Recent Events ({issues.events.length})
                  </div>
                  {issues.events.slice(0, 4).map((event, idx) => (
                    <div key={idx} style={{ 
                      padding: '6px 10px', 
                      background: 'rgba(255, 193, 7, 0.05)',
                      borderRadius: '6px',
                      marginBottom: '4px',
                      fontSize: '11px',
                      display: 'flex',
                      gap: '8px'
                    }}>
                      <span style={{ fontWeight: '500', color: 'var(--accent-orange)', minWidth: '70px' }}>{event.reason}</span>
                      <span style={{ flex: 1, color: 'var(--text-secondary)' }}>
                        {event.message?.substring(0, 60)}{event.message?.length > 60 ? '...' : ''}
                      </span>
                      <span style={{ color: 'var(--text-muted)' }}>{event.age}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            )}
          </div>
        )}

        {/* Recent Alerts / Status - Always show (with success state when healthy) */}
        {stackData.alerts && stackData.alerts.length > 0 && (() => {
          const isAllHealthy = stackData.alerts.length === 1 && stackData.alerts[0].severity === 'success';
          const alertColor = isAllHealthy ? '76, 175, 80' : '255, 193, 7'; // green or orange
          
          return (
          <div style={{ 
            background: `linear-gradient(135deg, rgba(${alertColor}, 0.08) 0%, rgba(${alertColor}, 0.05) 100%)`,
            borderRadius: '12px',
            padding: '16px 20px',
            border: `1px solid rgba(${alertColor}, 0.2)`,
            marginBottom: '20px'
          }}>
            <div 
              style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                cursor: 'pointer'
              }}
              onClick={() => setAlertsPanelCollapsed(!alertsPanelCollapsed)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ 
                  width: '32px', 
                  height: '32px', 
                  borderRadius: '8px',
                  background: `rgba(${alertColor}, 0.15)`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  {isAllHealthy ? (
                    <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />
                  ) : (
                    <Bell size={16} style={{ color: 'var(--accent-orange)' }} />
                  )}
                </div>
                <div>
                  <div style={{ fontWeight: '600', fontSize: '14px' }}>
                    {isAllHealthy ? 'System Status' : 'Recent Alerts'}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {isAllHealthy 
                      ? 'All systems operational - no issues detected'
                      : `${stackData.alerts.length} alert${stackData.alerts.length !== 1 ? 's' : ''} in the last hour`
                    }
                  </div>
                </div>
              </div>
              <button
                style={{
                  background: `rgba(${alertColor}, 0.1)`,
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 10px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  color: 'var(--text-secondary)',
                  fontSize: '12px',
                  fontWeight: '500',
                  transition: 'all 0.2s ease'
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setAlertsPanelCollapsed(!alertsPanelCollapsed);
                }}
              >
                {alertsPanelCollapsed ? 'Show' : 'Hide'}
                {alertsPanelCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>

            {!alertsPanelCollapsed && (
              <div style={{ 
                marginTop: '12px',
                maxHeight: '200px',
                overflowY: 'auto'
              }}>
                {stackData.alerts.slice(0, 10).map((alert, idx) => (
                  <div key={idx} style={{ 
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '8px 12px',
                    background: alert.severity === 'success' ? 'rgba(76, 175, 80, 0.08)' : 'var(--card-bg)',
                    borderRadius: '8px',
                    marginBottom: '6px',
                    border: alert.severity === 'success' ? '1px solid rgba(76, 175, 80, 0.2)' : '1px solid var(--border-color)',
                    fontSize: '12px'
                  }}>
                    <span style={{ 
                      color: 'var(--text-muted)', 
                      fontSize: '11px',
                      minWidth: '60px'
                    }}>{alert.time}</span>
                    <span style={{ 
                      background: alert.severity === 'success' ? 'rgba(76, 175, 80, 0.15)' : 'var(--bg-secondary)',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontWeight: '500',
                      fontSize: '11px',
                      color: alert.severity === 'success' ? 'var(--accent-green)' : 'inherit'
                    }}>{alert.stack}</span>
                    <span style={{ 
                      flex: 1, 
                      color: alert.severity === 'success' ? 'var(--accent-green)' : 'var(--text-secondary)'
                    }}>{alert.message}</span>
                    <span style={{ 
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontSize: '10px',
                      fontWeight: '600',
                      textTransform: 'uppercase',
                      background: alert.severity === 'critical' ? 'rgba(244, 67, 54, 0.15)' : 
                                 alert.severity === 'warning' ? 'rgba(255, 193, 7, 0.15)' : 'rgba(76, 175, 80, 0.15)',
                      color: alert.severity === 'critical' ? 'var(--accent-red)' : 
                             alert.severity === 'warning' ? 'var(--accent-orange)' : 'var(--accent-green)'
                    }}>{alert.severity === 'success' ? 'healthy' : alert.severity}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          );
        })()}

        {/* ===== VIEW CONTROLS ===== */}
        <div style={{ 
          display: 'flex', 
          gap: '16px', 
          marginBottom: '20px', 
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          {/* Left: View Mode Tabs */}
          <div style={{ 
            display: 'flex', 
            gap: '4px', 
            background: 'var(--card-bg)', 
            padding: '4px', 
            borderRadius: '10px',
            border: '1px solid var(--border-color)'
          }}>
            {[
              { id: 'grid', label: 'Stacks', icon: <Layers size={14} /> },
              { id: 'comparison', label: 'Compare', icon: <Activity size={14} /> },
            ].map(view => (
              <button
                key={view.id}
                onClick={() => { 
                  // If clicking the same view (Stacks), toggle collapse all
                  if (stackViewMode === view.id && view.id === 'grid') {
                    if (areAllStacksCollapsed()) {
                      expandAllStacks();
                    } else {
                      collapseAllStacks();
                    }
                    return;
                  }
                  // Always collapse all expanded stacks when switching tabs
                  setExpandedStacks({});
                  setCollapsedStackCards({}); // Reset collapsed state when switching views
                  setStackViewMode(view.id); 
                  closeSidePanel(); 
                }}
                title={stackViewMode === view.id && view.id === 'grid' 
                  ? (areAllStacksCollapsed() ? 'Click to expand all stacks' : 'Click to collapse all stacks')
                  : `Switch to ${view.label} view`
                }
                style={{
                  padding: '8px 16px',
                  border: 'none',
                  borderRadius: '8px',
                  background: stackViewMode === view.id 
                    ? 'linear-gradient(135deg, var(--accent-purple) 0%, #9c27b0 100%)' 
                    : 'transparent',
                  color: stackViewMode === view.id ? 'white' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: '500',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  transition: 'all 0.2s ease',
                }}
              >
                {view.icon} {view.label}
                {/* Show collapse indicator for Stacks button when in stacks view */}
                {view.id === 'grid' && stackViewMode === 'grid' && (
                  <span style={{ 
                    marginLeft: '4px', 
                    opacity: 0.8,
                    display: 'flex',
                    alignItems: 'center'
                  }}>
                    {areAllStacksCollapsed() ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Center: Environment Filter (NPE vs Production) */}
          <div style={{ 
            display: 'flex', 
            gap: '4px', 
            background: 'var(--card-bg)', 
            padding: '4px', 
            borderRadius: '10px',
            border: '1px solid var(--border-color)'
          }}>
            {[
              { id: 'all', label: 'All', count: stackData?.stacks?.length || 0 },
              { id: 'npe', label: 'NPE', count: stackData?.stacks?.filter(s => !isProductionStack(s.id)).length || 0 },
              { id: 'production', label: 'Production', count: stackData?.stacks?.filter(s => isProductionStack(s.id)).length || 0 },
            ].map(filter => (
              <button
                key={filter.id}
                onClick={() => setStackEnvFilter(filter.id)}
                style={{
                  padding: '6px 12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: stackEnvFilter === filter.id 
                    ? filter.id === 'production' 
                      ? 'linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)' 
                      : filter.id === 'npe'
                        ? 'linear-gradient(135deg, #ff9800 0%, #f57c00 100%)'
                        : 'linear-gradient(135deg, var(--accent-purple) 0%, #9c27b0 100%)'
                    : 'transparent',
                  color: stackEnvFilter === filter.id ? 'white' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontSize: '12px',
                  fontWeight: '500',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  transition: 'all 0.2s ease',
                }}
              >
                {filter.label}
                <span style={{
                  background: stackEnvFilter === filter.id ? 'rgba(255,255,255,0.2)' : 'var(--bg-secondary)',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontWeight: '600',
                }}>
                  {filter.count}
                </span>
              </button>
            ))}
          </div>

          {/* Right: Search and Filters */}
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Search Input */}
            <div style={{ position: 'relative', minWidth: '220px' }}>
              <Search size={14} style={{ 
                position: 'absolute', 
                left: '10px', 
                top: '50%', 
                transform: 'translateY(-50%)',
                color: 'var(--text-muted)'
              }} />
              <input
                type="text"
                placeholder="Search deployments by name..."
                value={stackSearchQuery}
                onChange={(e) => setStackSearchQuery(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 32px 8px 32px',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  background: 'var(--card-bg)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                }}
              />
              {stackSearchQuery && (
                <button
                  onClick={() => setStackSearchQuery('')}
                  style={{
                    position: 'absolute',
                    right: '8px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--text-muted)',
                    padding: '2px',
                  }}
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Status Filter Pills */}
            <div style={{ display: 'flex', gap: '6px' }}>
              {['all', 'healthy', 'warning', 'critical'].map(status => (
                <button
                  key={status}
                  onClick={() => setStackStatusFilter(status)}
                  style={{
                    padding: '6px 12px',
                    border: '1px solid',
                    borderColor: stackStatusFilter === status 
                      ? (status === 'healthy' ? 'var(--accent-green)' : 
                         status === 'warning' ? 'var(--accent-orange)' : 
                         status === 'critical' ? 'var(--accent-red)' : 'var(--accent-purple)')
                      : 'var(--border-color)',
                    borderRadius: '6px',
                    background: stackStatusFilter === status 
                      ? (status === 'healthy' ? 'rgba(76, 175, 80, 0.1)' : 
                         status === 'warning' ? 'rgba(255, 193, 7, 0.1)' : 
                         status === 'critical' ? 'rgba(244, 67, 54, 0.1)' : 'rgba(156, 39, 176, 0.1)')
                      : 'transparent',
                    color: stackStatusFilter === status 
                      ? (status === 'healthy' ? 'var(--accent-green)' : 
                         status === 'warning' ? 'var(--accent-orange)' : 
                         status === 'critical' ? 'var(--accent-red)' : 'var(--accent-purple)')
                      : 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: '500',
                    textTransform: 'capitalize',
                  }}
                >
                  {status === 'all' ? 'All' : status}
                </button>
              ))}
            </div>

          </div>
        </div>
        
        {/* ===== STACKS VIEW ===== */}
        {stackViewMode === 'grid' && (
          <div className="stacks-grid">
            {filterStacksByEnvironment(stackData.stacks).map(stack => {
              const filteredComponents = filterStackDeployments(stack.components);
              if (filteredComponents.length === 0 && (stackSearchQuery || stackStatusFilter !== 'all')) {
                return null; // Hide stack if no components match filter
              }
              
              const isCardCollapsed = collapsedStackCards[stack.id];
              
              return (
                <div key={stack.id} className={`stack-card status-${stack.status}`}>
                  <div 
                    className="stack-header" 
                    onClick={() => toggleStackCardCollapse(stack.id)}
                    style={{ cursor: 'pointer', userSelect: 'none' }}
                    title={isCardCollapsed ? "Click to expand" : "Click to collapse"}
                  >
                    <div className="stack-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {isCardCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                      {getStatusIcon(stack.status)}
                      <span>{stack.name}</span>
                      {isCardCollapsed && (
                        <span style={{ 
                          fontSize: '11px', 
                          color: 'var(--text-muted)',
                          fontWeight: 'normal',
                          marginLeft: '4px'
                        }}>
                          ({filteredComponents.length} deployments)
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {isCardCollapsed && (
                        <span style={{
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          background: stack.status === 'healthy' ? 'rgba(76, 175, 80, 0.2)' :
                                     stack.status === 'warning' ? 'rgba(255, 193, 7, 0.2)' :
                                     'rgba(244, 67, 54, 0.2)',
                          color: stack.status === 'healthy' ? 'var(--accent-green)' :
                                stack.status === 'warning' ? 'var(--accent-orange)' :
                                'var(--accent-red)',
                        }}>
                          {stack.healthPercentage || Math.round((stack.components?.filter(c => c.status === 'healthy').length / stack.components?.length) * 100) || 0}% healthy
                        </span>
                      )}
                      <span className="stack-region">{stack.region}</span>
                    </div>
                  </div>

                  {!isCardCollapsed && (
                  <>
                  <div className="stack-components">
                    {(expandedStacks[stack.id] 
                      ? filteredComponents 
                      : filteredComponents.slice(0, 5)
                    ).map((comp, idx) => (
                      <div key={idx} className="component-item" style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <Server size={16} />
                        <span className="component-label" style={{ minWidth: '100px', flex: '0 0 auto' }}>{comp.namespace}</span>
                        <span className={`component-status status-${normalizeStatus(comp.status)}`}>
                          {comp.status}
                        </span>
                        {/* Replica Status */}
                        {comp.replicas && (
                          <span 
                            title={`Desired: ${comp.replicas.desired}, Ready: ${comp.replicas.ready}, Available: ${comp.replicas.available}`}
                            style={{
                              fontSize: '11px',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              background: comp.replicas.ready < comp.replicas.desired 
                                ? 'rgba(255, 193, 7, 0.2)' 
                                : 'rgba(76, 175, 80, 0.2)',
                              color: comp.replicas.ready < comp.replicas.desired 
                                ? 'var(--accent-orange)' 
                                : 'var(--accent-green)',
                            }}
                          >
                            {comp.replicas.ready}/{comp.replicas.desired} pods
                          </span>
                        )}
                        {/* Restart Count */}
                        {comp.restarts > 0 && (
                          <span 
                            title={`Pod restarts: ${comp.restarts}`}
                            style={{
                              fontSize: '10px',
                              padding: '2px 5px',
                              borderRadius: '4px',
                              background: comp.restarts > 5 ? 'rgba(255, 193, 7, 0.2)' : 'rgba(33, 150, 243, 0.15)',
                              color: comp.restarts > 5 ? 'var(--accent-orange)' : 'var(--accent-cyan)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '3px',
                            }}
                          >
                            <RotateCcw size={10} /> {comp.restarts}
                          </span>
                        )}
                        {/* CrashLoopBackOff Indicator */}
                        {comp.crashLoop && (
                          <span 
                            title="Pod is in CrashLoopBackOff state"
                            style={{
                              fontSize: '10px',
                              padding: '2px 5px',
                              borderRadius: '4px',
                              background: 'rgba(244, 67, 54, 0.2)',
                              color: 'var(--accent-red)',
                              fontWeight: '600',
                            }}
                          >
                            CrashLoop
                          </span>
                        )}
                        {/* Age */}
                        {comp.age && comp.age !== 'unknown' && (
                          <span 
                            title={`Last updated: ${comp.lastUpdated || 'unknown'}`}
                            style={{ fontSize: '11px', color: 'var(--text-muted)' }}
                          >
                            {comp.age}
                          </span>
                        )}
                        <span className="component-metric" title={comp.deployment} style={{ fontSize: '11px' }}>{comp.version}</span>
                        
                        {/* Quick Actions */}
                        <div style={{ marginLeft: 'auto', display: 'flex', gap: '4px', alignItems: 'center' }}>
                          {/* Details Button - Opens Side Panel */}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              openDeploymentDetails(comp.namespace, comp.deployment, stack.id, comp.namespaceFull);
                            }}
                            title="View deployment details"
                            style={{
                              padding: '2px 8px',
                              fontSize: '10px',
                              background: 'linear-gradient(135deg, var(--accent-purple) 0%, #9c27b0 100%)',
                              border: 'none',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              color: 'white',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '3px',
                            }}
                          >
                            <ChevronRight size={10} /> Details
                          </button>
                          <button
                            onClick={(e) => copyKubectlCommand(e, comp.deployment, comp.namespaceFull || comp.namespace, stack.id)}
                            title="Copy kubectl get command"
                            style={{
                              padding: '2px 6px',
                              fontSize: '10px',
                              background: copiedCommand === `${comp.deployment}-${stack.id}` ? 'var(--accent-green)' : 'var(--bg-secondary)',
                              border: '1px solid var(--border-color)',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              color: copiedCommand === `${comp.deployment}-${stack.id}` ? 'white' : 'var(--text-muted)',
                            }}
                          >
                            {copiedCommand === `${comp.deployment}-${stack.id}` ? '✓' : 'kubectl'}
                          </button>
                          <button
                            onClick={(e) => copyLogsCommand(e, comp.deployment, comp.namespaceFull || comp.namespace, stack.id)}
                            title="Copy logs command"
                            style={{
                              padding: '2px 6px',
                              fontSize: '10px',
                              background: copiedCommand === `logs-${comp.deployment}-${stack.id}` ? 'var(--accent-green)' : 'var(--bg-secondary)',
                              border: '1px solid var(--border-color)',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              color: copiedCommand === `logs-${comp.deployment}-${stack.id}` ? 'white' : 'var(--text-muted)',
                            }}
                          >
                            {copiedCommand === `logs-${comp.deployment}-${stack.id}` ? '✓' : 'logs'}
                          </button>
                        </div>
                      </div>
                    ))}
                    {filteredComponents.length > 5 && (
                      <div 
                        className="component-item expand-toggle" 
                        onClick={() => toggleStackExpansion(stack.id)}
                        style={{ cursor: 'pointer' }}
                      >
                        {expandedStacks[stack.id] ? (
                          <>
                            <ChevronUp size={16} />
                            <span className="component-label">Show less</span>
                          </>
                        ) : (
                          <>
                            <ChevronDown size={16} />
                            <span className="component-label">+ {filteredComponents.length - 5} more</span>
                          </>
                        )}
                      </div>
                    )}
                    {filteredComponents.length === 0 && (
                      <div style={{ padding: '12px', color: 'var(--text-muted)', textAlign: 'center', fontSize: '13px' }}>
                        No deployments match filter
                      </div>
                    )}
                  </div>

                  <div className="stack-metrics">
                    <div className="stack-metric">
                      <CheckCircle size={14} />
                      <span>{stack.metrics.healthy} healthy</span>
                    </div>
                    <div className="stack-metric">
                      <AlertTriangle size={14} />
                      <span>{stack.metrics.warning} warning</span>
                    </div>
                    <div className="stack-metric">
                      <XCircle size={14} />
                      <span>{stack.metrics.critical} critical</span>
                    </div>
                    <div className="stack-metric">
                      <Activity size={14} />
                      <span>{stack.healthPercent}% health</span>
                    </div>
                    {/* Pod Stats */}
                    {stack.pods && stack.pods.desired > 0 && (
                      <div 
                        className="stack-metric"
                        style={{
                          background: stack.pods.ready < stack.pods.desired 
                            ? 'rgba(255, 193, 7, 0.15)' 
                            : 'rgba(76, 175, 80, 0.15)',
                          borderRadius: '4px',
                          padding: '4px 8px',
                        }}
                      >
                        <Server size={14} />
                        <span style={{ 
                          color: stack.pods.ready < stack.pods.desired 
                            ? 'var(--accent-orange)' 
                            : 'var(--accent-green)' 
                        }}>
                          {stack.pods.ready}/{stack.pods.desired} pods
                        </span>
                      </div>
                    )}
                    {/* Restart Stats */}
                    {stack.restarts > 0 && (
                      <div 
                        className="stack-metric"
                        style={{
                          background: stack.restarts > 5 ? 'rgba(255, 193, 7, 0.15)' : 'rgba(33, 150, 243, 0.1)',
                          borderRadius: '4px',
                          padding: '4px 8px',
                        }}
                      >
                        <RotateCcw size={14} />
                        <span style={{ color: stack.restarts > 5 ? 'var(--accent-orange)' : 'var(--accent-cyan)' }}>
                          {stack.restarts} restarts
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Events/Warnings Section */}
                  {stack.events && stack.events.length > 0 && (
                    <div style={{ 
                      marginTop: '12px', 
                      padding: '10px', 
                      background: 'rgba(255, 193, 7, 0.05)', 
                      borderRadius: '8px',
                      border: '1px solid rgba(255, 193, 7, 0.2)'
                    }}>
                      <div style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: '6px', 
                        marginBottom: '8px',
                        fontSize: '12px',
                        fontWeight: '600',
                        color: 'var(--accent-orange)'
                      }}>
                        <AlertTriangle size={14} />
                        Recent Events ({stack.events.length})
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {stack.events.slice(0, 3).map((event, idx) => (
                          <div 
                            key={idx} 
                            style={{ 
                              fontSize: '11px', 
                              display: 'flex',
                              gap: '8px',
                              alignItems: 'flex-start',
                              color: 'var(--text-secondary)'
                            }}
                          >
                            <span style={{ 
                              color: event.type === 'Error' ? 'var(--accent-red)' : 'var(--accent-orange)',
                              fontWeight: '500',
                              minWidth: '60px'
                            }}>
                              {event.reason}
                            </span>
                            <span style={{ flex: 1, opacity: 0.9 }} title={event.message}>
                              {event.message.length > 80 ? event.message.substring(0, 80) + '...' : event.message}
                            </span>
                            <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
                              {event.age}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="stack-footer">
                    <Clock size={12} />
                    <span>Last check: {stack.lastCheck}</span>
                  </div>
                  </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Version Comparison Table View */}
        {stackViewMode === 'comparison' && (
          <div style={{ 
            background: 'var(--card-bg)', 
            borderRadius: '12px', 
            border: '1px solid var(--border-color)'
          }}>
            <div style={{ 
              padding: '16px 20px', 
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              gap: '12px'
            }}>
              <Activity size={20} style={{ color: 'var(--accent-purple)' }} />
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600' }}>Version Comparison Across Stacks</h3>
              <span style={{ 
                fontSize: '12px', 
                color: 'var(--text-muted)',
                background: 'var(--bg-secondary)',
                padding: '4px 8px',
                borderRadius: '4px'
              }}>
                {getComparisonData().length} deployments · {filterStacksByEnvironment(stackData.stacks).length} stacks
              </span>
            </div>
            
            <div style={{ 
              overflowX: 'scroll', 
              overflowY: 'visible', 
              width: '100%',
              WebkitOverflowScrolling: 'touch'
            }}>
              <div style={{ 
                minWidth: `${200 + (filterStacksByEnvironment(stackData.stacks).length * 150)}px`,
                display: 'inline-block'
              }}>
              <table style={{ 
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '13px',
                tableLayout: 'fixed'
              }}>
                <thead>
                  <tr style={{ background: 'var(--bg-secondary)' }}>
                    <th style={{ 
                      padding: '12px 16px', 
                      textAlign: 'left', 
                      fontWeight: '600',
                      borderBottom: '1px solid var(--border-color)',
                      position: 'sticky',
                      left: 0,
                      background: '#f8f9fa',
                      width: '200px',
                      minWidth: '200px',
                      zIndex: 20,
                      boxShadow: '2px 0 4px rgba(0,0,0,0.1)'
                    }}>
                      Deployment
                    </th>
                    {filterStacksByEnvironment(stackData.stacks).map(stack => (
                      <th key={stack.id} style={{ 
                        padding: '12px 16px', 
                        textAlign: 'center', 
                        fontWeight: '600',
                        borderBottom: '1px solid var(--border-color)',
                        width: '150px',
                        minWidth: '150px',
                        opacity: stack.connectionError ? 0.6 : 1
                      }}
                      title={stack.connectionError ? stack.errorMessage : undefined}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                          {getStatusIcon(stack.status)}
                          {stack.id.toUpperCase()}
                          {stack.connectionError && (
                            <span style={{ 
                              fontSize: '9px', 
                              background: 'var(--bg-tertiary)', 
                              padding: '2px 4px', 
                              borderRadius: '3px',
                              color: 'var(--text-muted)'
                            }}>
                              N/A
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>
                          {stack.region}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {getComparisonData().map((row, idx) => {
                    const hasMismatch = hasVersionMismatch(row.stacks);
                    return (
                      <tr 
                        key={idx} 
                        style={{ 
                          background: hasMismatch ? 'rgba(255, 193, 7, 0.05)' : 'transparent',
                          borderLeft: hasMismatch ? '3px solid var(--accent-orange)' : '3px solid transparent'
                        }}
                      >
                        <td style={{ 
                          padding: '10px 16px', 
                          borderBottom: '1px solid var(--border-color)',
                          position: 'sticky',
                          left: 0,
                          background: hasMismatch ? '#fff8e1' : '#ffffff',
                          zIndex: 10,
                          boxShadow: '2px 0 4px rgba(0,0,0,0.05)'
                        }}>
                          <div style={{ fontWeight: '500' }}>{row.namespace}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{row.deployment}</div>
                        </td>
                        {filterStacksByEnvironment(stackData.stacks).map(stack => {
                          const stackInfo = row.stacks[stack.id];
                          if (!stackInfo) {
                            return (
                              <td key={stack.id} style={{ 
                                padding: '10px 16px', 
                                textAlign: 'center',
                                borderBottom: '1px solid var(--border-color)',
                                color: 'var(--text-muted)'
                              }}>
                                —
                              </td>
                            );
                          }
                          return (
                            <td key={stack.id} style={{ 
                              padding: '10px 16px', 
                              textAlign: 'center',
                              borderBottom: '1px solid var(--border-color)',
                            }}>
                              <div style={{ 
                                display: 'flex', 
                                flexDirection: 'column', 
                                alignItems: 'center', 
                                gap: '4px' 
                              }}>
                                <span className={`component-status status-${normalizeStatus(stackInfo.status)}`} style={{ fontSize: '11px' }}>
                                  {stackInfo.status}
                                </span>
                                <code style={{ 
                                  fontSize: '11px', 
                                  background: 'var(--bg-secondary)', 
                                  padding: '2px 6px', 
                                  borderRadius: '4px',
                                  fontFamily: 'monospace'
                                }}>
                                  {stackInfo.version}
                                </code>
                                {stackInfo.replicas && (
                                  <span style={{ 
                                    fontSize: '10px',
                                    color: stackInfo.replicas.ready < stackInfo.replicas.desired 
                                      ? 'var(--accent-orange)' 
                                      : 'var(--accent-green)'
                                  }}>
                                    {stackInfo.replicas.ready}/{stackInfo.replicas.desired} pods
                                  </span>
                                )}
                                {stackInfo.age && (
                                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                    {stackInfo.age}
                                  </span>
                                )}
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              </div>
              
              {getComparisonData().length === 0 && (
                <div style={{ 
                  padding: '40px', 
                  textAlign: 'center', 
                  color: 'var(--text-muted)' 
                }}>
                  No deployments match the current filter
                </div>
              )}
            </div>
            
            {/* Legend */}
            <div style={{ 
              padding: '12px 20px', 
              borderTop: '1px solid var(--border-color)',
              display: 'flex',
              gap: '20px',
              fontSize: '12px',
              color: 'var(--text-muted)'
            }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ 
                  width: '12px', 
                  height: '12px', 
                  background: 'rgba(255, 193, 7, 0.3)',
                  borderLeft: '3px solid var(--accent-orange)',
                  borderRadius: '2px'
                }}></span>
                Version mismatch across stacks
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <CheckCircle size={12} style={{ color: 'var(--accent-green)' }} />
                Healthy
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <AlertTriangle size={12} style={{ color: 'var(--accent-orange)' }} />
                Warning
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <XCircle size={12} style={{ color: 'var(--accent-red)' }} />
                Critical
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Activity size={12} style={{ color: 'var(--text-muted)' }} />
                <span style={{ opacity: 0.6 }}>N/A</span>
                = Connection error
              </span>
            </div>
          </div>
        )}

        {/* ===== SIDE PANEL BACKDROP ===== */}
        {sidePanelOpen && (
          <div 
            onClick={closeSidePanel}
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              width: '100vw',
              height: '100vh',
              background: 'rgba(0,0,0,0.5)',
              zIndex: 9998,
              cursor: 'pointer',
            }}
          />
        )}

        {/* ===== SIDE PANEL - Deployment Detail View ===== */}
        {sidePanelOpen && (
          <div 
            style={{
              position: 'fixed',
              top: 0,
              right: 0,
              width: '480px',
              height: '100vh',
              background: 'var(--bg-primary, #1a1a2e)',
              borderLeft: '1px solid var(--border-color)',
              boxShadow: '-8px 0 30px rgba(0,0,0,0.3)',
              zIndex: 9999,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              animation: 'slideInRight 0.3s ease-out',
            }}
          >
            {/* Panel Header */}
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'linear-gradient(135deg, var(--accent-purple) 0%, #9c27b0 100%)',
              color: 'white',
            }}>
              <div>
                <div style={{ fontSize: '16px', fontWeight: '600' }}>
                  {selectedDeployment?.deployment?.split('/')[0] || 'Deployment Details'}
                </div>
                <div style={{ fontSize: '12px', opacity: 0.8 }}>
                  {selectedDeployment?.namespace} • {selectedDeployment?.stack?.toUpperCase()}
                </div>
              </div>
              <button
                onClick={closeSidePanel}
                style={{
                  background: 'rgba(255,255,255,0.2)',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px',
                  cursor: 'pointer',
                  color: 'white',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Tabs */}
            <div style={{
              display: 'flex',
              borderBottom: '1px solid var(--border-color)',
              background: 'var(--card-bg, #252542)',
            }}>
              {[
                { id: 'overview', label: 'Overview', icon: <Activity size={14} /> },
                { id: 'pods', label: 'Pods', icon: <Server size={14} /> },
                { id: 'logs', label: 'Logs', icon: <Terminal size={14} /> },
                { id: 'history', label: 'History', icon: <BarChart3 size={14} /> },
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setDetailActiveTab(tab.id)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    border: 'none',
                    background: detailActiveTab === tab.id ? 'var(--bg-primary, #1a1a2e)' : 'transparent',
                    borderBottom: detailActiveTab === tab.id ? '2px solid var(--accent-purple)' : '2px solid transparent',
                    color: detailActiveTab === tab.id ? 'var(--accent-purple)' : 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: '500',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    transition: 'all 0.2s ease',
                  }}
                >
                  {tab.icon} {tab.label}
                </button>
              ))}
            </div>

            {/* Panel Content */}
            <div style={{ flex: 1, overflow: 'auto', padding: '16px', background: 'var(--bg-primary, #1a1a2e)' }}>
              {loadingDetails ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
                  <Loader size={32} className="spin" style={{ color: 'var(--accent-purple)' }} />
                </div>
              ) : detailsError ? (
                <div style={{ 
                  padding: '20px', 
                  background: 'rgba(244, 67, 54, 0.1)', 
                  borderRadius: '8px',
                  color: 'var(--accent-red)',
                  textAlign: 'center'
                }}>
                  <XCircle size={32} style={{ marginBottom: '8px' }} />
                  <div style={{ fontWeight: '600' }}>Error Loading Details</div>
                  <div style={{ fontSize: '12px', marginTop: '4px' }}>{detailsError}</div>
                </div>
              ) : !deploymentDetails ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                  Select a deployment to view details
                </div>
              ) : (
                <>
                  {/* OVERVIEW TAB */}
                  {detailActiveTab === 'overview' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {/* Replicas Card */}
                      <div style={{ 
                        background: 'var(--bg-secondary)', 
                        borderRadius: '12px', 
                        padding: '16px' 
                      }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                          REPLICA STATUS
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
                          {[
                            { label: 'Desired', value: deploymentDetails.replicas?.desired || 0, color: 'var(--text-primary)' },
                            { label: 'Ready', value: deploymentDetails.replicas?.ready || 0, color: 'var(--accent-green)' },
                            { label: 'Available', value: deploymentDetails.replicas?.available || 0, color: 'var(--accent-cyan)' },
                            { label: 'Unavailable', value: deploymentDetails.replicas?.unavailable || 0, color: 'var(--accent-red)' },
                          ].map(stat => (
                            <div key={stat.label} style={{ textAlign: 'center' }}>
                              <div style={{ fontSize: '24px', fontWeight: '700', color: stat.color }}>{stat.value}</div>
                              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{stat.label}</div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Probes Card */}
                      {deploymentDetails.probes && (
                        <div style={{ 
                          background: 'var(--bg-secondary)', 
                          borderRadius: '12px', 
                          padding: '16px' 
                        }}>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                            HEALTH PROBES
                          </div>
                          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                            {['readiness', 'liveness', 'startup'].map(probeType => {
                              const probe = deploymentDetails.probes[probeType];
                              if (!probe?.configured) return null;
                              
                              const isHealthy = probe.status === 'passing';
                              return (
                                <div 
                                  key={probeType}
                                  style={{
                                    flex: '1 1 140px',
                                    padding: '12px',
                                    borderRadius: '8px',
                                    background: isHealthy 
                                      ? 'rgba(76, 175, 80, 0.1)' 
                                      : 'rgba(244, 67, 54, 0.1)',
                                    border: `1px solid ${isHealthy ? 'rgba(76, 175, 80, 0.3)' : 'rgba(244, 67, 54, 0.3)'}`,
                                  }}
                                >
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                                    {isHealthy ? <Heart size={14} style={{ color: 'var(--accent-green)' }} /> 
                                               : <XCircle size={14} style={{ color: 'var(--accent-red)' }} />}
                                    <span style={{ fontWeight: '600', fontSize: '12px', textTransform: 'capitalize' }}>
                                      {probeType}
                                    </span>
                                  </div>
                                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                    {probe.type} {probe.path && `→ ${probe.path}`}
                                  </div>
                                  <div style={{ 
                                    fontSize: '10px', 
                                    marginTop: '4px',
                                    color: isHealthy ? 'var(--accent-green)' : 'var(--accent-red)'
                                  }}>
                                    {isHealthy ? '● Passing' : '● Failing'}
                                  </div>
                                </div>
                              );
                            })}
                            {!deploymentDetails.probes.readiness?.configured && 
                             !deploymentDetails.probes.liveness?.configured && (
                              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                                No probes configured
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Resource Metrics Card */}
                      {deploymentDetails.resource_metrics && Object.keys(deploymentDetails.resource_metrics).length > 0 && (
                        <div style={{ 
                          background: 'var(--bg-secondary)', 
                          borderRadius: '12px', 
                          padding: '16px' 
                        }}>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                            RESOURCE USAGE
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            {Object.entries(deploymentDetails.resource_metrics).slice(0, 3).map(([podName, metrics]) => (
                              <div key={podName} style={{ 
                                padding: '10px', 
                                background: 'var(--card-bg)', 
                                borderRadius: '6px',
                                fontSize: '12px'
                              }}>
                                <div style={{ fontWeight: '500', marginBottom: '8px', color: 'var(--text-secondary)' }}>
                                  {podName.split('-').slice(-2).join('-')}
                                </div>
                                <div style={{ display: 'flex', gap: '16px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Cpu size={14} style={{ color: 'var(--accent-cyan)' }} />
                                    <span>CPU: {metrics.cpu?.usage || 'N/A'}</span>
                                  </div>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <HardDrive size={14} style={{ color: 'var(--accent-purple)' }} />
                                    <span>Memory: {metrics.memory?.usage || 'N/A'}</span>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Deployment Info */}
                      <div style={{ 
                        background: 'var(--bg-secondary)', 
                        borderRadius: '12px', 
                        padding: '16px' 
                      }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                          DEPLOYMENT INFO
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Age</span>
                            <span>{deploymentDetails.age || 'Unknown'}</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: 'var(--text-muted)' }}>Total Restarts</span>
                            <span style={{ color: deploymentDetails.total_restarts > 0 ? 'var(--accent-orange)' : 'inherit' }}>
                              {deploymentDetails.total_restarts || 0}
                            </span>
                          </div>
                          {deploymentDetails.containers && deploymentDetails.containers.length > 0 && (
                            <div>
                              <span style={{ color: 'var(--text-muted)' }}>Containers:</span>
                              {deploymentDetails.containers.map((c, idx) => (
                                <div key={idx} style={{ 
                                  marginTop: '6px', 
                                  padding: '8px', 
                                  background: 'var(--card-bg)', 
                                  borderRadius: '4px' 
                                }}>
                                  <div style={{ fontWeight: '500' }}>{c.name}</div>
                                  <code style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{c.version}</code>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Events */}
                      {deploymentDetails.events && deploymentDetails.events.length > 0 && (
                        <div style={{ 
                          background: 'rgba(255, 193, 7, 0.05)', 
                          borderRadius: '12px', 
                          padding: '16px',
                          border: '1px solid rgba(255, 193, 7, 0.2)'
                        }}>
                          <div style={{ fontSize: '12px', color: 'var(--accent-orange)', marginBottom: '12px', fontWeight: '600' }}>
                            RECENT EVENTS ({deploymentDetails.events.length})
                          </div>
                          {deploymentDetails.events.slice(0, 5).map((event, idx) => (
                            <div key={idx} style={{ 
                              padding: '8px', 
                              background: 'var(--card-bg)', 
                              borderRadius: '6px',
                              marginBottom: '6px',
                              fontSize: '11px'
                            }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                <span style={{ fontWeight: '500', color: 'var(--accent-orange)' }}>{event.reason}</span>
                                <span style={{ color: 'var(--text-muted)' }}>{event.age}</span>
                              </div>
                              <div style={{ color: 'var(--text-secondary)' }}>{event.message}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* PODS TAB */}
                  {detailActiveTab === 'pods' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {!deploymentDetails.pods || deploymentDetails.pods.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                          No pods found
                        </div>
                      ) : (
                        deploymentDetails.pods.map((pod, idx) => (
                          <div 
                            key={idx}
                            style={{
                              background: 'var(--bg-secondary)',
                              borderRadius: '10px',
                              padding: '14px',
                              border: pod.crash_loop ? '1px solid rgba(244, 67, 54, 0.3)' : '1px solid var(--border-color)'
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                              <div>
                                <div style={{ fontWeight: '500', fontSize: '13px' }}>{pod.name.split('-').slice(-2).join('-')}</div>
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{pod.node || 'Unknown node'}</div>
                              </div>
                              <span style={{
                                padding: '3px 8px',
                                borderRadius: '4px',
                                fontSize: '10px',
                                fontWeight: '600',
                                background: pod.status === 'Running' ? 'rgba(76, 175, 80, 0.15)' : 
                                            pod.crash_loop ? 'rgba(244, 67, 54, 0.15)' : 'rgba(255, 193, 7, 0.15)',
                                color: pod.status === 'Running' ? 'var(--accent-green)' : 
                                       pod.crash_loop ? 'var(--accent-red)' : 'var(--accent-orange)'
                              }}>
                                {pod.crash_loop ? 'CrashLoop' : pod.status}
                              </span>
                            </div>
                            <div style={{ display: 'flex', gap: '16px', fontSize: '11px', marginBottom: '10px' }}>
                              <span style={{ color: 'var(--text-muted)' }}>
                                Age: <span style={{ color: 'var(--text-secondary)' }}>{pod.age}</span>
                              </span>
                              <span style={{ color: 'var(--text-muted)' }}>
                                Restarts: <span style={{ color: pod.restarts > 0 ? 'var(--accent-orange)' : 'var(--text-secondary)' }}>{pod.restarts}</span>
                              </span>
                              {pod.ip && (
                                <span style={{ color: 'var(--text-muted)' }}>
                                  IP: <span style={{ color: 'var(--text-secondary)' }}>{pod.ip}</span>
                                </span>
                              )}
                            </div>
                            <button
                              onClick={() => { setDetailActiveTab('logs'); fetchPodLogs(pod.name); }}
                              style={{
                                padding: '6px 12px',
                                background: 'var(--card-bg)',
                                border: '1px solid var(--border-color)',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontSize: '11px',
                                color: 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px'
                              }}
                            >
                              <FileText size={12} /> View Logs
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {/* LOGS TAB */}
                  {detailActiveTab === 'logs' && (
                    <div>
                      {/* Pod Selector */}
                      {deploymentDetails.pods && deploymentDetails.pods.length > 0 && (
                        <div style={{ marginBottom: '12px' }}>
                          <select
                            value={selectedPodForLogs || ''}
                            onChange={(e) => { setSelectedPodForLogs(e.target.value); fetchPodLogs(e.target.value); }}
                            style={{
                              width: '100%',
                              padding: '8px 12px',
                              borderRadius: '8px',
                              border: '1px solid var(--border-color)',
                              background: 'var(--bg-secondary)',
                              color: 'var(--text-primary)',
                              fontSize: '12px'
                            }}
                          >
                            {deploymentDetails.pods.map((pod, idx) => (
                              <option key={idx} value={pod.name}>
                                {pod.name.split('-').slice(-2).join('-')} ({pod.status})
                              </option>
                            ))}
                          </select>
                        </div>
                      )}

                      {/* Logs Content */}
                      {loadingLogs ? (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
                          <Loader size={24} className="spin" style={{ color: 'var(--accent-purple)' }} />
                        </div>
                      ) : podLogs?.error ? (
                        <div style={{ 
                          padding: '20px', 
                          background: 'rgba(244, 67, 54, 0.1)', 
                          borderRadius: '8px',
                          color: 'var(--accent-red)',
                          textAlign: 'center',
                          fontSize: '12px'
                        }}>
                          {podLogs.error}
                        </div>
                      ) : podLogs?.logs ? (
                        <div style={{
                          background: '#1e1e1e',
                          borderRadius: '8px',
                          padding: '12px',
                          fontFamily: 'monospace',
                          fontSize: '11px',
                          lineHeight: '1.5',
                          color: '#d4d4d4',
                          maxHeight: '400px',
                          overflow: 'auto',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all'
                        }}>
                          {podLogs.logs || 'No logs available'}
                        </div>
                      ) : (
                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                          Select a pod to view logs
                        </div>
                      )}
                    </div>
                  )}

                  {/* HISTORY TAB */}
                  {detailActiveTab === 'history' && (
                    <div>
                      {loadingHistory ? (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
                          <Loader size={24} className="spin" style={{ color: 'var(--accent-purple)' }} />
                        </div>
                      ) : stackHistory?.error ? (
                        <div style={{ 
                          padding: '20px', 
                          background: 'rgba(244, 67, 54, 0.1)', 
                          borderRadius: '8px',
                          color: 'var(--accent-red)',
                          textAlign: 'center',
                          fontSize: '12px'
                        }}>
                          {stackHistory.error}
                        </div>
                      ) : stackHistory?.history && stackHistory.history.length > 0 ? (
                        <div>
                          <div style={{ 
                            marginBottom: '16px', 
                            padding: '12px', 
                            background: 'var(--bg-secondary)', 
                            borderRadius: '8px',
                            fontSize: '12px',
                            color: 'var(--text-muted)'
                          }}>
                            Showing {stackHistory.data_points} snapshots from the last {stackHistory.hours_requested} hours
                          </div>
                          
                          {/* Simple trend chart */}
                          <div style={{ 
                            background: 'var(--bg-secondary)', 
                            borderRadius: '12px', 
                            padding: '16px',
                            marginBottom: '16px'
                          }}>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                              HEALTH TREND
                            </div>
                            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '2px', height: '80px' }}>
                              {stackHistory.history.slice(-24).map((snapshot, idx) => {
                                const total = snapshot.healthy_count + snapshot.unhealthy_count;
                                const healthPct = total > 0 ? (snapshot.healthy_count / total) * 100 : 100;
                                return (
                                  <div
                                    key={idx}
                                    title={`${new Date(snapshot.timestamp).toLocaleTimeString()}: ${healthPct.toFixed(0)}% healthy`}
                                    style={{
                                      flex: 1,
                                      height: `${healthPct}%`,
                                      minHeight: '4px',
                                      background: healthPct >= 90 ? 'var(--accent-green)' : 
                                                  healthPct >= 70 ? 'var(--accent-orange)' : 'var(--accent-red)',
                                      borderRadius: '2px 2px 0 0',
                                      opacity: 0.7,
                                    }}
                                  />
                                );
                              })}
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontSize: '10px', color: 'var(--text-muted)' }}>
                              <span>24h ago</span>
                              <span>Now</span>
                            </div>
                          </div>

                          {/* Restart trend */}
                          <div style={{ 
                            background: 'var(--bg-secondary)', 
                            borderRadius: '12px', 
                            padding: '16px' 
                          }}>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                              RESTART TREND
                            </div>
                            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '2px', height: '60px' }}>
                              {stackHistory.history.slice(-24).map((snapshot, idx) => {
                                const maxRestarts = Math.max(...stackHistory.history.map(s => s.total_restarts || 0), 1);
                                const heightPct = ((snapshot.total_restarts || 0) / maxRestarts) * 100;
                                return (
                                  <div
                                    key={idx}
                                    title={`${new Date(snapshot.timestamp).toLocaleTimeString()}: ${snapshot.total_restarts} restarts`}
                                    style={{
                                      flex: 1,
                                      height: `${heightPct}%`,
                                      minHeight: snapshot.total_restarts > 0 ? '4px' : '2px',
                                      background: snapshot.total_restarts > 10 ? 'var(--accent-red)' : 
                                                  snapshot.total_restarts > 0 ? 'var(--accent-orange)' : 'var(--border-color)',
                                      borderRadius: '2px 2px 0 0',
                                    }}
                                  />
                                );
                              })}
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                          <BarChart3 size={32} style={{ marginBottom: '12px', opacity: 0.5 }} />
                          <div>No historical data available yet</div>
                          <div style={{ fontSize: '11px', marginTop: '4px' }}>
                            Snapshots are saved hourly
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

      </div>
    );
  };

  return (
    <div className="monitoring-section">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><Activity size={24} /> {viewMode === 'pdv' ? 'PDV Monitoring' : 'Stack Monitoring'}</h1>
          <p>{viewMode === 'pdv' ? 'Real-time monitoring of daily PDV test results' : 'Real-time monitoring of stack infrastructure'}</p>
        </div>
        <div className="header-actions">
          <button className="action-btn secondary" onClick={handleRefresh} disabled={loading || loadingEndpointPdv}>
            <RefreshCw size={16} className={(loading || loadingEndpointPdv) ? 'spinning' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* PDV Sub-View Tabs - Only show for PDV monitoring */}
      {viewMode === 'pdv' && (
        <div style={{ 
          display: 'flex', 
          gap: '8px', 
          marginBottom: '20px',
          background: 'var(--bg-secondary)',
          padding: '6px',
          borderRadius: '10px',
          width: 'fit-content'
        }}>
          <button
            onClick={() => setPdvSubView('backend')}
            style={{
              padding: '10px 20px',
              borderRadius: '8px',
              border: 'none',
              background: pdvSubView === 'backend' ? 'var(--accent-blue)' : 'transparent',
              color: pdvSubView === 'backend' ? 'white' : 'var(--text-secondary)',
              fontWeight: '600',
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.2s'
            }}
          >
            <Server size={16} /> Backend PDV Runs
          </button>
          <button
            onClick={() => setPdvSubView('endpoint')}
            style={{
              padding: '10px 20px',
              borderRadius: '8px',
              border: 'none',
              background: pdvSubView === 'endpoint' ? 'var(--accent-purple)' : 'transparent',
              color: pdvSubView === 'endpoint' ? 'white' : 'var(--text-secondary)',
              fontWeight: '600',
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.2s'
            }}
          >
            <Microscope size={16} /> Endpoint PDV Runs
          </button>
        </div>
      )}

      {/* Loading State - Show skeleton cards for better UX */}
      {loading && viewMode === 'stack' && (
        <div className="stack-monitoring-skeleton">
          {/* Skeleton Dashboard Summary */}
          <div className="skeleton-summary">
            <div className="skeleton-stat">
              <div className="skeleton-icon pulse"></div>
              <div className="skeleton-text pulse" style={{ width: '80px' }}></div>
            </div>
            <div className="skeleton-stat">
              <div className="skeleton-icon pulse"></div>
              <div className="skeleton-text pulse" style={{ width: '60px' }}></div>
            </div>
            <div className="skeleton-stat">
              <div className="skeleton-icon pulse"></div>
              <div className="skeleton-text pulse" style={{ width: '70px' }}></div>
            </div>
            <div className="skeleton-stat">
              <div className="skeleton-icon pulse"></div>
              <div className="skeleton-text pulse" style={{ width: '90px' }}></div>
            </div>
          </div>
          
          {/* Skeleton Stack Cards */}
          <div className="skeleton-stacks">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="skeleton-stack-card">
                <div className="skeleton-header">
                  <div className="skeleton-title pulse" style={{ width: '120px' }}></div>
                  <div className="skeleton-badge pulse" style={{ width: '60px' }}></div>
                </div>
                <div className="skeleton-deployments">
                  {[1, 2, 3, 4, 5].map(j => (
                    <div key={j} className="skeleton-deployment">
                      <div className="skeleton-text pulse" style={{ width: '150px' }}></div>
                      <div className="skeleton-text pulse" style={{ width: '50px' }}></div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          
          <div className="skeleton-loading-text">
            <RefreshCw size={16} className="spinning" />
            <span>Loading stack monitoring data...</span>
          </div>
        </div>
      )}
      
      {/* Loading State for PDV */}
      {loading && viewMode === 'pdv' && (
        <div className="loading-state">
          <RefreshCw size={32} className="spinning" />
          <p>Loading monitoring data...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="error-state">
          <AlertTriangle size={32} />
          <p>Error loading monitoring data</p>
          <span>{error}</span>
        </div>
      )}

      {/* Content */}
      {!loading && !error && (
        <>
          {viewMode === 'pdv' && pdvSubView === 'backend' && renderPDVMonitoring()}
          {viewMode === 'pdv' && pdvSubView === 'endpoint' && renderEndpointPDVMonitoring()}
          {viewMode === 'stack' && renderStackMonitoring()}
        </>
      )}
    </div>
  );
};

export default MonitoringSection;

