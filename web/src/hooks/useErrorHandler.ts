import { useCallback } from 'react';
import { createAlertError, createHelpfulError, createInlineError } from '@web/utils/errorHelpers';
import type { ErrorHelperOptions } from '@web/types';

/**
 * Hook for creating helpful error messages
 */
export function useErrorHandler() {
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
    createHelpful,
    createInline,
    handleApiError,
  };
}
