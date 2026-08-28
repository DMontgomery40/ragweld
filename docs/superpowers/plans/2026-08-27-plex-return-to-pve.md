# Plex Return to pve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Plex and the arr suite in LXC 4214 from `pve1` back to `pve` (`192.168.68.173`) while keeping the physically attached pve1 media intact and writable through a narrowly scoped NFSv4 bridge.

**Architecture:** Back up first, export only `pve1:/srv/media` to the exact `.173` client, mount it at the same host path on `.173`, then perform an offline Proxmox LXC root-disk migration. Preserve VMID, IP, bind path, Docker state, and rollback capability; share the `.173` Intel render device with Scrypted.

**Tech Stack:** Proxmox VE 9.2.2, PBS, privileged LXC, NFSv4, systemd mount units, Docker, Plex, Sonarr, Radarr, qBittorrent, Intel Quick Sync.

**Spec:** `docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md`

## Global Constraints

- Execute only after `2026-08-27-proxmox-runtime-foundation.md` is published and its NFS templates are green.
- Use SSH key `/Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519` with `IdentitiesOnly=yes`; never use or print stored passwords.
- Preserve all media on `plex-vg`; do not copy, reformat, resize, move, or delete media files.
- Preserve VMID `4214`, LXC IP `192.168.68.214`, and all Docker volumes/configuration.
- Do not touch Scrypted LXC 1043 except to observe shared-GPU health.
- Stop for investigation if `/srv/media` is not backed by `/dev/mapper/plex--vg-plex--lv`, if VMID 4214 is not on `pve1`, or if the PBS backup fails.
- Keep the NFS export restricted to the single client `192.168.68.173`; do not export to a subnet or wildcard.
- Treat every stop/migrate/start command as a rollback checkpoint and record its exit status.
- Do not remove the source backup, NFS bridge, or source-node rollback notes during this plan.

## Operator corrections (David, 2026-08-28 07:10)

From `docs/exec-plans/active/watchdog-proxmox-foundation-2026-08-28.md`
(W37-W40). These override the conflicting steps below.

- **W37 — the automount must be live when the container starts.** Before
  Task 2, land a foundation follow-up commit setting `TimeoutIdleSec=0` in
  `deploy/proxmox/plex/srv-media.automount` (with the contract test updated).
  Task 2 Step 3 installs a `.173` drop-in owned by Plex alone:
  `/etc/systemd/system/pve-container@4214.service.d/srv-media.conf`.
  It carries `Requires=srv-media.automount`, orders after the automount and
  network-online target, and runs the fatal, bounded check
  `ExecStartPre=/usr/bin/timeout 60 /bin/sh -c 'ls /srv/media >/dev/null 2>&1 && findmnt -t nfs4 /srv/media >/dev/null'`.
  Do not attach this check to `pve-guests.service`: that unit starts every
  autostarting guest on `.173`, including Scrypted LXC 1043. The per-instance
  drop-in makes missing media fail only Plex 4214 while cameras remain
  independent. Task 3 Step 5 runs
  `findmnt -t nfs4 /srv/media` on `.173` immediately before `pct start 4214`
  and afterwards proves `pct exec 4214 -- findmnt -t nfs4 /srv/media`
  (fstype `nfs4`, never `autofs`). Reason: an LXC bind mount created while
  the automount is expired or untriggered captures the autofs stub and the
  container sees an empty media tree.
- **W38 — `shared=1` is a precondition, not an assumption.** Task 1 Step 2
  records the actual `mp1` line. If `shared=1` is absent, add an explicit
  Task 3 Step 0: `pct set 4214 -mp1 /srv/media,mp=/srv/media,shared=1`
  (metadata only; rollback is `shared=0`), before the migrate.
