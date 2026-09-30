import React, { useState, useEffect, useCallback, Suspense, lazy } from 'react';
import { 
  Loader,
  X
} from 'lucide-react';
import './App.css';

// Components
import Sidebar from './components/Sidebar';
import ChatWindow from './components/ChatWindow';

// Overview loaded eagerly (landing page)
import OverviewSection from './components/sections/OverviewSection';

// All other sections lazy-loaded for code splitting
const TestRailSection = lazy(() => import('./components/sections/TestRailSection'));
const JiraSection = lazy(() => import('./components/sections/JiraSection'));
const JenkinsSection = lazy(() => import('./components/sections/JenkinsSection'));
const DevPipelinesSection = lazy(() => import('./components/sections/DevPipelinesSection'));
const WeeklyStatusSection = lazy(() => import('./components/sections/WeeklyStatusSection'));
const ReleaseCalendarSection = lazy(() => import('./components/sections/ReleaseCalendarSection'));
const OnCallCalendarSection = lazy(() => import('./components/sections/OnCallCalendarSection'));
const ResiliencySection = lazy(() => import('./components/sections/ResiliencySection'));
const CustomerEscalationsSection = lazy(() => import('./components/sections/CustomerEscalationsSection'));
const MonitoringSection = lazy(() => import('./components/sections/MonitoringSection'));
const StackMonitoringPage = lazy(() => import('./components/sections/StackMonitoringPage'));
const ReleaseReadinessSection = lazy(() => import('./components/sections/ReleaseReadinessSection'));
const ReleaseRegressionSection = lazy(() => import('./components/sections/ReleaseRegressionSection'));
const TestHealthSection = lazy(() => import('./components/sections/TestHealthSection'));
const DevDigestSection = lazy(() => import('./components/sections/DevDigestSection'));
const TestEfficacySection = lazy(() => import('./components/sections/TestEfficacySection'));
const DocumentationUpdatesSection = lazy(() => import('./components/sections/DocumentationUpdatesSection'));
const FeatureInsightsSection = lazy(() => import('./components/sections/FeatureInsightsSection'));

const API_BASE = '/api';

/**
 * Derive stack_health_summary from the Stack Monitoring page's localStorage
 * cache so the Overview card renders instantly without waiting for the full
 * overview API (which is gated behind regression / other slow fetches).
 * 
 * Uses same formula as Stack Monitoring page:
 * Score = (Healthy×100 + Warning×50 + Critical×0) / Total Stacks
 */
const getStackHealthFromMonitoringCache = () => {
  try {
    const cached = localStorage.getItem('stackMonitoring_cache');
    if (!cached) return null;

    const { data, timestamp } = JSON.parse(cached);
    const age = Date.now() - timestamp;
    if (age > 10 * 60 * 1000) return null; // stale (>10 min)

    const summary = data?.summary;
    if (!summary || typeof summary !== 'object') return null;

    // Count stacks by status (same logic as Stack Monitoring calculateHealthScore)
    // Frontend logic: critical if critical>0, warning if warning>0 OR restarts>5
    let healthyStacks = 0;
    let warningStacks = 0;
    let criticalStacks = 0;
    let initializingStacks = 0;
    const unhealthyStackList = [];

    // Total configured stacks (all stacks in summary, including those with no data)
    const totalConfiguredStacks = Object.keys(summary).length;

    for (const [stackId, counts] of Object.entries(summary)) {
      const stackTotal = counts.total || 0;
      if (stackTotal === 0) {
        initializingStacks++; // Stack has no data yet
        continue;
      }
      
      const stackCritical = counts.critical || 0;
      const stackWarning = counts.warning || 0;
      const stackRestarts = counts.restarts || 0;

      if (stackCritical > 0) {
        criticalStacks++;
        unhealthyStackList.push({ stack: stackId, unhealthy: stackCritical + stackWarning });
      } else if (stackWarning > 0 || stackRestarts > 5) {
        warningStacks++;
        unhealthyStackList.push({ stack: stackId, unhealthy: stackWarning });
      } else {
        healthyStacks++;
      }
    }

    const stacksWithData = healthyStacks + warningStacks + criticalStacks;
    if (stacksWithData === 0) return null;

    // Same formula as Stack Monitoring: (Healthy×100 + Warning×50 + Critical×0) / Total
    const healthScore = Math.round((healthyStacks * 100 + warningStacks * 50) / stacksWithData);

    return {
      available: true,
      placeholder: false,
      total_stacks: stacksWithData,
      total_configured_stacks: totalConfiguredStacks,
      healthy_stacks: healthyStacks,
      warning_stacks: warningStacks,
      critical_stacks: criticalStacks,
      initializing_stacks: initializingStacks,
      health_pct: healthScore,
      unhealthy_stacks: unhealthyStackList,
      from_monitoring_cache: true,
      cache_age_seconds: Math.round(age / 1000),
    };
  } catch {
    return null;
  }
};

