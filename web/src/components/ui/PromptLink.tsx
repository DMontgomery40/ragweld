/**
 * PromptLink Component
 *
 * Cross-tab navigation component that links to the System Prompts subtab
 * in the Eval Analysis tab (/eval).
 *
 * Uses CSS classes from inline-gui-styles.css for styling with proper
 * hover/focus states and micro-interactions.
 *
 * Usage:
 *   <PromptLink promptKey="main_rag_chat">Edit System Prompt</PromptLink>
 *   <PromptLink>View All Prompts</PromptLink>
 */

import { useNavigate } from 'react-router-dom';

interface PromptLinkProps {
  /** Optional prompt key to scroll to in the System Prompts subtab */
  promptKey?: string;
  /** Button content */
  children: React.ReactNode;
  /** Optional additional className */
  className?: string;
}

export function PromptLink({ promptKey, children, className = '' }: PromptLinkProps) {
  const navigate = useNavigate();

  const handleClick = () => {
    // Navigate to Eval Analysis tab's System Prompts subtab
    // The ?subtab=prompts param tells EvalAnalysisTab to switch to prompts subtab
    // The ?prompt=KEY param tells SystemPromptsSubtab to highlight that prompt
    const params = new URLSearchParams();
    params.set('subtab', 'prompts');
    if (promptKey) {
      params.set('prompt', promptKey);
    }
    navigate(`/eval?${params.toString()}`);
  };

  // Generate aria-label from children if it's a string
  const ariaLabel = typeof children === 'string'
    ? `Edit ${children} prompt`
    : 'Edit prompt';

  return (
    <button
      onClick={handleClick}
      className={`prompt-link ${className}`.trim()}
      aria-label={ariaLabel}
    >
      <span className="prompt-link-icon" aria-hidden="true">✏️</span>
      {children}
    </button>
  );
}

export default PromptLink;
