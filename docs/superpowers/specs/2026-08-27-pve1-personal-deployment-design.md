# Ragweld Personal Proxmox Deployment Design

**Date:** 2026-08-27  
**Status:** Approved architecture; implementation not yet started  
**Target:** Permanent personal Ragweld instance on `pve1` (`192.168.68.171`)

## 1. Outcome

Deploy the full Ragweld workbench as a clean personal instance on `pve1`, make
it usable remotely at `me.ragweld.com`, and leave the Mac installation intact.
The instance must expose the operator-facing application and selected companion
UIs behind one password-based identity boundary without exposing Proxmox,
databases, container administration, or private LAN services.

This is not the old demo and it is not a migration of accumulated test state.
It is a clean data plane built from published `main`, with only deliberately
selected public corpora copied from the Mac.

## 2. Approved decisions

- Use a dedicated, privileged Debian 13 LXC on `pve1`; do not deploy Ragweld
  directly on the Proxmox host.
- Give the LXC access to every `pve1` CPU and the Intel render device, with the
  largest safe memory allocation while Home Assistant remains on that node.
- Move LXC 4214 (Plex and the arr suite) back to `pve` (`192.168.68.173`) before
  making the Intel render device exclusive to Ragweld.
- Preserve Plex media where it physically lives on `pve1`; temporarily present
  it to `pve` over a LAN-only NFS mount. A later physical disk move can remove
  this temporary dependency.
- Leave Home Assistant VM 120 on `pve1` until `pve3` is upgraded to a compatible
  Proxmox version; do not attempt a backward PVE 9.2 to PVE 8.4 migration.
- Use Cloudflare authoritative DNS and Cloudflare Tunnel. Temporary disturbance
  to the existing landing page is acceptable during the DNS cutover.
- Put Caddy and Authelia behind the tunnel. Authelia provides the requested
  username/password login and a shared session across Ragweld hostnames.
- Use LiteLLM as the only generation gateway. On this Intel-only host, initial
  generation uses paid OpenRouter routes. Do not claim that the Iris Xe GPU is
  a supported CUDA vLLM device.
- Keep the Mac source, state, and current runtime untouched. Every transfer from
  the Mac is copy-only; nothing is moved or deleted.

## 3. Verified starting state

The following facts were observed on 2026-08-26/27 and must be rechecked before
mutation:

| Item | Current state |
| --- | --- |
| `pve1` | PVE 9.2.2, i5-13500H, 16 logical CPUs, 31 GiB RAM, about 792 GiB free on `local-lvm` |
| `pve1` GPU | Intel render device at `/dev/dri/renderD128` |
| LXC 4214 | Privileged Docker LXC on `pve1`; 16 cores, 32 GB cap; Plex/arr; `/srv/media` bind mount; `/dev/dri` passthrough |
| Plex media | About 7.3 TB on `plex-vg`, mounted at `pve1:/srv/media`; about 5.4 TB used |
| VM 120 | HAOS on `pve1`; 8 cores, 16 GB cap; about 4.2 GiB observed use |
| `pve` / `.173` | PVE 9.2.2, Core Ultra 5 125H, 18 logical CPUs, 31 GiB RAM, about 797 GiB free on `local-lvm` |
| `pve` GPU | Intel Arc-class render device at `/dev/dri/renderD128`; already shared with Scrypted LXC 1043 |
| PBS | `pbs-beelink` active, about 1.7 TB free; recent backups exist for LXC 4214 and VM 120 |
| Git | Local and remote `main` both at `65bbf181d2b86b7fa9f202a961150bdd390b2c98`; one branch and one worktree |

LXC ID `100` is currently free cluster-wide. The Debian 13 template is
available for download but is not yet cached on `pve1`.

## 4. Target topology

```mermaid
flowchart LR
    Browser[Remote browser] --> CF[Cloudflare DNS and Tunnel]
    CF --> Tunnel[cloudflared in LXC 100]
    Tunnel --> Caddy[Caddy ingress]
    Caddy --> Auth[Authelia password and session]
    Auth --> Workbench[Ragweld workbench]
    Auth --> Grafana[Grafana]
    Auth --> Langfuse[Langfuse]
    Auth --> MLflow[MLflow]
    Auth --> Flyte[Flyte console]

    Workbench --> API[FastAPI]
    API --> LiteLLM[LiteLLM]
    LiteLLM --> OpenRouter[OpenRouter]
    API --> Postgres[(Postgres)]
    API --> Qdrant[(Qdrant)]
    API --> Neo4j[(Neo4j)]

    subgraph PVE1[pve1 192.168.68.171]
      subgraph LXC100[Ragweld LXC 100]
        Tunnel
        Caddy
        Auth
        Workbench
        Grafana
        Langfuse
        MLflow
        Flyte
        API
        LiteLLM
        Postgres
        Qdrant
        Neo4j
      end
      Media[/srv/media on plex-vg]
      HAOS[HAOS VM 120]
    end

    Media -->|LAN-only NFS| Plex[Plex and arr LXC 4214 on pve .173]
```

