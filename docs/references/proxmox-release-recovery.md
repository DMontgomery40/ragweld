# Proxmox release artifacts and recovery drills

Ragweld runs in LXC100 on pve1. Run every command below inside LXC100;
the Mac checkout is source only. These tools do not restart Ragweld, replace
its checkout, change networks, or touch production volumes. Release and drill
directories are private operational evidence, not files to publish or commit.

## Seal a release after the final build

Finish the coordinated source commit and build on LXC100, then seal that clean
Git commit and its prepared `web/dist`. A tracked source edit during capture
fails the command. The tool checks for concurrent source, lockfile, and frontend
changes and refuses to overwrite any existing output directory.

```bash
cd /opt/ragweld
# Run the final locked dependency/build and acceptance gates first.
release_id="$(git rev-parse HEAD)"
.venv/bin/python deploy/proxmox/release_artifact.py seal \
  --output "/srv/ragweld/releases/$release_id" \
  --backup-reference /srv/ragweld/backups/20260927T043730Z \
  --config /etc/ragweld/tribrid_config.json \
  --config /etc/ragweld/runtime.env \
  --config /etc/ragweld/litellm.env \
  --config /etc/ragweld/langfuse.env
.venv/bin/python deploy/proxmox/release_artifact.py verify \
  "/srv/ragweld/releases/$release_id"
```

The bundle preserves the exact committed source archive, built frontend archive,
source SHA/tree, lockfile hashes, every web asset hash, running Compose image IDs
and repository digests, backup reference, and private configuration **hashes**.
It does not copy secret values from `/etc/ragweld`. `images.compose.json` is a
digest-pinned Compose override using locally present images and `pull_policy:
never`. It is only applied explicitly by the owner; the ordinary launcher does
not read it. Retain the matching images or export them separately before image
garbage collection; recorded digests alone do not preserve image bytes.

Frontend provenance is explicitly `captured-prebuilt-assets`: the artifact
reproduces the captured deployed files byte for byte, but cannot retrospectively
prove which source produced an already existing build. The integration owner
records the successful build at the same clean SHA before the final seal.
The directory and contents are read-only after sealing. Checksums detect
corruption, not malicious replacement by an actor who can rewrite both manifest
and checksum; retain independent backup copies and access controls.

## Prove apply and rollback materialization

Materialization verifies all artifact hashes, extracts only ordinary files and
directories into a **new** directory, and checks the reconstructed frontend and
lockfiles. It fails on archive traversal, symlinks, special files, or an existing
destination. There is no force/overwrite option and no checkout/reset command.

```bash
.venv/bin/python deploy/proxmox/release_artifact.py materialize \
  "/srv/ragweld/releases/$release_id" \
  "/srv/ragweld/release-staging/$release_id"
```

The same command materializes the previous known-good release for rollback.
`RELEASE-MANIFEST.json` identifies the reconstructed source and assets. Recreate
dependencies using that release's `uv.lock` (`uv sync --frozen`) and
`web/package-lock.json` (`npm ci --prefix web`) on the intended Linux runtime.
The packaged frontend needs no rebuild when restoring the captured assets.

Production activation remains an explicit integration step because `/opt/ragweld`
currently mixes committed source, `.venv`, secret symlinks, and mutable files
under `data/`. Do not replace that whole directory with an archive. The owner:

1. Records the current and target release SHA, checks the current restore proof,
   and verifies both release bundles. Reject rollback across an incompatible
   database schema; restore is a separately authorized data operation.
2. Materializes the target into its new staging directory and verifies it.
3. Preserves the current served `web/dist` by renaming it to a unique sibling,
   places the staged `web/dist` at the original path, and checks `/` plus each
   referenced asset. Reversing those two directory moves restores the prior
   frontend without deleting either tree. Run under the runtime user so mode
   and ownership remain suitable for the serving process.
4. For a bounded rollback drill, stops the service, records the clean canonical
   HEAD, and restores tracked paths and the index from the verified release SHA
   with `git restore --source <release-sha> --staged --worktree -- .`.
   `git write-tree` must equal the sealed `git_tree`; the deployment marker records
   the activated release SHA while canonical HEAD remains unchanged. Returning to
   the canonical release uses the same explicit restore operation from the
   recorded HEAD and must leave the tracked checkout clean. Restore locked
   dependencies if either lockfile changed. Preserve all untracked runtime state,
   secrets and volumes; never use a hard reset, `git clean`, or a recursive
   copy/delete across runtime state. If exact source parity cannot be
   established, stop before activation. A permanent rollback is a reviewed
   revert commit on canonical main, rather than an indefinitely dirty checkout.
5. Uses the normal owner-controlled service restart, then verifies liveness,
   readiness, authenticated browser behavior, and a real corpus question. If it
   fails, restores the previously preserved frontend and reviewed source release
   and repeats those checks. No database volume rollback is implicit.

Materialization is independently testable and non-destructive. An exercised
materialization is not evidence of a completed production rollback; record the
actual activation/reversal separately when the integration owner runs it.

## Run the isolated core-store restore drill

```bash
cd /opt/ragweld
.venv/bin/python deploy/proxmox/restore_drill.py \
  /srv/ragweld/backups/20260927T043730Z \
  --evidence-dir /srv/ragweld/restore-drills/UNIQUE-RUN-ID
```

The tool verifies the complete `SHA256SUMS` inventory before starting anything.
It then runs PostgreSQL, Qdrant, and Neo4j sequentially using the exact image IDs
of the currently running stores. It restores to new uniquely named/labeled
volumes. PostgreSQL and Neo4j have no network; Qdrant has a random loopback-only
HTTP port on the existing bridge. Maximum per-container memory is 512 MiB,
1 GiB, and 2 GiB respectively, with two CPUs and a PID limit. The hostname is
explicitly `localhost` so Neo4j can resolve its hostname with networking off.

The evidence includes every backup checksum, image IDs, restored table/collection
counts, graph node/relationship counts, and cleanup status. It never outputs
database rows or secret values. Cleanup removes only names created in that run,
after checking their ownership labels. Failed restore evidence is retained.
An abrupt host kill can leave disposable resources: inspect the exact
`ragweld.restore-drill` label before manually removing them. Do not use broad
Docker prune commands. No existing backup, container, or volume is removed.

This proves core data can be read after restore; it does not prove point-in-time
consistency across stores. The existing backup captures stores sequentially.
MLflow and Langfuse payloads are checksum/inventory verified only by this drill;
the drill does not claim to have started their restored applications. Secret
configuration and application filesystem state require the separately retained
LXC/PBS backup. Do not treat logical-store recovery as complete host recovery.

## Recorded proof: 2026-09-27

Backup: `/srv/ragweld/backups/20260927T043730Z`.
Evidence: `/srv/ragweld/restore-drills/20260927-readiness-v2/evidence.json`.
All 14 data files passed SHA-256 verification. PostgreSQL restored 9 tables and
32,633 rows (11,678 chunks, 2,922 documents, 5 corpora). Qdrant restored all
8 snapshot collections containing 22,898 points. Neo4j restored 47,825 nodes
and 113,466 relationships. Disposable container and volume cleanup was verified.
MLflow and Langfuse remain inventory/checksum proof at this checkpoint.

The first drill failed at Neo4j startup with network disabled and an unresolvable
generated hostname. The explicit localhost hostname fixed that isolated startup;
the first run also removed all its disposable resources. No live service was
stopped or restarted by either drill.
