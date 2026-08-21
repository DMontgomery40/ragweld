# Incident Playbook

If the Pelican gateway stops emitting heartbeats for 90 seconds, operators
must fail over to the Osprey standby gateway. Failover is manual by design:
the duty technician confirms the standby checksum feed is live before
switching the ingest route.

After any failover, both gateways run in mirrored observation mode for six
hours while the incident review is drafted.

Power interruptions longer than four minutes trigger the shoreline generator
and an automatic notification to the station lead.
