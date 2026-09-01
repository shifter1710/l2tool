from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config.toml"
EXAMPLE_CONFIG_PATH = ROOT_DIR / "config.example.toml"
MISSING_CONFIG_MESSAGE = (
    "Config file config.toml not found. "
    "Copy config.example.toml to config.toml and fill real values."
)


def _parse_value(raw_value):
    value = raw_value.strip()

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value == "true":
        return True

    if value == "false":
        return False

    try:
        return int(value)
    except ValueError:
        return value


def _strip_comment(line):
    in_string = False

    for index, char in enumerate(line):
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
            return line[:index]

    return line


def _read_simple_toml(path):
    data = {}
    current = data

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            current = data
            for part in line[1:-1].split("."):
                current = current.setdefault(part.strip(), {})
            continue

        key, value = line.split("=", 1)
        current[key.strip()] = _parse_value(value)

    return data


def _read_toml(path):
    if tomllib:
        return tomllib.loads(path.read_text(encoding="utf-8"))

    return _read_simple_toml(path)


def load_config(path=None):
    if path:
        return _read_toml(Path(path))

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(MISSING_CONFIG_MESSAGE)

    return _read_toml(CONFIG_PATH)


def config_value(key_path, default=None):
    value = load_config()

    for key in key_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]

    return value


def service_url(name):
    return config_value(f"services.{name}.url")


def service_index_pattern(name):
    return config_value(f"services.{name}.index_pattern")


def service_minutes_before(name, default=2):
    return config_value(f"services.{name}.minutes_before", default)


def service_minutes_after(name, default=90):
    return config_value(f"services.{name}.minutes_after", default)


def default_env():
    return config_value("defaults.env")


def grafana_find_call_dashboard():
    return config_value("grafana.find_call_dashboard")


def grafana_org_id():
    return config_value("grafana.org_id")


def grafana_env():
    return config_value("grafana.env", default_env())


def grafana_env_cluster():
    return config_value("grafana.env_cluster", default_env())


def grafana_recording_loki_datasource_uid():
    return config_value("grafana.recording.loki_datasource_uid")


def opensearch_base_url():
    return config_value("opensearch.base_url")


def opensearch_index_pattern(name):
    return config_value(f"opensearch.index_patterns.{name}")
