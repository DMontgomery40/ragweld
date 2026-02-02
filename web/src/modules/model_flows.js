// Model add flows and helpers. Exported via window.ModelFlows
;(function(){
  'use strict';
  const api = (window.CoreUtils && window.CoreUtils.api) ? window.CoreUtils.api : (p=>p);

  async function updateEnv(envUpdates){
    try{
      // Legacy env-update flow is deprecated in TriBridRAG.
      // The React/Zustand pipeline owns configuration now; secrets live in `.env` only.
      const msg = 'Legacy env update flow is disabled. Use the React settings UI or edit `.env`.';
      console.warn('[model_flows] updateEnv disabled', envUpdates);
      try { if (typeof window.showStatus === 'function') window.showStatus(msg, 'warning'); } catch {}
      alert(msg);
    }catch(e){ alert('Failed: ' + e.message); }
  }

  async function upsertPrice(entry){
    try{
      await fetch(api('/api/models/upsert'), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(entry) });
    }catch(e){ console.warn('Price upsert failed:', e); }
  }

  /**
   * ---agentspec
   * what: |
   *   Prompts user for LLM provider and model ID. Returns {provider, model} or null if cancelled.
   *
   * why: |
   *   Interactive UI for selecting generation model before workflow execution.
   *
   * guardrails:
   *   - DO NOT validate model against tribrid_config.json here; defer to addGenModelFlow caller
   *   - NOTE: Returns null on user cancel; caller must handle
   *   - ASK USER: Should this pre-populate from current GEN_MODEL config?
   * ---/agentspec
   */
  function promptStr(msg, defVal=''){
    const v = window.prompt(msg, defVal);
    return v === null ? null : v.trim();
  }

  async function addGenModelFlow(){
    const provider = promptStr('Provider (openai, anthropic, google, local)', 'openai');
    if (!provider) return;
    const model = promptStr('Model ID (from tribrid_config.json GEN_MODEL)', '');
    if (!model) return;
    const baseUrl = promptStr('Base URL (optional; for proxies or local, e.g., http://127.0.0.1:11434)', '');
    let apiKey = '';
    if (provider !== 'local') apiKey = promptStr('API Key (optional; shown locally only)', '') || '';

    const env = { GEN_MODEL: model };
    if (provider === 'openai'){ if (apiKey) env.OPENAI_API_KEY = apiKey; if (baseUrl) env.OPENAI_BASE_URL = baseUrl; }
    else if (provider === 'anthropic'){ if (apiKey) env.ANTHROPIC_API_KEY = apiKey; }
    else if (provider === 'google'){ if (apiKey) env.GOOGLE_API_KEY = apiKey; }
    else if (provider === 'local'){ if (baseUrl) env.OLLAMA_URL = baseUrl; }
    await updateEnv(env);
    if (window.Config?.loadConfig) await window.Config.loadConfig();

    const entry = { provider, model, family:'gen', base_url: baseUrl || undefined };
    entry.unit = provider === 'local' ? 'request' : '1k_tokens';
    await upsertPrice(entry);
    if (window.models?.loadmodels) await window.models.loadmodels();
    alert('Generation model added.');
  }

  async function addEmbedModelFlow(){
    const provider = promptStr('Embedding provider (openai, voyage, local, mxbai)', 'openai');
    if (!provider) return;
    const model = promptStr('Embedding model ID (optional; depends on provider)', provider === 'openai' ? 'text-embedding-3-small' : '');
    const baseUrl = promptStr('Base URL (optional)', '');
    let apiKey = '';
    if (provider !== 'local' && provider !== 'mxbai') apiKey = promptStr('API Key (optional)', '') || '';

    const env = {};
    if (provider === 'openai'){ env.EMBEDDING_TYPE = 'openai'; if (apiKey) env.OPENAI_API_KEY = apiKey; if (baseUrl) env.OPENAI_BASE_URL = baseUrl; }
    else if (provider === 'voyage'){ env.EMBEDDING_TYPE = 'voyage'; if (apiKey) env.VOYAGE_API_KEY = apiKey; }
    else if (provider === 'mxbai'){ env.EMBEDDING_TYPE = 'mxbai'; }
    else if (provider === 'local'){ env.EMBEDDING_TYPE = 'local'; }
    await updateEnv(env);
    if (window.Config?.loadConfig) await window.Config.loadConfig();

    const entry = { provider, model: model || provider + '-embed', family:'embed', base_url: baseUrl || undefined };
    entry.unit = '1k_tokens';
    await upsertPrice(entry);
    if (window.models?.loadmodels) await window.models.loadmodels();
    alert('Embedding model added.');
  }

  async function addRerankModelFlow(){
    const mode = promptStr('Rerank mode (cloud, local, learning, none)', 'local');
    if (!mode) return;

    const config = { reranker_mode: mode };

    if (mode === 'cloud') {
      const cloudProvider = promptStr('Cloud provider (cohere, voyage, jina)', 'cohere');
      if (!cloudProvider) return;
      const cloudModel = promptStr('Cloud model ID (e.g., rerank-v3.5)', 'rerank-v3.5');
      config.reranker_cloud_provider = cloudProvider;
      config.reranker_cloud_model = cloudModel;
    } else if (mode === 'local') {
      const localModel = promptStr('Local model ID', 'cross-encoder/ms-marco-MiniLM-L-12-v2');
      config.reranker_local_model = localModel;
    }
    // learning and none modes don't need additional config

    // Update via config API (NOT env)
    // Legacy config write path removed (POST /api/config no longer exists).
    {
      const msg = 'Legacy reranker model flow is disabled. Use the React Reranker settings UI.';
      console.warn('[model_flows] addRerankModelFlow disabled', config);
      try { if (typeof window.showStatus === 'function') window.showStatus(msg, 'warning'); } catch {}
      alert(msg);
      return;
    }

    const entry = { provider: mode === 'cloud' ? config.reranker_cloud_provider : mode, model: config.reranker_cloud_model || config.reranker_local_model || mode, family:'rerank' };
    entry.unit = mode === 'cloud' ? '1k_tokens' : 'request';
    await upsertPrice(entry);
    if (window.models?.loadmodels) await window.models.loadmodels();
    alert('Rerank model added.');
  }

  async function addCostModelFlow(){
    const provider = promptStr('Provider', 'openai');
    if (!provider) return;
    const model = promptStr('Model ID (from config)', '');
    if (!model) return;
    const baseUrl = promptStr('Base URL (optional)', '');
    const unit = promptStr('Unit (1k_tokens or request)', provider === 'local' ? 'request' : '1k_tokens') || '1k_tokens';
    await upsertPrice({ provider, model, family:'misc', base_url: baseUrl || undefined, unit });
    if (window.models?.loadmodels) await window.models.loadmodels();
    alert('Model added to pricing catalog.');
  }

  // Initialization function called by config.js when rag-retrieval view mounts
  // Does NOT register view - config.js handles that
  window.initModelFlows = function() {
    console.log('[model_flows.js] Initializing model flows for rag-retrieval view');
    // Model flows are utility functions, no specific init needed
  };

  window.ModelFlows = { updateEnv, upsertPrice, promptStr, addGenModelFlow, addEmbedModelFlow, addRerankModelFlow, addCostModelFlow };

  console.log('[model_flows.js] Module loaded (coordination with config.js for rag-retrieval view)');
})();