- **W39 — pve1 host firewall.** Task 2 Step 2 first runs `pve-firewall status`
  on pve1; if enabled, add `IN ACCEPT -source 192.168.68.173 -p tcp -dport 2049`
  to `/etc/pve/nodes/pve1/host.fw` before the `.173` mount, and record it as
  part of the bridge to remove later.
- **W40 — probe paths.** Task 4 Step 3 derives the three probe paths and the
  container UID from the Task 1 Step 3 inventory instead of the hardcoded
  `/tv`, `/movies`, `/downloads` mappings.
- **Live destination correction 2026-08-28.** `.173` had an absent-device
  ext4 UUID in `/etc/fstab` for `/srv/media` plus 31.6 GB of stale root-disk
  data below that path. The exact fstab was preserved at
  `/etc/fstab.ragweld-pre-nfs-20260828`, only the absent-UUID line was
  disabled, and the directory was renamed without copying or deleting data to
  `/srv/media-local-pre-nfs-20260828`. Do not remove that quarantine during
  this migration. Also, Debian 13 did not create `/etc/exports.d`; Task 2
  explicitly creates the standard directory before installing the export.
- **W41 — prove `root_squash` before the migration depends on it.** Today the
  container writes `/srv/media` as a local bind mount, so uid 0 writes work;
  over the bridge they must be owned by the anonymous uid. The export root is
  intentionally mode `0777`, so a root-side write may succeed even when
  squashing works; failure is not the contract. Task 2 Step 4 creates one
  root-side probe and requires owner `65534:65534` on both nodes, then removes
  it. Task 4 Step 2 greps the four media
  containers' logs for `permission denied|operation not permitted|chown|EACCES`
  before acceptance. Any hit stops the plan. If an init genuinely needs root
  ownership on one subtree, the fix is a targeted `no_root_squash` for that
  path with an explicit ruling — never a blanket export relaxation.
- **W43 — isolate the start gate and reboot `.173` once before acceptance.**
  The media pre-start check belongs only to `pve-container@4214.service`, not
  global `pve-guests.service`, so pve1 availability cannot hold Scrypted's
  cameras hostage. Task 4
  Step 5 adds one clean reboot of `.173` after the bridge is live, then
  confirms Scrypted 1043 is running, 4214 is running, and
  `pct exec 4214 -- findmnt -t nfs4 /srv/media` still reports `nfs4`. The
  boot-order path is where the W37 trap lives and no other step exercises it.
- **W42 — make the underlying mountpoint fail loudly.** Preflight recorded
  `.173:/srv/media` as an unmounted plain directory. Before mounting in Task 2
  Step 3: assert it is empty, then `chmod 0555 /srv/media`. Otherwise any
  window without the NFS mount silently writes to `.173`'s root disk — the
  writes succeed, disappear under the next mount, and can fill the node now
  hosting Plex. Record the `0555` as a bridge component; removing the bridge
  means unmounting **and** restoring the mode.

### The trap behind W37 (read this before Task 2 or Task 3)

A host `.mount`/`.automount` pair plus an LXC bind mount passes every static
check and can still hand the container an **empty media tree**.

`pct start` creates `mp1: /srv/media,mp=/srv/media` by binding whatever exists
at that host path **at that instant**, with private mount propagation. If the
NFS filesystem is not mounted right then — expired after `TimeoutIdleSec`
(the original template said `60`; fixed to `0` in `b421d203`), or never
triggered since a `.173` reboot — the container can bind the **autofs stub**,
not the NFS mount. The `pve-container@4214.service` drop-in prevents that
specific guest from starting until the host view is `nfs4`. A later host-side
automount does not propagate into an already running container.

What makes this expensive: the host looks correct. `findmnt /srv/media` on
`.173` reports `nfs4`, `systemctl status srv-media.automount` is active, the
export is right, and Plex/arr simply start against an empty library — which
reads as an application or permissions failure, sends you to Task 3 Step 6
rollback, and then recurs on the next reboot.

