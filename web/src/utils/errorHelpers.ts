import type { ErrorHelperOptions } from '@web/types';

/**
 * Create a helpful error message with context, troubleshooting, and links
 */
export function createHelpfulError(options: ErrorHelperOptions): string {
  const {
    title = 'An error occurred',
    message = '',
    causes = [],
    fixes = [],
    links = [],
    context = ''
  } = options;

  let html = `
    <div style="padding: 16px; background: var(--bg-elev2); border-left: 3px solid var(--err); border-radius: 4px;">
      <div style="font-weight: 600; color: var(--err); margin-bottom: 8px;">
        ❌ ${escapeHtml(title)}
      </div>
  `;

  if (message) {
    html += `
      <div style="font-size: 11px; color: var(--fg-muted); font-family: 'SF Mono', monospace; margin-bottom: 12px; padding: 8px; background: var(--code-bg); border-radius: 4px;">
        ${escapeHtml(message)}
      </div>
    `;
  }

  if (context) {
    html += `
      <div style="font-size: 12px; color: var(--fg); margin-bottom: 12px;">
        ${escapeHtml(context)}
      </div>
    `;
  }

  if (causes.length > 0) {
    html += `
      <div style="font-size: 12px; color: var(--fg); margin-bottom: 12px; line-height: 1.6;">
        <strong>Common causes:</strong><br>
        ${causes.map(cause => `• ${escapeHtml(cause)}`).join('<br>')}
      </div>
    `;
  }

  if (fixes.length > 0) {
    html += `
      <div style="font-size: 12px; color: var(--fg); margin-bottom: 12px; line-height: 1.6;">
        <strong>Quick fixes:</strong><br>
        ${fixes.map((fix, i) => `${i + 1}. ${escapeHtml(fix)}`).join('<br>')}
      </div>
    `;
  }

  if (links.length > 0) {
    html += `
      <div style="font-size: 11px; margin-top: 12px;">
        <strong>Learn more:</strong><br>
        <div style="margin-top: 6px; display: flex; flex-wrap: wrap; gap: 8px;">
          ${links.map(([label, url]) =>
            `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" style="color: var(--link); text-decoration: none; padding: 4px 8px; background: var(--bg-elev1); border-radius: 4px; border: 1px solid var(--line);">${escapeHtml(label)}</a>`
          ).join('')}
        </div>
      </div>
    `;
  }

  html += `</div>`;
  return html;
}

/**
 * Create a compact inline error message (for status lines)
 */
export function createInlineError(title: string, options: Partial<ErrorHelperOptions> = {}): string {
  const { links = [] } = options;

  if (links.length > 0) {
    const linkHtml = links.map(([label, url]) =>
      `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" style="color: var(--link); text-decoration: underline; margin-left: 8px;">${escapeHtml(label)}</a>`
    ).join('');
    return `✗ ${escapeHtml(title)}${linkHtml}`;
  }

  return `✗ ${escapeHtml(title)}`;
}

/**
 * Create an alert-style error message with help
 */
export function createAlertError(title: string, options: Partial<ErrorHelperOptions> = {}): string {
  const { message = '', causes = [], fixes = [], links = [] } = options;

  let text = `❌ ${title}\n\n`;

  if (message) {
    text += `Error: ${message}\n\n`;
  }

  if (causes.length > 0) {
    text += `Common causes:\n${causes.map(c => `• ${c}`).join('\n')}\n\n`;
  }

  if (fixes.length > 0) {
    text += `Quick fixes:\n${fixes.map((f, i) => `${i + 1}. ${f}`).join('\n')}\n\n`;
  }

  if (links.length > 0) {
    text += `Learn more:\n${links.map(([label, url]) => `• ${label}: ${url}`).join('\n')}`;
  }

  return text;
}

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Expose on window for legacy JS modules (docker.js, chat.js, reranker.js, etc.)
// This replaces /modules/error-helpers.js
if (typeof window !== 'undefined') {
  (window as any).ErrorHelpers = {
    createHelpfulError,
    createInlineError,
    createAlertError,
    escapeHtml
  };
}
