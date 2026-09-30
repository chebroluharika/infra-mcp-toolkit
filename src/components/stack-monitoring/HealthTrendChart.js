/**
 * HealthTrendChart - 24-hour health signal chart for Stack Monitoring
 * 
 * Shows health trends over time with:
 * - Healthy deployment count (green area)
 * - Unhealthy deployment count (red area)
 * - Restart trend line (purple dashed)
 * - Timeframe indicator
 * - Key insights
 */
import React, { useEffect, useState, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Line,
  ComposedChart
} from 'recharts';
import { Activity, TrendingUp, TrendingDown, RefreshCw, Clock, AlertTriangle, CheckCircle, Zap } from 'lucide-react';
import api from '../../services/api';

/**
 * Custom tooltip for health trend chart
 */
const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="health-trend-tooltip">
        <p className="tooltip-time">{label}</p>
        {payload.map((entry, index) => (
          <p key={index} className="tooltip-item" style={{ color: entry.color }}>
            <span className="tooltip-dot" style={{ background: entry.color }}></span>
            {entry.name}: <strong>{entry.value}</strong>
          </p>
        ))}
      </div>
    );
  }
  return null;
};

const HealthTrendChart = ({ onRefresh }) => {
  const [historyData, setHistoryData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch history data on mount
  useEffect(() => {
    fetchHistory();
  }, []);

  const fetchHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getStackHistory(0);
      setHistoryData(data);
    } catch (err) {
      setError(err.message || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  };

  // Process all data with useMemo BEFORE any early returns
  const processedData = useMemo(() => {
    if (!historyData?.history || historyData.history.length === 0) {
      return null;
    }

    // Helper to format date/time for insights
    const formatDateTime = (timestamp) => {
      const date = new Date(timestamp);
      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();
      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      const isYesterday = date.toDateString() === yesterday.toDateString();
      
      const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      
      if (isToday) {
        return `today at ${timeStr}`;
      } else if (isYesterday) {
        return `yesterday at ${timeStr}`;
      } else {
        const dateStr = date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        return `${dateStr} at ${timeStr}`;
      }
    };

    // Transform data for Recharts
    const chartData = historyData.history.map((point, index) => {
      const time = new Date(point.timestamp);
      const now = new Date();
      const isToday = time.toDateString() === now.toDateString();
      
      // Format X-axis label: "Mar 23, 14:30" for other days, "14:30" for today
      const timeStr = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const dateStr = time.toLocaleDateString([], { month: 'short', day: 'numeric' });
      const xAxisLabel = isToday ? timeStr : `${dateStr}, ${timeStr}`;
      
      return {
        time: xAxisLabel,
        fullTime: time.toLocaleString(),
        timestamp: point.timestamp,
        formattedDateTime: formatDateTime(point.timestamp),
        healthy: point.healthy_count || 0,
        unhealthy: point.unhealthy_count || 0,
        restarts: point.total_restarts || 0,
        index
      };
    });

    // Calculate timeframe
    const firstTimestamp = new Date(chartData[0]?.timestamp);
    const lastTimestamp = new Date(chartData[chartData.length - 1]?.timestamp);
    const hoursSpan = Math.round((lastTimestamp - firstTimestamp) / (1000 * 60 * 60));

    const formatTimeframe = () => {
      const formatDate = (date) => date.toLocaleDateString([], { month: 'short', day: 'numeric' });
      const formatTime = (date) => date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      
      if (firstTimestamp.toDateString() === lastTimestamp.toDateString()) {
        return `${formatDate(firstTimestamp)}, ${formatTime(firstTimestamp)} - ${formatTime(lastTimestamp)}`;
      }
      return `${formatDate(firstTimestamp)} ${formatTime(firstTimestamp)} - ${formatDate(lastTimestamp)} ${formatTime(lastTimestamp)}`;
    };

    // Calculate trends
    const firstPoint = chartData[0];
    const lastPoint = chartData[chartData.length - 1];
    const healthyTrend = lastPoint.healthy - firstPoint.healthy;
    const unhealthyTrend = lastPoint.unhealthy - firstPoint.unhealthy;
    const restartsTrend = lastPoint.restarts - firstPoint.restarts;

    // Get values for insights
    const maxRestarts = Math.max(...chartData.map(p => p.restarts));
    const currentRestarts = lastPoint.restarts;

    // Find when decline started (if currently declining)
    let declineStartPoint = null;
    if (lastPoint.unhealthy > 0) {
      // Walk backwards to find when unhealthy started increasing
      for (let i = chartData.length - 2; i >= 0; i--) {
        if (chartData[i].unhealthy === 0 || chartData[i].unhealthy < chartData[i + 1].unhealthy) {
          declineStartPoint = chartData[i + 1];
          break;
        }
      }
      if (!declineStartPoint && chartData[0].unhealthy > 0) {
        declineStartPoint = chartData[0];
      }
    }

    // Find worst point (highest unhealthy)
    const worstPoint = chartData.reduce((worst, p) => p.unhealthy > worst.unhealthy ? p : worst, chartData[0]);
    
    // Generate insights
    const insights = [];
    
    // Current health state - most important
    if (lastPoint.unhealthy === 0 && lastPoint.healthy > 0) {
      insights.push({ type: 'positive', icon: CheckCircle, text: `All ${lastPoint.healthy} deployments currently healthy` });
    } else if (lastPoint.unhealthy > 0) {
      const declineInfo = declineStartPoint 
        ? ` (since ${declineStartPoint.formattedDateTime})`
        : '';
      insights.push({ 
        type: 'warning', 
        icon: AlertTriangle, 
        text: `${lastPoint.unhealthy} unhealthy deployment${lastPoint.unhealthy > 1 ? 's' : ''} right now${declineInfo}` 
      });
    }
    
    // Trend insight - show if improving or worsening
    if (healthyTrend > 0 && unhealthyTrend < 0) {
      insights.push({ type: 'positive', icon: TrendingUp, text: `Recovering: ${Math.abs(unhealthyTrend)} fewer unhealthy vs start of period` });
    } else if (unhealthyTrend > 0) {
      insights.push({ type: 'warning', icon: TrendingDown, text: `Degrading: +${unhealthyTrend} more unhealthy vs start of period` });
    }
    
    // Current restart count (not cumulative)
    if (currentRestarts > 0) {
      insights.push({ type: 'warning', icon: Zap, text: `${currentRestarts} restarts in latest snapshot` });
    } else if (maxRestarts > 0) {
      insights.push({ type: 'info', icon: Zap, text: `Peak restarts was ${maxRestarts} (currently 0)` });
    }
    
    // Worst period - only if different from current and notable
    if (worstPoint.unhealthy > lastPoint.unhealthy && worstPoint.unhealthy > 0) {
      insights.push({ type: 'info', icon: Activity, text: `Worst was ${worstPoint.unhealthy} unhealthy ${worstPoint.formattedDateTime}` });
    }

    return {
      chartData,
      timeframe: formatTimeframe(),
      hoursSpan,
      healthyTrend,
      unhealthyTrend,
      restartsTrend,
      maxRestarts,
      insights: insights.slice(0, 3)
    };
  }, [historyData]);

  // Early returns AFTER useMemo
  if (loading) {
    return (
      <div className="health-trend-chart loading">
        <RefreshCw size={20} className="spinning" />
        <span>Loading health trends...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="health-trend-chart error">
        <Activity size={20} />
        <span>{error}</span>
        <button onClick={fetchHistory} className="retry-btn">Retry</button>
      </div>
    );
  }

  if (!processedData) {
    return (
      <div className="health-trend-chart empty">
        <Activity size={24} />
        <span>No historical data available</span>
        <p>Health snapshots are collected hourly</p>
      </div>
    );
  }

  const { chartData, timeframe, hoursSpan, healthyTrend, unhealthyTrend, restartsTrend, maxRestarts, insights } = processedData;

  return (
    <div className="health-trend-chart">
      <div className="chart-header">
        <div className="chart-title">
          <Activity size={16} />
          <span>Health Trend</span>
        </div>
        <div className="chart-timeframe">
          <Clock size={12} />
          <span>{timeframe}</span>
          <span className="timeframe-duration">({hoursSpan}h · {chartData.length} snapshots)</span>
        </div>
      </div>

      <div className="chart-trends">
        <span className={`trend ${healthyTrend >= 0 ? 'positive' : 'negative'}`}>
          {healthyTrend >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          Healthy: {healthyTrend >= 0 ? '+' : ''}{healthyTrend}
        </span>
        <span className={`trend ${unhealthyTrend <= 0 ? 'positive' : 'negative'}`}>
          {unhealthyTrend <= 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
          Unhealthy: {unhealthyTrend >= 0 ? '+' : ''}{unhealthyTrend}
        </span>
        <span className={`trend ${restartsTrend <= 0 ? 'positive' : 'negative'}`}>
          {restartsTrend <= 0 ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
          Restarts: {restartsTrend >= 0 ? '+' : ''}{restartsTrend}
        </span>
      </div>

      <div className="chart-container">
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="healthyGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#4caf50" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#4caf50" stopOpacity={0.05}/>
              </linearGradient>
              <linearGradient id="unhealthyGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f44336" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#f44336" stopOpacity={0.05}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
            <XAxis 
              dataKey="time" 
              tick={{ fill: 'var(--text-muted)', fontSize: 9, angle: -35, textAnchor: 'end' }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickLine={false}
              interval={Math.max(0, Math.floor(chartData.length / 6) - 1)}
              height={45}
            />
            <YAxis 
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickLine={false}
              domain={[0, 'auto']}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area 
              type="monotone" 
              dataKey="healthy" 
              name="Healthy"
              stroke="#4caf50" 
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#healthyGradient)" 
            />
            <Area 
              type="monotone" 
              dataKey="unhealthy" 
              name="Unhealthy"
              stroke="#f44336" 
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#unhealthyGradient)" 
            />
            {maxRestarts > 0 && (
              <Line 
                type="monotone" 
                dataKey="restarts" 
                name="Restarts"
                stroke="#9c27b0" 
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                yAxisId={0}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#4caf50' }}></span>
          Healthy
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: '#f44336' }}></span>
          Unhealthy
        </span>
        <span className="legend-item">
          <span className="legend-dot dashed" style={{ background: '#9c27b0' }}></span>
          Restarts
        </span>
      </div>

      {insights.length > 0 && (
        <div className="chart-insights">
          {insights.map((insight, idx) => (
            <div key={idx} className={`insight ${insight.type}`}>
              <insight.icon size={12} />
              <span>{insight.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HealthTrendChart;
