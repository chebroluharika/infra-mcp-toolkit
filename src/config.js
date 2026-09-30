/**
 * Frontend Configuration
 * ======================
 * 
 * IMPORTANT: Update DEFAULT_RELEASE when switching to a new release!
 * This MUST match CURRENT_RELEASE in docker-start.sh and backend/config.py
 * 
 * The frontend fetches releases from /api/releases at runtime, but this
 * fallback is used when the API is unavailable (e.g., during initial load).
 */

// ============================================================================
// DEFAULT RELEASE - UPDATE THIS WHEN SWITCHING RELEASES
// ============================================================================
export const DEFAULT_RELEASE = 'R139';
// ============================================================================

// API configuration
// Use relative URL by default for local dev and Docker
// For VM deployment: set REACT_APP_API_URL=http://10.136.126.85:8000
export const API_BASE_URL = process.env.REACT_APP_API_URL || '';
