/**
 * QuickStatusGrid - Compact grid showing all stacks at a glance
 * 
 * Features:
 * - Color-coded status tiles for each stack
 * - Shows deployment count, restarts, and health percentage
 * - Hover for detailed breakdown
 * - Click to scroll to stack card
 */
import React, { useMemo } from 'react';
import { Layers, RotateCcw, CheckCircle, AlertTriangle, XCircle, Activity } from 'lucide-react';

const QuickStatusGrid = ({ stackData, onStackClick }) => {
  // Calculate status for each stack - use pre-calculated metrics from stack data
  const stackStatuses = useMemo(() => {
    if (!stackData?.stacks) return [];
    
    return stackData.stacks.map(stack => {
      // Use pre-calculated metrics from the stack object
      const metrics = stack.metrics || {};
      const healthy = metrics.healthy || 0;
      const warning = metrics.warning || 0;
      const critical = metrics.critical || 0;
      const restarts = stack.restarts || 0;
      
      const total = stack.totalDeployments || (healthy + warning + critical);
      const healthPercent = total > 0 ? Math.round((healthy / total) * 100) : 100;
      
      // Determine overall status based on metrics
      let overallStatus = 'healthy';
      if (critical > 0) {
        overallStatus = 'critical';
      } else if (warning > 0 || restarts > 10) {
        overallStatus = 'warning';
      }
      
      // Format stack name
      let displayName = stack.name?.toUpperCase() || stack.id?.toUpperCase() || 'Unknown';
      displayName = displayName
        .replace(/^STACK[-_\s]*/i, '')
        .replace(/[-_\s]*STACK$/i, '');
      
      return {
        id: stack.id || stack.name,
        name: displayName,
        fullName: stack.name || stack.id,
        status: overallStatus,
        healthy,
        warning,
        critical,
        restarts,
        total,
        healthPercent,
        environment: stack.environment || 'unknown'
      };
    }).sort((a, b) => {
      // Sort: critical first, then warning, then healthy
      const statusOrder = { critical: 0, warning: 1, healthy: 2 };
      return statusOrder[a.status] - statusOrder[b.status];
    });
  }, [stackData]);

  if (!stackStatuses.length) {
    return (
      <div className="quick-status-grid empty">
        <Layers size={24} />
        <span>Waiting for stack data...</span>
      </div>
    );
  }

  // Calculate totals
  const totals = stackStatuses.reduce((acc, s) => ({
    healthy: acc.healthy + (s.status === 'healthy' ? 1 : 0),
    warning: acc.warning + (s.status === 'warning' ? 1 : 0),
    critical: acc.critical + (s.status === 'critical' ? 1 : 0),
    totalRestarts: acc.totalRestarts + s.restarts
  }), { healthy: 0, warning: 0, critical: 0, totalRestarts: 0 });

  return (
    <div className="quick-status-grid">
      <div className="grid-header">
        <div className="grid-title">
          <Activity size={16} />
          <span>Quick Status</span>
        </div>
        <div className="grid-summary">
          <span className="summary-badge healthy" title="Healthy stacks">
            <CheckCircle size={11} /> {totals.healthy}
          </span>
          {totals.warning > 0 && (
            <span className="summary-badge warning" title="Stacks with warnings">
              <AlertTriangle size={11} /> {totals.warning}
            </span>
          )}
          {totals.critical > 0 && (
            <span className="summary-badge critical" title="Critical stacks">
              <XCircle size={11} /> {totals.critical}
            </span>
          )}
        </div>
      </div>

      <div className="status-grid">
        {stackStatuses.map(stack => (
          <div
            key={stack.id}
            className={`status-tile ${stack.status}`}
            onClick={() => onStackClick?.(stack.id)}
            title={`${stack.fullName}\n${stack.healthy} healthy, ${stack.warning} warning, ${stack.critical} critical\n${stack.restarts} restarts`}
          >
            <div className="tile-name">{stack.name}</div>
            <div className="tile-stats">
              <span className="tile-health">{stack.healthPercent}%</span>
              {stack.restarts > 0 && (
                <span className="tile-restarts" title={`${stack.restarts} restarts`}>
                  <RotateCcw size={9} /> {stack.restarts}
                </span>
              )}
            </div>
            <div className="tile-bar">
              <div 
                className="tile-bar-fill" 
                style={{ width: `${stack.healthPercent}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="grid-footer">
        <span className="footer-info">{stackStatuses.length} stacks monitored</span>
        {totals.totalRestarts > 0 && (
          <span className="footer-restarts">
            <RotateCcw size={10} /> {totals.totalRestarts} total restarts
          </span>
        )}
      </div>
    </div>
  );
};

export default QuickStatusGrid;
