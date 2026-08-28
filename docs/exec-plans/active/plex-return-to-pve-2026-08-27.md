# Plex return-to-pve execution evidence

Status: Tasks 1-3 and non-visual Task 4 acceptance verified; signed-in Plex playback/transcode proof pending

Plan: `docs/superpowers/plans/2026-08-27-plex-return-to-pve.md`

## Locked source state

- Verified published source before live work: `62cff6055c096e3209b7527b101038b9e2ee9259`
- Local branch/worktree canon at preflight: one branch (`main`), one worktree.
- Preserved local-only instruction/tooling changes remain excluded from deployment publication.
- W37 follow-up is test-first in the working tree and must be verified, committed, and pushed before Plex Task 2:
  `deploy/proxmox/plex/srv-media.automount` uses `TimeoutIdleSec=0`.

## Task 1 Step 2 — live cluster and mount preflight

Controller verification on 2026-08-28 used key-only, batch-mode SSH and made no remote changes.

- Cluster `homelabz`: three nodes; quorum `Yes`.
- Source node: `pve1` / `192.168.68.171`.
- Destination node: `pve` / `192.168.68.173`, PVE `9.2.2`.
- LXC 4214 is running on pve1 with:
  - `cores: 16`
  - `memory: 32000`
  - `unprivileged: 0`
  - `features: keyctl=1,nesting=1,fuse=1`
  - `rootfs: local-lvm:vm-4214-disk-0,size=32G`
  - `net0 ... ip=192.168.68.214/24`
  - `mp1: /srv/media,mp=/srv/media,shared=1`
- W38 is satisfied: the media bind mount already carries `shared=1`.
- Source `/srv/media` is `/dev/mapper/plex--vg-plex--lv`, `ext4`, `rw,relatime`.
- pve1 host firewall reports `disabled/running`; W39's port-2049 rule is not currently required. Recheck immediately before exporting NFS.
- Both nodes expose `/dev/dri/card0` and `/dev/dri/renderD128`.
- Available storage reported at preflight:
  - pve1 `local-lvm`: `791910701 KiB`
  - pve `.173` `local-lvm`: `796991323 KiB`
  - `pbs-beelink`: active, `1729927772 KiB` available
- `.173:/srv/media` exists as a plain root-owned directory and is not mounted. This is not a conflicting media mount; Task 2 must install the planned unit over this mountpoint.
- VM 120 is running on pve1.

## Task 1 Step 3 — sanitized Plex/arr inventory

Running containers observed: Plex, Sonarr, Radarr, qBittorrent, Prowlarr, Overseerr, Portainer, Startpage, Gluetun, and the Sonarr/Radarr/Prowlarr exporters.

The LinuxServer media containers have a blank Docker `Config.User` because their s6 init starts as root, but direct non-secret environment inspection confirms all four application identities are configured with `PUID=1000` and `PGID=1000`.

W40 probe mappings derived from the live container mounts:

- Plex: `/srv/media -> /media`, `/srv/media/radarr -> /movies`, `/srv/media/tv-sonarr -> /tv`.
- Sonarr: `/srv/media/downloads -> /downloads`, `/srv/media/tv-sonarr -> /tv`.
- Radarr: `/srv/media/radarr -> /movies`, `/srv/media/downloads -> /downloads`.
- qBittorrent: `/srv/media/downloads -> /downloads`, `/srv/media/radarr -> /movies`, `/srv/media/tv-sonarr -> /tv`.

Every listed mount is writable according to Docker's live mount metadata. Task 4 write probes must use these inventory-derived paths and UID/GID 1000; do not substitute hardcoded assumptions.

## Rollback owner and next checkpoint

- Rollback owner: the controller executing this plan.
- No stop, migration, export, mount, or package install has occurred yet.
- Fresh PBS backups completed successfully on 2026-08-28:
  - LXC 4214: `pbs-beelink:backup/ct/4214/2026-08-28T13:20:54Z`, size `22680849192` bytes. The 21.117 GiB root/Docker state was included; `/srv/media` was explicitly excluded as an external bind mount. Duration: `00:01:02`.
  - VM 120: `pbs-beelink:backup/vm/120/2026-08-28T13:22:12Z`, size `34360280145` bytes. Both `scsi0` and `efidisk0` were included; the guest-agent freeze/thaw completed and the dirty bitmap was clean. Duration: `00:00:03`.
