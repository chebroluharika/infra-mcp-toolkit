/**
 * ProblematicDeploymentsChart - Visual chart showing deployments that need immediate attention
 * 
 * Aggregates issues across all stacks to show:
 * - Which deployments have the most problems (restarts, crashes, errors)
 * - Issue breakdown per deployment (color-coded bars)
 * - Quick actions to investigate
 */
import React, { useMemo, useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';
import { 
  AlertTriangle, 
  RotateCcw, 
  Zap, 
  XCircle,
  Eye,
  ChevronDown,
  ChevronUp,
  Server,
  Clock
} from 'lucide-react';

const ISSUE_COLORS = {
  crashLoop: '#dc2626',
  restarts: '#f59e0b', 
  unhealthy: '#ef4444',
  errors: '#e11d48'
};

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const data = payload[0]?.payload;
    if (!data) return null;
    
    return (
      <div className="problematic-tooltip">
        <div className="tooltip-header">
          <span className="deployment-name">{data.deployment}</span>
          <span className="namespace">{data.namespace}</span>
        </div>
        <div className="tooltip-metrics">
          {data.crashLoops > 0 && (
            <div className="metric crash">
              <Zap size={12} />
              <span>{data.crashLoops} CrashLoop{data.crashLoops > 1 ? 's' : ''}</span>
            </div>
          )}
          {data.restarts > 0 && (
            <div className="metric restarts">
              <RotateCcw size={12} />
              <span>{data.restarts} Restart{data.restarts > 1 ? 's' : ''}</span>
            </div>
          )}
          {data.unhealthy > 0 && (
            <div className="metric unhealthy">
              <XCircle size={12} />
              <span>{data.unhealthy} Unhealthy</span>
            </div>
          )}
        </div>
        <div className="tooltip-stacks">
          <span className="stacks-label">Affected stacks:</span>
          <span className="stacks-list">{data.stacks.join(', ')}</span>
        </div>
      </div>
    );
  }
  return null;
};

