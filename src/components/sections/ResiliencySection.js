/**
 * ResiliencySection - NS Client Resiliency Dashboard
 * 
 * Currently disabled - shows Coming Soon placeholder.
 * Will be implemented with JIRA escalations data in future.
 */
import React from 'react';
import { Shield, Clock } from 'lucide-react';

const ResiliencySection = () => {
  return (
    <div className="resiliency-section">
      <div className="section-page-header">
        <div className="header-left">
          <h1><Shield size={24} /> NS Client Resiliency</h1>
          <p>Customer escalations trend and category analysis</p>
        </div>
      </div>

      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '100px 40px',
        textAlign: 'center',
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-color)'
      }}>
        <div style={{
          width: '80px',
          height: '80px',
          borderRadius: '50%',
          background: 'linear-gradient(135deg, var(--accent-purple) 0%, var(--accent-cyan) 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '24px'
        }}>
          <Clock size={40} style={{ color: 'white' }} />
        </div>
        
        <h2 style={{ 
          fontSize: '28px', 
          fontWeight: '700', 
          color: 'var(--text-primary)',
          margin: '0 0 12px 0'
        }}>
          Coming Soon
        </h2>
        
        <p style={{ 
          fontSize: '16px', 
          color: 'var(--text-muted)',
          maxWidth: '400px',
          lineHeight: '1.6'
        }}>
          NS Client Resiliency dashboard is under development. 
          This section will display customer escalation trends, 
          category analysis, and resolution metrics.
        </p>
        
        <div style={{
          marginTop: '32px',
          padding: '16px 24px',
          background: 'var(--bg-tertiary)',
          borderRadius: 'var(--radius-md)',
          fontSize: '13px',
          color: 'var(--text-secondary)'
        }}>
          <strong>Data Source:</strong> JIRA Escalations (jira_escalated label)
        </div>
      </div>
    </div>
  );
};

export default ResiliencySection;
