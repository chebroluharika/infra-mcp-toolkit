import React, { useState, useEffect } from 'react';
import {
  TestTube,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Smartphone,
  Globe,
  Server,
  Monitor,
  Search,
  ExternalLink,
  RefreshCw,
  TrendingUp,
  AlertTriangle,
  Layers,
  Cpu,
  Users,
  User,
  Mail,
  ChevronDown,
  ChevronRight
} from 'lucide-react';
import { API_BASE_URL } from '../../config';

const PlatformIcon = ({ platform, size = 16 }) => {
  const icons = {
    iOS: <Smartphone size={size} />,
    Android: <Smartphone size={size} />,
    Web: <Globe size={size} />,
    API: <Server size={size} />,
    Backend: <Server size={size} />,
    Mac: <Monitor size={size} />,
    Windows: <Monitor size={size} />,
    ChromeOS: <Monitor size={size} />,
    Linux: <Monitor size={size} />,
  };
  return icons[platform] || <Monitor size={size} />;
};

// Categorize test runs into areas
const categorizeRuns = (runs) => {
  const categories = {
    platform: { label: 'Platform Tests', icon: <Smartphone size={16} />, runs: [] },
    integration: { label: 'Integration Tests', icon: <Layers size={16} />, runs: [] },
    automation: { label: 'Automation Suites', icon: <Cpu size={16} />, runs: [] },
    other: { label: 'Other Tests', icon: <TestTube size={16} />, runs: [] },
  };

  runs.forEach(run => {
    const name = run.name.toLowerCase();
    if (name.includes('integration') || name.includes('e2e') || name.includes('end-to-end')) {
      categories.integration.runs.push(run);
    } else if (name.includes('regression') || name.includes('automation') || name.includes('automated')) {
      categories.automation.runs.push(run);
    } else if (name.includes('android') || name.includes('ios') || name.includes('mac') || 
               name.includes('windows') || name.includes('chrome') || name.includes('linux') ||
               name.includes('web') || name.includes('mobile')) {
      categories.platform.runs.push(run);
    } else {
      categories.other.runs.push(run);
    }
  });

  return categories;
};

