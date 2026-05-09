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

## Windows app

Run the GUI next to the CLI:

```bash
python gui.py
```

The window lets you paste a ticket, choose modules, generate links, save local
history, and open the generated links.

On Windows, build a standalone app with:

```bat
build_windows.bat
```

The executable is created at:

```text
dist\l2tool.exe
```

GitHub Actions also builds the Windows executable automatically. Open:

```text
GitHub -> Actions -> Build Windows EXE -> latest run -> Artifacts -> l2tool-windows-exe
```

For a release download, push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow attaches `l2tool.exe` to that GitHub Release.

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
