/**
 * API Service
 * Fetches data from the FastAPI backend which uses direct API clients
 * 
 * Data Flow:
 * React Frontend → API Service → FastAPI Backend → External APIs (TestRail, JIRA, Jenkins, etc.)
 */

// Use relative URL by default - works with:
// - Local dev: package.json "proxy" setting forwards /api/* to localhost:8000
// - Docker: nginx proxies /api/* to backend container
// - For VM deployment: set REACT_APP_API_URL=http://10.136.126.85:8000
const API_BASE_URL = process.env.REACT_APP_API_URL || '';

class ApiService {
  constructor() {
    this.baseUrl = API_BASE_URL;
    this.cache = new Map();
    this.cacheTTL = 60000; // 1 minute cache
  }

  /**
   * Make an API request with caching
   */
  async fetch(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const cacheKey = url + JSON.stringify(options);
    
    // Check cache
    const cached = this.cache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < this.cacheTTL) {
      return cached.data;
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      });

      if (!response.ok) {
        // Try to get detailed error message from response
        let errorMessage = `API error: ${response.status} ${response.statusText}`;
        try {
          const errorData = await response.json();
          if (response.status === 401 && errorData.detail) {
            // Handle JIRA auth errors specially
            const detail = errorData.detail;
            if (typeof detail === 'object' && detail.error === 'jira_auth_error') {
              errorMessage = `⚠️ JIRA Authentication Failed: ${detail.message}. ${detail.action || ''}`;
            } else if (typeof detail === 'string') {
              errorMessage = detail;
            }
          } else if (errorData.detail) {
            errorMessage = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
          }
        } catch {
          // Ignore JSON parse errors
        }
        const error = new Error(errorMessage);
        error.status = response.status;
        throw error;
      }

      const data = await response.json();
      
      // Cache the response
      this.cache.set(cacheKey, { data, timestamp: Date.now() });
      
      return data;
    } catch (error) {
      throw error;
    }
  }

  /**
   * Clear cache (useful after mutations)
   */
  clearCache() {
    this.cache.clear();
  }

  // ============ TestRail MCP Agent Endpoints ============

  // ============ JIRA MCP Agent Endpoints ============

  /**
   * Get Release Readiness data
   * Tracks stories and bugs across release phases (Branch Cut, Final Build)
   */
  async getReleaseReadiness(release, refresh = false) {
    return this.fetch(`/api/jira/release-readiness?release=${release}&refresh=${refresh}`);
  }

  // ============ Centralized Release Data Endpoints ============
  // These endpoints use a single JQL query and apply filters server-side.
  // All data is cached for 2 minutes for optimal performance.

  /**
   * Get all release data using centralized service
   * Single JQL query, includes all items and pre-calculated summary
   */
  async getReleaseData(release, refresh = false) {
    return this.fetch(`/api/jira/release-data?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get release summary (counts only, lighter endpoint)
   * Ideal for Overview tiles that only need counts
   */
  async getReleaseSummary(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/summary?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get release data grouped by assignee
   */
  async getReleaseDataByAssignee(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/by-assignee?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get blocker/critical items for a release
   */
  async getReleaseBlockers(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/blockers?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get items in Code Review status
   */
  async getReleaseCodeReview(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/code-review?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get release data grouped by status
   */
  async getReleaseDataByStatus(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/by-status?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get release data grouped by priority
   */
  async getReleaseDataByPriority(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/by-priority?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get release readiness metrics (health score, status, recommendation)
   * Ideal for Overview tiles that need quick status indicators
   */
  async getReleaseMetrics(release, refresh = false) {
    return this.fetch(`/api/jira/release-data/metrics?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get items moved out of a release after IRR date
   * Tracks bugs/stories that had their fixVersion changed to another release
   */
  async getItemsMovedOut(release, refresh = false) {
    return this.fetch(`/api/jira/items-moved-out?release=${release}&refresh=${refresh}`);
  }

  /**
   * Get NPLANs/Features planned for a release
   * Fetches from WEEKLY STATUS REPORT Google Sheet
   * @param {string} release - Release version (e.g., "135", "R135")
   */
  async getNplans(release) {
    return this.fetch(`/api/jira/nplans?release=${release}`);
  }

  /**
   * Get bugs linked to NPLANs for a release
   * Fetches bugs from JIRA with labels matching NPLAN IDs (e.g., nplan-5417)
   * @param {string} release - Release version (e.g., "135", "R135")
   * @param {boolean} includeClosed - Whether to include closed bugs (default: true)
   */
  async getNplanBugs(release, includeClosed = true) {
    return this.fetch(`/api/jira/nplan-bugs?release=${release}&include_closed=${includeClosed}`);
  }

  /**
   * Get PR/merge status for sub-tickets under NPLANs
   */
  async getNplanDevStatus(release) {
    return this.fetch(`/api/jira/nplan-dev-status?release=${release}`);
  }

  async getFeatureInsights(refresh = false) {
    if (refresh) {
      return this.fetch('/api/jira/feature-insights?refresh=true');
    }
    return this.fetch('/api/jira/feature-insights');
  }

  /**
   * Get IRR milestone tracking data
   * Shows stories unresolved by IRR date for release quality tracking
   */
  async getIRRMilestoneData(release) {
    return this.fetch(`/api/jira/milestone/irr?release=${release}`);
  }

  /**
   * Get Branch Cut milestone tracking data
   */
  async getBranchCutMilestoneData(release) {
    return this.fetch(`/api/jira/milestone/branch-cut?release=${release}`);
  }

  /**
   * Get Final Build milestone tracking data
   */
  async getFinalBuildMilestoneData(release) {
    return this.fetch(`/api/jira/milestone/final-build?release=${release}`);
  }

  /**
   * Get day-wise resolution progress from IRR to Final Build
   * Shows cumulative bugs and stories resolved per day for progress tracking
   */
  async getResolutionProgress(release) {
    return this.fetch(`/api/jira/resolution-progress?release=${release}`);
  }

  /**
   * Get deployment day milestone tracking data
   * @param {string} release - Release ID
   * @param {number} day - Deployment day (1-4)
   */
  async getDeploymentMilestoneData(release, day) {
    return this.fetch(`/api/jira/milestone/deployment?release=${release}&day=${day}`);
  }

  // ============ GitHub Commit Tracking Endpoints ============

  /**
   * Get commits after branch cut from all configured repos
   */
  async getCommitsAfterBranchCut(release) {
    return this.fetch(`/api/github/commits?release=${release}`);
  }

  /**
   * Analyze a single commit for test impact and semantic understanding
   * @param {string} owner - Repository owner (e.g., 'your-org')
   * @param {string} repo - Repository name
   * @param {string} sha - Commit SHA (full or short)
   * @param {boolean} includeLlm - Whether to include LLM analysis (default: true)
   */
  async analyzeCommit(owner, repo, sha, includeLlm = true) {
    return this.fetch(`/api/github/commit-analysis?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&sha=${encodeURIComponent(sha)}&include_llm=${includeLlm}`);
  }

  /**
   * Analyze a pull request by number (owner/repo/pr_number)
   */
  async analyzePr(owner, repo, prNumber, includeLlm = true) {
    return this.fetch(`/api/github/pr-analysis?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&pr_number=${encodeURIComponent(prNumber)}&include_llm=${includeLlm}`);
  }

  /**
   * Analyze a PR using multi-agent system (escalation_analysis_agent)
   * Returns categorized recommendations: MUST RUN, SHOULD RUN, MANUAL QA, TEST GAPS
   */
  async analyzePrWithAgents(owner, repo, prNumber, ticketKey = null, sessionId = 'escalation-analysis') {
    const body = { owner, repo, pr_number: prNumber, session_id: sessionId };
    if (ticketKey) body.ticket_key = ticketKey;
    return this.fetch('/api/agents/analyze-pr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  /**
   * Analyze ALL PRs for a JIRA ticket using multi-agent system
   * Fetches JIRA context (description, components, comments) and all linked PRs
   * Returns combined analysis across all PRs
   */
  async analyzeTicketWithAgents(ticketKey, sessionId = 'escalation-analysis') {
    return this.fetch('/api/agents/analyze-ticket', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_key: ticketKey, session_id: sessionId }),
    });
  }

  /**
   * Get FAISS index status (TestRail + Repo + Test Code indexes)
   */
  async getIndexStatus() {
    return this.fetch('/api/index/status');
  }

  /**
   * Trigger TestRail test case re-indexing
   */
  async reindexTestrail(milestoneId = 5319, projectId = 38) {
    return this.fetch(`/api/index/testrail/reindex?milestone_id=${milestoneId}&project_id=${projectId}`, { method: 'POST' });
  }

  /**
   * Trigger GitHub repo re-indexing
   */
  async reindexRepo(owner = 'your-org', repo = 'client', branch = 'main') {
    return this.fetch(`/api/index/repo/reindex?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`, { method: 'POST' });
  }

  /**
   * Trigger QE test code re-indexing (your-company-qe/your-product-tests)
   * Indexes test_*.py docstrings to supplement TestRail case descriptions
   */
  async reindexTestCode(owner = 'your-company-qe', repo = 'your-product-tests', branch = 'main') {
    return this.fetch(`/api/index/testcode/reindex?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`, { method: 'POST' });
  }

  /**
   * Check commit analysis backend status
   */
  async getCommitAnalysisStatus() {
    return this.fetch('/api/github/commit-analysis/status');
  }

  // ============ Escalation Analysis Endpoints ============

  /**
   * Get available releases with escalation data
   */
  async getEscalationReleases() {
    return this.fetch('/api/escalation-analysis/releases');
  }

  /**
   * Get escalation tickets for a release
   */
  async getEscalationTickets(releaseId) {
    return this.fetch(`/api/escalation-analysis/tickets/${encodeURIComponent(releaseId)}`);
  }

  /**
   * Get ALL escalation tickets across all releases
   */
  async getAllEscalationTickets() {
    return this.fetch('/api/escalation-analysis/all-tickets');
  }

  /**
   * Get quick summary for a release (no AI)
   */
  async getEscalationSummary(releaseId) {
    return this.fetch(`/api/escalation-analysis/summary/${encodeURIComponent(releaseId)}`);
  }

  /**
   * Get summary for ALL escalations across all releases
   */
  async getAllEscalationsSummary() {
    return this.fetch('/api/escalation-analysis/all-summary');
  }

  /**
   * Run full AI analysis for a release
   */
  async analyzeEscalations(releaseId, includeAi = true) {
    return this.fetch(`/api/escalation-analysis/analyze/${encodeURIComponent(releaseId)}?include_ai=${includeAi}`);
  }

  /**
   * Get full details for a single escalation ticket (linked issues, PRs, description)
   */
  async getEscalationTicketDetails(ticketKey) {
    return this.fetch(`/api/escalation-analysis/ticket-details/${encodeURIComponent(ticketKey)}`);
  }

  /**
   * Analyze impacted areas for a single escalation ticket
   * Returns impacted features/components and recommended test areas
   */
  async analyzeTicketImpact(ticketKey) {
    return this.fetch(`/api/escalation-analysis/ticket/${encodeURIComponent(ticketKey)}/impact`);
  }

  /**
   * Fetch PR counts for a batch of tickets (background loading)
   * Returns { pr_counts: { ticketKey: count, ... } }
   */
  async getTicketPrCounts(ticketKeys) {
    return this.fetch('/api/escalation-analysis/ticket-pr-counts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ticketKeys),
    });
  }

  /**
   * Get escalation trends over time (by month and component)
   * Returns { data: { months, components, series, totals } }
   */
  async getEscalationTrends(months = 12) {
    return this.fetch(`/api/escalation-analysis/trends?months=${months}`);
  }

  /**
   * Get AI-analyzed impacted features for all tickets from cache
   * Returns { ticket_features: { [ticket_key]: { impacted_features, analyzed_at, ... } } }
   */
  async getTicketFeatures() {
    return this.fetch('/api/escalation-analysis/ticket-features');
  }

  /**
   * Get AI-generated summary for a recurring escalation pattern.
   * @param {string} customer - Customer name
   * @param {string} component - Component/feature name
   * @param {string[]} ticketKeys - Array of ticket keys in this pattern
   * @returns {Object} AI summary with root cause, themes, and recommendation
   */
  async summarizeEscalationPattern(customer, component, ticketKeys) {
    const params = new URLSearchParams({
      customer,
      component,
      ticket_keys: ticketKeys.join(','),
    });
    return this.fetch(`/api/escalation-analysis/summarize-pattern?${params}`, {
      method: 'POST',
    });
  }

  // ============ Google Sheets MCP Agent Endpoints ============

  // ============ Documentation Updates Endpoints ============

  /**
   * Get available releases that have bugs needing documentation updates
   */
  async getDocsUpdateReleases() {
    return this.fetch('/api/docs-updates/releases');
  }

  /**
   * Get bugs needing documentation updates for a specific release
   */
  async getDocsUpdateBugs(affectedVersion) {
    return this.fetch(`/api/docs-updates/bugs?affected_version=${encodeURIComponent(affectedVersion)}`);
  }

  /**
   * Get summary statistics for documentation updates
   */
  async getDocsUpdateSummary(affectedVersion = null) {
    const url = affectedVersion
      ? `/api/docs-updates/summary?affected_version=${encodeURIComponent(affectedVersion)}`
      : '/api/docs-updates/summary';
    return this.fetch(url);
  }

  /**
   * Refresh the docs update cache
   */
  async refreshDocsUpdateCache() {
    return this.fetch('/api/docs-updates/refresh', { method: 'POST' });
  }

  /**
   * Get available releases that have NPLANs needing documentation updates
   */
  async getDocsUpdateNplanReleases() {
    return this.fetch('/api/docs-updates/nplan-releases');
  }

  /**
   * Get NPLANs needing documentation updates for a specific release
   * @param {string} release - Release number like "R135", "135", or full value like "26-Q1-Mar-R135"
   */
  async getDocsUpdateNplans(release) {
    return this.fetch(`/api/docs-updates/nplans?release=${encodeURIComponent(release)}`);
  }

  /**
   * Get documentation funnel statistics for a specific release
   * Tracks NPLANs through: Needs Docs → Writer Assigned → TOI Scheduled → Draft Complete → Published
   * @param {string} release - Release number like "R135"
   */
  async getDocsUpdateFunnel(release) {
    return this.fetch(`/api/docs-updates/funnel?release=${encodeURIComponent(release)}`);
  }

  // ============ Jenkins Endpoints ============

  /**
   * Get Jenkins pipeline status
   */
  async getPipelines() {
    return this.fetch('/api/jenkins/pipelines');
  }

  // ============ Releases ============

  /**
   * Get available releases
   */
  async getReleases() {
    return this.fetch('/api/releases');
  }

  // ============ Health Check ============

  /**
   * Check API health and agent status
   */
  async healthCheck() {
    return this.fetch('/api/health');
  }

  // ============ Release Calendar Endpoints ============

  /**
   * Get all releases with milestone dates from PDF
   */
  async getReleaseCalendar() {
    return this.fetch('/api/release-calendar/releases');
  }

  /**
   * Get a specific release by name
   * @param {string} releaseName - Release name (e.g., R133.0)
   */
  async getReleaseByName(releaseName) {
    return this.fetch(`/api/release-calendar/releases/${releaseName}`);
  }

  /**
   * Get release calendar summary
   */
  async getReleaseCalendarSummary() {
    return this.fetch('/api/release-calendar/summary');
  }

  /**
   * Get milestone definitions
   */
  async getReleaseMilestones() {
    return this.fetch('/api/release-calendar/milestones');
  }

  /**
   * Filter releases by type, status, or search
   * @param {object} filters - Filter options
   */
  async filterReleaseCalendar(filters = {}) {
    const params = new URLSearchParams();
    if (filters.type) params.append('release_type', filters.type);
    if (filters.status) params.append('status', filters.status);
    if (filters.search) params.append('search', filters.search);
    return this.fetch(`/api/release-calendar/filter?${params.toString()}`);
  }

  // ============ On-Call Calendar Endpoints ============

  /**
   * Get all on-call schedules (Primary + Managers)
   * Returns data for both schedules in a unified format
   */
  async getAllOnCallSchedules() {
    return this.fetch('/api/on-call-calendar/schedules');
  }

  /**
   * Get on-call schedule for a specific type
   * @param {string} scheduleType - "primary" or "managers"
   */
  async getOnCallSchedule(scheduleType = 'primary') {
    return this.fetch(`/api/on-call-calendar/schedule?schedule_type=${scheduleType}`);
  }

  /**
   * Get current on-call for all schedules
   */
  async getCurrentOnCall() {
    return this.fetch('/api/on-call-calendar/current');
  }

  async getOnCallTeam() {
    return this.fetch('/api/on-call-calendar/team');
  }

  async getOnCallSummary() {
    return this.fetch('/api/on-call-calendar/summary');
  }

  // ============ Slack Notifications ============

  /**
   * Get Slack notification configuration status
   */
  async getSlackStatus() {
    return this.fetch('/api/slack/status');
  }

  /**
   * Send release readiness notification to Slack
   * @param {string} release - Release ID
   */
  async sendSlackNotification(release) {
    return this.fetch('/api/slack/notify', {
      method: 'POST',
      body: JSON.stringify({ release }),
    });
  }

  // ============ PDV (Post-Deployment Validation) ============

  /**
   * Get PDV status for deployment milestones from Insights Platform
   * @param {string} releaseId - Release ID (e.g., "R135", "R136")
   * @returns {Promise<Object>} Milestone status for Day 1-4 deployments
   */
  async getPDVMilestoneStatus(releaseId) {
    return this.fetch(`/api/pdv/milestone-status/${releaseId}`);
  }

  /**
   * Get PDV status for a specific release version
   * @param {string} version - Release version (e.g., "135.0")
   * @returns {Promise<Object>} Full PDV status for all days
   */
  async getPDVReleaseStatus(version) {
    return this.fetch(`/api/pdv/release/${version}`);
  }

  /**
   * Get PDV status for a specific deployment day
   * @param {string} version - Release version (e.g., "135.0")
   * @param {string} day - Day label (e.g., "prod day 1", "staging")
   * @returns {Promise<Object>} Detailed PDV status for the day
   */
  async getPDVDayStatus(version, day) {
    return this.fetch(`/api/pdv/release/${version}/${encodeURIComponent(day)}`);
  }

  /**
   * Check PDV connection status
   * @returns {Promise<Object>} Connection status and token availability
   */
  async getPDVStatus() {
    return this.fetch('/api/pdv/status');
  }

  // ============ Stack Monitoring Endpoints ============

  /**
   * Get stack monitoring data with performance optimizations
   * @param {string} stacks - Comma-separated stack IDs (optional)
   * @param {boolean} refresh - Force refresh cached data
   * @param {boolean} lite - Use lite mode for faster initial load (skip events/restarts)
   * @param {boolean} useLocalCache - Return localStorage cached data immediately while fetching
   */
  async getStackMonitoring(stacks = null, refresh = false, lite = false, useLocalCache = true, onFreshData = null) {
    // Use separate cache keys for lite vs full data to avoid returning lite data for full requests
    const LOCAL_CACHE_KEY = lite ? 'stackMonitoring_cache_lite' : 'stackMonitoring_cache_full';
    const LOCAL_CACHE_TTL = 5 * 60 * 1000; // 5 minutes
    
    // Build endpoint with new parameters
    let endpoint = `/api/monitoring/stack?refresh=${refresh}&lite=${lite}&stale_ok=true`;
    if (stacks) endpoint += `&stacks=${stacks}`;
    
    // Try to return localStorage cached data for instant display
    // Only use cache for lite mode to avoid showing stale data without restarts
    if (useLocalCache && !refresh && lite) {
      try {
        const cached = localStorage.getItem(LOCAL_CACHE_KEY);
        if (cached) {
          const { data, timestamp } = JSON.parse(cached);
          const age = Date.now() - timestamp;
          
          // If cache is fresh (less than 5 min), return it immediately
          if (age < LOCAL_CACHE_TTL) {
            // Fetch fresh data in background (non-blocking)
            // and call onFreshData callback to update UI when ready
            this.fetch(endpoint).then(freshData => {
              localStorage.setItem(LOCAL_CACHE_KEY, JSON.stringify({
                data: freshData,
                timestamp: Date.now()
              }));
              // Call callback to update UI with fresh data
              if (onFreshData && typeof onFreshData === 'function') {
                onFreshData(freshData);
              }
            }).catch((err) => {
              console.warn('Background fetch failed:', err);
            });
            
            return { ...data, fromLocalCache: true, cacheAge: Math.round(age / 1000) };
          }
        }
      } catch (e) {
        // Ignore localStorage errors
        console.warn('LocalStorage cache read error:', e);
      }
    }
    
    // Fetch from API
    const data = await this.fetch(endpoint);
    
    // Save to localStorage for next time
    try {
      localStorage.setItem(LOCAL_CACHE_KEY, JSON.stringify({
        data,
        timestamp: Date.now()
      }));
    } catch (e) {
      console.warn('LocalStorage cache write error:', e);
    }
    
    return data;
  }

  /**
   * Get detailed deployment information for side panel
   * @param {string} namespace - Kubernetes namespace (full namespace like stg01-mp--addonman)
   * @param {string} deployment - Deployment name
   * @param {string} stack - Stack identifier
   * @param {boolean} lite - If true, skip metrics/events for faster loading
   */
  async getDeploymentDetails(namespace, deployment, stack, lite = false) {
    const params = new URLSearchParams({
      namespace,
      deployment,
      stack,
      lite: lite.toString()
    });
    return this.fetch(`/api/monitoring/stack/details?${params.toString()}`);
  }

  /**
   * Get pod logs preview
   * @param {string} namespace - Kubernetes namespace
   * @param {string} pod - Pod name
   * @param {string} stack - Stack identifier
   * @param {string} container - Container name (optional)
   * @param {number} lines - Number of lines to fetch (default 50)
   */
  async getPodLogs(namespace, pod, stack, container = null, lines = 50) {
    const params = new URLSearchParams({
      namespace,
      pod,
      stack,
      lines: lines.toString()
    });
    if (container) params.append('container', container);
    return this.fetch(`/api/monitoring/stack/logs?${params.toString()}`);
  }

  /**
   * Get historical stack monitoring data for trends
   * @param {number} hours - Hours of history to retrieve (default 24)
   */
  async getStackHistory(hours = 24) {
    return this.fetch(`/api/monitoring/stack/history?hours=${hours}`);
  }

  /**
   * Get restart timeline for a specific deployment
   * Shows when restarts started, last increased, and if they're ongoing
   * @param {string} namespace - Namespace key (e.g., '--addonman')
   * @param {string} deployment - Deployment name
   * @param {string} stack - Stack identifier (e.g., 'stg01')
   */
  async getRestartTimeline(namespace, deployment, stack) {
    const params = new URLSearchParams({ namespace, deployment, stack });
    return this.fetch(`/api/monitoring/stack/restart-timeline?${params.toString()}`);
  }

  /**
   * Get historical data for a specific deployment on a specific stack
   * @param {string} namespace - Namespace key (e.g., '--provisioner-pycore')
   * @param {string} deployment - Deployment name
   * @param {string} stack - Stack identifier (e.g., 'am2')
   * @param {number} hours - Hours of history to retrieve (default 24)
   */
  async getDeploymentHistory(namespace, deployment, stack, hours = 24) {
    const params = new URLSearchParams({ namespace, deployment, stack, hours: hours.toString() });
    return this.fetch(`/api/monitoring/stack/deployment-history?${params.toString()}`);
  }

  /**
   * Get logs from a deployment by automatically finding its pods
   * Useful for viewing error logs directly from issue panels
   * @param {string} namespace - Kubernetes namespace
   * @param {string} deployment - Deployment name  
   * @param {string} stack - Stack identifier (e.g., 'stg01')
   * @param {number} lines - Number of lines per pod (default 50)
   */
  async getDeploymentLogs(namespace, deployment, stack, lines = 50) {
    const params = new URLSearchParams({ namespace, deployment, stack, lines: lines.toString() });
    return this.fetch(`/api/monitoring/stack/deployment-logs?${params.toString()}`);
  }

  /**
   * Manually trigger a snapshot save
   */
  async createStackSnapshot() {
    return this.fetch('/api/monitoring/stack/snapshot', { method: 'POST' });
  }

  /**
   * Get prioritized stack issues for quick dashboard view
   * Returns only problematic deployments, sorted by severity
   * @param {string} severity - Filter by severity level (critical, high, medium, low)
   * @param {number} limit - Maximum issues to return (default 50)
   */
  async getStackIssues(severity = null, limit = 50) {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (severity) params.append('severity', severity);
    return this.fetch(`/api/monitoring/stack/issues?${params.toString()}`);
  }

  /**
   * Get release version compliance alerts
   * Checks if stacks have the expected version based on release milestones
   * 
   * Rules:
   * - Branch Cut reached → QA stacks should have that version
   * - Signoff STG reached → Staging stacks should have that version
   * - Deploy MP Pre PROD reached → Pre-Prod stacks should have that version
   * - Deploy Prod Day 1 reached → Prod stacks should have that version
   */
  async getReleaseCompliance() {
    return this.fetch('/api/monitoring/release-compliance');
  }

  /**
   * Send Slack alert for current stack monitoring issues
   * @param {string} severityFilter - Filter alerts by severity (critical, high, medium, low)
   * @param {string} channel - Override default Slack channel
   * @param {boolean} includeSummary - Include health summary in alert
   */
  async sendStackSlackAlert(severityFilter = null, channel = null, includeSummary = true) {
    const body = {
      include_summary: includeSummary
    };
    if (severityFilter) body.severity_filter = severityFilter;
    if (channel) body.channel = channel;
    
    return this.fetch('/api/monitoring/stack/alert', {
      method: 'POST',
      body: JSON.stringify(body)
    });
  }

  // ==================== Release Risk Prediction ====================

  /**
   * Get AI-powered risk prediction for a release
   * Returns probability, risk factors, and LLM-generated insights
   * @param {string} releaseId - Release ID (e.g., "R136")
   * @param {boolean} refresh - Force refresh of cached data
   */
  async getReleaseRisk(releaseId, refresh = false) {
    return this.fetch(`/api/release-risk/${releaseId}?refresh=${refresh}`);
  }

  /**
   * Get historical risk data for a release
   * Returns snapshots at different phases and outcome data
   * @param {string} releaseId - Release ID
   */
  async getReleaseRiskHistory(releaseId) {
    return this.fetch(`/api/release-risk/history/${releaseId}`);
  }

  /**
   * Save a risk snapshot for a release at a specific phase
   * @param {string} releaseId - Release ID
   * @param {string} phase - Milestone phase (e.g., "irr_minus_3", "branch_cut")
   * @param {boolean} force - Overwrite existing snapshot
   */
  async saveReleaseRiskSnapshot(releaseId, phase, force = false) {
    return this.fetch(`/api/release-risk/snapshot/${releaseId}?phase=${phase}&force=${force}`, {
      method: 'POST'
    });
  }

  /**
   * Record the final outcome of a release (for training future predictions)
   * @param {string} releaseId - Release ID
   * @param {Object} outcome - Outcome data (onTime, slipDays, blockersAtRelease, notes)
   */
  async recordReleaseOutcome(releaseId, outcome) {
    const params = new URLSearchParams({
      on_time: outcome.onTime.toString(),
      slip_days: (outcome.slipDays || 0).toString(),
      blockers_at_release: (outcome.blockersAtRelease || 0).toString(),
      notes: outcome.notes || ''
    });
    return this.fetch(`/api/release-risk/outcome/${releaseId}?${params.toString()}`, {
      method: 'POST'
    });
  }

  /**
   * Get risk predictor status (LLM availability, configuration)
   */
  async getReleaseRiskStatus() {
    return this.fetch('/api/release-risk/status');
  }

  /**
   * Get all releases with historical risk data
   */
  async getAllRiskReleases() {
    return this.fetch('/api/release-risk/releases/all');
  }

  // ==================== Dev Insights ====================

  async getKnowledgeGaps(release) {
    const params = release ? `?release=${release}` : '';
    return this.fetch(`/api/dev-insights/knowledge-gaps${params}`);
  }

  async getDailyDigest(developer, release) {
    const params = new URLSearchParams({ developer });
    if (release) params.append('release', release);
    return this.fetch(`/api/dev-insights/daily-digest?${params.toString()}`);
  }

  async getWorkloadAnomalies(release) {
    const params = release ? `?release=${release}` : '';
    return this.fetch(`/api/dev-insights/workload-anomalies${params}`);
  }

  async getCrossConcernLinks(release) {
    const params = release ? `?release=${release}` : '';
    return this.fetch(`/api/dev-insights/cross-concern-links${params}`);
  }

}

// Export singleton instance
const api = new ApiService();
export default api;

// Export class for testing
export { ApiService };