const ProblematicDeploymentsChart = ({ stackData, onDeploymentClick }) => {
  const [showAll, setShowAll] = useState(false);
  const MAX_VISIBLE = 8;

  const problematicDeployments = useMemo(() => {
    if (!stackData?.stacks) return [];

    const deploymentIssues = {};

    stackData.stacks.forEach(stack => {
      (stack.components || []).forEach(comp => {
        const key = `${comp.namespace}/${comp.deployment}`;
        
        if (!deploymentIssues[key]) {
          deploymentIssues[key] = {
            key,
            namespace: comp.namespace,
            namespaceFull: comp.namespaceFull || comp.namespace,
            deployment: comp.deployment,
            crashLoops: 0,
            restarts: 0,
            unhealthy: 0,
            stacks: [],
            score: 0
          };
        }

        const entry = deploymentIssues[key];
        
        if (comp.crashLoop) {
          entry.crashLoops++;
          entry.score += 100;
        }
        // Use restart rate instead of raw count for scoring
        if (comp.restartRateHigh) {
          entry.restarts += comp.restarts;
          entry.score += 30; // High restart rate adds to score
        } else if (comp.restarts > 0) {
          entry.restarts += comp.restarts;
          // Low restart rate doesn't significantly impact score
          entry.score += 1;
        }
        if (comp.status?.includes('unhealthy') || comp.status === 'critical') {
          entry.unhealthy++;
          entry.score += 50;
        }
        
        if (comp.crashLoop || comp.restartRateHigh || comp.status?.includes('unhealthy')) {
          if (!entry.stacks.includes(stack.id.toUpperCase())) {
            entry.stacks.push(stack.id.toUpperCase());
          }
        }
      });
    });

    return Object.values(deploymentIssues)
      .filter(d => d.score > 0)
      .sort((a, b) => b.score - a.score);
  }, [stackData]);

  if (problematicDeployments.length === 0) {
    return (
      <div className="problematic-deployments-chart empty">
        <Server size={24} />
        <span>All deployments healthy</span>
        <p>No critical issues detected across stacks</p>
      </div>
    );
  }

  const visibleDeployments = showAll 
    ? problematicDeployments 
    : problematicDeployments.slice(0, MAX_VISIBLE);
  
  const hasMore = problematicDeployments.length > MAX_VISIBLE;
  const hiddenCount = problematicDeployments.length - MAX_VISIBLE;

  const chartData = visibleDeployments.map(d => ({
    ...d,
    name: d.deployment.length > 20 ? d.deployment.slice(0, 18) + '...' : d.deployment,
    fullName: d.deployment
  }));

  const getBarColor = (entry) => {
    if (entry.crashLoops > 0) return ISSUE_COLORS.crashLoop;
    if (entry.unhealthy > 0) return ISSUE_COLORS.unhealthy;
    return ISSUE_COLORS.restarts;
  };

  // Parse custom timestamp format: "2026-03-24 06:39:02 PM IST / 2026-03-24 01:09:02 PM GMT"
  const parseTimestamp = (timestampStr) => {
    if (!timestampStr) return null;
    
    // Try standard Date parsing first (for ISO format)
    let date = new Date(timestampStr);
    if (!isNaN(date.getTime())) return date;
    
    // Handle custom format: "YYYY-MM-DD HH:MM:SS AM/PM TZ / ..."
    // Extract the GMT part (after the /) for consistent parsing
    const parts = timestampStr.split(' / ');
    const gmtPart = parts[1] || parts[0];
    
    // Parse "2026-03-24 01:09:02 PM GMT" format
    const match = gmtPart.match(/(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)/i);
    if (match) {
      const [, datePart, hours, minutes, seconds, ampm] = match;
      let hour = parseInt(hours, 10);
      if (ampm.toUpperCase() === 'PM' && hour !== 12) hour += 12;
      if (ampm.toUpperCase() === 'AM' && hour === 12) hour = 0;
      
      date = new Date(`${datePart}T${hour.toString().padStart(2, '0')}:${minutes}:${seconds}Z`);
      if (!isNaN(date.getTime())) return date;
    }
    
    return null;
  };

  // Format the data timestamp for display with from-to range
  const getTimeframeInfo = () => {
    if (!stackData) return null;
    
    const lastUpdated = stackData.lastUpdated || stackData.stacks?.[0]?.lastCheck;
    const endTime = parseTimestamp(lastUpdated);
    
    if (endTime) {
      // Restart counts are typically collected over 24 hours
      const startTime = new Date(endTime.getTime() - 24 * 60 * 60 * 1000);
      
      const formatTime = (date) => date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const formatDate = (date) => date.toLocaleDateString([], { month: 'short', day: 'numeric' });
      
      const isSameDay = startTime.toDateString() === endTime.toDateString();
      
      if (isSameDay) {
        // Same day: "Mar 24, 10:00 AM - 2:45 PM"
        return `${formatDate(startTime)}, ${formatTime(startTime)} - ${formatTime(endTime)}`;
      } else {
        // Different days: "Mar 23, 2:45 PM - Mar 24, 2:45 PM"
        return `${formatDate(startTime)}, ${formatTime(startTime)} - ${formatDate(endTime)}, ${formatTime(endTime)}`;
      }
    }
    
    return null;
  };

  const timeframeInfo = getTimeframeInfo();

  return (
    <div className="problematic-deployments-chart">
      <div className="chart-header">
        <div className="chart-title">
          <AlertTriangle size={16} />
          <span>Top Problematic Deployments</span>
          <span className="issue-count">{problematicDeployments.length} with issues</span>
        </div>
        {timeframeInfo && (
          <div className="chart-timeframe">
            <Clock size={12} />
            <span>{timeframeInfo}</span>
            <span className="timeframe-duration">(24h)</span>
          </div>
        )}
        <div className="chart-legend-inline">
          <span className="legend-item">
            <span className="dot crash"></span>CrashLoop
          </span>
          <span className="legend-item">
            <span className="dot restarts"></span>Restarts
          </span>
          <span className="legend-item">
            <span className="dot unhealthy"></span>Unhealthy
          </span>
        </div>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="100%" height={Math.min(300, chartData.length * 36 + 40)}>
          <BarChart 
            data={chartData} 
            layout="vertical"
            margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
            barSize={14}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} />
            <XAxis 
              type="number"
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickLine={false}
              label={{ value: 'Issue Score', position: 'bottom', fontSize: 10, fill: 'var(--text-muted)' }}
            />
            <YAxis 
              type="category"
              dataKey="name"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickLine={false}
              width={130}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--hover-bg)' }} />
            <Bar 
              dataKey="score" 
              radius={[0, 6, 6, 0]}
              onClick={(data) => onDeploymentClick?.(data.namespace, data.fullName, data.stacks[0]?.toLowerCase(), data.namespaceFull)}
              style={{ cursor: 'pointer' }}
            >
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={getBarColor(entry)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {hasMore && (
        <button 
          className="show-more-btn"
          onClick={() => setShowAll(!showAll)}
        >
          {showAll ? (
            <>
              <ChevronUp size={14} />
              Show less
            </>
          ) : (
            <>
              <ChevronDown size={14} />
              Show {hiddenCount} more
            </>
          )}
        </button>
      )}

      <div className="deployments-summary">
        <div className="summary-stat crash">
          <Zap size={14} />
          <span>{problematicDeployments.reduce((sum, d) => sum + d.crashLoops, 0)}</span>
          <label>CrashLoops</label>
        </div>
        <div className="summary-stat restarts">
          <RotateCcw size={14} />
          <span>{problematicDeployments.reduce((sum, d) => sum + d.restarts, 0)}</span>
          <label>Restarts</label>
        </div>
        <div className="summary-stat unhealthy">
          <XCircle size={14} />
          <span>{problematicDeployments.reduce((sum, d) => sum + d.unhealthy, 0)}</span>
          <label>Unhealthy</label>
        </div>
      </div>
    </div>
  );
};

export default ProblematicDeploymentsChart;
