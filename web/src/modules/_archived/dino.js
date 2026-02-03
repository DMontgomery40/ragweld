// Legacy dino.js module (archived).
//
// This file previously exposed a small `window.Dino` utility.
// As part of the legacy JS → React migration, the Dino module has been removed
// (no remaining React/TS call sites) and MUST NOT be reintroduced as a window global.
//
// If Dino functionality is needed again, re-add it as:
// - a typed service under `web/src/services/`
// - optionally a Zustand store under `web/src/stores/`
// - a hook under `web/src/hooks/`
// - and a React component under `web/src/components/`

