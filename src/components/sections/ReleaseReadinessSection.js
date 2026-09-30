/**
 * ReleaseReadinessSection - ReleaseReadiness Dashboard
 * 
 * Single-page dashboard for Dev, QA, and Leadership to track release status.
 * All data visible with collapsible sections - no tabs needed.
 */
import React, { useState, useEffect, useMemo } from 'react';
import {
  CheckSquare,
  AlertTriangle,
  Clock,
  RefreshCw,
  ExternalLink,
  Bug,
  BookOpen,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  User,
  Zap,
  Target,
  Package,
  Activity,
  TrendingUp,
  TrendingDown,
  Minus,
  Calendar,
  Users,
  GitPullRequest,
  Pause,
  ArrowRight,
  Info,
  BarChart3,
  Send,
  MessageSquare,
  FileText,
  Search,
  FileCode,
  Folder,
  X,
  Loader,
  Maximize2,
  Filter,
  ArrowUpDown
} from 'lucide-react';
import { DEFAULT_RELEASE } from '../../config';
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  ReferenceLine
} from 'recharts';
import api from '../../services/api';
import './ReleaseReadinessSection.css';
import '../../styles/analysis.css';

const ReleaseReadinessSection = ({ selectedRelease = DEFAULT_RELEASE }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedComponent, setSelectedComponent] = useState('YOUR_PRODUCT');
  const [selectedMilestone, setSelectedMilestone] = useState('all');
  
  // Milestone-specific data
  const [milestoneData, setMilestoneData] = useState(null);
  const [milestoneLoading, setMilestoneLoading] = useState(false);
  const [milestoneError, setMilestoneError] = useState(null);
  
  // Code commits data - always fetched
  const [commitsData, setCommitsData] = useState(null);
  const [commitsLoading, setCommitsLoading] = useState(false);
  const [expandedRepos, setExpandedRepos] = useState({});
  
  // Resolution progress data - for day-wise chart
  const [resolutionProgressData, setResolutionProgressData] = useState(null);
  const [resolutionProgressLoading, setResolutionProgressLoading] = useState(false);
  
  // PDV (Post-Deployment Validation) data - from Insights Platform
  const [pdvData, setPdvData] = useState(null);
  const [pdvLoading, setPdvLoading] = useState(false);
  const [pdvError, setPdvError] = useState(null);
  const [pdvCache, setPdvCache] = useState({});  // Cache PDV data by release
  const [pdvCollapsed, setPdvCollapsed] = useState({});  // Track collapsed state for each component group
  
  // Items moved out of release data
  const [itemsMovedOutData, setItemsMovedOutData] = useState(null);
  const [itemsMovedOutLoading, setItemsMovedOutLoading] = useState(false);
  const [itemsMovedOutError, setItemsMovedOutError] = useState(null);
  
  // NPLANs data - Features planned for release
  const [nplansData, setNplansData] = useState(null);
  const [nplansLoading, setNplansLoading] = useState(false);
  const [nplansError, setNplansError] = useState(null);
  
  // NPLAN Bugs data - Bugs linked to NPLANs via labels
  const [nplanBugsData, setNplanBugsData] = useState(null);
  const [nplanBugsLoading, setNplanBugsLoading] = useState(false);
  const [nplanBugsError, setNplanBugsError] = useState(null);
  const [expandedNplanBugs, setExpandedNplanBugs] = useState({}); // Track which NPLAN rows are expanded

  // NPLAN Dev Status (PR merge status)
  const [nplanDevStatusData, setNplanDevStatusData] = useState(null);
  const [nplanDevStatusLoading, setNplanDevStatusLoading] = useState(false);

  // Commit analysis state
  const [commitAnalysis, setCommitAnalysis] = useState(null);
  const [commitAnalysisLoading, setCommitAnalysisLoading] = useState(false);
  const [commitAnalysisError, setCommitAnalysisError] = useState(null);
  const [selectedCommitForAnalysis, setSelectedCommitForAnalysis] = useState(null);
  
  // Slack notification state
  const [slackSending, setSlackSending] = useState(false);
  const [slackStatus, setSlackStatus] = useState(null); // 'success', 'error', or null
  
  // All sections collapsible - Runway style
  const [expandedSections, setExpandedSections] = useState({
    timeline: false,      // Timeline hidden by default (View Timeline button)
    actionItems: false,   // Action items hidden by default - opens on "Some items need attention" click
    pending: true,        // Pending items visible by default
    awaitingQA: true,     // Awaiting QA visible by default
    trends: false,        // Trends collapsed by default
    ownership: false,     // Ownership collapsed
    milestoneDetail: true, // Milestone detail expanded by default when selected
    codeCommits: true,    // Code commits visible by default for leads
    nplans: true          // NPLANs expanded by default
  });
  
  const [expandedAssignees, setExpandedAssignees] = useState({});
  const [expandedMilestoneComponents, setExpandedMilestoneComponents] = useState({});
  const [expandedStatBox, setExpandedStatBox] = useState(null); // 'missed', 'open', or null
  const [showAllItems, setShowAllItems] = useState({}); // Track which action items show all
  const [milestonePanelCollapsed, setMilestonePanelCollapsed] = useState(false);
  const [hoveredTrendTile, setHoveredTrendTile] = useState(null); // Track which trend tile is hovered
  const [expandedWorkloadAssignee, setExpandedWorkloadAssignee] = useState(null); // Track which dev assignee is expanded
  const [expandedQAAssignee, setExpandedQAAssignee] = useState(null); // Track which QA assignee is expanded

  // Detail Modal state - for Release Content, Developer Workload, QA Backlog
  const [detailModal, setDetailModal] = useState(null); // 'releaseContent', 'devWorkload', 'qaBacklog', or null
  const [detailModalSort, setDetailModalSort] = useState({ field: null, direction: 'asc' });
  const [detailModalFilter, setDetailModalFilter] = useState('');
  const [detailModalPage, setDetailModalPage] = useState(1);
  const ITEMS_PER_PAGE = 50;

  // Milestone descriptions for leadership context
  const milestoneDescriptions = {
    all: {
      label: 'All Milestones',
      description: 'Complete release timeline showing all key milestones',
      requirement: 'Track progress across all phases'
    },
    irr: {
      label: 'Internal Release Review',
      description: 'First internal milestone - Feature freeze checkpoint',
      requirement: 'All Stories must be RESOLVED',
      icon: '🎯'
    },
    branch_cut: {
      label: 'Branch Cut',
      description: 'Release branch is cut from main - Only bug fixes allowed after this',
      requirement: 'All Stories must be RESOLVED',
      icon: '✂️'
    },
    final_build: {
      label: 'Final Build',
      description: 'Last build that will go to production - Critical deadline',
      requirement: 'All Stories & Bugs must be CLOSED or COMPLETED',
      icon: '🏗️'
    },
    stg_deploy: {
      label: 'STG Deploy',
      description: 'Staging environment deployment - Final validation before production',
      requirement: 'All regression tests passed. No critical blockers.',
      icon: '🧪'
    },
    pre_prd_deploy: {
      label: 'PRE-PRD Deploy',
      description: 'Pre-production deployment - Final sanity checks before going live',
      requirement: 'Staging validated. Production readiness confirmed.',
      icon: '🔄'
    },
    day1_deploy: {
      label: 'Day 1 Deploy',
      description: 'Initial production deployment - Canary rollout begins',
      requirement: 'Monitor for critical issues. Rollback capability ready.',
      icon: '🚀'
    },
    day2_deploy: {
      label: 'Day 2 Deploy',
      description: 'Expanded rollout - More traffic moved to new version',
      requirement: 'No P0/P1 issues from Day 1. Metrics stable.',
      icon: '📈'
    },
    day3_deploy: {
      label: 'Day 3 Deploy',
      description: 'Majority rollout - Most traffic on new version',
      requirement: 'All critical metrics healthy. No regressions.',
      icon: '📊'
    },
    day4_deploy: {
      label: 'Day 4 Deploy',
      description: 'Full rollout complete - 100% traffic on new version',
      requirement: 'Release complete. Begin next cycle planning.',
      icon: '✅'
    }
  };

  const fetchReadinessData = async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    
    if (forceRefresh) {
      setMilestoneData(null);
      setCommitsData(null);
      setResolutionProgressData(null);
      setPdvData(null);
      setExpandedRepos({});
      setExpandedAssignees({});
      setExpandedMilestoneComponents({});
    }
    
    try {
      const result = await api.getReleaseReadiness(selectedRelease, forceRefresh);
      setData(result);
      
      // Fire secondary re-fetches in parallel (non-blocking)
      if (forceRefresh) {
        api.getCommitsAfterBranchCut(selectedRelease)
          .then(r => setCommitsData(r))
          .catch(err => console.error('Error fetching commits:', err));
        api.getResolutionProgress(selectedRelease)
          .then(r => setResolutionProgressData(r))
          .catch(err => console.error('Error fetching resolution progress:', err));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedRelease) return;  // Wait until release is loaded
    fetchReadinessData();  // Initial load doesn't need force refresh
    // Reset expanded sections when release changes to avoid stale UI state
    setExpandedSections(prev => ({ ...prev, codeCommits: false }));
    setExpandedRepos({});
    
    // Fetch commits data for the Code Commits section
    const fetchCommitsData = async () => {
      setCommitsLoading(true);
      try {
        const result = await api.getCommitsAfterBranchCut(selectedRelease);
        setCommitsData(result);
      } catch (err) {
        console.error('Error fetching commits:', err);
        setCommitsData(null);
      } finally {
        setCommitsLoading(false);
      }
    };
    fetchCommitsData();
    
    // Fetch resolution progress data for the progress chart
    const fetchResolutionProgress = async () => {
      setResolutionProgressLoading(true);
      try {
        const result = await api.getResolutionProgress(selectedRelease);
        setResolutionProgressData(result);
      } catch (err) {
        console.error('Error fetching resolution progress:', err);
        setResolutionProgressData(null);
      } finally {
        setResolutionProgressLoading(false);
      }
    };
    fetchResolutionProgress();
    
    // Fetch items moved out of release data
    const fetchItemsMovedOut = async () => {
      setItemsMovedOutLoading(true);
      setItemsMovedOutError(null);
      try {
        const result = await api.getItemsMovedOut(selectedRelease);
        setItemsMovedOutData(result);
      } catch (err) {
        console.error('Error fetching items moved out:', err);
        setItemsMovedOutError(err.message);
        setItemsMovedOutData(null);
      } finally {
        setItemsMovedOutLoading(false);
      }
    };
    fetchItemsMovedOut();
    
    // Fetch NPLANs data for this release
    const fetchNplans = async () => {
      setNplansLoading(true);
      setNplansError(null);
      try {
        const result = await api.getNplans(selectedRelease);
        setNplansData(result);
      } catch (err) {
        console.error('Error fetching NPLANs:', err);
        setNplansError(err.message);
        setNplansData(null);
      } finally {
        setNplansLoading(false);
      }
    };
    fetchNplans();
    
    // Fetch NPLAN bugs data for this release
    const fetchNplanBugs = async () => {
      setNplanBugsLoading(true);
      setNplanBugsError(null);
      try {
        const result = await api.getNplanBugs(selectedRelease, true);
        setNplanBugsData(result);
      } catch (err) {
        console.error('Error fetching NPLAN bugs:', err);
        setNplanBugsError(err.message);
        setNplanBugsData(null);
      } finally {
        setNplanBugsLoading(false);
      }
    };
    fetchNplanBugs();

    // Fetch NPLAN dev status (PR merge info) for this release
    const fetchNplanDevStatus = async () => {
      setNplanDevStatusLoading(true);
      try {
        const result = await api.getNplanDevStatus(selectedRelease);
        setNplanDevStatusData(result);
      } catch (err) {
        console.error('Error fetching NPLAN dev status:', err);
        setNplanDevStatusData(null);
      } finally {
        setNplanDevStatusLoading(false);
      }
    };
    fetchNplanDevStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRelease]);

  // Fetch milestone-specific data when a milestone is selected
  useEffect(() => {
    const fetchMilestoneData = async () => {
      if (selectedMilestone === 'all') {
        setMilestoneData(null);
        setMilestoneError(null);
        setPdvData(null);
        setPdvError(null);
        return;
      }

      // Day deploy milestones - fetch PDV data from Insights Platform
      if (selectedMilestone.startsWith('day')) {
        setMilestoneData(null);
        setMilestoneError(null);
        setMilestoneLoading(false);
        setMilestonePanelCollapsed(false);
        
        const dayNum = selectedMilestone.replace('day', '').replace('_deploy', '');
        const dayPdvKey = `prod_day${dayNum}`;
        
        // Check cache first - avoid refetching if we already have data for this release
        if (pdvCache[selectedRelease]) {
          const cachedMilestones = pdvCache[selectedRelease].milestones || {};
          setPdvData({
            all: cachedMilestones,
            current: cachedMilestones[dayPdvKey] || null,
            version: pdvCache[selectedRelease].version,
            fetched_at: pdvCache[selectedRelease].fetched_at
          });
          return;
        }
        
        setPdvLoading(true);
        setPdvError(null);
        
        try {
          const pdvResponse = await api.getPDVMilestoneStatus(selectedRelease);
          const milestones = pdvResponse?.milestones || {};
          
          // Cache the response for this release
          setPdvCache(prev => ({
            ...prev,
            [selectedRelease]: pdvResponse
          }));
          
          setPdvData({
            all: milestones,
            current: milestones?.[dayPdvKey] || null,
            version: pdvResponse?.version,
            fetched_at: pdvResponse?.fetched_at
          });
        } catch (err) {
          console.error('Error fetching PDV data:', err);
          setPdvError(err.message || 'Failed to fetch PDV data');
        } finally {
          setPdvLoading(false);
        }
        return;
      }

      // STG and Pre-PRD deploy milestones - fetch PDV data
      if (selectedMilestone === 'stg_deploy' || selectedMilestone === 'pre_prd_deploy') {
        setMilestoneData(null);
        setMilestoneError(null);
        setMilestoneLoading(false);
        setMilestonePanelCollapsed(false);
        
        const pdvKey = selectedMilestone === 'stg_deploy' ? 'staging' : 'preprod_day1';
        
        // Check cache first
        if (pdvCache[selectedRelease]) {
          const cachedMilestones = pdvCache[selectedRelease].milestones || {};
          setPdvData({
            all: cachedMilestones,
            current: cachedMilestones[pdvKey] || null,
            version: pdvCache[selectedRelease].version,
            fetched_at: pdvCache[selectedRelease].fetched_at
          });
          return;
        }
        
        setPdvLoading(true);
        setPdvError(null);
        
        try {
          const pdvResponse = await api.getPDVMilestoneStatus(selectedRelease);
          const milestones = pdvResponse?.milestones || {};
          
          // Cache the response
          setPdvCache(prev => ({
            ...prev,
            [selectedRelease]: pdvResponse
          }));
          
          setPdvData({
            all: milestones,
            current: milestones?.[pdvKey] || null,
            version: pdvResponse?.version,
            fetched_at: pdvResponse?.fetched_at
          });
        } catch (err) {
          console.error('Error fetching PDV data:', err);
          setPdvError(err.message || 'Failed to fetch PDV data');
        } finally {
          setPdvLoading(false);
        }
        return;
      }

      // Clear PDV data for non-deploy milestones
      setPdvData(null);
      setPdvError(null);

      setMilestoneLoading(true);
      setMilestoneError(null);
      setMilestonePanelCollapsed(false);
      setExpandedStatBox(null);
      
      try {
        let result;
        if (selectedMilestone === 'irr') {
          result = await api.getIRRMilestoneData(selectedRelease);
        } else if (selectedMilestone === 'branch_cut') {
          result = await api.getBranchCutMilestoneData(selectedRelease);
        } else if (selectedMilestone === 'final_build') {
          result = await api.getFinalBuildMilestoneData(selectedRelease);
        }
        setMilestoneData(result);
      } catch (err) {
        console.error('Error fetching milestone data:', err);
        setMilestoneError(err.message);
      } finally {
        setMilestoneLoading(false);
      }
    };

    fetchMilestoneData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMilestone, selectedRelease]);

  const toggleSection = (section) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  // Send Slack notification
  const sendSlackNotification = async () => {
    setSlackSending(true);
    setSlackStatus(null);
    try {
      const result = await api.sendSlackNotification(selectedRelease);
      if (result.success) {
        setSlackStatus('success');
        // Clear success message after 3 seconds
        setTimeout(() => setSlackStatus(null), 3000);
      } else {
        setSlackStatus('error');
        console.error('Slack notification failed:', result);
      }
    } catch (err) {
      console.error('Error sending Slack notification:', err);
      setSlackStatus('error');
    } finally {
      setSlackSending(false);
    }
  };

  // Analyze a commit for test impact
  const analyzeCommit = async (commit, repoData) => {
    setSelectedCommitForAnalysis({ commit, repoData });
    setCommitAnalysisLoading(true);
    setCommitAnalysisError(null);
    setCommitAnalysis(null);
    
    try {
      const result = await api.analyzeCommit(
        repoData.owner || 'your-org',
        repoData.name,
        commit.full_sha || commit.sha
      );
      setCommitAnalysis(result);
    } catch (err) {
      console.error('Error analyzing commit:', err);
      setCommitAnalysisError(err.message || 'Failed to analyze commit');
    } finally {
      setCommitAnalysisLoading(false);
    }
  };

  // Close commit analysis modal
  const closeCommitAnalysis = () => {
    setSelectedCommitForAnalysis(null);
    setCommitAnalysis(null);
    setCommitAnalysisError(null);
  };

  // Extract data from API response
  const { 
    summary = {}, 
    componentsData = {}, 
    components = ['YOUR_PRODUCT'], 
    phaseCountdown = {}, 
    currentPhase = {},
    releaseSummary = {},  // Contains rrsScore from backend
    storiesByAssignee = [], 
    resolvedByQA = [], 
    totalResolvedOnly = 0,
    jiraDashboardUrl = 'https://your-org.atlassian.net/jira/dashboards/20524',
    trendAnalysis = {},
    blockersAnalysis = {},
    releaseLead = ''
  } = data || {};
  
  const trackBugs = currentPhase?.trackBugs ?? true;

  // Get stats based on selected component
  const getStats = () => {
    if (selectedComponent === 'all') {
      return {
        stories: summary.total_bc_stories || 0,
        bugs: summary.total_bc_bugs || 0,
        codeReview: summary.total_code_review || 0
      };
    }
    const compData = componentsData[selectedComponent];
    if (!compData) return { stories: 0, bugs: 0, codeReview: 0 };
    return {
      stories: compData.summary?.bc_stories || 0,
      bugs: compData.summary?.bc_bugs || 0,
      codeReview: compData.summary?.code_review || 0
    };
  };

  // Get filtered stories by component
  const getFilteredStories = () => {
    if (!storiesByAssignee || storiesByAssignee.length === 0) return [];
    if (selectedComponent === 'all') return storiesByAssignee;
    return storiesByAssignee
      .map(item => {
        const filteredTickets = (item.tickets || []).filter(t => t.component === selectedComponent);
        const openCount = filteredTickets.filter(t => t.status?.toLowerCase() !== 'code review').length;
        const crCount = filteredTickets.filter(t => t.status?.toLowerCase() === 'code review').length;
        return { ...item, tickets: filteredTickets, open: openCount, code_review: crCount };
      })
      .filter(item => item.tickets.length > 0);
  };

  // Get filtered resolved items by component
  const getFilteredResolved = () => {
    if (!resolvedByQA || resolvedByQA.length === 0) return [];
    if (selectedComponent === 'all') {
      // Ensure stories/bugs counts are calculated from tickets if not provided
      return resolvedByQA.map(item => {
        const tickets = item.tickets || [];
        const stories = item.stories ?? tickets.filter(t => t.type !== 'Bug').length;
        const bugs = item.bugs ?? tickets.filter(t => t.type === 'Bug').length;
        return { ...item, stories, bugs };
      });
    }
    return resolvedByQA
      .map(item => {
        const filteredTickets = (item.tickets || []).filter(t => t.component === selectedComponent);
        const storiesCount = filteredTickets.filter(t => t.type !== 'Bug').length;
        const bugsCount = filteredTickets.filter(t => t.type === 'Bug').length;
        const resolvedCount = filteredTickets.filter(t => t.status === 'Resolved').length;
        return { ...item, tickets: filteredTickets, resolved: resolvedCount, stories: storiesCount, bugs: bugsCount };
      })
      .filter(item => item.tickets.length > 0);
  };

  // Get bug items from componentsData
  const getBugItems = () => {
    let allBugs = [];
    if (selectedComponent === 'all') {
      // Get bugs from all components
      Object.keys(componentsData).forEach(comp => {
        const issues = componentsData[comp]?.issues || [];
        const bugs = issues.filter(i => i.type === 'Bug');
        allBugs = [...allBugs, ...bugs];
      });
    } else {
      const issues = componentsData[selectedComponent]?.issues || [];
      allBugs = issues.filter(i => i.type === 'Bug');
    }
    return allBugs;
  };

  // Helper to check for More Info status
  const isMoreInfoStatus = (status) => {
    const s = (status || '').toLowerCase();
    return s.includes('more info') || s.includes('moreinfo');
  };

  // Get action items (from blockers analysis + stats as clickable items)
  const getActionItems = () => {
    const items = [];
    
    const filterByComponent = (arr) => {
      if (selectedComponent === 'all' || !arr) return arr || [];
      return arr.filter(item => item.component === selectedComponent);
    };
    
    // Deduplicate arrays by key
    const deduplicateByKey = (arr) => {
      const seen = new Set();
      return (arr || []).filter(item => {
        if (!item.key || seen.has(item.key)) return false;
        seen.add(item.key);
        return true;
      });
    };
    
    const criticalItems = deduplicateByKey(filterByComponent(blockersAnalysis?.criticalItems));
    const stuckItems = deduplicateByKey(filterByComponent(blockersAnalysis?.stuckItems));
    const reviewItems = deduplicateByKey(filterByComponent(blockersAnalysis?.codeReviewBottleneck));
    const bugItems = deduplicateByKey(getBugItems());
    
    // Stories action item (always show if > 0)
    if (stats.stories > 0) {
      // Get story items from filteredStories (deduplicated)
      const storyItemsList = [];
      const storyKeys = new Set();
      filteredStories.forEach(assigneeData => {
        (assigneeData.tickets || []).forEach(t => {
          if ((t.type === 'Story' || !t.type) && t.key && !storyKeys.has(t.key)) {
            storyKeys.add(t.key);
            storyItemsList.push(t);
          }
        });
      });
      
      items.push({
        priority: 'warning',
        icon: '📖',
        title: `${stats.stories} Open Stories`,
        description: 'Stories pending resolution before deadline',
        owners: [...new Set(filteredStories.slice(0, 3).map(s => s.assignee))].join(', ') || 'Dev Team',
        action: 'Complete development and move to Code Review',
        items: storyItemsList.slice(0, 20),
        clickAction: 'pending'
      });
    }
    
    // Bugs action item (if tracking bugs and > 0)
    if (trackBugs && stats.bugs > 0) {
      items.push({
        priority: stats.bugs > 5 ? 'critical' : 'warning',
        icon: '🐛',
        title: `${stats.bugs} Pending Bugs`,
        description: 'Bugs awaiting resolution before release',
        owners: [...new Set(bugItems.slice(0, 3).map(b => b.assignee))].filter(Boolean).join(', ') || 'Dev Team',
        action: 'Prioritize and fix bugs',
        items: bugItems.slice(0, 20),
        clickAction: 'pending'
      });
    }
    
    // Code Review action item
    if (stats.codeReview > 0) {
      items.push({
        priority: stats.codeReview > 3 ? 'warning' : 'info',
        icon: '🔄',
        title: `${stats.codeReview} In Code Review`,
        description: 'Items waiting for review approval',
        owners: 'Tech Leads',
        action: 'Complete code reviews',
        items: reviewItems,
        clickAction: 'pending'
      });
    }
    
    // Note: Awaiting QA is shown in QA Backlog chart, not duplicated here
    
    // Critical/Blocker items (high priority)
    if (criticalItems.length > 0) {
      items.unshift({
        priority: 'critical',
        icon: '🚨',
        title: `${criticalItems.length} Critical/Blocker`,
        description: 'Immediate escalation required - These block release',
        owners: [...new Set(criticalItems.map(i => i.assignee))].slice(0, 3).join(', '),
        action: 'Escalate to ensure resolution today',
        items: criticalItems
      });
    }
    
    // Stuck items
    if (stuckItems.length > 0) {
      items.push({
        priority: 'warning',
        icon: '⏸️',
        title: `${stuckItems.length} Not Started`,
        description: 'Items in Open/Reopened status',
        owners: [...new Set(stuckItems.map(i => i.assignee))].slice(0, 3).join(', '),
        action: 'Check for blockers or reassign',
        items: stuckItems
      });
    }
    
    // More Info items - stories + bugs awaiting information (deduplicated)
    // Both stories and bugs are always included regardless of trackBugs phase
    // These are action items that need attention from reporters
    const moreInfoItems = [];
    const moreInfoKeys = new Set();
    
    // Process stories
    filteredStories.forEach(assigneeData => {
      (assigneeData.tickets || []).forEach(t => {
        if (isMoreInfoStatus(t.status) && t.key && !moreInfoKeys.has(t.key)) {
          moreInfoKeys.add(t.key);
          moreInfoItems.push(t);
        }
      });
    });
    
    // Always process bugs for More Info (regardless of trackBugs phase)
    // These are action items that need attention
    bugItems.forEach(bug => {
      if (isMoreInfoStatus(bug.status) && bug.key && !moreInfoKeys.has(bug.key)) {
        moreInfoKeys.add(bug.key);
        moreInfoItems.push(bug);
      }
    });
    
    if (moreInfoItems.length > 0) {
      // Group More Info items by reporter
      const groupedByReporter = {};
      moreInfoItems.forEach(item => {
        const reporter = item.reporter || 'Unknown';
        if (!groupedByReporter[reporter]) {
          groupedByReporter[reporter] = [];
        }
        groupedByReporter[reporter].push(item);
      });
      
      items.push({
        priority: 'info',
        icon: 'ℹ️',
        title: `${moreInfoItems.length} More Info`,
        description: 'Items awaiting additional information from reporter',
        tooltip: 'These work items are blocked and waiting for clarification or additional details from the original reporter. Contact the reporters listed to provide the requested information and unblock progress.',
        isMoreInfo: true,
        groupedByReporter: groupedByReporter,
        owners: [...new Set(moreInfoItems.map(i => i.reporter).filter(Boolean))].slice(0, 3).join(', ') || 'Reporters',
        action: 'Follow up with reporters for required information',
        items: moreInfoItems
      });
    }
    
    // Defects awaiting QA closure with no assigned QA (assignee is None/null)
    // JQL: (fixVersion = "X.0.0") AND (project = ENG AND component = "NS Client (NSC)" AND type IN (Bug, Story, Task) 
    //      AND status IN (Resolved, "Pending Close"))
    const unassignedQAItems = resolvedByQA
      .filter(qa => !qa.qa || qa.qa === 'Unassigned' || qa.qa === 'None' || qa.qa.toLowerCase() === 'none')
      .flatMap(qa => qa.tickets || []);
    
    if (unassignedQAItems.length > 0) {
      items.push({
        priority: 'warning',
        icon: '🔍',
        title: `${unassignedQAItems.length} Unassigned QA Items`,
        description: 'Resolved items with no QA assigned for verification',
        tooltip: 'These items are resolved/pending close but have no QA assignee to verify and close them. Assign QA resources to complete the verification process.',
        owners: 'QA Lead',
        action: 'Assign QA resources to verify and close these items',
        items: unassignedQAItems,
        clickAction: 'awaitingQA'
      });
    }
    
    // Triage items - ONLY items assigned to explicit triage accounts (not empty/unassigned)
    // Only ns_client_eng_triage and similar explicit triage service accounts
    const triageAccountPatterns = [
      'your-product-triage', 'product-triage', 'eng_triage'
    ];
    const triageItems = [];
    const triageKeys = new Set();
    
    // Check if assignee is an explicit triage account (NOT empty/unassigned)
    const isTriageAccount = (assigneeName) => {
      if (!assigneeName || assigneeName.trim() === '') return false; // Empty is NOT triage
      const name = (assigneeName || '').toLowerCase().trim();
      return triageAccountPatterns.some(pattern => name.includes(pattern));
    };
    
    // Check stories from storiesByAssignee - only explicit triage accounts
    filteredStories.forEach(assigneeData => {
      const groupAssignee = assigneeData.assignee || '';
      if (isTriageAccount(groupAssignee)) {
        (assigneeData.tickets || []).forEach(t => {
          if (t.key && !triageKeys.has(t.key)) {
            triageKeys.add(t.key);
            triageItems.push({ ...t, assignee: groupAssignee });
          }
        });
      }
    });
    
    // Also check bugs from componentsData for triage accounts
    bugItems.forEach(bug => {
      const bugAssignee = bug.assignee || '';
      if (isTriageAccount(bugAssignee) && bug.key && !triageKeys.has(bug.key)) {
        triageKeys.add(bug.key);
        triageItems.push(bug);
      }
    });
    
    if (triageItems.length > 0) {
      // Insert after critical items but before other items (position 1 if critical exists, else 0)
      const insertPosition = items.findIndex(i => i.priority !== 'critical');
      const needsAssignmentItem = {
        priority: 'warning',
        icon: '👤',
        title: `${triageItems.length} Needs Assignment`,
        description: 'Stories/bugs assigned to triage - need owner assignment',
        tooltip: 'These work items are assigned to ns_client_eng_triage or similar triage accounts. They need to be assigned to specific developers to ensure timely completion.',
        owners: 'Engineering Manager',
        action: 'Assign these items to available developers',
        items: triageItems,
        clickAction: 'pending'
      };
      
      if (insertPosition === -1) {
        items.push(needsAssignmentItem);
      } else {
        items.splice(insertPosition, 0, needsAssignmentItem);
      }
    }
    
    return items;
  };

  const stats = getStats();
  const filteredStories = getFilteredStories();
  const filteredResolved = getFilteredResolved();
  const actionItems = getActionItems();
  const totalOpen = stats.stories + (trackBugs ? stats.bugs : 0);
  const totalPendingItems = filteredStories.reduce((acc, s) => acc + (s.open || 0) + (s.code_review || 0), 0);
  const totalAwaitingQA = filteredResolved.reduce((acc, r) => acc + (r.resolved || 0), 0);

  // Calculate workload data for Developer Workload (used in hero dashboard and detail modal)
  const { allAssignees, totalDevItems, maxWorkload } = useMemo(() => {
    const workloadByAssignee = {};
    filteredStories.forEach(item => {
      const name = item.assignee || 'Unassigned';
      if (!workloadByAssignee[name]) {
        workloadByAssignee[name] = { stories: 0, bugs: 0, review: 0, total: 0, tickets: [] };
      }
      const tickets = item.tickets || [];
      const storyTickets = tickets.filter(t => t.type !== 'Bug' && t.status?.toLowerCase() !== 'code review');
      const bugTickets = tickets.filter(t => t.type === 'Bug' && t.status?.toLowerCase() !== 'code review');
      const reviewTickets = tickets.filter(t => t.status?.toLowerCase() === 'code review');
      
      workloadByAssignee[name].stories += storyTickets.length;
      workloadByAssignee[name].bugs += bugTickets.length;
      workloadByAssignee[name].review += reviewTickets.length;
      workloadByAssignee[name].total += storyTickets.length + bugTickets.length + reviewTickets.length;
      workloadByAssignee[name].tickets.push(...storyTickets, ...bugTickets, ...reviewTickets);
    });
    
    const assignees = Object.entries(workloadByAssignee).sort((a, b) => b[1].total - a[1].total);
    const maxWork = Math.max(...assignees.map(([_, d]) => d.total), 1);
    const totalItems = assignees.reduce((acc, [_, d]) => acc + d.total, 0);
    
    return { allAssignees: assignees, totalDevItems: totalItems, maxWorkload: maxWork };
  }, [filteredStories]);

  // Calculate QA workload data (used in hero dashboard and detail modal)
  const { allQAs, totalQAItems, maxQAWork } = useMemo(() => {
    const qaWorkload = {};
    filteredResolved.forEach(item => {
      const qa = item.qa || 'Unassigned';
      if (!qaWorkload[qa]) {
        qaWorkload[qa] = { stories: 0, bugs: 0, total: 0, tickets: [] };
      }
      const tickets = item.tickets || [];
      qaWorkload[qa].stories += item.stories || 0;
      qaWorkload[qa].bugs += item.bugs || 0;
      qaWorkload[qa].total += (item.stories || 0) + (item.bugs || 0);
      qaWorkload[qa].tickets.push(...tickets);
    });
    
    const qas = Object.entries(qaWorkload).sort((a, b) => b[1].total - a[1].total);
    const maxWork = Math.max(...qas.map(([_, v]) => v.total), 1);
    const totalItems = qas.reduce((acc, [_, v]) => acc + v.total, 0);
    
    return { allQAs: qas, totalQAItems: totalItems, maxQAWork: maxWork };
  }, [filteredResolved]);

  // Get all work items (stories + bugs) grouped by status
  const getWorkItemsByStatus = () => {
    const statusGroups = {};
    const moreInfoByReporter = {};
    const processedKeys = new Set(); // Track processed items to avoid duplicates
    
    // Helper to process a ticket
    const processTicket = (ticket) => {
      if (!ticket.key || processedKeys.has(ticket.key)) return;
      processedKeys.add(ticket.key);
      
      const status = ticket.status || 'Open';
      const type = ticket.type || 'Story';
      
      // Always add to statusGroups (including More Info items)
      if (!statusGroups[status]) {
        statusGroups[status] = { stories: 0, bugs: 0, items: [] };
      }
      if (type === 'Bug') {
        statusGroups[status].bugs++;
      } else {
        statusGroups[status].stories++;
      }
      statusGroups[status].items.push(ticket);
      
      // Also track More Info items separately by reporter for the dedicated section
      if (isMoreInfoStatus(status)) {
        const reporter = ticket.reporter || 'Unknown';
        if (!moreInfoByReporter[reporter]) {
          moreInfoByReporter[reporter] = { stories: 0, bugs: 0, items: [] };
        }
        if (type === 'Bug') {
          moreInfoByReporter[reporter].bugs++;
        } else {
          moreInfoByReporter[reporter].stories++;
        }
        moreInfoByReporter[reporter].items.push(ticket);
      }
    };
    
    // Process all stories from filteredStories
    filteredStories.forEach(assigneeData => {
      (assigneeData.tickets || []).forEach(processTicket);
    });
    
    // Process bugs from getBugItems (will skip already processed)
    const bugItems = getBugItems();
    bugItems.forEach(processTicket);
    
    return { statusGroups, moreInfoByReporter };
  };
  
  const { statusGroups, moreInfoByReporter } = getWorkItemsByStatus();

  // Use backend's total count directly from JQL query (single source of truth)
  // This matches the JIRA dashboard query exactly
  const totalOpenItems = summary.total_fb_issues || 0;

  // Get all work items grouped by priority
  const getWorkItemsByPriority = () => {
    const priorityGroups = {};
    const processedKeys = new Set(); // Track processed items to avoid duplicates
    
    // Helper to process a ticket
    const processTicket = (ticket) => {
      if (!ticket.key || processedKeys.has(ticket.key)) return;
      processedKeys.add(ticket.key);
      
      const priority = ticket.priority || 'Medium';
      const type = ticket.type || 'Story';
      
      if (!priorityGroups[priority]) {
        priorityGroups[priority] = { stories: 0, bugs: 0, total: 0, items: [] };
      }
      if (type === 'Bug') {
        priorityGroups[priority].bugs++;
      } else {
        priorityGroups[priority].stories++;
      }
      priorityGroups[priority].total++;
      priorityGroups[priority].items.push(ticket);
    };
    
    // Process all stories from filteredStories
    filteredStories.forEach(assigneeData => {
      (assigneeData.tickets || []).forEach(processTicket);
    });
    
    // Process bugs from getBugItems (will skip already processed)
    const bugItems = getBugItems();
    bugItems.forEach(processTicket);
    
    return priorityGroups;
  };
  
  const priorityGroups = getWorkItemsByPriority();

  // Get critical priority bugs count from componentsData (release data items)
  // IMPORTANT: Use componentsData bugs (same JQL as backend's release data) for consistency.
  // priorityGroups mixes developer workload items (ENG+OPS+CD) with release data (ENG only),
  // which would produce a different blocker count than the backend's calculate_rrs_score().
  const getBlockerCountFromReleaseData = () => {
    const criticalPriorities = ['critical', 'blocker', 'highest'];
    let count = 0;
    const allIssues = selectedComponent === 'all'
      ? Object.values(componentsData).flatMap(comp => comp?.issues || [])
      : (componentsData[selectedComponent]?.issues || []);
    allIssues.forEach(issue => {
      if (criticalPriorities.includes((issue.priority || '').toLowerCase())) {
        count++;
      }
    });
    return count;
  };

  const criticalBugsCount = (priorityGroups['Critical']?.bugs || 0) + (priorityGroups['Blocker']?.bugs || 0) + (priorityGroups['Highest']?.bugs || 0);
  
  // Release Readiness Score (RRS) - Use backend's calculated score for consistency
  // This ensures the score matches what's shown on the Overview page
  const calculateHealthScore = () => {
    // Use backend's rrsScore if available (single source of truth)
    if (releaseSummary?.rrsScore !== undefined && releaseSummary.rrsScore !== null) {
      return releaseSummary.rrsScore;
    }
    
    // Fallback: Calculate locally using release data stats (same source as backend)
    const openStories = stats.stories || 0;
    const openBugs = stats.bugs || 0;
    const codeReviewItems = stats.codeReview || 0;
    
    if (openStories === 0 && openBugs === 0) return 100;
    
    // Use blocker count from release data (componentsData) for consistency with backend
    const blockerCount = getBlockerCountFromReleaseData();
    
    const criticalPenalty = blockerCount * 2;
    const storyPenalty = openStories * 1;
    const nonCriticalBugs = Math.max(0, openBugs - blockerCount);
    const bugPenalty = nonCriticalBugs * 0.5;
    const codeReviewPenalty = codeReviewItems * 0.25;
    
    const totalPenalty = Math.min(100, criticalPenalty + storyPenalty + bugPenalty + codeReviewPenalty);
    const rrsScore = Math.round(100 - totalPenalty);
    
    return Math.max(0, Math.min(100, rrsScore));
  };
  
  const healthScore = calculateHealthScore();
  const openStoriesCount = stats.stories || 0;
  
  const getHealthStatus = () => {
    if (healthScore >= 80) return { label: 'On Track', status: 'success', icon: <CheckCircle size={20} />, message: 'Release is progressing well' };
    if (healthScore >= 50) return { label: 'At Risk', status: 'warning', icon: <AlertTriangle size={20} />, message: 'Some items need attention' };
    return { label: 'Critical', status: 'critical', icon: <XCircle size={20} />, message: 'Immediate action required' };
  };
  const healthStatus = getHealthStatus();

  // Health score tooltip explanation for PMO
  const getHealthScoreTooltip = () => {
    const blockerCount = getBlockerCountFromReleaseData();
    const criticalPenalty = blockerCount * 2;
    const storyPenalty = openStoriesCount * 1;
    const nonCriticalBugs = Math.max(0, (stats.bugs || 0) - blockerCount);
    const bugPenalty = nonCriticalBugs * 0.5;
    const codeReviewPenalty = (stats.codeReview || 0) * 0.25;
    const totalPenalty = criticalPenalty + storyPenalty + bugPenalty + codeReviewPenalty;
    
    let explanation = `Release Readiness Score: ${healthScore}%\n\n`;
    explanation += `Formula: 100 - Total Penalty\n`;
    explanation += `━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;
    explanation += `Penalty Breakdown:\n`;
    explanation += `• Critical/Blocker Items: ${blockerCount} × 2 = ${criticalPenalty}pts\n`;
    explanation += `• Open Stories: ${openStoriesCount} × 1 = ${storyPenalty}pts\n`;
    explanation += `• Other Bugs: ${nonCriticalBugs} × 0.5 = ${bugPenalty}pts\n`;
    explanation += `• In Code Review: ${stats.codeReview || 0} × 0.25 = ${codeReviewPenalty}pts\n`;
    explanation += `━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;
    explanation += `Total Penalty: ${Math.min(100, totalPenalty).toFixed(1)}pts\n`;
    explanation += `Score: 100 - ${Math.min(100, totalPenalty).toFixed(1)} = ${healthScore}%\n\n`;
    explanation += `Thresholds:\n`;
    explanation += `• 80-100%: On Track (Green)\n`;
    explanation += `• 50-79%: At Risk (Yellow)\n`;
    explanation += `• 0-49%: Critical (Red)`;
    
    return explanation;
  };

  // Milestone options - All visible for all components
  const milestoneOptions = [
    { value: 'all', label: 'All Milestones' },
    { value: 'irr', label: 'IRR' },
    { value: 'branch_cut', label: 'Branch Cut' },
    { value: 'final_build', label: 'Final Build' },
    { value: 'stg_deploy', label: 'STG Deploy' },
    { value: 'pre_prd_deploy', label: 'PRE-PRD Deploy' },
    { value: 'day1_deploy', label: 'Day 1 Deploy' },
    { value: 'day2_deploy', label: 'Day 2 Deploy' },
    { value: 'day3_deploy', label: 'Day 3 Deploy' },
    { value: 'day4_deploy', label: 'Day 4 Deploy' }
  ];

  if (loading) {
    return (
      <div className="rr-dashboard">
        <div className="rr-loading">
          <RefreshCw size={40} className="spinning" />
          <p>Loading release readiness data...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rr-dashboard">
        <div className="rr-error">
          <AlertTriangle size={48} />
          <h2>Unable to Load Data</h2>
          <p>{error}</p>
          <button onClick={() => fetchReadinessData(true)} className="rr-btn primary">
            <RefreshCw size={16} /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rr-dashboard runway-style">
      {/* ============================================
          HEADER - Filters & Actions
          ============================================ */}
      <header className="rr-header">
        <div className="rr-header-left">
          <Package size={24} />
          <div>
            <h1>Release Readiness</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span className="rr-release-tag">{selectedRelease}</span>
              <span style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: '6px',
                background: 'rgba(99, 102, 241, 0.1)', 
                color: '#6366f1',
                padding: '4px 12px',
                borderRadius: '16px',
                fontSize: '12px',
                fontWeight: '600'
              }}>
                <User size={14} />
                Release Lead: {releaseLead || 'Not Assigned'}
              </span>
            </div>
        </div>
        </div>
        
        <div className="rr-header-right">
          {/* Component Filter */}
          <div className="rr-filter-group">
            <label>Component:</label>
            <select 
              value={selectedComponent} 
              onChange={(e) => setSelectedComponent(e.target.value)}
              className="rr-select"
            >
              {components.map(comp => (
                <option key={comp} value={comp}>{comp}</option>
              ))}
            </select>
          </div>
          
          {/* Milestone Filter */}
          <div className="rr-filter-group">
            <label>Milestone:</label>
            <select 
              value={selectedMilestone} 
              onChange={(e) => setSelectedMilestone(e.target.value)}
              className="rr-select"
            >
              {milestoneOptions.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
        </div>
          
          <button onClick={() => fetchReadinessData(true)} className="rr-btn icon" title="Refresh (bypass cache)">
            <RefreshCw size={18} />
          </button>
          <a href={jiraDashboardUrl} target="_blank" rel="noopener noreferrer" className="rr-btn primary">
            <ExternalLink size={16} /> JIRA
          </a>
          
          {/* Slack Notification Button */}
          <button 
            className={`rr-btn slack-btn ${slackSending ? 'sending' : ''} ${slackStatus || ''}`}
            onClick={sendSlackNotification}
            disabled={slackSending}
            title={slackStatus === 'success' ? 'Notification sent!' : slackStatus === 'error' ? 'Failed to send' : 'Send release status to Slack'}
          >
            {slackSending ? (
              <><RefreshCw size={16} className="spinning" /> Sending...</>
            ) : slackStatus === 'success' ? (
              <><CheckCircle size={16} /> Sent!</>
            ) : slackStatus === 'error' ? (
              <><AlertTriangle size={16} /> Failed</>
            ) : (
              <><Send size={16} /> Slack</>
            )}
          </button>
          
            <button 
            className={`rr-btn timeline-btn ${expandedSections.timeline ? 'active' : ''}`}
            onClick={() => toggleSection('timeline')}
            >
            <Clock size={16} />
            {expandedSections.timeline ? 'Hide Timeline' : 'View Timeline'}
            </button>
        </div>
      </header>

      {/* ============================================
          HERO DASHBOARD - Information Dense Layout
          ============================================ */}
      {(() => {
        // Flagged commits count
        const flaggedCommits = commitsData?.summary?.flaggedCommits || 0;
        const totalCommitsAfterBranchCut = commitsData?.summary?.totalCommits || 0;
        
        return (
          <div className="hero-dashboard">
            {/* Row 1: Main Stats Cards */}
            <div className="hero-stats-row">
              {/* Health Score Card */}
              <div className={`stat-card health-card ${healthStatus.status}`} title={getHealthScoreTooltip()} style={{ cursor: 'help' }}>
                <div style={{ width: '140px', height: '140px', position: 'relative' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={[
                          { name: 'Complete', value: healthScore, color: healthStatus.status === 'success' ? '#10b981' : healthStatus.status === 'warning' ? '#f59e0b' : '#ef4444' },
                          { name: 'Remaining', value: 100 - healthScore, color: '#e5e7eb' }
                        ]}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={65}
                        dataKey="value"
                        strokeWidth={0}
                        startAngle={90}
                        endAngle={-270}
                      >
                        {[
                          { name: 'Complete', value: healthScore, color: healthStatus.status === 'success' ? '#10b981' : healthStatus.status === 'warning' ? '#f59e0b' : '#ef4444' },
                          { name: 'Remaining', value: 100 - healthScore, color: '#e5e7eb' }
                        ].map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ 
                    position: 'absolute', top: '50%', left: '50%', 
                    transform: 'translate(-50%, -50%)', textAlign: 'center' 
                  }}>
                    <div style={{ fontSize: '24px', fontWeight: '700', color: healthStatus.status === 'success' ? '#10b981' : healthStatus.status === 'warning' ? '#f59e0b' : '#ef4444' }}>
                      {healthScore}%
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Ready</div>
                  </div>
                </div>
                <div className={`health-status-badge ${healthStatus.status}`}>
                  {healthStatus.icon}
                  <span>{healthStatus.label}</span>
                </div>
              </div>

              {/* Deadline Card */}
              <div className="stat-card deadline-card">
                <div className="deadline-icon">
                  <Clock size={18} />
                </div>
                <div className="deadline-content">
                  <div className="deadline-days">
                    <span className="days-num">{phaseCountdown?.days_remaining ?? '—'}</span>
                    <span className="days-text">days</span>
                  </div>
                  <div className="deadline-label">to {phaseCountdown?.current_phase === 'pre_irr' ? 'IRR' : (phaseCountdown?.deadline_name || 'Deadline')}</div>
                </div>
              </div>

              {/* Total Open Items Card with Breakdown - PMO visibility */}
              <div className="stat-card open-items-card with-breakdown" title="Total open work items matching JIRA dashboard query (Stories + Bugs)">
                <div className="open-items-icon">
                  <FileText size={16} />
                </div>
                <div className="open-items-total">{totalOpenItems}</div>
                <div className="open-items-label">Open Items</div>
                <div className="open-items-bar-container">
                  <div className="open-items-stacked-bar">
                    <div 
                      className="bar-segment stories-segment"
                      style={{ width: `${totalOpenItems > 0 ? (stats.stories / totalOpenItems) * 100 : 0}%` }}
                      title={`${stats.stories} Stories`}
                    />
                    <div 
                      className="bar-segment bugs-segment"
                      style={{ width: `${totalOpenItems > 0 ? (stats.bugs / totalOpenItems) * 100 : 0}%` }}
                      title={`${stats.bugs} Bugs`}
                    />
                  </div>
                </div>
                <div className="open-items-breakdown">
                  <span className="breakdown-item stories" title="Stories">
                    <BookOpen size={11} />{stats.stories}
                  </span>
                  <span className="breakdown-item bugs" title="Bugs">
                    <Bug size={11} />{stats.bugs}
                  </span>
                </div>
              </div>

              {/* Action Items Inline - Clickable to expand */}
              <div 
                className={`stat-card action-items-inline-card ${expandedSections.actionItems ? 'expanded' : ''}`}
                onClick={() => actionItems.length > 0 && setExpandedSections(prev => ({ ...prev, actionItems: !prev.actionItems }))}
              >
                <div className="action-inline-header">
                  <Zap size={16} />
                  <span>Action Items</span>
                  <span className="action-inline-badge">{actionItems.length}</span>
                  {actionItems.length > 0 && (
                    <ChevronDown size={16} className={`action-inline-chevron ${expandedSections.actionItems ? 'expanded' : ''}`} />
                  )}
                </div>
                <div className="action-inline-grid">
                  {actionItems.length > 0 ? (
                    actionItems.slice(0, 5).map((item, idx) => {
                      const categoryClass = item.priority === 'critical' ? 'critical' 
                        : item.title.includes('Stories') ? 'stories'
                        : item.title.includes('Bugs') ? 'bugs'
                        : item.title.includes('Review') ? 'review'
                        : item.title.includes('Assignment') ? 'assignment'
                        : 'blocked';
                      return (
                        <div 
                          key={idx}
                          className={`action-inline-item ${categoryClass}`}
                          title={item.description}
                        >
                          <span className="action-inline-icon">
                            {item.priority === 'critical' ? <AlertTriangle size={14} /> :
                             item.title.includes('Stories') ? <BookOpen size={14} /> :
                             item.title.includes('Bugs') ? <Bug size={14} /> :
                             item.title.includes('Review') ? <GitPullRequest size={14} /> :
                             item.title.includes('Assignment') ? <User size={14} /> :
                             <Pause size={14} />}
                          </span>
                          <span className="action-inline-count">{item.title.match(/\d+/)?.[0] || '0'}</span>
                          <span className="action-inline-label">{item.title.replace(/\d+\s*/, '')}</span>
                        </div>
                      );
                    })
                  ) : (
                    <div className="action-inline-clear">
                      <CheckCircle size={20} />
                      <span>All Clear!</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Flagged Commits Card - Only show after branch cut */}
              {commitsData?.branchCutPassed === true && (
                <div 
                  className={`stat-card commits-card ${flaggedCommits > 0 ? 'has-flags' : 'clear'} ${expandedSections.codeCommits ? 'expanded' : ''}`}
                  onClick={() => toggleSection('codeCommits')}
                >
                  <div className="commits-icon-large">
                    <Activity size={24} />
                  </div>
                  <span className={`commits-count-large ${flaggedCommits > 0 ? 'warning' : ''}`}>{flaggedCommits}</span>
                  <span className="commits-label-large">Flagged Commits</span>
                  <span className="commits-sublabel">{expandedSections.codeCommits ? 'Click to hide' : 'Click to view'}</span>
                </div>
              )}
            </div>

            {/* Expanded Action Items - Category Cards (shown when Action Items card is clicked) */}
            {expandedSections.actionItems && actionItems.length > 0 && (
              <div className="action-items-expanded-section">
                <div className="action-categories-grid">
                  {actionItems.map((item, idx) => {
                    const categoryClass = item.priority === 'critical' ? 'critical' 
                      : item.title.includes('Stories') ? 'stories'
                      : item.title.includes('Bugs') ? 'bugs'
                      : item.title.includes('Review') ? 'review'
                      : 'blocked';
                    
                    return (
                      <div 
                        key={idx}
                        className={`action-category-card ${categoryClass} ${expandedSections[`action_${idx}`] ? 'expanded' : ''}`}
                        title={item.tooltip || item.description}
                      >
                        <div className="category-header">
                          <div className={`category-icon ${categoryClass}`}>
                            {item.priority === 'critical' ? <AlertTriangle size={16} /> :
                             item.title.includes('Stories') ? <BookOpen size={16} /> :
                             item.title.includes('Bugs') ? <Bug size={16} /> :
                             item.title.includes('Review') ? <GitPullRequest size={16} /> :
                             item.title.includes('More Info') ? <Info size={16} /> :
                             <Pause size={16} />}
                          </div>
                          <span className="category-count">
                            {item.title.match(/\d+/)?.[0] || '0'}
                          </span>
                        </div>
                        <div className="category-title">{item.title.replace(/\d+\s*/, '')}</div>
                        <div className="category-desc">{item.description}</div>
                        
                        {/* View Items Button - Toggles item list */}
                        {item.items && item.items.length > 0 && (
                          <button 
                            className="category-action-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedSections(prev => ({ ...prev, [`action_${idx}`]: !prev[`action_${idx}`] }));
                            }}
                          >
                            <span>{expandedSections[`action_${idx}`] ? '▼ Hide' : '▶ View'} {item.items.length} items</span>
                            <ArrowRight size={14} className={expandedSections[`action_${idx}`] ? 'rotated' : ''} />
                          </button>
                        )}
                        
                        {/* Expandable Items List */}
                        {expandedSections[`action_${idx}`] && item.items && (
                          <div className="category-items-list" onClick={(e) => e.stopPropagation()}>
                            {item.isMoreInfo && item.groupedByReporter ? (
                              // Special rendering for More Info - grouped by reporter
                              <div className="reporter-grouped-list">
                                {Object.entries(item.groupedByReporter)
                                  .sort((a, b) => b[1].length - a[1].length)
                                  .map(([reporter, tickets]) => (
                                    <div key={reporter} className="reporter-group">
                                      <div className="reporter-header">
                                        <User size={12} />
                                        <span className="reporter-name">{reporter}</span>
                                        <span className="reporter-count">{tickets.length} item{tickets.length > 1 ? 's' : ''}</span>
                                      </div>
                                      <div className="reporter-tickets">
                                        {(showAllItems[`reporter_${reporter}`] ? tickets : tickets.slice(0, 5)).map(ticket => (
                                          <a 
                                            key={ticket.key} 
                                            href={ticket.url} 
                                            target="_blank" 
                                            rel="noopener noreferrer"
                                            className="category-item-row"
                                          >
                                            <span className="item-key">{ticket.key}</span>
                                            <span className="item-summary">{ticket.summary?.substring(0, 50)}{ticket.summary?.length > 50 ? '...' : ''}</span>
                                            <span className={`item-type ${ticket.type?.toLowerCase() || 'story'}`}>{ticket.type || 'Story'}</span>
                                          </a>
                                        ))}
                                        {tickets.length > 5 && (
                                          <div 
                                            className="items-more clickable"
                                            onClick={(e) => {
                                              e.stopPropagation();
                                              setShowAllItems(prev => ({ ...prev, [`reporter_${reporter}`]: !prev[`reporter_${reporter}`] }));
                                            }}
                                          >
                                            {showAllItems[`reporter_${reporter}`] 
                                              ? '▲ Show less' 
                                              : `▼ +${tickets.length - 5} more`}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                              </div>
                            ) : (
                              // Standard rendering for other action items
                              <>
                                {(showAllItems[idx] ? item.items : item.items.slice(0, 10)).map(ticket => (
                                  <a 
                                    key={ticket.key} 
                                    href={ticket.url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="category-item-row"
                                  >
                                    <span className="item-key">{ticket.key}</span>
                                    <span className="item-summary">{ticket.summary?.substring(0, 60)}{ticket.summary?.length > 60 ? '...' : ''}</span>
                                    <span className="item-component">{ticket.component}</span>
                                  </a>
                                ))}
                                {item.items.length > 10 && (
                                  <div 
                                    className="items-more clickable"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setShowAllItems(prev => ({ ...prev, [idx]: !prev[idx] }));
                                    }}
                                  >
                                    {showAllItems[idx] 
                                      ? '▲ Show less' 
                                      : `▼ +${item.items.length - 10} more items`}
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Charts Row - Status, Priority, and More Info */}
                <div className="action-charts-row">
                  {/* Horizontal Stacked Bar Chart by Status */}
                  <div className="action-chart-card">
                    <div className="action-chart-header">
                      <h4><Activity size={14} /> Work Items by Status</h4>
                      <span className="action-chart-badge">{Object.values(statusGroups).reduce((acc, s) => acc + s.stories + s.bugs, 0)} total</span>
                    </div>
                    <div className="action-stacked-bars-container">
                      {Object.keys(statusGroups).length > 0 ? (
                        (() => {
                          const sortedStatuses = Object.entries(statusGroups)
                            .sort((a, b) => (b[1].stories + b[1].bugs) - (a[1].stories + a[1].bugs));
                          const maxCount = Math.max(...sortedStatuses.map(([_, d]) => d.stories + d.bugs), 1);
                          const totalStories = sortedStatuses.reduce((acc, [_, d]) => acc + d.stories, 0);
                          const totalBugs = sortedStatuses.reduce((acc, [_, d]) => acc + d.bugs, 0);
                          
                          return (
                            <div className="stacked-bar-chart">
                              {/* Legend */}
                              <div className="stacked-bar-legend">
                                <span className="legend-item">
                                  <span className="legend-color story-color"></span>
                                  Stories ({totalStories})
                                </span>
                                <span className="legend-item">
                                  <span className="legend-color bug-color"></span>
                                  Bugs ({totalBugs})
                                </span>
                              </div>
                              
                              {/* Bars */}
                              <div className="stacked-bars">
                                {sortedStatuses.slice(0, 8).map(([status, statusData]) => {
                                  const total = statusData.stories + statusData.bugs;
                                  const storyPercent = total > 0 ? (statusData.stories / total) * 100 : 0;
                                  const bugPercent = total > 0 ? (statusData.bugs / total) * 100 : 0;
                                  const barWidth = (total / maxCount) * 100;
                                  
                                  return (
                                    <div key={status} className="stacked-bar-row">
                                      <div className="stacked-bar-label" title={status}>
                                        {status.length > 14 ? status.substring(0, 14) + '...' : status}
                                      </div>
                                      <div className="stacked-bar-track">
                                        <div 
                                          className="stacked-bar-fill"
                                          style={{ width: `${barWidth}%` }}
                                        >
                                          {statusData.stories > 0 && (
                                            <div 
                                              className="bar-segment story-segment"
                                              style={{ width: `${storyPercent}%` }}
                                              title={`${statusData.stories} Stories`}
                                            >
                                              {statusData.stories >= 2 && <span>{statusData.stories}</span>}
                                            </div>
                                          )}
                                          {statusData.bugs > 0 && (
                                            <div 
                                              className="bar-segment bug-segment"
                                              style={{ width: `${bugPercent}%` }}
                                              title={`${statusData.bugs} Bugs`}
                                            >
                                              {statusData.bugs >= 2 && <span>{statusData.bugs}</span>}
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                      <div className="stacked-bar-total">{total}</div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })()
                      ) : (
                        <div className="action-chart-empty">
                          <CheckCircle size={20} />
                          <span>No pending items</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* More Info Section - Grouped by Reporter */}
                  <div className="action-chart-card more-info-card" title="Items in 'More Info' status are awaiting additional details from the reporter. Follow up with reporters to unblock these items.">
                    <div className="action-chart-header">
                      <h4 title="Work items blocked pending clarification or additional information from the original reporter"><Info size={14} /> More Info Requested</h4>
                      <span className={`action-chart-badge ${Object.keys(moreInfoByReporter).length > 0 ? 'warning' : 'success'}`}>
                        {Object.values(moreInfoByReporter).reduce((acc, r) => acc + r.stories + r.bugs, 0)} items
                      </span>
                    </div>
                    <div className="more-info-reporters-list">
                      {Object.keys(moreInfoByReporter).length > 0 ? (
                        Object.entries(moreInfoByReporter)
                          .sort((a, b) => (b[1].stories + b[1].bugs) - (a[1].stories + a[1].bugs))
                          .slice(0, 6)
                          .map(([reporter, reporterData]) => (
                            <div key={reporter} className="more-info-reporter-row">
                              <div className="reporter-info">
                                <div className="reporter-avatar">
                                  {reporter.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase()}
                                </div>
                                <div className="reporter-details">
                                  <span className="reporter-name" title={reporter}>
                                    {reporter.length > 18 ? reporter.substring(0, 18) + '...' : reporter}
                                  </span>
                                  <span className="reporter-counts">
                                    {reporterData.stories > 0 && <span className="count-stories">{reporterData.stories} stories</span>}
                                    {reporterData.stories > 0 && reporterData.bugs > 0 && <span className="count-sep">•</span>}
                                    {reporterData.bugs > 0 && <span className="count-bugs">{reporterData.bugs} bugs</span>}
                                  </span>
                                </div>
                              </div>
                              <div className="reporter-total">{reporterData.stories + reporterData.bugs}</div>
                            </div>
                          ))
                      ) : (
                        <div className="action-chart-empty success">
                          <CheckCircle size={20} />
                          <span>No items need more info</span>
                        </div>
                      )}
                    </div>
                    {Object.keys(moreInfoByReporter).length > 6 && (
                      <div className="more-info-overflow">
                        +{Object.keys(moreInfoByReporter).length - 6} more reporters
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Inline Code Commits Section - Only shown after branch cut */}
            {expandedSections.codeCommits && commitsData?.branchCutPassed === true && (
              <div className="inline-commits-section">
                <div className="inline-commits-header">
                  <div className="inline-commits-title">
                    <Activity size={18} />
                    <span>Code Commits after Branch Cut</span>
                    {commitsData?.summary?.flaggedCommits > 0 && (
                      <span className="inline-commits-badge danger">⚠️ Review Required</span>
                    )}
                  </div>
                  <div className="inline-commits-meta">
                    <span>Branch Cut: {commitsData?.branchCutDate || 'N/A'}</span>
                    <span>•</span>
                    <span>Final Build: {commitsData?.finalBuildDate || 'N/A'}</span>
                    <span>•</span>
                    <span>{commitsData?.summary?.totalRepos || Object.keys(commitsData?.repos || {}).length || 0} repos tracked</span>
                    <span>•</span>
                    <span>{commitsData?.summary?.flaggedCommits > 0 ? `${commitsData.summary.flaggedCommits} flagged` : 'All clear'}</span>
                  </div>
                </div>
                
                {commitsLoading ? (
                  <div className="inline-commits-loading">
                    <RefreshCw size={20} className="spinning" />
                    <span>Loading commit data...</span>
                  </div>
                ) : commitsData?.repos && Object.keys(commitsData.repos).length > 0 ? (
                  <>
                  {/* Flagged Commits Chart with Expandable Commits */}
                  <div className="flagged-commits-chart">
                    <div className="flagged-chart-header">
                      <h4><AlertTriangle size={14} /> Flagged Commits by Repository</h4>
                      <span className="flagged-chart-total">
                        {commitsData.summary.flaggedCommits > 0 
                          ? `${commitsData.summary.flaggedCommits} between branch cut and final build` 
                          : 'All clear'}
                      </span>
                    </div>
                    <div className="flagged-chart-bars">
                      {(() => {
                        const allRepos = Object.entries(commitsData.repos)
                          .sort((a, b) => (b[1].stats?.flagged || 0) - (a[1].stats?.flagged || 0));
                        const maxFlagged = Math.max(...allRepos.map(([_, r]) => r.stats?.flagged || 0), 1);
                        
                        return allRepos.map(([repoKey, repoData]) => (
                          <div key={repoKey} className={`flagged-bar-group ${expandedRepos[repoKey] ? 'expanded' : ''}`}>
                            <div 
                              className={`flagged-bar-row ${repoData.stats?.flagged > 0 ? 'clickable has-flags' : ''}`}
                              onClick={() => repoData.stats?.flagged > 0 && setExpandedRepos(prev => ({ ...prev, [repoKey]: !prev[repoKey] }))}
                            >
                              <div className="flagged-bar-label" title={repoData.name}>
                                {repoData.stats?.flagged > 0 ? (
                                  <AlertTriangle size={12} className="icon-warning" />
                                ) : (
                                  <CheckCircle size={12} className="icon-success" />
                                )}
                                <span>{repoData.name.length > 18 ? repoData.name.substring(0, 18) + '...' : repoData.name}</span>
                                <a href={repoData.url} target="_blank" rel="noopener noreferrer" className="repo-link" onClick={e => e.stopPropagation()}>
                                  <ExternalLink size={10} />
                                </a>
                              </div>
                              <div className="flagged-bar-track">
                                {repoData.stats?.flagged > 0 ? (
                                  <div 
                                    className="flagged-bar-fill"
                                    style={{ width: `${(repoData.stats.flagged / maxFlagged) * 100}%` }}
                                  >
                                    <span className="flagged-bar-value">{repoData.stats.flagged}</span>
                                  </div>
                                ) : (
                                  <div className="flagged-bar-empty">
                                    <CheckCircle size={12} />
                                    <span>Clean</span>
                                  </div>
                                )}
                              </div>
                              <div className="flagged-bar-info">
                                <span className="flagged-bar-branch">{repoData.branch}</span>
                                {repoData.stats?.flagged > 0 && (
                                  expandedRepos[repoKey] ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                                )}
                              </div>
                            </div>
                            
                            {/* Expanded Commits List */}
                            {expandedRepos[repoKey] && repoData.flaggedCommits?.length > 0 && (
                              <div className="flagged-commits-list">
                                {repoData.flaggedCommits.slice(0, 10).map((commit, idx) => (
                                  <div key={idx} className="flagged-commit-row">
                                    <a 
                                      href={commit.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="commit-link"
                                    >
                                      <span className="commit-sha">{commit.sha}</span>
                                      <span className="commit-msg">{commit.message}</span>
                                      <span className="commit-author">{commit.author}</span>
                                      <span className="commit-date">{commit.formattedDate}</span>
                                    </a>
                                    <button 
                                      className="analyze-commit-btn"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        analyzeCommit(commit, repoData);
                                      }}
                                      title="Analyze commit for test impact"
                                    >
                                      <Search size={12} />
                                      Analyze
                                    </button>
                                  </div>
                                ))}
                                {repoData.flaggedCommits.length > 10 && (
                                  <a href={repoData.url} target="_blank" rel="noopener noreferrer" className="view-more-commits">
                                    View all {repoData.flaggedCommits.length} commits on GitHub →
                                  </a>
                                )}
                              </div>
                            )}
                          </div>
                        ));
                      })()}
                    </div>
                    <div className="flagged-chart-legend">
                      <span className="legend-note">Branch Cut: {commitsData.branchCutDate} • Click on flagged repos to view commits</span>
                    </div>
                  </div>
                  </>
                ) : (
                  <div className="inline-commits-empty">
                    <CheckCircle size={24} />
                    <span>No commits after branch cut - Release branch is stable</span>
                  </div>
                )}
              </div>
            )}

            {/* Success State - All Clear Banner */}
            {actionItems.length === 0 && totalOpen === 0 && (
              <div className="all-clear-banner success">
                <div className="clear-icon">
                  <CheckCircle size={24} />
                </div>
                <div className="clear-content">
                  <h3>🎉 All Clear for Release!</h3>
                  <p>No pending items or blockers. Release is ready to proceed.</p>
                </div>
              </div>
            )}

            {/* First Row: NPLANs List (full width, collapsible) */}
            <div className="nplans-row">
              <div className={`nplans-panel full-width ${expandedSections.nplans ? 'expanded' : 'collapsed'}`}>
                <div 
                  className="panel-header clickable"
                  onClick={() => setExpandedSections(prev => ({ ...prev, nplans: !prev.nplans }))}
                >
                  <div className="panel-title">
                    <ChevronDown 
                      size={16} 
                      className={`collapse-icon ${expandedSections.nplans ? 'expanded' : ''}`} 
                    />
                    <Package size={16} />
                    <span>Release Content for R{nplansData?.release || selectedRelease?.replace(/[^\d]/g, '').split('.')[0]}</span>
                    {nplansData?.total > 0 && (
                      <span className="panel-count-badge">{nplansData.total}</span>
                    )}
                  </div>
                  <div className="panel-right">
                    {/* Status Summary inline */}
                    {nplansData?.items?.length > 0 && (
                      <div className="nplans-status-inline">
                        {nplansData.by_status?.SHIPPED > 0 && (
                          <span className="status-pill shipped">
                            <CheckCircle size={12} /> {nplansData.by_status.SHIPPED} Shipped
                          </span>
                        )}
                        {nplansData.by_status?.ONTRACK > 0 && (
                          <span className="status-pill ontrack">
                            <TrendingUp size={12} /> {nplansData.by_status.ONTRACK} On Track
                          </span>
                        )}
                        {nplansData.by_status?.TBD > 0 && (
                          <span className="status-pill tbd">
                            <Clock size={12} /> {nplansData.by_status.TBD} TBD
                          </span>
                        )}
                        {/* NPLAN Bugs Summary */}
                        {nplanBugsData?.summary?.open_bugs > 0 && (
                          <span className="status-pill bugs">
                            <Bug size={12} /> {nplanBugsData.summary.open_bugs} Open Bugs
                          </span>
                        )}
                      </div>
                    )}
                    {/* Expand to Modal Button */}
                    <button
                      className="expand-modal-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailModal('releaseContent');
                        setDetailModalFilter('');
                        setDetailModalSort({ field: null, direction: 'asc' });
                        setDetailModalPage(1);
                      }}
                      title="Open in detailed view"
                    >
                      <Maximize2 size={16} />
                    </button>
                  </div>
                </div>
                
                {expandedSections.nplans && (
                  <>
                    {nplansLoading ? (
                      <div className="panel-loading">
                        <RefreshCw size={18} className="spinning" />
                        <span>Loading NPLANs...</span>
                      </div>
                    ) : nplansError ? (
                      <div className="panel-error">
                        <AlertTriangle size={18} />
                        <span>Unable to load</span>
                      </div>
                    ) : nplansData?.items?.length > 0 ? (
                      <div className="nplans-list-container">
                        {/* Table Header */}
                        <div className="nplans-list-header nplans-list-header-with-bugs">
                          <div className="nplans-col expand"></div>
                          <div className="nplans-col id">ID</div>
                          <div className="nplans-col desc">Description</div>
                          <div className="nplans-col status">Status</div>
                          <div className="nplans-col bugs">Bugs</div>
                          <div className="nplans-col merge-status">Merge Status</div>
                          <div className="nplans-col comments">Comments</div>
                        </div>
                        {/* Table Body */}
                        <div className="nplans-list-body">
                          {nplansData.items.map((item, idx) => {
                            const nplanId = item.id;
                            const bugsForNplan = nplanBugsData?.nplan_bugs?.[nplanId];
                            const bugCount = bugsForNplan?.total || 0;
                            const openBugCount = bugsForNplan?.open || 0;
                            
                            // Check for OPEN Critical/Blocker bugs only (not closed ones)
                            const closedStatuses = ['Closed', 'Resolved', 'Done', 'Verified', 'Won\'t Fix', 'Duplicate', 'Cannot Reproduce'];
                            const openBugs = bugsForNplan?.bugs?.filter(bug => !closedStatuses.includes(bug.status)) || [];
                            const hasOpenCritical = openBugs.some(bug => bug.priority === 'Critical' || bug.priority === 'Blocker');
                            const hasOpenHigh = openBugs.some(bug => bug.priority === 'High');
                            
                            const isExpanded = expandedNplanBugs[nplanId] || false;
                            
                            return (
                              <React.Fragment key={idx}>
                                <div 
                                  className={`nplans-list-row nplans-list-row-with-bugs ${item.status?.toLowerCase().replace(' ', '-')} ${bugCount > 0 ? 'has-bugs' : ''} ${isExpanded ? 'expanded' : ''}`}
                                  onClick={() => bugCount > 0 && setExpandedNplanBugs(prev => ({ ...prev, [nplanId]: !prev[nplanId] }))}
                                  style={{ cursor: bugCount > 0 ? 'pointer' : 'default' }}
                                >
                                  <div className="nplans-col expand">
                                    {bugCount > 0 && (
                                      <ChevronRight 
                                        size={14} 
                                        className={`expand-icon ${isExpanded ? 'expanded' : ''}`}
                                      />
                                    )}
                                  </div>
                                  <div className="nplans-col id">
                                    {item.jira_url && item.id ? (
                                      <a 
                                        href={item.jira_url} 
                                        target="_blank" 
                                        rel="noopener noreferrer"
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        {item.id}
                                      </a>
                                    ) : item.id ? (
                                      <span>{item.id}</span>
                                    ) : (
                                      <span 
                                        className="missing-id" 
                                        title={item.raw_entry ? `Raw data: ${item.raw_entry}` : 'No JIRA ID found in source data'}
                                      >
                                        —
                                      </span>
                                    )}
                                  </div>
                                  <div className="nplans-col desc" title={item.description}>
                                    {item.description || '—'}
                                  </div>
                                  <div className="nplans-col status">
                                    <span className={`nplan-status-tag ${item.status?.toLowerCase().replace(' ', '-')}`}>
                                      {item.status === 'SHIPPED' && <CheckCircle size={12} />}
                                      {item.status === 'ONTRACK' && <TrendingUp size={12} />}
                                      {item.status === 'TBD' && <Clock size={12} />}
                                      {item.status === 'ON HOLD' && <Pause size={12} />}
                                      {item.status || 'TBD'}
                                    </span>
                                  </div>
                                  <div className="nplans-col bugs">
                                    {nplanBugsLoading ? (
                                      <RefreshCw size={12} className="spinning" />
                                    ) : bugCount > 0 ? (
                                      (() => {
                                        // Count open bugs by priority
                                        const openPriorityCounts = {};
                                        openBugs.forEach(bug => {
                                          openPriorityCounts[bug.priority] = (openPriorityCounts[bug.priority] || 0) + 1;
                                        });
                                        
                                        // Critical/Blocker count (actionable urgent bugs)
                                        const criticalBlockerCount = (openPriorityCounts['Critical'] || 0) + (openPriorityCounts['Blocker'] || 0);
                                        const otherOpenCount = openBugCount - criticalBlockerCount;
                                        
                                        // Build detailed tooltip
                                        let tooltipLines = [];
                                        
                                        if (hasOpenCritical) {
                                          tooltipLines.push(`⚠️ ${criticalBlockerCount} Critical/Blocker bug${criticalBlockerCount > 1 ? 's' : ''} need attention!`);
                                          if (otherOpenCount > 0) {
                                            tooltipLines.push(`+ ${otherOpenCount} Major/Minor open bug${otherOpenCount > 1 ? 's' : ''}`);
                                          }
                                        } else if (openBugCount > 0) {
                                          tooltipLines.push(`${openBugCount} Open bug${openBugCount > 1 ? 's' : ''}`);
                                        } else {
                                          tooltipLines.push('✓ All bugs resolved');
                                        }
                                        
                                        tooltipLines.push('─────────────');
                                        tooltipLines.push(`Total: ${bugCount} (${openBugCount} open, ${bugCount - openBugCount} closed)`);
                                        
                                        if (openBugCount > 0) {
                                          tooltipLines.push('─────────────');
                                          tooltipLines.push('Open by Priority:');
                                          const priorityOrder = ['Blocker', 'Critical', 'High', 'Major', 'Medium', 'Minor', 'Low'];
                                          priorityOrder.forEach(p => {
                                            if (openPriorityCounts[p]) {
                                              const marker = (p === 'Blocker' || p === 'Critical') ? '🔴' : (p === 'High' ? '🟠' : '🟡');
                                              tooltipLines.push(`  ${marker} ${p}: ${openPriorityCounts[p]}`);
                                            }
                                          });
                                        }
                                        
                                        tooltipLines.push('─────────────');
                                        tooltipLines.push('Click row to see bug details');
                                        
                                        const tooltip = tooltipLines.join('\n');
                                        
                                        // Display: Show critical/blocker count if any, else show open count
                                        const displayCount = hasOpenCritical ? criticalBlockerCount : openBugCount;
                                        
                                        return (
                                          <span 
                                            className={`nplan-bug-badge ${hasOpenCritical ? 'critical' : hasOpenHigh ? 'high' : openBugCount > 0 ? 'open' : 'resolved'}`}
                                            title={tooltip}
                                          >
                                            <Bug size={11} />
                                            <span>{displayCount}</span>
                                            {hasOpenCritical && <span className="priority-indicator critical">!</span>}
                                            {otherOpenCount > 0 && hasOpenCritical && (
                                              <span className="other-open-indicator" title={`+ ${otherOpenCount} Major/Minor open`}>+{otherOpenCount}</span>
                                            )}
                                          </span>
                                        );
                                      })()
                                    ) : (
                                      <span className="no-bugs" title="No bugs linked to this NPLAN">—</span>
                                    )}
                                  </div>
                                  {(() => {
                                    const devStatus = nplanDevStatusData?.nplan_dev_status?.[nplanId];
                                    const mergeStatus = devStatus?.merge_status || '';
                                    const mergedCount = devStatus?.merged || 0;
                                    const totalItems = devStatus?.total_items || 0;
                                    const statusClass = mergeStatus === 'MERGED' ? 'merged' : mergeStatus === 'PARTIAL' ? 'partial' : mergeStatus === 'OPEN' ? 'pr-open' : 'none';
                                    const label = mergeStatus === 'MERGED' ? 'MERGED' : mergeStatus === 'PARTIAL' ? 'PARTIAL' : mergeStatus === 'OPEN' ? 'OPEN' : 'NONE';
                                    return (
                                      <div className="nplans-col merge-status">
                                        {nplanDevStatusLoading ? (
                                          <RefreshCw size={12} className="spinning" />
                                        ) : !devStatus || totalItems === 0 ? (
                                          <span className="no-bugs" title="No sub-tickets found">—</span>
                                        ) : (
                                          <span
                                            className={`nplan-merge-badge ${statusClass}`}
                                            title={`${mergedCount} of ${totalItems} sub-tickets merged`}
                                          >
                                            {label}
                                            <span className="merge-count"> {mergedCount}/{totalItems}</span>
                                          </span>
                                        )}
                                      </div>
                                    );
                                  })()}
                                  <div className="nplans-col comments" title={item.notes || ''}>
                                    {item.notes || '—'}
                                  </div>
                                </div>

                                {/* Expanded Bug Details Panel */}
                                {isExpanded && bugCount > 0 && (
                                  <div className="nplan-bugs-panel">
                                    <div className="nplan-bugs-header">
                                      <Bug size={14} />
                                      <span>{nplanId} Linked Bugs</span>
                                      <span className="bugs-count">({openBugCount} open, {bugCount} total)</span>
                                    </div>
                                    <div className="nplan-bugs-table">
                                      <div className="nplan-bugs-table-header">
                                        <div className="bug-col key">Key</div>
                                        <div className="bug-col summary">Summary</div>
                                        <div className="bug-col status">Status</div>
                                        <div className="bug-col priority">Priority</div>
                                        <div className="bug-col assignee">Assignee</div>
                                        <div className="bug-col merge-status">Merge Status</div>
                                      </div>
                                      <div className="nplan-bugs-table-body">
                                        {bugsForNplan?.bugs?.map((bug, bugIdx) => {
                                          const bugDevInfo = nplanDevStatusData?.nplan_dev_status?.[nplanId]?.items_by_key?.[bug.key];
                                          const bugMergeStatus = bugDevInfo?.merge_status || '';
                                          const bugMergeClass = bugMergeStatus === 'MERGED' ? 'merged' : bugMergeStatus === 'PARTIAL' ? 'partial' : bugMergeStatus === 'OPEN' ? 'pr-open' : bugMergeStatus === 'COMMITTED' ? 'committed' : bugMergeStatus === 'NONE' ? 'none' : '';
                                          const bugMergeLabel = bugMergeStatus === 'MERGED' ? 'MERGED' : bugMergeStatus === 'PARTIAL' ? 'PARTIAL' : bugMergeStatus === 'OPEN' ? 'OPEN' : bugMergeStatus === 'COMMITTED' ? 'COMMITTED' : bugMergeStatus === 'DECLINED' ? 'DECLINED' : bugMergeStatus === 'NONE' ? 'NONE' : '';
                                          const bugMergeTooltip = bugDevInfo ? `${bugDevInfo.pr_count} PRs, ${bugDevInfo.commit_count || 0} commits` : 'Dev status not loaded';
                                          return (
                                          <div key={bugIdx} className="nplan-bug-row">
                                            <div className="bug-col key">
                                              <a
                                                href={bug.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                {bug.key}
                                              </a>
                                            </div>
                                            <div className="bug-col summary" title={bug.summary}>
                                              {bug.summary}
                                            </div>
                                            <div className="bug-col status">
                                              <span className={`bug-status-tag ${bug.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                                {bug.status}
                                              </span>
                                            </div>
                                            <div className="bug-col priority">
                                              <span className={`bug-priority-tag ${bug.priority?.toLowerCase()}`}>
                                                {bug.priority}
                                              </span>
                                            </div>
                                            <div className="bug-col assignee" title={bug.assignee}>
                                              {bug.assignee || 'Unassigned'}
                                            </div>
                                            <div className="bug-col merge-status">
                                              {nplanDevStatusLoading ? (
                                                <RefreshCw size={10} className="spinning" />
                                              ) : bugMergeLabel ? (
                                                <span className={`nplan-merge-badge small ${bugMergeClass}`} title={bugMergeTooltip}>
                                                  {bugMergeLabel}
                                                </span>
                                              ) : (
                                                <span className="no-bugs">—</span>
                                              )}
                                            </div>
                                          </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  </div>
                                )}
                              </React.Fragment>
                            );
                          })}
                        </div>
                      </div>
                    ) : (
                      <div className="panel-empty-inline">
                        <Package size={16} />
                        <span>No NPLANs for this release</span>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Row 3: Workload Distribution Charts */}
            <div className="workload-charts-row">
              {/* Developer Workload Chart - All Assignees */}
              <div className="workload-chart workload-chart-scrollable">
                <div className="chart-header">
                  <h3 title="Work items yet to be resolved or completed by each developer">
                    <Users size={16} />
                    <a 
                      href={`https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(`(fixVersion = "${selectedRelease.replace('R', '')}.0.0") AND (component = "NS Client (NSC)" AND type IN (Bug, Story, Task) AND status NOT IN (Resolved, Closed, "Pending Close"))`)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="chart-title-link"
                    >
                      Developer Workload
                    </a>
                    <button
                      className="expand-modal-btn-inline"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDetailModal('devWorkload');
                        setDetailModalFilter('');
                        setDetailModalSort({ field: null, direction: 'asc' });
                        setDetailModalPage(1);
                      }}
                      title="Open in detailed view"
                    >
                      <Maximize2 size={14} />
                    </button>
                  </h3>
                  <span className="chart-subtitle">{totalDevItems} items ({allAssignees.length} assignees)</span>
                </div>
                <div className="horizontal-bars horizontal-bars-scrollable">
                  {allAssignees.map(([name, data], idx) => (
                    <React.Fragment key={name}>
                      <div 
                        className={`bar-row clickable ${expandedWorkloadAssignee === name ? 'expanded' : ''}`}
                        onClick={() => setExpandedWorkloadAssignee(expandedWorkloadAssignee === name ? null : name)}
                      >
                        <div className="bar-name-only" title={`${name}: ${data.stories} stories, ${data.bugs} bugs, ${data.review} in review`}>
                          {name}
                        </div>
                        <div className="bar-container">
                          <div className="stacked-bar">
                            <div 
                              className="bar-segment stories" 
                              style={{ width: `${(data.stories / maxWorkload) * 100}%` }}
                              title={`${data.stories} stories`}
                            ></div>
                            <div 
                              className="bar-segment bugs" 
                              style={{ width: `${(data.bugs / maxWorkload) * 100}%` }}
                              title={`${data.bugs} bugs`}
                            ></div>
                            <div 
                              className="bar-segment review" 
                              style={{ width: `${(data.review / maxWorkload) * 100}%` }}
                              title={`${data.review} in review`}
                            ></div>
                          </div>
                          <span className="bar-total clickable-count">{data.total}</span>
                          {expandedWorkloadAssignee === name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </div>
                      </div>
                      {expandedWorkloadAssignee === name && data.tickets?.length > 0 && (
                        <div className="inline-ticket-list">
                          {data.tickets.map(ticket => (
                            <a 
                              key={ticket.key} 
                              href={ticket.url || `https://your-org.atlassian.net/browse/${ticket.key}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-ticket-row"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <span className="ticket-key">{ticket.key}</span>
                              <span className="ticket-summary">{ticket.summary}</span>
                              <span className={`ticket-type ${ticket.type?.toLowerCase()}`}>{ticket.type}</span>
                              <span className={`ticket-priority ${ticket.priority?.toLowerCase()}`}>{ticket.priority}</span>
                            </a>
                          ))}
                        </div>
                      )}
                    </React.Fragment>
                  ))}
                </div>
                <div className="chart-legend">
                  <span className="legend-item"><span className="dot stories"></span>Stories</span>
                  <span className="legend-item"><span className="dot bugs"></span>Bugs</span>
                  <span className="legend-item"><span className="dot review"></span>Review</span>
                </div>
              </div>

              {/* QA Backlog Chart - All QA Assignees */}
              <div className="workload-chart workload-chart-scrollable">
                <div className="chart-header">
                  <h3 title="Resolved stories and bugs waiting for QA verification">
                    <CheckSquare size={16} />
                    <a 
                      href={`https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(`(fixVersion = "${selectedRelease.replace('R', '')}.0.0") AND (component = "NS Client (NSC)" AND type IN (Bug, Story, Task) AND status IN (Resolved, "Pending Close"))`)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="chart-title-link"
                    >
                      QA Backlog
                    </a>
                    <button
                      className="expand-modal-btn-inline"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDetailModal('qaBacklog');
                        setDetailModalFilter('');
                        setDetailModalSort({ field: null, direction: 'asc' });
                        setDetailModalPage(1);
                      }}
                      title="Open in detailed view"
                    >
                      <Maximize2 size={14} />
                    </button>
                  </h3>
                  <span className="chart-subtitle">{totalQAItems} items to verify ({allQAs.length} assignees)</span>
                </div>
                <div className="horizontal-bars horizontal-bars-scrollable">
                  {allQAs.length > 0 ? allQAs.map(([qa, qadata]) => (
                    <React.Fragment key={qa}>
                      <div 
                        className={`bar-row clickable ${expandedQAAssignee === qa ? 'expanded' : ''}`}
                        onClick={() => setExpandedQAAssignee(expandedQAAssignee === qa ? null : qa)}
                      >
                        <div className="bar-name-only" title={`${qa}: ${qadata.stories} stories, ${qadata.bugs} bugs`}>
                          {qa}
                        </div>
                        <div className="bar-container">
                          <div className="stacked-bar">
                            <div 
                              className="bar-fill stories" 
                              style={{ width: `${(qadata.stories / maxQAWork) * 100}%` }}
                              title={`${qadata.stories} stories`}
                            ></div>
                            <div 
                              className="bar-fill bugs" 
                              style={{ width: `${(qadata.bugs / maxQAWork) * 100}%` }}
                              title={`${qadata.bugs} bugs`}
                            ></div>
                          </div>
                          <span className="bar-total clickable-count">{qadata.total}</span>
                          {expandedQAAssignee === qa ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </div>
                      </div>
                      {expandedQAAssignee === qa && qadata.tickets?.length > 0 && (
                        <div className="inline-ticket-list">
                          {qadata.tickets.map(ticket => (
                            <a 
                              key={ticket.key} 
                              href={ticket.url || `https://your-org.atlassian.net/browse/${ticket.key}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-ticket-row"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <span className="ticket-key">{ticket.key}</span>
                              <span className="ticket-summary">{ticket.summary}</span>
                              <span className={`ticket-type ${ticket.type?.toLowerCase()}`}>{ticket.type}</span>
                              <span className={`ticket-status ${ticket.status?.toLowerCase().replace(/\s+/g, '-')}`}>{ticket.status}</span>
                            </a>
                          ))}
                        </div>
                      )}
                    </React.Fragment>
                  )) : (
                    <div className="empty-chart">
                      <CheckCircle size={24} />
                      <span>No items pending QA</span>
                    </div>
                  )}
                </div>
                {allQAs.length > 0 && (
                  <div className="chart-legend">
                    <span className="legend-item"><span className="dot stories"></span>Stories</span>
                    <span className="legend-item"><span className="dot bugs"></span>Bugs</span>
                  </div>
                )}
              </div>

            </div>
          </div>
        );
      })()}

      {/* ============================================
          MILESTONE INFO & DETAIL PANEL - When specific milestone selected
          ============================================ */}
      {selectedMilestone !== 'all' && milestoneDescriptions[selectedMilestone] && (
        <>
          <div className="rr-milestone-info">
            <div className="milestone-header">
              <span className="milestone-icon">{milestoneDescriptions[selectedMilestone].icon}</span>
              <h3>{milestoneDescriptions[selectedMilestone].label}</h3>
            </div>
            <p className="milestone-desc">{milestoneDescriptions[selectedMilestone].description}</p>
            <div className="milestone-requirement">
              <strong>Requirement:</strong> {milestoneDescriptions[selectedMilestone].requirement}
            </div>
          </div>

          {/* MILESTONE DETAIL PANEL */}
          {milestoneLoading && (
            <div className="milestone-detail-panel loading">
              <RefreshCw size={24} className="spinning" />
              <span>Loading {milestoneDescriptions[selectedMilestone].label} data...</span>
        </div>
                  )}

          {milestoneError && !selectedMilestone.startsWith('day') && (
            <div className="milestone-detail-panel error">
              <AlertTriangle size={24} />
              <span>{milestoneError}</span>
          </div>
          )}

          {/* IRR MILESTONE DETAIL */}
          {selectedMilestone === 'irr' && milestoneData && !milestoneLoading && (() => {
            // Filter components based on selected component
            const filteredComponents = selectedComponent === 'all' 
              ? milestoneData.components 
              : { [selectedComponent]: milestoneData.components?.[selectedComponent] };
            
            // Calculate filtered summary
            const filteredSummary = selectedComponent === 'all' 
              ? milestoneData.summary 
              : {
                  totalStories: filteredComponents[selectedComponent]?.counts?.total || 0,
                  resolvedOnTime: filteredComponents[selectedComponent]?.counts?.resolvedOnTime || 0,
                  totalMissed: filteredComponents[selectedComponent]?.counts?.totalMissed || 0,
                  resolvedAfterDeadline: filteredComponents[selectedComponent]?.counts?.resolvedAfterDeadline || 0,
                  stillOpen: filteredComponents[selectedComponent]?.counts?.stillOpen || 0
                };
            
            // Calculate filtered quality metrics
            const filteredOnTimeRate = filteredSummary.totalStories > 0 
              ? Math.round((filteredSummary.resolvedOnTime / filteredSummary.totalStories) * 100) 
              : 0;
            const filteredRecoveryRate = filteredSummary.totalMissed > 0 
              ? Math.round(((filteredSummary.resolvedAfterDeadline || 0) / filteredSummary.totalMissed) * 100) 
              : 100;
            
            // Status for visual styling
            const overallStatus = filteredSummary.stillOpen === 0 && filteredSummary.totalMissed === 0 ? 'excellent' 
              : filteredSummary.stillOpen === 0 ? 'good' 
              : filteredSummary.stillOpen <= 2 ? 'warning' : 'critical';

            return (
            <div className={`milestone-detail-panel irr-panel-v2 ${milestonePanelCollapsed ? 'collapsed' : ''}`}>
              {/* Collapse Toggle Header */}
              <div className="milestone-panel-header" onClick={() => setMilestonePanelCollapsed(!milestonePanelCollapsed)}>
                <div className="panel-header-left">
                  <span className={`panel-status-dot ${overallStatus}`} />
                  <span className="panel-title">IRR Summary</span>
                  <span className="milestone-jql-info" onClick={(e) => e.stopPropagation()}>
                    <Info size={14} />
                    <span className="milestone-jql-tooltip">
                      <strong>Data Source</strong>
                      <p>Tracks all Stories and Bugs for {selectedRelease} NS Client component.</p>
                      <strong>JQL Query (All Items)</strong>
                      <code>{milestoneData?.jql?.all_items || `(fixVersion = "${milestoneData?.fixVersion}") AND (project = ENG AND component = "NS Client (NSC)" AND type not in (EPIC, Sub-task, task, Escalation))`}</code>
                      <strong>Resolved After IRR</strong>
                      <code>{milestoneData?.jql?.resolved_late || `${milestoneData?.jql?.all_items || ''} AND resolved >= "${milestoneData?.milestoneDate}"`}</code>
                      <small>Copy these queries to JIRA to verify the data</small>
                    </span>
                  </span>
                  <span className="panel-score">{filteredOnTimeRate}% On-Time</span>
          </div>
                <ChevronDown size={18} className={`panel-chevron ${milestonePanelCollapsed ? '' : 'rotated'}`} />
        </div>

              {/* Collapsible Content */}
              {!milestonePanelCollapsed && (
              <>
              {/* Two Column Layout */}
              <div className="irr-layout">
                {/* LEFT: Visual Score Card */}
                <div className="irr-score-section">
                  <div className={`irr-score-ring ${overallStatus}`}>
                    <svg viewBox="0 0 100 100" className="score-svg">
                      <circle className="score-bg" cx="50" cy="50" r="42" fill="none" strokeWidth="8" />
                      <circle 
                        className="score-progress" 
                        cx="50" cy="50" r="42" 
                        fill="none" 
                        strokeWidth="8" 
                        strokeDasharray={filteredOnTimeRate >= 100 ? "none" : `${filteredOnTimeRate * 2.64} 264`}
                        strokeLinecap="round"
                      />
                    </svg>
                    <div className="score-center">
                      <span className="score-value">{filteredOnTimeRate}</span>
                      <span className="score-percent">%</span>
                    </div>
                  </div>
                  <div className="score-label">On-Time Rate</div>
                  <div className="score-sublabel">
                    {filteredSummary.resolvedOnTime} of {filteredSummary.totalStories} stories
                  </div>
                  
                  {/* Status Badge */}
                  <div className={`irr-status-badge ${overallStatus}`}>
                    {overallStatus === 'excellent' && <><CheckCircle size={16} /> Excellent</>}
                    {overallStatus === 'good' && <><CheckCircle size={16} /> Recovered</>}
                    {overallStatus === 'warning' && <><AlertTriangle size={16} /> Needs Attention</>}
                    {overallStatus === 'critical' && <><XCircle size={16} /> At Risk</>}
                  </div>
                </div>

                {/* RIGHT: Details */}
                <div className="irr-details-section">
                  {/* Header with Milestone Dropdown */}
                  <div className="irr-header-row">
                    <div className="irr-date-info">
                      <Calendar size={16} />
                      <span>IRR: {new Date(milestoneData.milestoneDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      {milestoneData.irrPassed ? (
                        <span className="days-badge passed">+{milestoneData.daysSinceIRR}d ago</span>
                      ) : (
                        <span className="days-badge upcoming">{milestoneData.daysToIRR}d left</span>
                      )}
                    </div>
                    {selectedComponent !== 'all' && (
                      <span className="component-tag">{selectedComponent}</span>
                  )}
      </div>

                  {/* Pie Chart + Stats */}
                  <div className="irr-pie-section">
                    <div className="mini-pie-chart">
                      <svg viewBox="0 0 100 100" className="pie-svg">
                        {/* On Time slice */}
                        <circle 
                          cx="50" cy="50" r="40"
                          fill="transparent"
                          stroke="var(--success)"
                          strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.resolvedOnTime / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          transform="rotate(-90 50 50)"
                        />
                        {/* Resolved After slice */}
                        <circle 
                          cx="50" cy="50" r="40"
                          fill="transparent"
                          stroke="var(--warning)"
                          strokeWidth="20"
                          strokeDasharray={`${((filteredSummary.resolvedAfterDeadline || 0) / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-((filteredSummary.resolvedOnTime / Math.max(filteredSummary.totalStories, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)"
                        />
                        {/* Still Open slice */}
                        <circle 
                          cx="50" cy="50" r="40"
                          fill="transparent"
                          stroke="var(--danger)"
                          strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.stillOpen / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-(((filteredSummary.resolvedOnTime + (filteredSummary.resolvedAfterDeadline || 0)) / Math.max(filteredSummary.totalStories, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)"
                        />
                        <text x="50" y="50" textAnchor="middle" dy="0.3em" className="pie-center-text">
                          {filteredSummary.totalStories}
                        </text>
                      </svg>
                    </div>
                    <div className="pie-legend">
                      <div 
                        className="legend-row success"
                        onClick={() => filteredSummary.resolvedOnTime > 0 && setExpandedStatBox(null)}
                      >
                        <span className="legend-dot"></span>
                        <span className="legend-label">On Time</span>
                        <span className="legend-value">{filteredSummary.resolvedOnTime}</span>
                      </div>
                      <div 
                        className={`legend-row warning clickable ${expandedStatBox === 'missed' ? 'active' : ''}`}
                        onClick={() => {
                          if (filteredSummary.totalMissed > 0) {
                            const newState = expandedStatBox === 'missed' ? null : 'missed';
                            setExpandedStatBox(newState);
                            // Auto-expand YOUR_PRODUCT when opening
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'YOUR_PRODUCT': true }));
                          }
                        }}
                      >
                        <span className="legend-dot"></span>
                        <span className="legend-label">Resolved Late</span>
                        <span className="legend-value">{filteredSummary.resolvedAfterDeadline || 0}</span>
                        {filteredSummary.totalMissed > 0 && <ChevronRight size={12} />}
                      </div>
                      <div 
                        className={`legend-row danger clickable ${expandedStatBox === 'open' ? 'active' : ''}`}
                        onClick={() => {
                          if (filteredSummary.stillOpen > 0) {
                            const newState = expandedStatBox === 'open' ? null : 'open';
                            setExpandedStatBox(newState);
                            // Auto-expand YOUR_PRODUCT when opening
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'YOUR_PRODUCT': true }));
                          }
                        }}
                      >
                        <span className="legend-dot"></span>
                        <span className="legend-label">Still Open</span>
                        <span className="legend-value">{filteredSummary.stillOpen}</span>
                        {filteredSummary.stillOpen > 0 && <ChevronRight size={12} />}
                      </div>
                    </div>
                  </div>

                  {/* Recovery Progress (if applicable) */}
                  {milestoneData.irrPassed && filteredSummary.totalMissed > 0 && (
                    <div className="irr-recovery">
                      <div className="recovery-header">
                        <span>Recovery Progress</span>
                        <span className={`recovery-rate ${filteredRecoveryRate >= 80 ? 'success' : ''}`}>{filteredRecoveryRate}%</span>
                      </div>
                      <div className="recovery-bar">
                        <div 
                          className={`recovery-fill ${filteredRecoveryRate >= 80 ? 'success' : filteredRecoveryRate >= 50 ? 'warning' : 'danger'}`} 
                          style={{ width: `${filteredRecoveryRate}%` }}
                        />
                      </div>
                      <div className="recovery-labels">
                        <span>{filteredSummary.resolvedAfterDeadline || 0} resolved since IRR</span>
                        <span>{filteredSummary.stillOpen} still open</span>
                </div>
                      </div>
                  )}

                  {/* Assessment Box */}
                  <div className={`irr-assessment ${overallStatus}`}>
                    <strong>Assessment:</strong>
                    {overallStatus === 'excellent' && ' All stories resolved on time. Excellent release quality.'}
                    {overallStatus === 'good' && ` All missed items now recovered. Release back on track.`}
                    {overallStatus === 'warning' && ` ${filteredSummary.stillOpen} item(s) need attention before Branch Cut.`}
                    {overallStatus === 'critical' && ` Release at risk. ${filteredSummary.stillOpen} items overdue. Escalation required.`}
                  </div>
                </div>
              </div>

              {/* Component Breakdown - Only shown when stat box is clicked */}
              {expandedStatBox && filteredComponents && Object.keys(filteredComponents).filter(k => filteredComponents[k]).length > 0 && (
                <div className="milestone-component-breakdown collapsible-panel">
                  <div className="breakdown-header-row">
                    <h4>
                      <Users size={16} /> 
                      {expandedStatBox === 'open' ? 'Still Open Issues' : 'Missed IRR Deadline'}
                      {selectedComponent !== 'all' && ` (${selectedComponent})`}
                    </h4>
                    <button className="close-breakdown" onClick={() => setExpandedStatBox(null)}>
                      <XCircle size={16} />
                    </button>
                  </div>
                  
                  {Object.entries(filteredComponents)
                    .filter(([_, compData]) => compData) // Filter out undefined
                    .filter(([_, compData]) => {
                      // Filter based on which stat box is clicked
                      if (expandedStatBox === 'open') return compData.counts?.stillOpen > 0 || milestoneData?.issues?.length > 0;
                      if (expandedStatBox === 'missed') return compData.counts?.totalMissed > 0;
                      return false;
                    })
                    .map(([compName, compData]) => (
                    <div key={compName} className="component-section">
                      <div 
                        className="component-header clickable"
                        onClick={() => setExpandedMilestoneComponents(prev => ({ 
                          ...prev, 
                          [compName]: !prev[compName] 
                        }))}
                      >
                        <span className="component-name">{compName}</span>
                        <div className="component-counts">
                          {expandedStatBox === 'open' && (compData.counts?.stillOpen > 0 || milestoneData?.issues?.length > 0) && (
                            <span className="count-pill danger">{compData.counts?.stillOpen || milestoneData?.issues?.length || 0} open</span>
                          )}
                          {expandedStatBox === 'missed' && (
                            <>
                              {compData.counts?.stillOpen > 0 && (
                                <span className="count-pill danger">{compData.counts.stillOpen} open</span>
                              )}
                              {compData.counts?.resolvedAfterDeadline > 0 && (
                                <a 
                                  href={`https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(milestoneData?.jql?.resolved_late || `(fixVersion = "${milestoneData?.fixVersion}") AND (project = ENG AND component = "NS Client (NSC)" AND status in (resolved, closed, "Pending Close") AND type not in (EPIC, Sub-task, task, Escalation) AND resolved > "${milestoneData?.milestoneDate}")`)}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="count-pill success clickable-pill"
                                  onClick={(e) => e.stopPropagation()}
                                  title="View in JIRA"
                                >
                                  {compData.counts.resolvedAfterDeadline} resolved <ExternalLink size={10} />
                                </a>
                              )}
                            </>
                          )}
                      </div>
                        {expandedMilestoneComponents[compName] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </div>
                      
                      {expandedMilestoneComponents[compName] && (
                        <div className="component-issues">
                          {/* Still Open Issues - Show for both 'open' and 'missed' */}
                          {(expandedStatBox === 'open' || expandedStatBox === 'missed') && milestoneData?.issues?.length > 0 && (
                            <div className="issue-group">
                              <h5 className="issue-group-title danger">
                                <XCircle size={14} /> Still Open ({milestoneData.issues.length})
                              </h5>
                              <div className="issue-list">
                                {milestoneData.issues.map(issue => (
                                  <a 
                                    key={issue.key} 
                                    href={issue.url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="issue-row"
                                  >
                                    <span className="issue-key">{issue.key}</span>
                                    <span className="issue-summary">{issue.summary}</span>
                                    <span className="issue-assignee">{issue.assignee}</span>
                                    <span className={`issue-priority ${issue.priority?.toLowerCase()}`}>{issue.priority}</span>
                                    <span className="issue-type">{issue.type}</span>
                                  </a>
                                ))}
                      </div>
                    </div>
                  )}
                          
                          {/* Resolved After IRR - Only show for 'missed' */}
                          {expandedStatBox === 'missed' && milestoneData?.lateIssues?.length > 0 && (
                            <div className="issue-group">
                              <h5 className="issue-group-title success">
                                <CheckCircle size={14} /> Resolved After IRR ({milestoneData.lateIssues.length})
                              </h5>
                              <div className="issue-list">
                                {milestoneData.lateIssues.map(issue => (
                                  <a 
                                    key={issue.key} 
                                    href={issue.url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="issue-row resolved"
                                  >
                                    <span className="issue-key">{issue.key}</span>
                                    <span className="issue-summary">{issue.summary}</span>
                                    <span className="issue-assignee">{issue.assignee}</span>
                                    <span className="issue-type">{issue.type}</span>
                                  </a>
                                ))}
                </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* All Clear State */}
              {filteredSummary.totalMissed === 0 && (
                <div className="milestone-all-clear">
                  <CheckCircle size={32} />
                  <h4>All Stories Resolved by IRR! {selectedComponent !== 'all' ? `(${selectedComponent})` : ''}</h4>
                  <p>Great job! All stories were completed on time for the Internal Release Review.</p>
                </div>
              )}
              </>
              )}
            </div>
            );
                      })()}
                      
          {/* BRANCH CUT MILESTONE - Same structure as IRR */}
          {selectedMilestone === 'branch_cut' && milestoneData && !milestoneLoading && (() => {
            const filteredComponents = selectedComponent === 'all' 
              ? milestoneData.components 
              : { [selectedComponent]: milestoneData.components?.[selectedComponent] };
            
            const filteredSummary = selectedComponent === 'all' 
              ? milestoneData.summary 
              : {
                  totalStories: filteredComponents[selectedComponent]?.counts?.total || 0,
                  resolvedOnTime: filteredComponents[selectedComponent]?.counts?.resolvedOnTime || 0,
                  totalMissed: filteredComponents[selectedComponent]?.counts?.totalMissed || 0,
                  resolvedAfterDeadline: filteredComponents[selectedComponent]?.counts?.resolvedAfterDeadline || 0,
                  stillOpen: filteredComponents[selectedComponent]?.counts?.stillOpen || 0
                };
            
            const filteredOnTimeRate = filteredSummary.totalStories > 0 
              ? Math.round((filteredSummary.resolvedOnTime / filteredSummary.totalStories) * 100) : 0;
            const filteredRecoveryRate = filteredSummary.totalMissed > 0 
              ? Math.round(((filteredSummary.resolvedAfterDeadline || 0) / filteredSummary.totalMissed) * 100) : 100;
            const overallStatus = filteredSummary.stillOpen === 0 && filteredSummary.totalMissed === 0 ? 'excellent' 
              : filteredSummary.stillOpen === 0 ? 'good' : filteredSummary.stillOpen <= 2 ? 'warning' : 'critical';
                        
                        return (
            <div className={`milestone-detail-panel irr-panel-v2 ${milestonePanelCollapsed ? 'collapsed' : ''}`}>
              {/* Collapse Toggle Header */}
              <div className="milestone-panel-header" onClick={() => setMilestonePanelCollapsed(!milestonePanelCollapsed)}>
                <div className="panel-header-left">
                  <span className={`panel-status-dot ${overallStatus}`} />
                  <span className="panel-title">Branch Cut Summary</span>
                  <span className="milestone-jql-info" onClick={(e) => e.stopPropagation()}>
                    <Info size={14} />
                    <span className="milestone-jql-tooltip">
                      Tracks all Stories and Bugs for {selectedRelease} NS Client component.
                      {'\n\n'}JQL: {milestoneData?.jql?.all_items || `(fixVersion = "${milestoneData.fixVersion}") AND (project = ENG AND component = "NS Client (NSC)" AND type not in (EPIC, Sub-task, task, Escalation))`}
                    </span>
                  </span>
                  <span className="panel-score">{filteredOnTimeRate}% On-Time</span>
                </div>
                <ChevronDown size={18} className={`panel-chevron ${milestonePanelCollapsed ? '' : 'rotated'}`} />
              </div>

              {!milestonePanelCollapsed && (
              <>
              <div className="irr-layout">
                <div className="irr-score-section">
                  <div className={`irr-score-ring ${overallStatus}`}>
                    <svg viewBox="0 0 100 100" className="score-svg">
                      <circle className="score-bg" cx="50" cy="50" r="42" fill="none" strokeWidth="8" />
                      <circle className="score-progress" cx="50" cy="50" r="42" fill="none" strokeWidth="8" 
                        strokeDasharray={filteredOnTimeRate >= 100 ? "none" : `${filteredOnTimeRate * 2.64} 264`} strokeLinecap="round" />
                    </svg>
                    <div className="score-center">
                      <span className="score-value">{filteredOnTimeRate}</span>
                      <span className="score-percent">%</span>
                    </div>
                  </div>
                  <div className="score-label">On-Time Rate</div>
                  <div className="score-sublabel">{filteredSummary.resolvedOnTime} of {filteredSummary.totalStories} stories</div>
                  <div className={`irr-status-badge ${overallStatus}`}>
                    {overallStatus === 'excellent' && <><CheckCircle size={16} /> Excellent</>}
                    {overallStatus === 'good' && <><CheckCircle size={16} /> Recovered</>}
                    {overallStatus === 'warning' && <><AlertTriangle size={16} /> Needs Attention</>}
                    {overallStatus === 'critical' && <><XCircle size={16} /> At Risk</>}
                  </div>
                </div>
                <div className="irr-details-section">
                  <div className="irr-header-row">
                    <div className="irr-date-info">
                      <Calendar size={16} />
                      <span>Branch Cut: {new Date(milestoneData.milestoneDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      {milestoneData.deadlinePassed ? (
                        <span className="days-badge passed">+{milestoneData.daysSinceDeadline}d ago</span>
                      ) : (
                        <span className="days-badge upcoming">{milestoneData.daysToDeadline}d left</span>
                      )}
                    </div>
                    {selectedComponent !== 'all' && <span className="component-tag">{selectedComponent}</span>}
                  </div>
                  {/* Pie Chart + Stats */}
                  <div className="irr-pie-section">
                    <div className="mini-pie-chart">
                      <svg viewBox="0 0 100 100" className="pie-svg">
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--success)" strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.resolvedOnTime / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          transform="rotate(-90 50 50)" />
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--warning)" strokeWidth="20"
                          strokeDasharray={`${((filteredSummary.resolvedAfterDeadline || 0) / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-((filteredSummary.resolvedOnTime / Math.max(filteredSummary.totalStories, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)" />
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--danger)" strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.stillOpen / Math.max(filteredSummary.totalStories, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-(((filteredSummary.resolvedOnTime + (filteredSummary.resolvedAfterDeadline || 0)) / Math.max(filteredSummary.totalStories, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)" />
                        <text x="50" y="50" textAnchor="middle" dy="0.3em" className="pie-center-text">{filteredSummary.totalStories}</text>
                      </svg>
                    </div>
                    <div className="pie-legend">
                      <div className="legend-row success"><span className="legend-dot"></span><span className="legend-label">On Time</span><span className="legend-value">{filteredSummary.resolvedOnTime}</span></div>
                      <div className={`legend-row warning clickable ${expandedStatBox === 'missed' ? 'active' : ''}`}
                        onClick={() => {
                          if ((filteredSummary.resolvedAfterDeadline || 0) > 0) {
                            const newState = expandedStatBox === 'missed' ? null : 'missed';
                            setExpandedStatBox(newState);
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'YOUR_PRODUCT': true }));
                          }
                        }}>
                        <span className="legend-dot"></span><span className="legend-label">Resolved Late</span><span className="legend-value">{filteredSummary.resolvedAfterDeadline || 0}</span>
                        {(filteredSummary.resolvedAfterDeadline || 0) > 0 && <ChevronRight size={12} />}
                      </div>
                      <div className={`legend-row danger clickable ${expandedStatBox === 'open' ? 'active' : ''}`}
                        onClick={() => {
                          if (filteredSummary.stillOpen > 0) {
                            const newState = expandedStatBox === 'open' ? null : 'open';
                            setExpandedStatBox(newState);
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'YOUR_PRODUCT': true }));
                          }
                        }}>
                        <span className="legend-dot"></span><span className="legend-label">Still Open</span><span className="legend-value">{filteredSummary.stillOpen}</span>
                        {filteredSummary.stillOpen > 0 && <ChevronRight size={12} />}
                      </div>
                    </div>
                  </div>

                  {/* Recovery Progress */}
                  {milestoneData.deadlinePassed && filteredSummary.totalMissed > 0 && (
                    <div className="irr-recovery">
                      <div className="recovery-header"><span>Recovery Progress</span><span className={`recovery-rate ${filteredRecoveryRate >= 80 ? 'success' : ''}`}>{filteredRecoveryRate}%</span></div>
                      <div className="recovery-bar"><div className={`recovery-fill ${filteredRecoveryRate >= 80 ? 'success' : filteredRecoveryRate >= 50 ? 'warning' : 'danger'}`} style={{ width: `${filteredRecoveryRate}%` }} /></div>
                      <div className="recovery-labels"><span>{filteredSummary.resolvedAfterDeadline || 0} resolved since</span><span>{filteredSummary.stillOpen} still open</span></div>
                    </div>
                  )}

                  {/* Assessment */}
                  <div className={`irr-assessment ${overallStatus}`}>
                    <strong>Assessment:</strong>
                    {overallStatus === 'excellent' && ' All stories resolved on time. Ready for bug fixes phase.'}
                    {overallStatus === 'good' && ' All missed items now recovered. Branch is stable.'}
                    {overallStatus === 'warning' && ` ${filteredSummary.stillOpen} item(s) need attention before Final Build.`}
                    {overallStatus === 'critical' && ` Release at risk. ${filteredSummary.stillOpen} items overdue. Escalation required.`}
                  </div>
                </div>
              </div>

              {/* Still Open Stories - Show grouped by assignee with clickable tickets */}
              {expandedStatBox === 'open' && milestoneData?.issues?.length > 0 && (() => {
                const issuesByAssignee = milestoneData.issues.reduce((acc, issue) => {
                  const assignee = issue.assignee || 'Unassigned';
                  if (!acc[assignee]) acc[assignee] = [];
                  acc[assignee].push(issue);
                  return acc;
                }, {});
                const sortedAssignees = Object.entries(issuesByAssignee).sort((a, b) => b[1].length - a[1].length);
                
                return (
                  <div className="milestone-component-breakdown collapsible-panel">
                    <div className="breakdown-header-row">
                      <h4>
                        <Users size={16} /> 
                        Still Open Stories
                        <span className="header-count">({milestoneData.issues.length} items, {sortedAssignees.length} assignees)</span>
                      </h4>
                      <button className="close-breakdown" onClick={() => setExpandedStatBox(null)}>
                        <XCircle size={16} />
                      </button>
                    </div>
                    <div className="assignee-issues-list">
                      {sortedAssignees.map(([assignee, issues]) => (
                        <div key={assignee} className="assignee-group">
                          <div className="assignee-header">
                            <span className="assignee-name">{assignee}</span>
                            <span className="assignee-count">{issues.length}</span>
                          </div>
                          <div className="issue-list">
                            {issues.map(issue => (
                              <a 
                                key={issue.key} 
                                href={issue.url || `https://your-org.atlassian.net/browse/${issue.key}`} 
                                target="_blank" 
                                rel="noopener noreferrer" 
                                className="issue-row"
                              >
                                <span className="issue-key">{issue.key}</span>
                                <span className="issue-summary">{issue.summary}</span>
                                <span className={`issue-priority ${issue.priority?.toLowerCase()}`}>{issue.priority}</span>
                                <span className={`issue-type-badge ${issue.type?.toLowerCase()}`}>{issue.type}</span>
                              </a>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
              
              {/* Missed Deadline - Keep component breakdown for resolved items */}
              {expandedStatBox === 'missed' && filteredComponents && (
                <div className="milestone-component-breakdown collapsible-panel">
                  <div className="breakdown-header-row">
                    <h4>
                      <Users size={16} /> 
                      Missed Branch Cut Deadline
                    </h4>
                    <button className="close-breakdown" onClick={() => setExpandedStatBox(null)}>
                      <XCircle size={16} />
                    </button>
                  </div>
                  {Object.entries(filteredComponents)
                    .filter(([_, compData]) => compData && compData.counts?.totalMissed > 0)
                    .map(([compName, compData]) => (
                    <div key={compName} className="component-section">
                      <div className="component-header clickable" onClick={() => setExpandedMilestoneComponents(prev => ({ ...prev, [compName]: !prev[compName] }))}>
                        <span className="component-name">{compName}</span>
                        <div className="component-counts">
                          {compData.counts?.stillOpen > 0 && <span className="count-pill danger">{compData.counts.stillOpen} open</span>}
                          {compData.counts?.resolvedAfterDeadline > 0 && <span className="count-pill success">{compData.counts.resolvedAfterDeadline} resolved</span>}
                        </div>
                        {expandedMilestoneComponents[compName] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </div>
                      {expandedMilestoneComponents[compName] && (
                        <div className="component-issues">
                          {milestoneData?.lateIssues?.length > 0 && (
                            <div className="issue-group">
                              <h5 className="issue-group-title success"><CheckCircle size={14} /> Resolved After Deadline ({milestoneData.lateIssues.length})</h5>
                              <div className="issue-list">
                                {milestoneData.lateIssues.map(issue => (
                                  <a key={issue.key} href={issue.url} target="_blank" rel="noopener noreferrer" className="issue-row">
                                    <span className="issue-key">{issue.key}</span>
                                    <span className="issue-summary">{issue.summary}</span>
                                    <span className="issue-assignee">{issue.assignee}</span>
                                    <span className={`issue-priority ${issue.priority?.toLowerCase()}`}>{issue.priority}</span>
                                    <span className="issue-delay">{issue.missedBy}</span>
                                  </a>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              </>
              )}
            </div>
            );
          })()}

          {/* FINAL BUILD MILESTONE - Stories AND Bugs */}
          {selectedMilestone === 'final_build' && milestoneData && !milestoneLoading && (() => {
            const filteredComponents = selectedComponent === 'all' 
              ? milestoneData.components 
              : { [selectedComponent]: milestoneData.components?.[selectedComponent] };
            
            const filteredSummary = selectedComponent === 'all' 
              ? milestoneData.summary 
              : {
                  totalItems: filteredComponents[selectedComponent]?.counts?.total || 0,
                  closedOnTime: filteredComponents[selectedComponent]?.counts?.closedOnTime || 0,
                  totalNotClosed: filteredComponents[selectedComponent]?.counts?.notClosed || 0,
                  storiesNotClosed: filteredComponents[selectedComponent]?.counts?.storiesNotClosed || 0,
                  bugsNotClosed: filteredComponents[selectedComponent]?.counts?.bugsNotClosed || 0
                };
            
            const onTimeRate = filteredSummary.totalItems > 0 
              ? Math.round((filteredSummary.closedOnTime / filteredSummary.totalItems) * 100) : 0;
            const overallStatus = filteredSummary.totalNotClosed === 0 ? 'excellent' 
              : filteredSummary.totalNotClosed <= 5 ? 'warning' : 'critical';
        
        return (
            <div className={`milestone-detail-panel irr-panel-v2 final-build ${milestonePanelCollapsed ? 'collapsed' : ''}`}>
              {/* Collapse Toggle Header */}
              <div className="milestone-panel-header" onClick={() => setMilestonePanelCollapsed(!milestonePanelCollapsed)}>
                <div className="panel-header-left">
                  <span className={`panel-status-dot ${overallStatus}`} />
                  <span className="panel-title">Final Build Summary</span>
                  <span className="milestone-jql-info" onClick={(e) => e.stopPropagation()}>
                    <Info size={14} />
                    <span className="milestone-jql-tooltip">
                      Tracks all Stories and Bugs for {selectedRelease} NS Client component.
                      {'\n\n'}JQL: {milestoneData?.jql?.all_items || `(fixVersion = "${milestoneData.fixVersion}") AND (project = ENG AND component = "NS Client (NSC)" AND type not in (EPIC, Sub-task, task, Escalation))`}
                    </span>
                  </span>
                  <span className="panel-score">{onTimeRate}% Closed</span>
              </div>
                <ChevronDown size={18} className={`panel-chevron ${milestonePanelCollapsed ? '' : 'rotated'}`} />
              </div>

              {!milestonePanelCollapsed && (
              <>
              <div className="irr-layout">
                <div className="irr-score-section">
                  <div className={`irr-score-ring ${overallStatus}`}>
                    <svg viewBox="0 0 100 100" className="score-svg">
                      <circle className="score-bg" cx="50" cy="50" r="42" fill="none" strokeWidth="8" />
                      <circle className="score-progress" cx="50" cy="50" r="42" fill="none" strokeWidth="8" 
                        strokeDasharray={onTimeRate >= 100 ? "none" : `${onTimeRate * 2.64} 264`} strokeLinecap="round" />
                    </svg>
                    <div className="score-center">
                      <span className="score-value">{onTimeRate}</span>
                      <span className="score-percent">%</span>
                    </div>
                  </div>
                  <div className="score-label">Closure Rate</div>
                  <div className="score-sublabel">{filteredSummary.closedOnTime} of {filteredSummary.totalItems} items</div>
                  <div className={`irr-status-badge ${overallStatus}`}>
                    {overallStatus === 'excellent' && <><CheckCircle size={16} /> Ready</>}
                    {overallStatus === 'warning' && <><AlertTriangle size={16} /> Almost Ready</>}
                    {overallStatus === 'critical' && <><XCircle size={16} /> Not Ready</>}
                      </div>
                    </div>
                <div className="irr-details-section">
                  <div className="irr-header-row">
                    <div className="irr-date-info">
                      <Calendar size={16} />
                      <span>Final Build: {new Date(milestoneData.milestoneDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                      {milestoneData.deadlinePassed ? (
                        <span className="days-badge passed">+{milestoneData.daysSinceDeadline}d ago</span>
                      ) : (
                        <span className="days-badge upcoming">{milestoneData.daysToDeadline}d left</span>
                  )}
                </div>
                    {selectedComponent !== 'all' && <span className="component-tag">{selectedComponent}</span>}
              </div>

                  {/* Pie Chart + Stats - Stories & Bugs Breakdown */}
                  <div className="irr-pie-section">
                    <div className="mini-pie-chart">
                      <svg viewBox="0 0 100 100" className="pie-svg">
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--success)" strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.closedOnTime / Math.max(filteredSummary.totalItems, 1)) * 251.2} 251.2`}
                          transform="rotate(-90 50 50)" />
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--warning)" strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.storiesNotClosed / Math.max(filteredSummary.totalItems, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-((filteredSummary.closedOnTime / Math.max(filteredSummary.totalItems, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)" />
                        <circle cx="50" cy="50" r="40" fill="transparent" stroke="var(--danger)" strokeWidth="20"
                          strokeDasharray={`${(filteredSummary.bugsNotClosed / Math.max(filteredSummary.totalItems, 1)) * 251.2} 251.2`}
                          strokeDashoffset={`${-(((filteredSummary.closedOnTime + filteredSummary.storiesNotClosed) / Math.max(filteredSummary.totalItems, 1)) * 251.2)}`}
                          transform="rotate(-90 50 50)" />
                        <text x="50" y="50" textAnchor="middle" dy="0.3em" className="pie-center-text">{filteredSummary.totalItems}</text>
                      </svg>
                    </div>
                    <div className="pie-legend">
                      <div className="legend-row success"><span className="legend-dot"></span><span className="legend-label">Closed</span><span className="legend-value">{filteredSummary.closedOnTime}</span></div>
                      <div className={`legend-row warning clickable ${expandedStatBox === 'stories' ? 'active' : ''}`}
                        onClick={() => {
                          if (filteredSummary.storiesNotClosed > 0) {
                            const newState = expandedStatBox === 'stories' ? null : 'stories';
                            setExpandedStatBox(newState);
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'fb_YOUR_PRODUCT': true }));
                          }
                        }}>
                        <span className="legend-dot"></span><span className="legend-label">Stories Open</span><span className="legend-value">{filteredSummary.storiesNotClosed}</span>
                        {filteredSummary.storiesNotClosed > 0 && <ChevronRight size={12} />}
                      </div>
                      <div className={`legend-row danger clickable ${expandedStatBox === 'bugs' ? 'active' : ''}`}
                        onClick={() => {
                          if (filteredSummary.bugsNotClosed > 0) {
                            const newState = expandedStatBox === 'bugs' ? null : 'bugs';
                            setExpandedStatBox(newState);
                            if (newState) setExpandedMilestoneComponents(prev => ({ ...prev, 'fb_YOUR_PRODUCT': true }));
                          }
                        }}>
                        <span className="legend-dot"></span><span className="legend-label">Bugs Open</span><span className="legend-value">{filteredSummary.bugsNotClosed}</span>
                        {filteredSummary.bugsNotClosed > 0 && <ChevronRight size={12} />}
                      </div>
                    </div>
                  </div>

                  <div className={`irr-assessment ${overallStatus}`}>
                    <strong>Assessment:</strong>
                    {overallStatus === 'excellent' && ' All items closed. Ready for Final Build deployment.'}
                    {overallStatus === 'warning' && ` ${filteredSummary.totalNotClosed} items need closure (${filteredSummary.storiesNotClosed} stories, ${filteredSummary.bugsNotClosed} bugs).`}
                    {overallStatus === 'critical' && ` Not ready. ${filteredSummary.totalNotClosed} items open. Block deployment until resolved.`}
                  </div>
                              </div>
                          </div>

              {/* Collapsible Component Breakdown for Final Build */}
              {expandedStatBox && filteredComponents && (
                <div className="milestone-component-breakdown collapsible-panel">
                  <div className="breakdown-header-row">
                    <h4>
                      {expandedStatBox === 'stories' ? <><BookOpen size={16} /> Stories Not Closed</> : <><Bug size={16} /> Bugs Not Closed</>}
                    </h4>
                    <button className="close-breakdown" onClick={() => setExpandedStatBox(null)}>
                      <XCircle size={16} />
                    </button>
                        </div>
                  {Object.entries(filteredComponents)
                    .filter(([_, compData]) => compData?.notClosed?.length > 0)
                    .map(([compName, compData]) => {
                      const filteredIssues = compData.notClosed.filter(issue => 
                        expandedStatBox === 'stories' ? issue.type === 'Story' : issue.type === 'Bug'
                      );
                      if (filteredIssues.length === 0) return null;
                      return (
                        <div key={compName} className="component-section">
                          <div className="component-header clickable" onClick={() => setExpandedMilestoneComponents(prev => ({ ...prev, [`fb_${compName}`]: !prev[`fb_${compName}`] }))}>
                            <span className="component-name">{compName}</span>
                            <span className={`count-pill ${expandedStatBox === 'stories' ? 'warning' : 'danger'}`}>{filteredIssues.length}</span>
                            {expandedMilestoneComponents[`fb_${compName}`] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </div>
                          {expandedMilestoneComponents[`fb_${compName}`] && (
                            <div className="component-issues">
                              <div className="issue-list">
                                {filteredIssues.map(issue => (
                                  <a key={issue.key} href={issue.url} target="_blank" rel="noopener noreferrer" className="issue-row">
                                    <span className="issue-key">{issue.key}</span>
                                    <span className="issue-summary">{issue.summary}</span>
                                    <span className="issue-assignee">{issue.assignee}</span>
                                    <span className={`issue-priority ${issue.priority?.toLowerCase()}`}>{issue.priority}</span>
                                    <span className="issue-overdue">{issue.missedBy}</span>
                            </a>
                          ))}
                        </div>
                            </div>
                      )}
                        </div>
                      );
                    })}
                    </div>
                  )}
              </>
              )}
            </div>
            );
          })()}

          {/* DEPLOYMENT MILESTONES - Day 1-4 */}
          {selectedMilestone.startsWith('day') && (() => {
            const dayNum = selectedMilestone.replace('day', '').replace('_deploy', '');
            const releaseVersion = selectedRelease.replace('R', '') + '.0';
            const insightsPlatformUrl = `https://insights.example.com/pdv/release/prod/dashboard`;
            
            // Extract PDV status info from current milestone
            const pdvCurrent = pdvData?.current;
            const pdvSummary = pdvCurrent?.summary || {};
            const pdvStatus = pdvCurrent?.status?.toLowerCase() || '';
            const pdvPassRate = pdvCurrent?.completion_percent ?? 0;
            const pdvTotal = pdvSummary.total ?? 0;
            const pdvPassed = pdvSummary.success ?? 0;
            const pdvFailed = pdvCurrent?.failures_count ?? pdvSummary.failure ?? 0;
            const pdvPending = pdvSummary.pending ?? 0;
            
            // Check if PDV data is in error/todo state (no token/connection or not started)
            const isPdvError = pdvStatus === 'error' || pdvStatus === 'not_configured';
            const isPdvTodo = pdvStatus === 'todo' && pdvTotal === 0;
            const hasRealPdvData = pdvTotal > 0 || pdvPassed > 0 || pdvFailed > 0;
            
            // Determine status class for PDV
            const getPdvStatusClass = (status) => {
              if (status === 'success' || status === 'approved') return 'good';
              if (status === 'failure') return 'critical';
              if (status === 'error' || status === 'not_configured') return 'unknown';
              if (status === 'in_progress' || status === 'running') return 'warning';
              if (status === 'pending' || status === 'todo') return 'unknown';
              return 'unknown';
            };
                
            return (
            <div className={`milestone-detail-panel deployment-panel ${milestonePanelCollapsed ? 'collapsed' : ''}`}>
              <div className="milestone-panel-header" onClick={() => setMilestonePanelCollapsed(!milestonePanelCollapsed)}>
                <div className="panel-header-left">
                  <span className={`panel-status-dot ${getPdvStatusClass(pdvStatus)}`} />
                  <span className="panel-title">Day {dayNum} Deployment Status</span>
                  <span className="panel-score">{selectedRelease} • {releaseVersion}</span>
                </div>
                <div className="panel-header-right">
                  <a 
                    href={insightsPlatformUrl}
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="panel-external-link"
                    onClick={(e) => e.stopPropagation()}
                    title="Open Insights Platform"
                  >
                    <ExternalLink size={14} />
                  </a>
                  <ChevronDown size={18} className={`panel-chevron ${milestonePanelCollapsed ? '' : 'rotated'}`} />
                </div>
              </div>

              {!milestonePanelCollapsed && (
              <div className="deployment-content">
                {/* Loading State */}
                {pdvLoading && (
                  <div className="deployment-loading">
                    <RefreshCw size={24} className="spinning" />
                    <span>Fetching Day {dayNum} deployment data...</span>
                  </div>
                )}

                {/* Error State */}
                {pdvError && !pdvLoading && (
                  <div className="deployment-error">
                    <AlertTriangle size={24} />
                    <div className="error-content">
                      <h4>Unable to fetch deployment data</h4>
                      <p>{pdvError}</p>
                      <a 
                        href={insightsPlatformUrl}
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="external-link-btn"
                      >
                        <ExternalLink size={14} />
                        View in Insights Platform
                      </a>
                    </div>
                  </div>
                )}

                {/* PDV Data */}
                {!pdvLoading && pdvCurrent && (
                  <>
                    {/* Show error/no-data state when PDV connection failed or TODO */}
                    {(isPdvError || isPdvTodo) && !hasRealPdvData ? (
                      <div className="deployment-no-data">
                        <Activity size={32} />
                        <h4>{isPdvError ? 'PDV Connection Issue' : 'Deployment Not Started'}</h4>
                        <p>
                          {isPdvError 
                            ? `Unable to fetch PDV data for Day ${dayNum}.`
                            : `Day ${dayNum} deployment has not started yet.`}
                        </p>
                        <span style={{ fontSize: '12px', color: '#666', marginBottom: '12px', display: 'block' }}>
                          {isPdvError 
                            ? 'PDV service connection issue. Please ensure the backend has valid Insights Platform authentication.'
                            : 'PDV validation will begin once the deployment phase starts. Check Insights Platform for updates.'}
                        </span>
                        <a 
                          href={insightsPlatformUrl}
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="external-link-btn"
                        >
                          <ExternalLink size={14} />
                          View in Insights Platform
                        </a>
                      </div>
                    ) : (
                      <>
                        {/* Summary Cards */}
                        <div className="deployment-summary">
                          {/* Overall Status */}
                          <div className={`summary-card ${getPdvStatusClass(pdvStatus)}`}>
                            <div className="summary-icon">
                              {pdvStatus === 'success' || pdvStatus === 'approved' ? <CheckCircle size={24} /> :
                               pdvStatus === 'in_progress' || pdvStatus === 'running' ? <Activity size={24} /> :
                               pdvStatus === 'failure' ? <XCircle size={24} /> :
                               <Activity size={24} />}
                            </div>
                            <div className="summary-content">
                              <span className="summary-label">Overall Status</span>
                              <span className="summary-value">
                                {(pdvCurrent.status || 'NO DATA').replace('_', ' ').toUpperCase()}
                              </span>
                            </div>
                          </div>
                          
                          {/* Pass Rate */}
                          <div className="summary-card">
                            <div className="summary-content">
                              <span className="summary-label">Pass Rate</span>
                              <span className={`summary-value ${pdvPassRate >= 90 ? 'good' : pdvPassRate >= 70 ? 'warning' : 'critical'}`}>
                                {pdvPassRate}%
                              </span>
                            </div>
                          </div>
                          
                          {/* Total Jobs */}
                          <div className="summary-card">
                            <div className="summary-content">
                              <span className="summary-label">Total Jobs</span>
                              <span className="summary-value">{pdvTotal}</span>
                            </div>
                          </div>
                          
                          {/* Passed */}
                          <div className="summary-card success">
                            <div className="summary-content">
                              <span className="summary-label">Passed</span>
                              <span className="summary-value">{pdvPassed}</span>
                            </div>
                          </div>
                          
                          {/* Failed */}
                          <div className="summary-card danger">
                            <div className="summary-content">
                              <span className="summary-label">Failed</span>
                              <span className="summary-value">{pdvFailed}</span>
                            </div>
                          </div>
                        </div>

                        {/* Components/Stacks section */}
                        <div className="deployment-services">
                          <h4><Package size={16} /> NS Client PDV Status</h4>
                          
                          {pdvCurrent?.components && pdvCurrent.components.length > 0 ? (
                            (() => {
                              // Group by Application (DP, MP, DP_Compliance, MP_Compliance, etc.)
                              const appGroups = {};
                              
                              // Define sort order for applications
                              const appOrder = ['DP', 'MP', 'MP_Manual', 'DP_Compliance', 'MP_Compliance', 'MP_Manual_Compliance'];
                              
                              pdvCurrent.components.forEach(comp => {
                                const appName = comp.application || 'Unknown';
                                const compName = comp.name || 'Unknown';
                                
                                if (!appGroups[appName]) {
                                  appGroups[appName] = {
                                    application: appName,
                                    componentName: compName,
                                    datacenters: [],
                                    summary: { success: 0, failure: 0, pending: 0, total: 0 }
                                  };
                                }
                                
                                (comp.datacenters || []).forEach(dc => {
                                  appGroups[appName].datacenters.push(dc);
                                  appGroups[appName].summary.total++;
                                  const status = (dc.status || '').toUpperCase();
                                  if (status === 'SUCCESS' || status === 'APPROVED') {
                                    appGroups[appName].summary.success++;
                                  } else if (status === 'FAILURE' || status === 'FAILED') {
                                    appGroups[appName].summary.failure++;
                                  } else {
                                    appGroups[appName].summary.pending++;
                                  }
                                });
                              });

                              // Sort applications by predefined order
                              const sortedApps = Object.values(appGroups).sort((a, b) => {
                                const aIdx = appOrder.indexOf(a.application);
                                const bIdx = appOrder.indexOf(b.application);
                                if (aIdx === -1 && bIdx === -1) return a.application.localeCompare(b.application);
                                if (aIdx === -1) return 1;
                                if (bIdx === -1) return -1;
                                return aIdx - bIdx;
                              });

                              return (
                                <div className="pdv-app-groups">
                                  {sortedApps.map((group, idx) => {
                                    const groupKey = `${dayNum}_${group.application}`;
                                    const isCollapsed = pdvCollapsed[groupKey];
                                    
                                    return (
                                      <div key={idx} className="pdv-app-group">
                                        <div 
                                          className="app-group-header clickable"
                                          onClick={() => setPdvCollapsed(prev => ({
                                            ...prev,
                                            [groupKey]: !prev[groupKey]
                                          }))}
                                        >
                                          <span className="collapse-icon">
                                            {isCollapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                                          </span>
                                          <span className="app-name">{group.application.replace(/_/g, ' ')}</span>
                                          <span className="app-type">({group.componentName})</span>
                                          <div className="app-summary">
                                            <span className="summary-badge success">{group.summary.success} ✓</span>
                                            <span className="summary-badge failure">{group.summary.failure} ✗</span>
                                            <span className="summary-badge pending">{group.summary.pending} ⏳</span>
                                            <span className="component-count">{group.summary.total} DCs</span>
                                          </div>
                                        </div>
                                        
                                        {!isCollapsed && (
                                          <table className="pdv-dc-table">
                                            <thead>
                                              <tr>
                                                <th>Datacenter</th>
                                                <th>PDV Status</th>
                                                <th>Deploy Status</th>
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {group.datacenters.map((dc, dcIdx) => (
                                                <tr key={dcIdx} className={`dc-row status-${(dc.status || 'unknown').toLowerCase()}`}>
                                                  <td className="dc-name" title={dc.dc_id}>
                                                    {dc.name || dc.dc_id?.substring(0, 8) || 'N/A'}
                                                  </td>
                                                  <td className={`status-cell ${(dc.status || 'unknown').toLowerCase()}`}>
                                                    {dc.status || 'TODO'}
                                                  </td>
                                                  <td className={`status-cell ${(dc.deploy_status || 'unknown').toLowerCase()}`}>
                                                    {dc.deploy_status || 'TODO'}
                                                  </td>
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              );
                            })()
                          ) : (
                            <div className="no-services">
                              <Activity size={20} />
                              <p>No NS Client data available for Day {dayNum}</p>
                              <span>
                                NS Client PDV status will appear once validation begins.
                              </span>
                            </div>
                          )}
                        </div>

                        {/* Footer */}
                        <div className="deployment-footer">
                          <div className="deployment-meta">
                            <span><strong>Release:</strong> {releaseVersion}</span>
                            <span><strong>Day:</strong> {dayNum}</span>
                            <span><strong>Updated:</strong> {
                              pdvData?.fetched_at 
                                ? new Date(pdvData.fetched_at).toLocaleTimeString()
                                : 'N/A'
                            }</span>
                          </div>
                          <a 
                            href={insightsPlatformUrl}
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="open-fullscreen-btn"
                          >
                            <ExternalLink size={14} />
                            Open Insights Platform
                          </a>
                        </div>
                      </>
                    )}
                  </>
                )}

                {/* No Data State */}
                {!pdvCurrent && !pdvLoading && !pdvError && (
                  <div className="deployment-no-data">
                    <Activity size={32} />
                    <h4>No Deployment Data</h4>
                    <p>Deployment data for Day {dayNum} is not yet available.</p>
                    <span style={{ fontSize: '12px', color: '#666', marginBottom: '12px', display: 'block' }}>
                      PDV data for this release day has not been configured or is pending. Check Insights Platform.
                    </span>
                    <a 
                      href={insightsPlatformUrl}
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="external-link-btn"
                    >
                      <ExternalLink size={14} />
                      Check Insights Platform
                    </a>
                  </div>
                )}
              </div>
              )}
            </div>
            );
          })()}

          {/* STG DEPLOY and PRE-PRD DEPLOY MILESTONES */}
          {(selectedMilestone === 'stg_deploy' || selectedMilestone === 'pre_prd_deploy') && (() => {
            const phaseLabel = selectedMilestone === 'stg_deploy' ? 'Staging' : 'Pre-Production';
            const phaseIcon = selectedMilestone === 'stg_deploy' ? '🧪' : '🔄';
            const releaseVersion = selectedRelease.replace('R', '') + '.0';
            const insightsPlatformUrl = selectedMilestone === 'stg_deploy' 
              ? 'https://insights.example.com/pdv/staging-release/staging/dashboard'
              : 'https://insights.example.com/pdv/release/prod/dashboard';
            
            // Extract PDV status info
            const pdvCurrent = pdvData?.current;
            const pdvSummary = pdvCurrent?.summary || {};
            const pdvStatus = pdvCurrent?.status?.toLowerCase() || '';
            const pdvPassRate = pdvCurrent?.completion_percent ?? 0;
            const pdvTotal = pdvSummary.total ?? 0;
            const pdvPassed = pdvSummary.success ?? 0;
            const pdvFailed = pdvCurrent?.failures_count ?? pdvSummary.failure ?? 0;
            
            // Check if PDV data is in error/todo state (no token/connection or not started)
            const isPdvError = pdvStatus === 'error' || pdvStatus === 'not_configured';
            const isPdvTodo = pdvStatus === 'todo' && pdvTotal === 0;
            const hasRealPdvData = pdvTotal > 0 || pdvPassed > 0 || pdvFailed > 0;
            
            const getPdvStatusClass = (status) => {
              if (status === 'success' || status === 'approved') return 'good';
              if (status === 'failure') return 'critical';
              if (status === 'error' || status === 'not_configured') return 'unknown';
              if (status === 'in_progress' || status === 'running') return 'warning';
              if (status === 'pending' || status === 'todo') return 'unknown';
              return 'unknown';
            };
            
            return (
              <div className={`milestone-detail-panel deployment-panel ${milestonePanelCollapsed ? 'collapsed' : ''}`}>
                <div className="milestone-panel-header" onClick={() => setMilestonePanelCollapsed(!milestonePanelCollapsed)}>
                  <div className="panel-header-left">
                    <span className={`panel-status-dot ${getPdvStatusClass(pdvStatus)}`} />
                    <span className="panel-title">{phaseIcon} {phaseLabel} Deployment Status</span>
                    <span className="panel-score">{selectedRelease} • {releaseVersion}</span>
                  </div>
                  <div className="panel-header-right">
                    <a 
                      href={insightsPlatformUrl}
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="panel-external-link"
                      onClick={(e) => e.stopPropagation()}
                      title="Open Insights Platform"
                    >
                      <ExternalLink size={14} />
                    </a>
                    <ChevronDown size={18} className={`panel-chevron ${milestonePanelCollapsed ? '' : 'rotated'}`} />
                  </div>
                </div>

                {!milestonePanelCollapsed && (
                  <div className="deployment-content">
                    {/* Loading */}
                    {pdvLoading && (
                      <div className="deployment-loading">
                        <RefreshCw size={24} className="spinning" />
                        <span>Fetching {phaseLabel} deployment data...</span>
                      </div>
                    )}

                    {/* Error */}
                    {pdvError && !pdvLoading && (
                      <div className="deployment-error">
                        <AlertTriangle size={24} />
                        <div className="error-content">
                          <h4>Unable to fetch deployment data</h4>
                          <p>{pdvError}</p>
                        </div>
                      </div>
                    )}

                    {/* PDV Data */}
                    {!pdvLoading && pdvCurrent && (
                      <>
                        {/* Show error/no-data state when PDV connection failed or TODO */}
                        {(isPdvError || isPdvTodo) && !hasRealPdvData ? (
                          <div className="deployment-no-data">
                            <Activity size={32} />
                            <h4>{isPdvError ? 'PDV Connection Issue' : 'Deployment Not Started'}</h4>
                            <p>
                              {isPdvError 
                                ? `Unable to fetch PDV data for ${phaseLabel}.`
                                : `${phaseLabel} deployment has not started yet.`}
                            </p>
                            <span style={{ fontSize: '12px', color: '#666', marginBottom: '12px', display: 'block' }}>
                              {isPdvError 
                                ? 'PDV service connection issue. Please ensure the backend has valid Insights Platform authentication.'
                                : 'PDV validation will begin once the deployment phase starts. Check Insights Platform for updates.'}
                            </span>
                            <a 
                              href={insightsPlatformUrl}
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="external-link-btn"
                            >
                              <ExternalLink size={14} />
                              View in Insights Platform
                            </a>
                          </div>
                        ) : (
                          <>
                            {/* Summary Cards */}
                            <div className="deployment-summary">
                              <div className={`summary-card ${getPdvStatusClass(pdvStatus)}`}>
                                <div className="summary-icon">
                                  {pdvStatus === 'success' || pdvStatus === 'approved' ? <CheckCircle size={24} /> :
                                   pdvStatus === 'in_progress' || pdvStatus === 'running' ? <Activity size={24} /> :
                                   pdvStatus === 'failure' ? <XCircle size={24} /> :
                                   <Activity size={24} />}
                                </div>
                                <div className="summary-content">
                                  <span className="summary-label">Overall Status</span>
                                  <span className="summary-value">
                                    {(pdvCurrent.status || 'NO DATA').replace('_', ' ').toUpperCase()}
                                  </span>
                                </div>
                              </div>
                              
                              <div className="summary-card">
                                <div className="summary-content">
                                  <span className="summary-label">Pass Rate</span>
                                  <span className={`summary-value ${pdvPassRate >= 90 ? 'good' : pdvPassRate >= 70 ? 'warning' : 'critical'}`}>
                                    {pdvPassRate}%
                                  </span>
                                </div>
                              </div>
                              
                              <div className="summary-card">
                                <div className="summary-content">
                                  <span className="summary-label">Total Jobs</span>
                                  <span className="summary-value">{pdvTotal}</span>
                                </div>
                              </div>
                              
                              <div className="summary-card success">
                                <div className="summary-content">
                                  <span className="summary-label">Passed</span>
                                  <span className="summary-value">{pdvPassed}</span>
                                </div>
                              </div>
                              
                              <div className="summary-card danger">
                                <div className="summary-content">
                                  <span className="summary-label">Failed</span>
                                  <span className="summary-value">{pdvFailed}</span>
                                </div>
                              </div>
                            </div>

                            {/* Footer */}
                            <div className="deployment-footer">
                              <div className="deployment-meta">
                                <span><strong>Release:</strong> {releaseVersion}</span>
                                <span><strong>Phase:</strong> {phaseLabel}</span>
                                <span><strong>Updated:</strong> {
                                  pdvData?.fetched_at 
                                    ? new Date(pdvData.fetched_at).toLocaleTimeString()
                                    : 'N/A'
                                }</span>
                              </div>
                              <a 
                                href={insightsPlatformUrl}
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="open-fullscreen-btn"
                              >
                                <ExternalLink size={14} />
                                Open Insights Platform
                              </a>
                            </div>
                          </>
                        )}
                      </>
                    )}

                    {/* No Data */}
                    {!pdvCurrent && !pdvLoading && !pdvError && (
                      <div className="deployment-no-data">
                        <Activity size={32} />
                        <h4>No Deployment Data</h4>
                        <p>Deployment data for {phaseLabel} is not yet available.</p>
                        <a 
                          href={insightsPlatformUrl}
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="external-link-btn"
                        >
                          <ExternalLink size={14} />
                          Check Insights Platform
                        </a>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })()}
        </>
      )}

      {/* ============================================
          MAIN CONTENT - Single Page, Collapsible Sections
          ============================================ */}
      <div className="rr-content single-page">
        
        {/* Note: Action Items section removed - now shown inline in first row */}

        {/* SECTION: Timeline (Shown inline after first box) */}
        {expandedSections.timeline && (
        <div className="rr-timeline-inline">
          <div className="timeline-header">
            <span className="timeline-title"><Target size={16} /> Release Timeline</span>
            <button className="timeline-close" onClick={() => toggleSection('timeline')}>×</button>
            </div>
              {(() => {
                const today = new Date();
                const irr = new Date(data?.timeline?.irr_date || `${today.getFullYear()}-01-01`);
                const branchCut = new Date(data?.timeline?.branch_cut_date || `${today.getFullYear()}-01-08`);
                const finalBuild = new Date(data?.timeline?.final_build_date || `${today.getFullYear()}-01-22`);
            const day1Deploy = data?.timeline?.day1_deploy ? new Date(data.timeline.day1_deploy) : new Date(finalBuild.getTime() + 11 * 24 * 60 * 60 * 1000);
            const day2Deploy = data?.timeline?.day2_deploy ? new Date(data.timeline.day2_deploy) : new Date(finalBuild.getTime() + 14 * 24 * 60 * 60 * 1000);
            const day3Deploy = data?.timeline?.day3_deploy ? new Date(data.timeline.day3_deploy) : new Date(finalBuild.getTime() + 15 * 24 * 60 * 60 * 1000);
            const day4Deploy = data?.timeline?.day4_deploy ? new Date(data.timeline.day4_deploy) : new Date(finalBuild.getTime() + 18 * 24 * 60 * 60 * 1000);
            const formatDate = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            
            const milestones = [
              { key: 'irr', date: irr, label: 'IRR', done: today >= irr },
              { key: 'branch_cut', date: branchCut, label: 'Branch Cut', done: today >= branchCut },
              { key: 'final_build', date: finalBuild, label: 'Final Build', done: today >= finalBuild },
              { key: 'day1_deploy', date: day1Deploy, label: 'Day 1', done: today >= day1Deploy },
              { key: 'day2_deploy', date: day2Deploy, label: 'Day 2', done: today >= day2Deploy },
              { key: 'day3_deploy', date: day3Deploy, label: 'Day 3', done: today >= day3Deploy },
              { key: 'day4_deploy', date: day4Deploy, label: 'Day 4', done: today >= day4Deploy }
            ];
            
            const currentIdx = milestones.findIndex(m => !m.done);
            const currentPhaseIdx = currentIdx === -1 ? milestones.length - 1 : currentIdx;
                
                return (
              <div className="rr-tl-steps">
                {milestones.map((m, idx) => (
                  <div key={m.key} className={`rr-tl-step ${m.done ? 'done' : ''} ${idx === currentPhaseIdx && !m.done ? 'current' : ''}`}>
                    <div className="rr-tl-marker">
                      {m.done ? <CheckCircle size={14} /> : idx === currentPhaseIdx ? <span className="rr-tl-current">●</span> : <span className="rr-tl-future">○</span>}
                    </div>
                    <div className="rr-tl-info">
                      <span className="rr-tl-name">{m.label}</span>
                      <span className="rr-tl-date">{formatDate(m.date)}</span>
                    </div>
                    {idx === currentPhaseIdx && !m.done && <span className="rr-tl-now">Now</span>}
                    </div>
                ))}
                  </div>
                );
              })()}
            </div>
        )}

        {/* SECTION: Charts Grid - Priority Breakdown */}
        <div className="charts-grid">
          {/* Priority Distribution Chart */}
          <div className="chart-tile priority-tile">
            <div className="chart-tile-header">
              <span className="chart-tile-title" title="Work items distribution by priority level">
                <AlertTriangle size={16} /> Priority Breakdown
              </span>
              <span className="chart-tile-badge">
                {Object.values(priorityGroups).reduce((acc, p) => acc + p.total, 0)} items
              </span>
            </div>
            
            <div className="priority-chart">
              {(() => {
                const priorityOrder = ['Blocker', 'Critical', 'Highest', 'High', 'Major', 'Medium', 'Minor', 'Low', 'Lowest'];
                const sortedPriorities = Object.entries(priorityGroups)
                  .sort((a, b) => {
                    const aIdx = priorityOrder.indexOf(a[0]);
                    const bIdx = priorityOrder.indexOf(b[0]);
                    return (aIdx === -1 ? 999 : aIdx) - (bIdx === -1 ? 999 : bIdx);
                  });
                const maxCount = Math.max(
                  ...sortedPriorities.map(([_, d]) => Math.max(d.stories, d.bugs)), 
                  1
                );
                
                if (sortedPriorities.length === 0) {
                  return (
                    <div className="priority-empty">
                      <CheckCircle size={24} />
                      <span>No pending items</span>
                    </div>
                  );
                }
                
                return (
                  <div className="priority-dual-bars">
                    {sortedPriorities.map(([priority, data]) => {
                      const isUrgent = ['Critical', 'Blocker', 'Highest'].includes(priority);
                      return (
                        <div key={priority} className={`priority-dual-row ${isUrgent ? 'urgent' : ''}`}>
                          <div className="priority-label">
                            <span className={`priority-dot ${priority.toLowerCase()}`}></span>
                            <span className="priority-name">{priority}</span>
                          </div>
                          <div className="priority-dual-tracks">
                            {/* Stories Bar */}
                            <div className="priority-track-row">
                              <span className="track-type-label">S</span>
                              <div className="priority-bar-track stories-track">
                                <div 
                                  className="priority-bar-fill stories-fill"
                                  style={{ width: `${(data.stories / maxCount) * 100}%` }}
                                >
                                  {data.stories > 0 && <span className="bar-count">{data.stories}</span>}
                                </div>
                              </div>
                            </div>
                            {/* Bugs Bar */}
                            <div className="priority-track-row">
                              <span className="track-type-label">B</span>
                              <div className="priority-bar-track bugs-track">
                                <div 
                                  className="priority-bar-fill bugs-fill"
                                  style={{ width: `${(data.bugs / maxCount) * 100}%` }}
                                >
                                  {data.bugs > 0 && <span className="bar-count">{data.bugs}</span>}
                                </div>
                              </div>
                            </div>
                          </div>
                          <div className="priority-total">{data.total}</div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
            
            <div className="priority-legend">
              <div className="priority-type-legend">
                <span className="legend-item"><span className="legend-dot stories"></span>Stories</span>
                <span className="legend-item"><span className="legend-dot bugs"></span>Bugs</span>
              </div>
            </div>
          </div>

          {/* Items Moved Out Tile */}
          <div className="chart-tile items-moved-tile">
            <div className="chart-tile-header">
              <span className="chart-tile-title" title="Items moved out of this release since IRR">
                <ArrowRight size={16} /> Items Moved Out
              </span>
              {itemsMovedOutData && (
                <a 
                  href={itemsMovedOutData.jira_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="chart-tile-jira-link"
                  title="View in JIRA"
                >
                  <ExternalLink size={14} />
                </a>
              )}
            </div>
            
            {itemsMovedOutLoading ? (
              <div className="items-moved-loading">
                <RefreshCw size={20} className="spin" />
                <span>Loading...</span>
              </div>
            ) : itemsMovedOutError ? (
              <div className="items-moved-error">
                <AlertTriangle size={20} />
                <span>Unable to load data</span>
              </div>
            ) : itemsMovedOutData ? (
              <div className="items-moved-content-tile">
                {/* IRR Date */}
                <div className="items-moved-irr">
                  <span className="irr-label">Since IRR:</span>
                  <span className="irr-date">{itemsMovedOutData.irr_date}</span>
                </div>
                
                {/* Total Count */}
                <div className="items-moved-total-tile">
                  <span className="total-number">{itemsMovedOutData.total_moved_out}</span>
                  <span className="total-label">Total Moved Out</span>
                </div>
                
                {/* Type Breakdown */}
                <div className="items-moved-types-tile">
                  <div className="type-stat bugs">
                    <Bug size={16} />
                    <span className="type-count">{itemsMovedOutData.bugs_count}</span>
                    <span className="type-label">Bugs</span>
                  </div>
                  <div className="type-stat stories">
                    <BookOpen size={16} />
                    <span className="type-count">{itemsMovedOutData.stories_count}</span>
                    <span className="type-label">Stories</span>
                  </div>
                </div>
                
                {/* Priority Breakdown */}
                <div className="items-moved-priorities-tile">
                  <span className="priorities-title">Priority Breakdown:</span>
                  <div className="priority-mini-badges">
                    {Object.entries(itemsMovedOutData.by_priority || {}).map(([priority, count]) => (
                      <div 
                        key={priority} 
                        className={`priority-mini-badge ${priority.toLowerCase()}`}
                      >
                        <span className="priority-name">{priority}:</span>
                        <span className="priority-count">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="items-moved-empty">
                <CheckCircle size={20} />
                <span>No items moved out</span>
              </div>
            )}
          </div>
        </div>

        {/* SECTION: Trends & Analytics - Enhanced Visualization */}
        <div className="trends-analytics-section">
          <div className="trends-header">
            <h3><TrendingUp size={18} /> Trends & Analytics</h3>
            {trendAnalysis?.has_data && trendAnalysis?.first_data_date && (
              <span className="trends-date-range">
                Since IRR: {trendAnalysis.first_data_date} ({trendAnalysis.data_points} snapshots)
              </span>
            )}
          </div>

          {/* Summary Stats Bar */}
          {trendAnalysis?.has_data && (
            <div className="trends-summary-bar">
              <div className="summary-stat" title="Total open Stories and Bugs at the start of tracking (IRR date)">
                <span className="summary-label">At IRR</span>
                <span className="summary-value">{trendAnalysis.period_start_total || 0}</span>
              </div>
              <div className="summary-arrow">
                {trendAnalysis.trend_direction === 'improving' ? <TrendingDown size={20} className="improving" /> : 
                 trendAnalysis.trend_direction === 'declining' ? <TrendingUp size={20} className="declining" /> : 
                 <ArrowRight size={20} className="stable" />}
              </div>
              <div className="summary-stat" title="Current number of open Stories and Bugs">
                <span className="summary-label">Now</span>
                <span className="summary-value">{trendAnalysis.current_total || 0}</span>
              </div>
              <div 
                className={`summary-stat change ${(trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0) >= 0 ? 'positive' : 'negative'}`}
                title={`Net change in open items since IRR. ${(trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0) >= 0 ? 'Negative means items are being resolved.' : 'Positive means more items are being added than resolved.'}`}
              >
                <span className="summary-label">Net Change</span>
                <span className="summary-value">
                  {(trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0) >= 0 
                    ? `−${(trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0)}`
                    : `+${Math.abs((trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0))}`}
                </span>
              </div>
              <div 
                className="summary-stat velocity" 
                title={`Average rate of resolution. ${trendAnalysis.velocity > 0 ? `Resolving ~${trendAnalysis.velocity} items per day.` : trendAnalysis.velocity < 0 ? `Adding ~${Math.abs(trendAnalysis.velocity)} items per day (negative velocity).` : 'No net change in items.'}`}
              >
                <span className="summary-label">Velocity</span>
                <span className={`summary-value ${trendAnalysis.velocity > 0 ? 'positive' : trendAnalysis.velocity < 0 ? 'negative' : ''}`}>
                  {trendAnalysis.velocity > 0 ? `${trendAnalysis.velocity}/day` : trendAnalysis.velocity < 0 ? `${trendAnalysis.velocity}/day` : '0/day'}
                </span>
              </div>
              <div 
                className="summary-stat eta" 
                title={trendAnalysis.prediction_date ? `Estimated date when all open items will be resolved at current velocity.` : 'Cannot estimate completion date. Velocity needs to improve.'}
              >
                <span className="summary-label">ETA</span>
                <span className={`summary-value ${trendAnalysis.prediction_date ? 'on-track' : 'off-track'}`}>
                  {trendAnalysis.prediction_date || 'N/A'}
                </span>
              </div>
            </div>
          )}

          {/* Insight Tiles - Only show when we have meaningful data */}
          {trendAnalysis?.has_data && (
            <div className="trends-tiles-grid">
              {/* Tile 1: Trend Direction */}
              <div className={`trend-tile-v2 ${trendAnalysis?.trend_direction || 'neutral'}`}>
                <div className="tile-header">
                  <div className="tile-icon">
                    {trendAnalysis?.trend_direction === 'improving' ? <TrendingDown size={18} /> :
                     trendAnalysis?.trend_direction === 'declining' ? <TrendingUp size={18} /> :
                     <Minus size={18} />}
                  </div>
                  <span className="tile-label">Open Items Trend</span>
                </div>
                <div className="tile-main">
                  <span className="tile-value">
                    {trendAnalysis?.trend_direction === 'improving' ? 'Decreasing' : 
                     trendAnalysis?.trend_direction === 'declining' ? 'Increasing' : 'Stable'}
                  </span>
                </div>
                <div className="tile-description">
                  {trendAnalysis?.trend_direction === 'improving' 
                    ? `Open items reduced from ${trendAnalysis.period_start_total} to ${trendAnalysis.current_total}`
                    : trendAnalysis?.trend_direction === 'declining'
                      ? `Open items increased from ${trendAnalysis.period_start_total} to ${trendAnalysis.current_total}`
                      : `Open items remained at ${trendAnalysis.current_total}`}
                </div>
              </div>

              {/* Tile 2: Velocity */}
              <div className={`trend-tile-v2 velocity ${trendAnalysis?.velocity > 0 ? 'positive' : trendAnalysis?.velocity < 0 ? 'negative' : 'neutral'}`}>
                <div className="tile-header">
                  <div className="tile-icon">
                    <Activity size={18} />
                  </div>
                  <span className="tile-label">Resolution Velocity</span>
                </div>
                <div className="tile-main">
                  <span className="tile-value">{Math.abs(trendAnalysis?.velocity || 0)}</span>
                  <span className="tile-unit">items/day</span>
                </div>
                <div className="tile-description">
                  {trendAnalysis?.velocity > 0 
                    ? `Team is resolving ~${trendAnalysis.velocity} items per day on average`
                    : trendAnalysis?.velocity < 0 
                      ? `Items are being added faster than resolved (~${Math.abs(trendAnalysis.velocity)}/day)`
                      : 'Resolution rate matches incoming rate'}
                </div>
              </div>

              {/* Tile 3: Prediction */}
              <div className={`trend-tile-v2 prediction ${trendAnalysis?.current_total === 0 ? 'on-track' : (trendAnalysis?.velocity > 0 ? 'on-track' : 'off-track')}`}>
                <div className="tile-header">
                  <div className="tile-icon">
                    <Target size={18} />
                  </div>
                  <span className="tile-label">Completion Estimate</span>
                </div>
                <div className="tile-main">
                  <span className="tile-value">
                    {trendAnalysis?.current_total === 0 
                      ? '✓ Complete' 
                      : (trendAnalysis?.prediction_date || 'N/A')}
                  </span>
                </div>
                <div className="tile-description">
                  {trendAnalysis?.velocity > 0 && trendAnalysis?.current_total > 0
                    ? `At current pace, all ${trendAnalysis.current_total} items will be resolved in ~${Math.ceil(trendAnalysis.current_total / trendAnalysis.velocity)} days`
                    : trendAnalysis?.current_total === 0 
                      ? 'All items have been resolved!'
                      : 'Velocity needs to improve to estimate completion'}
                </div>
                {trendAnalysis?.current_total > 0 && trendAnalysis?.period_start_total > 0 && (
                  <div className="tile-progress-bar">
                    <div className="progress-bar-track">
                      <div 
                        className="progress-bar-fill"
                        style={{ 
                          width: `${Math.max(0, Math.min(100, ((trendAnalysis.period_start_total - trendAnalysis.current_total) / trendAnalysis.period_start_total) * 100))}%`,
                          background: trendAnalysis?.velocity > 0 ? '#10b981' : '#ef4444'
                        }}
                      />
                    </div>
                    <span className="progress-bar-label">
                      {Math.round(Math.max(0, Math.min(100, ((trendAnalysis.period_start_total - trendAnalysis.current_total) / trendAnalysis.period_start_total) * 100)))}% complete
                    </span>
                  </div>
                )}
              </div>

              {/* Tile 4: Alert (only if active) */}
              {(trendAnalysis?.plateau_detected || trendAnalysis?.spikes_detected) && (
                <div className={`trend-tile-v2 alert ${trendAnalysis?.spikes_detected ? 'danger' : 'warning'}`}>
                  <div className="tile-header">
                    <div className="tile-icon pulsing">
                      <AlertTriangle size={18} />
                    </div>
                    <span className="tile-label">Attention Needed</span>
                  </div>
                  <div className="tile-main">
                    <span className="tile-value">
                      {trendAnalysis?.plateau_detected ? 'Progress Stalled' : 'Sudden Increase'}
                    </span>
                  </div>
                  <div className="tile-description">
                    {trendAnalysis?.plateau_detected 
                      ? `No Stories or Bugs have been resolved in the last ${(trendAnalysis?.plateau_count || 0) * 2}+ hours. This could indicate blockers or resource constraints.`
                      : `${trendAnalysis?.spikes?.[0]?.increase || 'Multiple'} new Stories/Bugs were added to this release recently (${trendAnalysis?.spikes?.[0]?.datetime || 'recently'}). Review these new tickets and update priorities if needed.`}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Main Trend Chart - with clear title and description */}
          {trendAnalysis?.has_data && trendAnalysis?.chart_data?.length > 1 && (
            <div className="trends-main-chart">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-title">Open Items Over Time</span>
                  <span className="chart-subtitle">Tracking open Stories and Bugs since IRR</span>
                </div>
                <div className="chart-legend">
                  <span className="legend-item"><span className="legend-dot stories"></span> Stories</span>
                  <span className="legend-item"><span className="legend-dot bugs"></span> Bugs</span>
                  <span className="legend-item"><span className="legend-line total"></span> Total</span>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={trendAnalysis.chart_data} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
                  <defs>
                    <linearGradient id="storiesGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="bugsGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f97316" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#f97316" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                  <XAxis 
                    dataKey="date" 
                    tick={{ fontSize: 11, fill: '#6b7280' }} 
                    tickFormatter={(value) => value ? value.slice(5) : ''} 
                    interval="preserveStartEnd"
                    label={{ value: 'Date', position: 'bottom', offset: -5, fontSize: 10, fill: '#9ca3af' }}
                  />
                  <YAxis 
                    tick={{ fontSize: 11, fill: '#6b7280' }} 
                    width={35}
                    label={{ value: 'Open Items', angle: -90, position: 'insideLeft', offset: 10, fontSize: 10, fill: '#9ca3af' }}
                  />
                  <Tooltip 
                    contentStyle={{ fontSize: '12px', padding: '10px', borderRadius: '8px', border: '1px solid #e5e7eb' }}
                    labelFormatter={(label) => `Date: ${label}`}
                    formatter={(value, name) => [value, name === 'total' ? 'Total Open' : name === 'stories' ? 'Open Stories' : 'Open Bugs']}
                  />
                  <Area type="monotone" dataKey="stories" stackId="1" stroke="#3b82f6" fill="url(#storiesGradient)" strokeWidth={2} name="stories" />
                  <Area type="monotone" dataKey="bugs" stackId="1" stroke="#f97316" fill="url(#bugsGradient)" strokeWidth={2} name="bugs" />
                  <Line type="monotone" dataKey="total" stroke="#374151" strokeWidth={2} strokeDasharray="5 5" dot={false} name="total" />
                </AreaChart>
              </ResponsiveContainer>
              <div className="chart-footer">
                <span className="chart-insight">
                  {trendAnalysis?.trend_direction === 'improving' 
                    ? `Good progress! Open items have decreased by ${(trendAnalysis.period_start_total || 0) - (trendAnalysis.current_total || 0)} since IRR.`
                    : trendAnalysis?.trend_direction === 'declining'
                      ? `Attention: Open items have increased by ${(trendAnalysis.current_total || 0) - (trendAnalysis.period_start_total || 0)} since IRR.`
                      : 'Open items have remained stable since IRR.'}
                </span>
              </div>
            </div>
          )}

          {/* No data message */}
          {!trendAnalysis?.has_data && (
            <div className="trends-no-data">
              <Clock size={24} />
              <span>{trendAnalysis?.message || 'Collecting trend data... Check back in a few hours.'}</span>
            </div>
          )}
        </div>

        {/* SECTION: Resolution Progress Chart - Day-wise cumulative progress */}
        {resolutionProgressData?.chartData?.length > 0 && (
          <div className="resolution-progress-section">
            <div className="resolution-progress-header">
              <div className="resolution-progress-title">
                <BarChart3 size={18} />
                <h3>Resolution Progress</h3>
                <span className="resolution-progress-subtitle">
                  IRR to Final Build - Day-wise cumulative resolutions
                </span>
                <span className="resolution-progress-jql-info">
                  <Info size={14} />
                  <span className="jql-tooltip">
                    Tracks all resolved/closed Stories and Bugs for {selectedRelease} NS Client component (excludes EPICs, Sub-tasks, Tasks, and Escalations)
                    {resolutionProgressData?.jql && (
                      <>
                        {'\n\n'}JQL: {resolutionProgressData.jql}
                      </>
                    )}
                  </span>
                </span>
              </div>
              <div className="resolution-progress-stats">
                <div className="rp-stat">
                  <span className="rp-stat-value">{resolutionProgressData.summary?.totalResolved || 0}</span>
                  <span className="rp-stat-label">Total Resolved</span>
                </div>
                <div className="rp-stat stories">
                  <span className="rp-stat-value">{resolutionProgressData.summary?.totalStories || 0}</span>
                  <span className="rp-stat-label">Stories</span>
                </div>
                <div className="rp-stat bugs">
                  <span className="rp-stat-value">{resolutionProgressData.summary?.totalBugs || 0}</span>
                  <span className="rp-stat-label">Bugs</span>
                </div>
                <div className="rp-stat avg">
                  <span className="rp-stat-value">{resolutionProgressData.summary?.avgPerDay || 0}</span>
                  <span className="rp-stat-label">Avg/Day</span>
                </div>
              </div>
            </div>
            
            <div className="resolution-progress-chart">
              {resolutionProgressLoading ? (
                <div className="chart-loading">
                  <RefreshCw size={24} className="spin" />
                  <span>Loading progress data...</span>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <AreaChart
                    data={resolutionProgressData.chartData}
                    margin={{ top: 20, right: 30, left: 20, bottom: 60 }}
                  >
                    <defs>
                      <linearGradient id="storiesGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#4CAF50" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="#4CAF50" stopOpacity={0.1}/>
                      </linearGradient>
                      <linearGradient id="bugsGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#FF5722" stopOpacity={0.8}/>
                        <stop offset="95%" stopColor="#FF5722" stopOpacity={0.1}/>
                      </linearGradient>
                      <linearGradient id="productGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2196F3" stopOpacity={0.7}/>
                        <stop offset="95%" stopColor="#2196F3" stopOpacity={0.1}/>
                      </linearGradient>
                      <linearGradient id="npaGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#9C27B0" stopOpacity={0.7}/>
                        <stop offset="95%" stopColor="#9C27B0" stopOpacity={0.1}/>
                      </linearGradient>
                      <linearGradient id="epdlpGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#FF9800" stopOpacity={0.7}/>
                        <stop offset="95%" stopColor="#FF9800" stopOpacity={0.1}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                    <XAxis 
                      dataKey="displayDate" 
                      stroke="var(--text-muted)"
                      angle={-45}
                      textAnchor="end"
                      height={60}
                      tick={{ fontSize: 11 }}
                      interval="preserveStartEnd"
                    />
                    <YAxis 
                      stroke="var(--text-muted)"
                      tick={{ fontSize: 11 }}
                      label={{ value: 'Cumulative Resolutions', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: 'var(--text-muted)' } }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 'var(--radius-md)',
                        color: 'var(--text-primary)',
                        fontSize: '12px'
                      }}
                      formatter={(value, name) => {
                        const labels = {
                          'YOUR_PRODUCT': 'NS Client',
                          'cumulativeStories': 'Stories',
                          'cumulativeBugs': 'Bugs',
                          'cumulativeTotal': 'Total'
                        };
                        return [value, labels[name] || name];
                      }}
                    />
                    <Legend 
                      wrapperStyle={{ paddingTop: '15px' }}
                      iconType="square"
                      formatter={(value) => {
                        const labels = {
                          'YOUR_PRODUCT': 'NS Client'
                        };
                        return labels[value] || value;
                      }}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="YOUR_PRODUCT" 
                      stackId="1"
                      stroke="#2196F3" 
                      fill="url(#productGradient)" 
                      name="YOUR_PRODUCT"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
            
            {/* Component breakdown mini stats */}
            <div className="resolution-progress-components">
              {resolutionProgressData.summary?.byComponent && Object.entries(resolutionProgressData.summary.byComponent).map(([comp, count]) => (
                <div key={comp} className={`rp-component ${comp.toLowerCase()}`}>
                  <span className="rp-comp-name">{comp === 'YOUR_PRODUCT' ? 'NS Client' : comp}</span>
                  <span className="rp-comp-count">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ALL CLEAR STATE */}
        {totalOpen === 0 && totalAwaitingQA === 0 && (
          <div className="all-clear-banner">
            <CheckCircle size={48} />
            <h2>🎉 Release Ready!</h2>
            <p>All items resolved and verified for {selectedComponent}</p>
            </div>
            )}
      </div>

      {/* Commit Analysis Modal */}
      {selectedCommitForAnalysis && (
        <div className="commit-analysis-modal-overlay" onClick={closeCommitAnalysis}>
          <div className="commit-analysis-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                <Search size={18} />
                Commit Analysis
              </h3>
              <button className="modal-close" onClick={closeCommitAnalysis}>
                <X size={20} />
              </button>
            </div>
            
            <div className="modal-subheader">
              <span className="commit-sha-badge">{selectedCommitForAnalysis.commit.sha}</span>
              <span className="commit-repo">{selectedCommitForAnalysis.repoData.name}</span>
              <a 
                href={selectedCommitForAnalysis.commit.url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="view-on-github"
              >
                <ExternalLink size={14} />
                View on GitHub
              </a>
            </div>
            
            <div className="commit-message-full">
              {selectedCommitForAnalysis.commit.message}
            </div>

            <div className="modal-content">
              {commitAnalysisLoading && (
                <div className="analysis-loading">
                  <Loader className="spinner" size={24} />
                  <span>Analyzing commit...</span>
                </div>
              )}
              
              {commitAnalysisError && (
                <div className="analysis-error">
                  <AlertTriangle size={20} />
                  <span>{commitAnalysisError}</span>
                </div>
              )}
              
              {commitAnalysis && !commitAnalysisLoading && (
                <div className="analysis-results">
                  {/* Files Changed Summary */}
                  <div className="analysis-section">
                    <h4><FileCode size={16} /> Files Changed</h4>
                    <div className="files-stats">
                      <span className="stat">
                        <strong>{commitAnalysis.files_changed}</strong> files
                      </span>
                      <span className="stat additions">
                        +{commitAnalysis.stats?.additions || 0}
                      </span>
                      <span className="stat deletions">
                        -{commitAnalysis.stats?.deletions || 0}
                      </span>
                    </div>
                    
                    {commitAnalysis.files_by_component && Object.keys(commitAnalysis.files_by_component).length > 0 && (
                      <div className="files-by-component">
                        {Object.entries(commitAnalysis.files_by_component).map(([component, data]) => (
                          <div key={component} className="component-group">
                            <div className="component-header">
                              <Folder size={14} />
                              <span className="component-name">{component}/</span>
                              <span className="component-count">{data.count} files</span>
                            </div>
                            <div className="component-files">
                              {data.files?.slice(0, 5).map((file, idx) => (
                                <div key={idx} className={`file-item ${file.status}`}>
                                  <span className="file-status">{file.status === 'added' ? '+' : file.status === 'removed' ? '-' : 'M'}</span>
                                  <span className="file-name">{file.filename?.split('/').pop()}</span>
                                  <span className="file-changes">+{file.additions}/-{file.deletions}</span>
                                </div>
                              ))}
                              {data.files?.length > 5 && (
                                <div className="more-files">...and {data.files.length - 5} more</div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Test Impact */}
                  <div className="analysis-section">
                    <h4><Target size={16} /> Predicted Test Impact</h4>
                    <div className="test-impact-areas">
                      {commitAnalysis.test_impact?.primary_areas?.map((area, idx) => (
                        <span key={idx} className="test-area-badge">
                          {area}
                          {commitAnalysis.test_impact?.areas?.[area] > 1 && (
                            <span className="area-count">({commitAnalysis.test_impact.areas[area]})</span>
                          )}
                        </span>
                      ))}
                      {(!commitAnalysis.test_impact?.primary_areas || commitAnalysis.test_impact.primary_areas.length === 0) && (
                        <span className="no-impact">No specific test areas identified</span>
                      )}
                    </div>
                  </div>

                  {/* LLM Analysis */}
                  {commitAnalysis.llm_analysis?.available && (
                    <div className="analysis-section llm-section">
                      <h4><Zap size={16} /> AI Analysis</h4>
                      
                      {commitAnalysis.llm_analysis.summary && (
                        <div className="llm-summary">
                          <p>{commitAnalysis.llm_analysis.summary}</p>
                        </div>
                      )}
                      
                      {commitAnalysis.llm_analysis.risk_level && (
                        <div className={`risk-indicator ${commitAnalysis.llm_analysis.risk_level}`}>
                          <span className="risk-label">Risk Level:</span>
                          <span className="risk-value">{commitAnalysis.llm_analysis.risk_level.toUpperCase()}</span>
                          {commitAnalysis.llm_analysis.risk_reason && (
                            <span className="risk-reason">{commitAnalysis.llm_analysis.risk_reason}</span>
                          )}
                        </div>
                      )}
                      
                      {commitAnalysis.llm_analysis.testing_recommendations?.length > 0 && (
                        <div className="testing-recommendations">
                          <strong>Recommended Tests:</strong>
                          <ul>
                            {commitAnalysis.llm_analysis.testing_recommendations.map((rec, idx) => (
                              <li key={idx}>{rec}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      
                      {commitAnalysis.llm_analysis.key_changes?.length > 0 && (
                        <div className="key-changes">
                          <strong>Key Changes:</strong>
                          <ul>
                            {commitAnalysis.llm_analysis.key_changes.map((change, idx) => (
                              <li key={idx}>{change}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                  
                  {commitAnalysis.llm_analysis && !commitAnalysis.llm_analysis.available && (
                    <div className="analysis-section llm-unavailable">
                      <h4><Zap size={16} /> AI Analysis</h4>
                      <p className="unavailable-msg">
                        <AlertTriangle size={14} />
                        {commitAnalysis.llm_analysis.error || 'LLM analysis unavailable. Check Ollama configuration (is ollama serve running?).'}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Detail Modal for Release Content, Developer Workload, QA Backlog */}
      {detailModal && (
        <div className="detail-modal-overlay" onClick={() => setDetailModal(null)}>
          <div className="detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>
                {detailModal === 'releaseContent' && (
                  <>
                    <Package size={18} />
                    Release Content for R{nplansData?.release || selectedRelease?.replace(/[^\d]/g, '').split('.')[0]}
                  </>
                )}
                {detailModal === 'devWorkload' && (
                  <>
                    <Users size={18} />
                    Developer Workload
                  </>
                )}
                {detailModal === 'qaBacklog' && (
                  <>
                    <CheckSquare size={18} />
                    QA Backlog
                  </>
                )}
              </h3>
              <button className="modal-close" onClick={() => setDetailModal(null)}>
                <X size={20} />
              </button>
            </div>

            {/* Filter and Summary Bar */}
            <div className="modal-toolbar">
              <div className="modal-search">
                <Search size={16} />
                <input
                  type="text"
                  placeholder="Filter by assignee, ticket ID, or summary..."
                  value={detailModalFilter}
                  onChange={(e) => {
                    setDetailModalFilter(e.target.value);
                    setDetailModalPage(1);
                  }}
                />
                {detailModalFilter && (
                  <button className="clear-filter" onClick={() => { setDetailModalFilter(''); setDetailModalPage(1); }}>
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>

            {/* Quick Stats Summary Bar */}
            <div className="modal-stats-bar">
              {detailModal === 'releaseContent' && nplansData && (() => {
                const items = nplansData.items || [];
                const statusCounts = items.reduce((acc, item) => {
                  const status = item.status?.toLowerCase() || 'unknown';
                  if (status.includes('done') || status.includes('complete')) acc.done++;
                  else if (status.includes('progress') || status.includes('dev')) acc.inProgress++;
                  else if (status.includes('block') || status.includes('hold')) acc.blocked++;
                  else acc.other++;
                  return acc;
                }, { done: 0, inProgress: 0, blocked: 0, other: 0 });
                const openBugs = nplanBugsData?.summary?.open_bugs || 0;
                const closedBugs = (nplanBugsData?.summary?.total_bugs || 0) - openBugs;
                return (
                  <>
                    <div className="stat-chip total"><Package size={14} />{items.length} NPLANs</div>
                    <div className="stat-chip done"><CheckCircle size={14} />{statusCounts.done} Done</div>
                    <div className="stat-chip in-progress"><Clock size={14} />{statusCounts.inProgress} In Progress</div>
                    {statusCounts.blocked > 0 && <div className="stat-chip blocked"><AlertTriangle size={14} />{statusCounts.blocked} Blocked</div>}
                    <div className="stat-chip bugs-open"><Bug size={14} />{openBugs} Open Bugs</div>
                    {closedBugs > 0 && <div className="stat-chip bugs-closed"><CheckSquare size={14} />{closedBugs} Closed Bugs</div>}
                  </>
                );
              })()}
              {detailModal === 'devWorkload' && (() => {
                const allTickets = allAssignees.flatMap(([_, data]) => data.tickets || []);
                const stories = allTickets.filter(t => t.type !== 'Bug').length;
                const bugs = allTickets.filter(t => t.type === 'Bug').length;
                const inReview = allTickets.filter(t => t.status?.toLowerCase() === 'code review').length;
                const inProgress = allTickets.filter(t => t.status?.toLowerCase() === 'in progress').length;
                return (
                  <>
                    <div className="stat-chip total"><Users size={14} />{allAssignees.length} Assignees</div>
                    <div className="stat-chip stories"><BookOpen size={14} />{stories} Stories</div>
                    <div className="stat-chip bugs-open"><Bug size={14} />{bugs} Bugs</div>
                    <div className="stat-chip in-progress"><Clock size={14} />{inProgress} In Progress</div>
                    <div className="stat-chip in-review"><GitPullRequest size={14} />{inReview} In Review</div>
                  </>
                );
              })()}
              {detailModal === 'qaBacklog' && (() => {
                const allTickets = allQAs.flatMap(([_, data]) => data.tickets || []);
                const stories = allTickets.filter(t => t.type !== 'Bug').length;
                const bugs = allTickets.filter(t => t.type === 'Bug').length;
                const readyForQA = allTickets.filter(t => 
                  t.status?.toLowerCase().includes('ready') || t.status?.toLowerCase().includes('resolved')
                ).length;
                const inQA = allTickets.filter(t => t.status?.toLowerCase().includes('qa')).length;
                return (
                  <>
                    <div className="stat-chip total"><Users size={14} />{allQAs.length} QA Assignees</div>
                    <div className="stat-chip stories"><BookOpen size={14} />{stories} Stories</div>
                    <div className="stat-chip bugs-open"><Bug size={14} />{bugs} Bugs</div>
                    <div className="stat-chip ready"><Target size={14} />{readyForQA} Ready for QA</div>
                    {inQA > 0 && <div className="stat-chip in-progress"><Clock size={14} />{inQA} In QA</div>}
                  </>
                );
              })()}
            </div>

            <div className="modal-content">
              {/* Release Content Table */}
              {detailModal === 'releaseContent' && (() => {
                const filteredItems = (nplansData?.items || [])
                  .filter(item => {
                    if (!detailModalFilter) return true;
                    const filter = detailModalFilter.toLowerCase();
                    return (
                      item.id?.toLowerCase().includes(filter) ||
                      item.description?.toLowerCase().includes(filter) ||
                      item.status?.toLowerCase().includes(filter)
                    );
                  })
                  .sort((a, b) => {
                    if (!detailModalSort.field) return 0;
                    let aVal, bVal;
                    if (detailModalSort.field === 'bugs') {
                      aVal = nplanBugsData?.nplan_bugs?.[a.id]?.total || 0;
                      bVal = nplanBugsData?.nplan_bugs?.[b.id]?.total || 0;
                    } else {
                      aVal = a[detailModalSort.field] || '';
                      bVal = b[detailModalSort.field] || '';
                    }
                    if (typeof aVal === 'number') {
                      return detailModalSort.direction === 'asc' ? aVal - bVal : bVal - aVal;
                    }
                    return detailModalSort.direction === 'asc' 
                      ? String(aVal).localeCompare(String(bVal))
                      : String(bVal).localeCompare(String(aVal));
                  });
                const totalPages = Math.ceil(filteredItems.length / ITEMS_PER_PAGE);
                const startIdx = (detailModalPage - 1) * ITEMS_PER_PAGE;
                const paginatedItems = filteredItems.slice(startIdx, startIdx + ITEMS_PER_PAGE);
                
                return (
                  <>
                    <div className="detail-table-container">
                      <table className="detail-table">
                        <thead>
                          <tr>
                            <th 
                              className={`sortable ${detailModalSort.field === 'id' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'id',
                                direction: prev.field === 'id' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              NPLAN ID <ArrowUpDown size={12} />
                            </th>
                            <th>Description</th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'status' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'status',
                                direction: prev.field === 'status' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Status <ArrowUpDown size={12} />
                            </th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'bugs' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'bugs',
                                direction: prev.field === 'bugs' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Linked Bugs <ArrowUpDown size={12} />
                            </th>
                            <th>Notes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedItems.map((item, idx) => {
                            const bugsForNplan = nplanBugsData?.nplan_bugs?.[item.id];
                            const bugCount = bugsForNplan?.total || 0;
                            const openBugCount = bugsForNplan?.open || 0;
                            return (
                              <tr key={idx} className={item.status?.toLowerCase().replace(' ', '-')}>
                                <td>
                                  {item.jira_url ? (
                                    <a href={item.jira_url} target="_blank" rel="noopener noreferrer">
                                      {item.id}
                                    </a>
                                  ) : (
                                    item.id || '—'
                                  )}
                                </td>
                                <td className="desc-cell" title={item.description}>{item.description || '—'}</td>
                                <td>
                                  <span className={`status-badge ${item.status?.toLowerCase().replace(' ', '-')}`}>
                                    {item.status || 'TBD'}
                                  </span>
                                </td>
                                <td>
                                  {bugCount > 0 ? (
                                    <span className={`bug-count ${openBugCount > 0 ? 'has-open' : 'all-closed'}`}>
                                      {openBugCount > 0 ? `${openBugCount} open` : `${bugCount} closed`}
                                    </span>
                                  ) : (
                                    <span className="no-bugs">—</span>
                                  )}
                                </td>
                                <td className="notes-cell" title={item.notes}>{item.notes || '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {totalPages > 1 && (
                      <div className="modal-pagination">
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(1)}
                          title="First page"
                        >
                          <ChevronLeft size={14} /><ChevronLeft size={14} style={{ marginLeft: -8 }} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(p => p - 1)}
                          title="Previous page"
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <span className="pagination-info">
                          {startIdx + 1}–{Math.min(startIdx + ITEMS_PER_PAGE, filteredItems.length)} of {filteredItems.length}
                        </span>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(p => p + 1)}
                          title="Next page"
                        >
                          <ChevronRight size={16} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(totalPages)}
                          title="Last page"
                        >
                          <ChevronRight size={14} /><ChevronRight size={14} style={{ marginLeft: -8 }} />
                        </button>
                      </div>
                    )}
                  </>
                );
              })()}

              {/* Developer Workload Table */}
              {detailModal === 'devWorkload' && (() => {
                const filteredTickets = allAssignees
                  .flatMap(([name, data]) => 
                    (data.tickets || []).map(ticket => ({ ...ticket, assignee: name }))
                  )
                  .filter(ticket => {
                    if (!detailModalFilter) return true;
                    const filter = detailModalFilter.toLowerCase();
                    return (
                      ticket.key?.toLowerCase().includes(filter) ||
                      ticket.summary?.toLowerCase().includes(filter) ||
                      ticket.assignee?.toLowerCase().includes(filter) ||
                      ticket.type?.toLowerCase().includes(filter)
                    );
                  })
                  .sort((a, b) => {
                    if (!detailModalSort.field) return 0;
                    const aVal = a[detailModalSort.field] || '';
                    const bVal = b[detailModalSort.field] || '';
                    return detailModalSort.direction === 'asc' 
                      ? String(aVal).localeCompare(String(bVal))
                      : String(bVal).localeCompare(String(aVal));
                  });
                const totalPages = Math.ceil(filteredTickets.length / ITEMS_PER_PAGE);
                const startIdx = (detailModalPage - 1) * ITEMS_PER_PAGE;
                const paginatedTickets = filteredTickets.slice(startIdx, startIdx + ITEMS_PER_PAGE);
                
                return (
                  <>
                    <div className="detail-table-container">
                      <table className="detail-table">
                        <thead>
                          <tr>
                            <th 
                              className={`sortable ${detailModalSort.field === 'key' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'key',
                                direction: prev.field === 'key' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Ticket <ArrowUpDown size={12} />
                            </th>
                            <th>Summary</th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'type' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'type',
                                direction: prev.field === 'type' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Type <ArrowUpDown size={12} />
                            </th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'priority' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'priority',
                                direction: prev.field === 'priority' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Priority <ArrowUpDown size={12} />
                            </th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'assignee' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'assignee',
                                direction: prev.field === 'assignee' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Assignee <ArrowUpDown size={12} />
                            </th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedTickets.map((ticket, idx) => (
                            <tr key={idx}>
                              <td>
                                <a 
                                  href={ticket.url || `https://your-org.atlassian.net/browse/${ticket.key}`}
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {ticket.key}
                                </a>
                              </td>
                              <td className="summary-cell" title={ticket.summary}>{ticket.summary}</td>
                              <td>
                                <span className={`type-badge ${ticket.type?.toLowerCase()}`}>
                                  {ticket.type}
                                </span>
                              </td>
                              <td>
                                <span className={`priority-badge ${ticket.priority?.toLowerCase()}`}>
                                  {ticket.priority}
                                </span>
                              </td>
                              <td>{ticket.assignee}</td>
                              <td>
                                <span className={`status-badge ${ticket.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                  {ticket.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {totalPages > 1 && (
                      <div className="modal-pagination">
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(1)}
                          title="First page"
                        >
                          <ChevronLeft size={14} /><ChevronLeft size={14} style={{ marginLeft: -8 }} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(p => p - 1)}
                          title="Previous page"
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <span className="pagination-info">
                          {startIdx + 1}–{Math.min(startIdx + ITEMS_PER_PAGE, filteredTickets.length)} of {filteredTickets.length}
                        </span>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(p => p + 1)}
                          title="Next page"
                        >
                          <ChevronRight size={16} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(totalPages)}
                          title="Last page"
                        >
                          <ChevronRight size={14} /><ChevronRight size={14} style={{ marginLeft: -8 }} />
                        </button>
                      </div>
                    )}
                  </>
                );
              })()}

              {/* QA Backlog Table */}
              {detailModal === 'qaBacklog' && (() => {
                const filteredTickets = allQAs
                  .flatMap(([name, data]) => 
                    (data.tickets || []).map(ticket => ({ ...ticket, assignee: name }))
                  )
                  .filter(ticket => {
                    if (!detailModalFilter) return true;
                    const filter = detailModalFilter.toLowerCase();
                    return (
                      ticket.key?.toLowerCase().includes(filter) ||
                      ticket.summary?.toLowerCase().includes(filter) ||
                      ticket.assignee?.toLowerCase().includes(filter) ||
                      ticket.type?.toLowerCase().includes(filter)
                    );
                  })
                  .sort((a, b) => {
                    if (!detailModalSort.field) return 0;
                    const aVal = a[detailModalSort.field] || '';
                    const bVal = b[detailModalSort.field] || '';
                    return detailModalSort.direction === 'asc' 
                      ? String(aVal).localeCompare(String(bVal))
                      : String(bVal).localeCompare(String(aVal));
                  });
                const totalPages = Math.ceil(filteredTickets.length / ITEMS_PER_PAGE);
                const startIdx = (detailModalPage - 1) * ITEMS_PER_PAGE;
                const paginatedTickets = filteredTickets.slice(startIdx, startIdx + ITEMS_PER_PAGE);
                
                return (
                  <>
                    <div className="detail-table-container">
                      <table className="detail-table">
                        <thead>
                          <tr>
                            <th 
                              className={`sortable ${detailModalSort.field === 'key' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'key',
                                direction: prev.field === 'key' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Ticket <ArrowUpDown size={12} />
                            </th>
                            <th>Summary</th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'type' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'type',
                                direction: prev.field === 'type' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              Type <ArrowUpDown size={12} />
                            </th>
                            <th 
                              className={`sortable ${detailModalSort.field === 'assignee' ? detailModalSort.direction : ''}`}
                              onClick={() => setDetailModalSort(prev => ({
                                field: 'assignee',
                                direction: prev.field === 'assignee' && prev.direction === 'asc' ? 'desc' : 'asc'
                              }))}
                            >
                              QA Assignee <ArrowUpDown size={12} />
                            </th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedTickets.map((ticket, idx) => (
                            <tr key={idx}>
                              <td>
                                <a 
                                  href={ticket.url || `https://your-org.atlassian.net/browse/${ticket.key}`}
                                  target="_blank" 
                                  rel="noopener noreferrer"
                                >
                                  {ticket.key}
                                </a>
                              </td>
                              <td className="summary-cell" title={ticket.summary}>{ticket.summary}</td>
                              <td>
                                <span className={`type-badge ${ticket.type?.toLowerCase()}`}>
                                  {ticket.type}
                                </span>
                              </td>
                              <td>{ticket.assignee}</td>
                              <td>
                                <span className={`status-badge ${ticket.status?.toLowerCase().replace(/\s+/g, '-')}`}>
                                  {ticket.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {totalPages > 1 && (
                      <div className="modal-pagination">
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(1)}
                          title="First page"
                        >
                          <ChevronLeft size={14} /><ChevronLeft size={14} style={{ marginLeft: -8 }} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === 1}
                          onClick={() => setDetailModalPage(p => p - 1)}
                          title="Previous page"
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <span className="pagination-info">
                          {startIdx + 1}–{Math.min(startIdx + ITEMS_PER_PAGE, filteredTickets.length)} of {filteredTickets.length}
                        </span>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(p => p + 1)}
                          title="Next page"
                        >
                          <ChevronRight size={16} />
                        </button>
                        <button 
                          className="pagination-btn"
                          disabled={detailModalPage === totalPages}
                          onClick={() => setDetailModalPage(totalPages)}
                          title="Last page"
                        >
                          <ChevronRight size={14} /><ChevronRight size={14} style={{ marginLeft: -8 }} />
                        </button>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReleaseReadinessSection;
