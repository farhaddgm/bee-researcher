# Bee CFO v3.5.1

This safety patch makes the source-decision ledger authoritative for live price
delivery. An active catalog source is no longer sufficient to fetch or publish
a quote. The latest workspace decision for the exact indicator/source pair must
be `approved`, its UAT must be `passed`, and any expiry must still be in the
future. Read-only source probes remain available to complete UAT; the patch
does not activate sources, markets, scheduling, or publishing.

The change is contained in the Bee CFO bounded context. It adds no migration
and does not modify Bee Researcher or Consultant data, queues, configuration,
or runtime paths.
