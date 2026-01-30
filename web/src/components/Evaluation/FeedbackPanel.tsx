import React, { useState } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { useUIHelpers } from '@/hooks/useUIHelpers';

interface FeedbackPanelProps {
  className?: string;
}

export const FeedbackPanel: React.FC<FeedbackPanelProps> = ({ className = '' }) => {
  const [rating, setRating] = useState<number>(0);
  const [hoverRating, setHoverRating] = useState<number>(0);
  const [comment, setComment] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [lastSubmissionTime, setLastSubmissionTime] = useState<Date | null>(null);

  const { api } = useAPI();
  const { showToast } = useUIHelpers();

  const handleSubmitFeedback = async () => {
    if (rating === 0) {
      alert('Please select a rating (1-5 stars)');
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(api('/api/feedback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rating,
          comment: comment.trim(),
          timestamp: new Date().toISOString(),
          context: 'evaluation'
        })
      });

      if (!response.ok) {
        throw new Error(`Feedback submission failed: ${response.status}`);
      }

      const data = await response.json();

      if (data.ok || data.success) {
        showToast('Feedback submitted successfully', 'success');
        setLastSubmissionTime(new Date());
        // Clear form
        setRating(0);
        setComment('');
      } else {
        throw new Error(data.error || 'Failed to submit feedback');
      }
    } catch (error) {
      console.error('Failed to submit feedback:', error);
      showToast(`Failed to submit feedback: ${error}`, 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const displayRating = hoverRating || rating;

  const getRatingLabel = (r: number) => {
    switch (r) {
      case 1: return 'Poor';
      case 2: return 'Fair';
      case 3: return 'Good';
      case 4: return 'Very Good';
      case 5: return 'Excellent';
      default: return 'Rate your experience';
    }
  };

  const getRatingColor = (r: number) => {
    if (r <= 2) return 'var(--err)';
    if (r === 3) return 'var(--warn)';
    return 'var(--accent)';
  };

  return (
    <div className={`feedback-panel ${className}`}>
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '20px',
        maxWidth: '600px',
        margin: '0 auto'
      }}>
        <h3 style={{
          fontSize: '16px',
          fontWeight: 600,
          color: 'var(--fg)',
          marginBottom: '8px',
          textAlign: 'center'
        }}>
          Help Us Improve
        </h3>

        <p style={{
          fontSize: '13px',
          color: 'var(--fg-muted)',
          marginBottom: '24px',
          textAlign: 'center'
        }}>
          Your feedback helps us improve the evaluation system
        </p>

        {/* Star Rating */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          marginBottom: '24px'
        }}>
          <div style={{
            fontSize: '14px',
            fontWeight: 600,
            color: getRatingColor(displayRating),
            marginBottom: '12px',
            minHeight: '21px'
          }}>
            {getRatingLabel(displayRating)}
          </div>

          <div style={{
            display: 'flex',
            gap: '8px'
          }}>
            {[1, 2, 3, 4, 5].map((star) => {
              const isFilled = star <= displayRating;
              return (
                <button
                  key={star}
                  onClick={() => setRating(star)}
                  onMouseEnter={() => setHoverRating(star)}
                  onMouseLeave={() => setHoverRating(0)}
                  disabled={isSubmitting}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    cursor: isSubmitting ? 'not-allowed' : 'pointer',
                    padding: '4px',
                    fontSize: '32px',
                    color: isFilled ? getRatingColor(displayRating) : 'var(--line)',
                    transition: 'all 0.2s ease',
                    transform: hoverRating === star ? 'scale(1.1)' : 'scale(1)',
                    opacity: isSubmitting ? 0.5 : 1
                  }}
                  aria-label={`${star} star${star !== 1 ? 's' : ''}`}
                >
                  {isFilled ? '★' : '☆'}
                </button>
              );
            })}
          </div>
        </div>

        {/* Comment Field */}
        <div style={{ marginBottom: '20px' }}>
          <label htmlFor="feedback-comment" style={{
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--fg)',
            display: 'block',
            marginBottom: '8px'
          }}>
            Additional Comments (Optional)
          </label>
          <textarea
            id="feedback-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={isSubmitting}
            placeholder="Tell us about your experience with the evaluation system..."
            style={{
              width: '100%',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '6px',
              padding: '12px',
              fontSize: '13px',
              color: 'var(--fg)',
              fontFamily: 'inherit',
              resize: 'vertical',
              minHeight: '100px',
              opacity: isSubmitting ? 0.5 : 1
            }}
          />
          <div style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            marginTop: '6px',
            textAlign: 'right'
          }}>
            {comment.length} / 1000 characters
          </div>
        </div>

        {/* Submit Button */}
        <button
          onClick={handleSubmitFeedback}
          disabled={isSubmitting || rating === 0}
          style={{
            width: '100%',
            background: isSubmitting || rating === 0 ? 'var(--bg-elev2)' : 'var(--accent)',
            color: isSubmitting || rating === 0 ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            padding: '12px 24px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: isSubmitting || rating === 0 ? 'not-allowed' : 'pointer',
            opacity: isSubmitting || rating === 0 ? 0.7 : 1,
            transition: 'all 0.2s ease'
          }}
        >
          {isSubmitting ? 'Submitting...' : 'Submit Feedback'}
        </button>

        {/* Last Submission Info */}
        {lastSubmissionTime && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            background: 'color-mix(in oklch, var(--ok) 8%, var(--bg))',
            border: '1px solid var(--ok)',
            borderRadius: '6px',
            fontSize: '12px',
            color: 'var(--ok)',
            textAlign: 'center'
          }}>
            ✓ Thank you! Your feedback was submitted at{' '}
            {lastSubmissionTime.toLocaleTimeString()}
          </div>
        )}

        {/* Info Section */}
        <div style={{
          marginTop: '24px',
          padding: '16px',
          background: 'var(--bg-elev2)',
          borderRadius: '6px',
          fontSize: '12px',
          color: 'var(--fg-muted)',
          lineHeight: '1.6'
        }}>
          <div style={{ fontWeight: 600, marginBottom: '8px', color: 'var(--fg)' }}>
            What we use feedback for:
          </div>
          <ul style={{
            margin: '0',
            paddingLeft: '20px'
          }}>
            <li>Improving evaluation accuracy and performance</li>
            <li>Prioritizing feature development</li>
            <li>Identifying and fixing bugs</li>
            <li>Understanding user workflows and pain points</li>
          </ul>
        </div>
      </div>
    </div>
  );
};