- Both backup commands exited `0` and ended with `Backup job finished successfully`.
- W37 was published on `main` as `b421d203` before bridge activation.
- Next checkpoint: commit this bridge evidence, then rerun the destructive-action gate immediately before stopping LXC 4214. Stop on any quorum, PBS, storage, media mount, NFS, GPU, or service-state mismatch.

## Task 2 — scoped NFSv4 bridge evidence

### pve1 server

- Debian 13 installed `nfs-kernel-server` but did not create
  `/etc/exports.d`; the first activation attempt stopped before writing either
  Ragweld config file. Debian's `exports(5)` confirms the directory is
  supported, so the plan now creates `/etc/exports.d` at mode `0755` before
  installing the export.
- Active export:
  `/srv/media 192.168.68.173(sync,wdelay,hide,no_subtree_check,sec=sys,rw,secure,root_squash,no_all_squash)`.
- `nfsconf` reports `vers3=n`, `vers4=y`.
- `nfs-server` is active; NFSv4 RPC on TCP/2049 responds from `.173`.
- pve1 firewall was rechecked immediately before activation and remained
  `disabled/running`; no host-firewall rule was added.

### Preserved destination state

- `.173:/etc/fstab` contained one stale line for absent UUID
  `5ddacfd6-1309-4c2c-8bb8-890bbef8546d` targeting `/srv/media`.
- `blkid -U` confirmed the UUID is absent; `lsblk` showed no matching device.
- Exact fstab backup:
  `/etc/fstab.ragweld-pre-nfs-20260828`.
- Only that exact absent-UUID line was disabled in the live fstab.
- The previous root-disk directory contained `145` files totaling
  `31598868913` bytes under `downloads`; it was renamed on the same filesystem
  to `/srv/media-local-pre-nfs-20260828` and remains intact. Nothing in that
  quarantine was deleted or copied.
- A new empty `/srv/media` mountpoint was created at mode `0755`.
- Before restoring the automount, that empty underlying directory was changed
  to mode `0555`; a direct UID/GID 1000 write was denied. The live NFS root's
  own permissions apply while mounted. Bridge rollback must restore the
  underlying directory mode after unmounting.

### `.173` client and boot ordering

- Installed `srv-media.mount` and `srv-media.automount` from commit
  `b421d203`.
- The initial global `pve-guests.service` drop-in was removed before migration:
  it would have made pve1 media availability a start dependency for unrelated
  Scrypted LXC 1043.
- Installed the correctly scoped
  `/etc/systemd/system/pve-container@4214.service.d/srv-media.conf` with:
  - `Requires=srv-media.automount`
  - `After=srv-media.automount network-online.target`
  - `ExecStartPre=/usr/bin/timeout 60 /bin/sh -c 'ls /srv/media >/dev/null 2>&1 && findmnt -t nfs4 /srv/media >/dev/null'`
- `systemctl show` proves the drop-in attaches only to
  `pve-container@4214.service`; `pve-guests.service` has no drop-in and
  Scrypted 1043 remained running.
- Live mount:
  `192.168.68.171:/srv/media`, `nfs4`, `vers=4.2`, `rw`, `hard`, `noatime`,
  `proto=tcp`.
- `srv-media.automount` and `srv-media.mount` are active.
- systemd reports `TimeoutIdleUSec=infinity` for the automount.
- Live behavior established that `stat /srv/media` does not traverse this
  direct automount; the executable plan now uses bounded `ls /srv/media`
  probes instead.

### Read/write and retrigger proof

- A single probe written from `.173` as UID/GID `1000:1000` appeared on pve1
  with owner `1000:1000`, mode `0644`, size `9`, and exact content
  `nfs-probe`.
- The exact probe file was removed and confirmed absent on both nodes.
- A root-created squash probe succeeded because pve1's export root is mode
  `0777`, but it appeared on both nodes as owner `65534:65534`. That ownership,
  not write failure, proves `root_squash` is active. The exact squash probe was
  removed.
- After `systemctl stop srv-media.mount`, autofs remained active; a bounded
  `ls /srv/media` retriggered the same NFSv4 source and returned both units to
  active state.

### Bridge rollback

If migration has not started, the reversible bridge rollback is: stop and
disable `srv-media.automount`, stop `srv-media.mount`, remove only the two
Ragweld units and the `pve-container@4214.service` drop-in, restore the dated fstab
backup, daemon-reload, and rename the dated quarantine back to `/srv/media`
only after confirming the NFS mount is absent and restoring its prior mode. On pve1, remove only
`/etc/exports.d/ragweld-media.exports` and
`/etc/nfs.conf.d/99-ragweld.conf`, then reload `exportfs` and restart NFS.
Do not remove the quarantine or PBS backups during this plan.