Only a fstype check **inside the guest** distinguishes the two states:

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'findmnt -t nfs4 /srv/media'                    # host view
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- findmnt -t nfs4 /srv/media'   # the one that matters
```

`autofs` (or no match) inside the container means the bind captured the stub:
stop the container, trigger and verify the mount on the host, start again. Do
not proceed to acceptance on a host-side check alone.

Generalization for later homelab work: binding any lazily-mounted filesystem
(autofs, systemd automount, network mounts) into a container or namespace
captures whatever exists at bind time. Config review cannot catch it; only a
runtime check on the consumer side can. Same shape as the Colima
`host.docker.internal` divergence — the host view and the guest view differ,
and only the guest view is real.

---

### Task 1: Capture immutable preflight evidence and a fresh PBS backup

**Files:**
- Create: `docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`

**Interfaces:**
- Consumes: live cluster state, `pbs-beelink`, LXC 4214.
- Produces: verified LXC 4214 and VM 120 backup identifiers plus pre-migration inventory used by every later task.

- [ ] **Step 1: Define the exact SSH prefix locally**

```bash
PVE_SSH=(ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes)
```

- [ ] **Step 2: Verify the source, destination, quorum, storage, mount, and guest identity**

Run read-only checks:

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pvecm status; pvesh get /cluster/resources --type vm --output-format json; pct config 4214; findmnt -no SOURCE,FSTYPE,OPTIONS /srv/media; pvesm status; ls -l /dev/dri'
"${PVE_SSH[@]}" root@192.168.68.173 'pveversion; free -h; pct list; pvesm status; ls -l /dev/dri; test ! -e /srv/media || findmnt /srv/media'
```

Expected:

- cluster quorate;
- LXC 4214 running on `pve1` with `mp1: /srv/media,mp=/srv/media,shared=1`;
- `/srv/media` source `/dev/mapper/plex--vg-plex--lv`, ext4, read/write;
- `.173` PVE 9.2.2 and `local-lvm` has more than 64 GiB free;
- `.173` exposes `/dev/dri/renderD128`;
- no existing `.173:/srv/media` mount conflicts with the planned unit.

- [ ] **Step 3: Record the current application inventory without secrets**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pct exec 4214 -- docker ps --format "{{.Names}}|{{.Status}}|{{.Ports}}"; pct exec 4214 -- sh -lc '\''for c in plex sonarr radarr qbittorrent; do docker inspect --format "{{.Name}} user={{.Config.User}} {{range .Mounts}}{{println .Source \"->\" .Destination \"rw=\" .RW}}{{end}}" "$c"; done'\'''
```

Expected: Plex, Sonarr, Radarr, qBittorrent, Prowlarr, Overseerr, Portainer, exporters, gluetun, and startpage are running; the media consumers use UID/GID 1000 and writable `/srv/media` paths.

- [ ] **Step 4: Create fresh snapshot-mode PBS backups**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'vzdump 4214 --storage pbs-beelink --mode snapshot --compress zstd'
"${PVE_SSH[@]}" root@192.168.68.171 'vzdump 120 --storage pbs-beelink --mode snapshot --compress zstd'
```

Expected: both commands exit 0 with `TASK OK`. Any warning about the external Plex bind mount must state it is excluded rather than failed; the LXC root disk/Docker state and the HAOS VM disk must be included.

