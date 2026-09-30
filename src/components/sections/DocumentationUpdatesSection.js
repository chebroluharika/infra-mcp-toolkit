import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BookOpen, RefreshCw, ExternalLink, ChevronDown, ChevronRight,
  Loader, Search, FileText, CheckCircle, AlertTriangle, Tag, Layers,
  Calendar, Bug, TrendingUp, PieChart, Filter, ChevronsUp, User, Clock,
  FileEdit, ClipboardList, Beaker
} from 'lucide-react';
import api from '../../services/api';
import '../../styles/docs-updates.css';

const PRIORITY_COLORS = {
  blocker: '#dc2626', critical: '#dc2626', highest: '#dc2626',
  high: '#ea580c', major: '#ea580c',
  medium: '#ca8a04', normal: '#ca8a04',
  low: '#16a34a', minor: '#16a34a', trivial: '#16a34a', lowest: '#16a34a',
};

const PRIORITY_ORDER = ['blocker', 'critical', 'highest', 'high', 'major', 'medium', 'normal', 'minor', 'low', 'trivial', 'lowest'];

const STATUS_COLORS = {
  'Open': '#3b82f6',
  'In Progress': '#f59e0b',
  'In Review': '#8b5cf6',
  'Done': '#10b981',
  'Closed': '#6b7280',
  'Resolved': '#10b981',
  'To Do': '#64748b',
  'Backlog': '#94a3b8',
};

