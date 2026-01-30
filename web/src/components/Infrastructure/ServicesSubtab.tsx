// AGRO - Infrastructure Services Subtab
// Real React component with full backend wiring

import { useState, useEffect } from 'react';
import { dockerApi } from '@/api/docker';
import { configApi } from '@/api/config';
import { useAPI } from '@/hooks';
import type { DockerStatus, DockerContainer } from '@web/types';

interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'checking';
  color: string;
  port: number;
  description: string;
}

/**
 * ---agentspec
 * what: |
 *   React component that renders a subtab for displaying and managing Docker services and containers.
 *   Accepts no props; uses useAPI hook to access API client context.
 *   Returns a JSX element displaying Docker status, container lists (general and agro-specific), and service management controls.
 *   Manages local state for dockerStatus (DockerStatus | null), containers (DockerContainer[]), and agroContainers (DockerContainer[]).
 *   Side effects: Fetches Docker status and container data on mount via api client; updates state based on API responses.
 *   Edge cases: Handles null dockerStatus gracefully; distinguishes between general containers and agro-specific containers; manages loading/error states during API calls.
 *
 * why: |
 *   Separates Docker service management into a dedicated subtab component to keep the parent tab component clean and focused.
 *   Uses local useState hooks for container and status data rather than global state because this data is subtab-scoped and doesn't need to be shared across the application.
 *   The distinction between containers and agroContainers suggests domain-specific filtering or categorization of Docker resources.
 *
 * guardrails:
 *   - DO NOT move dockerStatus, containers, or agroContainers to a zustand store without user confirmation; these are subtab-local concerns and useState is appropriate
 *   - ALWAYS validate api client existence before calling api methods; useAPI hook should guarantee this but add defensive checks
 *   - NOTE: State initialization shows incomplete implementation; service status state variables are declared but not shown—confirm all state hooks are present before deployment
 *   - ASK USER: Clarify the distinction between containers and agroContainers; are these filtered by label, namespace, or another criterion? This affects data-fetching logic.
 * ---/agentspec
 */
