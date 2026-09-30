/**
 * StackHealthSignals - Horizontal sparkline strip showing stack health trends
 * 
 * Compact horizontal layout with mini cards for each stack showing:
 * - Stack name
 * - Mini sparkline (24h trend)
 * - Current health percentage with status dot
 */
import React, { useEffect, useState, useMemo } from 'react';
import { RefreshCw, Activity } from 'lucide-react';
import api from '../../services/api';

/**
 * Mini Sparkline - compact SVG sparkline for cards
 */
const MiniSparkline = ({ data, width = 60, height = 20, color = '#4caf50' }) => {
  if (!data || data.length < 2) {
    return (
      <svg width={width} height={height} className="mini-sparkline empty">
        <line x1="0" y1={height/2} x2={width} y2={height/2} stroke="var(--border-color)" strokeDasharray="2 2" />
      </svg>
    );
  }

  const max = Math.max(...data, 100);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  
  // Calculate points for the sparkline
  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(' ');

  // Create area fill path
  const areaPath = `M0,${height} L${data.map((value, index) => {
    const x = (index / (data.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(' L')} L${width},${height} Z`;

  const gradientId = `miniSparkGrad-${color.replace('#', '')}`;

  return (
    <svg width={width} height={height} className="mini-sparkline">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0.1" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
};

/**
 * Main StackHealthSignals component - Horizontal layout
 * @param {Object} stackData - Current stack data with health counts
 * @param {Function} onStackClick - Callback when a stack is clicked
 */
const StackHealthSignals = ({ stackData, onStackClick }) => {
  const [historyData, setHistoryData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchHistory();
  }, []);

  const fetchHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getStackHistory(24);
      setHistoryData(data);
    } catch (err) {
      setError(err.message || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  };
  
  // Build current health map from stackData prop (more reliable than history summary)
  const currentHealthMap = useMemo(() => {
    const map = {};
    if (stackData?.stacks) {
      stackData.stacks.forEach(stack => {
        // Stack metrics are under stack.metrics.healthy/warning/critical
        const metrics = stack.metrics || {};
        const healthy = metrics.healthy || 0;
        const warning = metrics.warning || 0;
        const critical = metrics.critical || 0;
        const total = healthy + warning + critical;
        
        if (total > 0) {
          map[stack.id] = {
            healthy: healthy,
            total: total,
            healthPct: Math.round((healthy / total) * 100)
          };
        }
      });
    }
    return map;
  }, [stackData]);

  // Process history data into per-stack sparkline data
  const stackSignals = useMemo(() => {
    // Get all stack IDs from current data and history
    const allStacks = new Set(Object.keys(currentHealthMap));
    
    if (historyData?.history) {
      historyData.history.forEach(snapshot => {
        Object.keys(snapshot.summary || {}).forEach(stackId => {
          allStacks.add(stackId);
        });
      });
    }
    
    if (allStacks.size === 0) {
      return [];
    }

    // Build per-stack health percentage arrays
    const signals = Array.from(allStacks).map(stackId => {
      // Get sparkline data from history (if available)
      const healthData = (historyData?.history || []).map(snapshot => {
        const stackSummary = snapshot.summary?.[stackId];
        if (!stackSummary || stackSummary.total === 0) {
          return null;
        }
        return Math.round((stackSummary.healthy / stackSummary.total) * 100);
      }).filter(v => v !== null);

      // Use current health from stackData prop (more reliable)
      const currentData = currentHealthMap[stackId];
      const currentHealth = currentData?.healthPct ?? null;
      const total = currentData?.total || 0;
      const healthy = currentData?.healthy || 0;

      // Determine sparkline color based on current health
      let sparkColor = '#4caf50';
      let status = 'healthy';
      if (currentHealth !== null) {
        if (currentHealth < 80) {
          sparkColor = '#f44336';
          status = 'critical';
        } else if (currentHealth < 95) {
          sparkColor = '#ff9800';
          status = 'warning';
        }
      }

      return {
        stackId,
        stackName: stackId.toUpperCase(),
        healthData,
        currentHealth,
        sparkColor,
        status,
        total,
        healthy,
      };
    });

    // Filter out stacks with no current data, then sort
    return signals
      .filter(s => s.currentHealth !== null)
      .sort((a, b) => {
        const statusOrder = { critical: 0, warning: 1, healthy: 2 };
        const aOrder = statusOrder[a.status] ?? 3;
        const bOrder = statusOrder[b.status] ?? 3;
        if (aOrder !== bOrder) return aOrder - bOrder;
        return a.stackId.localeCompare(b.stackId);
      });
  }, [historyData, currentHealthMap]);

  if (loading) {
    return (
      <div className="stack-health-signals-horizontal loading">
        <div className="signals-header-h">
          <Activity size={14} />
          <span>Stack Health Signals based on pod/deployment status (24h)</span>
        </div>
        <div className="signals-loading-h">
          <RefreshCw size={14} className="spinning" />
          <span>Loading...</span>
        </div>
      </div>
    );
  }

  if (error || stackSignals.length === 0) {
    return (
      <div className="stack-health-signals-horizontal empty">
        <div className="signals-header-h">
          <Activity size={14} />
          <span>Stack Health Signals based on pod/deployment status (24h)</span>
        </div>
        <div className="signals-empty-h">
          {error ? (
            <>
              <span>{error}</span>
              <button onClick={fetchHistory} className="retry-btn-h">Retry</button>
            </>
          ) : (
            <span>No historical data - snapshots collected hourly</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack-health-signals-horizontal">
      <div className="signals-header-h">
        <Activity size={14} />
        <span>Stack Health Signals based on pod/deployment status (24h)</span>
        <button onClick={fetchHistory} className="refresh-btn-h" title="Refresh">
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="signals-strip">
        {stackSignals.map(signal => (
          <div 
            key={signal.stackId}
            className={`signal-card ${signal.status}`}
            onClick={() => onStackClick?.(signal.stackId)}
            title={`${signal.stackName}: ${signal.healthy}/${signal.total} healthy`}
          >
            <div className="signal-card-header">
              <span className="stack-name">{signal.stackName}</span>
              <span className={`status-dot ${signal.status}`} />
            </div>
            <MiniSparkline 
              data={signal.healthData}
              width={70}
              height={24}
              color={signal.sparkColor}
            />
            <div className="signal-card-footer">
              <span className="health-pct">
                {signal.currentHealth !== null ? `${signal.currentHealth}%` : 'N/A'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default StackHealthSignals;
