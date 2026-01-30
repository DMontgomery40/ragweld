// AGRO GUI - Index Profiles Module
// Handles index profile selection and application

(function () {
    'use strict';

    const { api, $, state } = window.CoreUtils || {};

    if (!api || !$ || !state) {
        console.error('[index_profiles.js] CoreUtils not loaded!');
        return;
    }

    // Profile definitions
    const PROFILES = {
        shared: {
            name: 'Shared (Fast)',
            description: 'BM25-only indexing with no API calls. Perfect for quick searches across branches without embedding costs.',
            settings: {
                OUT_DIR_BASE: './out.noindex-shared',
                COLLECTION_NAME: 'code_chunks_agro_shared',
                SKIP_DENSE: '1',
                EMBEDDING_TYPE: 'local'
            },
            color: 'var(--accent)'
        },
        full: {
            name: 'Full (Best Quality)',
            description: 'Complete indexing with BM25 + dense embeddings (OpenAI). Best search quality, requires API key.',
            settings: {
                OUT_DIR_BASE: './out',
                COLLECTION_NAME: '',  // Auto-generated
                SKIP_DENSE: '0',
                EMBEDDING_TYPE: 'openai'
            },
            color: 'var(--link)'
        },
        dev: {
            name: 'Development (Testing)',
            description: 'Small subset for testing. Local embeddings, limited chunks. Fast iteration during development.',
            settings: {
                OUT_DIR_BASE: './out.noindex-dev',
                COLLECTION_NAME: 'code_chunks_agro_dev',
                SKIP_DENSE: '0',
                EMBEDDING_TYPE: 'local',
                CARDS_MAX: '50'
            },
            color: 'var(--warn)'
        }
    };

    /**
     * Update profile description based on selection
     */
    /**
     * ---agentspec
     * what: |
     *   Updates DOM element #profile-description with text from PROFILES[profileKey]. Reads selected value from #index-profile-select dropdown.
     *
     * why: |
     *   Decouples profile data (PROFILES object) from UI rendering via key-based lookup.
     *
     * guardrails:
     *   - DO NOT assume select.value exists; validate profileKey before PROFILES lookup
     *   - NOTE: Returns early if DOM elements missing; silent failure—consider logging
     *   - ASK USER: Should missing profile keys throw or default to empty string?
     * ---/agentspec
     */
    function updateProfileDescription() {
        const select = $('#index-profile-select');
        const descEl = $('#profile-description');
        
        if (!select || !descEl) return;

        const profileKey = select.value;
        const profile = PROFILES[profileKey];

        if (!profile) return;

        descEl.innerHTML = `
            <div style="color: ${profile.color}; font-weight: 600; margin-bottom: 8px;">
                ${profile.name}
            </div>
            <p style="color: var(--fg-muted); margin-bottom: 12px;">${profile.description}</p>
            <div style="background: var(--card-bg); padding: 12px; border-radius: 4px; border: 1px solid var(--line);">
                <div style="color: var(--fg-muted); font-size: 11px; font-weight: 600; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
                    Settings that will be applied:
                </div>
                <div style="font-family: 'SF Mono', monospace; font-size: 11px; color: var(--fg-muted); line-height: 1.8;">
                    ${Object.entries(profile.settings)
                        .map(([key, value]) => `<div><span style="color: var(--accent);">${key}:</span> ${value || '(auto)'}</div>`)
                        .join('')}
                </div>
            </div>
        `;
    }

    /**
     * Apply selected profile
     */
    async function applyProfile() {
        const select = $('#index-profile-select');
        const btn = $('#btn-apply-profile');
        
        if (!select) return;

        const profileKey = select.value;
        const profile = PROFILES[profileKey];

        if (!profile) {
            alert('Invalid profile selected');
            return;
        }

        if (btn) btn.disabled = true;

        try {
            // Apply settings via config API
            const response = await fetch(api('/api/config'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    env: profile.settings
                })
            });

            if (!response.ok) {
                throw new Error('Failed to apply profile settings');
            }

            const result = await response.json();
            
            if (result.status === 'success') {
                if (window.showStatus) {
                    window.showStatus(`✓ Profile "${profile.name}" applied successfully!`, 'success');
                } else {
                    alert(`✓ Profile "${profile.name}" applied!\n\nRun indexing to use these settings.`);
                }

                // Reload config to show updated values
                if (window.Config && window.Config.loadConfig) {
                    await window.Config.loadConfig();
                }
            }
        } catch (e) {
            if (window.showStatus) {
                window.showStatus(`Failed to apply profile: ${e.message}`, 'error');
            } else {
                alert(`Error: ${e.message}`);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    /**
     * Initialize index profiles UI
     */
    /**
     * ---agentspec
     * what: |
     *   Initializes index profile UI by binding change event to dropdown and apply button. Triggers updateProfileDescription on selection change.
     *
     * why: |
     *   Centralizes event setup for profile management UI in one init function.
     *
     * guardrails:
     *   - DO NOT assume DOM elements exist; add null checks before addEventListener
     *   - NOTE: applyBtn bound but never used; remove or implement click handler
     * ---/agentspec
     */
    function initIndexProfiles() {
        // Bind events
        const select = $('#index-profile-select');
        const applyBtn = $('#btn-apply-profile');

        if (select) {
            select.addEventListener('change', updateProfileDescription);
        }

        if (applyBtn) {
            applyBtn.addEventListener('click', applyProfile);
        }

        // Initial description
        updateProfileDescription();
    }

    // Export to window
    window.IndexProfiles = {
        initIndexProfiles,
        updateProfileDescription,
        applyProfile,
        PROFILES
    };

    // Initialization function called by indexing.js when rag-indexing view mounts
    // Does NOT register view - indexing.js handles that
    window.initIndexProfiles = function() {
        console.log('[index_profiles.js] Initializing index profiles for rag-indexing view');
        initIndexProfiles();
    };

    // Legacy mode: auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initIndexProfiles);
    } else {
        initIndexProfiles();
    }

    console.log('[index_profiles.js] Module loaded (coordination with indexing.js for rag-indexing view)');
})();

