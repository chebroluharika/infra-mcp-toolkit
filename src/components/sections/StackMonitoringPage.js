import React, { useState, useCallback, useMemo } from 'react';
import { 
  Activity,
  RefreshCw,
  Search,
  Filter,
  Layers,
  ChevronDown,
  ChevronUp,
  Clock,
  GitCompare,
  CheckCircle,
  AlertTriangle,
  XCircle,
  AlertCircle,
  Loader
} from 'lucide-react';

// Stack monitoring components
import useStackMonitoring from '../stack-monitoring/hooks/useStackMonitoring';
import HealthScoreCard from '../stack-monitoring/HealthScoreCard';
import ActionableIssuesPanel from '../stack-monitoring/ActionableIssuesPanel';
import StackCard from '../stack-monitoring/StackCard';
import DeploymentDetailPanel from '../stack-monitoring/DeploymentDetailPanel';
import HealthTrendChart from '../stack-monitoring/HealthTrendChart';
import ProblematicDeploymentsChart from '../stack-monitoring/ProblematicDeploymentsChart';
import StackHealthSignals from '../stack-monitoring/StackHealthSignals';

// Styles
import '../../styles/stack-monitoring.css';

/**
 * StackMonitoringPage - Refactored stack monitoring page
 * 
 * Features:
 * - Weighted health score with actionable breakdown
 * - Prioritized issues panel showing what needs attention
 * - Stack cards with deployments
 * - Side panel for deployment details
 */
