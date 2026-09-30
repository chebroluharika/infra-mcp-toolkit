import { useState, useEffect } from 'react';
import { Brain, X, ExternalLink, RefreshCw, Loader2 } from 'lucide-react';
import { DEFAULT_RELEASE } from '../config';

/**
 * ChatWindow - Embeds Streamlit AI Assistant
 * 
 * The Streamlit app runs on port 8501 and is embedded via iframe.
 * This provides the full AI chat experience within the dashboard.
 * 
 * To start Streamlit:
 *   cd ai_agents && streamlit run streamlit_app.py
 */
const ChatWindow = ({ onClose, selectedRelease = DEFAULT_RELEASE }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [isBlocked, setIsBlocked] = useState(false);
  
  // Streamlit URL - handles both local dev and production (nginx proxy)
  const getStreamlitUrl = () => {
    if (process.env.REACT_APP_STREAMLIT_URL) {
      return process.env.REACT_APP_STREAMLIT_URL;
    }
    
    const hostname = window.location.hostname;
    const port = window.location.port;
    
    // Local development (React dev server on port 3000) - use direct URL
    if (port === '3000' || hostname === 'localhost' || hostname === '127.0.0.1') {
      return `http://${hostname}:8501`;
    }
    
    // Production (nginx on port 8080) - use proxy to avoid cross-origin issues
    return `${window.location.origin}/streamlit/`;
  };
  const STREAMLIT_URL = getStreamlitUrl();
  
  // Direct URL for "Open in New Tab"
  const getDirectStreamlitUrl = () => {
    const hostname = window.location.hostname;
    const port = window.location.port;
    
    // Local development - Streamlit runs without BASE_URL_PATH
    if (port === '3000' || hostname === 'localhost' || hostname === '127.0.0.1') {
      return `http://${hostname}:8501`;
    }
    
    // Production (VM) - Streamlit has BASE_URL_PATH=/streamlit
    return `http://${hostname}:8501/streamlit/`;
  };
  
  // Add release context to URL
  const streamlitUrl = `${STREAMLIT_URL}?release=${selectedRelease}&embed=true`;
  
  const handleIframeLoad = () => {
    setIsLoading(false);
    // Check if iframe content is accessible (might be blocked by CSP)
    try {
      const iframe = document.getElementById('streamlit-iframe');
      // If we can't access iframe content after load, it might be blocked
      if (iframe && iframe.contentWindow) {
        // Successfully loaded
        setHasError(false);
        setIsBlocked(false);
      }
    } catch (e) {
      // Cross-origin or blocked
      setIsBlocked(true);
    }
  };
  
  const handleIframeError = () => {
    setIsLoading(false);
    setHasError(true);
  };
  
  const handleRefresh = () => {
    setIsLoading(true);
    setHasError(false);
    setIsBlocked(false);
    // Force iframe reload by updating key
    const iframe = document.getElementById('streamlit-iframe');
    if (iframe) {
      iframe.src = streamlitUrl;
    }
  };
  
  const openInNewTab = () => {
    window.open(getDirectStreamlitUrl(), '_blank');
  };
  
  // Auto-detect blocked content after timeout
  useEffect(() => {
    const timer = setTimeout(() => {
      if (isLoading) {
        setIsLoading(false);
        setIsBlocked(true);
      }
    }, 8000); // 8 second timeout for slower connections
    return () => clearTimeout(timer);
  }, [isLoading]);

  return (
    <div className="chat-window-content">
      {/* Header */}
      <header className="cw-header">
        <div className="cw-header-left">
          <div className="cw-avatar">
            <Brain size={20} />
            <span className="cw-avatar-pulse"></span>
          </div>
          <div className="cw-header-info">
            <h3>AI Assistant</h3>
            <div className="cw-status">
              <span className={`cw-status-dot ${hasError ? 'coming-soon' : ''}`}></span>
              <span>{isLoading ? 'Connecting...' : hasError ? 'Not Available' : 'Online'}</span>
            </div>
          </div>
        </div>
        <div className="cw-header-actions">
          <button 
            className="cw-action-btn" 
            onClick={handleRefresh}
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
          <button 
            className="cw-action-btn" 
            onClick={openInNewTab}
            title="Open in new tab"
          >
            <ExternalLink size={16} />
          </button>
          {onClose && (
            <button className="cw-close-btn" onClick={onClose} aria-label="Close chat">
              <X size={18} />
            </button>
          )}
        </div>
      </header>

      {/* Streamlit Iframe Container */}
      <div className="cw-iframe-container">
        {isLoading && (
          <div className="cw-loading-overlay">
            <Loader2 size={32} className="spinning" />
            <p>Loading AI Assistant...</p>
            <span className="cw-loading-hint">
              Make sure Streamlit is running:<br />
              <code>cd ai_agents && streamlit run streamlit_app.py</code>
            </span>
          </div>
        )}
        
        {(hasError || isBlocked) && (
          <div className="cw-error-overlay">
            <div className="cw-error-content">
              <Brain size={48} />
              <h3>AI Assistant</h3>
              {isBlocked ? (
                <>
                  <p>Embedded view blocked by network policy.</p>
                  <p style={{ fontSize: '0.9em', color: '#666', marginTop: '8px' }}>
                    Corporate networks may block embedded content.
                  </p>
                </>
              ) : (
                <>
                  <p>The Streamlit server is not running.</p>
                  <div className="cw-error-instructions">
                    <p>Start it with:</p>
                    <code>cd ai_agents && streamlit run streamlit_app.py</code>
                  </div>
                </>
              )}
              <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
                <button className="cw-retry-btn" onClick={openInNewTab} style={{ background: '#4CAF50' }}>
                  <ExternalLink size={16} />
                  <span>Open in New Tab</span>
                </button>
                <button className="cw-retry-btn" onClick={handleRefresh}>
                  <RefreshCw size={16} />
                  <span>Retry</span>
                </button>
              </div>
            </div>
          </div>
        )}
        
        <iframe
          id="streamlit-iframe"
          src={streamlitUrl}
          title="AI Assistant"
          className="cw-streamlit-iframe"
          onLoad={handleIframeLoad}
          onError={handleIframeError}
          style={{ display: hasError ? 'none' : 'block' }}
        />
      </div>
    </div>
  );
};

export default ChatWindow;