- [ ] **Step 5: Resolve and record the newest backup**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pvesm list pbs-beelink --content backup --vmid 4214 | tail -n 3'
"${PVE_SSH[@]}" root@192.168.68.171 'pvesm list pbs-beelink --content backup --vmid 120 | tail -n 3'
```

Record both exact volume identifiers, timestamps, sizes, source/destination PVE versions, mount source, and current Git commit in the evidence file. Do not record credentials, tokens, or Plex authentication material.

- [ ] **Step 6: Commit preflight evidence**

```bash
git add docs/exec-plans/active/plex-return-to-pve-2026-08-27.md
git commit -m "docs(homelab): record plex migration preflight"
git push origin main
```

### Task 2: Establish and prove the scoped NFSv4 media bridge

**Files:**
- Consume: `deploy/proxmox/plex/exports.ragweld`
- Consume: `deploy/proxmox/plex/nfs.conf`
- Consume: `deploy/proxmox/plex/srv-media.mount`
- Consume: `deploy/proxmox/plex/srv-media.automount`
- Modify: `docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`

**Interfaces:**
- Consumes: exact pve1 export and `.173` mount templates.
- Produces: writable `.173:/srv/media` backed by pve1 media and surviving reboot/network restart.

- [ ] **Step 1: Copy templates to explicit temporary paths**

```bash
scp -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes deploy/proxmox/plex/exports.ragweld deploy/proxmox/plex/nfs.conf root@192.168.68.171:/root/
scp -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes deploy/proxmox/plex/srv-media.mount deploy/proxmox/plex/srv-media.automount root@192.168.68.173:/root/
```

- [ ] **Step 2: Install and activate NFSv4 on pve1**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'apt-get update && apt-get install -y nfs-kernel-server && install -d -m 0755 /etc/exports.d /etc/nfs.conf.d && install -m 0644 /root/exports.ragweld /etc/exports.d/ragweld-media.exports && install -m 0644 /root/nfs.conf /etc/nfs.conf.d/99-ragweld.conf && systemctl restart nfs-server && exportfs -ra && exportfs -v'
```

Expected: the only Ragweld export client shown is `192.168.68.173`; NFSv3 is disabled.

- [ ] **Step 3: Install the systemd mount/automount on `.173`**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'apt-get update && apt-get install -y nfs-common && install -d -m 0755 /srv/media /etc/systemd/system/pve-container@4214.service.d && test -z "$(ls -A /srv/media)" && chmod 0555 /srv/media && install -m 0644 /root/srv-media.mount /etc/systemd/system/srv-media.mount && install -m 0644 /root/srv-media.automount /etc/systemd/system/srv-media.automount && printf "%s\n" "[Unit]" "Requires=srv-media.automount" "After=srv-media.automount network-online.target" "" "[Service]" "ExecStartPre=/usr/bin/timeout 60 /bin/sh -c '\''ls /srv/media >/dev/null 2>&1 && findmnt -t nfs4 /srv/media >/dev/null'\''" > /etc/systemd/system/pve-container@4214.service.d/srv-media.conf && chmod 0644 /etc/systemd/system/pve-container@4214.service.d/srv-media.conf && systemctl daemon-reload && systemctl enable --now srv-media.automount && timeout 30 ls /srv/media >/dev/null && findmnt -t nfs4 /srv/media'
```

Expected: NFSv4 mount from `192.168.68.171:/srv/media`, `rw`, `hard`, and `noatime`.

- [ ] **Step 4: Prove UID/GID 1000 read and write across the bridge**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'setpriv --reuid=1000 --regid=1000 --clear-groups sh -c "printf nfs-probe > /srv/media/.ragweld-nfs-probe" && stat -c "%u:%g %a %s" /srv/media/.ragweld-nfs-probe'
"${PVE_SSH[@]}" root@192.168.68.171 'test "$(cat /srv/media/.ragweld-nfs-probe)" = nfs-probe && stat -c "%u:%g %a %s" /srv/media/.ragweld-nfs-probe'
"${PVE_SSH[@]}" root@192.168.68.173 'rm /srv/media/.ragweld-nfs-probe'
"${PVE_SSH[@]}" root@192.168.68.173 'printf squash-check > /srv/media/.ragweld-root-squash-probe; test "$(stat -c %u:%g /srv/media/.ragweld-root-squash-probe)" = 65534:65534'
"${PVE_SSH[@]}" root@192.168.68.171 'test "$(stat -c %u:%g /srv/media/.ragweld-root-squash-probe)" = 65534:65534'
"${PVE_SSH[@]}" root@192.168.68.173 'rm /srv/media/.ragweld-root-squash-probe'
```

