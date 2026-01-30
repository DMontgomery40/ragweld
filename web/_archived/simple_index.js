/**
 * SIMPLE INDEX BUTTON - NO BULLSHIT
 */

const $ = id => document.getElementById(id);

async function runRealIndex() {
    const repo = $('simple-repo-select')?.value;
    const dense = $('simple-dense-check')?.checked;
    const output = $('simple-output');
    const btn = $('simple-index-btn');
    
    if (!repo) {
        alert('Select a repo first');
        return;
    }
    
    btn.disabled = true;
    btn.textContent = '⏳ INDEXING...';
    output.style.display = 'block';
    output.textContent = 'Starting indexer...\n\n';
    
    try {
        const response = await fetch(`/api/index/run?repo=${repo}&dense=${dense}`, {
            method: 'POST'
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value, { stream: true });
            output.textContent += text;
            output.scrollTop = output.scrollHeight;
        }
        
        output.textContent += '\n\n✅ DONE\n';
        btn.textContent = '🚀 INDEX NOW';
        btn.disabled = false;
        
    } catch (e) {
        output.textContent += `\n\n❌ ERROR: ${e.message}\n`;
        btn.textContent = '🚀 INDEX NOW';
        btn.disabled = false;
    }
}

// Load repos on page load
async function loadRepos() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        const select = $('simple-repo-select');
        
        if (config.repos && config.repos.length > 0) {
            select.innerHTML = '';
            config.repos.forEach(repo => {
                const opt = document.createElement('option');
                opt.value = repo.name;
                opt.textContent = repo.name;
                select.appendChild(opt);
            });
            
            // Set default
            if (config.env && config.env.REPO) {
                select.value = config.env.REPO;
            }
        }
    } catch (e) {
        console.error('Failed to load repos:', e);
    }
}

// Bind button
document.addEventListener('DOMContentLoaded', () => {
    loadRepos();
    $('simple-index-btn')?.addEventListener('click', runRealIndex);
});

// Export for global access
window.SimpleIndex = { runRealIndex, loadRepos };