// Donut Chart Component
const DonutChart = ({ data, total, centerLabel }) => {
  const size = 140;
  const strokeWidth = 24;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  
  let currentOffset = 0;
  const segments = data.map((item, index) => {
    const percentage = total > 0 ? (item.count / total) * 100 : 0;
    const dashLength = (percentage / 100) * circumference;
    const segment = {
      ...item,
      percentage,
      dashArray: `${dashLength} ${circumference - dashLength}`,
      dashOffset: -currentOffset,
    };
    currentOffset += dashLength;
    return segment;
  });

  return (
    <div className="donut-chart-container">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--bg-tertiary)"
          strokeWidth={strokeWidth}
        />
        {segments.map((segment, index) => (
          <circle
            key={index}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={segment.color}
            strokeWidth={strokeWidth}
            strokeDasharray={segment.dashArray}
            strokeDashoffset={segment.dashOffset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ transition: 'stroke-dasharray 0.5s ease' }}
          />
        ))}
        <text
          x={size / 2}
          y={size / 2 - 8}
          textAnchor="middle"
          className="donut-center-value"
        >
          {total}
        </text>
        <text
          x={size / 2}
          y={size / 2 + 12}
          textAnchor="middle"
          className="donut-center-label"
        >
          {centerLabel}
        </text>
      </svg>
      <div className="donut-legend">
        {segments.filter(s => s.count > 0).slice(0, 5).map((segment, index) => (
          <div key={index} className="donut-legend-item">
            <span className="donut-legend-color" style={{ background: segment.color }} />
            <span className="donut-legend-label">{segment.name}</span>
            <span className="donut-legend-value">{segment.count} ({segment.percentage.toFixed(0)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
};

// Trend Stacked Bar Chart Component - shows Release Notes vs Documentation breakdown
const TrendChart = ({ data }) => {
  if (!data || data.length === 0) return null;
  
  // Use total if breakdown not available, otherwise use max of breakdown sums
  const hasBreakdown = data.some(d => (d.release_notes || 0) > 0 || (d.documentation || 0) > 0);
  const maxValue = hasBreakdown 
    ? Math.max(...data.map(d => (d.release_notes || 0) + (d.documentation || 0)), 1)
    : Math.max(...data.map(d => d.total || 0), 1);
  
  const width = 380;
  const height = 150;
  const padding = { top: 15, right: 10, bottom: 35, left: 35 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  
  const barWidth = Math.min(28, (chartWidth / data.length) * 0.65);
  const barGap = (chartWidth - barWidth * data.length) / (data.length + 1);

  return (
    <div className="trend-chart-container">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {/* Y-axis lines */}
        {[0, 0.5, 1].map((ratio, i) => (
          <g key={i}>
            <line
              x1={padding.left}
              y1={padding.top + chartHeight * (1 - ratio)}
              x2={width - padding.right}
              y2={padding.top + chartHeight * (1 - ratio)}
              stroke="var(--border-light)"
              strokeDasharray="3,3"
            />
            <text
              x={padding.left - 5}
              y={padding.top + chartHeight * (1 - ratio) + 4}
              textAnchor="end"
              className="trend-axis-label"
            >
              {Math.round(maxValue * ratio)}
            </text>
          </g>
        ))}
        
        {/* Stacked Bars */}
        {data.map((d, i) => {
          const x = padding.left + barGap + i * (barWidth + barGap);
          const rnCount = d.release_notes || 0;
          const docCount = d.documentation || 0;
          const totalCount = d.total || 0;
          
          // Shorten release label (e.g., "133.0.0" -> "133")
          const shortRelease = d.release?.split('.')[0] || d.release;
          
          // If no breakdown available, show total as a single bar
          if (!hasBreakdown && totalCount > 0) {
            const totalHeight = (totalCount / maxValue) * chartHeight;
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={padding.top + chartHeight - totalHeight}
                  width={barWidth}
                  height={totalHeight}
                  fill="#d97706"
                  rx="2"
                  style={{ cursor: 'pointer' }}
                >
                  <title>{d.release}: {totalCount}</title>
                </rect>
                <text
                  x={x + barWidth / 2}
                  y={height - 8}
                  textAnchor="middle"
                  className="trend-axis-label"
                >
                  {shortRelease}
                </text>
              </g>
            );
          }
          
          const rnHeight = (rnCount / maxValue) * chartHeight;
          const docHeight = (docCount / maxValue) * chartHeight;
          
          return (
            <g key={i}>
              {/* Release Notes bar (bottom - green) */}
              <rect
                x={x}
                y={padding.top + chartHeight - rnHeight}
                width={barWidth}
                height={Math.max(rnHeight, 0)}
                fill="#16a34a"
                rx="2"
                style={{ cursor: 'pointer' }}
              >
                <title>{d.release} - Release Notes: {rnCount}</title>
              </rect>
              {/* Documentation bar (top - purple, stacked) */}
              <rect
                x={x}
                y={padding.top + chartHeight - rnHeight - docHeight}
                width={barWidth}
                height={Math.max(docHeight, 0)}
                fill="#9333ea"
                rx="2"
                style={{ cursor: 'pointer' }}
              >
                <title>{d.release} - Documentation: {docCount}</title>
              </rect>
              {/* Release label */}
              <text
                x={x + barWidth / 2}
                y={height - 8}
                textAnchor="middle"
                className="trend-axis-label"
              >
                {shortRelease}
              </text>
            </g>
          );
        })}
      </svg>
      {/* Legend - show breakdown legend only when we have breakdown data */}
      {hasBreakdown ? (
        <div className="trend-chart-legend">
          <span className="legend-item">
            <span className="legend-color" style={{ background: '#16a34a' }}></span>
            Release Notes
          </span>
          <span className="legend-item">
            <span className="legend-color" style={{ background: '#9333ea' }}></span>
            Documentation
          </span>
        </div>
      ) : (
        <div className="trend-chart-legend">
          <span className="legend-item">
            <span className="legend-color" style={{ background: '#d97706' }}></span>
            Total Items
          </span>
        </div>
      )}
    </div>
  );
};

// Sub-Component Bar Chart Component (horizontal bars, clickable)
const SubComponentChart = ({ data, activeFilter, onFilterChange, maxItems = 8 }) => {
  if (!data || data.length === 0) {
    return <div className="docs-analytics-empty">No sub-component data available</div>;
  }
  
  const items = data.slice(0, maxItems);
  const maxCount = items[0]?.count || 1;
  
  return (
    <div className="subcomponent-chart-container">
      {items.map(({ component, count }) => (
        <div
          key={component}
          className={`subcomponent-bar-item ${activeFilter === component ? 'active' : ''}`}
          onClick={() => onFilterChange(activeFilter === component ? 'all' : component)}
          title={`Click to filter by ${component}`}
        >
          <div className="subcomponent-label">
            <span className="subcomponent-name">{component}</span>
            <span className="subcomponent-count">{count}</span>
          </div>
          <div className="subcomponent-bar-wrap">
            <div
              className="subcomponent-bar"
              style={{ width: `${(count / maxCount) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

// Documentation Funnel Component
const DocsFunnel = ({ data }) => {
  const maxCount = Math.max(...data.map(d => d.count), 1);
  
  return (
    <div className="docs-funnel-container">
      {data.map((stage, index) => (
        <div 
          key={index} 
          className="funnel-stage"
          title={stage.description || ''}
        >
          <div className="funnel-label">
            <span className="funnel-name">{stage.name}</span>
            <div className="funnel-stats">
              <span className="funnel-count">{stage.count}</span>
              {stage.percentage !== undefined && stage.percentage !== 100 && (
                <span className="funnel-percentage">({stage.percentage}%)</span>
              )}
            </div>
          </div>
          <div className="funnel-bar-wrap">
            <div
              className="funnel-bar"
              style={{
                width: `${(stage.count / maxCount) * 100}%`,
                background: stage.color,
              }}
            />
          </div>
        </div>
      ))}
      {data.length > 0 && data[data.length - 1].count > 0 && (
        <div className="funnel-completion">
          <CheckCircle size={14} />
          Completion: {((data[data.length - 1].count / data[0].count) * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
};

const DocumentationUpdatesSection = () => {
  // Tab state: 'bugs' or 'nplans'
  const [activeTab, setActiveTab] = useState('bugs');
  
  // Bug state
  const [releases, setReleases] = useState([]);
  const [selectedRelease, setSelectedRelease] = useState(null);
  const [bugs, setBugs] = useState([]);
  const [summary, setSummary] = useState(null);
  
  // NPLAN state
  const [nplanReleases, setNplanReleases] = useState([]);
  const [selectedNplanRelease, setSelectedNplanRelease] = useState(null);
  const [nplans, setNplans] = useState([]);
  const [funnelData, setFunnelData] = useState(null);
  
  const [loadingReleases, setLoadingReleases] = useState(true);
  const [loadingBugs, setLoadingBugs] = useState(false);
  const [loadingNplans, setLoadingNplans] = useState(false);
  const [loadingFunnel, setLoadingFunnel] = useState(false);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  
  const [searchQuery, setSearchQuery] = useState('');
  const [componentFilter, setComponentFilter] = useState('all');
  const [subComponentFilter, setSubComponentFilter] = useState('all');
  const [docsTypeFilter, setDocsTypeFilter] = useState('all'); // 'all', 'release_notes', 'documentation'
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [dateFilterType, setDateFilterType] = useState('created'); // 'created' or 'resolved'
  const [expandedBug, setExpandedBug] = useState(null);

  const fetchReleases = useCallback(async () => {
    setLoadingReleases(true);
    setError(null);
    try {
      const data = await api.getDocsUpdateReleases();
      const releaseList = data.releases || [];
      setReleases(releaseList);
      if (releaseList.length > 0 && !selectedRelease) {
        setSelectedRelease(releaseList[0].id);
      }
    } catch (e) {
      setError('Failed to load releases');
      console.error('Error fetching releases:', e);
    } finally {
      setLoadingReleases(false);
    }
  }, [selectedRelease]);

  const fetchBugs = useCallback(async (release) => {
    if (!release) return;
    setLoadingBugs(true);
    try {
      const data = await api.getDocsUpdateBugs(release);
      setBugs(data.bugs || []);
    } catch (e) {
      console.error('Error fetching bugs:', e);
      setBugs([]);
    } finally {
      setLoadingBugs(false);
    }
  }, []);

  const fetchSummary = useCallback(async (release) => {
    setLoadingSummary(true);
    try {
      const data = await api.getDocsUpdateSummary(release);
      setSummary(data);
    } catch (e) {
      console.error('Error fetching summary:', e);
      setSummary(null);
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  // NPLAN fetch functions
  const fetchNplanReleases = useCallback(async () => {
    try {
      const data = await api.getDocsUpdateNplanReleases();
      const releaseList = data.releases || [];
      setNplanReleases(releaseList);
      if (releaseList.length > 0 && !selectedNplanRelease) {
        setSelectedNplanRelease(releaseList[0].id);
      }
    } catch (e) {
      console.error('Error fetching NPLAN releases:', e);
    }
  }, [selectedNplanRelease]);

  const fetchNplans = useCallback(async (release) => {
    if (!release) return;
    setLoadingNplans(true);
    try {
      const data = await api.getDocsUpdateNplans(release);
      setNplans(data.nplans || []);
    } catch (e) {
      console.error('Error fetching NPLANs:', e);
      setNplans([]);
    } finally {
      setLoadingNplans(false);
    }
  }, []);

  const fetchFunnel = useCallback(async (release) => {
    if (!release) return;
    setLoadingFunnel(true);
    try {
      const data = await api.getDocsUpdateFunnel(release);
      setFunnelData(data);
    } catch (e) {
      console.error('Error fetching funnel data:', e);
      setFunnelData(null);
    } finally {
      setLoadingFunnel(false);
    }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshDocsUpdateCache();
      await Promise.all([
        fetchReleases(),
        fetchNplanReleases(),
        selectedRelease && fetchBugs(selectedRelease),
        selectedNplanRelease && fetchNplans(selectedNplanRelease),
        selectedNplanRelease && fetchFunnel(selectedNplanRelease),
        fetchSummary(selectedRelease),
      ]);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchReleases();
    fetchNplanReleases();
  }, [fetchReleases, fetchNplanReleases]);

  useEffect(() => {
    if (selectedRelease) {
      fetchBugs(selectedRelease);
      fetchSummary(selectedRelease);
    }
  }, [selectedRelease, fetchBugs, fetchSummary]);

  useEffect(() => {
    if (selectedNplanRelease) {
      fetchNplans(selectedNplanRelease);
      fetchFunnel(selectedNplanRelease);
    }
  }, [selectedNplanRelease, fetchNplans, fetchFunnel]);

  // Get the current items based on active tab
  const currentItems = activeTab === 'bugs' ? bugs : nplans;
  const currentLoading = activeTab === 'bugs' ? loadingBugs : loadingNplans;

  // Get unique components for filter dropdown
  const components = useMemo(() => {
    const comps = new Set();
    currentItems.forEach(b => {
      if (b.components && Array.isArray(b.components)) {
        b.components.forEach(c => {
          if (c && c !== 'Unknown') comps.add(c);
        });
      } else if (b.component && b.component !== 'Unknown') {
        comps.add(b.component);
      }
    });
    return Array.from(comps).sort();
  }, [currentItems]);

  // Get unique sub-components for filter dropdown
  const subComponents = useMemo(() => {
    const comps = new Set();
    currentItems.forEach(b => {
      if (b.sub_component && b.sub_component !== 'Unknown') {
        comps.add(b.sub_component);
      }
    });
    return Array.from(comps).sort();
  }, [currentItems]);

  const filteredItems = useMemo(() => {
    let list = [...currentItems];
    
    // Filter by component
    if (componentFilter !== 'all') {
      list = list.filter(b => {
        if (b.components && Array.isArray(b.components)) {
          return b.components.includes(componentFilter);
        }
        return b.component === componentFilter;
      });
    }
    
    // Filter by sub-component
    if (subComponentFilter !== 'all') {
      list = list.filter(b => b.sub_component === subComponentFilter);
    }
    
    // Filter by date range
    if (dateFrom || dateTo) {
      list = list.filter(b => {
        const dateField = dateFilterType === 'created' ? b.created : b.resolution_date;
        if (!dateField) return false;
        
        const bugDate = new Date(dateField).setHours(0, 0, 0, 0);
        
        if (dateFrom) {
          const fromDate = new Date(dateFrom).setHours(0, 0, 0, 0);
          if (bugDate < fromDate) return false;
        }
        
        if (dateTo) {
          const toDate = new Date(dateTo).setHours(23, 59, 59, 999);
          if (bugDate > toDate) return false;
        }
        
        return true;
      });
    }
    
    // Filter by search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        b => b.key?.toLowerCase().includes(q) ||
             b.summary?.toLowerCase().includes(q) ||
             b.component?.toLowerCase().includes(q) ||
             b.sub_component?.toLowerCase().includes(q) ||
             b.assignee?.toLowerCase().includes(q) ||
             b.priority?.toLowerCase().includes(q) ||
             b.status?.toLowerCase().includes(q) ||
             b.writer?.toLowerCase().includes(q) ||
             b.delivery_target_beta?.toLowerCase().includes(q) ||
             b.delivery_target_ga?.toLowerCase().includes(q)
      );
    }
    
    // Filter by docs type (Release Notes vs Documentation Required)
    if (docsTypeFilter !== 'all') {
      list = list.filter(item => {
        const releaseNote = item.release_note || item.releaseNote;
        const docsRequired = item.documentation_required || item.docsRequired;
        
        if (docsTypeFilter === 'release_notes') {
          return releaseNote === 'For Customer';
        } else if (docsTypeFilter === 'documentation') {
          return docsRequired === 'Yes';
        }
        return true;
      });
    }
    
    // Sort by priority
    list.sort((a, b) => {
      const pa = PRIORITY_ORDER.indexOf((a.priority || '').toLowerCase());
      const pb = PRIORITY_ORDER.indexOf((b.priority || '').toLowerCase());
      return (pa === -1 ? 99 : pa) - (pb === -1 ? 99 : pb);
    });
    return list;
  }, [currentItems, searchQuery, componentFilter, subComponentFilter, docsTypeFilter, dateFrom, dateTo, dateFilterType]);

  // Compute summary stats based on active tab
  const totalItems = currentItems.length;
  
  // For bugs, use the summary from API; for NPLANs, compute from local data
  const computedByPriority = useMemo(() => {
    if (activeTab === 'bugs') {
      return summary?.by_priority || {};
    }
    const counts = {};
    nplans.forEach(n => {
      const p = n.priority || 'Unknown';
      counts[p] = (counts[p] || 0) + 1;
    });
    return counts;
  }, [activeTab, summary, nplans]);
  
  const criticalCount = (computedByPriority.Blocker || 0) + (computedByPriority.Critical || 0) + (computedByPriority.Highest || 0);
  const highCount = (computedByPriority.High || 0) + (computedByPriority.Major || 0);
  
  // Documentation stats - counts for Release Notes vs Documentation Required
  const docsStats = useMemo(() => {
    let needsReleaseNotes = 0;
    let needsDocsRequired = 0;
    
    currentItems.forEach(item => {
      // Check Release Note field
      const releaseNote = item.release_note || item.releaseNote;
      if (releaseNote === 'For Customer') {
        needsReleaseNotes++;
      }
      // Check Documentation Required field
      const docsRequired = item.documentation_required || item.docsRequired;
      if (docsRequired === 'Yes') {
        needsDocsRequired++;
      }
    });
    
    return { needsReleaseNotes, needsDocsRequired };
  }, [currentItems]);
  
  // NPLAN-specific stats
  const nplanStats = useMemo(() => {
    if (activeTab !== 'nplans' || !nplans.length) {
      return { writerAssigned: 0, inProgress: 0 };
    }
    let writerAssigned = 0;
    let inProgress = 0;
    nplans.forEach(n => {
      if (n.writer) writerAssigned++;
      if (n.status && n.status.toLowerCase() === 'in progress') inProgress++;
    });
    return { writerAssigned, inProgress };
  }, [activeTab, nplans]);

  // Compute status distribution for donut chart
  const statusDistribution = useMemo(() => {
    const statusCounts = {};
    currentItems.forEach(item => {
      const status = item.status || 'Unknown';
      statusCounts[status] = (statusCounts[status] || 0) + 1;
    });
    
    return Object.entries(statusCounts)
      .map(([name, count]) => ({
        name,
        count,
        color: STATUS_COLORS[name] || '#94a3b8'
      }))
      .sort((a, b) => b.count - a.count);
  }, [currentItems]);

  // Compute trend data from releases with breakdown
  // Dynamically show selected release and 4 previous releases
  const trendData = useMemo(() => {
    const releaseList = activeTab === 'bugs' ? releases : nplanReleases;
    const currentRelease = activeTab === 'bugs' ? selectedRelease : selectedNplanRelease;
    
    if (!releaseList || releaseList.length === 0) return [];
    
    // Find the index of the selected release
    const selectedIndex = releaseList.findIndex(r => 
      (r.name || r.id) === currentRelease || r.id === currentRelease
    );
    
    // If selected release found, show it and 4 previous releases (5 total)
    // If not found, show the first 5 releases
    let startIndex = 0;
    let endIndex = 5;
    
    if (selectedIndex !== -1) {
      // Include selected release and up to 4 older releases
      startIndex = selectedIndex;
      endIndex = Math.min(selectedIndex + 5, releaseList.length);
    }
    
    return releaseList
      .slice(startIndex, endIndex)
      .reverse()
      .map(r => ({
        release: r.name || r.id,
        total: activeTab === 'bugs' ? (r.bug_count || 0) : (r.nplan_count || 0),
        release_notes: r.release_notes_count || 0,
        documentation: r.documentation_count || 0
      }));
  }, [activeTab, releases, nplanReleases, selectedRelease, selectedNplanRelease]);

  // Compute sub-component counts from current items (works for both bugs and NPLANs)
  const subComponentCounts = useMemo(() => {
    // For bugs, try to use summary data first
    if (activeTab === 'bugs' && summary?.by_component?.length > 0) {
      return summary.by_component;
    }
    
    // Compute from current items
    const counts = {};
    currentItems.forEach(item => {
      const subComp = item.sub_component;
      if (subComp && subComp !== 'Unknown') {
        counts[subComp] = (counts[subComp] || 0) + 1;
      }
    });
    
    return Object.entries(counts)
      .map(([component, count]) => ({ component, count }))
      .sort((a, b) => b.count - a.count);
  }, [activeTab, summary, currentItems]);

  // Get documentation funnel stages from API data (for NPLANs)
  // Falls back to status-based estimation for Bugs
  const computedFunnelData = useMemo(() => {
    // For NPLANs, use real funnel data from API
    if (activeTab === 'nplans' && funnelData?.stages?.length > 0) {
      return funnelData.stages;
    }
    
    // For Bugs (or if no funnel data), use status-based estimation
    const total = currentItems.length;
    if (total === 0) return [];
    
    const doneStatuses = ['Done', 'Closed', 'Resolved', 'Complete'];
    const completed = currentItems.filter(item =>
      doneStatuses.some(s => (item.status || '').toLowerCase().includes(s.toLowerCase()))
    ).length;
    
    return [
      { name: 'Needs Docs', count: total, color: '#3b82f6' },
      { name: 'Published', count: completed, color: '#10b981' },
    ];
  }, [activeTab, funnelData, currentItems]);

  if (loadingReleases && releases.length === 0) {
    return (
      <div className="docs-updates-section">
        <div className="docs-loading">
          <Loader className="spinning" size={24} />
          <span>Loading documentation updates...</span>
        </div>
      </div>
    );
  }

  if (error && releases.length === 0) {
    return (
      <div className="docs-updates-section">
        <div className="docs-error">
          <AlertTriangle size={24} />
          <span>{error}</span>
          <button onClick={fetchReleases} className="docs-retry-btn">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="docs-updates-section">
      {/* Tech Preview Banner */}
      <div className="docs-tech-preview-banner">
        <Beaker size={16} />
        <span className="docs-tech-preview-label">Tech Preview</span>
        <span className="docs-tech-preview-text">This feature is in active development. Data and functionality may change.</span>
      </div>

      {/* Header */}
      <div className="docs-header">
        <div className="docs-header-title">
          <BookOpen size={24} />
          <h1>Documentation Updates</h1>
        </div>
        <div className="docs-header-actions">
          <button
            className="docs-refresh-btn"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            <RefreshCw size={16} className={refreshing ? 'spinning' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Page Description */}
      <p className="docs-page-description">
        Track bugs and NPLANs that require documentation updates, release notes, or customer-facing content changes across releases.
      </p>

      {/* Tab Switcher */}
      <div className="docs-tabs">
        <button
          className={`docs-tab ${activeTab === 'bugs' ? 'active' : ''}`}
          onClick={() => setActiveTab('bugs')}
        >
          <Bug size={16} />
          Bugs ({bugs.length})
        </button>
        <button
          className={`docs-tab ${activeTab === 'nplans' ? 'active' : ''}`}
          onClick={() => setActiveTab('nplans')}
        >
          <FileText size={16} />
          NPLANs ({nplans.length})
        </button>
      </div>

      {/* Release Selector - context aware based on tab */}
      <div className="docs-release-selector">
        <label>{activeTab === 'bugs' ? 'Affected Version:' : 'Release (Beta/GA):'}</label>
        {activeTab === 'bugs' ? (
          <select
            value={selectedRelease || ''}
            onChange={(e) => setSelectedRelease(e.target.value)}
            disabled={loadingReleases}
          >
            {releases.map(r => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.bug_count} bugs)
              </option>
            ))}
          </select>
        ) : (
          <select
            value={selectedNplanRelease || ''}
            onChange={(e) => setSelectedNplanRelease(e.target.value)}
            disabled={loadingReleases}
          >
            {nplanReleases.map(r => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.nplan_count} NPLANs)
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Stats Cards */}
      <div className="docs-stats">
        <div className="docs-stat-card">
          <div className="docs-stat-icon" style={{ background: '#dbeafe', color: '#2563eb' }}>
            {activeTab === 'bugs' ? <Bug size={18} /> : <FileText size={18} />}
          </div>
          <div className="docs-stat-content">
            <div className="docs-stat-value">
              {currentLoading ? <Loader size={16} className="spinning" /> : totalItems}
            </div>
            <div className="docs-stat-label">Total {activeTab === 'bugs' ? 'Bugs' : 'NPLANs'}</div>
          </div>
        </div>

        <div className="docs-stat-card">
          <div className="docs-stat-icon" style={{ background: '#dcfce7', color: '#16a34a' }}>
            <FileEdit size={18} />
          </div>
          <div className="docs-stat-content">
            <div className="docs-stat-value" style={{ color: '#16a34a' }}>
              {currentLoading ? <Loader size={16} className="spinning" /> : docsStats.needsReleaseNotes}
            </div>
            <div className="docs-stat-label">Needs Release Notes</div>
          </div>
        </div>

        <div className="docs-stat-card">
          <div className="docs-stat-icon" style={{ background: '#f3e8ff', color: '#9333ea' }}>
            <ClipboardList size={18} />
          </div>
          <div className="docs-stat-content">
            <div className="docs-stat-value" style={{ color: '#9333ea' }}>
              {currentLoading ? <Loader size={16} className="spinning" /> : docsStats.needsDocsRequired}
            </div>
            <div className="docs-stat-label">Needs Documentation</div>
          </div>
        </div>

        {activeTab === 'bugs' ? (
          <div className="docs-stat-card">
            <div className="docs-stat-icon" style={{ background: '#fee2e2', color: '#dc2626' }}>
              <AlertTriangle size={18} />
            </div>
            <div className="docs-stat-content">
              <div className="docs-stat-value" style={{ color: '#dc2626' }}>
                {currentLoading ? <Loader size={16} className="spinning" /> : criticalCount}
              </div>
              <div className="docs-stat-label">Critical/Blocker</div>
            </div>
          </div>
        ) : (
          <div className="docs-stat-card">
            <div className="docs-stat-icon" style={{ background: '#fef3c7', color: '#d97706' }}>
              <User size={18} />
            </div>
            <div className="docs-stat-content">
              <div className="docs-stat-value" style={{ color: '#d97706' }}>
                {currentLoading ? <Loader size={16} className="spinning" /> : nplanStats.writerAssigned}
              </div>
              <div className="docs-stat-label">Writer Assigned</div>
            </div>
          </div>
        )}
      </div>

      {/* Analytics Dashboard */}
      {!currentLoading && currentItems.length > 0 && (
        <div className="docs-analytics-dashboard">
          <div className="docs-analytics-header">
            <TrendingUp size={18} />
            <h2>Analytics Dashboard</h2>
          </div>
          
          <div className="docs-analytics-grid">
            {/* Status Distribution - Donut Chart */}
            <div className="docs-analytics-card">
              <div className="docs-analytics-card-header">
                <PieChart size={16} />
                <h3>Status Distribution</h3>
              </div>
              <DonutChart 
                data={statusDistribution} 
                total={totalItems}
                centerLabel="total"
              />
            </div>

            {/* Trend Over Releases - Line Chart */}
            <div className="docs-analytics-card">
              <div className="docs-analytics-card-header">
                <TrendingUp size={16} />
                <h3>Trend Over Releases</h3>
              </div>
              {trendData.length > 0 ? (
                <TrendChart 
                  data={trendData}
                />
              ) : (
                <div className="docs-analytics-empty">No trend data available</div>
              )}
            </div>

            {/* By Sub-Component - Horizontal Bar Chart - Only show for Bugs */}
            {activeTab === 'bugs' && (
              <div className="docs-analytics-card">
                <div className="docs-analytics-card-header">
                  <Layers size={16} />
                  <h3>By Sub-Component</h3>
                  {subComponentFilter !== 'all' && (
                    <button
                      className="docs-chart-clear-btn"
                      onClick={() => setSubComponentFilter('all')}
                    >
                      Clear
                    </button>
                  )}
                </div>
                <SubComponentChart
                  data={subComponentCounts}
                  activeFilter={subComponentFilter}
                  onFilterChange={setSubComponentFilter}
                  maxItems={8}
                />
              </div>
            )}

            {/* Documentation Funnel - Only show for NPLANs with real data */}
            {activeTab === 'nplans' && (
              <div className="docs-analytics-card">
                <div className="docs-analytics-card-header">
                  <Filter size={16} />
                  <h3>Documentation Funnel</h3>
                  {funnelData?.completion_rate > 0 && (
                    <span className="funnel-completion-badge">
                      {funnelData.completion_rate}% Complete
                    </span>
                  )}
                </div>
                {loadingFunnel ? (
                  <div className="docs-analytics-empty">
                    <Loader size={16} className="spinning" /> Loading funnel...
                  </div>
                ) : computedFunnelData.length > 0 ? (
                  <DocsFunnel data={computedFunnelData} />
                ) : (
                  <div className="docs-analytics-empty">No funnel data available</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="docs-controls">
        <div className="docs-search">
          <Search size={16} />
          <input
            type="text"
            placeholder={activeTab === 'bugs' 
              ? "Search by key, summary, assignee, priority, status..." 
              : "Search by key, summary, assignee, status, writer..."}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        
        {/* Component Filter - Only for Bugs */}
        {activeTab === 'bugs' && (
          <div className="docs-filter-select">
            <Layers size={14} />
            <select
              value={componentFilter}
              onChange={(e) => setComponentFilter(e.target.value)}
            >
              <option value="all">All Components</option>
              {components.map(comp => (
                <option key={comp} value={comp}>{comp}</option>
              ))}
            </select>
          </div>
        )}
        
        {/* Sub-Component Filter - Only for Bugs */}
        {activeTab === 'bugs' && (
          <div className="docs-filter-select">
            <Tag size={14} />
            <select
              value={subComponentFilter}
              onChange={(e) => setSubComponentFilter(e.target.value)}
            >
              <option value="all">All Sub-Components</option>
              {subComponents.map(comp => (
                <option key={comp} value={comp}>{comp}</option>
              ))}
            </select>
          </div>
        )}
        
        {/* Docs Type Filter */}
        <div className="docs-filter-select">
          <FileEdit size={14} />
          <select
            value={docsTypeFilter}
            onChange={(e) => setDocsTypeFilter(e.target.value)}
          >
            <option value="all">All Types</option>
            <option value="release_notes">Needs Release Notes</option>
            <option value="documentation">Needs Documentation</option>
          </select>
        </div>
        
        <div className="docs-result-count">
          {filteredItems.length} of {totalItems} {activeTab === 'bugs' ? 'bugs' : 'NPLANs'}
        </div>
        
        {/* Collapse All Button */}
        {expandedBug && (
          <button
            className="docs-collapse-all-btn"
            onClick={() => setExpandedBug(null)}
            title="Collapse all expanded items"
          >
            <ChevronsUp size={14} />
            Collapse All
          </button>
        )}
      </div>

      {/* Date Range Filter */}
      <div className="docs-date-filter">
        <div className="docs-date-filter-type">
          <Calendar size={14} />
          <select
            value={dateFilterType}
            onChange={(e) => setDateFilterType(e.target.value)}
          >
            <option value="created">Created Date</option>
            <option value="resolved">Resolved Date</option>
          </select>
        </div>
        <div className="docs-date-inputs">
          <label>
            From:
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </label>
          <label>
            To:
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </label>
          {(dateFrom || dateTo) && (
            <button
              className="docs-date-clear"
              onClick={() => { setDateFrom(''); setDateTo(''); }}
              title="Clear date filter"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Item List */}
      <div className="docs-bug-list">
        {currentLoading ? (
          <div className="docs-loading-inline">
            <Loader className="spinning" size={20} />
            <span>Loading {activeTab === 'bugs' ? 'bugs' : 'NPLANs'}...</span>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="docs-empty">
            <FileText size={48} />
            <p>No {activeTab === 'bugs' ? 'bugs' : 'NPLANs'} found for this release.</p>
          </div>
        ) : (
          filteredItems.map(bug => (
            <div
              key={bug.key}
              className={`docs-bug-card ${expandedBug === bug.key ? 'expanded' : ''}`}
            >
              <div
                className="docs-bug-header"
                onClick={() => setExpandedBug(expandedBug === bug.key ? null : bug.key)}
              >
                <div className="docs-bug-expand">
                  {expandedBug === bug.key ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </div>
                <a
                  href={bug.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="docs-bug-key"
                  onClick={(e) => e.stopPropagation()}
                >
                  {bug.key}
                  <ExternalLink size={12} />
                </a>
                <div className="docs-bug-content">
                  <div className="docs-bug-summary">{bug.summary}</div>
                  {bug.description && (
                    <div className="docs-bug-preview">
                      {bug.description.substring(0, 120)}{bug.description.length > 120 ? '...' : ''}
                    </div>
                  )}
                </div>
                <div className="docs-bug-badges">
                  <span
                    className="docs-badge docs-priority-badge"
                    style={{
                      background: `${PRIORITY_COLORS[(bug.priority || '').toLowerCase()] || '#6b7280'}15`,
                      color: PRIORITY_COLORS[(bug.priority || '').toLowerCase()] || '#6b7280',
                    }}
                  >
                    {bug.priority || 'Unknown'}
                  </span>
                  <span className="docs-badge docs-status-badge">
                    <CheckCircle size={10} /> {bug.status}
                  </span>
                  {bug.sub_component && bug.sub_component !== 'Unknown' && (
                    <span className="docs-badge docs-component-badge">
                      <Layers size={10} /> {bug.sub_component}
                    </span>
                  )}
                </div>
              </div>

              {expandedBug === bug.key && (
                <div className="docs-bug-details">
                  <div className="docs-bug-detail-grid">
                    <div className="docs-detail-item">
                      <span className="docs-detail-label">Assignee</span>
                      <span className="docs-detail-value">{bug.assignee || 'Unassigned'}</span>
                    </div>
                    <div className="docs-detail-item">
                      <span className="docs-detail-label">Affected Version</span>
                      <span className="docs-detail-value">{bug.affected_version_str}</span>
                    </div>
                    <div className="docs-detail-item">
                      <span className="docs-detail-label">Created</span>
                      <span className="docs-detail-value">
                        {bug.created ? new Date(bug.created).toLocaleDateString() : '—'}
                      </span>
                    </div>
                    <div className="docs-detail-item">
                      <span className="docs-detail-label">Resolved</span>
                      <span className="docs-detail-value">
                        {bug.resolution_date ? new Date(bug.resolution_date).toLocaleDateString() : '—'}
                      </span>
                    </div>
                  </div>
                  {bug.description && (
                    <div className="docs-bug-description">
                      <div className="docs-detail-label">Description</div>
                      <div className="docs-detail-text">{bug.description}</div>
                    </div>
                  )}
                  <div className="docs-detail-badges">
                    <div className={`docs-release-note-badge ${bug.release_note === 'For Customer' ? 'active' : ''}`}>
                      <FileEdit size={14} />
                      <span>Release Note: <strong>{bug.release_note || '—'}</strong></span>
                    </div>
                    <div className={`docs-release-note-badge ${bug.documentation_required === 'Yes' ? 'active' : ''}`}>
                      <ClipboardList size={14} />
                      <span>Documentation Required: <strong>{bug.documentation_required || '—'}</strong></span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default DocumentationUpdatesSection;