Expected: the application probe is owner `1000:1000`; the root probe is
owner `65534:65534`, proving `root_squash`; content matches; both exact probe
files are removed. These two named probes are the only media-path deletions
authorized by this task.

- [ ] **Step 5: Prove the automount survives a clean unmount**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'systemctl stop srv-media.mount; findmnt -t autofs /srv/media; timeout 30 ls /srv/media >/dev/null; findmnt -t nfs4 /srv/media'
```

Expected: access retriggers the automount and the same NFSv4 source returns.

- [ ] **Step 6: Append bridge evidence and commit**

Record export client, mount source/options, UID/GID probe, and rollback commands. Commit and push only the evidence file.

### Task 3: Perform the offline LXC root-disk migration

**Files:**
- Modify: `docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`

**Interfaces:**
- Consumes: verified backup and NFS bridge.
- Produces: VMID 4214 registered and running on node `pve`, absent from `pve1` runtime.

- [ ] **Step 1: Re-run the destructive-action gate**

Immediately before stopping anything, rerun:

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pvecm status; pct status 4214; findmnt /srv/media; pvesm status'
"${PVE_SSH[@]}" root@192.168.68.173 'findmnt /srv/media; pvesm status; ls -l /dev/dri/renderD128'
```

Proceed only if quorum, PBS, both `local-lvm` pools, media source, NFS target, and GPU device match Task 1/2.

- [ ] **Step 2: Stop LXC 4214 cleanly and confirm it is stopped**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pct shutdown 4214 --timeout 180; pct status 4214'
```

Expected: `status: stopped`. If shutdown times out, inspect the guest; do not force-stop until database/download activity is understood.

- [ ] **Step 3: Migrate only the root disk to `.173`**

```bash
"${PVE_SSH[@]}" root@192.168.68.171 'pct migrate 4214 pve --target-storage local-lvm'
```

Expected: task exit 0. The `shared=1` `/srv/media` bind entry remains in config and is not copied.

- [ ] **Step 4: Validate the target config before start**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'pct config 4214; findmnt -t nfs4 /srv/media; ls -l /dev/dri/renderD128'
```

Required config: VMID 4214, 16 cores, privileged, nesting/keyctl/fuse, IP `192.168.68.214/24`, `mp1 /srv/media`, and `/dev/dri` mappings.

- [ ] **Step 5: Start on `.173` and require clean container status**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'findmnt -t nfs4 /srv/media; pct start 4214; pct status 4214; pct exec 4214 -- findmnt -t nfs4 /srv/media; pct exec 4214 -- ls -l /dev/dri; pct exec 4214 -- docker ps --format "{{.Names}}|{{.Status}}"'
```

Expected: LXC running, NFS-backed media visible, render device visible, and the full prior Docker container inventory starts.

- [ ] **Step 6: Roll back immediately on mount or Docker failure**

If `/srv/media` is absent/empty, `/dev/dri` is absent, or Plex/arr containers fail to start:

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'pct stop 4214; pct migrate 4214 pve1 --target-storage local-lvm'
"${PVE_SSH[@]}" root@192.168.68.171 'pct start 4214; pct exec 4214 -- findmnt /srv/media; pct exec 4214 -- docker ps'
```

Do not continue forward acceptance after rollback.

### Task 4: Prove Plex, arr, VPN, media writes, and shared GPU behavior

**Files:**
- Modify: `docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`

**Interfaces:**
- Consumes: running 4214 on `.173`.
- Produces: application-level acceptance and retained rollback window.

- [ ] **Step 1: Verify all expected HTTP services from the LAN**