/**
 * If overview data is missing stack_health_summary or localStorage cache is fresher,
 * use the Stack Monitoring localStorage cache for better data freshness.
 */
const enrichWithStackHealth = (overviewData) => {
  if (!overviewData) return overviewData;

  const stackHealth = getStackHealthFromMonitoringCache();
  
  // If no localStorage cache, keep whatever the API returned
  if (!stackHealth) return overviewData;
  
  // If API has no data, use localStorage cache
  if (!overviewData.stack_health_summary?.available) {
    return { ...overviewData, stack_health_summary: stackHealth };
  }
  
  // If localStorage cache is fresher (smaller cache_age_seconds), prefer it
  const apiCacheAge = overviewData.stack_health_summary?.cache_age_seconds || Infinity;
  const localCacheAge = stackHealth.cache_age_seconds || Infinity;
  
  if (localCacheAge < apiCacheAge) {
    return { ...overviewData, stack_health_summary: stackHealth };
  }
  
  return overviewData;
};

/**
 * Derive pdv_summary from the PDV Health page's localStorage cache so the
 * Overview card always shows the freshest numbers the user has seen.
 */
const getPdvHealthFromMonitoringCache = () => {
  try {
    const raw = localStorage.getItem('pdv_health_cache');
    if (!raw) return null;

    const data = JSON.parse(raw);
    if (Date.now() - (data.timestamp || 0) > 10 * 60 * 1000) return null;

    const backend = data.backend;
    const endpoint = data.endpoint;
    if (!backend && !endpoint) return null;

    const bFailed = backend?.failed_stacks || 0;
    const eFailed = endpoint?.failed_stacks || 0;
    const totalStacks = (backend?.total_stacks || 0) + (endpoint?.total_stacks || 0);
    const totalBuilds = (backend?.total_builds || 0) + (endpoint?.total_builds || 0);
    const buildsPassed = (backend?.builds_passed || 0) + (endpoint?.builds_passed || 0);
    const successRate = totalBuilds > 0 ? Math.round((buildsPassed / totalBuilds) * 100) : 0;

    const buildSection = (src) => src ? {
      total: src.total_stacks,
      passed: src.total_stacks - src.failed_stacks,
      failed: src.failed_stacks,
      status: src.failed_stacks === 0 ? 'healthy' : 'failing',
      success_rate: src.success_rate,
      total_builds: src.total_builds,
      builds_passed: src.builds_passed,
      stacks: [],
    } : null;

    return {
      available: true,
      placeholder: false,
      total: totalStacks,
      passed: totalStacks - bFailed - eFailed,
      failed: bFailed + eFailed,
      status: (bFailed + eFailed) === 0 ? 'healthy' : 'failing',
      success_rate: successRate,
      total_builds: totalBuilds,
      builds_passed: buildsPassed,
      backend: buildSection(backend),
      endpoint: buildSection(endpoint),
      from_monitoring_cache: true,
    };
  } catch {
    return null;
  }
};

/**
 * If overview data is missing pdv_summary or localStorage cache is fresher,
 * use the PDV Health page's localStorage cache for better data freshness.
 * This ensures the Overview shows the same numbers the user saw on the PDV page.
 */
const enrichWithPdvHealth = (overviewData) => {
  if (!overviewData) return overviewData;

  const cached = getPdvHealthFromMonitoringCache();
  
  // If no localStorage cache, keep whatever the API returned
  if (!cached) return overviewData;
  
  // If API has no data, use localStorage cache
  if (!overviewData.pdv_summary?.available) {
    return { ...overviewData, pdv_summary: cached };
  }
  
  // Always prefer localStorage cache if available - it matches what PDV page shows
  // This ensures consistency between Overview and PDV pages
  return { ...overviewData, pdv_summary: cached };
};

/**
 * Combine all enrichment passes so every setOverviewData call stays consistent.
 */
const enrichOverviewData = (data) => enrichWithPdvHealth(enrichWithStackHealth(data));

