# ragweld.com — Handoff Prompt

## TASK

Build and deploy `ragweld.com` on Netlify. Landing page + live demo.

---

## BRAND

- `ragweld` (lowercase) in marketing/domain. `ragWeld` (camelCase) in code/docs.
- Internal names (`tribrid_config_model.py`, `TriBridConfig`, `tribrid-rag`) DO NOT CHANGE. ragweld is a brand, not a refactor.
- Production RAG engine: vector + sparse + graph search, fused and reranked.

---

## DEMO

Copy `/Users/davidmontgomery/tribrid-rag/web/`. Build it. Serve it at `/demo/`. Iframe it.

One change: `vite.config.ts` `base` from `'/web/'` to `'/demo/'`.

One thing to build: mock API layer (MSW service worker or Axios interceptor) so the GUI gets JSON instead of 404s. Read `web/src/types/generated.ts` for response shapes. Read `web/src/api/client.ts` for how it calls endpoints. Seed corpus: "epstein-files-1". Tabs that need a live backend (Docker, Grafana, Terminal) get a "Demo mode" banner.

Do not modify any GUI source files. Mock at the network level.

---

## LANDING PAGE

Copy the pattern from `/Users/davidmontgomery/epstein-files-1/epstein.net/`. Read it. It's Astro + Tailwind, static output, deployed to Netlify. The Hero component iframes the demo. The build script chains demo build + Astro build + copy. `netlify.toml` has the redirects.

Do exactly that, but for ragweld. Dark-first (`#0a0a0a` bg, `#00ff88` accent green, `#5b9dff` blue). The iframe IS the hero.

---

## CI

When `tribrid-rag` pushes to `web/**` on main, trigger a Netlify rebuild:

```yaml
# .github/workflows/sync-demo.yml in tribrid-rag repo
name: Sync ragweld demo
on:
  push:
    branches: [main]
    paths: ['web/**']
jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - run: curl -X POST -d {} ${{ secrets.RAGWELD_NETLIFY_BUILD_HOOK }}
```

---

## TOOLS AVAILABLE

- Netlify CLI installed and logged in (wcgw MCP)
- Netlify MCP connector
- GitHub MCP for repo creation
- Filesystem access to all repos

## REPOS

| What | Path |
|------|------|
| GUI source | `/Users/davidmontgomery/tribrid-rag/web/` |
| Landing page reference | `/Users/davidmontgomery/epstein-files-1/epstein.net/` |

---

## DO NOT

- Describe, document, or analyze the GUI
- Rewrite or recreate any GUI component
- Rename internal code
- Build a fake demo — the demo IS `/web/`
