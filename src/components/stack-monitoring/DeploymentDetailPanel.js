import React, { useState, useEffect } from 'react';
import { 
  X,
  Server,
  Cpu,
  HardDrive,
  Terminal,
  FileText,
  Activity,
  Clock,
  RotateCcw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronRight,
  RefreshCw,
  Copy,
  Check,
  ExternalLink,
  BarChart3,
  Heart,
  AlertOctagon
} from 'lucide-react';
import StackHistoryChart from './StackHistoryChart';

/**
 * DeploymentDetailPanel - Side panel showing detailed deployment information
 */
const DeploymentDetailPanel = ({
  isOpen,
  deployment,
  details,
  loading,
  error,
  podLogs,
  loadingLogs,
  selectedPodForLogs,
  stackHistory,
  loadingHistory,
  activeTab,
  onClose,
  onTabChange,
  onFetchLogs,
  onSelectPod,
  onFetchHistory
}) => {
  const [copiedCommand, setCopiedCommand] = useState(null);
  
  const STACK_CONTEXTS = {
    'qa01': 'stork-qa01-mp-npe-iad0-nc1',
    'stg01': 'stork-stg01-mp-iad0-nc4',
    'stg01_mplegacy': 'stork-stg01-mp-iad0-nc4'
  };
  
  const copyCommand = (command, id) => {
    navigator.clipboard.writeText(command).then(() => {
      setCopiedCommand(id);
      setTimeout(() => setCopiedCommand(null), 2000);
    });
  };
  
  const getStatusIcon = (status) => {
    if (status === 'healthy' || status === 'Running') {
      return <CheckCircle size={14} style={{ color: 'var(--accent-green)' }} />;
    }
    if (status?.includes('unhealthy') || status === 'Failed' || status === 'CrashLoopBackOff') {
      return <XCircle size={14} style={{ color: 'var(--accent-red)' }} />;
    }
    return <AlertTriangle size={14} style={{ color: 'var(--accent-orange)' }} />;
  };
  
  // Fetch history when History tab is selected
  // Use a ref to track if we've already fetched for this deployment to prevent duplicate fetches
  const lastFetchedKey = React.useRef(null);
  const deploymentKey = deployment ? `${deployment.namespace}/${deployment.deployment}/${deployment.stack}` : null;
  
  useEffect(() => {
    // Only fetch if:
    // 1. Panel is open and History tab is active
    // 2. Not currently loading
    // 3. We have a fetch function
    // 4. We haven't already fetched for this exact deployment
    if (isOpen && activeTab === 'history' && !loadingHistory && onFetchHistory && deploymentKey) {
      // Check if we already fetched for this deployment
      if (lastFetchedKey.current !== deploymentKey) {
        lastFetchedKey.current = deploymentKey;
        onFetchHistory(24);
      }
    }
    
    // Reset the ref when panel closes so we re-fetch when reopened
    if (!isOpen) {
      lastFetchedKey.current = null;
    }
  }, [isOpen, activeTab, deploymentKey, loadingHistory, onFetchHistory]);
  
  if (!isOpen) return null;

  const deploymentName = deployment?.deployment?.split('/')[0] || deployment?.deployment;
  const context = STACK_CONTEXTS[deployment?.stack] || deployment?.stack;

  return (
    <>
      {/* Backdrop overlay */}
      <div 
        className="deployment-detail-backdrop" 
        onClick={onClose}
        aria-hidden="true"
      />
      
      <div className={`deployment-detail-panel ${isOpen ? 'open' : ''}`}>
        {/* Header */}
        <div className="panel-header">
        <div className="header-info">
          <Server size={20} />
          <div>
            <h3>{deploymentName}</h3>
            <div className="header-badges">
              <span className="stack-badge">{deployment?.stack}</span>
              {deployment?.namespace && (
                <span className="namespace-badge" title={`Namespace: ${deployment.namespace}`}>
                  {deployment.namespace.replace(/^--/, '').split('--').pop() || deployment.namespace}
                </span>
              )}
            </div>
          </div>
        </div>
        <button className="close-btn" onClick={onClose}>
          <X size={20} />
        </button>
      </div>
      
      {/* Tabs */}
      <div className="panel-tabs">
        <button 
          className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => onTabChange('overview')}
        >
          <Activity size={14} /> Overview
        </button>
        <button 
          className={`tab ${activeTab === 'pods' ? 'active' : ''}`}
          onClick={() => onTabChange('pods')}
        >
          <Server size={14} /> Pods
        </button>
        <button 
          className={`tab ${activeTab === 'logs' ? 'active' : ''}`}
          onClick={() => onTabChange('logs')}
        >
          <FileText size={14} /> Logs
        </button>
        <button 
          className={`tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => onTabChange('history')}
        >
          <BarChart3 size={14} /> History
        </button>
      </div>
      
      {/* Content */}
      <div className="panel-content">
        {loading && (
          <div className="loading-state">
            <RefreshCw size={24} className="spinning" />
            <span>Loading deployment details...</span>
          </div>
        )}
        
        {error && (
          <div className="error-state">
            <XCircle size={24} />
            <span>{error}</span>
          </div>
        )}
        
        {!loading && !error && details && (
          <>
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div className="tab-content overview">
                {/* Status Card */}
                <div className="detail-card">
                  <h4>Status</h4>
                  <div className="status-grid">
                    <div className="status-item">
                      <span className="label">Replicas</span>
                      <span className="value">
                        {details.replicas?.ready || 0}/{details.replicas?.desired || 0}
                        {details.replicas?.unavailable > 0 && (
                          <span className="warning"> ({details.replicas.unavailable} unavailable)</span>
                        )}
                      </span>
                    </div>
                    <div className="status-item">
                      <span className="label">Age</span>
                      <span className="value">{details.age || 'Unknown'}</span>
                    </div>
                    <div className="status-item">
                      <span className="label">Restarts</span>
                      <span className={`value ${details.total_restarts > 5 ? 'warning' : ''}`}>
                        {details.total_restarts || 0}
                      </span>
                    </div>
                    {details.created_at && (
                      <div className="status-item full-width">
                        <span className="label">Created</span>
                        <span className="value small">
                          {new Date(details.created_at).toLocaleDateString()} {new Date(details.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                    )}
                    {details.load_time_ms && (
                      <div className="status-item">
                        <span className="label">Load Time</span>
                        <span className="value small">{details.load_time_ms}ms</span>
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Containers */}
                <div className="detail-card">
                  <h4>Containers</h4>
                  {details.containers?.map((c, idx) => (
                    <div key={idx} className="container-item expanded">
                      <div className="container-header">
                        <span className="container-name">{c.name}</span>
                        <span className="container-version">{c.version}</span>
                      </div>
                      {c.image && (
                        <div className="container-image">
                          <span className="image-label">Image:</span>
                          <code className="image-url" title={c.image}>
                            {c.image.length > 60 ? `...${c.image.slice(-57)}` : c.image}
                          </code>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                
                {/* Resource Usage */}
                {details.resource_metrics && Object.keys(details.resource_metrics).length > 0 && (
                  <div className="detail-card">
                    <h4>
                      <Cpu size={14} />
                      Resource Usage
                    </h4>
                    <div className="resource-usage-list">
                      {Object.entries(details.resource_metrics).map(([podName, metrics], idx) => (
                        <div key={idx} className="resource-row">
                          <span className="pod-name" title={podName}>
                            {podName.length > 25 ? `${podName.slice(0, 12)}...${podName.slice(-10)}` : podName}
                          </span>
                          <div className="resource-values">
                            <span className="resource-item cpu">
                              <Cpu size={12} />
                              {metrics.cpu?.usage || 'N/A'}
                            </span>
                            <span className="resource-item memory">
                              <HardDrive size={12} />
                              {metrics.memory?.usage || 'N/A'}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {/* Pod Locations */}
                {details.pods && details.pods.length > 0 && (
                  <div className="detail-card">
                    <h4>
                      <Server size={14} />
                      Pod Locations
                    </h4>
                    <div className="pod-locations-list">
                      {details.pods.slice(0, 5).map((pod, idx) => (
                        <div key={idx} className="pod-location-row">
                          <div className="pod-info">
                            <span className={`pod-status-dot ${pod.status?.toLowerCase().replace(/\s/g, '-')}`}></span>
                            <span className="pod-name-short" title={pod.name}>
                              {pod.name.length > 30 ? `${pod.name.slice(0, 15)}...${pod.name.slice(-12)}` : pod.name}
                            </span>
                          </div>
                          <div className="pod-details">
                            {pod.ip && <span className="pod-ip" title="Pod IP">{pod.ip}</span>}
                            {pod.node && (
                              <span className="pod-node" title={`Node: ${pod.node}`}>
                                {pod.node.length > 20 ? `${pod.node.slice(0, 17)}...` : pod.node}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                      {details.pods.length > 5 && (
                        <div className="more-pods">+{details.pods.length - 5} more pods</div>
                      )}
                    </div>
                  </div>
                )}
                
                {/* Probes */}
                {details.probes && (
                  <div className="detail-card probes-card">
                    <h4>Health Probes</h4>
                    <div className="probes-grid">
                      <div className={`probe ${details.probes.readiness?.configured ? 'configured' : 'not-configured'}`}>
                        <Heart size={14} />
                        <span>Readiness</span>
                        {details.probes.readiness?.configured ? (
                          <span className={`status ${details.probes.readiness.status}`}>
                            {details.probes.readiness.status}
                          </span>
                        ) : (
                          <span className="status not-set">Not Set</span>
                        )}
                      </div>
                      <div className={`probe ${details.probes.liveness?.configured ? 'configured' : 'not-configured'}`}>
                        <Activity size={14} />
                        <span>Liveness</span>
                        {details.probes.liveness?.configured ? (
                          <span className={`status ${details.probes.liveness.status}`}>
                            {details.probes.liveness.status}
                          </span>
                        ) : (
                          <span className="status not-set">Not Set</span>
                        )}
                      </div>
                    </div>
                  </div>
                )}
                
                {/* Events/Warnings */}
                {details.events && details.events.length > 0 && (
                  <div className="detail-card events-card">
                    <h4>
                      <AlertOctagon size={14} style={{ color: 'var(--accent-orange)' }} />
                      Recent Events ({details.events.length})
                    </h4>
                    <div className="events-list">
                      {details.events.slice(0, 5).map((event, idx) => (
                        <div key={idx} className={`event-item event-${event.type?.toLowerCase()}`}>
                          <div className="event-header">
                            <span className={`event-type ${event.type?.toLowerCase()}`}>
                              {event.type === 'Warning' ? <AlertTriangle size={12} /> : <XCircle size={12} />}
                              {event.reason}
                            </span>
                            <span className="event-age">{event.age}</span>
                          </div>
                          <div className="event-message">{event.message}</div>
                          <div className="event-object">{event.object}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {/* Quick Commands */}
                <div className="detail-card commands-card">
                  <h4>Quick Commands</h4>
                  <div className="commands-list">
                    <div className="command-item">
                      <code>kubectl get deployment {deploymentName} -n {deployment?.namespace} --context={context}</code>
                      <button 
                        className={`copy-btn ${copiedCommand === 'get' ? 'copied' : ''}`}
                        onClick={() => copyCommand(`kubectl get deployment ${deploymentName} -n ${deployment?.namespace} --context=${context}`, 'get')}
                      >
                        {copiedCommand === 'get' ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                    <div className="command-item">
                      <code>kubectl logs -l app={deploymentName} -n {deployment?.namespace} --context={context} --tail=100</code>
                      <button 
                        className={`copy-btn ${copiedCommand === 'logs' ? 'copied' : ''}`}
                        onClick={() => copyCommand(`kubectl logs -l app=${deploymentName} -n ${deployment?.namespace} --context=${context} --tail=100`, 'logs')}
                      >
                        {copiedCommand === 'logs' ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                    <div className="command-item">
                      <code>kubectl describe deployment {deploymentName} -n {deployment?.namespace} --context={context}</code>
                      <button 
                        className={`copy-btn ${copiedCommand === 'describe' ? 'copied' : ''}`}
                        onClick={() => copyCommand(`kubectl describe deployment ${deploymentName} -n ${deployment?.namespace} --context=${context}`, 'describe')}
                      >
                        {copiedCommand === 'describe' ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                    <div className="command-item">
                      <code>kubectl rollout restart deployment {deploymentName} -n {deployment?.namespace} --context={context}</code>
                      <button 
                        className={`copy-btn ${copiedCommand === 'restart' ? 'copied' : ''}`}
                        onClick={() => copyCommand(`kubectl rollout restart deployment ${deploymentName} -n ${deployment?.namespace} --context=${context}`, 'restart')}
                      >
                        {copiedCommand === 'restart' ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
            
            {/* Pods Tab */}
            {activeTab === 'pods' && (
              <div className="tab-content pods">
                {details.pods?.length === 0 ? (
                  <div className="empty-state">No pods found</div>
                ) : (
                  <div className="pods-list">
                    {details.pods?.map((pod, idx) => (
                      <div 
                        key={idx} 
                        className={`pod-item ${pod.crash_loop ? 'crash-loop' : ''} ${selectedPodForLogs === pod.name ? 'selected' : ''}`}
                        onClick={() => onSelectPod(pod.name)}
                      >
                        <div className="pod-main">
                          {getStatusIcon(pod.status)}
                          <div className="pod-info">
                            <span className="pod-name">{pod.name}</span>
                            <span className="pod-meta">
                              {pod.status} | {pod.restarts} restarts | {pod.age}
                            </span>
                          </div>
                        </div>
                        <div className="pod-metrics">
                          {details.resource_metrics?.[pod.name] && (
                            <>
                              <span className="metric">
                                <Cpu size={12} /> {details.resource_metrics[pod.name].cpu?.usage}
                              </span>
                              <span className="metric">
                                <HardDrive size={12} /> {details.resource_metrics[pod.name].memory?.usage}
                              </span>
                            </>
                          )}
                        </div>
                        <ChevronRight size={14} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            
            {/* Logs Tab */}
            {activeTab === 'logs' && (
              <div className="tab-content logs">
                <div className="logs-header">
                  <select 
                    value={selectedPodForLogs || ''} 
                    onChange={(e) => {
                      onSelectPod(e.target.value);
                      onFetchLogs(e.target.value);
                    }}
                  >
                    <option value="">Select a pod...</option>
                    {details.pods?.map((pod, idx) => (
                      <option key={idx} value={pod.name}>{pod.name}</option>
                    ))}
                  </select>
                  <button 
                    className="refresh-btn"
                    onClick={() => selectedPodForLogs && onFetchLogs(selectedPodForLogs)}
                    disabled={!selectedPodForLogs || loadingLogs}
                  >
                    <RefreshCw size={14} className={loadingLogs ? 'spinning' : ''} />
                  </button>
                </div>
                
                <div className="logs-content">
                  {loadingLogs && (
                    <div className="loading-state">
                      <RefreshCw size={20} className="spinning" />
                      <span>Loading logs...</span>
                    </div>
                  )}
                  
                  {!loadingLogs && podLogs?.error && (
                    <div className="error-state">
                      <XCircle size={20} />
                      <span>{podLogs.error}</span>
                    </div>
                  )}
                  
                  {!loadingLogs && podLogs?.logs && (
                    <pre className="log-output">{podLogs.logs}</pre>
                  )}
                  
                  {!loadingLogs && !podLogs && !selectedPodForLogs && (
                    <div className="empty-state">
                      Select a pod to view logs
                    </div>
                  )}
                </div>
              </div>
            )}
            
            {/* History Tab */}
            {activeTab === 'history' && (
              <div className="tab-content history">
                <StackHistoryChart 
                  historyData={stackHistory}
                  loading={loadingHistory}
                  error={stackHistory?.error}
                  chartType="area"
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
    </>
  );
};

export default DeploymentDetailPanel;
