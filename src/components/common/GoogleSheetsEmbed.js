/**
 * GoogleSheetsEmbed - Reusable Google Sheets iframe component
 * 
 * Used by:
 * - CustomerEscalationsSection
 * - ManualExecutionSection  
 * - WeeklyStatusSection
 * 
 * Features:
 * - Loading skeleton while sheet loads
 * - Refresh capability
 * - Open in new tab
 * - Download as Excel
 * - Copy share link
 */
import React, { useState } from 'react';
import { 
  FileSpreadsheet, 
  ExternalLink, 
  RefreshCw, 
  Share2, 
  Download,
  Loader2
} from 'lucide-react';

const GoogleSheetsEmbed = ({ 
  spreadsheetId,
  sheetGid = '0',
  title,
  description,
  height = '80vh',
  showActions = true,
  hideExportButtons = false 
}) => {
  const [iframeKey, setIframeKey] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  // URLs
  const sheetUrl = `https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit?gid=${sheetGid}#gid=${sheetGid}`;
  const embedUrl = `https://docs.google.com/spreadsheets/d/${spreadsheetId}/preview?gid=${sheetGid}&rm=minimal&chrome=true`;

  const handleRefresh = () => {
    setIsLoading(true);
    setIframeKey(prev => prev + 1);
  };

  const handleIframeLoad = () => {
    setIsLoading(false);
  };

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(sheetUrl);
      alert('Link copied to clipboard!');
    } catch (err) {
      alert('Failed to copy link');
    }
  };

  const handleDownload = () => {
    const downloadUrl = `https://docs.google.com/spreadsheets/d/${spreadsheetId}/export?format=xlsx&gid=${sheetGid}`;
    window.open(downloadUrl, '_blank');
  };

  const handleOpenInSheets = () => {
    window.open(sheetUrl, '_blank');
  };

  return (
    <div className="google-sheets-embed">
      {/* Header */}
      <div className="section-page-header">
        <div className="header-left">
          <h1>
            <FileSpreadsheet size={24} /> {title}
          </h1>
          {description && <p>{description}</p>}
        </div>
        
        {showActions && (
          <div className="header-actions">
            <button 
              className="action-btn secondary"
              onClick={handleRefresh}
              title="Refresh"
              disabled={isLoading}
            >
              <RefreshCw size={16} className={isLoading ? 'spin' : ''} />
              {isLoading ? 'Loading...' : 'Refresh'}
            </button>
            <button 
              className="action-btn secondary"
              onClick={handleShare}
              title="Copy link"
            >
              <Share2 size={16} />
              Share
            </button>
            {!hideExportButtons && (
              <>
                <button 
                  className="action-btn secondary"
                  onClick={handleDownload}
                  title="Download Excel"
                >
                  <Download size={16} />
                  Export
                </button>
                <button 
                  className="action-btn primary"
                  onClick={handleOpenInSheets}
                  title="Open in Google Sheets"
                >
                  <ExternalLink size={16} />
                  Open in Sheets
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Iframe Container with Loading State */}
      <div className="sheets-iframe-container" style={{ height, position: 'relative' }}>
        {/* Loading Overlay */}
        {isLoading && (
          <div className="sheets-loading-overlay">
            <div className="sheets-loading-content">
              <Loader2 size={40} className="spin" />
              <p>Loading Google Sheet...</p>
              <span className="loading-hint">This may take a few seconds for large spreadsheets</span>
            </div>
            {/* Skeleton Grid */}
            <div className="sheets-skeleton">
              <div className="skeleton-header">
                <div className="skeleton-cell header" style={{ width: '15%' }}></div>
                <div className="skeleton-cell header" style={{ width: '25%' }}></div>
                <div className="skeleton-cell header" style={{ width: '20%' }}></div>
                <div className="skeleton-cell header" style={{ width: '15%' }}></div>
                <div className="skeleton-cell header" style={{ width: '25%' }}></div>
              </div>
              {[...Array(8)].map((_, i) => (
                <div key={i} className="skeleton-row">
                  <div className="skeleton-cell" style={{ width: '15%' }}></div>
                  <div className="skeleton-cell" style={{ width: '25%' }}></div>
                  <div className="skeleton-cell" style={{ width: '20%' }}></div>
                  <div className="skeleton-cell" style={{ width: '15%' }}></div>
                  <div className="skeleton-cell" style={{ width: '25%' }}></div>
                </div>
              ))}
            </div>
          </div>
        )}
        
        <iframe
          key={iframeKey}
          src={embedUrl}
          title={title}
          onLoad={handleIframeLoad}
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            borderRadius: '8px',
            opacity: isLoading ? 0 : 1,
            transition: 'opacity 0.3s ease',
          }}
          allowFullScreen
        />
      </div>
    </div>
  );
};

export default GoogleSheetsEmbed;
