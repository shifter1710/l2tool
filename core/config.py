from pathlib import Path

from core.url_guard import validate_external_url

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

    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(item) for item in _split_array_items(inner)]

    if value == "true":
        return True

    if value == "false":
        return False

    try:
        return int(value)
    except ValueError:
        return value


def _split_array_items(inner):
    """Элементы массива: запятые вне кавычек; вложенные массивы не нужны."""
    items = []
    current = []
    quote = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item for item in (entry.strip() for entry in items) if item]


def _strip_comment(line):
    in_string = False

    for index, char in enumerate(line):
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
            return line[:index]

    return line


def parse_simple_toml(text):
    """Разбор TOML без tomllib (Python 3.10): секции, скаляры и плоские массивы.

    Используется и как fallback-валидатор содержимого при импорте config.toml.
    """
    data = {}
    current = data

    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            current = data
            for part in line[1:-1].split("."):
                current = current.setdefault(part.strip(), {})
            continue

        try:
            key, value = line.split("=", 1)
        except ValueError as error:
            raise ValueError(
                f"config.toml: не удалось разобрать строку: {raw_line.strip()!r}"
            ) from error
        current[key.strip()] = _parse_value(value)

    return data


def _read_simple_toml(path):
    return parse_simple_toml(path.read_text(encoding="utf-8"))


def _read_toml(path):
    if tomllib:
        return tomllib.loads(path.read_text(encoding="utf-8"))

    return _read_simple_toml(path)


_CONFIG_CACHE = {}  # (mtime_ns, size) -> разобранный TOML


def load_config(path=None):
    if path:
        return _read_toml(Path(path))

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(MISSING_CONFIG_MESSAGE)

    stat = CONFIG_PATH.stat()
    cache_key = (str(CONFIG_PATH), stat.st_mtime_ns, stat.st_size)
    cached = _CONFIG_CACHE.get(cache_key)
    if cached is None:
        cached = _read_toml(CONFIG_PATH)
        _CONFIG_CACHE.clear()
        _CONFIG_CACHE[cache_key] = cached
    return cached


def config_value(key_path, default=None):
    value = load_config()

    for key in key_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]

    return value


def optional_value(key_path, default=None):
    """Значение из config.toml; нет файла или секции — значение по умолчанию.

    Для настроек, которые работают и без config.toml (динамические блоки):
    окна, наборы сервисов, лимиты.
    """
    try:
        return config_value(key_path, default)
    except (OSError, ValueError):
        return default


def feature_enabled(name):
    """Фича-тогл из секции [features] локального config.toml.

    Функции выключены по умолчанию и включаются явно, например:
    [features] runbook = true
    """
    return optional_value(f"features.{name}", False) is True


def service_url(name):
    url = config_value(f"services.{name}.url")
    return validate_external_url(url, what=f"ссылка сервиса «{name}» из config.toml")


def service_index_pattern(name):
    return config_value(f"services.{name}.index_pattern")


def service_minutes_before(name, default=2):
    return config_value(f"services.{name}.minutes_before", default)


def service_minutes_after(name, default=90):
    return config_value(f"services.{name}.minutes_after", default)


def service_time_from(name):
    return config_value(f"services.{name}.time_from")


def service_time_to(name):
    return config_value(f"services.{name}.time_to")


def default_env():
    return config_value("defaults.env")


def grafana_find_call_dashboard():
    return validate_external_url(
        config_value("grafana.find_call_dashboard"),
        what="ссылка grafana.find_call_dashboard из config.toml",
    )


def grafana_org_id():
    return config_value("grafana.org_id")


def grafana_env():
    return config_value("grafana.env", default_env())


def grafana_env_cluster():
    return config_value("grafana.env_cluster", default_env())


def grafana_recording_loki_datasource_uid():
    return config_value("grafana.recording.loki_datasource_uid")


def opensearch_base_url():
    return validate_external_url(
        config_value("opensearch.base_url"),
        what="ссылка opensearch.base_url из config.toml",
    )


def opensearch_index_pattern(name):
    return config_value(f"opensearch.index_patterns.{name}")