## Task 3 — offline LXC migration evidence

- The final destructive-action gate reverified quorum, both fresh PBS backup
  IDs, source ext4 media, `shared=1`, source container health, destination
  NFSv4, destination storage/GPU, Scrypted health, and the 4214-only start
  gate.
- LXC 4214 shut down gracefully and returned `status: stopped`; no force-stop
  was used.
- `pct migrate 4214 pve --target-storage local-lvm` completed successfully in
  `00:04:59`.
- Migration explicitly ignored the shared `/srv/media` bind, copied the full
  32 GiB root LV at approximately 116 MB/s, imported
  `local-lvm:vm-4214-disk-0` on node `pve`, and removed the source LV only
  after successful import.
- Proxmox config ownership then existed only at
  `/etc/pve/nodes/pve/lxc/4214.conf`; the pve1 node copy was absent.
- Stopped destination config preserved:
  - 16 cores, 32000 MiB memory, 2000 MiB swap
  - privileged container with `nesting=1,keyctl=1,fuse=1`
  - fixed IP `192.168.68.214/24`
  - `mp1: /srv/media,mp=/srv/media,shared=1`
  - root disk `local-lvm:vm-4214-disk-0,size=32G`
  - `/dev/dri`, `renderD128`, `/dev/net/tun`, and `/dev/fuse` mappings
- The 4214-only fatal/bounded NFS pre-start gate was present before start.
- Start succeeded. The guest itself—not merely the host—reported
  `192.168.68.171:/srv/media` as `nfs4`, so the bind did not capture the autofs
  stub. Both GPU devices were visible inside the guest.
- All 12 prior containers started; Gluetun reached `healthy`; zero containers
  were restarting; Plex/Sonarr/Radarr/qBittorrent showed no permission,
  `EACCES`, failed-chown, or operation-not-permitted signatures.

## Task 4 — acceptance evidence

### LAN services

Post-migration and post-reboot checks returned an HTTP response for every
expected surface:

- Plex `:32400/web/` -> `302`
- Overseerr `:5055` -> `307`
- Radarr `:7878` -> `302`
- Sonarr `:8989` -> `401`
- Prowlarr `:9696` -> `302`
- qBittorrent `:8080` -> `200`
- Startpage `:8082` -> `200`
- Portainer `:9000` -> `200`
- Portainer TLS `:9443` -> `200`

### Application-user media writes

- Sonarr wrote through `/tv`, Radarr through `/movies`, and qBittorrent
  through `/downloads` as UID/GID `1000:1000`.
- pve1 observed each exact probe in its inventory-derived host directory with
  owner `1000:1000` and the expected content.
- The three exact probe files were removed through their owning containers and
  confirmed absent on pve1.

### Boot-order and shared-resource proof

- Pre-reboot: Grafana 103, Scrypted 1043, and Plex 4214 were running with
  `onboot=1`; Scrypted was active with `renderD128`; Plex's guest NFS was
  `nfs4`; Gluetun was healthy.
- Node `pve` was rebooted once. SSH returned with boot time
  `2026-08-28 08:10:43`.
- After reboot, all three LXCs returned to `running`.
- `pve-guests.service`, `srv-media.automount`, and `srv-media.mount` were
  active. Host and guest views both reported the same NFSv4 source.
- Scrypted remained active with its render device. Plex's container sees
  `/dev/dri/card0` and `/dev/dri/renderD128`.
- All 12 Plex/arr containers returned; Gluetun was healthy; no media-permission
  signatures appeared; all nine LAN HTTP checks still responded.
- W43 is therefore accepted: the Plex-only start gate preserves cameras and
  survives the actual boot-order path.

### Remaining visual acceptance

- The in-app browser loaded the migrated Plex Web UI and reached Plex's
  legitimate authorization screen for `192.168.68.214`.
- That browser has no Plex token/session. No credential, password, or token was
  entered or read.
- A signed-in user must finish the remaining direct-play and forced
  lower-quality transcode interaction in that preserved in-app tab. While it
  runs, capture Plex's hardware-transcode indicator and sanitized `.173`
  video-engine activity. This is the only remaining Plex-plan acceptance
  item before starting Ragweld LXC provisioning.
