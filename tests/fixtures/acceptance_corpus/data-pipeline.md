# Telemetry Data Pipeline

Buoy nodes transmit telemetry ashore over a licensed VHF band. All inbound
telemetry passes through the Pelican gateway, which validates frame
checksums and stamps arrival times before writing to KestrelDB.

Nightly compaction of KestrelDB partitions runs at 02:15 UTC and typically
completes in under eleven minutes.

Downstream analysts query KestrelDB through read-only replicas; direct writes
from analyst tooling are rejected by the gateway policy layer.