const SectionSkeleton = () => (
  <div className="section-skeleton">
    <div className="skeleton-header">
      <div className="skeleton-line skeleton-title" />
      <div className="skeleton-line skeleton-subtitle" />
    </div>
    <div className="skeleton-cards">
      {[1, 2, 3, 4].map(i => (
        <div key={i} className="skeleton-card">
          <div className="skeleton-line skeleton-card-value" />
          <div className="skeleton-line skeleton-card-label" />
        </div>
      ))}
    </div>
    <div className="skeleton-content">
      <div className="skeleton-line skeleton-row" />
      <div className="skeleton-line skeleton-row" />
      <div className="skeleton-line skeleton-row short" />
    </div>
  </div>
);

function App() {
  const [activeSection, setActiveSection] = useState('overview');
  const [selectedRelease, setSelectedRelease] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dataSource, setDataSource] = useState('loading');
  const [availableReleases, setAvailableReleases] = useState([]);
  const [overviewData, setOverviewData] = useState(null);

  // Fetch overview data - used for manual refresh
  const fetchOverviewData = useCallback(async (showRefreshIndicator = false) => {
    if (showRefreshIndicator) {
      setRefreshing(true);
    } else if (!overviewData) {
      setLoading(true);
    }
    
    try {
      const response = await fetch(`${API_BASE}/overview?refresh=${showRefreshIndicator}`);
      if (!response.ok) throw new Error('Overview API not available');
      
      const overviewDataResult = enrichOverviewData(await response.json());
      setOverviewData(overviewDataResult);
      setDataSource('api');
      
      try {
        localStorage.setItem('overview_cache', JSON.stringify({
          data: overviewDataResult,
          timestamp: Date.now()
        }));
      } catch (e) { /* ignore */ }
    } catch (error) {
      console.error('Failed to fetch overview data:', error);
      setDataSource('error');
      setOverviewData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [overviewData]);

  // Fetch releases config AND overview data in parallel on mount
  useEffect(() => {
    const fetchInitialData = async () => {
      // Show cached overview instantly while fresh data loads
      try {
        const cached = localStorage.getItem('overview_cache');
        if (cached) {
          const { data, timestamp } = JSON.parse(cached);
          if (Date.now() - timestamp < 5 * 60 * 1000) {
            setOverviewData(enrichOverviewData(data));
            setDataSource('api');
            setLoading(false);
          }
        }
      } catch (e) { /* ignore */ }

      // Fire releases config + lite overview simultaneously for fast initial load
      const [releasesResponse, liteOverviewResponse] = await Promise.allSettled([
        fetch(`${API_BASE}/releases`),
        fetch(`${API_BASE}/overview?refresh=false&lite=true`),
      ]);

      // Process releases
      if (releasesResponse.status === 'fulfilled' && releasesResponse.value.ok) {
        try {
          const data = await releasesResponse.value.json();
          setAvailableReleases(data.releases || []);
          // Default to the current (is_current) release, or fall back to the first one
          if (data.releases && data.releases.length > 0) {
            const currentRelease = data.releases.find(r => r.is_current);
            setSelectedRelease(currentRelease ? currentRelease.id : data.releases[0].id);
          }
        } catch (e) {
          console.warn('Could not parse releases config');
        }
      }

      // Process lite overview (fast initial load)
      if (liteOverviewResponse.status === 'fulfilled' && liteOverviewResponse.value.ok) {
        try {
          const data = await liteOverviewResponse.value.json();
          const enriched = enrichOverviewData(data);
          setOverviewData(enriched);
          setDataSource('api');
          try {
            localStorage.setItem('overview_cache', JSON.stringify({
              data: enriched,
              timestamp: Date.now()
            }));
          } catch (e) { /* ignore */ }
        } catch (e) {
          console.warn('Could not parse overview data');
          if (!overviewData) setDataSource('error');
        }
      } else {
        if (!overviewData) setDataSource('error');
      }

      setLoading(false);

      // Background: fetch Stack Monitoring data if no localStorage cache
      // This ensures Overview shows stack health even on first visit
      const hasStackCache = !!localStorage.getItem('stackMonitoring_cache');
      const hasPdvCache = !!localStorage.getItem('pdv_health_cache');
      
      if (!hasStackCache || !hasPdvCache) {
        // Fire background fetches for missing data (non-blocking)
        const backgroundFetches = [];
        
        if (!hasStackCache) {
          backgroundFetches.push(
            fetch(`${API_BASE}/monitoring/stack?lite=true&stale_ok=true`)
              .then(res => res.ok ? res.json() : null)
              .then(data => {
                if (data && data.summary) {
                  localStorage.setItem('stackMonitoring_cache', JSON.stringify({
                    data,
                    timestamp: Date.now()
                  }));
                  // Re-enrich overview with new data
                  setOverviewData(prev => prev ? enrichOverviewData(prev) : prev);
                }
              })
              .catch(() => {})
          );
        }
        
        if (!hasPdvCache) {
          // Fetch PDV data in background - use same params as PDV Health page for consistency
          backgroundFetches.push(
            Promise.all([
              fetch(`${API_BASE}/jenkins/backend-pdv-by-stack?num_builds=15`).then(r => r.ok ? r.json() : null),
              fetch(`${API_BASE}/jenkins/golden-regression?num_builds=10`).then(r => r.ok ? r.json() : null),
            ]).then(([backend, endpoint]) => {
              if (backend || endpoint) {
                const pdvCache = { timestamp: Date.now() };
                if (backend?.summary) {
                  pdvCache.backend = {
                    total_stacks: backend.summary.stacksList?.length || 0,
                    failed_stacks: backend.summary.failedStacks || 0,
                    total_builds: backend.summary.totalRuns || 0,
                    builds_passed: backend.summary.totalPassed || 0,
                    success_rate: backend.summary.overallPassRate || 0,
                  };
                }
                if (endpoint?.stackGroups) {
                  const stackGroups = endpoint.stackGroups;
                  const totalStacks = Object.keys(stackGroups).length;
                  const failedStacks = Object.entries(stackGroups).filter(([, builds]) =>
                    builds.length > 0 && builds[0]?.status !== 'success'
                  ).length;
                  const totalBuilds = Object.values(stackGroups).reduce((s, b) => s + b.length, 0);
                  const buildsPassed = Object.values(stackGroups).reduce((s, b) =>
                    s + b.filter(x => x.status === 'success').length, 0);
                  pdvCache.endpoint = {
                    total_stacks: totalStacks,
                    failed_stacks: failedStacks,
                    total_builds: totalBuilds,
                    builds_passed: buildsPassed,
                    success_rate: totalBuilds > 0 ? Math.round((buildsPassed / totalBuilds) * 100) : 0,
                  };
                }
                localStorage.setItem('pdv_health_cache', JSON.stringify(pdvCache));
                // Re-enrich overview with new data
                setOverviewData(prev => prev ? enrichOverviewData(prev) : prev);
              }
            }).catch(() => {})
          );
        }
        
        // Run background fetches (don't await)
        Promise.all(backgroundFetches).catch(() => {});
      }

      // Background: fetch full overview data (includes regression + stack health)
      try {
        const fullResponse = await fetch(`${API_BASE}/overview?refresh=false`);
        if (fullResponse.ok) {
          const fullData = enrichOverviewData(await fullResponse.json());
          setOverviewData(fullData);
          try {
            localStorage.setItem('overview_cache', JSON.stringify({
              data: fullData,
              timestamp: Date.now()
            }));
          } catch (e) { /* ignore */ }
        }
      } catch (e) { /* full data fetch failed silently - lite data still shown */ }
    };

    fetchInitialData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Get releases from config API
  const releases = availableReleases;
  
  // Get release status from overview data
  const currentReleaseOverview = overviewData?.releases?.find(r => r.id === selectedRelease) || {};
  
  const releaseInfo = {
    currentRelease: selectedRelease || 'Loading...',
    targetDate: currentReleaseOverview.days_remaining_date || 'TBD',
    daysRemaining: currentReleaseOverview.days_remaining ?? 0,
    daysRemainingLabel: currentReleaseOverview.days_remaining_label || '',
    phase: currentReleaseOverview.phase || 'Not Started',
    status: (currentReleaseOverview.rrs_status || 'on-track').toLowerCase().replace(' ', '-'),
    statusReason: currentReleaseOverview.rrs_status_reason || '',
    rrsScore: currentReleaseOverview.rrs_score ?? 0
  };

  const handleNavigate = (section, releaseId = null) => {
    if (releaseId && releaseId !== selectedRelease) {
      setSelectedRelease(releaseId);
    }
    setActiveSection(section);
    if (window.innerWidth < 1000) {
      setSidebarCollapsed(true);
    }
  };

  // Refresh overview data - clears all caches and fetches fresh data
  const handleRefresh = () => {
    // Clear all localStorage caches
    try {
      localStorage.removeItem('overview_cache');
      localStorage.removeItem('stackMonitoring_cache');
      localStorage.removeItem('pdv_health_cache');
    } catch (e) { /* ignore */ }
    
    fetchOverviewData(true);
  };

  // Render active section
  // Note: Each section has its own API calls - no need for centralized dashboard data
  const renderSection = () => {
    switch (activeSection) {
      case 'overview':
        return (
          <OverviewSection 
            onNavigate={handleNavigate}
            selectedRelease={selectedRelease}
            overviewData={overviewData}
            onRefresh={handleRefresh}
            isRefreshing={refreshing}
          />
        );
      case 'weekly-status':
        return <WeeklyStatusSection selectedRelease={selectedRelease} />;
      case 'testrail':
        return <TestRailSection selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'flaky-tests':
        return <TestHealthSection selectedRelease={selectedRelease} />;
      case 'test-efficacy':
        return <TestEfficacySection selectedRelease={selectedRelease} />;
      // Pipeline section routes
      case 'dev-pipelines':
        return <DevPipelinesSection selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'pdv-pipelines':
        return <MonitoringSection selectedRelease={selectedRelease} defaultView="pdv" />;
      case 'regression-pipelines':
        return <JenkinsSection selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      // Legacy route support (for backward compatibility)
      case 'jenkins':
        return <JenkinsSection selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'pdv-monitoring':
        return <MonitoringSection selectedRelease={selectedRelease} defaultView="pdv" />;
      case 'major-releases':
        return <JiraSection viewType="release" selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'release-calendar':
        return <ReleaseCalendarSection selectedRelease={selectedRelease} onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'on-call-calendar':
        return <OnCallCalendarSection onRefresh={handleRefresh} isRefreshing={refreshing} />;
      case 'bugs':
      case 'regressions':
        return <JiraSection viewType="regressions" />;
      case 'stack-monitoring':
        return <StackMonitoringPage selectedRelease={selectedRelease} />;
      case 'regression-tracking':
        return <ReleaseRegressionSection selectedRelease={selectedRelease} />;
      case 'readiness-tracking':
        return <ReleaseReadinessSection selectedRelease={selectedRelease} />;
      case 'dev-digest':
        return <DevDigestSection selectedRelease={selectedRelease} />;
      case 'escalations-dashboard':
        return <CustomerEscalationsSection selectedRelease={selectedRelease} />;
      case 'docs-updates':
        return <DocumentationUpdatesSection />;
      case 'resiliency':
        return <ResiliencySection />;
      case 'feature-insights':
        return <FeatureInsightsSection />;
      default:
        return (
          <OverviewSection 
            onNavigate={handleNavigate}
            selectedRelease={selectedRelease}
            overviewData={overviewData}
            onRefresh={handleRefresh}
            isRefreshing={refreshing}
          />
        );
    }
  };

  return (
    <div className={`app-container ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${chatOpen ? 'chat-open' : ''}`}>
      {/* Left Sidebar Navigation */}
      <Sidebar 
        activeSection={activeSection} 
        setActiveSection={handleNavigate}
        releaseInfo={releaseInfo}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        isLoading={loading}
      />

      {/* Main Content Area */}
      <div className="main-area">
        {/* Top Header Bar */}
        <header className="top-header">
          <div className="header-left">
          </div>
          <div className="header-right">
            <div className="release-selector-mini">
              <label>Release:</label>
              <select 
                value={selectedRelease || ''} 
                onChange={(e) => setSelectedRelease(e.target.value)}
              >
                {releases.map((release) => (
                  <option key={release.id} value={release.id}>
                    {release.display_name || release.name || release.id}
                  </option>
                ))}
              </select>
            </div>
            <div className={`data-source-badge ${dataSource}`}>
              {dataSource === 'api' ? '🟢 Live' : dataSource === 'error' ? '🔴 Error' : '⏳'}
            </div>
          </div>
        </header>

        {/* Content Area */}
        <main className="content-area">
          {loading ? (
            <div className="loading-container">
              <Loader size={48} className="spin" />
              <p>Loading dashboard data...</p>
            </div>
          ) : (
            <Suspense fallback={<SectionSkeleton />}>
              {renderSection()}
            </Suspense>
          )}
        </main>
      </div>

      {/* AI Assistant Panel */}
      <div className={`chat-panel ${chatOpen ? 'open' : ''}`}>
        {chatOpen && <ChatWindow onClose={() => setChatOpen(false)} selectedRelease={selectedRelease} />}
      </div>
      
      {/* Chat Toggle Button */}
      <button 
        className={`chat-toggle-btn ${chatOpen ? 'active' : ''}`} 
        onClick={() => setChatOpen(!chatOpen)}
      >
        {chatOpen ? <X size={18} /> : '💬'} 
        <span>{chatOpen ? 'Close' : 'AI Assistant'}</span>
      </button>
    </div>
  );
}

export default App;
