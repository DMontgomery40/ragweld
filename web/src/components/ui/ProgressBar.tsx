import React from 'react';

export interface ProgressBarProps {
  value: number;
  max?: number;
  label?: string;
  showPercentage?: boolean;
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info';
  size?: 'sm' | 'md' | 'lg';
  animated?: boolean;
  className?: string;
}

/**
 * ProgressBar - Accessible progress indicator with multiple variants
 *
 * Features:
 * - ARIA-compliant progress semantics
 * - Multiple visual variants (default, success, warning, error, info)
 * - Optional label and percentage display
 * - Smooth animations
 * - Size variants (sm, md, lg)
 *
 * Usage:
 * ```tsx
 * <ProgressBar
 *   value={65}
 *   max={100}
 *   label="Indexing documents..."
 *   variant="success"
 *   showPercentage
 * />
 * ```
 */
export function ProgressBar({
  value,
  max = 100,
  label,
  showPercentage = true,
  variant = 'default',
  size = 'md',
  animated = true,
  className = ''
}: ProgressBarProps) {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100);
  const isIndeterminate = value < 0 || isNaN(value);

  return (
    <div
      className={`progress-container progress-${size} ${className}`}
      role="group"
      aria-label={label || 'Progress indicator'}
    >
      {label && (
        <div className="progress-header">
          <span className="progress-label">{label}</span>
          {showPercentage && !isIndeterminate && (
            <span className="progress-percentage" aria-live="polite">
              {Math.round(percentage)}%
            </span>
          )}
        </div>
      )}
      <div
        className="progress-bar"
        role="progressbar"
        aria-valuenow={isIndeterminate ? undefined : value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label || 'Progress'}
      >
        <div
          className={`progress-fill progress-${variant} ${animated ? 'progress-animated' : ''} ${isIndeterminate ? 'progress-indeterminate' : ''}`}
          style={{ width: isIndeterminate ? '100%' : `${percentage}%` }}
        />
      </div>
      {!label && showPercentage && !isIndeterminate && (
        <span className="progress-percentage progress-standalone" aria-live="polite">
          {Math.round(percentage)}%
        </span>
      )}
    </div>
  );
}

export default ProgressBar;
