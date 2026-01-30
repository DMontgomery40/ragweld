const get = async (url: string) => {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
};

const post = async (url: string, data?: any) => {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
};

const postStream = async (url: string, data: any, onChunk: (chunk: string) => void) => {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    });

    if (!response.body) {
        throw new Error("Response has no body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value);
        onChunk(text);
    }
};

export const healthApi = {
    check: () => get('/api/health'),
};

export const configApi = {
    get: () => get('/api/config'),
    update: (data: any) => post('/api/config', data),
    // Renamed from reloadEnv - reloads agro_config.json, NOT .env
    reloadConfig: () => post('/api/env/reload'),
    reloadEnv: () => post('/api/env/reload'), // DEPRECATED: use reloadConfig
    load: () => get('/api/config'),
    saveEnv: (env: any) => post('/api/config', { env }), // DEPRECATED naming
    saveConfig: (update: any) => post('/api/config', update),
    loadKeywords: () => get('/api/keywords'),
    addKeyword: (keyword: string, category?: string) => post('/api/keywords/add', { keyword, category }),
    deleteKeyword: (keyword: string) => post('/api/keywords/delete', { keyword }),
};

export const dockerApi = {
    getStatus: () => get('/api/docker/status'),
    listContainers: () => get('/api/docker/containers/all'),
    startContainer: (id: string) => post(`/api/docker/container/${id}/start`),
    stopContainer: (id: string) => post(`/api/docker/container/${id}/stop`),
    restartContainer: (id: string) => post(`/api/docker/container/${id}/restart`),
};

export const rerankerApi = {
    getAvailable: () => get('/api/reranker/available'),
};

export const indexApi = {
    getStatus: () => get('/api/index/status'),
    startIndexing: () => post('/api/index/start'),
    runIndexer: (repo: string, dense: boolean, onChunk: (chunk: string) => void) => postStream(`/api/index/run?repo=${repo}&dense=${dense}`, {}, onChunk),
};

export const keywordsApi = {
    generate: (repo: string, onChunk: (chunk: string) => void) => postStream('/api/keywords/generate', { repo }, onChunk),
};

// Generic api object for other calls
export const api = {
    get,
    post,
    postStream,
};