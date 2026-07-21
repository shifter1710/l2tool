# l2tool

L2 ticket helper CLI.

## Requirements

- Python 3.10 or newer (CI runs on Python 3.12)
- access to the Grafana and OpenSearch instances configured for your environment

Install the runtime dependency:

```bash
python3 -m pip install -r requirements.txt
```

## Setup

Create the local configuration from the supplied template:

```bash
cp config.example.toml config.toml
```

Replace every example URL, environment name, organization ID, and index pattern
in `config.toml` with values for your environment. The local file is ignored by
git and must not be committed.

Create the local ticket directory, which is also ignored by git:

```bash
mkdir -p tickets
```

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
- prompts for a product and selects its configured modules
- uses a 120 minute Grafana window
- prints prior local history matches
- prints generated links without opening a browser
- saves a local YAML archive under `history/`
- overwrites `tickets/current.parsed.json` with normalized values, generated
  links, and an empty `call_uuid` field for subsequent investigation

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

Every successful run also writes the same structure automatically next to the
input ticket. For `tickets/current.txt`, the sidecar path is
`tickets/current.parsed.json`. The original ticket remains unchanged. Sidecar
files match `*.parsed.json` and are ignored by Git.

Product profile mode:

```bash
python3 gtool.py --product recording
```

Available product profiles:

| Profile | Product | Modules |
| --- | --- | --- |
| `recording` | Запись | `zapis`, `sip_stack`, `bff` |
| `secretary` | Секретарь | `bff` |
| `calls` | Звонки | `myconnect`, `myconnect_call` |
| `noise` | Шумоподавление | not configured yet |
| `assistant` | Ассистент в звонке | not configured yet |

Use either `--product` or `--open`; the options cannot be combined. Pass
`--open all` to run every configured module. When neither option is supplied in
an interactive terminal, the tool displays the product menu. Non-interactive
runs use `zapis,bff,myconnect,myconnect_call` by default.

`--dry-run` parses the ticket, prints history matches and generated links, but
does not save history or write parser diagnostics.

To verify the setup without using a real ticket:

```bash
python3 gtool.py --file examples/ticket.example.txt --product recording --dry-run
```

## Local data and privacy

Ticket data can contain phone numbers and other sensitive information. The tool
stores the following data locally:

- `tickets/` contains ticket text supplied by the user.
- `*.parsed.json` sidecars contain normalized identifiers, generated links, and
  a blank `call_uuid` field. Each run overwrites the sidecar for its input file.
- `history/` contains YAML archives with the original ticket text, parsed
  fields, generated links, and phone numbers. The primary phone number is also
  included in each archive filename.
- `history/index.json` indexes archive paths by phone number.
- `parser_issues/parser_issues.jsonl` records unparsed source lines when parser
  diagnostics are produced.

These paths are ignored by git. `--no-history` prevents creation of a history
archive but does not disable parser diagnostics. Use `--dry-run` when neither
history nor parser diagnostics should be written.

## Modules

- `zapis` - search call logs in the Grafana dashboard `find-call-in-logs`.
- `sip_stack` - search SIP stack logs in OpenSearch by client `msisdn`.
- `bff` - search BFF logs in OpenSearch.
- `myconnect` - search `profile not found` cases in MyConnect.
- `myconnect_call` - search MyConnect logs for an attached/problem call using
  `master:<msisdn>` and the SIP participant.

## Development

Install the test dependency and run the test suite:

```bash
python3 -m pip install pytest
python3 -m pytest -q
```
