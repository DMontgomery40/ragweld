import { useState, useEffect, useCallback } from 'react';

// This is a placeholder for the actual API functions
// In a real app, this would be in a separate api.ts file
const api = {
    get: async (url: string) => {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    },
    post: async (url: string, data?: any) => {
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
    }
};


interface RerankerOption {
    id: string;
    backend: string;
    label: string;
    description: string;
}

interface IndexStatusMetadata {
    current_repo: string;
    current_branch: string;
    timestamp: string;
    embedding_model: string;
    keywords_count: number;
    total_storage: number;
    repos: {
        name: string;
        profile: string;
        chunk_count: number;
        has_cards: boolean;
        sizes: {
            chunks?: number;
            bm25?: number;
            cards?: number;
        };
    }[];
}

interface IndexStatus {
    lines: string[];
    metadata: IndexStatusMetadata | null;
    running: boolean;
}


/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages dashboard state for a multi-component UI system.
 *   Initializes and maintains state for: reranker options (array of RerankerOption objects), evaluation dropdown visibility (boolean), git branch/repo identifiers (strings), system health status (string), card count (string), MCP status (string), and autotune configuration (string).
 *   Returns an object containing all state variables and their setter functions for use in dashboard components.
 *   All state values default to '—' (em-dash) except rerankerOptions (empty array) and isEvalDropdownOpen (false), indicating uninitialized or unavailable data.
 *   No side effects on mount; state is purely local to the hook consumer.
 *
 * why: |
 *   Centralizes dashboard state management into a single reusable hook to avoid prop drilling across multiple dashboard components.
 *   Separates state logic from UI rendering, making the hook testable and composable across different dashboard layouts.
 *   The '—' default convention provides a consistent visual indicator for uninitialized or missing data across the dashboard UI.
 *
 * guardrails:
 *   - DO NOT add API calls or side effects directly in this hook; keep it a pure state container and move async logic to useEffect in consuming components
 *   - ALWAYS initialize new dashboard state variables in this hook rather than scattering them across multiple components to maintain single source of truth
 *   - NOTE: All string state fields default to '—'; consuming components must handle this sentinel value or replace it with actual data via setters
 *   - ASK USER: Before adding derived state (computed values based on other state), confirm whether it should live here or in a separate useMemo hook in the consumer component
 * ---/agentspec
 */