Only Cloudflare's outbound tunnel reaches the public Internet. There is no
router port-forward and no public Proxmox address.

## 5. Ragweld LXC contract

Create privileged LXC `100` named `ragweld` on `pve1` with:

- Debian 13 amd64;
- 16 visible CPUs, no CPU pinning, and high CPU scheduling weight;
- 24 GiB memory and 8 GiB swap while HAOS remains on `pve1`;
- a later increase to roughly 30 GiB after HAOS can safely return to `pve3`;
- a 300 GiB thin-provisioned root disk on `local-lvm`;
- Docker nesting/keyctl/fuse support required by the Compose stack and the
  privileged Flyte sandbox;
- `/dev/dri` passthrough, including `/dev/dri/renderD128`;
- an LXC firewall with SSH accepted only from the management LAN and no public
  inbound application ports;
- key-only root administration from the trusted LAN.

The LXC is privileged only because Docker-in-LXC plus the nested Flyte runtime
requires it. It receives no Proxmox socket, host Docker socket, or host data
mount. The Intel render device is available for components that genuinely
support it, but local inference is not declared ready merely because the device
exists.

## 6. Runtime layout

- Repository: `/opt/ragweld`, checked out from `origin/main` at the published
  commit selected by the implementation plan.
- Public corpus inputs: `/srv/ragweld/corpora`.
- Deployment secrets: `/etc/ragweld`, mode `0700`, with individual files mode
  `0600`.
- Persistent platform state: Docker named volumes inside the LXC, covered by
  LXC/PBS backups.
- Runtime ownership: a systemd unit owns the existing `start.sh` lifecycle and
  starts it after Docker and network-online.
- Frontend: build `web/dist` once and serve it with Caddy. Do not use the Vite
  development server as the permanent public process.
- Backend: run the existing host-mode FastAPI service under the systemd-owned
  launcher, bound to LXC loopback. This preserves the current localhost-only
  Docker control boundary without mounting the host Docker socket into an API
  container. Caddy runs as an LXC system service, proxies `/api/*` to loopback,
  and serves the `/web/` SPA with history fallback.
- Identity and tunnel: run Authelia in the deployment Compose overlay and run
  `cloudflared` as an LXC system service. Caddy reaches Authelia and all
  published companion UIs only through their loopback-bound ports.
- Full stack: Postgres, Qdrant, Neo4j, LiteLLM, MLflow, Flyte, Grafana,
  Prometheus, Loki, Promtail, Tempo, Alloy, Mimir, Pyroscope, Alertmanager, and
  the complete Langfuse service group.

All databases and control-plane ports remain internal to the Compose network or
loopback-bound. No direct public routes exist for Postgres, Qdrant, Neo4j,
Prometheus, Loki, Tempo, Mimir, Pyroscope, Alertmanager, MinIO, Redis, or
ClickHouse.

## 7. Generation and hardware truth

The current repo defaults require `ragweld-local`, backed by vLLM-metal on the
Apple Silicon Mac. That launcher cannot be copied honestly to this Linux Intel
host.

For the first Proxmox deployment:

- set the deployment's generation, enrichment, Chat, evaluation, and vision
  defaults to explicit OpenRouter-backed LiteLLM aliases;
- copy the existing OpenRouter credential securely into `/etc/ragweld` without
  printing or committing it;
- preserve LiteLLM as the only egress and keep retries/fallbacks disabled per
  the repository contract;
- add no llama.cpp, Ollama, fake vLLM responder, or compatibility route;
- make `chat.vllm.enabled=false` an honest nonblocking readiness state rather
  than reporting the whole application unavailable;
- keep the vLLM deployment path present but disabled until a supported local or
  remote accelerator is approved.

The application is considered fully usable when all operator workflows run
through real paid gateway models. “Local vLLM unavailable by design on this
hardware” is an explicit capability state, not a hidden failure and not a fake
green local-model claim.

Future Hugging Face training or inference is a separate slice. It may submit
ephemeral GPU jobs and return versioned artifacts; it must not turn the pve1
Intel iGPU into a claimed CUDA training device.

## 8. Authentication and public hostnames

