// Profile logic (algorithm only). Exported via window.ProfileLogic
;(function(){
  /**
   * ---agentspec
   * what: |
   *   Proposes inference profile (model, embedding, rerank) based on local runtime availability and budget. Returns config dict with GEN_MODEL, EMBEDDING_TYPE, RERANK_BACKEND, MAX_QUERY_REWRITES, TOPK_SPARSE.
   *
   * why: |
   *   Centralizes model selection logic to match constraints (budget=0 → local/cohere, budget>0 → cohere/openai).
   *
   * guardrails:
   *   - DO NOT use gpt-4o-mini; only gpt-5 allowed
   *   - NOTE: qwen3-coder:14b requires local ollama/coreml runtime present
   *   - ASK USER: Confirm gpt-5 migration before deploying
   * ---/agentspec
   */
  function proposeProfile(scan, budget){
    const hasLocal = !!(scan && (scan.runtimes?.ollama || scan.runtimes?.coreml));
    const rprov = (Number(budget) === 0) ? (hasLocal ? 'local' : 'cohere') : 'cohere';
    return {
      GEN_MODEL: hasLocal && Number(budget) === 0 ? 'qwen3-coder:14b' : 'gpt-4o-mini',
      EMBEDDING_TYPE: (Number(budget) === 0) ? (hasLocal ? 'local' : 'openai') : 'openai',
      RERANK_BACKEND: rprov,
      MAX_QUERY_REWRITES: Number(budget) > 50 ? '6' : '3',
      TOPK_SPARSE: '75',
      TOPK_DENSE: '75',
      FINAL_K: Number(budget) > 50 ? '20' : '10',
      HYDRATION_MODE: 'lazy',
    };
  }

  /**
   * ---agentspec
   * what: |
   *   Builds wizard profile by delegating to proposeProfile(scan, budget). Returns profile object.
   *
   * why: |
   *   Separates interface from logic; allows future tuning without affecting caller.
   *
   * guardrails:
   *   - NOTE: Currently a pass-through; do not add logic here until tuning requirements clarified
   *   - DO NOT register view; config.js handles mount and registration
   * ---/agentspec
   */
  function buildWizardProfile(scan, budget){
    // Currently mirrors proposeProfile; kept separate for future tuning
    return proposeProfile(scan, budget);
  }

  // Initialization function called by config.js when profiles view mounts
  // Does NOT register view - config.js handles that since it serves both rag-retrieval and profiles
  window.initProfileLogic = function() {
    console.log('[profile_logic.js] Initializing profile logic for profiles view');
    // Initialize profile algorithm state here if needed
    // Currently stateless, so nothing to do
  };

  window.ProfileLogic = { proposeProfile, buildWizardProfile };

  console.log('[profile_logic.js] Module loaded (coordination with config.js for profiles view)');
})();