const StackMonitoringPage = ({ selectedRelease }) => {
  // Use the custom hook for data management
  const {
    loading,
    refreshing,
    error,
    stackData,
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
    loadingRestarts,
    fetchStackMonitoring,
    openDeploymentDetails,
    closeSidePanel,
    fetchPodLogs,
    fetchStackHistory,
    fetchDeploymentHistory,
    setSelectedPodForLogs,
    calculateHealthScore,
    getActionableIssues,
  } = useStackMonitoring();
  
  // Local UI state
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [envFilter, setEnvFilter] = useState('all');
  const [viewMode, setViewMode] = useState('dashboard');
  const [expandedStacks, setExpandedStacks] = useState({});
  const [collapsedStacks, setCollapsedStacks] = useState({});
  const [issuesPanelCollapsed, setIssuesPanelCollapsed] = useState(false);
  const [detailActiveTab, setDetailActiveTab] = useState('overview');
  const [copiedCommand, setCopiedCommand] = useState(null);
  
  // Map stack IDs to contexts
  const STACK_CONTEXTS = {
    'qa01': 'stork-qa01-mp-npe-iad0-nc1',
    'stg01': 'stork-stg01-mp-iad0-nc4',
    'stg01_mplegacy': 'stork-stg01-mp-iad0-nc4'
  };
  
  // Handle refresh
  const handleRefresh = () => {
    fetchStackMonitoring(true, false);
  };
  
  // Copy kubectl command
  const copyKubectlCommand = (e, deployment, namespace, stackId) => {
    e.stopPropagation();
    const deploymentName = deployment.split('/')[0];
    const context = STACK_CONTEXTS[stackId] || stackId;
    const command = `kubectl get deployment ${deploymentName} -n ${namespace} -o wide --context=${context}`;
    navigator.clipboard.writeText(command).then(() => {
      setCopiedCommand(`${deployment}-${stackId}`);
      setTimeout(() => setCopiedCommand(null), 2000);
    });
  };
  
  // Toggle stack expansion
  const toggleStackExpand = (stackId) => {
    setExpandedStacks(prev => ({
      ...prev,
      [stackId]: !prev[stackId]
    }));
  };
  
  // Toggle stack collapse
  const toggleStackCollapse = (stackId) => {
    setCollapsedStacks(prev => ({
      ...prev,
      [stackId]: !prev[stackId]
    }));
  };
  
  // Environment category classification
  // Based on your 19 stacks categorization
  const ENVIRONMENT_CATEGORIES = {
    // NPE - Non-production environments (2)
    npe: ['qa01', 'npa01'],
    
    // Staging environments (3)
    staging: ['stg01', 'stg01_mplegacy', 'fed1mp', 'stg01-mp', 'stg01-mplegacy', 'fed1-mp', 'betaskope'],
    
    // Pre-prod environments (2)
    preprod: ['devint', 'fed-preprod', 'fedpreprod', 'fed02-mp-preprod', 'fed02mppreprod', 'fed02'],
    
    // Production environments (15)
    prod: [
      'fr4', 'sin2', 'lon3', 'sjc2', 'sv5', 'dfw3', 'sjc1', 'mel2', 
      'ruh1', 'fra2', 'zur2', 'am2', 'bom3', 'fedramp', 'fed-prod', 'pbmm', 'pbmm-prod'
    ]
  };
  
  // Get environment category for a stack
  const getStackCategory = (stackId) => {
    if (!stackId) return 'unknown';
    const id = stackId.toLowerCase().replace(/-/g, '').replace(/_/g, '');
    const idWithDash = stackId.toLowerCase();
    
    for (const [category, stacks] of Object.entries(ENVIRONMENT_CATEGORIES)) {
      for (const pattern of stacks) {
        const normalizedPattern = pattern.replace(/-/g, '').replace(/_/g, '');
        if (id === normalizedPattern || id.startsWith(normalizedPattern) || 
            idWithDash === pattern || idWithDash.startsWith(pattern)) {
          return category;
        }
      }
    }
    
    // Fallback: check if it looks like a production stack (pe- prefix or datacenter codes)
    const pePatterns = ['pe-', 'sjc', 'fra', 'lon', 'sin', 'mel', 'dfw', 'ruh', 'zur', 'am2', 'fr4', 'sv5'];
    if (pePatterns.some(p => idWithDash.startsWith(p) || idWithDash.includes(p))) {
      return 'prod';
    }
    
    return 'unknown';
  };
  
  // Get category display info
  const getCategoryInfo = (category) => {
    const info = {
      npe: { label: 'NPE', color: '#3b82f6', description: 'Non-Production Automation' },
      staging: { label: 'Staging', color: '#8b5cf6', description: 'Staging Environments' },
      preprod: { label: 'Pre-Prod', color: '#f59e0b', description: 'Pre-Production' },
      prod: { label: 'Production', color: '#10b981', description: 'Production Environments' },
      unknown: { label: 'Other', color: '#6b7280', description: 'Other Environments' }
    };
    return info[category] || info.unknown;
  };
  
  // Filter stacks by environment category and status
  const filterStacks = (stacks) => {
    if (!stacks) return [];
    return stacks.filter(stack => {
      // Environment filter
      if (envFilter !== 'all') {
        const category = getStackCategory(stack.id);
        if (envFilter !== category) return false;
      }
      // Status filter (filter by stack status)
      if (statusFilter !== 'all') {
        if (stack.status !== statusFilter) return false;
      }
      return true;
    });
  };
  
  // Get comparison data for version comparison view
  const getComparisonData = useMemo(() => {
    if (!stackData?.stacks) return [];
    
    const deploymentMap = {};
    const filteredStacksList = filterStacks(stackData.stacks);
    
    filteredStacksList.forEach(stack => {
      (stack.components || []).forEach(comp => {
        // Skip not_found deployments
        if (comp.status === 'not_found') return;
        
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
          restarts: comp.restarts,
          restartRateDisplay: comp.restartRateDisplay,
          restartRateHigh: comp.restartRateHigh,
          crashLoop: comp.crashLoop
        };
      });
    });
    
    // Sort by namespace then deployment name
    return Object.values(deploymentMap).sort((a, b) => {
      if (a.namespace !== b.namespace) return a.namespace.localeCompare(b.namespace);
      return a.deployment.localeCompare(b.deployment);
    });
  }, [stackData, envFilter]);
  
  // Check if versions match across all stacks
  const hasVersionMismatch = (stacksData) => {
    const versions = Object.values(stacksData)
      .map(s => s.version)
      .filter(v => v && v !== 'error' && v !== 'unknown');
    const uniqueVersions = [...new Set(versions)];
    return uniqueVersions.length > 1;
  };
  
  // Normalize status for CSS class
  const normalizeStatus = (status) => {
    if (!status) return 'unknown';
    const s = status.toLowerCase();
    if (s === 'healthy' || s === 'running') return 'healthy';
    if (s.includes('unhealthy') || s.includes('error') || s === 'critical') return 'critical';
    if (s.includes('warning') || s === 'pending') return 'warning';
    return 'unknown';
  };
  
  // Get status icon
  const getStatusIcon = (status) => {
    const s = normalizeStatus(status);
    switch(s) {
      case 'healthy': return <CheckCircle size={14} className="status-icon healthy" />;
      case 'critical': return <XCircle size={14} className="status-icon critical" />;
      case 'warning': return <AlertTriangle size={14} className="status-icon warning" />;
      default: return <AlertCircle size={14} className="status-icon unknown" />;
    }
  };
  
  // Count stacks by category for filter badges
  const stackCategoryCounts = useMemo(() => {
    if (!stackData?.stacks) return {};
    const counts = { all: 0, npe: 0, staging: 0, preprod: 0, prod: 0 };
    stackData.stacks.forEach(stack => {
      counts.all++;
      const category = getStackCategory(stack.id);
      if (counts[category] !== undefined) counts[category]++;
    });
    return counts;
  }, [stackData]);
  
  // Get health score
  const healthScore = calculateHealthScore();
  
  // Get actionable issues
  const issues = getActionableIssues();
  
  // Filter stacks for display
  const filteredStacks = filterStacks(stackData?.stacks || []);

  return (
    <div className="stack-monitoring-page">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><Activity size={24} /> Stack Monitoring</h1>
          <p>Real-time monitoring of stack infrastructure and deployments</p>
        </div>
        <div className="header-actions">
          {stackData?.cached && (
            <span className="cache-indicator">
              <Clock size={14} />
              Cached {Math.round(stackData.cacheAge || 0)}s ago
            </span>
          )}
          
          <button 
            className="action-btn secondary" 
            onClick={handleRefresh} 
            disabled={loading || refreshing}
          >
            <RefreshCw size={16} className={loading || refreshing ? 'spinning' : ''} />
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>
      
      {/* Loading State */}
      {loading && !stackData && (
        <div className="loading-skeleton">
          <div className="skeleton-health-card pulse" />
          <div className="skeleton-issues-panel pulse" />
          <div className="skeleton-stacks">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="skeleton-stack-card pulse" />
            ))}
          </div>
        </div>
      )}
      
      {/* Error State */}
      {error && !stackData && (
        <div className="error-banner">
          <Activity size={20} />
          <div>
            <strong>Error loading stack data</strong>
            <p>{error}</p>
          </div>
          <button onClick={handleRefresh}>Retry</button>
        </div>
      )}
      
      {/* Main Content */}
      {stackData && (
        <>
          {/* Top Section: Health Score + Issues */}
          <div className="monitoring-top-section">
            <HealthScoreCard 
              healthScore={healthScore}
              stackData={stackData}
              onStatClick={(status) => {
                // When clicking on a stat (healthy/warning/critical), 
                // find matching stacks and expand them
                const matchingStacks = stackData?.stacks?.filter(s => s.status === status) || [];
                
                if (matchingStacks.length > 0) {
                  // Set status filter to show only this status
                  setStatusFilter(status);
                  
                  // Expand all matching stacks (uncollapse them)
                  const newCollapsed = { ...collapsedStacks };
                  const newExpanded = { ...expandedStacks };
                  
                  matchingStacks.forEach(stack => {
                    newCollapsed[stack.id] = false; // Uncollapse the card
                    newExpanded[stack.id] = true;   // Expand to show all deployments
                  });
                  
                  setCollapsedStacks(newCollapsed);
                  setExpandedStacks(newExpanded);
                  
                  // Scroll to the stacks grid section
                  setTimeout(() => {
                    const gridElement = document.querySelector('.stacks-grid');
                    if (gridElement) {
                      gridElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                  }, 100);
                }
              }}
            />
            <ActionableIssuesPanel
              issues={issues}
              collapsed={issuesPanelCollapsed}
              onToggleCollapse={() => setIssuesPanelCollapsed(!issuesPanelCollapsed)}
              onViewLogs={(ns, dep, stack, nsFull) => {
                openDeploymentDetails(ns, dep, stack, nsFull);
                setDetailActiveTab('logs');
              }}
              onViewDetails={(ns, dep, stack, nsFull) => {
                openDeploymentDetails(ns, dep, stack, nsFull);
                setDetailActiveTab('overview');
              }}
              onCopyKubectl={copyKubectlCommand}
              onViewComparison={() => setViewMode('compare')}
              lastUpdated={stackData?.lastUpdated}
              loadingRestarts={loadingRestarts}
            />
          </div>
          
          {/* Initializing Banner */}
          {stackData?.initializing && stackData?.initializingStacks > 0 && (
            <div className="initializing-banner">
              <Loader size={14} className="spinning" />
              <span>
                {stackData.initializingStacks} stack{stackData.initializingStacks !== 1 ? 's' : ''} still loading — 
                Kubernetes connections initializing in background
              </span>
            </div>
          )}

          {/* Stack Health Signals - Sparkline grid per stack */}
          {stackData?.stacks?.length > 0 && (
            <div className="health-signals-section">
              <StackHealthSignals 
                stackData={stackData}
                onStackClick={(stackId) => {
                  const stack = stackData?.stacks?.find(s => s.id === stackId);
                  if (stack) {
                    // Reset filters so the stack is visible
                    setEnvFilter('all');
                    setStatusFilter('all');
                    // Expand this stack
                    setCollapsedStacks(prev => ({ ...prev, [stackId]: false }));
                    setExpandedStacks(prev => ({ ...prev, [stackId]: true }));
                    // Scroll to the specific stack card
                    setTimeout(() => {
                      const stackCard = document.querySelector(`[data-stack-id="${stackId}"]`);
                      if (stackCard) {
                        stackCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        stackCard.classList.add('highlight-pulse');
                        setTimeout(() => stackCard.classList.remove('highlight-pulse'), 2000);
                      }
                    }, 150);
                  }
                }}
              />
            </div>
          )}

          {/* Health Charts Row - Only show when we have stack data */}
          {stackData?.stacks?.length > 0 && (
            <div className="health-charts-row two-charts">
              <HealthTrendChart />
              <ProblematicDeploymentsChart 
                stackData={stackData}
                onDeploymentClick={(ns, dep, stack, nsFull) => {
                  openDeploymentDetails(ns, dep, stack, nsFull);
                  setDetailActiveTab('overview');
                }}
              />
            </div>
          )}
          
          {/* Filters Bar */}
          <div className="filters-bar">
            <div className="search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search deployments..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            
            <div className="filter-group">
              <Filter size={14} />
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="all">All Status</option>
                <option value="healthy">Healthy</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            
            {/* Environment Category Filter Buttons */}
            <div className="env-filter-buttons">
              {[
                { id: 'all', label: 'All', color: '#6b7280' },
                { id: 'prod', label: 'Prod', color: '#10b981' },
                { id: 'preprod', label: 'Pre-Prod', color: '#f59e0b' },
                { id: 'staging', label: 'Staging', color: '#8b5cf6' },
                { id: 'npe', label: 'NPE', color: '#3b82f6' }
              ].map(env => (
                <button
                  key={env.id}
                  className={`env-filter-btn ${envFilter === env.id ? 'active' : ''}`}
                  onClick={() => setEnvFilter(env.id)}
                  style={{ 
                    '--env-color': env.color,
                    borderColor: envFilter === env.id ? env.color : 'transparent'
                  }}
                >
                  <span className="env-label">{env.label}</span>
                  <span className="env-count">{stackCategoryCounts[env.id] || 0}</span>
                </button>
              ))}
            </div>
            
            <div className="view-toggle">
              <button 
                className={viewMode === 'dashboard' ? 'active' : ''} 
                onClick={() => setViewMode('dashboard')}
                title="Dashboard View"
              >
                <Layers size={16} />
              </button>
              <button 
                className={viewMode === 'compare' ? 'active' : ''} 
                onClick={() => setViewMode('compare')}
                title="Version Comparison"
              >
                <GitCompare size={16} />
              </button>
            </div>
          </div>
          
          {/* Stack Cards Grid (Dashboard & Grid views) */}
          {(viewMode === 'dashboard' || viewMode === 'grid') && (
            <div className={`stacks-grid view-${viewMode}`}>
              {filteredStacks.length === 0 ? (
                <div className="empty-state">
                  No stacks match the current filters
                </div>
              ) : (
                filteredStacks.map(stack => (
                  <StackCard
                    key={stack.id}
                    stack={stack}
                    stackCategory={getStackCategory(stack.id)}
                    categoryInfo={getCategoryInfo(getStackCategory(stack.id))}
                    isCollapsed={collapsedStacks[stack.id]}
                    isExpanded={expandedStacks[stack.id]}
                    onToggleCollapse={() => toggleStackCollapse(stack.id)}
                    onToggleExpand={() => toggleStackExpand(stack.id)}
                    onDeploymentClick={openDeploymentDetails}
                    onCopyKubectl={copyKubectlCommand}
                    searchQuery={searchQuery}
                    statusFilter={statusFilter}
                  />
                ))
              )}
            </div>
          )}
          
          {/* Version Comparison Table View */}
          {viewMode === 'compare' && (
            <div className="comparison-view-container">
              <div className="comparison-header">
                <GitCompare size={20} className="comparison-icon" />
                <h3>Version Comparison Across Stacks</h3>
                <span className="comparison-stats">
                  {getComparisonData.length} deployments · {filteredStacks.length} stacks
                </span>
              </div>
              
              <div className="comparison-table-wrapper">
                <div className="comparison-table-scroll" style={{ 
                  minWidth: `${250 + (filteredStacks.length * 160)}px`
                }}>
                  <table className="comparison-table">
                    <thead>
                      <tr>
                        <th className="deployment-col sticky-col">
                          <div className="th-content">Deployment</div>
                        </th>
                        {filteredStacks.map(stack => {
                          const category = getStackCategory(stack.id);
                          const catInfo = getCategoryInfo(category);
                          return (
                            <th key={stack.id} className="stack-col">
                              <div className="stack-header-cell">
                                <div className="stack-name-row">
                                  {getStatusIcon(stack.status)}
                                  <span className="stack-name">{stack.id.toUpperCase()}</span>
                                </div>
                                <div className="stack-meta">
                                  <span 
                                    className="stack-category-badge"
                                    style={{ background: catInfo.color }}
                                  >
                                    {catInfo.label}
                                  </span>
                                  <span className="stack-region">{stack.region}</span>
                                </div>
                              </div>
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {getComparisonData.length === 0 ? (
                        <tr>
                          <td colSpan={filteredStacks.length + 1} className="empty-comparison">
                            No deployments match the current filters
                          </td>
                        </tr>
                      ) : (
                        getComparisonData.map((row, idx) => {
                          const hasMismatch = hasVersionMismatch(row.stacks);
                          return (
                            <tr 
                              key={`${row.namespace}-${row.deployment}-${idx}`}
                              className={hasMismatch ? 'mismatch-row' : ''}
                            >
                              <td className="deployment-col sticky-col">
                                <div className="deployment-info">
                                  {hasMismatch && (
                                    <span className="mismatch-indicator" title="Version mismatch detected">
                                      <AlertTriangle size={12} />
                                    </span>
                                  )}
                                  <div className="deployment-names">
                                    <span className="namespace-name">{row.namespace}</span>
                                    <span className="deployment-name">{row.deployment}</span>
                                  </div>
                                </div>
                              </td>
                              {filteredStacks.map(stack => {
                                const stackInfo = row.stacks[stack.id];
                                if (!stackInfo) {
                                  return (
                                    <td key={stack.id} className="stack-col empty-cell">
                                      <span className="no-data">—</span>
                                    </td>
                                  );
                                }
                                return (
                                  <td 
                                    key={stack.id} 
                                    className={`stack-col ${stackInfo.crashLoop ? 'crash-loop' : ''}`}
                                  >
                                    <div className="stack-deployment-info">
                                      <span className={`status-badge status-${normalizeStatus(stackInfo.status)}`}>
                                        {stackInfo.status}
                                      </span>
                                      <code className="version-tag">
                                        {stackInfo.version || '—'}
                                      </code>
                                      {stackInfo.replicas && (
                                        <span className={`replica-count ${
                                          stackInfo.replicas.ready < stackInfo.replicas.desired 
                                            ? 'degraded' : 'healthy'
                                        }`}>
                                          {stackInfo.replicas.ready}/{stackInfo.replicas.desired} pods
                                        </span>
                                      )}
                                      {stackInfo.crashLoop && (
                                        <span className="crash-badge">CrashLoop</span>
                                      )}
                                      {stackInfo.restarts > 0 && (
                                        <span 
                                          className={`restarts-count ${stackInfo.restartRateHigh ? 'high-rate' : ''}`}
                                          title={`${stackInfo.restarts} total restarts${stackInfo.restartRateHigh ? ' - HIGH RATE' : ''}`}
                                        >
                                          {stackInfo.restartRateDisplay || `${stackInfo.restarts}`} restarts
                                        </span>
                                      )}
                                    </div>
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
              
              {/* Mismatch Legend */}
              {getComparisonData.some(row => hasVersionMismatch(row.stacks)) && (
                <div className="comparison-legend">
                  <span className="legend-item mismatch">
                    <AlertTriangle size={12} />
                    Version mismatch detected
                  </span>
                </div>
              )}
            </div>
          )}
          
          {/* Deployment Detail Side Panel */}
          <DeploymentDetailPanel
            isOpen={sidePanelOpen}
            deployment={selectedDeployment}
            details={deploymentDetails}
            loading={loadingDetails}
            error={detailsError}
            podLogs={podLogs}
            loadingLogs={loadingLogs}
            selectedPodForLogs={selectedPodForLogs}
            stackHistory={stackHistory}
            loadingHistory={loadingHistory}
            activeTab={detailActiveTab}
            onClose={closeSidePanel}
            onTabChange={setDetailActiveTab}
            onFetchLogs={fetchPodLogs}
            onSelectPod={setSelectedPodForLogs}
            onFetchHistory={fetchDeploymentHistory}
          />
        </>
      )}
    </div>
  );
};

export default StackMonitoringPage;
