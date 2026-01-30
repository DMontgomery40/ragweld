import React from 'react';

export interface SkeletonLoaderProps {
  width?: string | number;
  height?: string | number;
  variant?: 'text' | 'circular' | 'rectangular' | 'rounded';
  count?: number;
  className?: string;
  animate?: boolean;
}

/**
 * SkeletonLoader - Loading placeholder with shimmer effect
 *
 * Features:
 * - ARIA-compliant loading states
 * - Multiple shape variants (text, circular, rectangular, rounded)
 * - Customizable dimensions
 * - Shimmer animation
 * - Support for multiple instances
 *
 * Usage:
 * ```tsx
 * <SkeletonLoader variant="text" width="100%" height="20px" count={3} />
 * <SkeletonLoader variant="circular" width={48} height={48} />
 * <SkeletonLoader variant="rectangular" width="100%" height="200px" />
 * ```
 */
export function SkeletonLoader({
  width = '100%',
  height = '20px',
  variant = 'text',
  count = 1,
  className = '',
  animate = true
}: SkeletonLoaderProps) {
  const normalizedWidth = typeof width === 'number' ? `${width}px` : width;
  const normalizedHeight = typeof height === 'number' ? `${height}px` : height;

  const skeletonStyle: React.CSSProperties = {
    width: normalizedWidth,
    height: normalizedHeight
  };

  const skeletons = Array.from({ length: count }, (_, index) => (
    <div
      key={index}
      className={`skeleton skeleton-${variant} ${animate ? 'skeleton-animate' : ''} ${className}`}
      style={skeletonStyle}
      role="status"
      aria-label="Loading..."
      aria-busy="true"
    >
      <span className="sr-only">Loading...</span>
    </div>
  ));

  return count > 1 ? (
    <div className="skeleton-group" role="group" aria-label="Loading content">
      {skeletons}
    </div>
  ) : (
    <>{skeletons}</>
  );
}

/**
 * SkeletonCard - Predefined skeleton for card layouts
 */
export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`skeleton-card ${className}`} role="status" aria-label="Loading card">
      <SkeletonLoader variant="rectangular" width="100%" height="120px" />
      <div className="skeleton-card-content">
        <SkeletonLoader variant="text" width="60%" height="24px" />
        <SkeletonLoader variant="text" width="100%" height="16px" count={2} />
        <SkeletonLoader variant="text" width="40%" height="16px" />
      </div>
    </div>
  );
}

/**
 * SkeletonList - Predefined skeleton for list items
 */
export function SkeletonList({ items = 5, className = '' }: { items?: number; className?: string }) {
  return (
    <div className={`skeleton-list ${className}`} role="status" aria-label="Loading list">
      {Array.from({ length: items }, (_, index) => (
        <div key={index} className="skeleton-list-item">
          <SkeletonLoader variant="circular" width={40} height={40} />
          <div className="skeleton-list-content">
            <SkeletonLoader variant="text" width="80%" height="16px" />
            <SkeletonLoader variant="text" width="60%" height="14px" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default SkeletonLoader;
