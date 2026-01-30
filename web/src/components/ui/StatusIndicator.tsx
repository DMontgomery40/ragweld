import React from 'react';

export interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'loading' | 'success' | 'warning' | 'error' | 'idle';
  label?: string;
  pulse?: boolean;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  className?: string;
  ariaLabel?: string;
}

/**
 * StatusIndicator - Visual status indicator with optional label
 *
 * Features:
 * - ARIA-compliant with live region updates
 * - Multiple status types (online, offline, loading, success, warning, error, idle)
 * - Optional pulse animation
 * - Size variants (sm, md, lg)
 * - Accessible labels
 *
 * Usage:
 * ```tsx
 * <StatusIndicator
 *   status="online"
 *   label="Docker Service"
 *   pulse
 * />
 * ```
 */
export function StatusIndicator({
  status,
  label,
  pulse = true,
  size = 'md',
  showLabel = true,
  className = '',
  ariaLabel
}: StatusIndicatorProps) {
  const statusLabels = {
    online: 'Online',
    offline: 'Offline',
    loading: 'Loading',
    success: 'Success',
    warning: 'Warning',
    error: 'Error',
    idle: 'Idle'
  };

  const displayLabel = label || statusLabels[status];
  const effectiveAriaLabel = ariaLabel || `Status: ${displayLabel}`;

  return (
    <div
      className={`status-indicator status-indicator-${size} ${className}`}
      role="status"
      aria-label={effectiveAriaLabel}
      aria-live="polite"
    >
      <div
        className={`status-dot status-${status} ${pulse ? 'status-pulse' : ''}`}
        aria-hidden="true"
      />
      {showLabel && label && (
        <span className="status-label">{label}</span>
      )}
    </div>
  );
}

export default StatusIndicator;
