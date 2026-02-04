// TriBridRAG - React Router Configuration
// Converted from legacy navigation.js TAB_REGISTRY and NEW_TABS

import { ReactNode, ComponentType } from 'react';
import { Dashboard } from '../pages/Dashboard';
import Docker from '../pages/Docker';
// Tab components (all TypeScript)
import ChatTab from '../components/tabs/ChatTab';
import GrafanaTab from '../components/tabs/GrafanaTab';
import RAGTab from '../components/tabs/RAGTab';
import EvalAnalysisTab from '../components/tabs/EvalAnalysisTab';
import BenchmarkTab from '../components/Benchmark/BenchmarkTab';
// ProfilesTab removed - banned feature per CLAUDE.md
import InfrastructureTab from '../components/tabs/InfrastructureTab';
import AdminTab from '../components/tabs/AdminTab';
import StartTab from '../components/tabs/StartTab';

export interface Subtab {
  id: string;
  title: string;
}

export interface RouteConfig {
  path: string;
  element: ComponentType<any> | ReactNode;
  label: string;
  icon: string;
  order: number;
  subtabs?: Subtab[];
  nav?: {
    /** If false, route is not rendered in the TabBar. */
    visible?: boolean;
    /** Optional extra class for TabBar styling (e.g. promoted/keystone). */
    className?: string;
    /** Optional tooltip/title for the TabBar link. */
    title?: string;
  };
}

// Main route configuration - converted from NEW_TABS in navigation.js
export const routes: RouteConfig[] = [
  {
    path: '/start',
    element: StartTab,
    label: 'Get Started',
    icon: '🚀',
    order: 1,
    subtabs: [],
    nav: { visible: true }
  },
  {
    path: '/dashboard',
    element: Dashboard,
    label: 'Dashboard',
    icon: '📊',
    order: 2,
    subtabs: [
      { id: 'system', title: 'System Status' },
      { id: 'monitoring', title: 'Monitoring' },
      { id: 'storage', title: 'Storage' },
      { id: 'help', title: 'Help' },
      { id: 'glossary', title: 'Glossary' }
    ],
    nav: { visible: true }
  },
  {
    path: '/chat',
    element: ChatTab,
    label: 'Chat',
    icon: '💬',
    order: 3,
    subtabs: [
      { id: 'ui', title: 'Chat' },
      { id: 'settings', title: 'Settings' }
    ],
    nav: { visible: true }
  },
  {
    path: '/grafana',
    element: GrafanaTab,
    label: 'Grafana',
    icon: '📈',
    order: 4,
    subtabs: [
      { id: 'dashboard', title: 'Dashboard' },
      { id: 'config', title: 'Config' }
    ],
    nav: { visible: true, className: 'promoted-tab' }
  },
  {
    path: '/benchmark',
    element: BenchmarkTab,
    label: 'Benchmark',
    icon: '🏁',
    order: 5,
    subtabs: [],
    nav: { visible: true }
  },
  {
    path: '/rag',
    element: RAGTab,
    label: 'RAG',
    icon: '🧠',
    order: 6,
    subtabs: [
      { id: 'data-quality', title: 'Data Quality' },
      { id: 'retrieval', title: 'Retrieval' },
      { id: 'graph', title: 'Graph' },
      { id: 'reranker-config', title: 'Reranker' },
      { id: 'learning-ranker', title: 'Learning Ranker' },
      { id: 'indexing', title: 'Indexing' }
    ],
    nav: { visible: true }
  },
  {
    path: '/eval',
    element: EvalAnalysisTab,
    label: 'Eval Analysis',
    icon: '🔬',
    order: 7,
    subtabs: [
      { id: 'analysis', title: 'Analysis' },
      { id: 'dataset', title: 'Eval Dataset' },
      { id: 'prompts', title: 'System Prompts' },
      { id: 'trace', title: 'Trace Viewer' }
    ],
    nav: {
      visible: true,
      className: 'keystone-tab',
      title: 'Deep-dive into evaluation runs with AI-powered analysis'
    }
  },
  // Profiles route removed - banned feature per CLAUDE.md
  {
    path: '/infrastructure',
    element: InfrastructureTab,
    label: 'Infrastructure',
    icon: '🔧',
    order: 8,
    subtabs: [
      { id: 'services', title: 'Services' },
      { id: 'docker', title: 'Docker' },
      { id: 'mcp', title: 'MCP Servers' },
      { id: 'paths', title: 'Paths & Stores' },
      { id: 'monitoring', title: 'Monitoring' }
    ],
    nav: { visible: true }
  },
  {
    path: '/admin',
    element: AdminTab,
    label: 'Admin',
    icon: '⚙️',
    order: 9,
    subtabs: [
      { id: 'general', title: 'General' },
      { id: 'secrets', title: 'Secrets' },
      { id: 'integrations', title: 'Integrations' }
    ],
    nav: { visible: true }
  },
  {
    path: '/docker',
    element: Docker,
    label: 'Docker',
    icon: '🐳',
    order: 10,
    subtabs: [],
    nav: { visible: false }
  }
];

// Get route by path
export function getRouteByPath(path: string): RouteConfig | undefined {
  return routes.find(r => r.path === path);
}

// Get default route
export function getDefaultRoute(): RouteConfig {
  return routes.find(r => r.path === '/dashboard') || routes[0];
}