Cloudflare becomes authoritative for `ragweld.com`. Copy the existing apex and
`www` landing records into Cloudflare after nameserver cutover; temporary
landing-site interruption is acceptable.

Initial protected hostnames:

| Hostname | Surface |
| --- | --- |
| `me.ragweld.com` | Main workbench and API |
| `auth.ragweld.com` | Authelia login portal |
| `grafana.ragweld.com` | Grafana dashboards and pop-outs |
| `langfuse.ragweld.com` | Langfuse eval/trace drilldown |
| `mlflow.ragweld.com` | MLflow runs and artifacts |
| `flyte.ragweld.com` | Flyte console |

One Cloudflare Tunnel maps those hostnames to Caddy. Caddy delegates every
protected request to Authelia. Authelia uses a local, Argon2-hashed user file
and a cookie scoped to `ragweld.com`, so one password session covers the
protected sibling hostnames.

Langfuse retains its own application authorization but uses Authelia as its
OIDC provider, with open signup and direct username/password login disabled in
Langfuse. This avoids a second unrelated account password. Grafana may keep its
anonymous Viewer mode only behind Caddy/Authelia because its listener remains
internal; administrative Grafana access retains a separate internal credential.

Adding a Bet365 viewer later means adding a separate Authelia identity and a
hostname-specific authorization policy. It does not mean sharing the owner's
password or exposing the full operator workbench.

## 9. Clean-start data policy

Do not copy any accumulated database or index state from the Mac, including:

- Docker/Colima volumes;
- Postgres databases;
- Qdrant collections;
- Neo4j databases;
- MLflow or Langfuse databases;
- synthetic-run residue;
- lineage aliases, locks, bundles, or tombstones;
- Playwright output and generated test corpora;
- `recall_default` or other old test corpora.

Copy only an explicit allowlist of public source files, initially:

- the public Epstein-files corpus already used by the project;
- the small Aurora/evidence corpus where its licensing and provenance are
  already recorded;
- a deliberately small multimodal example set covering PDF, image, and audio
  or video ingestion if the product supports each format honestly.

Transfers use checksummed copy semantics. The Mac files remain in place. The
new instance indexes those sources from scratch through the real UI/API and
creates new Postgres, Qdrant, and Neo4j state.

## 10. Plex redistribution

Before touching LXC 4214:

1. create a fresh PBS backup of LXC 4214 and verify that the backup task
   completed successfully;
2. confirm the current `/srv/media` mount, `plex-vg` health, and container GPU
   device mapping;
3. configure a LAN-only NFS export of `pve1:/srv/media`, restricted to
   `192.168.68.173`;
4. mount it on `pve` at `/srv/media` with systemd automount and a hard failure
   if the share is unavailable;
5. verify path ownership and read/write behavior using a temporary probe file
   outside the media library before migration;
6. stop LXC 4214 and migrate its 32 GiB root disk to `pve` while preserving VMID
   4214, IP `192.168.68.214`, `/srv/media` bind mapping, and `/dev/dri` mapping;
7. start it on `pve`, prove direct play, one hardware transcode, arr imports,
   download-client routing, and library writes;
8. only after those checks, remove LXC 4214's GPU mapping and runtime presence
   from `pve1`.

The NFS server is a temporary storage bridge, not a compute workload. Restrict
it to the `.173` host, expose no NFS service to the Internet, and document the
later physical media-disk return to `.173` as the cleanup that removes the
bridge.

Rollback is to stop 4214 on `.173`, restore/migrate its root disk back to
`pve1`, and reattach the existing local `/srv/media` bind. Do not delete the
last known-good 4214 backup until the new placement has run successfully.

## 11. Backup and recovery

- Take fresh PBS backups of LXC 4214 and VM 120 before infrastructure changes.
- After Ragweld acceptance, take an initial PBS backup of LXC 100 and verify the
  backup log.
- Schedule daily PBS backups for LXC 100 with retention sufficient for at least
  seven daily and four weekly restore points, subject to measured datastore
  growth.
- Keep the Git repository as rebuildable source; keep secrets separately under
  `/etc/ragweld` and include them in the encrypted LXC backup.
- Export periodic logical backups for Postgres, Neo4j, Qdrant snapshots, MLflow,
  and Langfuse so recovery is not dependent solely on whole-LXC restore.
- Prove one restore path into an isolated VMID before calling recovery complete.

## 12. Failure handling and rollback

- DNS: retain the old nameserver and Netlify record inventory; if the tunnel or
  auth path fails, remove the new published routes or revert nameservers.
