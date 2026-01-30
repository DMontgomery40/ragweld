/**
 * AGRO UX Feedback Module
 * Version: 1.0.0
 * Agent: Senior UI/UX Polish Specialist
 *
 * Provides instant visual feedback for user interactions:
 * - Ripple effects on clicks
 * - Progress feedback management
 * - Form validation visual states
 * - Loading state orchestration
 *
 * Philosophy: Users should FEEL that something happened
 * Performance: < 50ms latency for all feedback
 * Accessibility: Respects prefers-reduced-motion
 */

(function () {
    'use strict';

    // Check for reduced motion preference
    /**
     * ---agentspec
     * what: |
     *   Detects user's reduced-motion preference via matchMedia API. Returns boolean.
     *
     * why: |
     *   Respects accessibility settings before applying animations.
     *
     * guardrails:
     *   - DO NOT animate if prefersReducedMotion() returns true
     *   - NOTE: matchMedia requires DOM; call only in browser context
     * ---/agentspec
     */
    const prefersReducedMotion = () => {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    };

    // ============================================
    // RIPPLE EFFECT - CLICK FEEDBACK
    // ============================================

    /**
     * Creates a ripple effect at click position
     * @param {HTMLElement} element - Target element
     * @param {MouseEvent} event - Click event
     */
    /**
     * ---agentspec
     * what: |
     *   Creates a ripple effect at click position on element. Skips if user prefers reduced motion.
     *
     * why: |
     *   Respects accessibility preferences while providing visual feedback.
     *
     * guardrails:
     *   - DO NOT create ripples if prefersReducedMotion() returns true; violates a11y
     *   - NOTE: Requires getBoundingClientRect() for accurate coordinate mapping
     * ---/agentspec
     */
    function createRipple(element, event) {
        // Skip if reduced motion is preferred
        if (prefersReducedMotion()) return;

        // Get click position relative to element
        const rect = element.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        // Create ripple element
        const ripple = document.createElement('span');
        ripple.classList.add('ripple');
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';

        // Ensure parent has position context
        const position = window.getComputedStyle(element).position;
        if (position === 'static') {
            element.style.position = 'relative';
        }

        // Add ripple to element
        element.appendChild(ripple);

        // Remove ripple after animation completes
        ripple.addEventListener('animationend', () => {
            ripple.remove();
        });

        // Fallback: remove after 1s if animationend doesn't fire
        setTimeout(() => {
            if (ripple.parentNode) {
                ripple.remove();
            }
        }, 1000);
    }

    /**
     * Attach ripple effect to all clickable elements
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes ripple effect event listeners on buttons and button-like elements. Targets 4 selector groups; excludes .no-ripple.
     *
     * why: |
     *   Centralized selector logic prevents duplication across ripple handlers.
     *
     * guardrails:
     *   - DO NOT attach listeners multiple times; call once on DOM ready
     *   - NOTE: .no-ripple opt-out must be present in HTML before init
     * ---/agentspec
     */
    function initRippleEffects() {
        // Target selectors
        const selectors = [
            'button:not(.no-ripple)',
            'a[role="button"]:not(.no-ripple)',
            '[role="button"]:not(.no-ripple)',
            '.ripple-enabled'
        ];

        // Add click listeners
        document.addEventListener('click', (e) => {
            const target = e.target.closest(selectors.join(', '));
            if (target && !target.disabled) {
                createRipple(target, e);
            }
        }, { passive: true });

        console.log('[UX Feedback] Ripple effects initialized');
    }

    // ============================================
    // PROGRESS FEEDBACK - LOADING STATES
    // ============================================

    /**
     * Progress Manager
     * Handles loading states and progress indication
     */
    const ProgressManager = {
        activeProgressBars: new Map(),

        /**
         * Show a progress bar
         * @param {string} id - Unique identifier
         * @param {Object} options - Configuration
         */
        show(id, options = {}) {
            const {
                container = document.body,
                initialPercent = 0,
                message = 'Loading...',
                eta = null
            } = options;

            // Check if already exists
            if (this.activeProgressBars.has(id)) {
                return this.update(id, { percent: initialPercent, message, eta });
            }

            // Create progress bar wrapper
            const wrapper = document.createElement('div');
            wrapper.className = 'loading-state';
            wrapper.setAttribute('data-progress-id', id);
            wrapper.innerHTML = `
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${initialPercent}%"></div>
                    <div class="progress-shine"></div>
                </div>
                <p class="loading-text">${message}</p>
                ${eta ? `<p class="loading-eta">~${eta} remaining</p>` : ''}
            `;

            // Add to container
            const targetContainer = typeof container === 'string'
                ? document.querySelector(container)
                : container;

            if (targetContainer) {
                targetContainer.appendChild(wrapper);
                this.activeProgressBars.set(id, wrapper);
            }

            return wrapper;
        },

        /**
         * Update progress bar
         * @param {string} id - Progress bar identifier
         * @param {Object} updates - Updates to apply
         */
        update(id, updates = {}) {
            const wrapper = this.activeProgressBars.get(id);
            if (!wrapper) return;

            const { percent, message, eta } = updates;

            if (percent !== undefined) {
                const fill = wrapper.querySelector('.progress-fill');
                if (fill) {
                    fill.style.width = percent + '%';
                }
            }

            if (message !== undefined) {
                const textEl = wrapper.querySelector('.loading-text');
                if (textEl) {
                    textEl.textContent = message;
                }
            }

            if (eta !== undefined) {
                let etaEl = wrapper.querySelector('.loading-eta');
                if (!etaEl && eta) {
                    etaEl = document.createElement('p');
                    etaEl.className = 'loading-eta';
                    wrapper.appendChild(etaEl);
                }
                if (etaEl) {
                    etaEl.textContent = eta ? `~${eta} remaining` : '';
                }
            }
        },

        /**
         * Hide and remove progress bar
         * @param {string} id - Progress bar identifier
         */
        hide(id) {
            const wrapper = this.activeProgressBars.get(id);
            if (wrapper) {
                // Fade out before removing
                wrapper.style.opacity = '0';
                wrapper.style.transition = 'opacity 0.3s ease-out';

                setTimeout(() => {
                    wrapper.remove();
                    this.activeProgressBars.delete(id);
                }, 300);
            }
        },

        /**
         * Show a simple spinner
         * @param {HTMLElement|string} container - Container element or selector
         */
        showSpinner(container) {
            const targetContainer = typeof container === 'string'
                ? document.querySelector(container)
                : container;

            if (!targetContainer) return null;

            const spinner = document.createElement('div');
            spinner.className = 'loading-spinner';
            targetContainer.appendChild(spinner);

            return spinner;
        },

        /**
         * Remove spinner
         * @param {HTMLElement} spinner - Spinner element to remove
         */
        hideSpinner(spinner) {
            if (spinner && spinner.parentNode) {
                spinner.remove();
            }
        }
    };

    // ============================================
    // FORM VALIDATION - VISUAL FEEDBACK
    // ============================================

    /**
     * Form Validation Feedback
     * Adds visual states to form inputs
     */
    const FormFeedback = {
        /**
         * Mark input as valid
         * @param {HTMLElement} input - Input element
         * @param {string} message - Optional success message
         */
        markValid(input, message = '') {
            if (!input) return;

            // Remove invalid state
            input.classList.remove('invalid');

            // Add valid state
            input.classList.add('valid');

            // Hide error messages
            this.hideError(input);

            // Show success message if provided
            if (message) {
                this.showSuccess(input, message);
            }
        },

        /**
         * Mark input as invalid
         * @param {HTMLElement} input - Input element
         * @param {string} message - Error message
         */
        markInvalid(input, message = 'Invalid input') {
            if (!input) return;

            // Remove valid state
            input.classList.remove('valid');

            // Add invalid state
            input.classList.add('invalid');

            // Show error message
            this.showError(input, message);

            // Hide success message
            this.hideSuccess(input);
        },

        /**
         * Clear validation state
         * @param {HTMLElement} input - Input element
         */
        clearValidation(input) {
            if (!input) return;

            input.classList.remove('valid', 'invalid');
            this.hideError(input);
            this.hideSuccess(input);
        },

        /**
         * Show error message
         * @param {HTMLElement} input - Input element
         * @param {string} message - Error message
         */
        showError(input, message) {
            let errorEl = input.nextElementSibling;

            // Check if it's already an error message element
            if (!errorEl || !errorEl.classList.contains('error-message')) {
                // Create new error element
                errorEl = document.createElement('p');
                errorEl.className = 'error-message';
                input.parentNode.insertBefore(errorEl, input.nextSibling);
            }

            errorEl.textContent = message;
            errorEl.classList.add('show');
        },

        /**
         * Hide error message
         * @param {HTMLElement} input - Input element
         */
        hideError(input) {
            const errorEl = input.nextElementSibling;
            if (errorEl && errorEl.classList.contains('error-message')) {
                errorEl.classList.remove('show');
            }
        },

        /**
         * Show success message
         * @param {HTMLElement} input - Input element
         * @param {string} message - Success message
         */
        showSuccess(input, message) {
            let successEl = input.nextElementSibling;

            // Look for existing success message or create new
            if (!successEl || !successEl.classList.contains('success-message')) {
                successEl = document.createElement('p');
                successEl.className = 'success-message';
                input.parentNode.insertBefore(successEl, input.nextSibling);
            }

            successEl.textContent = message;
            successEl.classList.add('show');
        },

        /**
         * Hide success message
         * @param {HTMLElement} input - Input element
         */
        hideSuccess(input) {
            const successEl = input.nextElementSibling;
            if (successEl && successEl.classList.contains('success-message')) {
                successEl.classList.remove('show');
            }
        },

        /**
         * Validate field with custom validation function
         * @param {HTMLElement} input - Input element
         * @param {Function} validator - Validation function (returns true/false or {valid, message})
         */
        validate(input, validator) {
            if (!input || typeof validator !== 'function') return;

            const result = validator(input.value);

            if (typeof result === 'boolean') {
                if (result) {
                    this.markValid(input);
                } else {
                    this.markInvalid(input);
                }
            } else if (typeof result === 'object') {
                if (result.valid) {
                    this.markValid(input, result.message);
                } else {
                    this.markInvalid(input, result.message);
                }
            }
        }
    };

    // ============================================
    // SUBTAB REVEAL - SMOOTH ANIMATIONS
    // ============================================

    /**
     * Enhance subtab bar reveal animations
     */
    /**
     * ---agentspec
     * what: |
     *   Marks all `.subtab-bar` elements with `data-state="visible"` on page load. Enables JS-driven reveal animations when parent tabs are clicked.
     *
     * why: |
     *   Decouples initial DOM state from animation logic; allows CSS/JS to control visibility transitions independently.
     *
     * guardrails:
     *   - DO NOT rely on this alone for tab state; parent tab click handlers must toggle data-state
     *   - NOTE: Runs once at load; dynamic subtab insertion requires re-invocation
     * ---/agentspec
     */
    function enhanceSubtabReveal() {
        // Find all subtab bars
        const subtabBars = document.querySelectorAll('.subtab-bar');

        subtabBars.forEach(bar => {
            // Initially mark as visible (they're shown by default in HTML)
            // JavaScript will handle the animation when parent tab is clicked
            bar.setAttribute('data-state', 'visible');
        });

        console.log('[UX Feedback] Subtab reveal enhanced');
    }

    // ============================================
    // HEALTH STATUS - PULSE ANIMATIONS
    // ============================================

    /**
     * Add pulse animation to health status based on state
     */
    /**
     * ---agentspec
     * what: |
     *   Monitors DOM element #health-status for text mutations. Triggers callback on childList or characterData changes; extracts and lowercases text content.
     *
     * why: |
     *   MutationObserver detects real-time health status updates without polling.
     *
     * guardrails:
     *   - DO NOT assume observer auto-disconnects; call observer.disconnect() when done
     *   - NOTE: Callback fires on every mutation; add debounce if text updates rapidly
     *   - ASK USER: What action should trigger on status change? (Currently observes only)
     * ---/agentspec
     */
    function enhanceHealthStatus() {
        const healthStatus = document.getElementById('health-status');
        if (!healthStatus) return;

        // Monitor health status text changes
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList' || mutation.type === 'characterData') {
                    const text = healthStatus.textContent.toLowerCase();

                    // Remove all health classes
                    healthStatus.classList.remove('healthy', 'unhealthy');

                    // Add appropriate class based on content
                    if (text.includes('healthy') || text.includes('ok') || text.includes('ready')) {
                        healthStatus.classList.add('healthy');
                    } else if (text.includes('unhealthy') || text.includes('error') || text.includes('down')) {
                        healthStatus.classList.add('unhealthy');
                    }
                }
            });
        });

        observer.observe(healthStatus, {
            childList: true,
            characterData: true,
            subtree: true
        });

        console.log('[UX Feedback] Health status pulse enabled');
    }

    // ============================================
    // EVENT EMITTER - PROGRESS EVENTS
    // ============================================

    /**
     * Listen for custom progress events from other modules
     */
    /**
     * ---agentspec
     * what: |
     *   Attaches event listeners to window for 'index:progress' events. Extracts id, percent, message, eta from event.detail; shows/updates ProgressManager based on percent value (0 = show, ≥100 = complete).
     *
     * why: |
     *   Decouples progress UI updates from indexing logic via event-driven architecture.
     *
     * guardrails:
     *   - DO NOT assume event.detail exists; guard with || {}
     *   - NOTE: Incomplete handler for percent ≥100 case (finalization logic missing)
     *   - ASK USER: Should percent ≥100 call ProgressManager.hide(id) or ProgressManager.complete(id)?
     * ---/agentspec
     */
    function setupProgressEventListeners() {
        // Listen for index progress events
        window.addEventListener('index:progress', (e) => {
            const { id, percent, message, eta } = e.detail || {};

            if (id) {
                if (percent === 0) {
                    ProgressManager.show(id, { message, eta, initialPercent: 0 });
                } else if (percent >= 100) {
                    ProgressManager.update(id, { percent: 100, message: message || 'Complete!' });
                    setTimeout(() => ProgressManager.hide(id), 1000);
                } else {
                    ProgressManager.update(id, { percent, message, eta });
                }
            }
        });

        // Listen for general loading events
        window.addEventListener('loading:start', (e) => {
            const { id, message } = e.detail || {};
            if (id) {
                ProgressManager.show(id, { message: message || 'Loading...' });
            }
        });

        window.addEventListener('loading:end', (e) => {
            const { id } = e.detail || {};
            if (id) {
                ProgressManager.hide(id);
            }
        });

        console.log('[UX Feedback] Progress event listeners registered');
    }

    // ============================================
    // INITIALIZATION
    // ============================================

    /**
     * Initialize all UX feedback systems
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes UX feedback system when DOM is ready. Defers execution until DOMContentLoaded fires if document still loading.
     *
     * why: |
     *   Prevents race conditions by ensuring DOM elements exist before initialization logic runs.
     *
     * guardrails:
     *   - DO NOT call init() synchronously at script load; defer to DOMContentLoaded
     *   - NOTE: Recursive guard prevents double-binding if init() called before DOM ready
     * ---/agentspec
     */
    function init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        console.log('[UX Feedback] Initializing...');

        // Initialize all systems
        initRippleEffects();
        enhanceSubtabReveal();
        enhanceHealthStatus();
        setupProgressEventListeners();

        console.log('[UX Feedback] All systems active ✓');
    }

    // ============================================
    // PUBLIC API
    // ============================================

    window.UXFeedback = {
        // Ripple
        createRipple,

        // Progress
        progress: ProgressManager,

        // Form validation
        form: FormFeedback,

        // Utility
        prefersReducedMotion,

        // Manual init (if needed)
        init
    };

    // Auto-initialize
    init();

    console.log('[UX Feedback] Module loaded');
})();

