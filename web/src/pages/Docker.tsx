// AGRO - Docker Page
// Simple wrapper for Docker status and container management

import { DockerStatusCard } from '@/components/DockerStatusCard';
import { useDockerStore } from '@/stores';
import { useEffect } from 'react';

export default function Docker() {
  const { status, loading, error, fetchStatus } = useDockerStore();

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--fg)', marginBottom: '8px' }}>
          Docker Containers
        </h2>
        <p style={{ color: 'var(--fg-muted)', fontSize: '14px' }}>
          Monitor and manage Docker infrastructure
        </p>
      </div>

      <DockerStatusCard
        status={status}
        loading={loading}
        error={error}
        onRefresh={fetchStatus}
      />
    </div>
  );
}

