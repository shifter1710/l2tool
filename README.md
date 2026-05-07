# l2tool

L2 ticket helper CLI.

## Default workflow

Paste the current ticket into:

```text
tickets/current.txt
```

Then run:

```bash
python3 gtool.py
```

Default behavior:

- reads `tickets/current.txt`
- opens `zapis,bff,myconnect,myconnect_call`
- uses a 120 minute Grafana window
- prints local history matches
- saves a new local history YAML under `history/`
- opens generated links in the browser

Useful overrides:

```bash
python3 gtool.py --file tickets/other.txt
python3 gtool.py --open zapis,bff
python3 gtool.py --window 60
python3 gtool.py --dry-run
python3 gtool.py --no-history
```

## Modules

- `zapis` - search call logs in the Grafana dashboard `find-call-in-logs`.
- `bff` - search BFF logs in OpenSearch.
- `myconnect` - search `profile not found` cases in MyConnect.
- `myconnect_call` - search MyConnect logs for an attached/problem call using `master:<msisdn>` and SIP participant.

Legacy aliases are still accepted: `grafana`, `logs`, `find_call_in_logs`,
`bff_logs_opensearch`, `profile_not_found_myconnect`, `attached`, and
`attached_call_myconnect`.

## Local history

History is local-only and ignored by git:

```text
history/YYYY/MM/YYYY-MM-DD_<main_number>_<shortid>.yaml
history/index.json
```

Use `--dry-run` to print parsed context, history matches, and generated links
without opening browser links or saving history. Use `--no-history` to skip only
new history YAML saving.
