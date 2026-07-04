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
- asks which product profile to use in an interactive terminal
- uses `zapis,sip_stack,bff,myconnect,myconnect_call` when stdin is not interactive
- uses a 120 minute Grafana window
- prints generated links to stdout

Useful overrides:

```bash
python3 gtool.py --file tickets/other.txt
python3 gtool.py --product recording
python3 gtool.py --window 60
```

Fast mode without the menu:

```bash
python3 gtool.py --product recording
```

Expert mode:

```bash
python3 gtool.py --open zapis,bff
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