- Authentication: maintain a LAN-only recovery route reachable only from the
  management subnet; it must not bypass authentication from the Internet.
- Ragweld: stop LXC 100 or its systemd unit without touching the Mac runtime.
- Plex: follow the rollback in section 10; media is never copied, reformatted,
  or deleted during the root-disk migration.
- Secrets: revoke the Cloudflare tunnel credentials and rotate the
  Authelia/OpenRouter credentials if they are printed or written outside
  `/etc/ragweld`.
- Data: a failed clean-start index may be deleted only from the new LXC after
  confirming the Mac source files remain unchanged.

## 13. Acceptance criteria

The deployment is working only when all of the following are true:

1. `me.ragweld.com` loads from a phone or office network with no VPN and no
   router port-forward.
2. An unauthenticated browser receives the Authelia login page and cannot reach
   the workbench, API, Grafana, Langfuse, MLflow, or Flyte directly.
3. One owner password session reaches all protected hostnames; Langfuse SSO does
   not require a second password.
4. Proxmox, SSH, Postgres, Qdrant, Neo4j, Redis, ClickHouse, MinIO, Prometheus,
   Loki, Tempo, Mimir, Pyroscope, and Alertmanager are unreachable from the
   public Internet.
5. The exact published `main` commit is shown in the deployment evidence and
   the LXC worktree has one local branch and one worktree.
6. Required repository validators, backend tests, frontend lint/build, and the
   relevant real-browser acceptance suites pass on the deployed commit.
7. Docker reports the complete requested service set healthy or honestly
   running where an upstream image has no healthcheck.
8. `/api/health` is healthy and `/api/ready` is green with vLLM explicitly
   disabled/nonblocking for this deployment, not silently failed.
9. A real paid OpenRouter request succeeds through Ragweld -> LiteLLM with no
   direct-provider path, retry, or fallback.
10. A public text corpus is created, indexed from scratch, searched with a real
    question, and used in a cited Chat answer.
11. A PDF/image multimodal sample is ingested and inspected through the rendered
    UI, or the unsupported format is explicitly excluded rather than mocked.
12. The operator can open Grafana, Langfuse, MLflow, and Flyte from the rendered
    workbench and see real current state rather than placeholder data.
13. A curious-user browser pass clicks every primary tab, scrolls the full
    surfaces, opens pop-outs, checks browser console/network failures, and logs
    any remaining product defects without hiding them.
14. LXC 4214 runs on `.173`, sees the existing media library, completes one
    hardware transcode, and the arr workflow can write through the NFS bridge.
15. The Mac source, local runtime, and source corpus files remain present and
    unchanged.
16. Fresh, verified PBS backups exist for the moved Plex LXC and the accepted
    Ragweld LXC, and the recovery commands are documented without secrets.

## 14. Explicit non-goals for this slice

- Deleting or moving the Mac installation.
- Importing old database/index/runtime debris.
- Moving Home Assistant before `pve3` is version-compatible.
- Physically moving the Plex media disks while the user is remote.
- Claiming local vLLM or Unsloth training on the Intel iGPU.
- Building a public multi-tenant SaaS control plane.
- Exposing Proxmox or low-level storage services through Cloudflare.
- Fixing unrelated product bugs discovered during the final browser pass; log
  them for the next product session unless they block deployment acceptance.

## 15. Primary implementation artifacts

The implementation plan should create a small, deployment-owned surface rather
than embed machine-specific values throughout the application:

- `deploy/proxmox/` for the Compose production override, Caddy, Authelia,
  cloudflared, systemd, firewall, and operator runbook inputs;
- focused tests for the deployment topology, public-route allowlist, secret
  boundaries, disabled-vLLM readiness, and production frontend serving;
- a deployment evidence file under `docs/exec-plans/active/` recording hashes,
  guest configuration, service health, browser proof, and backup IDs without
  secrets.

No generated MkDocs output is hand-edited. Any lasting operator behavior is
documented in the repo-local knowledge base and fed through the existing docs
ownership path.

## 16. Reference documentation

- Cloudflare Tunnel: <https://developers.cloudflare.com/tunnel/>
- Cloudflare Tunnel routing: <https://developers.cloudflare.com/tunnel/routing/>
- Authelia Docker deployment: <https://www.authelia.com/integration/deployment/docker/>
- Authelia OpenID Connect provider: <https://www.authelia.com/configuration/identity-providers/openid-connect/provider/>
- Langfuse self-hosted authentication and SSO: <https://langfuse.com/self-hosting/security/authentication-and-sso>
- Langfuse hardening: <https://langfuse.com/self-hosting/configuration/hardening>
