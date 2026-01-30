// Profile Renderer - Rich, professional display of auto-generated profiles
;(function(){
  
  // Setting metadata with explanations
  const SETTING_INFO = {
    GEN_MODEL: {
      name: 'Generation Model',
      description: 'The AI model used to generate answers from retrieved code. This is the "brain" that synthesizes information.',
      category: 'Generation',
      icon: '🧠'
    },
    EMBEDDING_TYPE: {
      name: 'Embedding Provider',
      description: 'Creates vector representations of your code for semantic search. Higher quality embeddings find more relevant results.',
      category: 'Retrieval',
      icon: '🔍'
    },
    RERANK_BACKEND: {
      name: 'Reranking Engine',
      description: 'Re-scores retrieved results for precision. This is your quality filter that ensures the best results rise to the top. Shows backend and model when applicable.',
      category: 'Retrieval',
      icon: '⚡'
    },
    COHERE_RERANK_MODEL: {
      name: 'Rerank Model',
      description: 'Specific Cohere reranker model used when backend = cohere (e.g., rerank-3.5).',
      category: 'Retrieval',
      icon: '⚙️'
    },
    RERANKER_MODEL: {
      name: 'Rerank Model',
      description: 'Local/HF reranker model used when backend = local or hf (e.g., BAAI/bge-reranker-v2-m3).',
      category: 'Retrieval',
      icon: '⚙️'
    },
    MAX_QUERY_REWRITES: {
      name: 'Multi-Query Expansion',
      description: 'Number of query variations generated to cast a wider search net. More rewrites = better recall but higher cost.',
      category: 'Search Strategy',
      icon: '🎯',
      valueExplainer: (v) => v + ' variations per query'
    },
    TOPK_SPARSE: {
      name: 'BM25 Candidates',
      description: 'Number of keyword-based matches to retrieve. BM25 is excellent for exact terms and technical names.',
      category: 'Search Strategy',
      icon: '📝',
      valueExplainer: (v) => 'Top ' + v + ' keyword matches'
    },
    TOPK_DENSE: {
      name: 'Vector Candidates',
      description: 'Number of semantic matches to retrieve. Vector search excels at conceptual similarity.',
      category: 'Search Strategy',
      icon: '🎨',
      valueExplainer: (v) => 'Top ' + v + ' semantic matches'
    },
    FINAL_K: {
      name: 'Final Results',
      description: 'After hybrid fusion and reranking, this many results are sent to generation. Balance between context and cost.',
      category: 'Search Strategy',
      icon: '🎁',
      valueExplainer: (v) => v + ' final results'
    },
    HYDRATION_MODE: {
      name: 'Code Hydration',
      description: 'How full code is loaded. "Lazy" fetches on-demand for efficiency. "Eager" pre-loads everything.',
      category: 'Performance',
      icon: '💧'
    }
  };

  const TIER_INFO = {
    0: { name: 'Free Tier', color: 'var(--link)', badge: 'LOCAL ONLY' },
    10: { name: 'Starter', color: 'var(--link)', badge: 'BUDGET FRIENDLY' },
    50: { name: 'Professional', color: 'var(--link)', badge: 'BALANCED' },
    200: { name: 'Enterprise', color: 'var(--accent)', badge: 'MAXIMUM PERFORMANCE' }
  };

  /**
   * ---agentspec
   * what: |
   *   Renders profile results UI block. Takes profile, scan, budget objects; outputs HTML string with tier name, badge, styling.
   *
   * why: |
   *   Centralizes tier-based UI rendering to avoid duplicating TIER_INFO lookups and style logic.
   *
   * guardrails:
   *   - DO NOT mutate profile/scan/budget; read-only
   *   - NOTE: Assumes TIER_INFO[budget] exists or falls back to 'Custom'
   *   - ASK USER: Validate tierInfo.color is valid CSS var before render
   * ---/agentspec
   */
  function renderProfileResults(profile, scan, budget) {
    const tierInfo = TIER_INFO[budget] || { name: 'Custom', color: 'var(--fg-muted)', badge: 'CUSTOM CONFIG' };
    
    let html = '<div style="margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid var(--line);">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">';
    html += '<div>';
    html += '<h4 style="font-size:18px;font-weight:700;color: var(--fg);margin-bottom:4px;">' + tierInfo.name + ' Profile</h4>';
    html += '<span style="font-size:11px;color:' + tierInfo.color + ';font-weight:600;letter-spacing:0.8px;">' + tierInfo.badge + '</span>';
    html += '</div>';
    html += '<div style="font-size:28px;font-weight:800;color:' + tierInfo.color + ';">$' + budget + '/mo</div>';
    html += '</div>';
    
    html += '<div style="background: var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px;margin-top:12px;">';
    html += '<p style="font-size:13px;color:var(--fg-muted);line-height:1.6;margin:0;">';
    html += '<strong style="color:var(--accent);">Baseline Configuration</strong> — ';
    html += 'This profile gives you a strong starting point optimized for your hardware and budget. ';
    html += 'You can fine-tune any setting in the Models, Retrieval, or Infrastructure tabs. ';
    html += 'Consider saving multiple profiles for different use cases (e.g., "dev-fast" vs "prod-quality").';
    html += '</p></div></div>';

    html += '<div style="display:flex;flex-direction:column;gap:16px;margin-bottom:24px;">';

    // Group settings by category
    const categories = {};
    Object.keys(profile).forEach(key => {
      const info = SETTING_INFO[key];
      if (!info) return;
      
      const cat = info.category;
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push({ key: key, value: profile[key], info: info });
    });

    // Render each category
    Object.entries(categories).forEach(([catName, settings]) => {
      html += '<div style="background:var(--card-bg);border:1px solid var(--line);border-radius:6px;padding:16px;">';
      html += '<h5 style="font-size:12px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:14px;">';
      html += catName + '</h5>';
      html += '<div style="display:flex;flex-direction:column;gap:12px;">';

      settings.forEach(({ key, value, info }) => {
        let displayValue = info.valueExplainer ? info.valueExplainer(value) : value;
        if (key === 'RERANK_BACKEND') {
          if (String(value) === 'cohere' && profile.COHERE_RERANK_MODEL) {
            displayValue = `${value}: ${profile.COHERE_RERANK_MODEL}`;
          } else if ((String(value) === 'hf' || String(value) === 'local') && profile.RERANKER_MODEL) {
            displayValue = `${value}: ${profile.RERANKER_MODEL}`;
          }
        }
        html += '<div style="display:flex;gap:12px;">';
        html += '<div style="font-size:20px;flex-shrink:0;width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--bg-elev2);border-radius:6px;">';
        html += info.icon + '</div>';
        html += '<div style="flex:1;">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">';
        html += '<span style="font-size:13px;font-weight:600;color: var(--fg);">' + info.name + '</span>';
        html += '<code style="font-size:12px;color:var(--accent);background:var(--card-bg);padding:2px 8px;border-radius:4px;font-family:\'SF Mono\',monospace;">';
        html += displayValue + '</code></div>';
        html += '<p style="font-size:12px;color:var(--fg-muted);line-height:1.5;margin:0;">' + info.description + '</p>';
        html += '</div></div>';
      });

      html += '</div></div>';
    });

    html += '</div>';

    html += '<div style="display:flex;gap:12px;padding-top:16px;border-top:1px solid var(--line);">';
    html += '<button id="apply-profile-btn" class="small-button" style="flex:1;background:var(--accent);color: var(--accent-contrast);border:none;padding:12px;font-weight:700;">';
    html += 'Apply This Profile</button>';
    html += '<button id="export-profile-btn" class="small-button" style="background:var(--bg-elev2);border:1px solid var(--line);color:var(--fg-muted);padding:12px;">';
    html += 'Export JSON</button>';
    html += '<button id="save-profile-btn" class="small-button" style="background:var(--bg-elev2);border:1px solid var(--line);color:var(--fg-muted);padding:12px;">';
    html += 'Save As...</button></div>';

    html += '<div style="margin-top:20px;padding:14px;background:var(--card-bg);border:1px solid var(--line);border-radius:6px;">';
    html += '<div style="font-size:11px;color:var(--fg-muted);line-height:1.6;">';
    html += '<strong style="color:var(--fg-muted);">Hardware Detected:</strong> ';
    html += (scan && scan.info && scan.info.os) || 'Unknown';
    html += ' • ';
    html += (scan && scan.info && scan.info.arch) || 'Unknown';
    html += ' • ';
    html += (scan && scan.info && scan.info.cpu_cores) || '?';
    html += ' cores • ';
    html += (scan && scan.info && scan.info.mem_gb) ? scan.info.mem_gb + 'GB RAM' : 'RAM unknown';
    if (scan && scan.runtimes && scan.runtimes.ollama) html += ' • Ollama available';
    if (scan && scan.runtimes && scan.runtimes.cuda) html += ' • CUDA available';
    html += '</div></div>';

    return html;
  }

  // Initialization function called by config.js when profiles view mounts
  // Does NOT register view - config.js handles that
  window.initProfileRenderer = function() {
    console.log('[profile_renderer.js] Initializing profile renderer for profiles view');
    // Initialize renderer state here if needed
    // Currently stateless rendering, so nothing to do
  };

  window.ProfileRenderer = { renderProfileResults: renderProfileResults };
  window.ProfileRenderer.bindTooltips = function bindTooltips(root){
    if (!root) return;
    const icons = root.querySelectorAll('.help-icon');
    icons.forEach(icon => {
      const wrap = icon.parentElement;
      const bubble = wrap && wrap.querySelector('.tooltip-bubble');
      if (!wrap || !bubble) return;
      function show(){ bubble.classList.add('tooltip-visible'); }
      function hide(){ bubble.classList.remove('tooltip-visible'); }
      icon.addEventListener('mouseenter', show);
      icon.addEventListener('mouseleave', hide);
      icon.addEventListener('focus', show);
      icon.addEventListener('blur', hide);
      icon.addEventListener('click', (e)=>{ e.stopPropagation(); bubble.classList.toggle('tooltip-visible'); });
      document.addEventListener('click', (evt)=>{ if (!wrap.contains(evt.target)) bubble.classList.remove('tooltip-visible'); });
    });
  }

  console.log('[profile_renderer.js] Module loaded (coordination with config.js for profiles view)');
})();
