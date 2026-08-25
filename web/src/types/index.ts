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
