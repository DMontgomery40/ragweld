// Shared front-end UI-only types.
//
// IMPORTANT:
// - API payload types MUST be imported from `web/src/types/generated.ts`.
// - This file is reserved for UI-only types that do not map to Pydantic models.

export interface ErrorHelperOptions {
  title?: string;
  message?: string;
  causes?: string[];
  fixes?: string[];
  links?: Array<[string, string]>;
  context?: string;
}

// ---------------------------------------------------------------------------
// UI-only search types (not part of backend Pydantic contracts)
// ---------------------------------------------------------------------------

export interface SettingSearchItem {
  label: string;
  title: string;
  name: string;
  placeholder: string;
  element: HTMLElement;
  content: string;
}

export interface SearchResult {
  file_path: string;
  start_line: number;
  end_line: number;
  language: string;
  rerank_score: number;
  // Settings search fields (used by GlobalSearch modal)
  label?: string;
  title?: string;
  name?: string;
  element?: HTMLElement;
}
