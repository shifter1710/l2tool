# l2tool

L2 ticket helper CLI.

## Modules

- `find_call_in_logs` - search call logs in the Grafana dashboard `find-call-in-logs`.
- `bff_logs_opensearch` - search BFF logs in OpenSearch.
- `profile_not_found_myconnect` - search `profile not found` cases in MyConnect.
- `attached_call_myconnect` - search MyConnect logs for an attached/problem call using `master:<msisdn>` and SIP participant.

Legacy aliases are still accepted: `grafana`, `logs`, `myconnect`, and `attached`.
