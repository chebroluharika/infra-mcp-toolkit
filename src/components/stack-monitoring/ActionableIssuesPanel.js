import React, { useState, useCallback, useMemo } from 'react';
import { 
  AlertTriangle, 
  XCircle,
  ChevronDown,
  ChevronUp,
  FileText,
  Eye,
  Terminal,
  RotateCcw,
  GitCompare,
  Clock,
  CheckCircle,
  Download,
  TrendingUp,
  TrendingDown,
  Activity,
  RefreshCw,
  ChevronRight,
  Zap,
  Server,
  AlertOctagon,
  ArrowRight,
  Copy,
  ExternalLink,
  Calendar,
  Tag,
  Info
} from 'lucide-react';
import api from '../../services/api';

/**
 * ActionableIssuesPanel - Summary-only view with inline expandable items
 * 
 * Features:
 * - Three cards: Restarts, Errors, Version Drift
 * - Each item is expandable inline for details
 * - Action buttons available directly in expanded state
 * - "+X more" expands the list instead of switching views
 */
const ActionableIssuesPanel = ({ 
  issues, 
  onViewLogs, 
  onViewDetails, 
  onCopyKubectl,
  onViewComparison,
  collapsed,
  onToggleCollapse,
  lastUpdated, // timestamp of when data was last fetched
  loadingRestarts = false // true while fetching full data with restarts
}) => {
  // Expanded states for each card's items
  const [expandedRestarts, setExpandedRestarts] = useState({});
  const [expandedErrors, setExpandedErrors] = useState({});
  const [expandedCompliance, setExpandedCompliance] = useState({});
  const [expandedServiceLists, setExpandedServiceLists] = useState({});  // Track which alerts show all services
  
  // Show more states for each card
  const [showAllRestarts, setShowAllRestarts] = useState(false);
  const [showAllErrors, setShowAllErrors] = useState(false);
  const [showAllCompliance, setShowAllCompliance] = useState(false);
  
  // Collapsed states for Version Drift sections
  const [releaseComplianceCollapsed, setReleaseComplianceCollapsed] = useState(false);
  
  // Timeline data cache
  const [restartTimelines, setRestartTimelines] = useState({});
  const [loadingTimelines, setLoadingTimelines] = useState({});
  
  // Error logs cache
  const [errorLogs, setErrorLogs] = useState({});
  const [loadingErrorLogs, setLoadingErrorLogs] = useState({});

  // Group issues by type with analytics
  const groupedIssues = useMemo(() => {
    const restarts = [];
    const errors = { crashLoop: [], imagePull: [], unhealthy: [], oomKilled: [], pending: [] };
    const releaseCompliance = [];
    let oldestErrorTimestamp = null;
    let newestErrorTimestamp = null;

    const trackTimestamp = (issue) => {
      if (issue.timestamp) {
        const ts = new Date(issue.timestamp);
        if (!isNaN(ts.getTime())) {
          if (!oldestErrorTimestamp || ts < oldestErrorTimestamp) oldestErrorTimestamp = ts;
          if (!newestErrorTimestamp || ts > newestErrorTimestamp) newestErrorTimestamp = ts;
        }
      }
    };

    issues.forEach(issue => {
      if (issue.type === 'restarts') {
        restarts.push(issue);
      } else if (issue.type === 'crashLoop') {
        errors.crashLoop.push(issue);
        trackTimestamp(issue);
      } else if (issue.type === 'imagePull') {
        errors.imagePull.push(issue);
        trackTimestamp(issue);
      } else if (issue.type === 'unhealthy') {
        errors.unhealthy.push(issue);
        trackTimestamp(issue);
      } else if (issue.type === 'oomKilled') {
        errors.oomKilled.push(issue);
        trackTimestamp(issue);
      } else if (issue.type === 'pending') {
        errors.pending.push(issue);
        trackTimestamp(issue);
      } else if (issue.type === 'releaseCompliance') {
        releaseCompliance.push(issue);
      }
    });

    // Aggregate restarts by service with more analytics
    const restartsByService = {};
    let highestRestartService = null;
    let totalAffectedStacks = new Set();
    
    restarts.forEach(issue => {
      const serviceName = issue.service;
      totalAffectedStacks.add(issue.stack);
      if (!restartsByService[serviceName]) {
        restartsByService[serviceName] = {
          service: serviceName,
          totalRestarts: 0,
          stacks: [],
          issues: []
        };
      }
      const restartCount = issue.restarts || parseInt(issue.message) || 0;
      restartsByService[serviceName].totalRestarts += restartCount;
      restartsByService[serviceName].stacks.push({
        stack: issue.stack,
        stackName: issue.stackName,
        restarts: restartCount,
        namespace: issue.namespace,
        namespaceFull: issue.namespaceFull || issue.namespace
      });
      restartsByService[serviceName].issues.push(issue);
    });

    const sortedRestarts = Object.values(restartsByService)
      .sort((a, b) => b.totalRestarts - a.totalRestarts);

    // Find the service with highest restarts for insights
    highestRestartService = sortedRestarts[0] || null;
    
    // Calculate restart severity distribution
    const criticalRestarts = sortedRestarts.filter(s => s.totalRestarts > 100).length;
    const highRestarts = sortedRestarts.filter(s => s.totalRestarts > 50 && s.totalRestarts <= 100).length;
    const mediumRestarts = sortedRestarts.filter(s => s.totalRestarts <= 50).length;

    // Flatten all errors into a single list for easier rendering
    const allErrors = [
      ...errors.crashLoop.map(e => ({ ...e, errorType: 'crashLoop' })),
      ...errors.imagePull.map(e => ({ ...e, errorType: 'imagePull' })),
      ...errors.oomKilled.map(e => ({ ...e, errorType: 'oomKilled' })),
      ...errors.pending.map(e => ({ ...e, errorType: 'pending' })),
      ...errors.unhealthy.map(e => ({ ...e, errorType: 'unhealthy' }))
    ];

    return {
      restarts: sortedRestarts,
      errors,
      allErrors,
      releaseCompliance,
      totalRestarts: sortedRestarts.reduce((sum, s) => sum + s.totalRestarts, 0),
      totalErrors: allErrors.length,
      totalReleaseCompliance: releaseCompliance.length,
      // Analytics
      restartAnalytics: {
        totalAffectedStacks: totalAffectedStacks.size,
        highestRestartService,
        criticalCount: criticalRestarts,
        highCount: highRestarts,
        mediumCount: mediumRestarts
      },
      errorTimeRange: {
        oldest: oldestErrorTimestamp,
        newest: newestErrorTimestamp
      }
    };
  }, [issues]);

  // Toggle restart item expansion and fetch timeline
  const toggleRestartExpand = useCallback(async (serviceKey, serviceData) => {
    const willExpand = !expandedRestarts[serviceKey];
    setExpandedRestarts(prev => ({ ...prev, [serviceKey]: willExpand }));

    if (willExpand && !restartTimelines[serviceKey] && serviceData.stacks?.length > 0) {
      // Use the stack with highest restarts for timeline
      const topStack = serviceData.stacks.sort((a, b) => b.restarts - a.restarts)[0];
      setLoadingTimelines(prev => ({ ...prev, [serviceKey]: true }));
      try {
        // Use namespaceKey for timeline API (matches snapshot storage format)
        const timeline = await api.getRestartTimeline(
          topStack.namespaceKey || topStack.namespace,
          serviceData.service,
          topStack.stack
        );
        // Add which stack we fetched for
        timeline.analyzed_stack = topStack.stackName || topStack.stack;
        setRestartTimelines(prev => ({ ...prev, [serviceKey]: timeline }));
      } catch (err) {
        console.error('Failed to fetch restart timeline:', err);
        setRestartTimelines(prev => ({ ...prev, [serviceKey]: { error: err.message } }));
      } finally {
        setLoadingTimelines(prev => ({ ...prev, [serviceKey]: false }));
      }
    }
  }, [expandedRestarts, restartTimelines]);

  // Toggle error item expansion
  const toggleErrorExpand = useCallback((errorId) => {
    setExpandedErrors(prev => ({ ...prev, [errorId]: !prev[errorId] }));
  }, []);

  // Fetch error logs for a specific error using the deployment logs API
  // Uses namespaceFull (full K8s namespace) for API calls, falls back to namespace if not available
  const fetchErrorLogs = useCallback(async (errorId, namespaceFull, deployment, stack) => {
    if (errorLogs[errorId] || loadingErrorLogs[errorId]) return;
    
    // Extract actual deployment name (remove container suffix like "deployment/container")
    const deploymentName = deployment.includes('/') ? deployment.split('/')[0] : deployment;
    
    setLoadingErrorLogs(prev => ({ ...prev, [errorId]: true }));
    try {
      const logsData = await api.getDeploymentLogs(namespaceFull, deploymentName, stack, 30);
      setErrorLogs(prev => ({ ...prev, [errorId]: logsData }));
    } catch (err) {
      setErrorLogs(prev => ({ 
        ...prev, 
        [errorId]: { error: err.message || 'Failed to fetch logs' } 
      }));
    } finally {
      setLoadingErrorLogs(prev => ({ ...prev, [errorId]: false }));
    }
  }, [errorLogs, loadingErrorLogs]);

  // Toggle release compliance item expansion
  const toggleComplianceExpand = useCallback((complianceId) => {
    setExpandedCompliance(prev => ({ ...prev, [complianceId]: !prev[complianceId] }));
  }, []);

  const formatTimestamp = (isoString) => {
    if (!isoString) return 'N/A';
    try {
      const date = new Date(isoString);
      return date.toLocaleString([], { 
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit' 
      });
    } catch {
      return isoString;
    }
  };

  const formatRelativeTime = (date) => {
    if (!date || isNaN(date.getTime())) return 'just now';
    const now = new Date();
    const diffMs = now - date;
    if (isNaN(diffMs) || diffMs < 0) return 'just now';
    
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  const getRestartRecommendation = (serviceData) => {
    if (!serviceData) return null;
    const { totalRestarts, stacks } = serviceData;
    
    if (totalRestarts > 100) {
      return {
        severity: 'critical',
        message: 'Critical: Investigate immediately - possible memory leak or configuration issue',
        icon: AlertOctagon
      };
    } else if (totalRestarts > 50) {
      return {
        severity: 'high', 
        message: 'High: Check application logs for recurring errors',
        icon: AlertTriangle
      };
    } else if (stacks.length > 3) {
      return {
        severity: 'medium',
        message: 'Affecting multiple stacks - may indicate a deployment issue',
        icon: Server
      };
    }
    return null;
  };

  const totalIssues = issues.length;
  const criticalCount = issues.filter(i => i.severity === 'critical').length;
  const highCount = issues.filter(i => i.severity === 'high').length;

  if (totalIssues === 0) {
    return (
      <div className="actionable-issues-panel all-clear">
        <div className="panel-header">
          <div className="header-left">
            <CheckCircle size={20} style={{ color: 'var(--accent-green)' }} />
            <span className="panel-title">All Clear</span>
          </div>
        </div>
        <div className="all-clear-message">
          No issues detected. All deployments are healthy and versions are in sync.
        </div>
      </div>
    );
  }

  const INITIAL_SHOW = 5;

  return (
    <div className={`actionable-issues-panel ${collapsed ? 'collapsed' : ''}`}>
      {/* Header */}
      <div className="panel-header" onClick={onToggleCollapse}>
        <div className="header-left">
          <AlertTriangle size={20} style={{ color: criticalCount > 0 ? 'var(--accent-red)' : 'var(--accent-orange)' }} />
          <span className="panel-title">Needs Attention</span>
          <span className="issue-count-badge">
            {totalIssues} issue{totalIssues !== 1 ? 's' : ''}
          </span>
          <div className="severity-badges">
            {criticalCount > 0 && (
              <span className="severity-badge critical">{criticalCount} critical</span>
            )}
            {highCount > 0 && (
              <span className="severity-badge high">{highCount} high</span>
            )}
          </div>
        </div>
        <div className="header-right">
          {collapsed ? <ChevronDown size={20} /> : <ChevronUp size={20} />}
        </div>
      </div>

      {!collapsed && (
        <div className="summary-content">
          {/* ========== RESTARTS CARD ========== */}
          <div className="summary-card restarts-card">
            <div className="card-header">
              <div className="card-icon-wrapper restarts">
                <RotateCcw size={18} />
              </div>
              <div className="card-title-section">
                <span className="card-title">Pod Restarts</span>
                <span className="card-subtitle">
                  {groupedIssues.restarts.length} services • {groupedIssues.restartAnalytics?.totalAffectedStacks || 0} stacks
                </span>
              </div>
              <div className="card-metric">
                <span className="metric-value">{groupedIssues.totalRestarts}</span>
                <span className="metric-label">total</span>
              </div>
            </div>

            {/* Restart Analytics Summary */}
            {groupedIssues.restarts.length > 0 && (
              <div className="card-analytics">
                <div className="analytics-row">
                  {groupedIssues.restartAnalytics?.criticalCount > 0 && (
                    <span className="analytics-badge critical">
                      <AlertOctagon size={10} />
                      {groupedIssues.restartAnalytics.criticalCount} critical (&gt;100)
                    </span>
                  )}
                  {groupedIssues.restartAnalytics?.highCount > 0 && (
                    <span className="analytics-badge high">
                      <AlertTriangle size={10} />
                      {groupedIssues.restartAnalytics.highCount} high (&gt;50)
                    </span>
                  )}
                  {lastUpdated && (
                    <span className="analytics-timestamp">
                      <Clock size={10} />
                      Updated {formatRelativeTime(new Date(lastUpdated))}
                    </span>
                  )}
                </div>
              </div>
            )}
            
            <div className="card-content">
              {groupedIssues.restarts.length === 0 ? (
                loadingRestarts ? (
                  <div className="empty-state loading">
                    <RefreshCw size={20} className="spinning" />
                    <span>Loading restart data...</span>
                  </div>
                ) : (
                  <div className="empty-state success">
                    <CheckCircle size={20} />
                    <span>No restart issues</span>
                  </div>
                )
              ) : (
                <div className="expandable-list">
                  {(showAllRestarts ? groupedIssues.restarts : groupedIssues.restarts.slice(0, INITIAL_SHOW)).map((item, idx) => {
                    const serviceKey = item.service;
                    const isExpanded = expandedRestarts[serviceKey];
                    const maxRestarts = groupedIssues.restarts[0]?.totalRestarts || 1;
                    const barWidth = (item.totalRestarts / maxRestarts) * 100;
                    const severity = item.totalRestarts > 100 ? 'critical' : item.totalRestarts > 50 ? 'high' : 'medium';
                    const timeline = restartTimelines[serviceKey];
                    const isLoading = loadingTimelines[serviceKey];

                    return (
                      <div key={idx} className={`expandable-item ${severity} ${isExpanded ? 'expanded' : ''}`}>
                        <div 
                          className="item-header"
                          onClick={() => toggleRestartExpand(serviceKey, item)}
                        >
                          <div className="item-info">
                            <Server size={14} />
                            <span className="item-service" title={item.service}>
                              {item.service.length > 28 ? item.service.slice(0, 26) + '...' : item.service}
                            </span>
                            <span className="item-stacks-badge">
                              {item.stacks.length} stack{item.stacks.length !== 1 ? 's' : ''}
                            </span>
                          </div>
                          <div className="item-bar">
                            <div className="bar-track-inline">
                              <div 
                                className={`bar-fill-inline ${severity}`}
                                style={{ width: `${barWidth}%` }}
                              />
                            </div>
                            <span className={`item-value ${severity}`}>{item.totalRestarts}</span>
                          </div>
                          <div className="item-expand-icon">
                            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="item-expanded-content">
                            {/* Timeline Section */}
                            <div className="expanded-section">
                              <div className="section-header">
                                <Activity size={14} />
                                <span>Restart Timeline</span>
                                {timeline?.analyzed_stack && item.stacks.length > 1 && (
                                  <span className="timeline-stack-label">({timeline.analyzed_stack})</span>
                                )}
                                {timeline && !timeline.error && timeline.data_available && (
                                  <span className={`status-badge ${timeline.is_ongoing ? 'ongoing' : 'stopped'}`}>
                                    {timeline.is_ongoing ? <><TrendingUp size={10} /> Ongoing</> : <><TrendingDown size={10} /> Stopped</>}
                                  </span>
                                )}
                              </div>
                              
                              {isLoading ? (
                                <div className="loading-state">
                                  <RefreshCw size={14} className="spinning" />
                                  <span>Loading timeline...</span>
                                </div>
                              ) : timeline?.error ? (
                                <div className="error-state">
                                  <AlertTriangle size={14} />
                                  <span>Failed to load timeline</span>
                                </div>
                              ) : timeline ? (
                                <>
                                  {!timeline.data_available ? (
                                    <div className="no-data-state">
                                      <Info size={14} />
                                      <span>No historical snapshots available. Timeline data requires the snapshot scheduler to be running.</span>
                                    </div>
                                  ) : (
                                    <div className="timeline-grid">
                                      <div className="timeline-stat">
                                        <span className="stat-label">Last restart (K8s)</span>
                                        <span className="stat-value">
                                          {timeline.last_restart_at 
                                            ? formatTimestamp(timeline.last_restart_at)
                                            : 'N/A'}
                                        </span>
                                        {timeline.hours_since_last_restart !== null && (
                                          <span className="stat-hint">
                                            {timeline.hours_since_last_restart < 1 
                                              ? '< 1 hour ago' 
                                              : `${timeline.hours_since_last_restart}h ago`}
                                          </span>
                                        )}
                                      </div>
                                      <div className="timeline-stat">
                                        <span className="stat-label">First detected</span>
                                        <span className="stat-value">{formatTimestamp(timeline.first_seen_at)}</span>
                                      </div>
                                      <div className="timeline-stat">
                                        <span className="stat-label">Last count increase</span>
                                        <span className="stat-value">
                                          {timeline.first_seen_at === timeline.last_increased_at 
                                            ? 'No increase since first detected'
                                            : formatTimestamp(timeline.last_increased_at)}
                                        </span>
                                        {timeline.hours_since_last_increase !== null && 
                                         timeline.first_seen_at !== timeline.last_increased_at && (
                                          <span className="stat-hint">
                                            {timeline.hours_since_last_increase < 1 
                                              ? '< 1 hour ago' 
                                              : `${timeline.hours_since_last_increase}h ago`}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  )}
                                </>
                              ) : null}
                            </div>

                            {/* Recommendation Section */}
                            {(() => {
                              const rec = getRestartRecommendation(item);
                              return rec ? (
                                <div className={`recommendation-section ${rec.severity}`}>
                                  <div className="recommendation-header">
                                    <rec.icon size={14} />
                                    <span className="recommendation-title">Recommendation</span>
                                  </div>
                                  <p className="recommendation-text">{rec.message}</p>
                                </div>
                              ) : null;
                            })()}

                            {/* Affected Stacks - clickable to view logs/pod */}
                            <div className="expanded-section">
                              <div className="section-header">
                                <Server size={14} />
                                <span>Affected Stacks ({item.stacks.length})</span>
                                <span className="section-hint">Click to view details</span>
                              </div>
                              <div className="stacks-grid">
                                {item.stacks.sort((a, b) => b.restarts - a.restarts).map((s, i) => {
                                  // Check if there are multiple entries for the same stack (different namespaces)
                                  const sameStackCount = item.stacks.filter(st => st.stack === s.stack).length;
                                  const showNamespaceSuffix = sameStackCount > 1;
                                  // Extract namespace suffix for display (e.g., "support" from "--provisioner-pycore--support")
                                  const nsSuffix = showNamespaceSuffix && s.namespace 
                                    ? s.namespace.split('--').filter(Boolean).pop() 
                                    : null;
                                  
                                  return (
                                    <div 
                                      key={`${s.stack}-${s.namespace}-${i}`} 
                                      className={`stack-chip clickable ${s.restarts > 50 ? 'high' : s.restarts > 20 ? 'medium' : ''}`}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onViewDetails && onViewDetails(s.namespace, item.service, s.stack, s.namespaceFull);
                                      }}
                                      title={`View ${s.stackName || s.stack} - ${s.namespace} pod details`}
                                    >
                                      <span className="stack-name">
                                        {s.stackName || s.stack}
                                        {nsSuffix && <span className="ns-suffix">({nsSuffix})</span>}
                                      </span>
                                      <span className="stack-count">{s.restarts}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>

                          </div>
                        )}
                      </div>
                    );
                  })}

                  {groupedIssues.restarts.length > INITIAL_SHOW && (
                    <button 
                      className="show-more-btn"
                      onClick={() => setShowAllRestarts(!showAllRestarts)}
                    >
                      {showAllRestarts ? (
                        <><ChevronUp size={14} /> Show less</>
                      ) : (
                        <><ChevronDown size={14} /> Show {groupedIssues.restarts.length - INITIAL_SHOW} more services</>
                      )}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ========== ERRORS CARD ========== */}
          <div className="summary-card errors-card">
            <div className="card-header">
              <div className="card-icon-wrapper errors">
                <AlertOctagon size={18} />
              </div>
              <div className="card-title-section">
                <span className="card-title">Active Errors</span>
                <span className="card-subtitle">Requires immediate action</span>
              </div>
              <div className="card-metric">
                <span className="metric-value">{groupedIssues.totalErrors}</span>
                <span className="metric-label">total</span>
              </div>
            </div>

            {/* Error Summary Context */}
            {groupedIssues.totalErrors > 0 && (
              <div className="card-analytics">
                <div className="analytics-row">
                  {groupedIssues.errors.crashLoop.length > 0 && (
                    <span className="analytics-badge critical">
                      <RotateCcw size={10} />
                      {groupedIssues.errors.crashLoop.length} crash loop{groupedIssues.errors.crashLoop.length !== 1 ? 's' : ''}
                    </span>
                  )}
                  {groupedIssues.errors.oomKilled.length > 0 && (
                    <span className="analytics-badge critical">
                      <Zap size={10} />
                      {groupedIssues.errors.oomKilled.length} OOM
                    </span>
                  )}
                  {groupedIssues.errors.imagePull.length > 0 && (
                    <span className="analytics-badge high">
                      <Download size={10} />
                      {groupedIssues.errors.imagePull.length} image pull{groupedIssues.errors.imagePull.length !== 1 ? 's' : ''}
                    </span>
                  )}
                  {groupedIssues.errors.pending.length > 0 && (
                    <span className="analytics-badge medium">
                      <Clock size={10} />
                      {groupedIssues.errors.pending.length} pending
                    </span>
                  )}
                  {groupedIssues.errors.unhealthy.length > 0 && (
                    <span className="analytics-badge medium">
                      <AlertTriangle size={10} />
                      {groupedIssues.errors.unhealthy.length} unhealthy
                    </span>
                  )}
                  {lastUpdated && (
                    <span className="analytics-timestamp">
                      <Clock size={10} />
                      Live data as of {formatRelativeTime(new Date(lastUpdated))}
                    </span>
                  )}
                </div>
              </div>
            )}
            
            <div className="card-content">
              {groupedIssues.totalErrors === 0 ? (
                <div className="empty-state success">
                  <CheckCircle size={20} />
                  <span>All pods healthy</span>
                </div>
              ) : (
                <div className="expandable-list">
                  {/* CrashLoopBackOff Errors */}
                  {groupedIssues.errors.crashLoop.length > 0 && (
                    <div className="error-group">
                      <div className="error-group-header crash">
                        <RotateCcw size={14} />
                        <span>CrashLoopBackOff</span>
                        <span className="error-group-count">{groupedIssues.errors.crashLoop.length}</span>
                      </div>
                      {(showAllErrors ? groupedIssues.errors.crashLoop : groupedIssues.errors.crashLoop.slice(0, 3)).map((error, idx) => {
                        const isExpanded = expandedErrors[error.id];
                        return (
                          <div key={idx} className={`expandable-item error-item crash ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleErrorExpand(error.id)}
                            >
                              <div className="item-info">
                                <span className="error-stack">{error.stackName || error.stack}</span>
                                <ArrowRight size={12} />
                                <span className="error-service">{error.service}</span>
                              </div>
                              <div className="item-meta">
                                <span className="restart-badge">{error.message}</span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="error-details-section">
                                  <div className="error-message-box">
                                    <span className="error-label">Error</span>
                                    <code className="error-code">
                                      CrashLoopBackOff - Container keeps crashing after restart
                                    </code>
                                  </div>
                                  {error.timestamp && (
                                    <div className="error-message-box">
                                      <span className="error-label">
                                        Last Crash
                                        <span className="label-hint" title="Time of most recent crash. The crash loop may have started earlier.">
                                          <Info size={10} />
                                        </span>
                                      </span>
                                      <code className="error-code error-timestamp">
                                        <Clock size={12} />
                                        {formatRelativeTime(new Date(error.timestamp))} ({new Date(error.timestamp).toLocaleString()})
                                      </code>
                                    </div>
                                  )}
                                  {error.errorDetails && (
                                    <div className="error-message-box">
                                      <span className="error-label">Details</span>
                                      <code className="error-code">{error.errorDetails}</code>
                                    </div>
                                  )}
                                </div>

                                {/* Inline Error Logs Section */}
                                <div className="inline-logs-section">
                                  <div className="logs-header">
                                    <FileText size={14} />
                                    <span>Recent Logs</span>
                                    {!errorLogs[error.id] && !loadingErrorLogs[error.id] && (
                                      <button 
                                        className="fetch-logs-btn"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          fetchErrorLogs(error.id, error.namespaceFull || error.namespace, error.service, error.stack);
                                        }}
                                      >
                                        Load Logs
                                      </button>
                                    )}
                                    {loadingErrorLogs[error.id] && (
                                      <span className="logs-loading">
                                        <RefreshCw size={12} className="spinning" /> Loading...
                                      </span>
                                    )}
                                  </div>
                                  
                                  {errorLogs[error.id] && !errorLogs[error.id].error && (
                                    <div className="inline-logs-content">
                                      {errorLogs[error.id].pods?.map((pod, podIdx) => (
                                        <div key={podIdx} className="pod-logs-block">
                                          <div className="pod-logs-header">
                                            <span className={`pod-status ${pod.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                              {pod.status}
                                            </span>
                                            <span className="pod-name">{pod.name}</span>
                                          </div>
                                          {pod.logs ? (
                                            <pre className="pod-logs-output">{pod.logs}</pre>
                                          ) : pod.error ? (
                                            <div className="pod-logs-error">{pod.error}</div>
                                          ) : (
                                            <div className="pod-logs-empty">No logs available</div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  
                                  {errorLogs[error.id]?.error && (
                                    <div className="logs-error-msg">
                                      <AlertTriangle size={12} />
                                      {errorLogs[error.id].error}
                                    </div>
                                  )}
                                </div>

                                <div className="expanded-actions">
                                  <button 
                                    className="action-btn primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewLogs && onViewLogs(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <ExternalLink size={14} />
                                    Full Logs
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewDetails && onViewDetails(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <Eye size={14} />
                                    View Pod
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onCopyKubectl && onCopyKubectl(e, error.service, error.namespace, error.stack);
                                    }}
                                  >
                                    <Terminal size={14} />
                                    kubectl
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* ImagePullBackOff Errors */}
                  {groupedIssues.errors.imagePull.length > 0 && (
                    <div className="error-group">
                      <div className="error-group-header pull">
                        <Download size={14} />
                        <span>ImagePullBackOff</span>
                        <span className="error-group-count">{groupedIssues.errors.imagePull.length}</span>
                      </div>
                      {groupedIssues.errors.imagePull.map((error, idx) => {
                        const isExpanded = expandedErrors[error.id];
                        return (
                          <div key={idx} className={`expandable-item error-item pull ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleErrorExpand(error.id)}
                            >
                              <div className="item-info">
                                <span className="error-stack">{error.stackName || error.stack}</span>
                                <ArrowRight size={12} />
                                <span className="error-service">{error.service}</span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="error-details-section">
                                  <div className="error-message-box">
                                    <span className="error-label">Error</span>
                                    <code className="error-code">{error.message || 'Failed to pull image'}</code>
                                  </div>
                                  {error.errorDetails && (
                                    <div className="error-message-box">
                                      <span className="error-label">Details</span>
                                      <code className="error-code">{error.errorDetails}</code>
                                    </div>
                                  )}
                                </div>

                                <div className="expanded-actions">
                                  <button 
                                    className="action-btn primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewDetails && onViewDetails(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <Eye size={14} />
                                    View Details
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onCopyKubectl && onCopyKubectl(e, error.service, error.namespace, error.stack);
                                    }}
                                  >
                                    <Terminal size={14} />
                                    kubectl
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Unhealthy Errors */}
                  {groupedIssues.errors.unhealthy.length > 0 && (
                    <div className="error-group">
                      <div className="error-group-header unhealthy">
                        <XCircle size={14} />
                        <span>Unhealthy</span>
                        <span className="error-group-count">{groupedIssues.errors.unhealthy.length}</span>
                      </div>
                      {(showAllErrors ? groupedIssues.errors.unhealthy : groupedIssues.errors.unhealthy.slice(0, 3)).map((error, idx) => {
                        const isExpanded = expandedErrors[error.id];
                        return (
                          <div key={idx} className={`expandable-item error-item unhealthy ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleErrorExpand(error.id)}
                            >
                              <div className="item-info">
                                <span className="error-stack">{error.stackName || error.stack}</span>
                                <ArrowRight size={12} />
                                <span className="error-service">{error.service}</span>
                              </div>
                              <div className="item-meta">
                                <span className="unhealthy-badge">{error.message}</span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="error-details-section">
                                  {error.timestamp && (
                                    <div className="error-message-box">
                                      <span className="error-label">Unhealthy Since</span>
                                      <code className="error-code error-timestamp">
                                        <Clock size={12} />
                                        {formatRelativeTime(new Date(error.timestamp))} ({new Date(error.timestamp).toLocaleString()})
                                      </code>
                                    </div>
                                  )}
                                  {error.errorDetails && (
                                    <div className="error-message-box">
                                      <span className="error-label">Error</span>
                                      <code className="error-code">{error.errorDetails}</code>
                                    </div>
                                  )}
                                </div>

                                {/* Inline Error Logs Section */}
                                <div className="inline-logs-section">
                                  <div className="logs-header">
                                    <FileText size={14} />
                                    <span>Recent Logs</span>
                                    {!errorLogs[error.id] && !loadingErrorLogs[error.id] && (
                                      <button 
                                        className="fetch-logs-btn"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          fetchErrorLogs(error.id, error.namespaceFull || error.namespace, error.service, error.stack);
                                        }}
                                      >
                                        Load Logs
                                      </button>
                                    )}
                                    {loadingErrorLogs[error.id] && (
                                      <span className="logs-loading">
                                        <RefreshCw size={12} className="spinning" /> Loading...
                                      </span>
                                    )}
                                  </div>
                                  
                                  {errorLogs[error.id] && !errorLogs[error.id].error && (
                                    <div className="inline-logs-content">
                                      {errorLogs[error.id].pods?.map((pod, podIdx) => (
                                        <div key={podIdx} className="pod-logs-block">
                                          <div className="pod-logs-header">
                                            <span className={`pod-status ${pod.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                              {pod.status}
                                            </span>
                                            <span className="pod-name">{pod.name}</span>
                                          </div>
                                          {pod.logs ? (
                                            <pre className="pod-logs-output">{pod.logs}</pre>
                                          ) : pod.error ? (
                                            <div className="pod-logs-error">{pod.error}</div>
                                          ) : (
                                            <div className="pod-logs-empty">No logs available</div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  
                                  {errorLogs[error.id]?.error && (
                                    <div className="logs-error-msg">
                                      <AlertTriangle size={12} />
                                      {errorLogs[error.id].error}
                                    </div>
                                  )}
                                </div>

                                <div className="expanded-actions">
                                  <button 
                                    className="action-btn primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewLogs && onViewLogs(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <ExternalLink size={14} />
                                    Full Logs
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewDetails && onViewDetails(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <Eye size={14} />
                                    View Pod
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* OOMKilled Errors */}
                  {groupedIssues.errors.oomKilled.length > 0 && (
                    <div className="error-group">
                      <div className="error-group-header oom">
                        <Zap size={14} />
                        <span>OOMKilled</span>
                        <span className="error-group-count">{groupedIssues.errors.oomKilled.length}</span>
                      </div>
                      {groupedIssues.errors.oomKilled.map((error, idx) => {
                        const isExpanded = expandedErrors[error.id];
                        return (
                          <div key={idx} className={`expandable-item error-item oom ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleErrorExpand(error.id)}
                            >
                              <div className="item-info">
                                <span className="error-stack">{error.stackName || error.stack}</span>
                                <ArrowRight size={12} />
                                <span className="error-service">{error.service}</span>
                              </div>
                              <div className="item-meta">
                                <span className="oom-badge">Memory limit exceeded</span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="error-details-section">
                                  <div className="error-message-box">
                                    <span className="error-label">Error</span>
                                    <code className="error-code">Container killed due to exceeding memory limits</code>
                                  </div>
                                  {error.timestamp && (
                                    <div className="error-message-box">
                                      <span className="error-label">OOM Occurred</span>
                                      <code className="error-code error-timestamp">
                                        <Clock size={12} />
                                        {formatRelativeTime(new Date(error.timestamp))} ({new Date(error.timestamp).toLocaleString()})
                                      </code>
                                    </div>
                                  )}
                                  {error.errorDetails && (
                                    <div className="error-message-box">
                                      <span className="error-label">Details</span>
                                      <code className="error-code">{error.errorDetails}</code>
                                    </div>
                                  )}
                                </div>

                                <div className="inline-logs-section">
                                  <div className="logs-header">
                                    <FileText size={14} />
                                    <span>Recent Logs</span>
                                    {!errorLogs[error.id] && !loadingErrorLogs[error.id] && (
                                      <button 
                                        className="fetch-logs-btn"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          fetchErrorLogs(error.id, error.namespaceFull || error.namespace, error.service, error.stack);
                                        }}
                                      >
                                        Load Logs
                                      </button>
                                    )}
                                    {loadingErrorLogs[error.id] && (
                                      <span className="logs-loading">
                                        <RefreshCw size={12} className="spinning" /> Loading...
                                      </span>
                                    )}
                                  </div>
                                  
                                  {errorLogs[error.id] && !errorLogs[error.id].error && (
                                    <div className="inline-logs-content">
                                      {errorLogs[error.id].pods?.map((pod, podIdx) => (
                                        <div key={podIdx} className="pod-logs-block">
                                          <div className="pod-logs-header">
                                            <span className={`pod-status ${pod.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                              {pod.status}
                                            </span>
                                            <span className="pod-name">{pod.name}</span>
                                          </div>
                                          {pod.logs ? (
                                            <pre className="pod-logs-output">{pod.logs}</pre>
                                          ) : pod.error ? (
                                            <div className="pod-logs-error">{pod.error}</div>
                                          ) : (
                                            <div className="pod-logs-empty">No logs available</div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  
                                  {errorLogs[error.id]?.error && (
                                    <div className="logs-error-msg">
                                      <AlertTriangle size={12} />
                                      {errorLogs[error.id].error}
                                    </div>
                                  )}
                                </div>

                                <div className="expanded-actions">
                                  <button 
                                    className="action-btn primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewLogs && onViewLogs(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <ExternalLink size={14} />
                                    Full Logs
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewDetails && onViewDetails(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <Eye size={14} />
                                    View Pod
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Pending Errors */}
                  {groupedIssues.errors.pending.length > 0 && (
                    <div className="error-group">
                      <div className="error-group-header pending">
                        <Clock size={14} />
                        <span>Pending</span>
                        <span className="error-group-count">{groupedIssues.errors.pending.length}</span>
                      </div>
                      {groupedIssues.errors.pending.map((error, idx) => {
                        const isExpanded = expandedErrors[error.id];
                        return (
                          <div key={idx} className={`expandable-item error-item pending ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleErrorExpand(error.id)}
                            >
                              <div className="item-info">
                                <span className="error-stack">{error.stackName || error.stack}</span>
                                <ArrowRight size={12} />
                                <span className="error-service">{error.service}</span>
                              </div>
                              <div className="item-meta">
                                <span className="pending-badge">Waiting for resources</span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="error-details-section">
                                  <div className="error-message-box">
                                    <span className="error-label">Status</span>
                                    <code className="error-code">{error.message || 'Pod stuck in pending state'}</code>
                                  </div>
                                  {error.errorDetails && (
                                    <div className="error-message-box">
                                      <span className="error-label">Reason</span>
                                      <code className="error-code">{error.errorDetails}</code>
                                    </div>
                                  )}
                                </div>

                                <div className="expanded-actions">
                                  <button 
                                    className="action-btn primary"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onViewDetails && onViewDetails(error.namespace, error.service, error.stack, error.namespaceFull);
                                    }}
                                  >
                                    <Eye size={14} />
                                    View Details
                                  </button>
                                  <button 
                                    className="action-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onCopyKubectl && onCopyKubectl(e, error.service, error.namespace, error.stack);
                                    }}
                                  >
                                    <Terminal size={14} />
                                    kubectl
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {(groupedIssues.errors.crashLoop.length > 3 || groupedIssues.errors.unhealthy.length > 3 || 
                    groupedIssues.errors.oomKilled.length > 3 || groupedIssues.errors.pending.length > 3) && (
                    <button 
                      className="show-more-btn"
                      onClick={() => setShowAllErrors(!showAllErrors)}
                    >
                      {showAllErrors ? (
                        <><ChevronUp size={14} /> Show less</>
                      ) : (
                        <><ChevronDown size={14} /> Show all errors</>
                      )}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ========== VERSION DRIFT CARD ========== */}
          <div className="summary-card mismatches-card">
            <div className="card-header">
              <div className="card-icon-wrapper mismatches">
                <GitCompare size={18} />
              </div>
              <div className="card-title-section">
                <span className="card-title">Version Drift</span>
                <span className="card-subtitle">Release compliance status</span>
              </div>
              <div className="card-metric">
                <span className="metric-value">{groupedIssues.totalReleaseCompliance}</span>
                <span className="metric-label">issues</span>
              </div>
            </div>

            {/* Release Compliance Analytics */}
            {groupedIssues.totalReleaseCompliance > 0 && (
              <div className="card-analytics">
                <div className="analytics-row">
                  <span className="analytics-badge critical">
                    <Calendar size={10} />
                    {groupedIssues.totalReleaseCompliance} stack{groupedIssues.totalReleaseCompliance !== 1 ? 's' : ''} not on expected version
                  </span>
                </div>
              </div>
            )}
            
            <div className="card-content">
              {groupedIssues.releaseCompliance.length === 0 ? (
                <div className="empty-state success">
                  <CheckCircle size={20} />
                  <span>All stacks on expected versions</span>
                </div>
              ) : (
                <div className="expandable-list">
                  {/* Release Compliance Alerts - Show first as they're more important */}
                  {groupedIssues.releaseCompliance.length > 0 && (
                    <div className="error-group">
                      <div 
                        className="error-group-header release-compliance collapsible"
                        onClick={() => setReleaseComplianceCollapsed(!releaseComplianceCollapsed)}
                      >
                        <Calendar size={14} />
                        <span>Release Version Mismatch</span>
                        <span className="error-group-count">{groupedIssues.releaseCompliance.length}</span>
                        <div className="group-collapse-icon">
                          {releaseComplianceCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                        </div>
                      </div>
                      {!releaseComplianceCollapsed && (showAllCompliance ? groupedIssues.releaseCompliance : groupedIssues.releaseCompliance.slice(0, 3)).map((alert, idx) => {
                        const isExpanded = expandedCompliance[alert.id];
                        const categoryColors = {
                          qa: '#3b82f6',
                          staging: '#8b5cf6',
                          preprod: '#f59e0b',
                          prod_day1: '#ef4444',
                          prod_day2: '#f97316',
                          prod_day3: '#eab308',
                          prod_day4: '#22c55e',
                          prod_fedramp: '#8b5cf6',
                          prod: '#ef4444'
                        };
                        const categoryLabels = {
                          qa: 'QA',
                          staging: 'Staging',
                          preprod: 'Pre-Prod',
                          prod_day1: 'Prod Day 1',
                          prod_day2: 'Prod Day 2',
                          prod_day3: 'Prod Day 3',
                          prod_day4: 'Prod Day 4',
                          prod_fedramp: 'FedRAMP',
                          prod: 'Production'
                        };

                        return (
                          <div key={idx} className={`expandable-item compliance-item ${alert.severity} ${isExpanded ? 'expanded' : ''}`}>
                            <div 
                              className="item-header"
                              onClick={() => toggleComplianceExpand(alert.id)}
                            >
                              <div className="item-info">
                                <span 
                                  className="compliance-category-badge"
                                  style={{ backgroundColor: categoryColors[alert.stackCategory] || '#6b7280' }}
                                >
                                  {categoryLabels[alert.stackCategory] || alert.stackCategory}
                                </span>
                                <span className="compliance-stack">{alert.stackName || alert.stack}</span>
                              </div>
                              <div className="item-meta">
                                <span className="compliance-version-badge">
                                  <Tag size={10} />
                                  Expected: {alert.expectedVersion}
                                </span>
                              </div>
                              <div className="item-expand-icon">
                                {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                              </div>
                            </div>
                            
                            {/* Reason summary - always visible */}
                            <div className="compliance-reason-summary">
                              <Calendar size={12} />
                              <span>
                                <strong>{alert.milestone}</strong> reached on {alert.milestoneDate} — 
                                {alert.nonCompliantServices?.length || 0} service(s) still on older version
                              </span>
                            </div>

                            {isExpanded && (
                              <div className="item-expanded-content">
                                <div className="compliance-details-section">
                                  <div className="compliance-info-row">
                                    <div className="compliance-info-item">
                                      <span className="info-label">Milestone</span>
                                      <span className="info-value">{alert.milestone}</span>
                                    </div>
                                    <div className="compliance-info-item">
                                      <span className="info-label">Reached On</span>
                                      <span className="info-value">{alert.milestoneDate}</span>
                                    </div>
                                    <div className="compliance-info-item">
                                      <span className="info-label">Release</span>
                                      <span className="info-value">{alert.releaseName}</span>
                                    </div>
                                  </div>

                                  {/* Non-compliant services */}
                                  {alert.nonCompliantServices && alert.nonCompliantServices.length > 0 && (
                                    <div className="compliance-services">
                                      <div className="services-header critical">
                                        <XCircle size={12} />
                                        <span>Services not on expected version ({alert.nonCompliantServices.length})</span>
                                      </div>
                                      <div className="services-list">
                                        {(expandedServiceLists[alert.id] ? alert.nonCompliantServices : alert.nonCompliantServices.slice(0, 5)).map((svc, i) => (
                                          <div key={i} className="service-row non-compliant clickable-row">
                                            <span className="service-name">
                                              {svc.service}
                                              {svc.source === 'github' && (
                                                <span className="github-badge" title="Version from GitHub tag">GH</span>
                                              )}
                                            </span>
                                            <div className="service-versions">
                                              <div className="version-with-label">
                                                <span className="version-label">Current</span>
                                                <code className="service-version current">{svc.version}</code>
                                              </div>
                                              <ArrowRight size={10} className="version-arrow" />
                                              <div className="version-with-label">
                                                <span className="version-label">Expected</span>
                                                <code className="service-version expected">{svc.expected || alert.expectedVersion}</code>
                                              </div>
                                            </div>
                                          </div>
                                        ))}
                                        {alert.nonCompliantServices.length > 5 && (
                                          <button 
                                            className="service-row more clickable"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              setExpandedServiceLists(prev => ({ ...prev, [alert.id]: !prev[alert.id] }));
                                            }}
                                          >
                                            {expandedServiceLists[alert.id] 
                                              ? <><ChevronUp size={12} /> Show less</>
                                              : <><ChevronDown size={12} /> +{alert.nonCompliantServices.length - 5} more services</>
                                            }
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                  )}

                                  {/* Compliance ratio indicator */}
                                  {alert.complianceRatio !== undefined && (
                                    <div className="compliance-ratio">
                                      <div className="ratio-bar-track">
                                        <div 
                                          className={`ratio-bar-fill ${alert.complianceRatio >= 80 ? 'good' : alert.complianceRatio >= 50 ? 'warning' : 'critical'}`}
                                          style={{ width: `${alert.complianceRatio}%` }}
                                        />
                                      </div>
                                      <span className="ratio-text">{alert.complianceRatio}% compliant</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}

                      {!releaseComplianceCollapsed && groupedIssues.releaseCompliance.length > 3 && (
                        <button 
                          className="show-more-btn"
                          onClick={() => setShowAllCompliance(!showAllCompliance)}
                        >
                          {showAllCompliance ? (
                            <><ChevronUp size={14} /> Show less</>
                          ) : (
                            <><ChevronDown size={14} /> Show {groupedIssues.releaseCompliance.length - 3} more</>
                          )}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ActionableIssuesPanel;
