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
- prints prior local history matches
- prints generated links to stdout
- opens generated links in the browser
- saves a local YAML archive under `history/`

Useful overrides:

```bash
python3 gtool.py --file tickets/other.txt
python3 gtool.py --open zapis,bff
python3 gtool.py --window 60
python3 gtool.py --no-history
python3 gtool.py --dry-run
```

## Case JSON export

Use `--export-case` to save the parsed ticket context and generated links to a
structured JSON file for later handoff to `l2-local-ai`:

```bash
python3 gtool.py --file tickets/current.txt --product recording --export-case cases/current.json
```

The export contains normalized identifiers, event date/time, selected modules,
and generated links. It does not include the original ticket text, raw phone
fields, absolute local paths, config contents, tokens, cookies, or environment
variables.

Case JSON files can contain customer numbers and internal links. The `cases/`
directory is ignored by Git.

Product profile mode:

```bash
python3 gtool.py --product recording
```

`--dry-run` parses the ticket, prints history matches and generated links, but
does not save history and does not open browser links.

## Config

Default config values are stored in `config.example.toml`. Before running the
tool, copy it to `config.toml` and fill real values in the local file:

```bash
cp config.example.toml config.toml
```

`config.toml` is ignored by git and is not committed.

## Modules

- `zapis` - search call logs in the Grafana dashboard `find-call-in-logs`.
- `sip_stack` - search SIP stack logs in OpenSearch by client `msisdn`.
- `bff` - search BFF logs in OpenSearch.
- `myconnect` - search `profile not found` cases in MyConnect.
- `myconnect_call` - search MyConnect logs for an attached/problem call using `master:<msisdn>` and SIP participant.
