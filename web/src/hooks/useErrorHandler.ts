import { useCallback } from 'react';
import { createAlertError, createHelpfulError, createInlineError } from '@web/utils/errorHelpers';
import type { ErrorHelperOptions } from '@web/types';

/**
 * Hook for creating helpful error messages
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that provides error handling utilities for displaying and creating user-friendly error messages.
 *   Exports two memoized callback functions: showAlert (displays formatted error via browser alert) and createHelpful (creates structured error objects).
 *   showAlert takes a title string and optional ErrorHelperOptions object, calls createAlertError helper, and displays result via native alert().
 *   createHelpful takes ErrorHelperOptions and returns result from createHelpfulError helper for programmatic error object creation.
 *   No side effects beyond alert() display; relies on external helper functions (createAlertError, createHelpfulError) for actual error formatting logic.
 *
 * why: |
 *   Wraps error formatting helpers in a custom hook to provide consistent error handling across React components with memoized callbacks.
 *   useCallback prevents unnecessary re-renders of child components that depend on these error handlers as props or dependencies.
 *   Centralizes error UI patterns (alert-based display vs structured error objects) in one reusable hook rather than scattered throughout components.
 *
 * guardrails:
 *   - DO NOT call alert() directly in components; always use this hook's showAlert method to ensure consistent error formatting and messaging
 *   - ALWAYS verify that createAlertError and createHelpfulError helper functions are properly exported and tested before using this hook
 *   - NOTE: Browser alert() is blocking and poor UX; consider refactoring showAlert to use a toast/modal component instead of native alert()
 *   - ASK USER: Before modifying ErrorHelperOptions interface, confirm all consuming components and their error handling requirements to avoid breaking changes
 * ---/agentspec
 */
export function useErrorHandler() {
  const showAlert = useCallback((title: string, options: Partial<ErrorHelperOptions> = {}) => {
    const message = createAlertError(title, options);
    alert(message);
  }, []);

  const createHelpful = useCallback((options: ErrorHelperOptions) => {
    return createHelpfulError(options);
  }, []);

  const createInline = useCallback((title: string, options: Partial<ErrorHelperOptions> = {}) => {
    return createInlineError(title, options);
  }, []);

  const handleApiError = useCallback((error: unknown, context: string) => {
    const message = error instanceof Error ? error.message : 'Unknown error';

    return createAlertError(`${context} failed`, {
      message,
      causes: [
        'Backend API server is not running or not responding',
        'Network connectivity issue or timeout',
        'Invalid or missing data in request',
        'Authentication or authorization failure'
      ],
      fixes: [
        'Verify backend service is running in Infrastructure tab',
        'Check browser console for detailed error messages',
        'Verify network connectivity and firewall rules',
        'Refresh the page and try again'
      ],
      links: [
        ['Fetch API Documentation', 'https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API']
      ]
    });
  }, []);

  return {
    showAlert,
    createHelpful,
    createInline,
    handleApiError,
  };
}
