import React, { useState, useCallback, useMemo } from 'react';
import {
  RefreshCw,
  Search,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle,
  XCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Clock,
  Copy,
  FileText,
  X,
  Shuffle,
  BarChart3,
  AlertCircle,
  Info,
  Briefcase,
  Download,
  Zap,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Flame,
  Layers
} from 'lucide-react';
import './TestHealthSection.css';

const API_BASE = '/api';

const TestHealthSection = ({ selectedRelease }) => {
  const [flakyData, setFlakyData] = useState(null);
  const [loading, setLoading] = useState(false);  // Start with false - don't auto-load
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [hasLoaded, setHasLoaded] = useState(false);  // Track if user initiated load
  
  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [suiteFilter, setSuiteFilter] = useState('all');
  const [daysFilter, setDaysFilter] = useState(10);
  
  // Expanded test detail
  const [expandedTest, setExpandedTest] = useState(null);
  
  // Copied state
  const [copiedText, setCopiedText] = useState(null);
  
  // Info panel state
  const [showInfo, setShowInfo] = useState(false);
  
  // Sort state for table columns
  const [sortField, setSortField] = useState('flakiness_percent');
  const [sortDirection, setSortDirection] = useState('desc');

  // Fetch flaky tests data - only runs when user clicks "Analyze"
  // This prevents overwhelming Jenkins with automatic requests
  const fetchFlakyTests = useCallback(async (showRefresh = false) => {
    if (showRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    setHasLoaded(true);

    try {
      const response = await fetch(
        `${API_BASE}/jenkins/flaky-tests?days=${daysFilter}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch flaky tests data');
      }
      
      const data = await response.json();
      
      // Check for API-level error
      if (data.error) {
        setError(data.error);
        setFlakyData(data); // Still set data for summary display
      } else {
        setFlakyData(data);
        setError(null);
      }
    } catch (err) {
      console.error('Error fetching flaky tests:', err);
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [daysFilter]);

  // Don't auto-fetch - wait for user to click "Analyze"
  // This prevents overwhelming Jenkins with many parallel requests

  // Export flaky tests to CSV
  const exportToCSV = () => {
    if (!flakyData?.flaky_tests?.length) return;
    
    const headers = ['Test Name', 'Class', 'Suite', 'Flakiness %', 'Pass Rate', 'Total Runs', 'Passes', 'Failures', 'Severity', 'Last Failure'];
    const rows = flakyData.flaky_tests.map(test => [
      test.test_name,
      test.class_name || '',
      test.suite || '',
      test.flakiness_percent,
      test.pass_rate,
      test.total_runs,
      test.passes,
      test.failures,
      test.severity,
      test.last_failure || ''
    ]);
    
    const csvContent = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `flaky-tests-${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
  };

  // Get unique suites for filter
  const getSuites = () => {
    if (!flakyData?.flaky_tests) return [];
    const suites = new Set(flakyData.flaky_tests.map(t => t.suite));
    return Array.from(suites).sort();
  };

  // Filter tests
  const getFilteredTests = () => {
    if (!flakyData?.flaky_tests) return [];
    
    return flakyData.flaky_tests.filter(test => {
      // Search filter
      const searchMatch = !searchQuery || 
        test.test_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        test.class_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        test.suite?.toLowerCase().includes(searchQuery.toLowerCase());
      
      // Severity filter
      const severityMatch = severityFilter === 'all' || test.severity === severityFilter;
      
      // Suite filter
      const suiteMatch = suiteFilter === 'all' || test.suite === suiteFilter;
      
      return searchMatch && severityMatch && suiteMatch;
    });
  };

  // Handle column sort
  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  // Get sort icon for column header
  const getSortIcon = (field) => {
    if (sortField !== field) return <ArrowUpDown size={12} className="sort-icon inactive" />;
    return sortDirection === 'asc' 
      ? <ArrowUp size={12} className="sort-icon active" />
      : <ArrowDown size={12} className="sort-icon active" />;
  };

  // Severity rank for sorting
  const severityRank = { critical: 3, warning: 2, low: 1 };
  const trendRank = { increasing: 3, stable: 2, decreasing: 1 };

  // Top 5 offenders (always sorted by flakiness, unaffected by filters)
  const topOffenders = useMemo(() => {
    if (!flakyData?.flaky_tests?.length) return [];
    return [...flakyData.flaky_tests]
      .sort((a, b) => b.flakiness_percent - a.flakiness_percent)
      .slice(0, 5);
  }, [flakyData]);

  // Suite-level summary
  const suiteSummary = useMemo(() => {
    if (!flakyData?.flaky_tests?.length) return [];
    const suiteMap = {};
    flakyData.flaky_tests.forEach(test => {
      const suite = test.suite || 'Unknown';
      if (!suiteMap[suite]) {
        suiteMap[suite] = { suite, total: 0, critical: 0, warning: 0, low: 0, avgFlakiness: 0, totalFlakiness: 0 };
      }
      suiteMap[suite].total += 1;
      suiteMap[suite][test.severity] = (suiteMap[suite][test.severity] || 0) + 1;
      suiteMap[suite].totalFlakiness += test.flakiness_percent;
    });
    return Object.values(suiteMap)
      .map(s => ({ ...s, avgFlakiness: Math.round(s.totalFlakiness / s.total * 10) / 10 }))
      .sort((a, b) => b.critical - a.critical || b.avgFlakiness - a.avgFlakiness);
  }, [flakyData]);

  // Copy to clipboard
  const copyToClipboard = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(null), 2000);
  };

  // Get severity icon
  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'critical':
        return <XCircle size={16} className="severity-icon critical" />;
      case 'warning':
        return <AlertTriangle size={16} className="severity-icon warning" />;
      default:
        return <CheckCircle size={16} className="severity-icon low" />;
    }
  };

  // Get trend icon
  const getTrendIcon = (trend) => {
    switch (trend) {
      case 'increasing':
        return <TrendingUp size={14} className="trend-icon increasing" title="Getting worse" />;
      case 'decreasing':
        return <TrendingDown size={14} className="trend-icon decreasing" title="Improving" />;
      default:
        return <Minus size={14} className="trend-icon stable" title="Stable" />;
    }
  };

  // Render run history as visual dots
  const renderRunHistory = (history) => {
    return (
      <div className="run-history">
        {history.map((status, idx) => (
          <span
            key={idx}
            className={`run-dot ${status}`}
            title={`Run ${idx + 1}: ${status}`}
          >
            {status === 'pass' ? '✓' : status === 'fail' ? '✗' : '○'}
          </span>
        ))}
      </div>
    );
  };

  // Format relative time
  const formatRelativeTime = (isoString) => {
    if (!isoString) return 'N/A';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffDays > 0) return `${diffDays}d ago`;
    if (diffHours > 0) return `${diffHours}h ago`;
    return 'Recently';
  };

  // Apply filtering then sorting
  const filteredTests = useMemo(() => {
    const filtered = getFilteredTests();
    return [...filtered].sort((a, b) => {
      let aVal, bVal;
      switch (sortField) {
        case 'severity':
          aVal = severityRank[a.severity] || 0;
          bVal = severityRank[b.severity] || 0;
          break;
        case 'test_name':
          aVal = a.test_name.toLowerCase();
          bVal = b.test_name.toLowerCase();
          return sortDirection === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        case 'suite':
          aVal = (a.suite || '').toLowerCase();
          bVal = (b.suite || '').toLowerCase();
          return sortDirection === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        case 'flakiness_percent':
          aVal = a.flakiness_percent;
          bVal = b.flakiness_percent;
          break;
        case 'total_runs':
          aVal = a.total_runs;
          bVal = b.total_runs;
          break;
        case 'trend':
          aVal = trendRank[a.trend] || 0;
          bVal = trendRank[b.trend] || 0;
          break;
        default:
          aVal = a.flakiness_percent;
          bVal = b.flakiness_percent;
      }
      return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
    });
  }, [flakyData, searchQuery, severityFilter, suiteFilter, sortField, sortDirection]);

  // Show loading spinner while analyzing
  if (loading) {
    return (
      <div className="test-health-section">
        <div className="loading-state">
          <RefreshCw size={32} className="spinning" />
          <p>Analyzing test results from Jenkins...</p>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px' }}>
            This may take a minute as we fetch test reports from multiple builds.
          </p>
        </div>
      </div>
    );
  }

  // Show start prompt if user hasn't initiated analysis yet
  if (!hasLoaded && !flakyData) {
    return (
      <div className="test-health-section">
        <div className="section-header">
          <div className="header-left">
            <h1><Shuffle size={24} /> Flaky Tests</h1>
            <p>Track and manage tests with inconsistent results</p>
          </div>
        </div>
        <div className="empty-state" style={{ marginTop: '60px' }}>
          <Shuffle size={48} style={{ color: 'var(--accent-purple)', marginBottom: '16px' }} />
          <h3>Flaky Test Analysis</h3>
          <p style={{ marginBottom: '20px' }}>
            Analyze test results from Jenkins to identify tests with inconsistent pass/fail behavior.
          </p>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '16px' }}>
            <select
              value={daysFilter}
              onChange={(e) => setDaysFilter(Number(e.target.value))}
              className="days-select"
            >
              <option value={7}>Last 7 days</option>
              <option value={10}>Last 10 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <button
              className="refresh-btn"
              onClick={() => fetchFlakyTests(false)}
              style={{ padding: '10px 24px' }}
            >
              <RefreshCw size={16} />
              Start Analysis
            </button>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Note: Analysis fetches test reports from multiple Jenkins builds and may take a minute.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="test-health-section">
      {/* Header */}
      <div className="section-header">
        <div className="header-left">
          <h1><Shuffle size={24} /> Flaky Tests</h1>
          <p>Track and manage tests with inconsistent results</p>
        </div>
        <div className="header-actions">
          <select
            value={daysFilter}
            onChange={(e) => setDaysFilter(Number(e.target.value))}
            className="days-select"
          >
            <option value={7}>Last 7 days</option>
            <option value={10}>Last 10 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
          <button
            className={`refresh-btn ${refreshing ? 'refreshing' : ''}`}
            onClick={() => fetchFlakyTests(true)}
            disabled={refreshing}
          >
            <RefreshCw size={16} className={refreshing ? 'spinning' : ''} />
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          {flakyData?.flaky_tests?.length > 0 && (
            <button
              className="export-btn"
              onClick={exportToCSV}
              title="Export to CSV"
            >
              <Download size={16} />
              Export
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <AlertCircle size={18} />
          <span>{error}</span>
          <button onClick={() => fetchFlakyTests(true)}>Retry</button>
        </div>
      )}

      {/* Summary Stats */}
      <div className="summary-row">
        <div className="summary-cards">
          <div className="summary-card">
            <div className="card-icon flaky">
              <Shuffle size={20} />
            </div>
            <div className="card-content">
              <span className="card-value">{flakyData?.summary?.flaky_count || 0}</span>
              <span className="card-label">Flaky Tests</span>
            </div>
          </div>
          
          <div className="summary-card">
            <div className="card-icon critical">
              <XCircle size={20} />
            </div>
            <div className="card-content">
              <span className="card-value">{flakyData?.summary?.critical_count || 0}</span>
              <span className="card-label">Critical (&gt;50%)</span>
            </div>
          </div>
          
          <div className="summary-card">
            <div className="card-icon warning">
              <AlertTriangle size={20} />
            </div>
            <div className="card-content">
              <span className="card-value">{flakyData?.summary?.warning_count || 0}</span>
              <span className="card-label">Warning (10-50%)</span>
            </div>
          </div>
          
          <div className="summary-card">
            <div className="card-icon total">
              <BarChart3 size={20} />
            </div>
            <div className="card-content">
              <span className="card-value">{flakyData?.summary?.total_tests || 0}</span>
              <span className="card-label">Total Tests</span>
            </div>
          </div>
          
          <div className="summary-card">
            <div className="card-icon rate">
              <TrendingUp size={20} />
            </div>
            <div className="card-content">
              <span className="card-value">{flakyData?.summary?.flakiness_rate || 0}%</span>
              <span className="card-label">Flakiness Rate</span>
            </div>
          </div>
        </div>
        
        <button 
          className={`info-toggle-btn ${showInfo ? 'active' : ''}`}
          onClick={() => setShowInfo(!showInfo)}
          title="Show analysis details"
        >
          <Info size={18} />
        </button>
      </div>

      {/* Analysis Info Panel */}
      {showInfo && flakyData && (
        <div className="analysis-info-panel">
          <div className="info-section">
            <h4><Briefcase size={16} /> Jobs Being Tracked</h4>
            <div className="jobs-list">
              {flakyData?.filters?.jobs_analyzed?.map((job, idx) => (
                <span key={idx} className="job-tag">{job.replace('your-product-backend-', '').replace('_regression_test', '')}</span>
              )) || <span className="no-data">No jobs configured</span>}
            </div>
          </div>
          
          <div className="info-section">
            <h4><Info size={16} /> Analysis Criteria</h4>
            <ul className="criteria-list">
              <li><strong>Time Range:</strong> Last {flakyData?.filters?.days || 10} days</li>
              <li><strong>Min Runs:</strong> {flakyData?.filters?.min_runs || 3} executions required</li>
              <li><strong>Flakiness %:</strong> (failures ÷ total runs) × 100</li>
              <li><strong>Critical:</strong> &gt;50% failure rate</li>
              <li><strong>Warning:</strong> 10-50% failure rate</li>
              <li><strong>Low:</strong> &lt;10% failure rate</li>
            </ul>
          </div>
          
          <div className="info-section">
            <h4><BarChart3 size={16} /> Analysis Metadata</h4>
            <ul className="metadata-list">
              <li><strong>Builds Analyzed:</strong> {flakyData?.metadata?.builds_analyzed || 0}</li>
              <li><strong>Reports Found:</strong> {flakyData?.metadata?.reports_found || 0}</li>
              <li><strong>Reports Failed:</strong> {flakyData?.metadata?.reports_failed || 0}</li>
              <li><strong>Unique Tests:</strong> {flakyData?.metadata?.unique_tests || 0}</li>
              <li><strong>Analysis Time:</strong> {flakyData?.metadata?.analysis_time_seconds || 0}s</li>
              <li><strong>Generated:</strong> {flakyData?.metadata?.generated_at ? new Date(flakyData.metadata.generated_at).toLocaleString() : 'N/A'}</li>
            </ul>
          </div>
        </div>
      )}

      {/* Failure Patterns Section */}
      {flakyData?.failure_patterns?.patterns?.length > 0 && (
        <div className="failure-patterns-section">
          <h4><Zap size={16} /> Common Failure Patterns</h4>
          <div className="patterns-grid">
            {flakyData.failure_patterns.patterns.slice(0, 6).map((pattern, idx) => (
              <div key={idx} className={`pattern-card ${pattern.pattern}`}>
                <div className="pattern-header">
                  <span className="pattern-label">{pattern.label}</span>
                  <span className="pattern-count">{pattern.count} failures</span>
                </div>
                <div className="pattern-stats">
                  <span className="affected-tests">{pattern.affected_tests} test{pattern.affected_tests !== 1 ? 's' : ''} affected</span>
                </div>
                {pattern.sample_errors?.length > 0 && (
                  <div className="pattern-sample">
                    <code>{pattern.sample_errors[0].substring(0, 100)}...</code>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="patterns-footer">
            <span className="total-analyzed">
              {flakyData.failure_patterns.total_failures_analyzed} total failures analyzed
            </span>
          </div>
        </div>
      )}

      {/* Top Offenders */}
      {topOffenders.length > 0 && (
        <div className="top-offenders-section">
          <h4><Flame size={16} /> Top Offenders</h4>
          <div className="offenders-grid">
            {topOffenders.map((test, idx) => (
              <div 
                key={idx} 
                className={`offender-card offender-${test.severity}`}
                onClick={() => {
                  const tableIdx = filteredTests.findIndex(t => t.full_name === test.full_name);
                  if (tableIdx >= 0) setExpandedTest(tableIdx);
                }}
                title="Click to expand details in table"
              >
                <div className="offender-rank">#{idx + 1}</div>
                <div className="offender-body">
                  <div className="offender-header">
                    <span className={`offender-flakiness ${test.severity}`}>{test.flakiness_percent}%</span>
                    {getTrendIcon(test.trend)}
                  </div>
                  <div className="offender-name">{test.test_name}</div>
                  <div className="offender-meta">
                    <span className="offender-suite">{test.suite}</span>
                    <span className="offender-runs">{test.failures}/{test.total_runs} failed</span>
                  </div>
                  <div className="offender-history">
                    {renderRunHistory(test.run_history)}
                  </div>
                </div>
                <div className="offender-actions">
                  <button
                    className="offender-copy-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      copyToClipboard(test.full_name, `offender-${idx}`);
                    }}
                    title="Copy test path"
                  >
                    {copiedText === `offender-${idx}` ? <CheckCircle size={13} /> : <Copy size={13} />}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Suite-Level Summary */}
      {suiteSummary.length > 1 && (
        <div className="suite-summary-section">
          <h4><Layers size={16} /> Suite Breakdown</h4>
          <div className="suite-summary-grid">
            {suiteSummary.map((suite, idx) => (
              <div 
                key={idx} 
                className="suite-summary-card"
                onClick={() => setSuiteFilter(suiteFilter === suite.suite ? 'all' : suite.suite)}
                title={suiteFilter === suite.suite ? 'Click to clear filter' : `Click to filter by ${suite.suite}`}
              >
                <div className="suite-card-header">
                  <span className="suite-card-name">{suite.suite}</span>
                  <span className={`suite-card-badge ${suite.critical > 0 ? 'critical' : suite.warning > 0 ? 'warning' : 'low'}`}>
                    {suite.total} flaky
                  </span>
                </div>
                <div className="suite-card-bar">
                  <div 
                    className="suite-bar-critical" 
                    style={{ width: `${suite.total > 0 ? (suite.critical / suite.total) * 100 : 0}%` }}
                    title={`${suite.critical} critical`}
                  />
                  <div 
                    className="suite-bar-warning" 
                    style={{ width: `${suite.total > 0 ? (suite.warning / suite.total) * 100 : 0}%` }}
                    title={`${suite.warning} warning`}
                  />
                  <div 
                    className="suite-bar-low" 
                    style={{ width: `${suite.total > 0 ? (suite.low / suite.total) * 100 : 0}%` }}
                    title={`${suite.low} low`}
                  />
                </div>
                <div className="suite-card-stats">
                  {suite.critical > 0 && <span className="suite-stat critical">{suite.critical} critical</span>}
                  {suite.warning > 0 && <span className="suite-stat warning">{suite.warning} warning</span>}
                  {suite.low > 0 && <span className="suite-stat low">{suite.low} low</span>}
                  <span className="suite-stat avg">avg {suite.avgFlakiness}%</span>
                </div>
                {suiteFilter === suite.suite && (
                  <div className="suite-active-indicator">Active Filter</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="filters-bar">
        <div className="search-input">
          <Search size={16} />
          <input
            type="text"
            placeholder="Search test name, class, or suite..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className="clear-btn" onClick={() => setSearchQuery('')}>
              <X size={14} />
            </button>
          )}
        </div>

        <div className="filter-group">
          <label>Severity:</label>
          <div className="filter-pills">
            {['all', 'critical', 'warning', 'low'].map(sev => (
              <button
                key={sev}
                className={`filter-pill ${severityFilter === sev ? 'active' : ''} ${sev}`}
                onClick={() => setSeverityFilter(sev)}
              >
                {sev === 'all' ? 'All' : sev.charAt(0).toUpperCase() + sev.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-group">
          <label>Suite:</label>
          <select
            value={suiteFilter}
            onChange={(e) => setSuiteFilter(e.target.value)}
            className="suite-select"
          >
            <option value="all">All Suites</option>
            {getSuites().map(suite => (
              <option key={suite} value={suite}>{suite}</option>
            ))}
          </select>
        </div>

        <div className="filter-count">
          Showing {filteredTests.length} of {flakyData?.flaky_tests?.length || 0} flaky tests
        </div>
      </div>


      {/* Flaky Tests Table */}
      <div className="flaky-tests-table">
        <div className="table-header">
          <div className="col-severity sortable" onClick={() => handleSort('severity')}>
            Severity {getSortIcon('severity')}
          </div>
          <div className="col-test sortable" onClick={() => handleSort('test_name')}>
            Test Name {getSortIcon('test_name')}
          </div>
          <div className="col-suite sortable" onClick={() => handleSort('suite')}>
            Suite {getSortIcon('suite')}
          </div>
          <div className="col-flakiness sortable" onClick={() => handleSort('flakiness_percent')}>
            Flaky % {getSortIcon('flakiness_percent')}
          </div>
          <div className="col-history">Last 10 Runs</div>
          <div className="col-trend sortable" onClick={() => handleSort('trend')}>
            Trend {getSortIcon('trend')}
          </div>
          <div className="col-actions">Actions</div>
        </div>

        <div className="table-body">
          {filteredTests.length === 0 ? (
            <div className="empty-state">
              <CheckCircle size={48} />
              <h3>No flaky tests found</h3>
              <p>All tests are running consistently. Great job!</p>
            </div>
          ) : (
            filteredTests.map((test, idx) => (
              <React.Fragment key={idx}>
                <div 
                  className={`table-row ${expandedTest === idx ? 'expanded' : ''}`}
                  onClick={() => setExpandedTest(expandedTest === idx ? null : idx)}
                >
                  <div className="col-severity">
                    {getSeverityIcon(test.severity)}
                  </div>
                  <div className="col-test">
                    <div className="test-name">{test.test_name}</div>
                    <div className="test-path">{test.class_name}</div>
                  </div>
                  <div className="col-suite">
                    <span className="suite-badge">{test.suite}</span>
                  </div>
                  <div className="col-flakiness">
                    <span className={`flakiness-value ${test.severity}`}>
                      {test.flakiness_percent}%
                    </span>
                  </div>
                  <div className="col-history">
                    {renderRunHistory(test.run_history)}
                  </div>
                  <div className="col-trend">
                    {getTrendIcon(test.trend)}
                  </div>
                  <div className="col-actions">
                    <button
                      className="action-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedTest(expandedTest === idx ? null : idx);
                      }}
                    >
                      {expandedTest === idx ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </button>
                  </div>
                </div>

                {/* Expanded Detail Panel */}
                {expandedTest === idx && (
                  <div className="detail-panel">
                    <div className="detail-header">
                      <h3>{test.test_name}</h3>
                      <span className="detail-path">{test.full_name}</span>
                    </div>

                    <div className="detail-grid">
                      <div className="detail-section stats">
                        <h4>Statistics</h4>
                        <div className="stats-grid">
                          <div className="stat-item">
                            <span className="stat-label">Total Runs</span>
                            <span className="stat-value">{test.total_runs}</span>
                          </div>
                          <div className="stat-item">
                            <span className="stat-label">Passes</span>
                            <span className="stat-value pass">{test.passes}</span>
                          </div>
                          <div className="stat-item">
                            <span className="stat-label">Failures</span>
                            <span className="stat-value fail">{test.failures}</span>
                          </div>
                          <div className="stat-item">
                            <span className="stat-label">Avg Duration</span>
                            <span className="stat-value">{test.avg_duration}s</span>
                          </div>
                          <div className="stat-item">
                            <span className="stat-label">Last Failure</span>
                            <span className="stat-value">{formatRelativeTime(test.last_failure)}</span>
                          </div>
                        </div>
                      </div>

                      <div className="detail-section patterns">
                        <h4>Failure Patterns</h4>
                        {test.failure_reasons && test.failure_reasons.length > 0 ? (
                          <div className="pattern-tags">
                            {test.failure_reasons.map((reason, i) => (
                              <span key={i} className={`pattern-tag ${reason}`}>
                                {reason}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="no-patterns">No patterns detected</p>
                        )}
                      </div>
                    </div>

                    <div className="detail-actions">
                      <button
                        className="detail-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          copyToClipboard(test.full_name, 'path');
                        }}
                      >
                        <Copy size={14} />
                        {copiedText === 'path' ? 'Copied!' : 'Copy Path'}
                      </button>
                      <button
                        className="detail-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          copyToClipboard(`pytest ${test.full_name} -v`, 'command');
                        }}
                      >
                        <FileText size={14} />
                        {copiedText === 'command' ? 'Copied!' : 'Copy pytest Command'}
                      </button>
                    </div>
                  </div>
                )}
              </React.Fragment>
            ))
          )}
        </div>
      </div>

      {/* Metadata Footer */}
      {flakyData?.metadata && (
        <div className="metadata-footer">
          <Clock size={14} />
          <span>
            Analysis completed in {flakyData.metadata.analysis_time_seconds}s
            {' • '}
            Generated: {new Date(flakyData.metadata.generated_at).toLocaleString()}
          </span>
        </div>
      )}
    </div>
  );
};

export default TestHealthSection;
