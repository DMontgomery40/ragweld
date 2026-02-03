import { useNavigate } from 'react-router-dom';
import { useOnboarding } from '@/hooks/useOnboarding';

// SVG Icons as components for cleaner JSX
const FolderIcon = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
  </svg>
);

const GitHubIcon = () => (
  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path>
  </svg>
);

const InfoIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="10"></circle>
    <line x1="12" y1="16" x2="12" y2="12"></line>
    <line x1="12" y1="8" x2="12.01" y2="8"></line>
  </svg>
);

// Onboarding tab rendered as proper React JSX (no dangerouslySetInnerHTML)
export default function StartTab() {
  const navigate = useNavigate();
  const { step, maxStep, setStep, nextStep, prevStep, reset } = useOnboarding();

  const handleNext = () => {
    if (step >= maxStep) {
      reset();
      navigate('/dashboard');
      return;
    }
    nextStep();
  };

  return (
    <div id="tab-start" className="tab-content">
      <div className="ob-container">
        {/* Progress indicator */}
        <div className="ob-progress-dots">
          {Array.from({ length: maxStep }).map((_, idx) => {
            const s = idx + 1;
            const classes = [
              'ob-dot',
              s === step ? 'active' : '',
              s < step ? 'completed' : '',
            ]
              .filter(Boolean)
              .join(' ');

            return (
              <span
                key={s}
                className={classes}
                data-step={String(s)}
                data-testid={`onboarding-dot-${s}`}
                role="button"
                tabIndex={0}
                aria-current={s === step ? 'step' : undefined}
                onClick={() => setStep(s)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setStep(s);
                }}
              >
                {s}
              </span>
            );
          })}
        </div>

        {/* Step 1: Welcome */}
        <div
          id="onboard-welcome"
          className={['ob-step', step === 1 ? 'active' : ''].filter(Boolean).join(' ')}
          data-testid="onboarding-step-1"
        >
          <div className="ob-main">
            <h2 className="ob-title">Welcome to Tri-Brid RAG</h2>
            <p className="ob-subtitle">Point Tri-Brid RAG at a folder or repo; in ~3 minutes it will answer questions about it.</p>

            <div className="ob-info-box">
              <p>We scan text, markdown, code, and docs. Nothing leaves your computer unless you turn on cloud.</p>
              <p>You can always start offline (keywords only) and add 'meaning' later.</p>
            </div>

            {/* Source choice cards */}
            <div className="ob-choice-cards">
              <button className="ob-card" data-choice="folder">
                <FolderIcon />
                <h3>Use a Folder on This Computer</h3>
                <p>Index local files and docs</p>
              </button>
              <button className="ob-card" data-choice="github">
                <GitHubIcon />
                <h3>Use a GitHub Repo</h3>
                <p>Clone and index a repository</p>
              </button>
            </div>

            {/* Helpful links */}
            <div className="ob-links">
              <h4>Helpful Resources:</h4>
              <div className="ob-link-grid">
                <a href="/docs/START_HERE.md" target="_blank" rel="noopener noreferrer">Getting Started</a>
                <a href="/docs/API_GUI.md" target="_blank" rel="noopener noreferrer">GUI Overview</a>
                <a href="/docs/QUICKSTART_MCP.md" target="_blank" rel="noopener noreferrer">MCP Quickstart</a>
                <a href="/docs/MODEL_RECOMMENDATIONS.md" target="_blank" rel="noopener noreferrer">Model Recommendations</a>
                <a href="/docs/PERFORMANCE_AND_COST.md" target="_blank" rel="noopener noreferrer">Performance &amp; Cost</a>
                <a href="/docs/MCP_README.md" target="_blank" rel="noopener noreferrer">MCP Details</a>
                <a href="/files/README.md" target="_blank" rel="noopener noreferrer">README</a>
                <a href="https://github.com/openai/codex" target="_blank" rel="noopener noreferrer">Codex CLI ↗</a>
                <a href="https://platform.openai.com/docs/guides/tools-connectors-mcp" target="_blank" rel="noopener noreferrer">MCP Guide ↗</a>
                <a href="https://openai.github.io/openai-agents-python/" target="_blank" rel="noopener noreferrer">Agents SDK ↗</a>
                <a href="https://openai.com/index/introducing-agentkit/" target="_blank" rel="noopener noreferrer">AgentKit ↗</a>
              </div>
            </div>
          </div>
        </div>

        {/* Step 2: Add Your Stuff */}
        <div
          id="onboard-source"
          className={['ob-step', step === 2 ? 'active' : ''].filter(Boolean).join(' ')}
          data-testid="onboarding-step-2"
        >
          <div className="ob-main">
            <h2 className="ob-title">Add Your Code and Docs</h2>

            {/* Mode switcher */}
            <div className="ob-mode-tabs">
              <button className="ob-mode-tab active" data-mode="folder">📁 Folder</button>
              <button className="ob-mode-tab" data-mode="github">🔗 GitHub</button>
            </div>

            {/* Folder mode */}
            <div id="onboard-folder-mode" className="ob-mode-content active">
              <div className="ob-input-group">
                <label>Choose Folder</label>
                <input
                  type="file"
                  id="onboard-folder-picker"
                  // @ts-expect-error webkitdirectory is a non-standard attribute
                  webkitdirectory=""
                  directory=""
                  multiple
                  style={{ display: 'none' }}
                />
                <div className="ob-file-input">
                  <button id="onboard-folder-btn" className="ob-browse-btn">Browse...</button>
                  <span id="onboard-folder-display" className="ob-file-display">No folder selected</span>
                </div>
                <p className="ob-hint">Or enter path manually:</p>
                <input type="text" id="onboard-folder-path" className="ob-text-input" placeholder="/path/to/your/project" />
              </div>
            </div>

            {/* GitHub mode */}
            <div id="onboard-github-mode" className="ob-mode-content">
              <div className="ob-input-group">
                <label>GitHub URL</label>
                <input type="text" id="onboard-github-url" className="ob-text-input" placeholder="https://github.com/owner/repo" />
              </div>
              <div className="ob-input-group">
                <label>Branch (optional)</label>
                <input type="text" id="onboard-github-branch" className="ob-text-input" placeholder="main" />
              </div>
              <div className="ob-input-group">
                <label>Personal Access Token (optional)</label>
                <input type="password" id="onboard-github-token" className="ob-text-input" placeholder="ghp_..." />
                <p className="ob-hint">Only used to clone; not stored unless you save this as a Project.</p>
              </div>
            </div>

            <div className="ob-info-box">
              We only read files you point us to. Nothing leaves your computer unless you turn on cloud.
            </div>
          </div>
        </div>

        {/* Step 3: Index & Enrich */}
        <div
          id="onboard-index"
          className={['ob-step', step === 3 ? 'active' : ''].filter(Boolean).join(' ')}
          data-testid="onboarding-step-3"
        >
          <div className="ob-main">
            <h2 className="ob-title">Build Your Indexes</h2>

            {/* Stage indicators */}
            <div className="ob-stages">
              <div className="ob-stage" data-stage="scan">
                <div className="ob-stage-dot"></div>
                <span>Light Scan</span>
              </div>
              <div className="ob-stage-arrow">→</div>
              <div className="ob-stage" data-stage="keywords">
                <div className="ob-stage-dot"></div>
                <span>Keywords &amp; Cards</span>
              </div>
              <div className="ob-stage-arrow">→</div>
              <div className="ob-stage" data-stage="smart">
                <div className="ob-stage-dot"></div>
                <span>Smart Search</span>
              </div>
            </div>

            {/* Progress bar */}
            <div className="ob-progress-bar">
              <div id="onboard-index-bar" className="ob-progress-fill"></div>
            </div>
            <div id="onboard-index-status" className="ob-progress-text">Ready to index</div>

            {/* Index log */}
            <div id="onboard-index-log" className="ob-log"></div>

            {/* Info tooltip */}
            <div className="ob-info-box">
              <div className="ob-tooltip-header">
                <InfoIcon />
                <span>How it works</span>
              </div>
              <p>We always keep a BM25 'keyword' index (works offline). When available, we add a dense 'meaning' index so it understands phrasing. If the smart part isn't ready, we fall back to keywords—so it always works.</p>
            </div>

            {/* Fallback message */}
            <div id="onboard-index-fallback" className="ob-warning-box" style={{ display: 'none' }}>
              Continuing with keywords only. Dense search can be added later.
            </div>
          </div>
        </div>

        {/* Step 4: Ask Your First Questions */}
        <div
          id="onboard-questions"
          className={['ob-step', step === 4 ? 'active' : ''].filter(Boolean).join(' ')}
          data-testid="onboarding-step-4"
        >
          <div className="ob-main">
            <h2 className="ob-title">Ask Your Codebase</h2>
            <p className="ob-subtitle">Try these Golden Questions (you can edit them)</p>

            {/* Questions */}
            <div className="ob-questions-list">
              <div className="ob-question-item">
                <input type="text" id="onboard-q1" className="ob-question-input" defaultValue="Where is hybrid retrieval implemented?" />
                <button className="ob-ask-btn" data-q="1">Ask</button>
                <div id="onboard-ans-1" className="ob-answer"></div>
                <a href="#" id="onboard-trace-1" className="ob-trace-link" style={{ display: 'none' }}>What happened under the hood?</a>
                <div id="onboard-trace-panel-1" className="ob-trace-panel" style={{ display: 'none' }}></div>
              </div>
              <div className="ob-question-item">
                <input type="text" id="onboard-q2" className="ob-question-input" defaultValue="Where are indexing settings?" />
                <button className="ob-ask-btn" data-q="2">Ask</button>
                <div id="onboard-ans-2" className="ob-answer"></div>
                <a href="#" id="onboard-trace-2" className="ob-trace-link" style={{ display: 'none' }}>What happened under the hood?</a>
                <div id="onboard-trace-panel-2" className="ob-trace-panel" style={{ display: 'none' }}></div>
              </div>
              <div className="ob-question-item">
                <input type="text" id="onboard-q3" className="ob-question-input" defaultValue="How do I change the default model?" />
                <button className="ob-ask-btn" data-q="3">Ask</button>
                <div id="onboard-ans-3" className="ob-answer"></div>
                <a href="#" id="onboard-trace-3" className="ob-trace-link" style={{ display: 'none' }}>What happened under the hood?</a>
                <div id="onboard-trace-panel-3" className="ob-trace-panel" style={{ display: 'none' }}></div>
              </div>
            </div>

            <button id="onboard-save-golden" className="ob-secondary-btn">Save to Eval Dataset</button>
          </div>
        </div>

        {/* Step 5: Tune & Save */}
        <div
          id="onboard-tune"
          className={['ob-step', step === 5 ? 'active' : ''].filter(Boolean).join(' ')}
          data-testid="onboarding-step-5"
        >
          <div className="ob-main">
            <h2 className="ob-title">Tune and Save Your Project</h2>

            {/* Sliders */}
            <div className="ob-sliders">
              <div className="ob-slider-group">
                <label>Faster ← → Thorough</label>
                <input type="range" id="onboard-slider-speed" min="1" max="4" defaultValue="2" step="1" />
                <div className="ob-slider-labels">
                  <span>Fast</span>
                  <span>Balanced</span>
                  <span>Thorough</span>
                </div>
              </div>

              <div className="ob-slider-group">
                <label>Cheapest ← → Smartest</label>
                <input type="range" id="onboard-slider-quality" min="1" max="3" defaultValue="2" step="1" />
                <div className="ob-slider-labels">
                  <span>Local/Free</span>
                  <span>Balanced</span>
                  <span>Best Quality</span>
                </div>
              </div>

              <div className="ob-slider-group">
                <label>Local ← → Cloud</label>
                <input type="range" id="onboard-slider-cloud" min="1" max="2" defaultValue="1" step="1" />
                <div className="ob-slider-labels">
                  <span>Local Only</span>
                  <span>Cloud APIs</span>
                </div>
              </div>
            </div>

            {/* Settings summary */}
            <div id="onboard-settings-summary" className="ob-settings-box">
              <h4>Settings to Apply:</h4>
              <div id="onboard-summary-content" className="ob-summary-content"></div>
            </div>

            {/* Action buttons */}
            <div className="ob-actions">
              <button id="onboard-save-project" className="ob-primary-btn">Save as a Project</button>
              <button id="onboard-run-eval" className="ob-secondary-btn">Run a Tiny Evaluation</button>
            </div>

            {/* Eval progress */}
            <div id="onboard-eval-progress" className="ob-eval-box" style={{ display: 'none' }}>
              <div className="ob-progress-bar">
                <div id="onboard-eval-bar" className="ob-progress-fill"></div>
              </div>
              <div id="onboard-eval-status" className="ob-progress-text">Running evaluation...</div>
              <div id="onboard-eval-result" className="ob-eval-result"></div>
            </div>
          </div>
        </div>

        {/* Mini help panel (persistent) */}
        <div className="ob-help-panel">
          <h4>Have questions?</h4>
          <p>Ask in plain English. We'll help.</p>
          <textarea id="onboard-help-input" className="ob-help-input" placeholder="Type your question..."></textarea>
          <button id="onboard-help-send" className="ob-help-btn">Ask</button>
          <div id="onboard-help-results" className="ob-help-results"></div>

          <div className="ob-help-pills">
            <button className="ob-help-pill" data-q="What is BM25?">What is BM25?</button>
            <button className="ob-help-pill" data-q="What is dense retrieval?">What is dense retrieval?</button>
            <button className="ob-help-pill" data-q="How long does indexing take?">How long does indexing take?</button>
          </div>

          <a href="#" id="onboard-open-chat" className="ob-help-link">Open full Chat →</a>
        </div>

        {/* Navigation footer */}
        <div className="ob-footer">
          <button
            id="onboard-back"
            className="ob-nav-btn"
            data-testid="onboarding-back"
            style={{ display: step === 1 ? 'none' : 'block' }}
            onClick={prevStep}
          >
            ← Back
          </button>
          <button
            id="onboard-next"
            className="ob-nav-btn ob-nav-primary"
            data-testid="onboarding-next"
            onClick={handleNext}
          >
            {step === maxStep ? 'Done' : 'Next →'}
          </button>
        </div>
      </div>
    </div>
  );
}
