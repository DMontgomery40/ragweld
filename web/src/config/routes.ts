// AGRO - React Router Configuration
// Converted from legacy navigation.js TAB_REGISTRY and NEW_TABS

import { ReactNode, ComponentType } from 'react';
import { Dashboard } from '../pages/Dashboard';
import Docker from '../pages/Docker';
// Tab components (all TypeScript)
import ChatTab from '../components/tabs/ChatTab';
import VSCodeTab from '../components/tabs/VSCodeTab';
import GrafanaTab from '../components/tabs/GrafanaTab';
import RAGTab from '../components/tabs/RAGTab';
import EvalAnalysisTab from '../components/tabs/EvalAnalysisTab';
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
}

// Main route configuration - converted from NEW_TABS in navigation.js
export const routes: RouteConfig[] = [
  {
    path: '/start',
    element: StartTab,
    label: 'Get Started',
    icon: '🚀',
    order: 1,
    subtabs: []
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
    ]
  },
  {
    path: '/chat',
    element: ChatTab,
    label: 'Chat',
    icon: '💬',
    order: 3,
    subtabs: []
  },
  {
    path: '/vscode',
    element: VSCodeTab,
    label: 'VS Code',
    icon: '📝',
    order: 4,
    subtabs: []
  },
  {
    path: '/grafana',
    element: GrafanaTab,
    label: 'Grafana',
    icon: '📈',
    order: 5,
    subtabs: []
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
      { id: 'indexing', title: 'Indexing' },
      { id: 'evaluate', title: 'Evaluate RAG Pipeline' }
    ]
  },
  {
    path: '/eval',
    element: EvalAnalysisTab,
    label: 'Eval Analysis',
    icon: '🔬',
    order: 7,
    subtabs: []
  },
  // Profiles route removed - banned feature per CLAUDE.md
  {
    path: '/infrastructure',
    element: InfrastructureTab,
    label: 'Infrastructure',
    icon: '🔧',
    order: 9,
    subtabs: [
      { id: 'services', title: 'Services' },
      { id: 'mcp', title: 'MCP Servers' },
      { id: 'paths', title: 'Paths & Stores' },
      { id: 'monitoring', title: 'Monitoring' }
    ]
  },
  {
    path: '/admin',
    element: AdminTab,
    label: 'Admin',
    icon: '⚙️',
    order: 10,
    subtabs: [
      { id: 'general', title: 'General' },
      { id: 'git', title: 'Git Integration' },
      { id: 'secrets', title: 'Secrets' },
      { id: 'integrations', title: 'Integrations' }
    ]
  },
  {
    path: '/docker',
    element: Docker,
    label: 'Docker',
    icon: '🐳',
    order: 11,
    subtabs: []
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