```bash
curl -fsS -o /dev/null http://192.168.68.214:32400/web/
curl -fsS -o /dev/null http://192.168.68.214:5055
curl -fsS -o /dev/null http://192.168.68.214:7878
curl -fsS -o /dev/null http://192.168.68.214:8989
curl -fsS -o /dev/null http://192.168.68.214:9696
curl -fsS -o /dev/null http://192.168.68.214:8080
curl -fkSs -o /dev/null https://192.168.68.214:9443
```

Expected: all return an HTTP response without timeout.

- [ ] **Step 2: Verify container and VPN health**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- docker ps --format "{{.Names}}|{{.Status}}"; pct exec 4214 -- docker inspect --format "{{.State.Health.Status}}" gluetun; pct exec 4214 -- docker logs --tail 50 gluetun'
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- sh -lc "for c in plex sonarr radarr qbittorrent; do docker logs --tail 200 \$c 2>&1 | grep -iE '\''permission denied|operation not permitted|chown|EACCES'\'' | sed \"s/^/\$c: /\"; done"'
```

Expected: gluetun healthy, no containers restarting, no route/auth regression,
and no media-permission signature in the four media-container logs. Do not
print VPN credentials.

- [ ] **Step 3: Prove application-user media writes**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- docker exec -u 1000:1000 sonarr sh -c "printf sonarr-probe > /tv/.ragweld-sonarr-probe"; pct exec 4214 -- docker exec -u 1000:1000 radarr sh -c "printf radarr-probe > /movies/.ragweld-radarr-probe"; pct exec 4214 -- docker exec -u 1000:1000 qbittorrent sh -c "printf qbit-probe > /downloads/.ragweld-qbit-probe"'
"${PVE_SSH[@]}" root@192.168.68.171 'test "$(cat /srv/media/tv-sonarr/.ragweld-sonarr-probe)" = sonarr-probe; test "$(cat /srv/media/radarr/.ragweld-radarr-probe)" = radarr-probe; test "$(cat /srv/media/downloads/.ragweld-qbit-probe)" = qbit-probe'
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- rm /srv/media/tv-sonarr/.ragweld-sonarr-probe /srv/media/radarr/.ragweld-radarr-probe /srv/media/downloads/.ragweld-qbit-probe'
```

These three named probe files are the only additional media-path deletions authorized.

- [ ] **Step 4: Prove Plex direct play and hardware transcode visually**

Use the signed-in Plex UI in the in-app Browser. Play one known local item directly, then force a lower remote quality to create a transcode. While it runs:

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'command -v intel_gpu_top >/dev/null || apt-get install -y intel-gpu-tools'
"${PVE_SSH[@]}" root@192.168.68.173 'pct exec 4214 -- docker exec plex ls -l /dev/dri; timeout 20 intel_gpu_top -J -s 1000'
```

Expected: Plex reports hardware transcoding in its dashboard/session details and `.173` video-engine activity rises. Capture a screenshot and sanitized GPU observation; do not record media-account tokens.

- [ ] **Step 5: Confirm Scrypted remains healthy while Plex transcodes**

```bash
"${PVE_SSH[@]}" root@192.168.68.173 'pct status 1043; pct exec 1043 -- systemctl is-active scrypted.service || true; pct exec 1043 -- ls -l /dev/dri/renderD128'
```

Also check the existing Scrypted UI/live camera view. A shared render device is accepted only if both workloads remain functional.

Before closing acceptance, reboot `.173` once. After SSH returns, require
`pct status 1043` and `pct status 4214` to be running, repeat the Scrypted
health checks above, and require
`pct exec 4214 -- findmnt -t nfs4 /srv/media`. The reboot/boot-order path is
part of W43 acceptance, not an optional soak test.

- [ ] **Step 6: Close evidence and retain rollback**

Record destination node, root disk storage, NFS options, all service checks, direct-play/transcode proof, Scrypted proof, downtime, and the PBS backup identifier. Commit and push the evidence file. Keep the NFS bridge and PBS backup in place.
