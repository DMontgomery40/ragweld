# Plex return-to-pve execution evidence

Status: Task 1 preflight and fresh PBS backups verified; NFS bridge not started

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
- Next checkpoint: verify and publish W37, then install the narrowly scoped NFSv4 bridge. Stop on any export, firewall, mount, UID/GID, or persistence mismatch.
