/**
 * DevDigestSection - Developer Daily Digest
 * 
 * Consolidated view of daily action items for developers:
 * 1. Customer Escalations - P1/P2 issues needing attention
 * 2. Security Issues - Security vulnerabilities and fixes
 * 3. Release Items - Open stories/bugs for current release
 * 4. NPLAN Tracking - Feature tracking status
 * 5. Open PR Reviews - Pending code reviews
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Zap,
  AlertTriangle,
  Shield,
  FileText,
  BarChart3,
  GitPullRequest,
  RefreshCw,
  ExternalLink,
  Clock,
  User,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  Info,
  Filter,
  Users as UsersIcon,
  Brain,
  Network,
  Activity,
  BookOpen,
  Link2,
  TrendingUp,
  TrendingDown,
  Target
} from 'lucide-react';
import { DEFAULT_RELEASE } from '../../config';
import DeveloperWorkloadChart from '../shared/DeveloperWorkloadChart';
import './DevDigestSection.css';

const API_BASE = '/api';

const DevDigestSection = ({ selectedRelease: selectedReleaseProp }) => {
  const selectedRelease = selectedReleaseProp || DEFAULT_RELEASE;
  // State for each data section
  const [escalations, setEscalations] = useState({ loading: true, data: [], error: null });
  const [securityIssues, setSecurityIssues] = useState({ loading: true, data: [], error: null });
  const [releaseItems, setReleaseItems] = useState({ loading: true, data: null, error: null });
  const [nplans, setNplans] = useState({ loading: true, data: null, error: null });
  const [nplanWorkitems, setNplanWorkitems] = useState({ loading: true, data: null, error: null });
  const [expandedNplans, setExpandedNplans] = useState({}); // Track which NPLANs are expanded
  const [openPRs, setOpenPRs] = useState({ loading: true, data: [], error: null });
  
  // AI Insights state
  const [knowledgeGaps, setKnowledgeGaps] = useState({ loading: false, data: null, error: null });
  const [workloadAnomalies, setWorkloadAnomalies] = useState({ loading: false, data: null, error: null });
  const [crossConcernLinks, setCrossConcernLinks] = useState({ loading: false, data: null, error: null });
  const [dailyDigest, setDailyDigest] = useState({ loading: false, data: null, error: null });
  const [aiInsightsLoaded, setAiInsightsLoaded] = useState(false);
  
  // Expanded sections state
  const [expandedSections, setExpandedSections] = useState({
    escalations: true,
    security: true,
    release: true,
    nplans: true,
    prs: true,
    knowledgeGaps: true,
    workload: true,
    crossLinks: true,
    digest: true,
  });

  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('data');
  
  // Global Assignee Filter - filters across ALL panels
  const [globalAssigneeFilter, setGlobalAssigneeFilter] = useState('all');
  
  // Security Issues Filter
  const [securityAssigneeFilter, setSecurityAssigneeFilter] = useState('all');
  
  // PR Filters
  const [prRepoFilter, setPrRepoFilter] = useState('all');
  const [prAssigneeFilter, setPrAssigneeFilter] = useState('all');
  const [prReviewerFilter, setPrReviewerFilter] = useState('all');
  
  // NPLAN Work Items Filter
  const [nplanAssigneeFilter, setNplanAssigneeFilter] = useState('all');

  // Toggle section expansion
  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Fetch all data - fire-and-forget pattern for progressive rendering
  const fetchAllData = (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    
    // Fire all fetches independently; each updates its own state as it resolves
    const promises = [
      fetchEscalations(),
      fetchSecurityIssues(),
      fetchReleaseItems(),
      fetchNplans(),
      fetchNplanWorkitems(),
      fetchOpenPRs()
    ];
    
    // Only clear refreshing indicator once all complete
    Promise.allSettled(promises).then(() => setRefreshing(false));
  };

  // Fetch customer escalations
  const fetchEscalations = async () => {
    try {
      const response = await fetch(`${API_BASE}/jira/escalations?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setEscalations({ 
          loading: false, 
          data: data.issues || [], 
          jiraUrl: data.jira_url,
          error: null 
        });
      } else {
        setEscalations({ loading: false, data: [], jiraUrl: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setEscalations({ loading: false, data: [], jiraUrl: null, error: err.message });
    }
  };

  // Fetch security issues
  const fetchSecurityIssues = async () => {
    try {
      const response = await fetch(`${API_BASE}/jira/security-issues?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setSecurityIssues({ 
          loading: false, 
          data: data.issues || [], 
          jiraUrl: data.jira_url,
          error: null 
        });
      } else {
        setSecurityIssues({ loading: false, data: [], jiraUrl: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setSecurityIssues({ loading: false, data: [], jiraUrl: null, error: err.message });
    }
  };

  // Fetch release items (from existing release readiness API)
  const fetchReleaseItems = async () => {
    try {
      const response = await fetch(`${API_BASE}/jira/release-readiness?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setReleaseItems({ loading: false, data: data, error: null });
      } else {
        setReleaseItems({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setReleaseItems({ loading: false, data: null, error: err.message });
    }
  };

  // Fetch NPLANs (from existing API)
  const fetchNplans = async () => {
    try {
      const response = await fetch(`${API_BASE}/jira/nplans?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setNplans({ loading: false, data: data, error: null });
      } else {
        setNplans({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setNplans({ loading: false, data: null, error: err.message });
    }
  };

  // Fetch NPLAN work items (Stories, Bugs, Tasks under NPLANs)
  const fetchNplanWorkitems = async () => {
    try {
      const response = await fetch(`${API_BASE}/jira/nplan-workitems?release=${selectedRelease}&include_closed=true`);
      if (response.ok) {
        const data = await response.json();
        setNplanWorkitems({ loading: false, data: data, error: null });
      } else {
        setNplanWorkitems({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setNplanWorkitems({ loading: false, data: null, error: err.message });
    }
  };

  // Fetch open PR reviews
  const fetchOpenPRs = async () => {
    try {
      const response = await fetch(`${API_BASE}/github/pending-reviews?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setOpenPRs({ loading: false, data: data.pull_requests || [], error: null });
      } else {
        setOpenPRs({ loading: false, data: [], error: 'Failed to fetch' });
      }
    } catch (err) {
      setOpenPRs({ loading: false, data: [], error: err.message });
    }
  };

  // AI Insights fetch functions
  const fetchKnowledgeGaps = async () => {
    setKnowledgeGaps(prev => ({ ...prev, loading: true, error: null }));
    try {
      const response = await fetch(`${API_BASE}/dev-insights/knowledge-gaps?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setKnowledgeGaps({ loading: false, data, error: null });
      } else {
        setKnowledgeGaps({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setKnowledgeGaps({ loading: false, data: null, error: err.message });
    }
  };

  const fetchWorkloadAnomalies = async () => {
    setWorkloadAnomalies(prev => ({ ...prev, loading: true, error: null }));
    try {
      const response = await fetch(`${API_BASE}/dev-insights/workload-anomalies?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setWorkloadAnomalies({ loading: false, data, error: null });
      } else {
        setWorkloadAnomalies({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setWorkloadAnomalies({ loading: false, data: null, error: err.message });
    }
  };

  const fetchCrossConcernLinks = async () => {
    setCrossConcernLinks(prev => ({ ...prev, loading: true, error: null }));
    try {
      const response = await fetch(`${API_BASE}/dev-insights/cross-concern-links?release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setCrossConcernLinks({ loading: false, data, error: null });
      } else {
        setCrossConcernLinks({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setCrossConcernLinks({ loading: false, data: null, error: err.message });
    }
  };

  const fetchDailyDigest = useCallback(async (developer) => {
    if (!developer || developer === 'all') return;
    setDailyDigest(prev => ({ ...prev, loading: true, error: null }));
    try {
      const response = await fetch(`${API_BASE}/dev-insights/daily-digest?developer=${encodeURIComponent(developer)}&release=${selectedRelease}`);
      if (response.ok) {
        const data = await response.json();
        setDailyDigest({ loading: false, data, error: null });
      } else {
        setDailyDigest({ loading: false, data: null, error: 'Failed to fetch' });
      }
    } catch (err) {
      setDailyDigest({ loading: false, data: null, error: err.message });
    }
  }, [selectedRelease]);

  const fetchAiInsights = () => {
    Promise.allSettled([
      fetchKnowledgeGaps(),
      fetchWorkloadAnomalies(),
      fetchCrossConcernLinks(),
    ]).then(() => setAiInsightsLoaded(true));
  };

  useEffect(() => {
    fetchAllData();
  }, [selectedRelease]);

  // Fetch daily digest when global filter changes to a specific person
  useEffect(() => {
    if (globalAssigneeFilter !== 'all' && activeTab === 'insights') {
      fetchDailyDigest(globalAssigneeFilter);
    }
  }, [globalAssigneeFilter, activeTab, fetchDailyDigest]);

  // Get priority badge class
  const getPriorityClass = (priority) => {
    if (!priority) return 'normal';
    const p = priority.toLowerCase();
    if (p.includes('blocker') || p === 'p1' || p === 'critical') return 'critical';
    if (p.includes('critical') || p === 'p2' || p === 'high') return 'high';
    if (p.includes('major') || p === 'p3' || p === 'medium') return 'medium';
    return 'normal';
  };

  // Get unique assignees for Security Issues filter
  const getSecurityAssignees = () => {
    const assignees = new Set();
    securityIssues.data?.forEach(issue => {
      if (issue.assignee && issue.assignee !== 'Unassigned') {
        assignees.add(issue.assignee);
      }
    });
    return Array.from(assignees).sort();
  };
  
  // Filter security issues by assignee
  const getFilteredSecurityIssues = () => {
    if (securityAssigneeFilter === 'all') {
      return securityIssues.data || [];
    }
    return (securityIssues.data || []).filter(issue => 
      issue.assignee === securityAssigneeFilter
    );
  };
  
  const securityAssignees = getSecurityAssignees();
  const filteredSecurityIssues = getFilteredSecurityIssues();
  
  // Get unique repos and assignees for PR filters
  const getUniqueRepos = () => {
    const repos = new Set();
    openPRs.data?.forEach(pr => {
      if (pr.repo) repos.add(pr.repo);
    });
    return Array.from(repos).sort();
  };
  
  // Get unique assignees (authors + assignees)
  const getUniqueAssignees = () => {
    const people = new Set();
    openPRs.data?.forEach(pr => {
      // Add author
      if (pr.author) people.add(pr.author);
      // Add assignees
      pr.assignees?.forEach(a => {
        if (a) people.add(a);
      });
    });
    return Array.from(people).sort();
  };
  
  // Get unique reviewers
  const getUniqueReviewers = () => {
    const reviewers = new Set();
    openPRs.data?.forEach(pr => {
      pr.reviewers?.forEach(r => {
        if (r) reviewers.add(r);
      });
    });
    return Array.from(reviewers).sort();
  };
  
  // Filter PRs based on selected filters
  const getFilteredPRs = () => {
    let filtered = openPRs.data || [];
    
    if (prRepoFilter !== 'all') {
      filtered = filtered.filter(pr => pr.repo === prRepoFilter);
    }
    
    if (prAssigneeFilter !== 'all') {
      filtered = filtered.filter(pr => 
        pr.author === prAssigneeFilter || 
        pr.assignees?.includes(prAssigneeFilter)
      );
    }
    
    if (prReviewerFilter !== 'all') {
      filtered = filtered.filter(pr => 
        pr.reviewers?.includes(prReviewerFilter)
      );
    }
    
    return filtered;
  };
  
  // ========== Global Assignee Filter Logic ==========
  
  // Collect ALL unique assignees across every data source
  const getAllAssignees = () => {
    const allNames = new Set();
    
    // Escalations assignees
    escalations.data?.forEach(item => {
      if (item.assignee && item.assignee !== 'Unassigned') {
        allNames.add(item.assignee);
      }
    });
    
    // Security issues assignees
    securityIssues.data?.forEach(item => {
      if (item.assignee && item.assignee !== 'Unassigned') {
        allNames.add(item.assignee);
      }
    });
    
    // Release items - from storiesByAssignee
    releaseItems.data?.storiesByAssignee?.forEach(entry => {
      if (entry.assignee && entry.assignee !== 'Unassigned') {
        allNames.add(entry.assignee);
      }
    });
    
    // NPLAN items assignees
    nplans.data?.items?.forEach(item => {
      if (item.assignee && item.assignee !== 'Unassigned') {
        allNames.add(item.assignee);
      }
    });
    
    // PR authors, assignees, reviewers
    openPRs.data?.forEach(pr => {
      if (pr.author) allNames.add(pr.author);
      pr.assignees?.forEach(a => { if (a) allNames.add(a); });
      pr.reviewers?.forEach(r => { if (r) allNames.add(r); });
    });
    
    return Array.from(allNames).sort();
  };
  
  const allAssignees = getAllAssignees();
  
  // Apply global filter to escalations
  const getGlobalFilteredEscalations = () => {
    if (globalAssigneeFilter === 'all') return escalations.data || [];
    return (escalations.data || []).filter(item => 
      item.assignee === globalAssigneeFilter
    );
  };
  
  // Apply global filter to security issues (combined with panel-level filter)
  const getGlobalFilteredSecurityIssues = () => {
    let filtered = securityIssues.data || [];
    if (globalAssigneeFilter !== 'all') {
      filtered = filtered.filter(item => item.assignee === globalAssigneeFilter);
    }
    if (securityAssigneeFilter !== 'all') {
      filtered = filtered.filter(item => item.assignee === securityAssigneeFilter);
    }
    return filtered;
  };
  
  // Apply global filter to release items storiesByAssignee
  const getGlobalFilteredStoriesByAssignee = () => {
    if (globalAssigneeFilter === 'all') return releaseItems.data?.storiesByAssignee || [];
    return (releaseItems.data?.storiesByAssignee || []).filter(entry =>
      entry.assignee === globalAssigneeFilter
    );
  };
  
  // Apply global filter to NPLAN items
  const getGlobalFilteredNplanItems = () => {
    if (globalAssigneeFilter === 'all') return nplans.data?.items || [];
    return (nplans.data?.items || []).filter(item =>
      item.assignee === globalAssigneeFilter
    );
  };
  
  // Apply global filter to PRs (combined with panel-level filters)
  const getGlobalFilteredPRs = () => {
    let filtered = openPRs.data || [];
    
    // Global assignee filter - matches author, assignees, or reviewers
    if (globalAssigneeFilter !== 'all') {
      filtered = filtered.filter(pr => 
        pr.author === globalAssigneeFilter || 
        pr.assignees?.includes(globalAssigneeFilter) ||
        pr.reviewers?.includes(globalAssigneeFilter)
      );
    }
    
    // Panel-level filters
    if (prRepoFilter !== 'all') {
      filtered = filtered.filter(pr => pr.repo === prRepoFilter);
    }
    if (prAssigneeFilter !== 'all') {
      filtered = filtered.filter(pr => 
        pr.author === prAssigneeFilter || 
        pr.assignees?.includes(prAssigneeFilter)
      );
    }
    if (prReviewerFilter !== 'all') {
      filtered = filtered.filter(pr => 
        pr.reviewers?.includes(prReviewerFilter)
      );
    }
    
    return filtered;
  };
  
  const globalFilteredEscalations = getGlobalFilteredEscalations();
  const globalFilteredSecurityIssues = getGlobalFilteredSecurityIssues();
  const globalFilteredStoriesByAssignee = getGlobalFilteredStoriesByAssignee();
  const globalFilteredNplanItems = getGlobalFilteredNplanItems();
  const globalFilteredPRs = getGlobalFilteredPRs();
  
  // Clear global filter and all panel filters
  const clearAllFilters = () => {
    setGlobalAssigneeFilter('all');
    setSecurityAssigneeFilter('all');
    setPrRepoFilter('all');
    setPrAssigneeFilter('all');
    setPrReviewerFilter('all');
  };
  
  // ========== Summary Stats (uses global filtered data) ==========
  
  const getSummaryStats = () => {
    if (globalAssigneeFilter === 'all') {
      // Unfiltered - use original totals
      return {
        escalationCount: escalations.data?.length || 0,
        securityCount: securityIssues.data?.length || 0,
        releaseOpenCount: releaseItems.data?.summary?.total_fb_issues || 0,
        nplanTotal: nplans.data?.total || 0,
        nplanComplete: nplans.data?.completed || 0,
        prCount: openPRs.data?.length || 0
      };
    }
    
    // Filtered - use filtered data counts
    const filteredReleaseCount = globalFilteredStoriesByAssignee.reduce((sum, entry) => {
      return sum + (entry.total || entry.count || 0);
    }, 0);
    
    return {
      escalationCount: globalFilteredEscalations.length,
      securityCount: globalFilteredSecurityIssues.length,
      releaseOpenCount: filteredReleaseCount || 0,
      nplanTotal: globalFilteredNplanItems.length,
      nplanComplete: globalFilteredNplanItems.filter(i => 
        i.status?.toLowerCase() === 'done' || i.status?.toLowerCase() === 'completed'
      ).length,
      prCount: globalFilteredPRs.length
    };
  };

  const stats = getSummaryStats();
  const isGlobalFilterActive = globalAssigneeFilter !== 'all';
  
  // ========== Per-panel filter helpers (kept for secondary filtering) ==========
  
  const uniqueRepos = getUniqueRepos();
  const uniqueAssignees = getUniqueAssignees();
  const uniqueReviewers = getUniqueReviewers();
  const filteredPRs = globalFilteredPRs;

  // Render loading spinner
  const renderLoading = () => (
    <div className="digest-loading">
      <RefreshCw size={20} className="spin" />
      <span>Loading...</span>
    </div>
  );

  // Render error state
  const renderError = (error) => (
    <div className="digest-error">
      <AlertTriangle size={16} />
      <span>{error || 'Failed to load data'}</span>
    </div>
  );

  // Render empty state
  const renderEmpty = (message) => (
    <div className="digest-empty">
      <CheckCircle size={20} />
      <span>{message}</span>
    </div>
  );

  return (
    <div className="dev-digest-section">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1><Zap size={24} /> Dev Digest</h1>
          <p>Daily developer action items for {selectedRelease}</p>
        </div>
        <div className="header-right">
          <button 
            className={`refresh-btn ${refreshing ? 'refreshing' : ''}`}
            onClick={() => fetchAllData(true)}
            disabled={refreshing}
          >
            <RefreshCw size={16} className={refreshing ? 'spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Global Assignee Filter */}
      <div className="global-filter-bar">
        <div className="global-filter-left">
          <UsersIcon size={16} className="global-filter-icon" />
          <span className="global-filter-label">Filter by Assignee</span>
          <select 
            value={globalAssigneeFilter}
            onChange={(e) => setGlobalAssigneeFilter(e.target.value)}
            className="global-filter-select"
          >
            <option value="all">All Team Members ({allAssignees.length})</option>
            {allAssignees.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          {isGlobalFilterActive && (
            <button className="global-filter-clear" onClick={clearAllFilters}>
              Clear All Filters
            </button>
          )}
        </div>
        {isGlobalFilterActive && (
          <div className="global-filter-active-indicator">
            <User size={14} />
            <span>Showing items for <strong>{globalAssigneeFilter}</strong></span>
          </div>
        )}
      </div>

      {/* Tab Navigation */}
      <div className="digest-tabs">
        <button 
          className={`digest-tab ${activeTab === 'data' ? 'active' : ''}`}
          onClick={() => setActiveTab('data')}
        >
          <Zap size={16} />
          Data Panels
        </button>
        <button 
          className={`digest-tab disabled`}
          disabled
          title="Coming Soon"
        >
          <Brain size={16} />
          AI Insights
          <span className="tab-badge coming-soon">Coming Soon</span>
        </button>
      </div>

      {/* Summary Cards */}
      <div className="digest-summary-row">
        <div className={`summary-card ${stats.escalationCount > 0 ? 'warning' : 'success'}`}>
          <AlertTriangle size={20} />
          <div className="summary-content">
            <span className="summary-value">{stats.escalationCount}</span>
            <span className="summary-label">Escalations</span>
          </div>
        </div>
        <div className={`summary-card ${stats.securityCount > 0 ? 'critical' : 'success'}`}>
          <Shield size={20} />
          <div className="summary-content">
            <span className="summary-value">{stats.securityCount}</span>
            <span className="summary-label">Security Issues</span>
          </div>
        </div>
        <div className={`summary-card ${stats.releaseOpenCount > 0 ? 'info' : 'success'}`}>
          <FileText size={20} />
          <div className="summary-content">
            <span className="summary-value">{stats.releaseOpenCount}</span>
            <span className="summary-label">Release Items</span>
          </div>
        </div>
        <div className="summary-card info">
          <BarChart3 size={20} />
          <div className="summary-content">
            <span className="summary-value">{stats.nplanComplete}/{stats.nplanTotal}</span>
            <span className="summary-label">NPLANs Done</span>
          </div>
        </div>
        <div className={`summary-card ${stats.prCount > 0 ? 'warning' : 'success'}`}>
          <GitPullRequest size={20} />
          <div className="summary-content">
            <span className="summary-value">{stats.prCount}</span>
            <span className="summary-label">Open PRs</span>
          </div>
        </div>
      </div>

      {/* Main Content Grid - Data Panels Tab */}
      <div className="digest-grid" style={{ display: activeTab === 'data' ? '' : 'none' }}>
        {/* Customer Escalations */}
        <div className="digest-panel">
          <div className="panel-header" onClick={() => toggleSection('escalations')}>
            <div className="panel-title">
              {expandedSections.escalations ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <AlertTriangle size={18} className="panel-icon escalation" />
              <h3>Customer Escalations</h3>
              <span className="panel-count">{stats.escalationCount}</span>
            </div>
            <div className="panel-header-right">
              {escalations.jiraUrl && (
                <a 
                  href={escalations.jiraUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="jira-btn"
                  onClick={(e) => e.stopPropagation()}
                  title="Open in JIRA"
                >
                  <ExternalLink size={14} />
                </a>
              )}
              <span className="panel-source">JIRA</span>
            </div>
          </div>
          {expandedSections.escalations && (
            <div className="panel-content">
              {escalations.loading ? renderLoading() :
               escalations.error ? renderError(escalations.error) :
               escalations.data.length === 0 ? renderEmpty(`No customer escalations for ${selectedRelease}`) :
               globalFilteredEscalations.length === 0 ? renderEmpty(`No escalations assigned to ${globalAssigneeFilter}`) :
               (
                <div className="items-list">
                  {globalFilteredEscalations.map((item, idx) => (
                    <div key={item.key || idx} className="digest-item escalation-item">
                      <div className="item-header">
                        <a 
                          href={item.url || `https://your-org.atlassian.net/browse/${item.key}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="item-key"
                        >
                          {item.key}
                          <ExternalLink size={12} />
                        </a>
                        <div className="item-badges">
                          <span className={`priority-badge ${getPriorityClass(item.priority)}`}>
                            {item.priority || 'P3'}
                          </span>
                          <span className={`status-badge ${(item.status || 'open').toLowerCase().replace(/\s+/g, '-')}`}>
                            {item.status || 'Open'}
                          </span>
                        </div>
                      </div>
                      <div className="item-summary">{item.summary}</div>
                      <div className="item-meta">
                        <span><User size={12} /> {item.assignee || 'Unassigned'}</span>
                        <span><Clock size={12} /> {item.age || 'New'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Security Issues */}
        <div className="digest-panel">
          <div className="panel-header" onClick={() => toggleSection('security')}>
            <div className="panel-title">
              {expandedSections.security ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <Shield size={18} className="panel-icon security" />
              <h3>Security Issues</h3>
              <span className="panel-count">{stats.securityCount}</span>
            </div>
            <div className="panel-header-right">
              {securityIssues.jiraUrl && (
                <a 
                  href={securityIssues.jiraUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="jira-btn"
                  onClick={(e) => e.stopPropagation()}
                  title="Open in JIRA"
                >
                  <ExternalLink size={14} />
                </a>
              )}
              <span className="panel-source">JIRA</span>
            </div>
          </div>
          {expandedSections.security && (
            <div className="panel-content">
              {securityIssues.loading ? renderLoading() :
               securityIssues.error ? renderError(securityIssues.error) :
               securityIssues.data.length === 0 ? renderEmpty('No security issues') :
               globalFilteredSecurityIssues.length === 0 ? renderEmpty(`No security issues for ${globalAssigneeFilter}`) :
               (
                <>
                  {/* Assignee Filter (secondary, within global) */}
                  {!isGlobalFilterActive && (
                    <div className="digest-filters">
                      <div className="filter-group">
                        <User size={14} />
                        <select 
                          value={securityAssigneeFilter} 
                          onChange={(e) => setSecurityAssigneeFilter(e.target.value)}
                          className="filter-select"
                          title="Filter by assignee"
                        >
                          <option value="all">All Assignees ({securityAssignees.length})</option>
                          {securityAssignees.map(assignee => (
                            <option key={assignee} value={assignee}>{assignee}</option>
                          ))}
                        </select>
                      </div>
                      {securityAssigneeFilter !== 'all' && (
                        <button 
                          className="filter-clear"
                          onClick={() => setSecurityAssigneeFilter('all')}
                        >
                          Clear
                        </button>
                      )}
                      <span className="filter-count">
                        Showing {globalFilteredSecurityIssues.length} of {securityIssues.data.length}
                      </span>
                    </div>
                  )}
                  {isGlobalFilterActive && (
                    <div className="digest-filters">
                      <span className="filter-count">
                        Showing {globalFilteredSecurityIssues.length} of {securityIssues.data.length} for {globalAssigneeFilter}
                      </span>
                    </div>
                  )}
                  <div className="items-list">
                    {globalFilteredSecurityIssues.map((item, idx) => (
                      <div key={item.key || idx} className="digest-item security-item">
                        <div className="item-header">
                          <a 
                            href={item.url || `https://your-org.atlassian.net/browse/${item.key}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="item-key"
                          >
                            {item.key}
                            <ExternalLink size={12} />
                          </a>
                          <div className="item-badges">
                            {item.type && (
                              <span className="pr-label">{item.type}</span>
                            )}
                            <span className={`priority-badge ${getPriorityClass(item.severity || item.priority)}`}>
                              {item.severity || item.priority || 'Medium'}
                            </span>
                          </div>
                        </div>
                        <div className="item-summary">{item.summary}</div>
                        <div className="item-meta">
                          <span><User size={12} /> {item.assignee || 'Unassigned'}</span>
                          <span><Clock size={12} /> {item.status || 'Open'}</span>
                          {item.fixVersion && (
                            <span className="pr-label">v{item.fixVersion}</span>
                          )}
                        </div>
                        {item.labels && item.labels.length > 0 && (
                          <div className="pr-labels">
                            {item.labels.slice(0, 4).map((label, i) => (
                              <span key={i} className="pr-label">{label}</span>
                            ))}
                            {item.labels.length > 4 && (
                              <span className="pr-label-more">+{item.labels.length - 4}</span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Release Items */}
        <div className="digest-panel">
          <div className="panel-header" onClick={() => toggleSection('release')}>
            <div className="panel-title">
              {expandedSections.release ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <FileText size={18} className="panel-icon release" />
              <h3>Release Items</h3>
              <span className="panel-count">{stats.releaseOpenCount}</span>
            </div>
            <span className="panel-source">JIRA</span>
          </div>
          {expandedSections.release && (
            <div className="panel-content">
              {releaseItems.loading ? renderLoading() :
               releaseItems.error ? renderError(releaseItems.error) :
               !releaseItems.data ? renderEmpty('No data available') :
               (
                <div className="release-summary">
                  <div className="release-stats-grid">
                    <div className="release-stat">
                      <span className="stat-value">{releaseItems.data.summary?.total_bc_stories || 0}</span>
                      <span className="stat-label">Stories</span>
                    </div>
                    <div className="release-stat">
                      <span className="stat-value">{releaseItems.data.summary?.total_bc_bugs || 0}</span>
                      <span className="stat-label">Bugs</span>
                    </div>
                    <div className="release-stat">
                      <span className="stat-value">{releaseItems.data.summary?.code_review_count || 0}</span>
                      <span className="stat-label">In Review</span>
                    </div>
                    <div className="release-stat">
                      <span className="stat-value">{releaseItems.data.summary?.blocked_count || 0}</span>
                      <span className="stat-label">Blocked</span>
                    </div>
                  </div>
                  
                  {/* Developer Workload Chart - Same as Release Readiness */}
                  {globalFilteredStoriesByAssignee && globalFilteredStoriesByAssignee.length > 0 && (
                    <div className="workload-chart-container">
                      <DeveloperWorkloadChart 
                        storiesByAssignee={globalFilteredStoriesByAssignee}
                        title={isGlobalFilterActive ? `${globalAssigneeFilter}'s Workload` : "Developer Workload"}
                        showLegend={true}
                        maxHeight="250px"
                        release={selectedRelease}
                      />
                    </div>
                  )}
                  {isGlobalFilterActive && globalFilteredStoriesByAssignee.length === 0 && (
                    <div className="digest-empty" style={{ padding: '12px' }}>
                      <Info size={14} />
                      <span>No release items assigned to {globalAssigneeFilter}</span>
                    </div>
                  )}
                  
                  {releaseItems.data.summary?.total_fb_issues > 0 && (
                    <a 
                      href={`#readiness-tracking`}
                      className="view-all-link"
                      onClick={(e) => {
                        e.preventDefault();
                        // Navigate to release readiness
                        window.location.hash = 'readiness-tracking';
                      }}
                    >
                      View all items in Release Readiness →
                    </a>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* NPLAN Tracking */}
        <div className="digest-panel">
          <div className="panel-header" onClick={() => toggleSection('nplans')}>
            <div className="panel-title">
              {expandedSections.nplans ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <BarChart3 size={18} className="panel-icon nplan" />
              <h3>NPLAN Tracking</h3>
              <span className="panel-count">{stats.nplanComplete}/{stats.nplanTotal}</span>
            </div>
            <span className="panel-source">JIRA</span>
          </div>
          {expandedSections.nplans && (
            <div className="panel-content">
              {nplans.loading || nplanWorkitems.loading ? renderLoading() :
               nplans.error ? renderError(nplans.error) :
               !nplans.data ? renderEmpty('No NPLAN data') :
               (
                <div className="nplan-tracking-container">
                  {/* Assignee Filter */}
                  <div className="nplan-filters">
                    <div className="filter-group">
                      <User size={14} />
                      <select 
                        value={nplanAssigneeFilter} 
                        onChange={(e) => setNplanAssigneeFilter(e.target.value)}
                        className="filter-select"
                      >
                        <option value="all">All Assignees ({nplanWorkitems.data?.assignees?.length || 0})</option>
                        {(nplanWorkitems.data?.assignees || []).map(assignee => (
                          <option key={assignee} value={assignee}>
                            {assignee} ({nplanWorkitems.data?.summary?.by_assignee?.[assignee] || 0})
                          </option>
                        ))}
                      </select>
                    </div>
                    {nplanAssigneeFilter !== 'all' && (
                      <button 
                        className="filter-clear"
                        onClick={() => setNplanAssigneeFilter('all')}
                      >
                        Clear filter
                      </button>
                    )}
                  </div>

                  {/* Overall Progress */}
                  <div className="nplan-overall-progress">
                    <div className="progress-stats">
                      <span className="progress-label">
                        {nplanWorkitems.data?.summary?.closed_items || 0} / {nplanWorkitems.data?.summary?.total_items || 0} items completed
                      </span>
                      <span className="progress-pct">
                        {nplanWorkitems.data?.summary?.completion_pct || 0}%
                      </span>
                    </div>
                    <div className="progress-bar">
                      <div 
                        className="progress-fill"
                        style={{ width: `${nplanWorkitems.data?.summary?.completion_pct || 0}%` }}
                      ></div>
                    </div>
                  </div>

                  {/* NPLAN List with Expandable Work Items */}
                  <div className="nplan-items-list">
                    {globalFilteredNplanItems && globalFilteredNplanItems.length > 0 ? (
                      globalFilteredNplanItems.map((nplanItem, idx) => {
                        const nplanId = nplanItem.id;
                        const workitemData = nplanWorkitems.data?.nplan_workitems?.[nplanId];
                        const metadata = nplanWorkitems.data?.nplans_metadata?.[nplanId];
                        const isExpanded = expandedNplans[nplanId] || false;
                        
                        // Filter items by assignee if filter is active
                        const filteredItems = nplanAssigneeFilter === 'all' 
                          ? workitemData?.items || []
                          : (workitemData?.items || []).filter(item => item.assignee === nplanAssigneeFilter);
                        
                        const itemCount = filteredItems.length;
                        const closedCount = filteredItems.filter(item => 
                          ['Closed', 'Resolved', 'Done', 'Pending Close'].includes(item.status)
                        ).length;
                        const openCount = itemCount - closedCount;
                        const completionPct = itemCount > 0 ? Math.round((closedCount / itemCount) * 100) : 0;

                        return (
                          <div key={idx} className={`nplan-tracking-row ${isExpanded ? 'expanded' : ''}`}>
                            {/* NPLAN Header Row */}
                            <div 
                              className={`nplan-row-header ${nplanItem.status?.toLowerCase().replace(/\s+/g, '-') || 'tbd'}`}
                              onClick={() => setExpandedNplans(prev => ({ ...prev, [nplanId]: !prev[nplanId] }))}
                            >
                              <div className="nplan-row-expand">
                                {itemCount > 0 ? (
                                  <ChevronRight size={14} className={`expand-icon ${isExpanded ? 'expanded' : ''}`} />
                                ) : (
                                  <span className="no-expand"></span>
                                )}
                              </div>
                              <div className="nplan-row-id">
                                <a 
                                  href={nplanItem.jira_url || `https://your-org.atlassian.net/browse/${nplanId}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {nplanId}
                                </a>
                              </div>
                              <div className="nplan-row-desc" title={nplanItem.description}>
                                {nplanItem.description || '—'}
                              </div>
                              <div className="nplan-row-status">
                                <span className={`nplan-status-badge ${nplanItem.status?.toLowerCase().replace(/\s+/g, '-') || 'tbd'}`}>
                                  {nplanItem.status || 'TBD'}
                                </span>
                              </div>
                              <div className="nplan-row-items">
                                {itemCount > 0 ? (
                                  <span className="item-count-badge">
                                    {itemCount} items
                                  </span>
                                ) : (
                                  <span className="no-items">—</span>
                                )}
                              </div>
                            </div>

                            {/* Expanded Work Items Panel */}
                            {isExpanded && itemCount > 0 && (
                              <div className="nplan-workitems-panel">
                                {/* Mini Progress */}
                                <div className="nplan-mini-progress">
                                  <div className="mini-progress-bar">
                                    <div 
                                      className="mini-progress-fill"
                                      style={{ width: `${completionPct}%` }}
                                    ></div>
                                  </div>
                                  <span className="mini-progress-text">
                                    {completionPct}% ({closedCount}/{itemCount})
                                  </span>
                                </div>

                                {/* Work Items Table */}
                                <div className="nplan-workitems-table">
                                  <div className="workitems-table-header">
                                    <div className="wi-col key">Key</div>
                                    <div className="wi-col type">Type</div>
                                    <div className="wi-col summary">Summary</div>
                                    <div className="wi-col status">Status</div>
                                    <div className="wi-col priority">Priority</div>
                                    <div className="wi-col assignee">Assignee</div>
                                  </div>
                                  <div className="workitems-table-body">
                                    {filteredItems.slice(0, 10).map((item, itemIdx) => (
                                      <div key={itemIdx} className="workitem-row">
                                        <div className="wi-col key">
                                          <a 
                                            href={item.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {item.key}
                                          </a>
                                        </div>
                                        <div className="wi-col type">
                                          <span className={`type-badge ${item.issuetype?.toLowerCase() || 'task'}`}>
                                            {item.issuetype === 'Story' && '📘'}
                                            {item.issuetype === 'Bug' && '🐛'}
                                            {item.issuetype === 'Task' && '📋'}
                                            {item.issuetype === 'Epic' && '⚡'}
                                            {!['Story', 'Bug', 'Task', 'Epic'].includes(item.issuetype) && '📄'}
                                            {' '}{item.issuetype || 'Task'}
                                          </span>
                                        </div>
                                        <div className="wi-col summary" title={item.summary}>
                                          {item.summary}
                                        </div>
                                        <div className="wi-col status">
                                          <span className={`wi-status-badge ${item.status?.toLowerCase().replace(/\s+/g, '-') || 'open'}`}>
                                            {item.status}
                                          </span>
                                        </div>
                                        <div className="wi-col priority">
                                          <span className={`wi-priority-badge ${item.priority?.toLowerCase() || 'medium'}`}>
                                            {item.priority}
                                          </span>
                                        </div>
                                        <div className="wi-col assignee" title={item.assignee}>
                                          {item.assignee || 'Unassigned'}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                  {filteredItems.length > 10 && (
                                    <div className="workitems-more">
                                      <a 
                                        href={`https://your-org.atlassian.net/issues/?jql=parent%20%3D%20${nplanId}%20OR%20issueKey%20IN%20portfolioChildIssuesOf(%22${nplanId}%22)${nplanAssigneeFilter !== 'all' ? `%20AND%20assignee%20%3D%20%22${encodeURIComponent(nplanAssigneeFilter)}%22` : ''}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                      >
                                        +{filteredItems.length - 10} more items → Open in JIRA
                                      </a>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <div className="digest-empty" style={{ padding: '12px' }}>
                        <Info size={14} />
                        <span>No NPLANs found for this release</span>
                      </div>
                    )}
                  </div>

                  {isGlobalFilterActive && globalFilteredNplanItems.length === 0 && (
                    <div className="digest-empty" style={{ padding: '12px' }}>
                      <Info size={14} />
                      <span>No NPLAN items for {globalAssigneeFilter}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Open PR Reviews */}
        <div className="digest-panel digest-panel-wide">
          <div className="panel-header" onClick={() => toggleSection('prs')}>
            <div className="panel-title">
              {expandedSections.prs ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <GitPullRequest size={18} className="panel-icon pr" />
              <h3>Open PR Reviews</h3>
              <span className="panel-count">{stats.prCount}</span>
            </div>
            <span className="panel-source">GitHub</span>
          </div>
          {expandedSections.prs && (
            <div className="panel-content">
              {openPRs.loading ? renderLoading() :
               openPRs.error ? renderError(openPRs.error) :
               openPRs.data.length === 0 ? renderEmpty('No pending PR reviews') :
               (
                <>
                  {/* PR Filters */}
                  <div className="pr-filters">
                    <div className="filter-group">
                      <Filter size={14} />
                      <select 
                        value={prRepoFilter} 
                        onChange={(e) => setPrRepoFilter(e.target.value)}
                        className="filter-select"
                      >
                        <option value="all">All Repos ({uniqueRepos.length})</option>
                        {uniqueRepos.map(repo => (
                          <option key={repo} value={repo}>{repo}</option>
                        ))}
                      </select>
                    </div>
                    {!isGlobalFilterActive && (
                      <>
                        <div className="filter-group">
                          <User size={14} />
                          <select 
                            value={prAssigneeFilter} 
                            onChange={(e) => setPrAssigneeFilter(e.target.value)}
                            className="filter-select"
                            title="Filter by author or assignee"
                          >
                            <option value="all">All Assignees ({uniqueAssignees.length})</option>
                            {uniqueAssignees.map(assignee => (
                              <option key={assignee} value={assignee}>{assignee}</option>
                            ))}
                          </select>
                        </div>
                        <div className="filter-group">
                          <UsersIcon size={14} />
                          <select 
                            value={prReviewerFilter} 
                            onChange={(e) => setPrReviewerFilter(e.target.value)}
                            className="filter-select"
                            title="Filter by requested reviewer"
                          >
                            <option value="all">All Reviewers ({uniqueReviewers.length})</option>
                            {uniqueReviewers.map(reviewer => (
                              <option key={reviewer} value={reviewer}>{reviewer}</option>
                            ))}
                          </select>
                        </div>
                      </>
                    )}
                    {(prRepoFilter !== 'all' || prAssigneeFilter !== 'all' || prReviewerFilter !== 'all') && !isGlobalFilterActive && (
                      <button 
                        className="filter-clear"
                        onClick={() => { setPrRepoFilter('all'); setPrAssigneeFilter('all'); setPrReviewerFilter('all'); }}
                      >
                        Clear filters
                      </button>
                    )}
                    <span className="filter-count">
                      Showing {filteredPRs.length} of {openPRs.data.length}
                      {isGlobalFilterActive && ` for ${globalAssigneeFilter}`}
                    </span>
                  </div>
                  
                  <div className="items-list pr-items-list">
                    {filteredPRs.map((pr, idx) => (
                      <div key={pr.id || idx} className={`digest-item pr-item pr-age-${pr.age_category || 'normal'}`}>
                        {/* Row 1: PR number, repo, status badges */}
                        <div className="pr-header-row">
                          <div className="pr-identity">
                            <a 
                              href={pr.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="item-key"
                            >
                              #{pr.number}
                              <ExternalLink size={12} />
                            </a>
                            <span className="pr-repo">{pr.repo}</span>
                            {pr.target_branch && (
                              <span className="pr-target-branch" title={`Target: ${pr.target_branch}`}>
                                → {pr.target_branch}
                              </span>
                            )}
                          </div>
                          <div className="pr-status-badges">
                            {/* Size badge */}
                            <span className={`pr-size-badge size-${pr.size?.toLowerCase() || 'm'}`} title={`+${pr.additions || 0} -${pr.deletions || 0}`}>
                              {pr.size || 'M'}
                            </span>
                            {/* CI Status */}
                            <span 
                              className={`pr-ci-badge ci-${pr.ci_status || 'unknown'}`} 
                              title={pr.ci_status === 'success' ? 'CI: All checks passed' : 
                                     pr.ci_status === 'failure' ? 'CI: One or more checks failed' : 
                                     pr.ci_status === 'pending' ? 'CI: Checks are still running' : 
                                     'CI: Status unknown (no checks configured or not yet computed)'}
                            >
                              {pr.ci_status === 'success' ? '✓ CI' : 
                               pr.ci_status === 'failure' ? '✗ CI' : 
                               pr.ci_status === 'pending' ? '○ CI' : '? CI'}
                            </span>
                            {/* Review Status */}
                            <span 
                              className={`pr-review-badge review-${pr.review_status || 'pending'}`} 
                              title={pr.review_status === 'approved' ? 'Review: Approved by all reviewers' : 
                                     pr.review_status === 'partially_approved' ? 'Review: Approved by some reviewers, others pending' :
                                     pr.review_status === 'changes_requested' ? 'Review: Changes requested by reviewer' : 
                                     'Review: Awaiting review'}
                            >
                              {pr.review_status === 'approved' ? '✓ Approved' : 
                               pr.review_status === 'partially_approved' ? '◐ Partial' :
                               pr.review_status === 'changes_requested' ? '✗ Changes' : '○ Review'}
                            </span>
                            {/* Merge conflict indicator */}
                            {pr.mergeable === false && (
                              <span className="pr-conflict-badge" title="Has merge conflicts">
                                ⚠ Conflict
                              </span>
                            )}
                            {/* Stale badge */}
                            {pr.age_category === 'stale' && (
                              <span className="pr-stale-badge" title={`Open for ${pr.age_days} days`}>
                                🕐 Stale
                              </span>
                            )}
                            {/* Priority badge */}
                            {pr.priority_score !== undefined && (
                              <span 
                                className={`pr-priority-badge priority-${pr.priority_score <= 50 ? 'high' : pr.priority_score <= 100 ? 'medium' : 'low'}`}
                                title={`Priority Score: ${pr.priority_score} (lower = higher priority). Based on CI status, review status, age, conflicts, and labels.`}
                              >
                                {pr.priority_score <= 50 ? '🔴' : pr.priority_score <= 100 ? '🟡' : '🟢'}
                              </span>
                            )}
                          </div>
                        </div>
                        
                        {/* Row 2: Title */}
                        <div className="item-summary">{pr.title}</div>
                        
                        {/* Row 3: Labels */}
                        {pr.labels && pr.labels.length > 0 && (
                          <div className="pr-labels">
                            {pr.labels.slice(0, 5).map((label, i) => (
                              <span key={i} className="pr-label">{label}</span>
                            ))}
                            {pr.labels.length > 5 && <span className="pr-label-more">+{pr.labels.length - 5}</span>}
                          </div>
                        )}
                        
                        {/* Row 4: Stats and people */}
                        <div className="pr-details-row">
                          <div className="pr-stats">
                            <span title="Files changed">📁 {pr.changed_files || 0}</span>
                            <span title="Commits">📝 {pr.commits || 0}</span>
                            <span title="Comments">💬 {(pr.comments || 0) + (pr.review_comments || 0)}</span>
                            <span title={`+${pr.additions || 0} -${pr.deletions || 0} lines`} className="pr-lines">
                              <span className="lines-add">+{pr.additions || 0}</span>
                              <span className="lines-del">-{pr.deletions || 0}</span>
                            </span>
                          </div>
                          <div className="pr-age-display">
                            <Clock size={12} />
                            <span>{pr.age || '?'}</span>
                          </div>
                        </div>
                        
                        {/* Row 5: People */}
                        <div className="pr-people-row">
                          <span title="Author" className="pr-author">
                            <User size={12} /> {pr.author}
                          </span>
                          {pr.assignees && pr.assignees.length > 0 && (
                            <span title="Assignees" className="pr-assignees">
                              <User size={12} /> {pr.assignees.join(', ')}
                            </span>
                          )}
                          {pr.reviewers && pr.reviewers.length > 0 && (
                            <span title="Requested Reviewers" className="pr-reviewers">
                              <UsersIcon size={12} /> {pr.reviewers.join(', ')}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {filteredPRs.length === 0 && (
                      <div className="digest-empty">
                        <Info size={16} />
                        <span>No PRs match the selected filters</span>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      {/* AI Insights Tab */}
      {activeTab === 'insights' && (
        <div className="digest-grid ai-insights-grid">
          
          {/* Personalized Daily Digest Panel */}
          {globalAssigneeFilter !== 'all' && (
            <div className="digest-panel digest-panel-wide ai-panel">
              <div className="panel-header" onClick={() => toggleSection('digest')}>
                <div className="panel-title">
                  {expandedSections.digest ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  <Target size={18} className="panel-icon digest-icon" />
                  <h3>Daily Digest for {globalAssigneeFilter}</h3>
                  {dailyDigest.data?.summary && (
                    <span className="panel-count">{dailyDigest.data.summary.total_assigned} items</span>
                  )}
                </div>
                <span className="panel-source ai-badge">AI Agent</span>
              </div>
              {expandedSections.digest && (
                <div className="panel-content">
                  {dailyDigest.loading ? renderLoading() :
                   dailyDigest.error ? renderError(dailyDigest.error) :
                   !dailyDigest.data ? renderEmpty('Select a developer using the global filter to see their digest') :
                   (
                    <div className="digest-detail">
                      <div className="digest-stats-row">
                        <div className="digest-stat-card critical">
                          <span className="stat-number">{dailyDigest.data.summary?.blockers || 0}</span>
                          <span className="stat-text">Blockers</span>
                        </div>
                        <div className="digest-stat-card warning">
                          <span className="stat-number">{dailyDigest.data.summary?.escalations || 0}</span>
                          <span className="stat-text">Escalations</span>
                        </div>
                        <div className="digest-stat-card info">
                          <span className="stat-number">{dailyDigest.data.summary?.bugs || 0}</span>
                          <span className="stat-text">Bugs</span>
                        </div>
                        <div className="digest-stat-card">
                          <span className="stat-number">{dailyDigest.data.summary?.prs_to_review || 0}</span>
                          <span className="stat-text">PRs to Review</span>
                        </div>
                        <div className="digest-stat-card">
                          <span className="stat-number">{dailyDigest.data.summary?.stories || 0}</span>
                          <span className="stat-text">Stories</span>
                        </div>
                      </div>

                      {dailyDigest.data.action_items?.length > 0 && (
                        <div className="action-items-list">
                          <h4>Priority Actions</h4>
                          {dailyDigest.data.action_items.map((item, idx) => (
                            <div key={idx} className={`action-item urgency-${item.urgency}`}>
                              <span className="action-number">{idx + 1}</span>
                              <span className={`urgency-dot ${item.urgency}`}></span>
                              <span className="action-text">{item.action}</span>
                              <span className={`action-category ${item.category}`}>{item.category.replace('_', ' ')}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {dailyDigest.data.prs_to_review?.length > 0 && (
                        <div className="digest-sub-section">
                          <h4><GitPullRequest size={14} /> PRs Awaiting Review</h4>
                          {dailyDigest.data.prs_to_review.map((pr, idx) => (
                            <div key={idx} className="digest-sub-item">
                              <a href={pr.url} target="_blank" rel="noopener noreferrer" className="item-key">
                                #{pr.number} <ExternalLink size={10} />
                              </a>
                              <span className="sub-item-text">{pr.title}</span>
                              <span className="sub-item-meta">{pr.repo} &middot; {pr.age_days}d old</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Workload Anomaly Panel */}
          <div className="digest-panel ai-panel">
            <div className="panel-header" onClick={() => toggleSection('workload')}>
              <div className="panel-title">
                {expandedSections.workload ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <Activity size={18} className="panel-icon workload-icon" />
                <h3>Workload Analysis</h3>
                {workloadAnomalies.data?.summary && (
                  <span className="panel-count">
                    {workloadAnomalies.data.summary.overloaded_count} overloaded
                  </span>
                )}
              </div>
              <span className="panel-source ai-badge">AI Agent</span>
            </div>
            {expandedSections.workload && (
              <div className="panel-content">
                {workloadAnomalies.loading ? renderLoading() :
                 workloadAnomalies.error ? renderError(workloadAnomalies.error) :
                 !workloadAnomalies.data ? renderEmpty('Click AI Insights tab to load') :
                 (
                  <div className="workload-detail">
                    <div className="workload-summary-bar">
                      <span className="ws-item">
                        <strong>{workloadAnomalies.data.summary?.total_developers || 0}</strong> developers
                      </span>
                      <span className="ws-item ws-mean">
                        Avg score: <strong>{workloadAnomalies.data.summary?.mean_workload || 0}</strong>
                      </span>
                    </div>

                    {workloadAnomalies.data.overloaded?.length > 0 && (
                      <div className="workload-section">
                        <h4><TrendingUp size={14} className="text-danger" /> Overloaded</h4>
                        {workloadAnomalies.data.overloaded.map((dev, idx) => (
                          <div key={idx} className="workload-dev-card overloaded">
                            <div className="dev-card-header">
                              <User size={14} />
                              <strong>{dev.developer}</strong>
                              <span className="workload-score">{dev.workload_score}</span>
                            </div>
                            <div className="dev-card-items">
                              {dev.items?.blockers > 0 && <span className="wl-tag critical">{dev.items.blockers} blockers</span>}
                              {dev.items?.escalations > 0 && <span className="wl-tag warning">{dev.items.escalations} escalations</span>}
                              {dev.items?.bugs > 0 && <span className="wl-tag info">{dev.items.bugs} bugs</span>}
                              {dev.items?.pr_reviews > 0 && <span className="wl-tag">{dev.items.pr_reviews} reviews</span>}
                              {dev.items?.stories > 0 && <span className="wl-tag">{dev.items.stories} stories</span>}
                            </div>
                            {dev.recommendation && (
                              <div className="dev-card-rec">{dev.recommendation}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {workloadAnomalies.data.underutilized?.length > 0 && (
                      <div className="workload-section">
                        <h4><TrendingDown size={14} className="text-success" /> Available Capacity</h4>
                        {workloadAnomalies.data.underutilized.map((dev, idx) => (
                          <div key={idx} className="workload-dev-card underutilized">
                            <div className="dev-card-header">
                              <User size={14} />
                              <strong>{dev.developer}</strong>
                              <span className="workload-score">{dev.workload_score}</span>
                            </div>
                            {dev.recommendation && (
                              <div className="dev-card-rec">{dev.recommendation}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Knowledge Gap Panel */}
          <div className="digest-panel ai-panel">
            <div className="panel-header" onClick={() => toggleSection('knowledgeGaps')}>
              <div className="panel-title">
                {expandedSections.knowledgeGaps ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <BookOpen size={18} className="panel-icon knowledge-icon" />
                <h3>Knowledge Gaps</h3>
                {knowledgeGaps.data?.summary && (
                  <span className="panel-count">
                    {knowledgeGaps.data.summary.bus_factor_score != null 
                      ? `Score: ${knowledgeGaps.data.summary.bus_factor_score}/100`
                      : 'Insufficient data'}
                  </span>
                )}
              </div>
              <span className="panel-source ai-badge">AI Agent</span>
            </div>
            {expandedSections.knowledgeGaps && (
              <div className="panel-content">
                {knowledgeGaps.loading ? renderLoading() :
                 knowledgeGaps.error ? renderError(knowledgeGaps.error) :
                 !knowledgeGaps.data ? renderEmpty('Click AI Insights tab to load') :
                 (
                  <div className="knowledge-detail">
                    <div className="bus-factor-gauge">
                      <div className="gauge-bar">
                        <div 
                          className={`gauge-fill ${
                            knowledgeGaps.data.summary.bus_factor_score == null ? 'neutral' :
                            knowledgeGaps.data.summary.bus_factor_score >= 75 ? 'good' : 
                            knowledgeGaps.data.summary.bus_factor_score >= 50 ? 'warning' : 'danger'
                          }`}
                          style={{ width: `${knowledgeGaps.data.summary.bus_factor_score ?? 0}%` }}
                        ></div>
                      </div>
                      <div className="gauge-labels">
                        <span className="gauge-stat danger">{knowledgeGaps.data.summary.high_risk_count} high risk</span>
                        <span className="gauge-stat warning">{knowledgeGaps.data.summary.medium_risk_count} medium</span>
                        <span className="gauge-stat info">{knowledgeGaps.data.summary.low_risk_count} low</span>
                      </div>
                    </div>

                    {knowledgeGaps.data.high_risk?.length > 0 && (
                      <div className="risk-section">
                        <h4>High Risk — Single-Person Dependencies</h4>
                        {knowledgeGaps.data.high_risk.slice(0, 8).map((item, idx) => (
                          <div key={idx} className="risk-item high">
                            <div className="risk-item-header">
                              <span className="risk-area">{item.area}</span>
                              <span className="risk-share">{item.top_contributor_share}%</span>
                            </div>
                            <div className="risk-item-detail">
                              <User size={12} /> <strong>{item.top_contributor}</strong> — {item.total_items} items
                            </div>
                            {item.recommendation && (
                              <div className="risk-rec">{item.recommendation}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {knowledgeGaps.data.medium_risk?.length > 0 && (
                      <div className="risk-section">
                        <h4>Medium Risk — High Concentration</h4>
                        {knowledgeGaps.data.medium_risk.slice(0, 5).map((item, idx) => (
                          <div key={idx} className="risk-item medium">
                            <div className="risk-item-header">
                              <span className="risk-area">{item.area}</span>
                              <span className="risk-share">{item.top_contributor_share}%</span>
                            </div>
                            <div className="risk-item-detail">
                              <User size={12} /> <strong>{item.top_contributor}</strong> — {item.reason}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {knowledgeGaps.data.recommendations?.length > 0 && (
                      <div className="risk-section">
                        <h4>Recommendations</h4>
                        {knowledgeGaps.data.recommendations.slice(0, 5).map((rec, idx) => (
                          <div key={idx} className="rec-item">
                            <span className={`rec-priority ${rec.priority}`}>{rec.priority}</span>
                            <span className="rec-text">{rec.action}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Cross-Concern Links Panel */}
          <div className="digest-panel digest-panel-wide ai-panel">
            <div className="panel-header" onClick={() => toggleSection('crossLinks')}>
              <div className="panel-title">
                {expandedSections.crossLinks ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <Link2 size={18} className="panel-icon links-icon" />
                <h3>Cross-Concern Links</h3>
                {crossConcernLinks.data?.summary && (
                  <span className="panel-count">
                    {crossConcernLinks.data.summary.total_links_found} links found
                  </span>
                )}
              </div>
              <span className="panel-source ai-badge">AI Agent</span>
            </div>
            {expandedSections.crossLinks && (
              <div className="panel-content">
                {crossConcernLinks.loading ? renderLoading() :
                 crossConcernLinks.error ? renderError(crossConcernLinks.error) :
                 !crossConcernLinks.data ? renderEmpty('Click AI Insights tab to load') :
                 (
                  <div className="cross-links-detail">
                    {/* Summary badges */}
                    <div className="links-summary">
                      <span className="link-badge esc-pr">
                        <Network size={12} /> {crossConcernLinks.data.summary?.escalation_pr_links || 0} Escalation↔PR
                      </span>
                      <span className="link-badge bug-pr">
                        <Link2 size={12} /> {crossConcernLinks.data.summary?.bug_pr_links || 0} Bug↔PR
                      </span>
                      <span className="link-badge clusters">
                        <Activity size={12} /> {crossConcernLinks.data.summary?.component_clusters || 0} Component Hotspots
                      </span>
                    </div>

                    {/* Escalation-PR Links */}
                    {crossConcernLinks.data.links?.filter(l => l.type === 'escalation_pr').length > 0 && (
                      <div className="links-section">
                        <h4><AlertTriangle size={14} /> Escalation → PR Links</h4>
                        {crossConcernLinks.data.links.filter(l => l.type === 'escalation_pr').slice(0, 8).map((link, idx) => (
                          <div key={idx} className="link-item escalation-link">
                            <div className="link-source">
                              <span className="link-key">{link.source?.key}</span>
                              <span className="link-summary">{link.source?.summary?.substring(0, 60)}</span>
                            </div>
                            <span className="link-arrow">→</span>
                            <div className="link-target">
                              <a href={link.target?.url} target="_blank" rel="noopener noreferrer" className="link-pr">
                                PR #{link.target?.number} <ExternalLink size={10} />
                              </a>
                              <span className="link-repo">{link.target?.repo}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Component Clusters */}
                    {crossConcernLinks.data.component_clusters?.length > 0 && (
                      <div className="links-section">
                        <h4><Activity size={14} /> Component Hotspots</h4>
                        {crossConcernLinks.data.component_clusters.slice(0, 5).map((cluster, idx) => (
                          <div key={idx} className="cluster-item">
                            <div className="cluster-header">
                              <span className="cluster-name">{cluster.component}</span>
                              <span className="cluster-count">{cluster.bug_count} bugs</span>
                            </div>
                            <div className="cluster-assignees">
                              {cluster.assignees?.slice(0, 4).map((a, i) => (
                                <span key={i} className="cluster-assignee"><User size={10} /> {a}</span>
                              ))}
                            </div>
                            <div className="cluster-insight">{cluster.insight}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Insights */}
                    {crossConcernLinks.data.insights?.length > 0 && (
                      <div className="links-section insights-section">
                        <h4><Brain size={14} /> Key Insights</h4>
                        {crossConcernLinks.data.insights.map((insight, idx) => (
                          <div key={idx} className="insight-item">
                            <Info size={12} />
                            <span>{insight}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default DevDigestSection;