export function useDashboard() {
    const [rerankerOptions, setRerankerOptions] = useState<RerankerOption[]>([]);
    const [isEvalDropdownOpen, setIsEvalDropdownOpen] = useState(false);
    const [branch, setBranch] = useState('—');
    const [repo, setRepo] = useState('—');
    const [health, setHealth] = useState('—');
    const [cards, setCards] = useState('—');
    const [mcp, setMcp] = useState('—');
    const [autotune, setAutotune] = useState('—');
    const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);

    // Terminal State
    const [isTerminalVisible, setIsTerminalVisible] = useState(false);
    const [terminalTitle, setTerminalTitle] = useState('');
    const [terminalLines, setTerminalLines] = useState<string[]>([]);
    const [terminalProgress, setTerminalProgress] = useState<{ percent: number, message: string } | null>(null);

    /**
     * ---agentspec
     * what: |
     *   Controls visibility and state of a terminal UI component in React.
     *   showTerminal takes a title string parameter and sets three state variables: terminal title, visibility flag to true, clears terminal output lines array, and resets progress indicator to null.
     *   hideTerminal takes no parameters and sets the visibility flag to false.
     *   No return values; side effects are state mutations that trigger React re-renders.
     *   Edge case: showTerminal clears previous terminal content, so rapid successive calls will lose prior output.
     *
     * why: |
     *   Separates terminal show/hide logic into two focused functions for cleaner component code and reusability.
     *   showTerminal resets state on each call to ensure a clean slate for new terminal sessions, preventing stale output from previous operations.
     *   hideTerminal is minimal because it only needs to toggle visibility; other state persists until the next showTerminal call.
     *
     * guardrails:
     *   - DO NOT call showTerminal and hideTerminal in rapid succession without waiting for state updates; React batching may cause race conditions
     *   - ALWAYS pass a non-empty title string to showTerminal; empty titles create poor UX and may break layout
     *   - NOTE: setTerminalLines([]) clears all previous output; if terminal history is needed, store it before calling showTerminal
     *   - ASK USER: Confirm whether terminal state should persist across hide/show cycles or reset each time before modifying the clear behavior
     * ---/agentspec
     */
    const showTerminal = (title: string) => {
        setTerminalTitle(title);
        setIsTerminalVisible(true);
        setTerminalLines([]);
        setTerminalProgress(null);
    };

    /**
     * ---agentspec
     * what: |
     *   Three utility functions for managing terminal UI state in a React component.
     *   hideTerminal() sets terminal visibility to false (no parameters, no return value).
     *   appendTerminalLine(line: string) appends a new string line to the terminal output array by spreading previous state and adding the new line.
     *   toggleEvalDropdown() toggles the evaluation dropdown state (incomplete implementation; body not shown).
     *   All three use React hooks (setIsTerminalVisible, setTerminalLines) to update component state.
     *
     * why: |
     *   These functions encapsulate state mutations for the terminal UI, providing a clean API for parent components or event handlers to control terminal visibility and output.
     *   Separating concerns (hide, append, toggle) makes the code more testable and reusable than inline setState calls.
     *   The spread operator in appendTerminalLine ensures immutability and proper React re-rendering.
     *
     * guardrails:
     *   - DO NOT call appendTerminalLine with null or undefined; validate input before calling to prevent array corruption
     *   - ALWAYS use these functions through event handlers or callbacks; do not call setState directly elsewhere in the component
     *   - NOTE: toggleEvalDropdown() is incomplete and will cause runtime errors if invoked; implementation is missing
     *   - ASK USER: Confirm the intended behavior of toggleEvalDropdown() before completing implementation (should it toggle a boolean, open/close a menu, etc.)
     * ---/agentspec
     */
    const hideTerminal = () => {
        setIsTerminalVisible(false);
    };
    
    /**
     * ---agentspec
     * what: |
     *   Provides three utility functions for managing terminal output and dropdown UI state in a React component.
     *   appendTerminalLine takes a string parameter and appends it to the terminalLines state array using functional setState.
     *   toggleEvalDropdown inverts the boolean isEvalDropdownOpen state without parameters.
     *   closeEvalDropdown is a memoized callback (via useCallback) that closes the dropdown by setting isEvalDropdownOpen to false.
     *   No return values; all functions produce side effects on component state only.
     *   Edge case: appendTerminalLine does not validate line content (empty strings, null, undefined will be added as-is).
     *
     * why: |
     *   These are standard React state management patterns extracted into separate functions for reusability and clarity.
     *   appendTerminalLine uses functional setState to ensure state updates are based on the previous state, avoiding race conditions in rapid updates.
     *   toggleEvalDropdown and closeEvalDropdown are separated to provide both toggle and explicit close semantics for different UI interactions.
     *   useCallback memoization on closeEvalDropdown prevents unnecessary re-renders of child components that receive it as a prop.
     *
     * guardrails:
     *   - DO NOT pass null or undefined to appendTerminalLine without validation; add a guard clause to filter invalid inputs
     *   - ALWAYS use functional setState in appendTerminalLine to maintain consistency with concurrent state updates
     *   - NOTE: closeEvalDropdown is incomplete in the provided code snippet; confirm the full implementation before deployment
     *   - ASK USER: Confirm whether appendTerminalLine should sanitize or validate line content before adding to state (e.g., max length, XSS prevention)
     * ---/agentspec
     */
    const appendTerminalLine = (line: string) => {
        setTerminalLines(prev => [...prev, line]);
    };

    /**
     * ---agentspec
     * what: |
     *   Manages dropdown UI state for an evaluation menu component.
     *   toggleEvalDropdown() accepts no parameters and toggles the isEvalDropdownOpen boolean state between true and false.
     *   closeEvalDropdown() is a memoized callback that sets isEvalDropdownOpen to false; returns undefined.
     *   Both functions have no side effects beyond state mutation; no external API calls or DOM manipulation.
     *   Edge case: Rapid successive calls to toggleEvalDropdown may cause state race conditions if component unmounts during state update.
     *
     * why: |
     *   Separates toggle and close behaviors to provide flexible dropdown control: toggle for click handlers, close for blur/escape key handlers.
     *   closeEvalDropdown is wrapped in useCallback to prevent unnecessary re-renders of child components that depend on this function reference.
     *   This pattern allows parent and child components to control dropdown state independently without prop drilling.
     *
     * guardrails:
     *   - DO NOT call these functions during render; they mutate state and will cause infinite loops
     *   - ALWAYS pair closeEvalDropdown with an event listener cleanup to prevent memory leaks when component unmounts
     *   - NOTE: useCallback dependency array is empty; if this function needs access to other state/props, add them to dependencies and update callers
     *   - ASK USER: Confirm whether rapid toggle clicks should be debounced or if current toggle behavior is intentional for your UX
     * ---/agentspec
     */
    const toggleEvalDropdown = () => {
        setIsEvalDropdownOpen(prev => !prev);
    };

    const closeEvalDropdown = useCallback(() => {
        setIsEvalDropdownOpen(false);
    }, []);


    // Fetch reranker options
    useEffect(() => {
        const fetchRerankerOptions = async () => {
            try {
                const data = await api.get('/api/reranker/available');
                if (data.options) {
                    setRerankerOptions(data.options);
                }
            } catch (error) {
                console.error('Failed to load reranker options:', error);
            }
        };
        fetchRerankerOptions();
    }, []);

    // Poll for index status
    useEffect(() => {
        const poll = async () => {
            try {
                const data: IndexStatus = await api.get('/api/index/status');
                setIndexStatus(data);
                if (data.metadata) {
                    setBranch(data.metadata.current_branch);
                    setRepo(data.metadata.current_repo);
                    const cardsCount = data.metadata.repos.reduce((acc, repo) => acc + (repo.has_cards ? 1 : 0), 0);
                    setCards(`${cardsCount} / ${data.metadata.repos.length}`);
                }
                 const healthData = await api.get('/api/health');
                 if(healthData.status === 'ok'){
                    setHealth('OK');
                 } else {
                    setHealth('Error');
                 }

                 const configData = await api.get('/api/config');
                 if(configData.MCP_SERVER_URL){
                     setMcp('Active');
                 } else {
                     setMcp('Inactive');
                 }
                 if(configData.AUTOTUNE_ENABLED === 'true'){
                    setAutotune('Enabled')
                 } else {
                    setAutotune('Disabled')
                 }


            } catch (error) {
                console.error('Failed to poll index status:', error);
            }
        };

        poll(); // initial poll
        const intervalId = setInterval(poll, 30000); // poll every 30 seconds

        return () => clearInterval(intervalId);
    }, []);

    const runIndexer = useCallback(async () => {
        showTerminal('Run Indexer');
        try {
            const response = await fetch('/api/index/start', { method: 'POST' });
            if (!response.body) return;
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const text = decoder.decode(value);
                appendTerminalLine(text);
            }
        } catch (error) {
            console.error('Failed to start indexer:', error);
            appendTerminalLine(`❌ Error: ${error instanceof Error ? error.message : String(error)}`);
        }
    }, []);
    
    const runKeywords = useCallback(async () => {
        showTerminal('Generate Keywords');
        appendTerminalLine('🔄 Loading keywords from repos.json...');
        try {
            const response = await fetch('/api/keywords/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            const data = await response.json();

            if (response.ok && data.ok !== false) {
                // Support both new format (count/keywords) and legacy format (total_count)
                const total = data.count ?? data.total_count ?? 0;
                appendTerminalLine(`✅ Loaded ${total} keywords from repos.json`);
                appendTerminalLine(`   Duration: ${data.duration_seconds || 0}s`);
            } else {
                const errorMsg = data.error || data.detail || 'Unknown error';
                appendTerminalLine(`❌ Error: ${errorMsg}`);
            }
        } catch (error) {
            console.error('Failed to generate keywords:', error);
            appendTerminalLine(`❌ Error: ${error instanceof Error ? error.message : String(error)}`);
        }
    }, []);
    
    const runEval = useCallback(async (model: string, backend: string) => {
        showTerminal(`Evaluate - ${model}`);
        appendTerminalLine(`Running eval with model: ${model}, backend: ${backend}`);
        // Placeholder for eval logic
        console.log(`Running eval with model: ${model}, backend: ${backend}`);
        closeEvalDropdown();
    }, [closeEvalDropdown]);

    // Close dropdown on click outside
    useEffect(() => {
        if (!isEvalDropdownOpen) return;

        const handleClickOutside = (event: MouseEvent) => {
            const trigger = document.getElementById('dash-eval-trigger');
            const dropdown = document.getElementById('dash-eval-dropdown');
            if (trigger && dropdown && !trigger.contains(event.target as Node) && !dropdown.contains(event.target as Node)) {
                closeEvalDropdown();
            }
        };

        document.addEventListener('click', handleClickOutside);
        return () => {
            document.removeEventListener('click', handleClickOutside);
        };
    }, [isEvalDropdownOpen, closeEvalDropdown]);

    return {
        rerankerOptions,
        isEvalDropdownOpen,
        toggleEvalDropdown,
        runEval,
        branch,
        repo,
        health,
        cards,
        mcp,
        autotune,
        runIndexer,
        runKeywords,
        indexStatus,
        isTerminalVisible,
        terminalTitle,
        terminalLines,
        terminalProgress,
        hideTerminal,
    };
}