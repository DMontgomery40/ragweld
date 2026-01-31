// AGRO - Progress Bar with Shimmer Effect
// Matches /gui micro-interactions.css progress bar polish



export interface ProgressBarWithShimmerProps {
  progress: number; // 0-100
  height?: string;
  showShimmer?: boolean;
  gradient?: string;
}

export function ProgressBarWithShimmer({
  progress,
  height = '8px',
  showShimmer = true,
  gradient = 'linear-gradient(90deg, var(--warn) 0%, var(--accent) 100%)',
}: ProgressBarWithShimmerProps) {
  return (
    <div
      className="progress-bar"
      style={{
        height,
        background: 'var(--bg-elev1)',
        borderRadius: '2px',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div
        className="progress-fill"
        style={{
          height: '100%',
          background: gradient,
          borderRadius: '2px',
          width: `${progress}%`,
          transition: 'width 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
          position: 'relative',
        }}
      >
        {showShimmer && progress > 0 && progress < 100 && (
          <div
            className="progress-shine"
            style={{
              position: 'absolute',
              top: 0,
              left: '-100%',
              height: '100%',
              width: '30%',
              background: 'linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent)',
              animation: 'shine 2s infinite',
            }}
          />
        )}
      </div>

      <style>{`
        @keyframes shine {
          0% {
            left: -100%;
          }
          100% {
            left: 100%;
          }
        }
      `}</style>
    </div>
  );
}

