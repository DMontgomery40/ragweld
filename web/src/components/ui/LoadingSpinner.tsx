import React from 'react';

export interface LoadingSpinnerProps {
  size?: number | 'sm' | 'md' | 'lg' | 'xl';
  color?: 'accent' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'white';
  variant?: 'circular' | 'dots' | 'bars';
  label?: string;
  center?: boolean;
  className?: string;
}

/**
 * LoadingSpinner - Animated loading indicator
 *
 * Features:
 * - ARIA-compliant with live region
 * - Multiple variants (circular, dots, bars)
 * - Color variants matching theme
 * - Size presets or custom pixel size
 * - Optional centering
 * - Accessible labels
 *
 * Usage:
 * ```tsx
 * <LoadingSpinner size="md" color="accent" />
 * <LoadingSpinner size={32} color="primary" label="Loading data..." />
 * <LoadingSpinner variant="dots" center />
 * ```
 */
export function LoadingSpinner({
  size = 'md',
  color = 'accent',
  variant = 'circular',
  label,
  center = false,
  className = ''
}: LoadingSpinnerProps) {
  const sizeMap = {
    sm: 16,
    md: 24,
    lg: 32,
    xl: 48
  };

  const pixelSize = typeof size === 'number' ? size : sizeMap[size];

  const spinnerStyle: React.CSSProperties = {
    width: `${pixelSize}px`,
    height: `${pixelSize}px`
  };

  const renderSpinner = () => {
    switch (variant) {
      case 'dots':
        return (
          <div className={`loading-spinner-dots spinner-${color}`} style={spinnerStyle}>
            <div className="spinner-dot" />
            <div className="spinner-dot" />
            <div className="spinner-dot" />
          </div>
        );
      case 'bars':
        return (
          <div className={`loading-spinner-bars spinner-${color}`} style={spinnerStyle}>
            <div className="spinner-bar" />
            <div className="spinner-bar" />
            <div className="spinner-bar" />
          </div>
        );
      case 'circular':
      default:
        return (
          <div
            className={`loading-spinner spinner-${color}`}
            style={spinnerStyle}
          />
        );
    }
  };

  const spinner = (
    <div
      className={`loading-spinner-container ${center ? 'loading-spinner-center' : ''} ${className}`}
      role="status"
      aria-label={label || 'Loading'}
      aria-live="polite"
      aria-busy="true"
    >
      {renderSpinner()}
      {label && <span className="loading-spinner-label">{label}</span>}
      <span className="sr-only">{label || 'Loading...'}</span>
    </div>
  );

  return spinner;
}

export default LoadingSpinner;