export function ServicesSubtab() {
  const { api } = useAPI();

  // Core state
  const [dockerStatus, setDockerStatus] = useState<DockerStatus | null>(null);
  const [containers, setContainers] = useState<DockerContainer[]>([]);
  const [agroContainers, setAgroContainers] = useState<DockerContainer[]>([]);

  // Service status
  const [qdrantStatus, setQdrantStatus] = useState<ServiceStatus>({
    name: 'Qdrant',
    status: 'checking',
    color: 'var(--accent)',
    port: 6333,
    description: 'Vector database'
  });

  const [redisStatus, setRedisStatus] = useState<ServiceStatus>({
    name: 'Redis',
    status: 'checking',
    color: 'var(--err)',
    port: 6379,
    description: 'Memory store'
  });

  const [prometheusStatus, setPrometheusStatus] = useState<ServiceStatus>({
    name: 'Prometheus',
    status: 'checking',
    color: 'var(--warn)',
    port: 9090,
    description: 'Metrics collector'
  });

  const [grafanaStatus, setGrafanaStatus] = useState<ServiceStatus>({
    name: 'Grafana',
    status: 'checking',
    color: 'var(--link)',
    port: 3000,
    description: 'Dashboards'
  });

  const [lokiStatus, setLokiStatus] = useState<ServiceStatus>({
    name: 'Loki',
    status: 'checking',
    color: 'var(--accent)',
    port: 3100,
    description: 'Log aggregation'
  });

  // Action states
  const [loading, setLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [runtimeMode, setRuntimeMode] = useState('0');

  // Logs modal state
  const [logsModalOpen, setLogsModalOpen] = useState(false);
  const [logsContent, setLogsContent] = useState('');
  const [logsContainerName, setLogsContainerName] = useState('');
  const [logsContainerId, setLogsContainerId] = useState('');
  const [logsLoading, setLogsLoading] = useState(false);

  // Load initial data
  useEffect(() => {
    fetchAllStatus();
    loadRuntimeMode();

    // Auto-refresh every 30 seconds
    const interval = setInterval(() => {
      fetchAllStatus();
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  // Load runtime mode from backend
  /**
   * ---agentspec
   * what: |
   *   Asynchronously fetches the runtime mode from the backend configuration API and updates local UI state.
   *   Takes no parameters; calls configApi.getRuntimeMode() which returns an object with a runtime_mode string field ('development' or 'production').
   *   Maps backend values to UI representation: 'development' → '1', 'production' → '0', then calls setRuntimeMode() to update state.
   *   On API failure, logs error to console and defaults to production mode ('0') to ensure safe fallback behavior.
   *   Side effect: Updates component state via setRuntimeMode hook; assumes setRuntimeMode is a Zustand store setter or React useState dispatch.
   *
   * why: |
   *   Abstracts backend runtime mode polling behind a consistent UI state layer, allowing the UI to work with simple numeric codes ('0'/'1') rather than string literals.
   *   The mapping layer decouples frontend representation from backend contract, making it easier to change either independently.
   *   Defensive error handling with a safe default (production mode) prevents the UI from entering an undefined state if the API call fails.
   *
   * guardrails:
   *   - DO NOT change the mapping logic ('development' → '1', 'production' → '0') without updating all consumers of setRuntimeMode; this is a contract between backend and UI
   *   - ALWAYS ensure setRuntimeMode is a Zustand store setter or React hook dispatch; if migrating state management, update this function's state call accordingly
   *   - NOTE: Error handling silently defaults to production mode; this may mask transient API failures. Consider adding retry logic or user notification if runtime mode mismatches are critical
   *   - ASK USER: Confirm whether the default fallback should be production ('0') or if a retry strategy with exponential backoff should be implemented for reliability
   * ---/agentspec
   */
  const loadRuntimeMode = async () => {
    try {
      const { runtime_mode } = await configApi.getRuntimeMode();
      // Map backend values to UI values: 'development' -> '1', 'production' -> '0'
      setRuntimeMode(runtime_mode === 'development' ? '1' : '0');
    } catch (error) {
      console.error('[ServicesSubtab] Failed to load runtime mode:', error);
      // Default to production (Docker) mode on error
      setRuntimeMode('0');
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Orchestrates parallel fetching of Docker daemon status and container list, then sequentially fetches service status using the freshly retrieved container data.
   *   Takes no parameters; returns a Promise that resolves when all three fetch operations complete.
   *   Executes fetchDockerStatus() and fetchContainers() in parallel via Promise.all(), discards the Docker status result, then passes the containersList to fetchServiceStatus() for sequential execution.
   *   Handles async coordination but does not implement error handling, retry logic, or timeout management—failures in any fetch will propagate uncaught.
   *
   * why: |
   *   Two-phase fetch pattern ensures service status checks operate on current container data rather than stale Zustand store state.
   *   Parallel execution of Docker status and containers reduces latency; sequential service status fetch depends on fresh container list to avoid querying against outdated infrastructure state.
   *   This prevents race conditions where service status queries might reference containers that no longer exist or miss newly created ones.
   *
   * guardrails:
   *   - DO NOT use stale containersList from Zustand store in fetchServiceStatus(); always pass the freshly returned value from Promise.all() to guarantee consistency
   *   - ALWAYS await the entire chain before considering the status fetch complete; partial completion leaves service status potentially out-of-sync with container reality
   *   - NOTE: Promise.all() will reject if either fetchDockerStatus() or fetchContainers() fails; no graceful degradation for partial failures
   *   - ASK USER: Should this function implement error boundaries (try/catch) and retry logic for transient Docker daemon failures, or is caller responsible for error handling?
   * ---/agentspec
   */
  const fetchAllStatus = async () => {
    // Fetch Docker status in parallel with containers
    const [, containersList] = await Promise.all([
      fetchDockerStatus(),
      fetchContainers()
    ]);
    // THEN check service status using the returned containers (not stale state)
    await fetchServiceStatus(containersList);
  };

  /**
   * ---agentspec
   * what: |
   *   Asynchronously fetches the current Docker daemon status and updates component state.
   *   Takes no parameters; calls dockerApi.getStatus() which returns a status object containing running (boolean), runtime (string), and containers_count (number).
   *   On success, updates the dockerStatus state via setDockerStatus with the returned status object.
   *   On failure (network error, API unavailable, etc.), logs the error to console and sets dockerStatus to a safe default: { running: false, runtime: 'Unknown', containers_count: 0 }.
   *   This ensures the UI always has a valid state object to render, preventing undefined reference errors.
   *
   * why: |
   *   Wraps the async API call with error handling to gracefully degrade when Docker is unavailable or unreachable.
   *   The default fallback state prevents UI crashes and communicates to users that Docker is not running or cannot be contacted.
   *   Logging the error aids debugging without exposing raw errors to end users.
   *
   * guardrails:
   *   - DO NOT remove the try-catch block; Docker API calls can fail for many reasons (daemon not running, permission denied, socket unavailable) and must be handled gracefully
   *   - ALWAYS set dockerStatus to the safe default on error to prevent undefined state from breaking the UI
   *   - NOTE: This function uses console.error for logging; consider integrating with a centralized error tracking/logging service for production monitoring
   *   - ASK USER: Confirm whether retry logic (exponential backoff, max attempts) should be added before calling dockerApi.getStatus(), or if single-attempt behavior is acceptable
   *   - ASK USER: Clarify if setDockerStatus should use a Zustand store or React hook (useState) for shared state management across components
   * ---/agentspec
   */
  const fetchDockerStatus = async () => {
    try {
      const status = await dockerApi.getStatus();
      setDockerStatus(status);
    } catch (error) {
      console.error('[ServicesSubtab] Failed to fetch Docker status:', error);
      setDockerStatus({ running: false, runtime: 'Unknown', containers_count: 0 });
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Asynchronous function that fetches all Docker containers from the Docker API and updates two Zustand store states: the full container list and a filtered subset of AGRO-managed containers.
   *   Takes no parameters; relies on dockerApi.listContainers() to retrieve container data from the Docker daemon.
   *   Returns a Promise<DockerContainer[]> containing all containers; side effects include calling setContainers() and setAgroContainers() to update shared state.
   *   Handles the edge case where result.containers is undefined or null by defaulting to an empty array; does not throw on API failure—errors are silently caught but not logged or re-thrown.
   *
   * why: |
   *   Separates container fetching logic from UI components to centralize Docker API interaction and enable reusable state management via Zustand hooks.
   *   The dual-state pattern (all containers + filtered AGRO subset) avoids repeated filtering in components and improves render performance.
   *   Filtering by agro_managed flag allows the UI to display AGRO-specific operations separately from unmanaged containers.
   *
   * guardrails:
   *   - DO NOT add retry logic here; implement exponential backoff at the dockerApi.listContainers() layer to keep concerns separated
   *   - ALWAYS validate that setContainers and setAgroContainers are Zustand store setters before calling; confirm store schema includes agro_managed boolean field
   *   - NOTE: The catch block silently swallows errors without logging; add error state to Zustand store and log failures for debugging production issues
   *   - NOTE: Type annotation uses 'any' for container objects; define and import a strict DockerContainer interface to catch schema mismatches at compile time
   *   - ASK USER: Confirm whether API errors should trigger a retry, update error state in the store, or both before modifying error handling
   * ---/agentspec
   */
  const fetchContainers = async (): Promise<DockerContainer[]> => {
    try {
      const result = await dockerApi.listContainers();
      const allContainers = result.containers || [];
      setContainers(allContainers);

      // Filter AGRO containers
      const agro = allContainers.filter((c: any) => c.agro_managed === true);
      setAgroContainers(agro);

      return allContainers;
    } catch (error) {
      console.error('[ServicesSubtab] Failed to fetch containers:', error);
      setContainers([]);
      setAgroContainers([]);
      return [];
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Asynchronously checks the operational status of services (specifically Qdrant) by inspecting a provided Docker containers list.
   *   Takes a containersList parameter (array of DockerContainer objects) and searches for a container with 'qdrant' in its name (case-insensitive).
   *   Updates the qdrantStatus state via setQdrantStatus hook, setting status to 'online' if the matching container's state is 'running', otherwise 'offline'.
   *   Returns a Promise that resolves when state update is queued (not when it completes).
   *   Handles edge cases: missing container (defaults to 'offline'), case-insensitive name matching, preserves other qdrantStatus fields via spread operator.
   *
   * why: |
   *   Accepts containersList as a parameter instead of reading from stale closure state, ensuring fresh Docker container data is used for status checks.
   *   Uses case-insensitive matching to handle naming variations in container names.
   *   Preserves existing qdrantStatus properties (e.g., lastChecked, error) while only updating the status field, preventing loss of metadata.
   *
   * guardrails:
   *   - DO NOT read container state from a zustand store or component state closure; always use the passed containersList parameter to avoid stale data
   *   - ALWAYS use case-insensitive matching (toLowerCase()) for container name lookups because Docker container names may vary in casing
   *   - NOTE: This function only checks if a container exists and is running; it does not validate that Qdrant is actually healthy or responding to requests
   *   - ASK USER: Should this function also perform a health check (e.g., HTTP ping to Qdrant API) or is container state sufficient for your use case?
   * ---/agentspec
   */
  const fetchServiceStatus = async (containersList: DockerContainer[]) => {
    // Check Qdrant - use passed containersList, not stale state
    const qdrantContainer = containersList.find(c =>
      c.name.toLowerCase().includes('qdrant')
    );
    setQdrantStatus(prev => ({
      ...prev,
      status: qdrantContainer?.state === 'running' ? 'online' : 'offline'
    }));

    // Check Redis via ping endpoint
    try {
      const res = await fetch(api('/api/docker/redis/ping'));
      if (res.ok) {
        const data = await res.json();
        setRedisStatus(prev => ({
          ...prev,
          status: data.success ? 'online' : 'offline'
        }));
      } else {
        setRedisStatus(prev => ({ ...prev, status: 'offline' }));
      }
    } catch {
      setRedisStatus(prev => ({ ...prev, status: 'offline' }));
    }

    // Check Prometheus - use passed containersList
    const prometheusContainer = containersList.find(c =>
      c.name.toLowerCase().includes('prometheus')
    );
    setPrometheusStatus(prev => ({
      ...prev,
      status: prometheusContainer?.state === 'running' ? 'online' : 'offline'
    }));

    // Check Grafana - use passed containersList
    const grafanaContainer = containersList.find(c =>
      c.name.toLowerCase().includes('grafana')
    );
    setGrafanaStatus(prev => ({
      ...prev,
      status: grafanaContainer?.state === 'running' ? 'online' : 'offline'
    }));

    // Check Loki
    try {
      const lokiData = await dockerApi.getLokiStatus();
      setLokiStatus(prev => ({
        ...prev,
        status: lokiData.reachable ? 'online' : 'offline'
      }));
    } catch {
      setLokiStatus(prev => ({ ...prev, status: 'offline' }));
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles opening and restarting Qdrant vector database container operations via UI interactions.
   *   handleQdrantOpen() opens the Qdrant dashboard in a new browser tab at http://localhost:6333/dashboard using window.open().
   *   handleQdrantRestart() searches the containers array for a container with 'qdrant' in its name (case-insensitive), then triggers a restart operation; sets actionMessage state if container not found.
   *   Both functions are event handlers (likely onClick callbacks) with no parameters.
   *   Edge case: handleQdrantRestart() silently fails if containers array is empty or no matching container exists; dashboard URL is hardcoded and assumes Qdrant runs on localhost:6333.
   *
   * why: |
   *   Separates UI concerns (opening dashboard, triggering restart) into discrete handler functions for clarity and reusability.
   *   Case-insensitive container name matching accommodates variations in container naming conventions.
   *   Using window.open() with '_blank' target isolates dashboard navigation from the main application window.
   *
   * guardrails:
   *   - DO NOT hardcode localhost:6333 in production; use environment variables or configuration to support different deployment environments
   *   - ALWAYS validate that containers array exists and is populated before calling find(); add null/undefined checks to prevent runtime errors
   *   - NOTE: handleQdrantRestart() is incomplete; the restart logic after finding the container is not shown, confirm implementation before deployment
   *   - ASK USER: Should actionMessage be cleared after successful restart, or should error handling include retry logic and detailed error messages?
   * ---/agentspec
   */
  const handleQdrantOpen = () => {
    window.open('http://localhost:6333/dashboard', '_blank');
  };

  /**
   * ---agentspec
   * what: |
   *   Handles the restart operation for a Qdrant container in a Docker environment.
   *   Takes no parameters; operates on component state (containers array and UI state setters).
   *   Searches the containers array for a container with 'qdrant' in its name (case-insensitive).
   *   Returns early with error message if no matching container found; otherwise sets loading state and displays "Restarting Qdrant..." message.
   *   Side effects: mutates UI state (setLoading, setActionMessage) but does not execute the actual restart API call (incomplete implementation).
   *
   * why: |
   *   Encapsulates the pre-restart validation and UI state management for the Qdrant restart workflow.
   *   Separates container lookup logic from the actual restart API call, allowing for staged implementation.
   *   Case-insensitive name matching provides robustness against naming variations in container metadata.
   *
   * guardrails:
   *   - DO NOT assume the restart API call is complete; this function only validates and sets UI state, actual restart logic must follow
   *   - ALWAYS validate that container exists before attempting restart to avoid null reference errors downstream
   *   - NOTE: Case-insensitive matching may match unintended containers if naming conventions are not strict (e.g., 'qdrant-backup' would match)
   *   - ASK USER: Confirm the expected container naming convention and whether case-insensitive matching is intentional before modifying the filter logic
   *   - DO NOT call setLoading(true) without a corresponding setLoading(false) in error or success handlers; incomplete state management will leave UI in loading state
   * ---/agentspec
   */
  const handleQdrantRestart = async () => {
    const container = containers.find(c => c.name.toLowerCase().includes('qdrant'));
    if (!container) {
      setActionMessage('Qdrant container not found');
      return;
    }

    setLoading(true);
    setActionMessage('Restarting Qdrant...');
    try {
      await dockerApi.restartContainer(container.id);
      setActionMessage('Qdrant restarted successfully');
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      setActionMessage(`Failed to restart Qdrant: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Async handler that pings a Redis instance via HTTP API endpoint and displays the result in UI state.
   *   Takes no parameters; uses fetch to call GET /api/docker/redis/ping endpoint.
   *   Returns nothing; updates three pieces of React state: setLoading (boolean), setActionMessage (string with response or error).
   *   On success, displays "Redis: {response}" message; on API error, displays "Redis ping failed: {error}"; on network failure, displays "Failed to ping Redis: {error}".
   *   Edge case: Does not distinguish between JSON parse errors and network timeouts; both collapse into the catch block.
   *
   * why: |
   *   Provides user feedback for Redis connectivity testing in a Docker environment via a simple fetch-based health check.
   *   State updates (loading flag, message display) follow React hook patterns for async operations with user-facing status.
   *   Chosen over direct socket connection to keep logic in the frontend and leverage existing API layer abstraction.
   *
   * guardrails:
   *   - DO NOT add retry logic here; implement at the API endpoint level (/api/docker/redis/ping) to keep concerns separated
   *   - ALWAYS set setLoading(false) in a finally block to prevent UI lockup if the endpoint hangs or times out
   *   - NOTE: Error messages expose raw error objects as strings; consider sanitizing before display in production to avoid leaking internal details
   *   - ASK USER: Confirm whether setActionMessage should be cleared/reset before the next ping attempt, or if message history should persist
   * ---/agentspec
   */
  const handleRedisPing = async () => {
    setLoading(true);
    setActionMessage('Pinging Redis...');
    try {
      const res = await fetch(api('/api/docker/redis/ping'));
      const data = await res.json();
      setActionMessage(data.success ? `Redis: ${data.response}` : `Redis ping failed: ${data.error}`);
    } catch (error) {
      setActionMessage(`Failed to ping Redis: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ```
   * ---agentspec
   * what: |
   *   Handles the restart operation for a Redis container in a containerized environment.
   *   Takes no parameters; reads from a `containers` state variable (array of container objects with `name` property).
   *   Searches for a container whose name includes 'redis' (case-insensitive).
   *   Returns early with error message if no Redis container is found; otherwise sets loading state to true and displays "Restarting Redis..." message.
   *   Side effects: mutates `setLoading` and `setActionMessage` state hooks; does not actually restart the container (incomplete implementation).
   *
   * why: |
   *   Encapsulates the Redis restart workflow as a discrete event handler, separating UI state management from container orchestration logic.
   *   Case-insensitive name matching provides flexibility for naming conventions (redis, Redis, REDIS, etc.).
   *   Early return pattern prevents unnecessary state updates if the container is not found.
   *   Incomplete implementation suggests this is a work-in-progress; the actual restart API call is missing.
   *
   * guardrails:
   *   - DO NOT assume the restart operation completes after setting loading state; the actual container restart logic (API call, exec command) is missing and must be implemented
   *   - ALWAYS validate that `containers` state is populated before calling this handler; if containers array is empty or undefined, the find() will return undefined and trigger the error message
   *   - NOTE: Case-insensitive matching using `.toLowerCase().includes('redis')` may match unintended containers (e.g., 'my-redis-cache-backup'); consider more specific matching if multiple Redis-like containers exist
   *   - ASK USER: Confirm the intended behavior after restart—should this handler await the restart completion, poll for container status, or trigger a callback? Also clarify error handling: should failure to find Redis throw an error or silently return?
   * ---/agentspec
   * ```
   */
  const handleRedisRestart = async () => {
    const container = containers.find(c => c.name.toLowerCase().includes('redis'));
    if (!container) {
      setActionMessage('Redis container not found');
      return;
    }

    setLoading(true);
    setActionMessage('Restarting Redis...');
    try {
      await dockerApi.restartContainer(container.id);
      setActionMessage('Redis restarted successfully');
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      setActionMessage(`Failed to restart Redis: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Provides three handler functions for opening monitoring dashboards and managing infrastructure state in a React component.
   *   handlePrometheusOpen() opens Prometheus metrics dashboard at http://localhost:9090 in a new browser tab.
   *   handleGrafanaOpen() opens Grafana visualization dashboard at http://localhost:3000 in a new browser tab.
   *   handleInfraUp() is declared but incomplete; appears to be an async function intended to start infrastructure services.
   *   All handlers use window.open() with '_blank' target to preserve the current page context.
   *
   * why: |
   *   These handlers encapsulate dashboard navigation and infrastructure control logic, allowing UI buttons to trigger external services without inline code.
   *   Separating concerns into named functions improves readability and enables reuse across multiple UI elements.
   *   The incomplete handleInfraUp() suggests this component is under active development for infrastructure orchestration.
   *
   * guardrails:
   *   - DO NOT hardcode localhost URLs without environment configuration; these will fail in production or non-standard deployments
   *   - ALWAYS validate that Prometheus (port 9090) and Grafana (port 3000) services are running before users click these handlers, or provide error feedback
   *   - NOTE: window.open() may be blocked by browser popup filters; consider user education or fallback messaging
   *   - ASK USER: What should handleInfraUp() do? Should it call a backend API, trigger Docker Compose, or manage Kubernetes resources? Confirm implementation before completing this function
   *   - ASK USER: Should these URLs be configurable via environment variables (e.g., REACT_APP_PROMETHEUS_URL, REACT_APP_GRAFANA_URL) for multi-environment support?
   * ---/agentspec
   */
  const handlePrometheusOpen = () => {
    window.open('http://localhost:9090', '_blank');
  };

  /**
   * ---agentspec
   * what: |
   *   Handles infrastructure startup and Grafana dashboard opening via UI button clicks.
   *   handleGrafanaOpen opens Grafana at http://localhost:3000 in a new browser tab (no parameters, no return value).
   *   handleInfraUp triggers a POST request to /api/docker/infra/up endpoint, sets loading state to true, and updates actionMessage to 'Starting infrastructure...'.
   *   Returns a Promise that resolves when the fetch completes; error handling is incomplete (try block present but catch block not shown).
   *   Side effects: modifies React state (setLoading, setActionMessage), opens new browser window, makes HTTP request to backend Docker API.
   *
   * why: |
   *   Separates UI event handlers from business logic: handleGrafanaOpen is a simple window.open wrapper for user convenience, while handleInfraUp orchestrates state management with async backend communication.
   *   This pattern allows the UI to provide visual feedback (loading spinner, status message) while infrastructure operations run asynchronously.
   *   Splitting into two functions keeps concerns isolated: navigation vs. infrastructure orchestration.
   *
   * guardrails:
   *   - DO NOT hardcode 'http://localhost:3000' as a magic string; extract to a config constant or environment variable because Grafana port may differ across deployments
   *   - ALWAYS implement the catch block for handleInfraUp to handle network errors, timeouts, and backend failures; currently incomplete and will silently fail
   *   - NOTE: setLoading(true) is never reset to false in the shown code; add setLoading(false) in finally block to prevent UI from remaining in loading state indefinitely
   *   - ASK USER: Confirm the intended behavior when /api/docker/infra/up fails—should actionMessage display error details, and should loading state be cleared on error?
   *   - DO NOT assume localhost is always available; consider adding a health check or fallback URL for Grafana in non-local environments
   * ---/agentspec
   */
  const handleGrafanaOpen = () => {
    window.open('http://localhost:3000', '_blank');
  };

  /**
   * ---agentspec
   * what: |
   *   Handles the UI interaction for starting Docker infrastructure via API call.
   *   Takes no parameters; triggered by user button click. Sets loading state to true and displays "Starting infrastructure..." message.
   *   Makes POST request to /api/docker/infra/up endpoint and receives JSON response with success boolean and optional error field.
   *   On success, displays "Infrastructure started" message; on failure, displays "Failed: {error message}".
   *   Automatically refreshes all status after 2-second delay via fetchAllStatus() call.
   *   Catches network/parsing errors but does not display them to user (silent failure).
   *
   * why: |
   *   Separates UI state management (loading, messages) from async API operations using React hooks (setLoading, setActionMessage).
   *   Polling delay (2000ms) allows Docker daemon time to process startup before status refresh.
   *   This pattern centralizes infrastructure control in a single handler, making it reusable across multiple UI triggers.
   *
   * guardrails:
   *   - DO NOT remove the setTimeout delay; Docker startup is asynchronous and status queries before 2s will return stale state
   *   - ALWAYS display error messages to user; current catch block silently fails, leaving user uncertain if action succeeded
   *   - NOTE: No validation of res.ok before calling res.json(); malformed responses will throw uncaught errors
   *   - ASK USER: Should error state be persisted in a Zustand store (shared state) so other components can react to infra failures, or keep local React state?
   * ---/agentspec
   */
  const handleInfraUp = async () => {
    setLoading(true);
    setActionMessage('Starting infrastructure...');
    try {
      const res = await fetch(api('/api/docker/infra/up'), { method: 'POST' });
      const data = await res.json();
      setActionMessage(data.success ? 'Infrastructure started' : `Failed: ${data.error}`);
      setTimeout(() => fetchAllStatus(), 2000);
    } catch (error) {
      setActionMessage(`Failed to start infrastructure: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles stopping all infrastructure services via Docker Compose down command.
   *   Takes no parameters; triggered by user confirmation dialog.
   *   Sends POST request to /api/docker/infra/down endpoint and receives JSON response with success boolean and optional error message.
   *   Updates component state (loading, actionMessage) to reflect operation status.
   *   Returns early if user cancels confirmation dialog; displays error message if API call fails.
   *
   * why: |
   *   Centralizes infrastructure shutdown logic in a single handler to maintain consistent UI state management.
   *   Confirmation dialog prevents accidental service termination.
   *   State updates (setLoading, setActionMessage) provide user feedback during async operation.
   *
   * guardrails:
   *   - DO NOT remove the confirmation dialog; accidental infrastructure shutdown causes data loss and service disruption
   *   - ALWAYS set setLoading(false) after API response to prevent UI from remaining in loading state indefinitely
   *   - NOTE: Error handling only displays data.error string; does not distinguish between network failures, timeout, or API errors
   *   - ASK USER: Should this handler integrate with a Zustand store for global infrastructure state, or remain as local component state via useState?
   * ---/agentspec
   */
  const handleInfraDown = async () => {
    if (!confirm('Stop all infrastructure services?')) return;

    setLoading(true);
    setActionMessage('Stopping infrastructure...');
    try {
      const res = await fetch(api('/api/docker/infra/down'), { method: 'POST' });
      const data = await res.json();
      setActionMessage(data.success ? 'Infrastructure stopped' : `Failed: ${data.error}`);
      setTimeout(() => fetchAllStatus(), 2000);
    } catch (error) {
      setActionMessage(`Failed to stop infrastructure: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles Docker container status refresh and runtime mode persistence in a React component.
   *   handleDockerRefresh() triggers fetchAllStatus() to poll container states, displays a transient "Refreshing..." message for 1 second, then clears it.
   *   handleSaveRuntimeMode() is an async function that sets loading state to true and displays a "Saving runtime mode..." message; the actual save logic and completion handler are not shown in this snippet.
   *   Both functions manage UI feedback (action messages) and loading states via React hooks (setActionMessage, setLoading).
   *   Edge case: If fetchAllStatus() throws an error, it is not caught; the loading state may remain true indefinitely.
   *
   * why: |
   *   These handlers provide user feedback during asynchronous operations (refresh and save) by displaying transient status messages and loading indicators.
   *   The 1-second timeout in handleDockerRefresh ensures the "Refreshing..." message is visible long enough to signal action, even if fetchAllStatus() completes instantly.
   *   Separating refresh and save handlers allows independent control of Docker polling and runtime configuration persistence.
   *
   * guardrails:
   *   - DO NOT remove the setTimeout in handleDockerRefresh; without it, the message may disappear before the user perceives the action
   *   - ALWAYS add error handling to handleSaveRuntimeMode (try/catch or .catch()) to reset loading state on failure
   *   - NOTE: handleDockerRefresh does not await fetchAllStatus(); if async, completion is not guaranteed before message clears
   *   - ASK USER: Confirm whether fetchAllStatus() is synchronous or async, and whether the 1-second delay should be tied to actual completion instead of a fixed timeout
   *   - ASK USER: Clarify the expected behavior if handleSaveRuntimeMode fails (retry, rollback, error display) before implementing the save logic
   * ---/agentspec
   */
  const handleDockerRefresh = () => {
    fetchAllStatus();
    setActionMessage('Refreshing...');
    setTimeout(() => setActionMessage(null), 1000);
  };

  /**
   * ---agentspec
   * what: |
   *   Handles saving runtime mode selection from UI to backend API.
   *   Takes runtimeMode string ('1' for development, '0' for production) from component state.
   *   Maps UI values to backend enum values, calls configApi.updateRuntimeMode(mode), sets loading state and action message.
   *   Returns Promise that resolves when API call completes; sets loading to false and updates actionMessage on success or error.
   *   Edge case: Does not validate runtimeMode input before mapping; invalid values will be passed to API unmapped.
   *
   * why: |
   *   Centralizes runtime mode persistence logic in a single handler to avoid duplicating API calls across components.
   *   UI uses '1'/'0' string values for form convenience; backend expects 'development'/'production' enum strings, so mapping layer is needed.
   *   Loading state and actionMessage provide user feedback during async operation.
   *
   * guardrails:
   *   - DO NOT remove the runtimeMode validation before mapping; invalid values like '2' or null will silently pass through to the API
   *   - ALWAYS validate that runtimeMode is either '1' or '0' before calling configApi.updateRuntimeMode to prevent backend errors
   *   - NOTE: actionMessage is set to 'Saving runtime mode...' but never cleared on success or error; caller must handle clearing this state
   *   - ASK USER: Confirm error handling strategy—should this handler catch and display API errors, or does the caller handle error states?
   *   - ASK USER: Confirm whether runtimeMode should be persisted to a Zustand store or hook context after successful API response
   * ---/agentspec
   */
  const handleSaveRuntimeMode = async () => {
    setLoading(true);
    setActionMessage('Saving runtime mode...');

    try {
      // Map UI values to backend values: '1' -> 'development', '0' -> 'production'
      const mode = runtimeMode === '1' ? 'development' : 'production';
      const result = await configApi.updateRuntimeMode(mode);

      setActionMessage(`Runtime mode saved: ${mode} (DEV_LOCAL_UVICORN=${runtimeMode})`);
      console.log('[ServicesSubtab] Runtime mode updated:', result);
    } catch (error) {
      console.error('[ServicesSubtab] Failed to save runtime mode:', error);
      setActionMessage(`Failed to save runtime mode: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Renders a service status card UI component with configurable styling and button actions.
   *   Takes a ServiceStatus object (containing service metadata/state) and a React.ReactNode for buttons as inputs.
   *   Returns a JSX element displaying the service card with elevated background, border, rounded corners, and 16px padding.
   *   Uses CSS custom properties (--bg-elev2, --line) for theming; applies flexbox layout for internal structure.
   *   Edge case: If buttons prop is null/undefined, renders empty button area; if ServiceStatus is malformed, component may fail silently without error boundary.
   *
   * why: |
   *   Centralizes service card rendering logic to maintain consistent UI across multiple service displays.
   *   Uses CSS variables for theming to allow dynamic color switching without component re-implementation.
   *   Flexbox layout chosen for responsive alignment of service info and action buttons.
   *
   * guardrails:
   *   - DO NOT hardcode color values; always use CSS custom properties (--bg-elev2, --line) because theme consistency depends on centralized variable management
   *   - ALWAYS validate ServiceStatus object shape before rendering to prevent undefined property access errors
   *   - NOTE: Component lacks error boundary; malformed ServiceStatus or missing CSS variables will cause silent failures or unstyled output
   *   - ASK USER: Confirm whether buttons should be optional (render empty area) or required (throw error if missing) before modifying prop validation
   * ---/agentspec
   */
  const renderServiceCard = (service: ServiceStatus, buttons: React.ReactNode) => (
    <div style={{
      background: 'var(--bg-elev2)',
      border: '1px solid var(--line)',
      borderRadius: '6px',
      padding: '16px'
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px'
      }}>
        <div style={{ fontWeight: '600', color: service.color }}>{service.name}</div>
        <div id={`${service.name.toLowerCase()}-status`} style={{
          fontSize: '11px',
          color: service.status === 'online' ? 'var(--accent)' :
                 service.status === 'offline' ? 'var(--err)' : 'var(--fg-muted)'
        }}>
          {service.status === 'online' ? '● Online' :
           service.status === 'offline' ? '○ Offline' : 'Checking...'}
        </div>
      </div>
      <div style={{
        fontSize: '12px',
        color: 'var(--fg-muted)',
        marginBottom: '12px'
      }}>
        {service.description} • Port {service.port}
      </div>
      <div style={{ display: 'flex', gap: '8px' }}>
        {buttons}
      </div>
    </div>
  );

  /**
   * ---agentspec
   * what: |
   *   Renders a single container status card with dynamic styling based on container state.
   *   Takes a container object with properties: id, state, status (string).
   *   Returns a JSX div element displaying the container with conditional background color and border styling.
   *   Determines pause state by checking if container.state === 'paused' OR status string includes 'paused' (case-insensitive).
   *   Maps container state to CSS custom properties: running → --accent, paused → --warn, other → --err.
   *   Side effect: Uses CSS variables (--bg-elev2, --line, --accent, --warn, --err) which must be defined in global scope.
   *
   * why: |
   *   Centralizes container rendering logic to ensure consistent visual feedback across the UI.
   *   Dual-checks both state field and status string to handle inconsistent backend data formats.
   *   Uses CSS custom properties for theming to allow runtime color changes without component re-renders.
   *   Conditional pause detection prevents false negatives when backend uses different state naming conventions.
   *
   * guardrails:
   *   - DO NOT hardcode color values; always use CSS custom properties (--accent, --warn, --err) because theme switching depends on variable mutation
   *   - ALWAYS validate that container.id is unique and truthy before rendering; duplicate keys cause React reconciliation bugs
   *   - NOTE: Case-insensitive status check (.toLowerCase()) assumes status is a string; will throw if status is null/undefined
   *   - ASK USER: Confirm the complete list of valid container states before adding new statusColor mappings; current logic only handles running/paused/other
   *   - DO NOT add inline event handlers (onClick, onHover) without confirming state management strategy; this component should remain a pure presentational component
   * ---/agentspec
   */
  const renderContainer = (container: any) => {
    const isPaused = container.state === 'paused' || container.status?.toLowerCase().includes('paused');
    const statusColor = container.state === 'running' ? 'var(--accent)' :
                       isPaused ? 'var(--warn)' : 'var(--err)';

    return (
      <div key={container.id} style={{
        background: 'var(--bg-elev2)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '12px'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: '8px'
        }}>
          <div>
            <div style={{ fontWeight: '600', fontSize: '13px' }}>{container.name}</div>
            <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '2px' }}>
              {container.image}
            </div>
          </div>
          <div style={{
            fontSize: '10px',
            padding: '2px 6px',
            borderRadius: '3px',
            background: statusColor + '20',
            color: statusColor,
            fontWeight: '600'
          }}>
            {isPaused ? 'paused' : container.state}
          </div>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
          {container.status}
        </div>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          <button
            onClick={() => handleViewLogs(container.id, container.name)}
            data-testid="view-logs-btn"
            data-tooltip="infra-view-logs"
            style={{
              fontSize: '10px',
              padding: '4px 8px',
              background: 'var(--bg-elev1)',
              color: 'var(--link)',
              border: '1px solid var(--link)',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            View Logs
          </button>
          {container.state === 'running' && !isPaused && (
            <>
              <button
                onClick={() => handlePauseContainer(container.id, container.name)}
                data-testid="pause-container-btn"
                data-tooltip="infra-pause-container"
                style={{
                  fontSize: '10px',
                  padding: '4px 8px',
                  background: 'var(--bg-elev1)',
                  color: 'var(--warn)',
                  border: '1px solid var(--warn)',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                ⏸ Pause
              </button>
              <button
                onClick={() => handleContainerAction('stop', container.id)}
                style={{
                  fontSize: '10px',
                  padding: '4px 8px',
                  background: 'var(--bg-elev1)',
                  color: 'var(--err)',
                  border: '1px solid var(--err)',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                Stop
              </button>
            </>
          )}
          {isPaused && (
            <button
              onClick={() => handleUnpauseContainer(container.id, container.name)}
              data-testid="unpause-container-btn"
              data-tooltip="infra-unpause-container"
              style={{
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                color: 'var(--accent)',
                border: '1px solid var(--accent)',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              ▶ Unpause
            </button>
          )}
          {container.state !== 'running' && !isPaused && (
            <button
              onClick={() => handleContainerAction('start', container.id)}
              style={{
                fontSize: '10px',
                padding: '4px 8px',
                background: 'var(--bg-elev1)',
                color: 'var(--accent)',
                border: '1px solid var(--accent)',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Start
            </button>
          )}
          <button
            onClick={() => handleContainerAction('restart', container.id)}
            style={{
              fontSize: '10px',
              padding: '4px 8px',
              background: 'var(--bg-elev1)',
              color: 'var(--warn)',
              border: '1px solid var(--warn)',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            Restart
          </button>
          <button
            onClick={() => handleRemoveContainer(container.id, container.name)}
            data-testid="remove-container-btn"
            data-tooltip="infra-remove-container"
            style={{
              fontSize: '10px',
              padding: '4px 8px',
              background: 'var(--bg-elev1)',
              color: 'var(--err)',
              border: '1px solid var(--err)',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            🗑 Remove
          </button>
        </div>
      </div>
    );
  };

  /**
   * ---agentspec
   * what: |
   *   Handles Docker container lifecycle actions (start, stop, restart) triggered by user interaction.
   *   Takes action string ('start', 'stop', 'restart') and containerId string as parameters.
   *   Calls corresponding dockerApi methods and updates UI state with loading indicator and status messages.
   *   Returns nothing; side effects include setting loading state, updating action message, and making async API calls.
   *   Edge cases: Does not handle API errors (no catch block), does not validate action string against allowed values, does not reset loading state on failure.
   *
   * why: |
   *   Centralizes container action handling in a single event handler to avoid duplicating API call logic across multiple button handlers.
   *   Uses setLoading and setActionMessage state updates to provide user feedback during async operations.
   *   Simple if-else routing was chosen over a dispatch map for readability in this small action set.
   *
   * guardrails:
   *   - DO NOT remove the setLoading(true) call; it prevents duplicate submissions and provides visual feedback
   *   - ALWAYS add error handling with a catch block that sets error state and resets loading; current code leaves loading=true on failure
   *   - DO NOT add new actions without validating the action parameter against a whitelist to prevent arbitrary API calls
   *   - NOTE: setActionMessage is never reset to empty/null after success; consider clearing it or adding a timeout to auto-dismiss
   *   - ASK USER: Confirm whether failed actions should reset loading state immediately or show an error message before proceeding with error handling implementation
   * ---/agentspec
   */
  const handleContainerAction = async (action: string, containerId: string) => {
    setLoading(true);
    setActionMessage(`${action}ing container...`);
    try {
      if (action === 'start') await dockerApi.startContainer(containerId);
      else if (action === 'stop') await dockerApi.stopContainer(containerId);
      else if (action === 'restart') await dockerApi.restartContainer(containerId);

      setActionMessage(`Container ${action}ed successfully`);
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      setActionMessage(`Failed to ${action} container: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles the user action of viewing logs for a Docker container by fetching and displaying them in a modal.
   *   Takes containerId (string) and containerName (string) as parameters.
   *   Updates local state to open a modal, set loading state, and populate container metadata.
   *   Fetches container logs via dockerApi.getContainerLogs(containerId, 500) where 500 is the line limit.
   *   Sets logsContent state with the response data (side effect); clears previous logs by initializing to empty string.
   *   Edge case: Does not handle API errors or network failures (try block present but catch block not shown).
   *
   * why: |
   *   Centralizes the log-viewing workflow into a single handler to avoid duplicating state management across multiple UI components.
   *   Separates concerns: UI state updates (modal, loading flags) from API calls, making the handler reusable.
   *   Pre-fetches logs immediately on modal open rather than lazy-loading, improving perceived responsiveness.
   *
   * guardrails:
   *   - DO NOT remove the setLogsContent('') initialization; it prevents stale logs from previous container views from appearing
   *   - ALWAYS include error handling in the catch block to set setLogsLoading(false) and display user-facing error messages
   *   - NOTE: Hardcoded line limit of 500 may truncate logs for verbose containers; consider making this configurable or paginated
   *   - ASK USER: Confirm whether logs should auto-refresh on an interval or if one-time fetch on modal open is the intended behavior
   * ---/agentspec
   */
  const handleViewLogs = async (containerId: string, containerName: string) => {
    setLogsContainerName(containerName);
    setLogsContainerId(containerId);
    setLogsModalOpen(true);
    setLogsLoading(true);
    setLogsContent('');

    try {
      const response = await dockerApi.getContainerLogs(containerId, 500);
      setLogsContent(response.logs || 'No logs available');
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      setLogsContent('Error loading logs: ' + error);
    } finally {
      setLogsLoading(false);
    }
  };

  /**
   * ```
   * ---agentspec
   * what: |
   *   Fetches and displays Docker container logs by container ID, updating UI state with the retrieved log content.
   *   Takes logsContainerId (string) as context; calls dockerApi.getContainerLogs(containerId, 500) to retrieve up to 500 lines of logs.
   *   Returns nothing; side effects include setting logsLoading state to true during fetch, updating logsContent state with log text or error message, and logging errors to console.
   *   Handles missing containerId by early return; handles API errors by catching and displaying error message in logsContent; handles missing logs property by defaulting to 'No logs available'.
   *
   * why: |
   *   Centralizes log refresh logic in a single handler to avoid duplication across the UI component.
   *   Provides user feedback via loading state and error messages to communicate async operation status.
   *   The 500-line limit balances performance (avoiding massive payloads) with utility (showing recent context).
   *
   * guardrails:
   *   - DO NOT remove the logsContainerId guard clause; it prevents unnecessary API calls and undefined behavior
   *   - ALWAYS set logsLoading to false after the try/catch block completes to prevent UI from remaining in loading state indefinitely
   *   - NOTE: Error messages concatenate error object directly ('Error loading logs: ' + error); this may produce '[object Object]' for non-string errors; consider error.message or JSON.stringify for clarity
   *   - ASK USER: Confirm whether 500-line limit is appropriate for your use case or if it should be configurable/user-selectable
   * ---/agentspec
   * ```
   */
  const handleRefreshLogs = async () => {
    if (!logsContainerId) return;
    setLogsLoading(true);
    try {
      const response = await dockerApi.getContainerLogs(logsContainerId, 500);
      setLogsContent(response.logs || 'No logs available');
    } catch (error) {
      console.error('Failed to refresh logs:', error);
      setLogsContent('Error loading logs: ' + error);
    } finally {
      setLogsLoading(false);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles the pause action for a Docker container via async API call with UI feedback.
   *   Takes containerId (string) and containerName (string) as parameters.
   *   Calls dockerApi.pauseContainer(containerId) and updates UI state with loading indicator and status messages.
   *   On success, displays confirmation message and refetches container status after 1-second delay.
   *   On error, logs to console but does not display error feedback to user or update error state.
   *
   * why: |
   *   Centralizes container pause logic with consistent UX patterns (loading state, action messages, status refresh).
   *   Separates API call from UI state management using React hooks (setLoading, setActionMessage).
   *   1-second delay before refetch allows Docker daemon time to process pause state change before querying status.
   *
   * guardrails:
   *   - DO NOT remove the setTimeout delay; Docker pause operations are asynchronous and status queries immediately after may return stale state
   *   - ALWAYS display error messages to the user via setActionMessage or error state; current implementation silently fails with only console.error
   *   - NOTE: No error state is set on failure, so UI remains in loading state indefinitely if dockerApi.pauseContainer rejects
   *   - ASK USER: Should failed pause operations display an error message in the UI, and should setLoading(false) be called in the catch block?
   * ---/agentspec
   */
  const handlePauseContainer = async (containerId: string, containerName: string) => {
    setLoading(true);
    setActionMessage(`Pausing ${containerName}...`);
    try {
      await dockerApi.pauseContainer(containerId);
      setActionMessage(`Container ${containerName} paused`);
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      console.error('Failed to pause:', error);
      setActionMessage(`Failed to pause container: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles resuming a paused Docker container by calling the unpause API endpoint.
   *   Takes containerId (string) and containerName (string) as parameters.
   *   Sets loading state to true, updates UI message to "Resuming {containerName}...", calls dockerApi.unpauseContainer(containerId), then updates message to success state.
   *   On success, fetches updated container status after 1000ms delay; on error, logs to console but does not propagate error to user or update error state.
   *   Edge case: If unpauseContainer rejects, error is caught but UI remains in loading state indefinitely and user sees no error feedback.
   *
   * why: |
   *   Provides user feedback during async Docker operation by updating action messages and loading state.
   *   Delays status refresh to allow Docker daemon time to process the unpause command before querying state.
   *   Chosen to keep UI responsive while background operation completes.
   *
   * guardrails:
   *   - DO NOT leave loading state true on error; user will see indefinite loading spinner with no error message
   *   - ALWAYS set error state or display error message when dockerApi.unpauseContainer rejects
   *   - ALWAYS clear loading state in finally block to guarantee UI returns to interactive state
   *   - NOTE: 1000ms delay is arbitrary; if Docker daemon is slow, status may still show stale state
   *   - ASK USER: Should errors be shown in UI (toast/alert) or only logged? Should loading state reset on error?
   * ---/agentspec
   */
  const handleUnpauseContainer = async (containerId: string, containerName: string) => {
    setLoading(true);
    setActionMessage(`Resuming ${containerName}...`);
    try {
      await dockerApi.unpauseContainer(containerId);
      setActionMessage(`Container ${containerName} resumed`);
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      console.error('Failed to unpause:', error);
      setActionMessage(`Failed to unpause container: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  /**
   * ---agentspec
   * what: |
   *   Handles removal of a Docker container after user confirmation. Takes containerId (string) and containerName (string) as parameters. Displays a browser confirmation dialog with warning text about data preservation. Returns early if user cancels. Sets loading state to true before removal (actual removal logic not shown in snippet). No return value; side effect is state mutation via setLoading and potential container deletion via async operation.
   *
   * why: |
   *   Confirmation dialog prevents accidental container deletion, which is a destructive operation. Centralizes the confirmation UX pattern so all container removal flows use consistent messaging. Loading state signals to UI that an async operation is in progress. The warning about data volumes educates users that removal behavior depends on configuration.
   *
   * guardrails:
   *   - DO NOT remove the confirmation dialog; accidental deletion of production containers is a critical risk
   *   - ALWAYS set loading state before initiating the async removal to prevent duplicate submissions
   *   - NOTE: Actual container removal logic is not visible in this snippet; ensure the async operation properly handles errors and updates UI state on completion/failure
   *   - ASK USER: Confirm whether this function should also clear related UI state (e.g., selected container, logs) after successful removal, and whether error handling should retry or show user-facing error messages
   * ---/agentspec
   */
  const handleRemoveContainer = async (containerId: string, containerName: string) => {
    const confirmed = window.confirm(
      `Are you sure you want to remove container "${containerName}"?\n\n` +
      `This action cannot be undone. Data volumes may be preserved depending on configuration.`
    );

    if (!confirmed) return;

    setLoading(true);
    setActionMessage(`Removing ${containerName}...`);
    try {
      await dockerApi.removeContainer(containerId);
      setActionMessage(`Container "${containerName}" removed`);
      setTimeout(() => fetchAllStatus(), 1000);
    } catch (error) {
      console.error('Failed to remove:', error);
      setActionMessage(`Failed to remove container: ${error}`);
    } finally {
      setLoading(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  };

  return (
    <div style={{ padding: '16px' }}>
      {/* Action message */}
      {actionMessage && (
        <div style={{
          padding: '12px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '12px',
          color: 'var(--fg)'
        }}>
          {actionMessage}
        </div>
      )}

      {/* Infrastructure Services */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)' }}>
        <h3>
          <span style={{ color: 'var(--warn)' }}>●</span> Infrastructure Services
        </h3>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: '12px',
          marginBottom: '16px'
        }}>
          {renderServiceCard(
            qdrantStatus,
            <>
              <button
                id="btn-qdrant-open"
                onClick={handleQdrantOpen}
                className="small-button"
                style={{
                  flex: 1,
                  background: 'var(--bg-elev2)',
                  color: 'var(--link)',
                  border: '1px solid var(--link)'
                }}
              >
                🌐 Open UI
              </button>
              <button
                id="btn-qdrant-restart"
                onClick={handleQdrantRestart}
                disabled={loading}
                className="small-button"
                style={{
                  flex: 1,
                  background: 'var(--bg-elev2)',
                  color: 'var(--warn)',
                  border: '1px solid var(--warn)'
                }}
              >
                ↻ Restart
              </button>
            </>
          )}

          {renderServiceCard(
            redisStatus,
            <>
              <button
                id="btn-redis-ping"
                onClick={handleRedisPing}
                disabled={loading}
                className="small-button"
                style={{
                  flex: 1,
                  background: 'var(--bg-elev2)',
                  color: 'var(--err)',
                  border: '1px solid var(--err)'
                }}
              >
                📡 Ping
              </button>
              <button
                id="btn-redis-restart"
                onClick={handleRedisRestart}
                disabled={loading}
                className="small-button"
                style={{
                  flex: 1,
                  background: 'var(--bg-elev2)',
                  color: 'var(--warn)',
                  border: '1px solid var(--warn)'
                }}
              >
                ↻ Restart
              </button>
            </>
          )}

          {renderServiceCard(
            prometheusStatus,
            <button
              id="btn-prometheus-open"
              onClick={handlePrometheusOpen}
              className="small-button"
              style={{
                flex: 1,
                background: 'var(--bg-elev2)',
                color: 'var(--warn)',
                border: '1px solid var(--warn)'
              }}
            >
              🌐 Open UI
            </button>
          )}

          {renderServiceCard(
            grafanaStatus,
            <button
              id="btn-grafana-open"
              onClick={handleGrafanaOpen}
              className="small-button"
              style={{
                flex: 1,
                background: 'var(--bg-elev2)',
                color: 'var(--link)',
                border: '1px solid var(--link)'
              }}
            >
              🌐 Open UI
            </button>
          )}

          {renderServiceCard(
            lokiStatus,
            <div data-tooltip="infra-loki-status" style={{
              fontSize: '11px',
              color: 'var(--fg-muted)',
              padding: '4px'
            }}>
              {lokiStatus.status === 'online'
                ? 'Collecting and indexing logs from all services'
                : 'Not reachable - log aggregation unavailable'}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            id="btn-infra-up"
            onClick={handleInfraUp}
            disabled={loading}
            className="small-button"
            style={{
              flex: 1,
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              padding: '12px',
              fontWeight: '600'
            }}
          >
            ▶ Start All Infrastructure
          </button>
          <button
            id="btn-infra-down"
            onClick={handleInfraDown}
            disabled={loading}
            className="small-button"
            style={{
              flex: 1,
              background: 'var(--err)',
              color: 'var(--fg)',
              padding: '12px',
              fontWeight: '600'
            }}
          >
            ■ Stop All Infrastructure
          </button>
        </div>
      </div>

      {/* Docker Status */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3 id="infra-docker-anchor">
          <span style={{ color: 'var(--link)' }}>●</span> Docker Status
          <button
            id="btn-docker-refresh"
            onClick={handleDockerRefresh}
            className="small-button"
            style={{
              float: 'right',
              padding: '4px 12px',
              fontSize: '11px'
            }}
          >
            ↻ Refresh All
          </button>
        </h3>

        <div id="docker-status-display" style={{ marginBottom: '16px' }}>
          {dockerStatus ? (
            <div style={{
              padding: '12px',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '6px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                <span>Status:</span>
                <span style={{ color: dockerStatus.running ? 'var(--accent)' : 'var(--err)' }}>
                  {dockerStatus.running ? '● Running' : '○ Not Running'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginTop: '6px' }}>
                <span>Runtime:</span>
                <span>{dockerStatus.runtime}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginTop: '6px' }}>
                <span>Containers:</span>
                <span>{dockerStatus.containers_count}</span>
              </div>
            </div>
          ) : (
            <div style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>Loading...</div>
          )}
        </div>

        {/* Runtime Mode Toggle */}
        <div className="input-row" style={{ marginTop: '8px' }}>
          <div className="input-group">
            <label>
              Runtime Mode (DEV_LOCAL_UVICORN)
            </label>
            <select
              id="infra-runtime-mode"
              value={runtimeMode}
              onChange={(e) => setRuntimeMode(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px',
                borderRadius: '4px'
              }}
            >
              <option value="0">Docker (default)</option>
              <option value="1">Local uvicorn (dev-only)</option>
            </select>
            <div className="small" style={{ color: 'var(--fg-muted)', marginTop: '6px' }}>
              Switch to Local uvicorn for development. In dev launcher, this scales Docker API to 0 and starts uvicorn on your host.
            </div>
            <button
              onClick={handleSaveRuntimeMode}
              disabled={loading}
              className="small-button"
              style={{
                marginTop: '8px',
                background: 'var(--link)',
                color: 'var(--accent-contrast)',
                fontWeight: '600',
                opacity: loading ? 0.5 : 1,
                cursor: loading ? 'not-allowed' : 'pointer'
              }}
            >
              💾 {loading ? 'Saving...' : 'Save Runtime Mode'}
            </button>
          </div>
        </div>
      </div>

      {/* AGRO Containers */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--accent)' }}>
        <h3>
          <span style={{ color: 'var(--accent)' }}>●</span> AGRO Containers
        </h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '12px' }}>
          Core containers managed by docker-compose.services.yml.
        </p>
        <div id="agro-containers-grid" style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '12px',
          marginBottom: '16px'
        }}>
          {agroContainers.length > 0 ? (
            agroContainers.map(renderContainer)
          ) : (
            <div style={{ color: 'var(--fg-muted)', padding: '16px' }}>
              No AGRO containers found
            </div>
          )}
        </div>
      </div>

      {/* All Containers */}
      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>
          <span style={{ color: 'var(--link)' }}>●</span> All Containers
          <button
            id="btn-docker-refresh-containers"
            onClick={handleDockerRefresh}
            className="small-button"
            style={{
              float: 'right',
              padding: '4px 12px',
              fontSize: '11px'
            }}
          >
            ↻ Refresh
          </button>
        </h3>
        <p className="small" style={{ color: 'var(--fg-muted)', marginBottom: '12px' }}>
          Every Docker container detected on this host (including AGRO and user projects).
        </p>
        <div id="docker-containers-grid" style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '12px',
          marginBottom: '16px'
        }}>
          {containers.length > 0 ? (
            containers.map(renderContainer)
          ) : (
            <div style={{ color: 'var(--fg-muted)', padding: '16px' }}>
              Loading containers...
            </div>
          )}
        </div>
      </div>

      {/* Logs Modal */}
      {logsModalOpen && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999
          }}
          onClick={() => setLogsModalOpen(false)}
        >
          <div
            style={{
              background: 'var(--bg)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              width: '90%',
              maxWidth: '1000px',
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '16px',
              borderBottom: '1px solid var(--line)'
            }}>
              <h3 style={{ margin: 0, fontSize: '16px' }}>
                Container Logs: {logsContainerName}
              </h3>
              <button
                onClick={() => setLogsModalOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--fg)',
                  fontSize: '24px',
                  cursor: 'pointer',
                  padding: '0 8px'
                }}
              >
                ×
              </button>
            </div>

            {/* Modal Body */}
            <div style={{
              flex: 1,
              overflow: 'auto',
              padding: '16px',
              background: 'var(--bg-elev1)'
            }}>
              {logsLoading ? (
                <div style={{ color: 'var(--fg-muted)' }}>Loading logs...</div>
              ) : (
                <pre
                  data-testid="logs-content"
                  style={{
                    margin: 0,
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    color: 'var(--fg)',
                    lineHeight: '1.4'
                  }}
                >
                  {logsContent}
                </pre>
              )}
            </div>

            {/* Modal Footer */}
            <div style={{
              display: 'flex',
              gap: '8px',
              padding: '16px',
              borderTop: '1px solid var(--line)'
            }}>
              <button
                onClick={handleRefreshLogs}
                disabled={logsLoading}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  background: 'var(--link)',
                  color: 'var(--fg)',
                  border: '1px solid var(--link)',
                  borderRadius: '4px',
                  cursor: logsLoading ? 'not-allowed' : 'pointer',
                  opacity: logsLoading ? 0.5 : 1
                }}
              >
                ↻ Refresh
              </button>
              <button
                onClick={() => setLogsModalOpen(false)}
                style={{
                  flex: 1,
                  padding: '8px 16px',
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