const TestRailSection = ({ testRailData, automationData, onRefresh, isRefreshing, selectedRelease }) => {
  // Use global selectedRelease prop directly (no local dropdown)
  const [viewMode, setViewMode] = useState('overview');
  const [syncing, setSyncing] = useState(false);
  const [untestedByOwner, setUntestedByOwner] = useState(null);
  const [loadingOwners, setLoadingOwners] = useState(false);
  const [expandedOwners, setExpandedOwners] = useState({});
  const [milestoneData, setMilestoneData] = useState(null);
  const [loadingMilestone, setLoadingMilestone] = useState(false);
  const [releaseConfig, setReleaseConfig] = useState(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  
  // State for expanded run test cases
  const [selectedRun, setSelectedRun] = useState(null);
  const [runTestCases, setRunTestCases] = useState(null);
  const [loadingTestCases, setLoadingTestCases] = useState(false);
  
  // Refresh counter to force re-fetch
  const [refreshCounter, setRefreshCounter] = useState(0);

  // Fetch release configuration from backend (centralized config)
  useEffect(() => {
    const fetchReleaseConfig = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/config/releases`);
        if (response.ok) {
          const config = await response.json();
          setReleaseConfig(config);
        }
      } catch (error) {
        console.error('Failed to load release configuration:', error);
      } finally {
        setLoadingConfig(false);
      }
    };
    
    fetchReleaseConfig();
  }, []);

  // Build milestone ID map from config
  const milestoneIdMap = React.useMemo(() => {
    if (!releaseConfig?.releases) return {};
    
    const map = {};
    releaseConfig.releases.forEach(release => {
      map[release.id] = release.milestone_id;
    });
    return map;
  }, [releaseConfig]);

  // Fetch TestRail data for selected release
  useEffect(() => {
    // Don't fetch until we have the config and selectedRelease
    if (!releaseConfig || Object.keys(milestoneIdMap).length === 0 || !selectedRelease) return;
    
    const fetchMilestoneData = async () => {
      setLoadingMilestone(true);
      // Clear untested by owner data when release changes or refresh triggered
      setUntestedByOwner(null);
      
      try {
        const milestoneId = milestoneIdMap[selectedRelease];
        const projectId = releaseConfig?.default_project_id || 38;
        
        if (!milestoneId) {
          setMilestoneData(null);
          setLoadingMilestone(false);
          return;
        }
        
        // Add cache-busting parameter when refreshing
        const cacheBust = refreshCounter > 0 ? `&_t=${Date.now()}` : '';
        const response = await fetch(
          `${API_BASE_URL}/api/testrail/milestone-data?project_id=${projectId}&milestone_id=${milestoneId}${cacheBust}`
        );
        
        if (response.ok) {
          const data = await response.json();
          setMilestoneData(data);
        } else {
          setMilestoneData(null);
        }
      } catch (error) {
        setMilestoneData(null);
      } finally {
        setLoadingMilestone(false);
      }
    };

    fetchMilestoneData();
  }, [selectedRelease, milestoneIdMap, releaseConfig, refreshCounter]);

  // Fetch untested by owner data ONLY when user clicks "By Owner" tab (lazy load)
  useEffect(() => {
    if (viewMode !== 'owners') return; // Only fetch when on owners tab
    if (!releaseConfig || Object.keys(milestoneIdMap).length === 0 || !selectedRelease) return;
    
    const fetchUntestedByOwner = async () => {
      setLoadingOwners(true);
      try {
        const milestoneId = milestoneIdMap[selectedRelease];
        const projectId = releaseConfig?.default_project_id || 38;
        
        if (!milestoneId) {
          setUntestedByOwner(null);
          setLoadingOwners(false);
          return;
        }
        
        // Add cache-busting parameter when refreshing
        const cacheBust = refreshCounter > 0 ? `&_t=${Date.now()}` : '';
        const response = await fetch(
          `${API_BASE_URL}/api/testrail/untested-by-owner?project_id=${projectId}&milestone_id=${milestoneId}${cacheBust}`
        );
        
        if (response.ok) {
          const data = await response.json();
          setUntestedByOwner(data);
        } else {
          setUntestedByOwner(null);
        }
      } catch (error) {
        setUntestedByOwner(null);
      } finally {
        setLoadingOwners(false);
      }
    };
    fetchUntestedByOwner();
  }, [viewMode, selectedRelease, milestoneIdMap, releaseConfig, refreshCounter]);

  const toggleOwnerExpand = (ownerName) => {
    setExpandedOwners(prev => ({
      ...prev,
      [ownerName]: !prev[ownerName]
    }));
  };

  // Fetch test cases for a specific run
  const handleRunClick = async (run) => {
    if (!run.id) return;
    
    setSelectedRun(run);
    setLoadingTestCases(true);
    setRunTestCases(null);
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/testrail/run/${run.id}/tests`);
      if (response.ok) {
        const data = await response.json();
        setRunTestCases(data);
      }
    } catch (error) {
      console.error('Failed to fetch test cases:', error);
    } finally {
      setLoadingTestCases(false);
    }
  };

  const closeRunModal = () => {
    setSelectedRun(null);
    setRunTestCases(null);
  };

  const handleSync = async () => {
    if (syncing || isRefreshing) return;
    setSyncing(true);
    try {
      // Increment refresh counter to trigger re-fetch of TestRail data
      setRefreshCounter(prev => prev + 1);
      
      // Also call parent refresh if provided (for overview data)
      if (onRefresh) {
        await onRefresh();
      }
    } finally {
      setSyncing(false);
    }
  };

  // Use milestones from backend config
  const milestones = releaseConfig?.releases?.map(release => ({
    id: release.id,
    name: release.display_name,
    status: release.status,
    progress: release.status === 'completed' ? 100 : 0,
  })) || testRailData?.milestones || [];

  // Get milestone name for display
  const selectedMilestoneInfo = milestones.find(m => m.id === selectedRelease);
  const milestoneName = selectedMilestoneInfo?.name || selectedRelease;

  // Use milestone-specific data if available, otherwise fall back to automationData prop
  const dataToUse = milestoneData || automationData;
  
  // Use API data from milestoneData or automationData.overall
  const overallStats = dataToUse?.overall || {
    totalCases: 0,
    passed: 0,
    failed: 0,
    blocked: 0,
    skipped: 0,
    untested: 0,
    passRate: 0,
  };

  // Test runs from API
  const testRuns = dataToUse?.testRuns || [];
  const platformData = dataToUse?.byPlatform || {};

  const totalStats = {
    total: overallStats.totalCases || 0,
    passed: overallStats.passed || 0,
    failed: overallStats.failed || 0,
    blocked: overallStats.blocked || 0,
    notRun: overallStats.untested || 0,
  };

  const passRate = overallStats.passRate || (totalStats.total > 0 ? Math.round((totalStats.passed / totalStats.total) * 100) : 0);
  
  // Check if we have data:
  // - milestoneData !== null means API call succeeded
  // - totalStats.total > 0 means milestone has test cases
  const hasData = milestoneData !== null && totalStats.total > 0;
  const isEmptyMilestone = milestoneData !== null && totalStats.total === 0;
  const isConnectionError = milestoneData === null && !loadingMilestone;

  // Categorize runs
  const categorizedRuns = categorizeRuns(testRuns);

  // Get failed test runs for release qualification
  const failedRuns = testRuns.filter(r => r.failed > 0).sort((a, b) => b.failed - a.failed);

  // Show loading state while fetching config
  if (loadingConfig) {
    return (
      <div className="testrail-section">
        <div className="section-page-header">
          <div className="header-left">
            <h1><TestTube size={24} /> TestRail - Test Cases</h1>
            <p>Loading configuration...</p>
          </div>
        </div>
        <div className="testrail-hero-card not-connected">
          <div className="not-connected-content">
            <RefreshCw size={48} className="spin" />
            <h2>Loading Release Configuration...</h2>
            <p>Fetching available releases and milestones from backend.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="testrail-section">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><TestTube size={24} /> TestRail - Test Cases</h1>
          <p>Milestone: {milestoneName}</p>
        </div>
        <div className="header-actions">
          <button 
            className={`action-btn secondary ${syncing ? 'syncing' : ''}`}
            onClick={handleSync}
            disabled={syncing || isRefreshing}
          >
            <RefreshCw size={16} className={syncing ? 'spin' : ''} /> 
            {syncing ? 'Syncing...' : 'Sync'}
          </button>
          <a 
            href={`https://your-org.testrail.io/index.php?/milestones/view/${milestoneIdMap[selectedRelease] || 5167}`}
            target="_blank" 
            rel="noopener noreferrer"
            className="action-btn primary"
          >
            Open TestRail <ExternalLink size={16} />
          </a>
        </div>
      </div>

      {/* Filters */}
      <div className="filters-bar">
        <div className="filter-group">
          <label>View</label>
          <div className="toggle-group">
            <button className={viewMode === 'overview' ? 'active' : ''} onClick={() => setViewMode('overview')}>
              Overview
            </button>
            <button className={viewMode === 'runs' ? 'active' : ''} onClick={() => setViewMode('runs')}>
              All Runs
            </button>
            <button className={viewMode === 'owners' ? 'active' : ''} onClick={() => setViewMode('owners')}>
              <Users size={14} /> By Owner
            </button>
          </div>
        </div>
        <div className="search-box">
          <Search size={16} />
          <input type="text" placeholder="Search test runs..." />
        </div>
      </div>

      {/* Tech Preview Banner */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '14px 18px',
        background: 'linear-gradient(135deg, #fef2f2, #fff1f2)',
        border: '2px solid #fca5a5', borderRadius: 'var(--radius-md)',
        marginBottom: 20, fontSize: 14,
        boxShadow: '0 2px 8px rgba(220, 38, 38, 0.08)',
      }}>
        <AlertTriangle size={20} style={{ color: '#dc2626', flexShrink: 0 }} />
        <span style={{ color: '#991b1b' }}>
          <strong style={{ color: '#dc2626', fontSize: 15 }}>Tech Preview</strong>
          <span style={{ margin: '0 6px', opacity: 0.4 }}>|</span>
          Data and analysis results may be incomplete.
        </span>
      </div>

      {loadingMilestone ? (
        <div className="testrail-hero-card not-connected">
          <div className="not-connected-content">
            <RefreshCw size={48} className="spin" />
            <h2>Loading {selectedRelease} Data...</h2>
            <p>Fetching TestRail data for the selected milestone.</p>
          </div>
        </div>
      ) : isConnectionError ? (
        <div className="testrail-hero-card not-connected">
          <div className="not-connected-content">
            <AlertCircle size={48} />
            <h2>Connection Error</h2>
            <p>Unable to fetch data from TestRail. Please check your backend connection.</p>
            <p style={{ marginTop: '10px', fontSize: '14px', opacity: 0.7 }}>
              Milestone ID: {milestoneIdMap[selectedRelease] || 'Unknown'}
            </p>
            <a 
              href={`https://your-org.testrail.io/index.php?/milestones/view/${milestoneIdMap[selectedRelease] || 5167}`}
              target="_blank" 
              rel="noopener noreferrer" 
              className="action-btn primary"
            >
              Open TestRail Directly <ExternalLink size={16} />
            </a>
          </div>
        </div>
      ) : isEmptyMilestone ? (
        <div className="testrail-hero-card not-connected" style={{ borderColor: 'var(--accent-yellow)' }}>
          <div className="not-connected-content">
            <Clock size={48} style={{ color: 'var(--accent-yellow)' }} />
            <h2>No Test Data for {selectedRelease}</h2>
            <p>
              Milestone <strong>{milestoneName}</strong> exists but has no test cases or test runs.
            </p>
            <p style={{ marginTop: '10px', fontSize: '14px', opacity: 0.8 }}>
              This is normal for completed releases where test data has been archived or removed.
            </p>
            <p style={{ marginTop: '5px', fontSize: '14px', opacity: 0.7 }}>
              Milestone ID: {milestoneIdMap[selectedRelease]}
            </p>
            <div style={{ marginTop: '20px' }}>
              <a 
                href={`https://your-org.testrail.io/index.php?/milestones/view/${milestoneIdMap[selectedRelease]}`}
                target="_blank" 
                rel="noopener noreferrer" 
                className="action-btn primary"
              >
                View Milestone in TestRail <ExternalLink size={16} />
              </a>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Summary Stats Row */}
          <div className="testrail-summary-row">
            <div className="summary-card main">
              <div className="pass-rate-display">
                <div className="rate-circle" style={{
                  '--progress': `${passRate * 3.6}deg`,
                  '--color': passRate >= 90 ? 'var(--accent-green)' : passRate >= 70 ? 'var(--accent-yellow)' : 'var(--accent-red)'
                }}>
                  <span className="rate-number">{Math.round(passRate)}</span>
                  <span className="rate-symbol">%</span>
                </div>
                <div className="rate-label">Pass Rate</div>
              </div>
            </div>
            <div className="summary-card">
              <div className="stat-icon"><TestTube size={20} /></div>
              <div className="stat-value">{totalStats.total.toLocaleString()}</div>
              <div className="stat-label">Total Tests</div>
            </div>
            <div className="summary-card success">
              <div className="stat-icon"><CheckCircle2 size={20} /></div>
              <div className="stat-value">{totalStats.passed.toLocaleString()}</div>
              <div className="stat-label">Passed</div>
            </div>
            <div className="summary-card danger">
              <div className="stat-icon"><XCircle size={20} /></div>
              <div className="stat-value">{totalStats.failed}</div>
              <div className="stat-label">Failed</div>
            </div>
            <div className="summary-card warning">
              <div className="stat-icon"><Clock size={20} /></div>
              <div className="stat-value">{totalStats.notRun}</div>
              <div className="stat-label">Untested</div>
            </div>
            <div className="summary-card">
              <div className="stat-icon"><Layers size={20} /></div>
              <div className="stat-value">{testRuns.length}</div>
              <div className="stat-label">Test Runs</div>
            </div>
          </div>

          {/* OVERVIEW VIEW - Two Column Layout */}
          {viewMode === 'overview' && (
            <div className="testrail-content-grid">
              {/* Left Column - Test Runs by Platform */}
              <div className="content-column">
                <div className="section-card">
                  <div className="card-header">
                    <h3><Smartphone size={18} /> Results by Platform</h3>
                  </div>
                  <div className="platform-results-list">
                    {Object.entries(platformData).length > 0 ? (
                      Object.entries(platformData).map(([platform, data]) => {
                        const rate = data.passRate || data.coverage || 0;
                        return (
                          <div key={platform} className="platform-result-row">
                            <div className="platform-info">
                              <PlatformIcon platform={platform} size={18} />
                              <span className="platform-name">{platform}</span>
                            </div>
                            <div className="platform-bar">
                              <div className="bar-track">
                                <div className="bar-fill" style={{ 
                                  width: `${rate}%`,
                                  background: rate >= 95 ? 'var(--accent-green)' : rate >= 80 ? 'var(--accent-yellow)' : 'var(--accent-red)'
                                }} />
                              </div>
                            </div>
                            <div className="platform-stats-inline">
                              <span className="rate" style={{ color: rate >= 95 ? 'var(--accent-green)' : rate >= 80 ? 'var(--accent-yellow)' : 'var(--accent-red)' }}>
                                {rate}%
                              </span>
                              <span className="counts">
                                <span className="passed">{data.passed}</span>/<span className="total">{data.total}</span>
                              </span>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="no-data">No platform data available</div>
                    )}
                  </div>
                </div>

                {/* Release Qualification - Failed Tests */}
                {failedRuns.length > 0 && (
                  <div className="section-card warning-card">
                    <div className="card-header">
                      <h3><AlertTriangle size={18} /> Failed Tests - Release Blockers</h3>
                      <span className="badge danger">{totalStats.failed} failures</span>
                    </div>
                    <div className="failed-tests-list">
                      {failedRuns.slice(0, 5).map((run, idx) => (
                        <div key={idx} className="failed-test-row">
                          <div className="test-info">
                            <XCircle size={14} className="fail-icon" />
                            <span className="test-name">{run.name}</span>
                          </div>
                          <div className="test-stats">
                            <span className="failed-count">{run.failed} failed</span>
                            <span className="pass-rate">{run.passRate}%</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Right Column - Test Runs by Area */}
              <div className="content-column">
                <div className="section-card">
                  <div className="card-header">
                    <h3><TrendingUp size={18} /> Test Runs by Area</h3>
                  </div>
                  <div className="test-runs-by-area">
                    {Object.entries(categorizedRuns)
                      .filter(([_, cat]) => cat.runs.length > 0)
                      .map(([key, category]) => (
                        <div key={key} className="area-group">
                          <div className="area-header">
                            {category.icon}
                            <span>{category.label}</span>
                            <span className="area-count">{category.runs.length} runs</span>
                          </div>
                          <div className="area-runs">
                            {category.runs.map((run, idx) => {
                              const passedPct = run.total > 0 ? (run.passed / run.total) * 100 : 0;
                              const failedPct = run.total > 0 ? (run.failed / run.total) * 100 : 0;
                              // "Other" includes: blocked, untested, retest, skipped, etc.
                              const otherPct = run.total > 0 ? ((run.other || 0) / run.total) * 100 : 0;
                              return (
                                <div 
                                  key={idx} 
                                  className="area-run-item clickable"
                                  onClick={() => handleRunClick(run)}
                                  title="Click to view test cases"
                                >
                                  <span className="run-name">{run.name}</span>
                                  <div className="run-mini-bar">
                                    <div className="mini-fill passed" style={{ width: `${passedPct}%` }} />
                                    <div className="mini-fill failed" style={{ width: `${failedPct}%` }} />
                                    <div className="mini-fill other" style={{ width: `${otherPct}%` }} />
                                  </div>
                                  <span className={`run-rate ${run.passRate >= 95 ? 'good' : run.passRate >= 80 ? 'warning' : 'danger'}`}>
                                    {run.passRate}%
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ALL RUNS VIEW - Full Table */}
          {viewMode === 'runs' && (
            <div className="section-card full-width">
              <div className="card-header">
                <h3><TestTube size={18} /> All Test Runs ({testRuns.length})</h3>
                <span className="header-subtitle">Complete list of test runs in selected milestone</span>
              </div>
              <div className="runs-table">
                <div className="table-header">
                  <span className="col-name">Test Run Name</span>
                  <span className="col-total">Total</span>
                  <span className="col-passed">Passed</span>
                  <span className="col-failed">Failed</span>
                  <span className="col-rate">Pass Rate</span>
                  <span className="col-status">Status</span>
                </div>
                {testRuns.map((run, idx) => {
                  const statusClass = run.passRate >= 95 ? 'good' : run.passRate >= 80 ? 'warning' : 'danger';
                  const statusText = run.passRate >= 95 ? 'Passing' : run.passRate >= 80 ? 'At Risk' : 'Failing';
                  return (
                    <div key={idx} className="table-row">
                      <span className="col-name">
                        <TestTube size={14} className="row-icon" />
                        {run.name}
                      </span>
                      <span className="col-total">{run.total}</span>
                      <span className="col-passed">{run.passed}</span>
                      <span className="col-failed">{run.failed > 0 ? run.failed : '-'}</span>
                      <span className={`col-rate ${statusClass}`}>{run.passRate}%</span>
                      <span className={`col-status ${statusClass}`}>
                        <span className={`status-badge ${statusClass}`}>{statusText}</span>
                      </span>
                    </div>
                  );
                })}
              </div>
              {testRuns.length === 0 && (
                <div className="no-data">No test runs found for this milestone</div>
              )}
            </div>
          )}

          {/* BY OWNER VIEW - Untested Tests by Assignee */}
          {viewMode === 'owners' && (
            <div className="section-card full-width owners-view">
              <div className="card-header">
                <h3><Users size={18} /> Untested Tests by Owner</h3>
                <span className="header-subtitle">
                  Track pending test execution by responsible owner
                </span>
              </div>
              
              {loadingOwners ? (
                <div className="loading-state">
                  <RefreshCw size={24} className="spin" />
                  <span>Loading owner data...</span>
                </div>
              ) : untestedByOwner ? (
                <>
                  {/* Summary Stats */}
                  <div className="owners-summary">
                    <div className="summary-stat">
                      <Clock size={16} />
                      <span className="stat-value">{untestedByOwner.summary?.total_pending_tests || untestedByOwner.summary?.total_not_executed || 0}</span>
                      <span className="stat-label">Pending Tests</span>
                    </div>
                    <div className="summary-stat">
                      <Users size={16} />
                      <span className="stat-value">{untestedByOwner.summary?.total_assignees || untestedByOwner.summary?.total_owners || 0}</span>
                      <span className="stat-label">Assignees</span>
                    </div>
                    <div className="summary-stat highlight-warning">
                      <AlertCircle size={16} />
                      <span className="stat-value">{untestedByOwner.summary?.total_unassigned || 0}</span>
                      <span className="stat-label">Unassigned</span>
                    </div>
                    <div className="summary-stat">
                      <Layers size={16} />
                      <span className="stat-value">{untestedByOwner.summary?.runs_checked || untestedByOwner.summary?.total_runs_with_untested || 0}</span>
                      <span className="stat-label">Runs Checked</span>
                    </div>
                  </div>

                  {/* Release Info */}
                  {untestedByOwner.release && (
                    <div className="release-badge">
                      Release: <strong>{untestedByOwner.release}</strong>
                    </div>
                  )}

                  {/* Assignees Table - TEST LEVEL */}
                  <div className="owners-table">
                    <div className="table-header">
                      <span className="col-expand"></span>
                      <span className="col-owner">Assignee</span>
                      <span className="col-untested">Pending</span>
                      <span className="col-failed">Failed</span>
                      <span className="col-blocked">Blocked</span>
                      <span className="col-other">Other</span>
                    </div>
                    
                    {(untestedByOwner.by_assignee || untestedByOwner.by_owner || []).map((owner, idx) => {
                      const assigneeName = owner.assignee || owner.owner;
                      const totalTests = owner.total_tests || 0;
                      const byStatus = owner.by_status || {};
                      const tests = owner.tests || owner.runs || [];
                      const isExpanded = expandedOwners[assigneeName];
                      
                      return (
                        <React.Fragment key={idx}>
                          <div 
                            className={`table-row owner-row ${isExpanded ? 'expanded' : ''}`}
                            onClick={() => toggleOwnerExpand(assigneeName)}
                          >
                            <span className="col-expand">
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </span>
                            <span className="col-owner">
                              <User size={14} className="row-icon" />
                              <span className="owner-name">
                                {assigneeName.startsWith('User #') ? (
                                  <a 
                                    href={`https://your-org.testrail.io/index.php?/admin/users/overview/${owner.user_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    title="Click to view in TestRail"
                                    className="user-link"
                                  >
                                    {assigneeName}
                                  </a>
                                ) : assigneeName}
                              </span>
                              {owner.email && (
                                <a 
                                  href={`mailto:${owner.email}`} 
                                  className="owner-email"
                                  onClick={(e) => e.stopPropagation()}
                                  title={owner.email}
                                >
                                  <Mail size={12} />
                                </a>
                              )}
                            </span>
                            <span className="col-untested highlight-warning">{byStatus.untested || totalTests}</span>
                            <span className="col-failed highlight-danger">{byStatus.failed || 0}</span>
                            <span className="col-blocked">{byStatus.blocked || 0}</span>
                            <span className="col-other">{byStatus.other || 0}</span>
                          </div>
                          
                          {/* Expanded Tests Detail - Shows individual test cases */}
                          {isExpanded && tests && (
                            <div className="owner-runs-detail tests-detail">
                              <div className="tests-header">
                                <span className="test-col-name">Test Case</span>
                                <span className="test-col-run">Test Run</span>
                                <span className="test-col-status">Status</span>
                                <span className="test-col-link"></span>
                              </div>
                              {tests.slice(0, 20).map((test, testIdx) => (
                                <div key={testIdx} className="test-detail-row">
                                  <span className="test-col-name" title={test.title || test.run_name}>
                                    <TestTube size={12} />
                                    {test.title || test.run_name}
                                  </span>
                                  <span className="test-col-run">{test.run_name || '-'}</span>
                                  <span className={`test-col-status status-${test.status || 'untested'}`}>
                                    {test.status || 'untested'}
                                  </span>
                                  {(test.run_url || test.url) && (
                                    <a 
                                      href={test.run_url || test.url} 
                                      target="_blank" 
                                      rel="noopener noreferrer"
                                      className="run-link"
                                    >
                                      <ExternalLink size={12} />
                                    </a>
                                  )}
                                </div>
                              ))}
                              {tests.length > 20 && (
                                <div className="more-tests">
                                  +{tests.length - 20} more tests...
                                </div>
                              )}
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                    
                    {/* Unassigned Section - Tests with no assignee */}
                    {(untestedByOwner.unassigned?.total > 0 || untestedByOwner.unassigned?.total_not_executed > 0 || untestedByOwner.unassigned?.total_untested > 0) && (
                      <>
                        <div 
                          className={`table-row owner-row unassigned ${expandedOwners['_unassigned'] ? 'expanded' : ''}`}
                          onClick={() => toggleOwnerExpand('_unassigned')}
                        >
                          <span className="col-expand">
                            {expandedOwners['_unassigned'] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </span>
                          <span className="col-owner">
                            <AlertCircle size={14} className="row-icon warning" />
                            <span className="owner-name">Unassigned Tests</span>
                          </span>
                          <span className="col-untested highlight-warning">
                            {untestedByOwner.unassigned.total || untestedByOwner.unassigned.total_not_executed || untestedByOwner.unassigned.total_untested || 0}
                          </span>
                          <span className="col-failed">-</span>
                          <span className="col-blocked">-</span>
                          <span className="col-other">
                            <span className="no-owner-badge">No Assignee</span>
                          </span>
                        </div>
                        
                        {expandedOwners['_unassigned'] && (untestedByOwner.unassigned.tests || untestedByOwner.unassigned.runs) && (
                          <div className="owner-runs-detail tests-detail">
                            <div className="tests-header">
                              <span className="test-col-name">Test Case</span>
                              <span className="test-col-run">Test Run</span>
                              <span className="test-col-status">Status</span>
                              <span className="test-col-link"></span>
                            </div>
                            {(untestedByOwner.unassigned.tests || untestedByOwner.unassigned.runs || []).slice(0, 20).map((test, testIdx) => (
                              <div key={testIdx} className="test-detail-row">
                                <span className="test-col-name" title={test.title || test.run_name}>
                                  <TestTube size={12} />
                                  {test.title || test.run_name}
                                </span>
                                <span className="test-col-run">{test.run_name || '-'}</span>
                                <span className={`test-col-status status-${test.status || 'untested'}`}>
                                  {test.status || 'untested'}
                                </span>
                                {(test.run_url || test.url) && (
                                  <a 
                                    href={test.run_url || test.url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="run-link"
                                  >
                                    <ExternalLink size={12} />
                                  </a>
                                )}
                              </div>
                            ))}
                            {(untestedByOwner.unassigned.tests || untestedByOwner.unassigned.runs || []).length > 20 && (
                              <div className="more-tests">
                                +{(untestedByOwner.unassigned.tests || untestedByOwner.unassigned.runs).length - 20} more tests...
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  
                  {untestedByOwner.by_owner?.length === 0 && untestedByOwner.unassigned?.total_untested === 0 && (
                    <div className="no-data success">
                      <CheckCircle2 size={24} />
                      <span>All tests have been executed!</span>
                    </div>
                  )}
                </>
              ) : (
                <div className="no-data">Unable to load owner data</div>
              )}
            </div>
          )}
        </>
      )}

      {/* Test Cases Modal */}
      {selectedRun && (
        <div className="testrail-modal-overlay" onClick={closeRunModal}>
          <div className="testrail-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">
                <TestTube size={20} />
                <div>
                  <div className="modal-run-name">{selectedRun.name}</div>
                  <div className="modal-run-stats">
                    {selectedRun.passed} passed • {selectedRun.failed} failed • {selectedRun.total} total
                  </div>
                </div>
              </div>
              <button className="modal-close" onClick={closeRunModal}>×</button>
            </div>
            
            {loadingTestCases ? (
              <div className="modal-loading">
                <RefreshCw size={24} className="spin" />
                <span>Loading test cases...</span>
              </div>
            ) : runTestCases ? (
              <>
                <div className="modal-summary">
                  <div className="summary-stats">
                    <span className="stat passed"><CheckCircle2 size={14} /> {runTestCases.passed}</span>
                    <span className="stat failed"><XCircle size={14} /> {runTestCases.failed}</span>
                    <span className="stat blocked"><AlertCircle size={14} /> {runTestCases.blocked}</span>
                    <span className="stat untested"><Clock size={14} /> {runTestCases.untested}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${runTestCases.pass_rate || 0}%` }} />
                  </div>
                  <span className="pass-rate-label">{runTestCases.pass_rate || 0}% Pass Rate</span>
                  {runTestCases.url && (
                    <a href={runTestCases.url} target="_blank" rel="noopener noreferrer" className="testrail-link">
                      Open in TestRail <ExternalLink size={12} />
                    </a>
                  )}
                </div>
                <div className="modal-test-list">
                  <div className="test-list-header">
                    <span className="col-case">Case ID</span>
                    <span className="col-title">Test Case</span>
                    <span className="col-status">Status</span>
                  </div>
                  <div className="test-list-body">
                    {runTestCases.tests?.map(test => (
                      <div key={test.id} className={`test-row status-${test.status}`}>
                        <span className="col-case">C{test.case_id}</span>
                        <span className="col-title">{test.title}</span>
                        <span className={`col-status badge-${test.status}`}>
                          {test.status === 'passed' && <CheckCircle2 size={12} />}
                          {test.status === 'failed' && <XCircle size={12} />}
                          {test.status === 'blocked' && <AlertCircle size={12} />}
                          {test.status === 'untested' && <Clock size={12} />}
                          {test.status === 'retest' && <RefreshCw size={12} />}
                          {test.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="modal-error">Failed to load test cases</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TestRailSection;
