/**
 * DeveloperWorkloadChart - Reusable component for displaying developer workload
 * 
 * Shows a horizontal stacked bar chart of work items grouped by assignee.
 * Used in both ReleaseReadinessSection and DevDigestSection.
 */
import React from 'react';
import { Users, ExternalLink } from 'lucide-react';
import './DeveloperWorkloadChart.css';

/**
 * Build JIRA URL for viewing open items for a release
 * @param {string} release - Release ID (e.g., "R134")
 * @returns {string} JIRA search URL
 */
const buildJiraUrl = (release) => {
  if (!release) return null;
  const versionNum = release.replace('R', '');
  const fixVersion = `${versionNum}.0.0`;
  
  const jql = `(fixVersion = "${fixVersion}") AND (project = ENG AND component = "NS Client (NSC)" AND status not in (resolved, closed, "Pending Close") AND type not in (EPIC, Sub-task, task, Escalation)) ORDER BY assignee ASC, priority DESC`;
  
  return `https://your-org.atlassian.net/issues/?jql=${encodeURIComponent(jql)}`;
};

const DeveloperWorkloadChart = ({ 
  storiesByAssignee = [], 
  title = "Developer Workload",
  showLegend = true,
  maxHeight = "300px",
  release = null  // Optional: pass release to show "Open in JIRA" link
}) => {
  // Calculate workload by assignee
  const workloadByAssignee = {};
  
  storiesByAssignee.forEach(item => {
    const name = item.assignee || 'Unassigned';
    if (!workloadByAssignee[name]) {
      workloadByAssignee[name] = { stories: 0, bugs: 0, review: 0, total: 0 };
    }
    
    // Count stories and bugs separately from tickets
    const tickets = item.tickets || [];
    const storyCount = tickets.filter(t => t.type !== 'Bug' && t.status?.toLowerCase() !== 'code review').length;
    const bugCount = tickets.filter(t => t.type === 'Bug' && t.status?.toLowerCase() !== 'code review').length;
    const reviewCount = tickets.filter(t => t.status?.toLowerCase() === 'code review').length;
    
    workloadByAssignee[name].stories += storyCount;
    workloadByAssignee[name].bugs += bugCount;
    workloadByAssignee[name].review += reviewCount;
    workloadByAssignee[name].total += storyCount + bugCount + reviewCount;
  });
  
  // Sort by total workload (descending)
  const allAssignees = Object.entries(workloadByAssignee)
    .sort((a, b) => b[1].total - a[1].total);
  
  const maxWorkload = Math.max(...allAssignees.map(([_, d]) => d.total), 1);
  const totalDevItems = allAssignees.reduce((acc, [_, d]) => acc + d.total, 0);
  
  if (allAssignees.length === 0) {
    return (
      <div className="workload-chart-shared">
        <div className="chart-header">
          <h3><Users size={16} /> {title}</h3>
          <span className="chart-subtitle">No data available</span>
        </div>
        <div className="empty-chart">No work items found</div>
      </div>
    );
  }
  
  const jiraUrl = buildJiraUrl(release);
  
  return (
    <div className="workload-chart-shared">
      <div className="chart-header">
        <h3 title="Work items yet to be resolved or completed by each developer">
          <Users size={16} /> {title}
        </h3>
        <div className="chart-header-right">
          <span className="chart-subtitle">{totalDevItems} items ({allAssignees.length} assignees)</span>
          {jiraUrl && (
            <a 
              href={jiraUrl} 
              target="_blank" 
              rel="noopener noreferrer"
              className="jira-link"
              title="Open in JIRA"
            >
              <ExternalLink size={14} />
              Open in JIRA
            </a>
          )}
        </div>
      </div>
      <div className="horizontal-bars-shared" style={{ maxHeight }}>
        {allAssignees.map(([name, data]) => (
          <div key={name} className="bar-row">
            <div className="bar-name" title={`${name}: ${data.stories} stories, ${data.bugs} bugs, ${data.review} in review`}>
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
              <span className="bar-total">{data.total}</span>
            </div>
          </div>
        ))}
      </div>
      {showLegend && (
        <div className="chart-legend">
          <span className="legend-item"><span className="dot stories"></span>Stories</span>
          <span className="legend-item"><span className="dot bugs"></span>Bugs</span>
          <span className="legend-item"><span className="dot review"></span>Review</span>
        </div>
      )}
    </div>
  );
};

export default DeveloperWorkloadChart;
