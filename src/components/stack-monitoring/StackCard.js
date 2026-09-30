import React, { useState } from 'react';
import { 
  Server,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Activity,
  RotateCcw,
  ExternalLink,
  Loader
} from 'lucide-react';
import DeploymentRow from './DeploymentRow';

/**
 * StackCard - Individual stack card showing deployments and health metrics
 */
const StackCard = ({ 
  stack, 
  stackCategory,
  categoryInfo,
  isCollapsed,
  isExpanded,
  onToggleCollapse,
  onToggleExpand,
  onDeploymentClick,
  onCopyKubectl,
  searchQuery,
  statusFilter
}) => {
  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle size={16} style={{ color: 'var(--accent-green)' }} />;
      case 'warning':
        return <AlertTriangle size={16} style={{ color: 'var(--accent-orange)' }} />;
      case 'critical':
        return <XCircle size={16} style={{ color: 'var(--accent-red)' }} />;
      case 'error':
        return <XCircle size={16} style={{ color: 'var(--text-muted)' }} />;
      case 'initializing':
        return <Loader size={16} className="spinning" style={{ color: 'var(--accent-blue, #3b82f6)' }} />;
      default:
        return <Activity size={16} style={{ color: 'var(--text-muted)' }} />;
    }
  };
  
  const getStatusColor = (status) => {
    switch (status) {
      case 'healthy': return 'var(--accent-green)';
      case 'warning': return 'var(--accent-orange)';
      case 'critical': return 'var(--accent-red)';
      case 'error': return 'var(--text-muted)';
      case 'initializing': return 'var(--accent-blue, #3b82f6)';
      default: return 'var(--text-muted)';
    }
  };
  
  // Filter deployments based on search and status
  const filterDeployments = (components) => {
    if (!components) return [];
    
    return components.filter(comp => {
      // Skip not_found in UI display
      if (comp.status === 'not_found') return false;
      
      // Search filter
      const searchMatch = !searchQuery || 
        comp.namespace?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        comp.deployment?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        comp.version?.toLowerCase().includes(searchQuery.toLowerCase());
      
      // Status filter
      const normalizedStatus = normalizeStatus(comp.status);
      const statusMatch = statusFilter === 'all' || normalizedStatus === statusFilter;
      
      return searchMatch && statusMatch;
    });
  };
  
  const normalizeStatus = (status) => {
    if (!status) return 'unknown';
    const lowerStatus = status.toLowerCase();
    if (lowerStatus === 'healthy') return 'healthy';
    if (lowerStatus.includes('unhealthy') || lowerStatus.includes('error') || lowerStatus.includes('critical')) {
      return 'critical';
    }
    return 'warning';
  };
  
  const filteredDeployments = filterDeployments(stack.components);
  const displayedDeployments = isExpanded ? filteredDeployments : filteredDeployments.slice(0, 5);
  const hasMore = filteredDeployments.length > 5;
  
  // Calculate stack-specific health
  const stackHealthPercent = stack.totalDeployments > 0 
    ? Math.round((stack.metrics.healthy / stack.totalDeployments) * 100)
    : 0;

  return (
    <div className={`stack-card status-${stack.status} ${isCollapsed ? 'collapsed' : ''}`} data-stack-id={stack.id}>
      {/* Stack Header */}
      <div className="stack-card-header" onClick={onToggleCollapse}>
        <div className="header-left">
          <Server size={18} style={{ color: getStatusColor(stack.status) }} />
          <div className="stack-info">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="stack-name">{stack.name}</span>
              {categoryInfo && (
                <span 
                  className="category-badge"
                  style={{ background: categoryInfo.color }}
                  title={categoryInfo.description}
                >
                  {categoryInfo.label}
                </span>
              )}
            </div>
            <span className="stack-region">{stack.region}</span>
          </div>
        </div>
        
        <div className="header-right">
          {/* Health Badge */}
          <div className={`health-badge status-${stack.status}`}>
            {getStatusIcon(stack.status)}
            <span>{stack.status === 'healthy' ? 'Healthy' : stack.status === 'initializing' ? 'Loading...' : stack.status}</span>
          </div>
          
          {/* Quick Stats */}
          {!isCollapsed && (
            <div className="quick-stats">
              <span className="stat healthy">
                <CheckCircle size={12} /> {stack.metrics.healthy}
              </span>
              {stack.metrics.warning > 0 && (
                <span className="stat warning">
                  <AlertTriangle size={12} /> {stack.metrics.warning}
                </span>
              )}
              {stack.metrics.critical > 0 && (
                <span className="stat critical">
                  <XCircle size={12} /> {stack.metrics.critical}
                </span>
              )}
              {stack.highRestartRateCount > 0 && (
                <span 
                  className="stat restarts high-rate" 
                  title={`${stack.highRestartRateCount} deployment(s) with high restart rate (${stack.restarts} total restarts)`}
                >
                  <RotateCcw size={12} /> {stack.highRestartRateCount} high
                </span>
              )}
              {stack.restarts > 0 && stack.highRestartRateCount === 0 && (
                <span 
                  className="stat restarts" 
                  title={`${stack.restarts} total restarts (rate is normal)`}
                >
                  <RotateCcw size={12} /> {stack.restarts}
                </span>
              )}
            </div>
          )}
          
          <button className="collapse-btn">
            {isCollapsed ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
          </button>
        </div>
      </div>
      
      {/* Stack Content */}
      {!isCollapsed && (
        <div className="stack-card-content">
          {/* Connection Error Banner */}
          {stack.connectionError && (
            <div className="connection-error-banner">
              <XCircle size={14} />
              <span>{stack.errorMessage || 'Connection error'}</span>
            </div>
          )}
          
          {/* Pods Summary */}
          <div className="pods-summary">
            <div className="pods-bar">
              <div 
                className="pods-ready" 
                style={{ width: `${stack.pods?.desired > 0 ? (stack.pods.ready / stack.pods.desired) * 100 : 0}%` }}
              />
            </div>
            <span className="pods-text">
              {stack.pods?.ready || 0}/{stack.pods?.desired || 0} pods ready
            </span>
          </div>
          
          {/* Deployments List */}
          <div className="deployments-list">
            {displayedDeployments.length === 0 && stack.status === 'initializing' ? (
              <div className="initializing-placeholder">
                <div className="shimmer-row" />
                <div className="shimmer-row short" />
                <div className="shimmer-row" />
                <span className="initializing-text">
                  <Loader size={12} className="spinning" /> Fetching deployment data...
                </span>
              </div>
            ) : displayedDeployments.length === 0 ? (
              <div className="no-deployments">
                {searchQuery || statusFilter !== 'all' 
                  ? 'No deployments match filters' 
                  : 'No deployments found'}
              </div>
            ) : (
              displayedDeployments.map((comp, idx) => (
                <DeploymentRow
                  key={`${comp.namespace}-${comp.deployment}-${idx}`}
                  deployment={comp}
                  stackId={stack.id}
                  onClick={() => onDeploymentClick(comp.namespace, comp.deployment, stack.id, comp.namespaceFull)}
                  onCopyKubectl={(e) => onCopyKubectl(e, comp.deployment, comp.namespaceFull || comp.namespace, stack.id)}
                />
              ))
            )}
          </div>
          
          {/* Show More/Less Button */}
          {hasMore && (
            <button 
              className="show-more-btn"
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand();
              }}
            >
              {isExpanded 
                ? `Show less` 
                : `Show ${filteredDeployments.length - 5} more`}
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default StackCard;
