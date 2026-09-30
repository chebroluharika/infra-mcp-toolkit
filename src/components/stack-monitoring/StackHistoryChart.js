/**
 * StackHistoryChart - Visual chart for stack monitoring history
 * 
 * Uses Recharts to display historical health trends.
 */
import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  LineChart,
  Line,
  BarChart,
  Bar
} from 'recharts';
import { TrendingUp, TrendingDown, Activity, Info } from 'lucide-react';

/**
 * Custom tooltip for the chart
 */
const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="stack-history-tooltip">
        <p className="tooltip-time">{label}</p>
        {payload.map((entry, index) => (
          <p key={index} style={{ color: entry.color }}>
            {entry.name}: {entry.value}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

/**
 * StackHistoryChart component
 */
const StackHistoryChart = ({ 
  historyData, 
  loading = false, 
  error = null,
  chartType = 'area' // 'area', 'line', or 'bar'
}) => {
  if (loading) {
    return (
      <div className="stack-history-chart loading">
        <Activity size={20} className="spinning" />
        <span>Loading history data...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="stack-history-chart error">
        <span>{error}</span>
      </div>
    );
  }

  if (!historyData?.history || historyData.history.length === 0) {
    return (
      <div className="stack-history-chart empty">
        <Activity size={24} />
        <span>No historical data available</span>
        <p>History snapshots are collected periodically.</p>
      </div>
    );
  }

  // Transform data for Recharts
  // Supports both global history (total_restarts) and deployment-specific history (restarts)
  const chartData = historyData.history.map((point, index) => {
    const time = new Date(point.timestamp);
    return {
      time: time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      fullTime: time.toLocaleString(),
      healthy: point.healthy_count || 0,
      unhealthy: point.unhealthy_count || 0,
      restarts: point.restarts ?? point.total_restarts ?? 0,
      index
    };
  });

  // Calculate trend
  const firstPoint = chartData[0];
  const lastPoint = chartData[chartData.length - 1];
  const healthyTrend = lastPoint.healthy - firstPoint.healthy;
  const unhealthyTrend = lastPoint.unhealthy - firstPoint.unhealthy;

  // Summary stats - use backend summary if available (deployment-specific), otherwise calculate
  const backendSummary = historyData.summary;
  const avgHealthy = backendSummary?.avg_healthy ?? Math.round(chartData.reduce((sum, p) => sum + p.healthy, 0) / chartData.length);
  const maxUnhealthy = backendSummary?.max_unhealthy ?? Math.max(...chartData.map(p => p.unhealthy));
  // For deployment-specific history, use max restarts (they accumulate); for global, sum them
  const totalRestarts = backendSummary?.total_restarts ?? Math.max(...chartData.map(p => p.restarts));

  const renderChart = () => {
    const commonProps = {
      data: chartData,
      margin: { top: 10, right: 10, left: -20, bottom: 0 }
    };

    if (chartType === 'bar') {
      return (
        <BarChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
          <XAxis 
            dataKey="time" 
            tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
            axisLine={{ stroke: 'var(--border-color)' }}
          />
          <YAxis 
            tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
            axisLine={{ stroke: 'var(--border-color)' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '11px' }} />
          <Bar dataKey="healthy" name="Healthy" fill="var(--accent-green)" stackId="a" />
          <Bar dataKey="unhealthy" name="Unhealthy" fill="var(--accent-red)" stackId="a" />
        </BarChart>
      );
    }

    if (chartType === 'line') {
      return (
        <LineChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
          <XAxis 
            dataKey="time" 
            tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
            axisLine={{ stroke: 'var(--border-color)' }}
          />
          <YAxis 
            tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
            axisLine={{ stroke: 'var(--border-color)' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '11px' }} />
          <Line 
            type="monotone" 
            dataKey="healthy" 
            name="Healthy" 
            stroke="var(--accent-green)" 
            strokeWidth={2}
            dot={false}
          />
          <Line 
            type="monotone" 
            dataKey="unhealthy" 
            name="Unhealthy" 
            stroke="var(--accent-red)" 
            strokeWidth={2}
            dot={false}
          />
          <Line 
            type="monotone" 
            dataKey="restarts" 
            name="Restarts" 
            stroke="var(--accent-purple, #9c27b0)" 
            strokeWidth={1}
            strokeDasharray="5 5"
            dot={false}
          />
        </LineChart>
      );
    }

    // Default: Area chart
    return (
      <AreaChart {...commonProps}>
        <defs>
          <linearGradient id="colorHealthy" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--accent-green)" stopOpacity={0.3}/>
            <stop offset="95%" stopColor="var(--accent-green)" stopOpacity={0}/>
          </linearGradient>
          <linearGradient id="colorUnhealthy" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--accent-red)" stopOpacity={0.3}/>
            <stop offset="95%" stopColor="var(--accent-red)" stopOpacity={0}/>
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
        <XAxis 
          dataKey="time" 
          tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
          axisLine={{ stroke: 'var(--border-color)' }}
        />
        <YAxis 
          tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
          axisLine={{ stroke: 'var(--border-color)' }}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: '11px' }} />
        <Area 
          type="monotone" 
          dataKey="healthy" 
          name="Healthy"
          stroke="var(--accent-green)" 
          fillOpacity={1}
          fill="url(#colorHealthy)" 
        />
        <Area 
          type="monotone" 
          dataKey="unhealthy" 
          name="Unhealthy"
          stroke="var(--accent-red)" 
          fillOpacity={1}
          fill="url(#colorUnhealthy)" 
        />
      </AreaChart>
    );
  };

  // Extract namespace info for display (if deployment-specific history)
  const namespaceInfo = historyData.namespace;
  const stackInfo = historyData.stack;

  return (
    <div className="stack-history-chart">
      {/* Namespace indicator for deployment-specific history */}
      {namespaceInfo && (
        <div className="history-namespace-info">
          <span className="namespace-label" title={`Full namespace key: ${namespaceInfo}`}>
            {namespaceInfo.replace(/^--/, '').replace(/--/g, ' → ')}
          </span>
          {stackInfo && <span className="stack-label">{stackInfo.toUpperCase()}</span>}
        </div>
      )}
      
      {/* Summary Stats */}
      <div className="history-summary-stats">
        <div className="stat-item">
          <span className="stat-label">Data Points</span>
          <span className="stat-value">{chartData.length}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Avg Healthy</span>
          <span className="stat-value healthy">{avgHealthy}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Max Unhealthy</span>
          <span className="stat-value unhealthy">{maxUnhealthy}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Total Restarts</span>
          <span className="stat-value">{totalRestarts}</span>
        </div>
      </div>

      {/* Trend Indicators */}
      <div className="history-trends">
        <div 
          className={`trend-item ${healthyTrend >= 0 ? 'positive' : 'negative'}`}
          title={`Change in healthy replicas from first to last data point.\n${healthyTrend === 0 ? 'No change indicates stable replica count.' : healthyTrend > 0 ? 'Positive: replicas increased over time.' : 'Negative: replicas decreased over time.'}`}
        >
          {healthyTrend >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          <span>Healthy: {healthyTrend >= 0 ? '+' : ''}{healthyTrend}</span>
        </div>
        <div 
          className={`trend-item ${unhealthyTrend <= 0 ? 'positive' : 'negative'}`}
          title={`Change in unhealthy/unavailable replicas from first to last data point.\n${unhealthyTrend === 0 ? 'No change - deployment remained stable.' : unhealthyTrend > 0 ? 'Warning: more replicas became unavailable.' : 'Good: fewer unavailable replicas now.'}`}
        >
          {unhealthyTrend <= 0 ? <TrendingDown size={14} /> : <TrendingUp size={14} />}
          <span>Unhealthy: {unhealthyTrend >= 0 ? '+' : ''}{unhealthyTrend}</span>
        </div>
        <div className="trend-info-tooltip" title="Trends show the change between the first and last data points in the time range. +0 means the value stayed constant (stable deployment).">
          <Info size={14} />
        </div>
      </div>

      {/* Chart */}
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={200}>
          {renderChart()}
        </ResponsiveContainer>
      </div>

      {/* Time Range Info */}
      <div className="history-time-range">
        <span>
          {chartData.length > 0 && (
            <>From {chartData[0].fullTime} to {chartData[chartData.length - 1].fullTime}</>
          )}
        </span>
      </div>
    </div>
  );
};

export default StackHistoryChart;
