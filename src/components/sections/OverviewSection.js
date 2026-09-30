import React, { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle,
  Clock,
  CheckCircle2,
  ArrowRight,
  RefreshCw,
  Server,
  AlertOctagon,
  TrendingUp,
  TrendingDown,
  Activity,
  FlaskConical,
  XCircle,
  ChevronRight,
  Target,
  Rocket,
  ArrowUpRight,
  ArrowDownRight,
  Layers,
  Lightbulb,
  Monitor,
  Minus,
  Phone
} from 'lucide-react';
import RiskPredictorCard from './RiskPredictorCard';

const API_BASE = '/api';

const OverviewSection = ({ 
  onNavigate = () => {},
  selectedRelease,
  overviewData: parentOverviewData = null,
  onRefresh,
  isRefreshing = false
}) => {
  const [localOverviewData, setLocalOverviewData] = useState(null);
  const [loading, setLoading] = useState(!parentOverviewData);
  const [refreshing, setRefreshing] = useState(false);
  const [onCallData, setOnCallData] = useState(null);

  // Use parent data if available (avoids duplicate API call)
  const overviewData = parentOverviewData || localOverviewData;

  // Fetch overview data (used for initial load and manual refresh)
  const fetchOverview = useCallback(async (isManualRefresh = false) => {
    if (isManualRefresh) {
      // If parent provides onRefresh, delegate to it
      if (onRefresh) {
        onRefresh();
        return;
      }
      setRefreshing(true);
    }
    try {
      const refreshParam = isManualRefresh ? 'true' : 'false';
      const response = await fetch(`${API_BASE}/overview?refresh=${refreshParam}`);
      if (response.ok) {
        const data = await response.json();
        setLocalOverviewData(data);
      }
    } catch (error) {
      console.error('Failed to fetch overview:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [onRefresh]);

  // Only fetch locally if parent didn't provide data
  useEffect(() => {
    if (parentOverviewData) {
      setLoading(false);
      return;
    }
    fetchOverview();
  }, [parentOverviewData, fetchOverview]);

  // Fetch on-call data (using /schedules endpoint for full region data)
  useEffect(() => {
    const fetchOnCall = async () => {
      try {
        const response = await fetch(`${API_BASE}/on-call-calendar/schedules`);
        if (response.ok) {
          const data = await response.json();
          console.log('[OnCall Debug] Fetched data:', data);
          console.log('[OnCall Debug] Has schedules.primary.current_rotation.regions:', 
            !!data?.schedules?.primary?.current_rotation?.regions);
          if (data?.schedules?.primary?.current_rotation?.regions) {
            console.log('[OnCall Debug] Regions:', 
              Object.keys(data.schedules.primary.current_rotation.regions));
          }
          setOnCallData(data);
        }
      } catch (error) {
        console.error('Failed to fetch on-call data:', error);
      }
    };
    fetchOnCall();
  }, []);

  const getRrsClass = (score) => {
    if (score >= 80) return 'good';
    if (score >= 60) return 'warning';
    return 'critical';
  };

  const getStatusClass = (status) => {
    if (status === 'healthy' || status === 'success') return 'good';
    if (status === 'warning') return 'warning';
    return 'critical';
  };

  if (loading) {
    return (
      <div className="overview-loading">
        <div className="loading-spinner">
          <RefreshCw size={32} className="spin" />
        </div>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  const { 
    releases = [], 
    pdv_summary = {}, 
    regression_summary = {},
    jenkins_summary = {},
    testrail_summary = {},
    stack_health_summary = {},
    trend_summary = {}
  } = overviewData || {};

  // Get the release to display:
  // 1. If selectedRelease prop is provided, try to find it in the releases array
  // 2. Otherwise, fall back to the "current" release (marked is_current)
  // 3. Finally, fall back to the first release in the list
  const currentRelease = (selectedRelease && releases.find(r => r.id === selectedRelease)) 
    || releases.find(r => r.is_current) 
    || releases[0];
  
  // Get TestRail data for the selected release (from per-release data, not global summary)
  const releaseTestrail = currentRelease?.testrail || {};
  
  // Calculate blockers for the selected release (not sum of all releases)
  const totalBlockers = currentRelease?.critical_blocker_total || currentRelease?.blocker_count || 0;
  
  // PDV Health: Use the same metric as PDV Monitoring page (success rate from backend)
  // This is based on build runs, not stack counts
  const pdvPassRate = pdv_summary.available 
    ? (pdv_summary.success_rate || pdv_summary.health_pct || 0)
    : 0;
  
  // Build Health: Use the same metric as Dev Pipelines page (health percent from backend)
  // This is based on build runs, not pipeline counts
  const jenkinsPassRate = jenkins_summary.available 
    ? (jenkins_summary.health_pct || 0)
    : 0;
  
  const testRailPassRate = Math.round(releaseTestrail.pass_rate || 0);
  
  // Get regression data for current release (live data)
  const regressionConfigured = regression_summary.releases ? 
    Object.values(regression_summary.releases).some(r => r.configured) : false;
  
  // Get regression progress for current release
  const currentReleaseRegression = currentRelease?.id && regression_summary.releases 
    ? regression_summary.releases[currentRelease.id] 
    : null;
  const regressionProgress = currentReleaseRegression?.configured && currentReleaseRegression?.total > 0
    ? currentReleaseRegression.completion_percent 
    : null;

  // Build action items from all sections
  const actionItems = [];
  
  // Release action items - use critical_blocker_total (P0+P1 combined)
  const blockerTotal = currentRelease?.critical_blocker_total || currentRelease?.blocker_count || 0;
  if (blockerTotal > 0) {
    actionItems.push({
      type: 'critical',
      section: 'Release',
      icon: AlertTriangle,
      message: `${blockerTotal} blocker${blockerTotal > 1 ? 's' : ''} need attention`,
      link: 'readiness-tracking'
    });
  }
  if (currentRelease?.action_items > 10) {
    actionItems.push({
      type: 'warning',
      section: 'Release',
      icon: Target,
      message: `${currentRelease.action_items} open items remaining`,
      link: 'readiness-tracking'
    });
  }
  
  // PDV action items - include failing stack names for tooltip
  // Use top-level pdv_summary.failed which is the total (backend + endpoint) calculated by the API
  const pdvFailing = pdv_summary.failed || 0;
  const pdvBackendFailing = pdv_summary.backend?.failed || 0;
  const pdvEndpointFailing = pdv_summary.endpoint?.failed || 0;
  
  if (pdvFailing > 0) {
    // Get failing stack names from both backend and endpoint
    const failingStacks = [
      ...(pdv_summary.backend?.stacks || []).filter(s => s.status === 'failed').map(s => s.name),
      ...(pdv_summary.endpoint?.stacks || []).filter(s => s.status === 'failed').map(s => s.name)
    ];
    // Show breakdown if both have failures
    const breakdownMessage = (pdvBackendFailing > 0 && pdvEndpointFailing > 0)
      ? `${pdvFailing} stacks failing (${pdvBackendFailing} Backend, ${pdvEndpointFailing} Endpoint)`
      : `${pdvFailing} stack${pdvFailing > 1 ? 's' : ''} failing PDV tests`;
    
    actionItems.push({
      type: 'critical',
      section: 'PDV',
      icon: Server,
      message: breakdownMessage,
      link: 'pdv-pipelines',
      details: failingStacks.length > 0 ? failingStacks.join(', ') : null
    });
  }
  
  // Build health action items - include failing pipeline names for tooltip
  const jenkinsFailing = jenkins_summary.failed || 0;
  if (jenkinsFailing > 0) {
    const failingPipelines = jenkins_summary.failed_pipelines || [];
    actionItems.push({
      type: 'warning',
      section: 'Build',
      icon: Activity,
      message: `${jenkinsFailing} pipeline${jenkinsFailing > 1 ? 's' : ''} failing`,
      link: 'dev-pipelines',
      details: failingPipelines.length > 0 ? failingPipelines.join(', ') : null
    });
  }
  
  // Regression action items
  if (currentReleaseRegression?.blocked > 0) {
    actionItems.push({
      type: 'warning',
      section: 'Regression',
      icon: TrendingUp,
      message: `${currentReleaseRegression.blocked} regression items blocked`,
      link: 'regression-tracking'
    });
  }
  
  // TestRail action items - use per-release TestRail data
  const testrailAvailable = releaseTestrail.available === true;
  
  if (testrailAvailable && releaseTestrail.failed > 0) {
    actionItems.push({
      type: 'warning',
      section: 'TestRail',
      icon: FlaskConical,
      message: `${releaseTestrail.failed} test${releaseTestrail.failed > 1 ? 's' : ''} failing`,
      link: 'testrail'
    });
  }
  if (testrailAvailable && releaseTestrail.blocked > 0) {
    actionItems.push({
      type: 'info',
      section: 'TestRail',
      icon: AlertOctagon,
      message: `${releaseTestrail.blocked} test${releaseTestrail.blocked > 1 ? 's' : ''} blocked`,
      link: 'testrail'
    });
  }

  return (
    <div className="overview-modern">
      {/* Header */}
      <header className="overview-header-modern">
        <div className="header-left-content">
          <h1>Agentic Insights Portal</h1>
          <span className="header-subtitle">
            {new Date().toLocaleDateString('en-US', { 
              weekday: 'long', 
              month: 'long', 
              day: 'numeric', 
              year: 'numeric' 
            })}
          </span>
        </div>

        {/* On-Call Inline Strip */}
        {onCallData?.schedules?.primary?.current_rotation?.regions && (
          <div 
            className="oncall-inline-strip"
            onClick={() => onNavigate('on-call-calendar')}
            title="Click to view full on-call calendar"
          >
            <Phone size={14} />
            <span className="oncall-strip-label">On-Call:</span>
            {(() => {
              const flags = { IST: '🇮🇳', TW: '🇹🇼', US: '🇺🇸' };
              const regionOrder = ['IST', 'TW', 'US'];
              const regions = onCallData.schedules.primary.current_rotation.regions;
              
              return regionOrder.map((regionId, idx) => {
                const person = regions[regionId];
                if (!person) return null;
                const firstName = (person.name || 'Unknown').split(' ')[0];
                return (
                  <span key={regionId} className="oncall-strip-person">
                    {idx > 0 && <span className="oncall-strip-dot">•</span>}
                    <span className="oncall-strip-flag">{flags[regionId] || '🌍'}</span>
                    <span className="oncall-strip-name">{firstName}</span>
                  </span>
                );
              }).filter(Boolean);
            })()}
          </div>
        )}

        <div className="header-actions">
          <button 
            className="time-filter"
            onClick={() => onNavigate('release-calendar')}
          >
            <Rocket size={16} />
            <span>Release Calendar</span>
          </button>
          <button 
            className={`refresh-btn-modern ${isRefreshing ? 'refreshing' : ''}`}
            onClick={() => onRefresh ? onRefresh() : window.location.reload()}
            disabled={isRefreshing}
          >
            <RefreshCw size={16} className={isRefreshing ? 'spin' : ''} />
          </button>
        </div>
      </header>

      {/* Action Items Banner - Horizontal compact layout */}
      {actionItems.length > 0 && (
        <div className="action-items-banner-horizontal">
          <div className="action-items-header-inline">
            <AlertOctagon size={16} />
            <span>Action Required</span>
          </div>
          <div className="action-items-row">
            {actionItems.map((item, index) => {
              const IconComponent = item.icon;
              return (
                <div 
                  key={index}
                  className={`action-chip ${item.type}`}
                  onClick={() => onNavigate(item.link)}
                  title={item.details || item.message}
                >
                  <IconComponent size={14} />
                  <span className="action-chip-text">{item.message}</span>
                  <ChevronRight size={12} />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main Stats Grid */}
      <div className="stats-grid-modern">
        {/* Release Hero Card */}
        {currentRelease && (
          <div 
            className="stat-card-hero"
            onClick={() => onNavigate('readiness-tracking', currentRelease.id)}
          >
            <div className="hero-card-header">
              <div className="hero-icon-wrapper">
                <Rocket size={24} />
              </div>
              <div className="hero-badge-wrapper">
                <span className={`badge-current ${currentRelease.status === 'completed' ? 'badge-completed' : ''}`}>
                  {currentRelease.status === 'completed' ? 'Completed' : 'Active Release'}
                </span>
              </div>
            </div>
            
            <div className="hero-main-stat">
              <span className="hero-value">{currentRelease.id}</span>
              <span className="hero-phase">
                <Clock size={14} />
                {currentRelease.phase}
              </span>
            </div>

            <div className="hero-rrs-section">
              <div className={`rrs-gauge ${getRrsClass(currentRelease.rrs_score)}`}>
                <svg viewBox="0 0 100 60">
                  <path
                    className="gauge-bg"
                    d="M 10 50 A 40 40 0 0 1 90 50"
                    fill="none"
                    strokeWidth="8"
                  />
                  <path
                    className="gauge-fill"
                    d="M 10 50 A 40 40 0 0 1 90 50"
                    fill="none"
                    strokeWidth="8"
                    strokeDasharray={`${(currentRelease.rrs_score / 100) * 126} 126`}
                  />
                  <text x="50" y="42" textAnchor="middle" className="gauge-text-number">
                    {currentRelease.rrs_score}%
                  </text>
                  <text x="50" y="54" textAnchor="middle" className="gauge-text-label">
                    RRS
                  </text>
                </svg>
              </div>
              <span className={`rrs-status-badge ${getRrsClass(currentRelease.rrs_score)}`}>
                {currentRelease.rrs_status}
              </span>
            </div>

            <div className="hero-mini-stats">
              <div className={`mini-stat ${(currentRelease.critical_blocker_total || currentRelease.blocker_count || 0) > 0 ? 'danger' : ''}`}>
                <span className="mini-value">{currentRelease.critical_blocker_total || currentRelease.blocker_count || 0}</span>
                <span className="mini-label">Blockers</span>
              </div>
              <div className="mini-stat">
                <span className="mini-value">{currentRelease.open_stories || 0}</span>
                <span className="mini-label">Stories</span>
              </div>
              <div className="mini-stat">
                <span className="mini-value">{currentRelease.open_bugs || 0}</span>
                <span className="mini-label">Bugs</span>
              </div>
              <div className="mini-stat">
                <span className="mini-value">{currentRelease.code_review || 0}</span>
                <span className="mini-label">In Review</span>
              </div>
              <div 
                className={`mini-stat ${((currentRelease.escalation?.count || 0) > 0) ? 'escalation' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  if (currentRelease.escalation?.jira_url) {
                    window.open(currentRelease.escalation.jira_url, '_blank');
                  }
                }}
                title="Open Customer Escalations — Click to view in JIRA"
              >
                <span className="mini-value">
                  {currentRelease.escalation?.available ? (currentRelease.escalation.count || 0) : <RefreshCw size={16} className="spin" />}
                </span>
                <span className="mini-label">Escalations</span>
              </div>
            </div>

            {currentRelease.days_remaining > 0 && (
              <div className="hero-countdown">
                <span className="countdown-value">{currentRelease.days_remaining}</span>
                <span className="countdown-text">days to {currentRelease.days_remaining_label?.replace('To ', '')}</span>
              </div>
            )}

            <div className="card-link">
              <span>View Release Details</span>
              <ArrowUpRight size={16} />
            </div>
          </div>
        )}

        {/* Stat Cards Column */}
        <div className="stat-cards-column">
          {/* Blockers Card with Trend Indicator */}
          <div 
            className={`stat-card-compact ${totalBlockers > 0 ? 'critical' : 'good'}`}
            onClick={() => onNavigate('readiness-tracking')}
          >
            <div className="compact-icon">
              <AlertOctagon size={20} />
            </div>
            <div className="compact-content">
              <div className="compact-value-row">
                <span className="compact-value">{totalBlockers}</span>
                {/* Trend Indicator */}
                {trend_summary.available && trend_summary.total_change !== 0 && (
                  <span className={`trend-indicator ${trend_summary.total_change < 0 ? 'improving' : 'declining'}`}
                    title={`${trend_summary.total_change < 0 ? 'Improved' : 'Increased'} by ${Math.abs(trend_summary.total_change)} vs last week`}
                  >
                    {trend_summary.total_change < 0 ? (
                      <><ArrowDownRight size={14} />{Math.abs(trend_summary.total_change)}</>
                    ) : (
                      <><ArrowUpRight size={14} />+{trend_summary.total_change}</>
                    )}
                  </span>
                )}
              </div>
              <span className="compact-label">Blockers</span>
            </div>
            <div className="compact-trend">
              {totalBlockers > 0 ? (
                <span className="trend-badge danger">
                  <AlertTriangle size={12} />
                  Needs Attention
                </span>
              ) : (
                <span className="trend-badge success">
                  <CheckCircle2 size={12} />
                  Clear
                </span>
              )}
            </div>
            <ChevronRight size={18} className="compact-arrow" />
          </div>

          {/* PDV Card with Recent Failures */}
          <div 
            className={`stat-card-compact ${pdv_summary.available ? (pdv_summary.failed > 0 ? 'warning' : 'good') : 'neutral'}`}
            onClick={() => onNavigate('pdv-pipelines')}
          >
            <div className="compact-icon">
              <Server size={20} />
            </div>
            <div className="compact-content">
              <span className="compact-value">{pdv_summary.available ? `${pdvPassRate}%` : <RefreshCw size={16} className="spin" />}</span>
              <span className="compact-label">PDV Health</span>
              {/* Recent Failures Sub-text */}
              {pdv_summary.available && pdv_summary.recent_failure_count > 0 && (
                <span className="compact-subtext warning"
                  title={pdv_summary.recent_failures?.map(f => `${f.stack}: ${f.timestamp}`).join('\n') || ''}
                >
                  {pdv_summary.recent_failure_count} failure{pdv_summary.recent_failure_count !== 1 ? 's' : ''} (24h)
                </span>
              )}
            </div>
            <div className="compact-trend">
              {pdv_summary.available && (
                <span className={`trend-badge ${pdv_summary.failed > 0 ? 'warning' : 'success'}`}>
                  {pdv_summary.builds_passed || pdv_summary.passed || 0}/{pdv_summary.total_builds || pdv_summary.total || 0} Passing
                </span>
              )}
            </div>
            <ChevronRight size={18} className="compact-arrow" />
          </div>

          {/* Jenkins Card */}
          <div 
            className={`stat-card-compact ${jenkins_summary.available ? (jenkins_summary.failed > 0 ? 'warning' : 'good') : 'neutral'}`}
            onClick={() => onNavigate('dev-pipelines')}
          >
            <div className="compact-icon">
              <Activity size={20} />
            </div>
            <div className="compact-content">
              <span className="compact-value">{jenkins_summary.available ? `${jenkinsPassRate}%` : <RefreshCw size={16} className="spin" />}</span>
              <span className="compact-label">Build Health</span>
            </div>
            <div className="compact-trend">
              {jenkins_summary.available && (
                <span className={`trend-badge ${jenkins_summary.failed > 0 ? 'warning' : 'success'}`}>
                  {jenkins_summary.total_passed || jenkins_summary.passed || 0}/{jenkins_summary.total_runs || jenkins_summary.total || 0} Passing
                </span>
              )}
            </div>
            <ChevronRight size={18} className="compact-arrow" />
          </div>

          {/* TestRail Card - only show data if it matches the selected release */}
          <div 
            className={`stat-card-compact ${testrailAvailable ? getStatusClass(releaseTestrail.status) : 'neutral'}`}
            onClick={() => onNavigate('testrail')}
          >
            <div className="compact-icon">
              <FlaskConical size={20} />
            </div>
            <div className="compact-content">
              <span className="compact-value">
                {testrailAvailable ? `${testRailPassRate}%` : 'N/A'}
              </span>
              <span className="compact-label">Test Pass Rate</span>
              {!testrailAvailable && currentRelease && (
                <span className="compact-subtext">No milestone for {currentRelease.id}</span>
              )}
            </div>
            <div className="compact-trend">
              {testrailAvailable && (
                <span className={`trend-badge ${testRailPassRate >= 80 ? 'success' : testRailPassRate >= 60 ? 'warning' : 'danger'}`}>
                  {releaseTestrail.passed}/{releaseTestrail.total} Passed
                </span>
              )}
            </div>
            <ChevronRight size={18} className="compact-arrow" />
          </div>

          {/* Stack Health Card - Shows critical/warning stack counts for consistency */}
          {(() => {
            const isLoading = !stack_health_summary.available || stack_health_summary.placeholder || 
              (stack_health_summary.initializing_stacks > 0 && stack_health_summary.total_stacks === 0);
            const criticalCount = stack_health_summary.critical_stacks || 0;
            const warningCount = stack_health_summary.warning_stacks || 0;
            
            return (
              <div 
                className={`stat-card-compact ${isLoading ? 'neutral' : criticalCount > 0 ? 'critical' : warningCount > 0 ? 'warning' : 'good'}`}
                onClick={() => onNavigate('stack-monitoring')}
              >
                <div className="compact-icon">
                  <Monitor size={20} />
                </div>
                <div className="compact-content">
                  <span className="compact-value">
                    {isLoading 
                      ? <RefreshCw size={16} className="spin" />
                      : criticalCount > 0
                        ? criticalCount
                        : warningCount > 0
                          ? warningCount
                          : <CheckCircle2 size={20} />
                    }
                  </span>
                  <span className="compact-label">
                    {isLoading 
                      ? 'Loading...'
                      : criticalCount > 0
                        ? `Critical Stack${criticalCount > 1 ? 's' : ''}`
                        : warningCount > 0
                          ? `Warning Stack${warningCount > 1 ? 's' : ''}`
                          : 'All Healthy'
                    }
                  </span>
                </div>
                <div className="compact-trend">
                  {!isLoading && stack_health_summary.available && (
                    <span className={`trend-badge ${criticalCount > 0 ? 'danger' : warningCount > 0 ? 'warning' : 'success'}`}>
                      {stack_health_summary.healthy_stacks}/{stack_health_summary.total_configured_stacks || stack_health_summary.total_stacks} Healthy
                    </span>
                  )}
                </div>
                <ChevronRight size={18} className="compact-arrow" />
              </div>
            );
          })()}
        </div>
      </div>

      {/* AI Risk Predictor Section - Disabled for now */}
      {/* {currentRelease && (
        <div className="risk-predictor-section">
          <RiskPredictorCard 
            releaseId={currentRelease.id} 
            onNavigate={onNavigate}
          />
        </div>
      )} */}

      {/* Bottom Section - Detail Panels */}
      <div className="detail-panels-modern">
        {/* Regression Status Panel - Shows cached progress */}
        <div 
          className="detail-panel-modern"
          onClick={() => onNavigate('regression-tracking')}
        >
          <div className="panel-header-modern">
            <div className="panel-title-group">
              <TrendingUp size={20} />
              <h3>Regression Progress</h3>
            </div>
            <ChevronRight size={18} className="panel-arrow" />
          </div>
          <div className="panel-content-modern">
            {regressionProgress !== null ? (
              <div className="regression-progress-display">
                <div className="regression-gauge-large">
                  <div 
                    className="gauge-ring"
                    style={{
                      '--progress': regressionProgress,
                      '--gauge-color': regressionProgress >= 80 ? '#10b981' : regressionProgress >= 50 ? '#f59e0b' : '#ef4444'
                    }}
                  >
                    <div className="gauge-inner">
                      <span className="gauge-percent">{regressionProgress}%</span>
                      <span className="gauge-label">Complete</span>
                    </div>
                  </div>
                </div>
                <div className="regression-details">
                  <div className="regression-stat">
                    <CheckCircle2 size={16} className="stat-icon done" />
                    <span className="stat-value">{currentReleaseRegression?.done || 0}</span>
                    <span className="stat-label">Done</span>
                  </div>
                  <div className="regression-stat">
                    <Activity size={16} className="stat-icon progress" />
                    <span className="stat-value">{currentReleaseRegression?.in_progress || 0}</span>
                    <span className="stat-label">In Progress</span>
                  </div>
                  <div className="regression-stat">
                    <AlertTriangle size={16} className="stat-icon blocked" />
                    <span className="stat-value">{currentReleaseRegression?.blocked || 0}</span>
                    <span className="stat-label">Blocked</span>
                  </div>
                  <div className="regression-stat total">
                    <Layers size={16} className="stat-icon" />
                    <span className="stat-value">{currentReleaseRegression?.total || 0}</span>
                    <span className="stat-label">Total</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="panel-nav-card">
                <div className="nav-card-icon">
                  <TrendingUp size={40} />
                </div>
                <div className="nav-card-content">
                  <h4>View Regression Tracking</h4>
                  <p>
                    {regressionConfigured 
                      ? 'Click to load regression test progress'
                      : 'No regression epics configured'}
                  </p>
                </div>
                <div className="nav-card-action">
                  <ArrowRight size={20} />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Test Automation Panel - only show data if it matches the selected release */}
        <div 
          className="detail-panel-modern"
          onClick={() => onNavigate('testrail')}
        >
          <div className="panel-header-modern">
            <div className="panel-title-group">
              <FlaskConical size={20} />
              <h3>Test Automation</h3>
            </div>
            <ChevronRight size={18} className="panel-arrow" />
          </div>
          <div className="panel-content-modern">
            {testrailAvailable ? (
              <div className="test-stats-grid">
                <div className="test-stat passed">
                  <CheckCircle2 size={18} />
                  <span className="test-stat-value">{releaseTestrail.passed || 0}</span>
                  <span className="test-stat-label">Passed</span>
                </div>
                <div className="test-stat failed">
                  <XCircle size={18} />
                  <span className="test-stat-value">{releaseTestrail.failed || 0}</span>
                  <span className="test-stat-label">Failed</span>
                </div>
                <div className="test-stat blocked">
                  <AlertTriangle size={18} />
                  <span className="test-stat-value">{releaseTestrail.blocked || 0}</span>
                  <span className="test-stat-label">Blocked</span>
                </div>
                <div className="test-stat untested">
                  <Layers size={18} />
                  <span className="test-stat-value">{releaseTestrail.untested || 0}</span>
                  <span className="test-stat-label">Untested</span>
                </div>
              </div>
            ) : (
              <div className="panel-empty-modern">
                <FlaskConical size={32} />
                <span>No TestRail milestone for {currentRelease?.id || 'this release'}</span>
              </div>
            )}
          </div>
        </div>

        {/* Quick Links Panel */}
        <div className="detail-panel-modern quick-links-panel">
          <div className="panel-header-modern">
            <div className="panel-title-group">
              <Target size={20} />
              <h3>Quick Actions</h3>
            </div>
          </div>
          <div className="panel-content-modern">
            <div className="quick-links-list">
              <button className="quick-link-item" onClick={() => onNavigate('readiness-tracking')}>
                <div className="quick-link-icon">
                  <Rocket size={18} />
                </div>
                <span className="quick-link-text">View Release Readiness</span>
                <ArrowRight size={16} />
              </button>
              <button className="quick-link-item" onClick={() => onNavigate('regression-tracking')}>
                <div className="quick-link-icon">
                  <TrendingUp size={18} />
                </div>
                <span className="quick-link-text">Track Regression Status</span>
                <ArrowRight size={16} />
              </button>
              <button className="quick-link-item" onClick={() => onNavigate('stack-monitoring')}>
                <div className="quick-link-icon">
                  <Server size={18} />
                </div>
                <span className="quick-link-text">Check Stack Health</span>
                <ArrowRight size={16} />
              </button>
              <button className="quick-link-item" onClick={() => onNavigate('dev-digest')}>
                <div className="quick-link-icon">
                  <Lightbulb size={18} />
                </div>
                <span className="quick-link-text">View Dev Insights</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
};

export default OverviewSection;