/**
 * Usage Examples:
 *
 * // Manual ripple on custom element
 * const button = document.querySelector('#my-button');
 * button.addEventListener('click', (e) => {
 *     window.UXFeedback.createRipple(button, e);
 * });
 *
 * // Show progress bar
 * window.UXFeedback.progress.show('indexing', {
 *     message: 'Indexing repository...',
 *     initialPercent: 0,
 *     eta: '2 minutes'
 * });
 *
 * // Update progress
 * window.UXFeedback.progress.update('indexing', {
 *     percent: 45,
 *     message: 'Processing files...',
 *     eta: '1 minute'
 * });
 *
 * // Hide progress
 * window.UXFeedback.progress.hide('indexing');
 *
 * // Form validation
 * const emailInput = document.querySelector('#email');
 * window.UXFeedback.form.validate(emailInput, (value) => {
 *     const isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
 *     return {
 *         valid: isValid,
 *         message: isValid ? 'Email looks good!' : 'Please enter a valid email'
 *     };
 * });
 *
 * // Emit progress event from any module
 * window.dispatchEvent(new CustomEvent('index:progress', {
 *     detail: {
 *         id: 'my-operation',
 *         percent: 50,
 *         message: 'Half way there!',
 *         eta: '30 seconds'
 *     }
 * }));
 */
