"""Проверка ссылок и секретов в конфигурациях.

Конфигурации l2tool переносятся между компьютерами одним файлом, поэтому
URL из config.toml проверяются так же строго, как ссылки динамических
блоков: только http(s), без логина/пароля и без ключей доступа. Проверка
структурная — имена ключей TOML и параметры ссылок разбираются, а не
ищутся одним регулярным выражением.
"""

import re
from urllib.parse import unquote, urlsplit

# Слова в именах ключей и параметров, похожих на секреты. Имя нормализуется
# (регистр и разделители схлопываются в «_») и сверяется по словам, поэтому
# «secretary_numbers» не совпадает с «secret», а «X-Auth-Token» — совпадает.
_SENSITIVE_WORDS = {
    "token",
    "key",
    "secret",
    "password",
    "passwd",
    "auth",
    "session",
    "bearer",
    "signature",
    "credential",
    "credentials",
    "authorization",
}
# camelCase-имена («accessToken», «apiKey») схлопываются в одно слово —
# их ловим по окончанию нормализованного имени.
_SENSITIVE_ENDINGS = (
    "token",
    "key",
    "secret",
    "password",
    "passwd",
    "auth",
    "signature",
    "credential",
    "credentials",
)
# Одиночный ключ «key» слишком общий (ключ продукта), чтобы запрещать.
_NON_SENSITIVE_NAMES = {"key"}

# URL внутри текста конфигурации: схема://до-пробела-или-кавычки.
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>`]+")
# Имена параметров: «?name=», «&name=», «;name=», rison/JSON «(name:», «"name":».
_PARAM_LIKE_NAMES = re.compile(r"[?&;]([A-Za-z0-9_.\-]+)\s*[=:]")
_JSON_LIKE_NAMES = re.compile(r"[,{(]\s*\"?([A-Za-z0-9_.\-]+)\"?\s*:")
# Строка TOML «key = value» (в том числе ключ в кавычках и с точками).
_TOML_KEY_LINE = re.compile(r"^\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_.\-]+))\s*=")
# Строковые значения TOML: «key = "value"», массивы «["a", 'b']».
_TOML_STRING_VALUE = re.compile(r"\"([^\"]*)\"|'([^']*)'")
# Схемы, исполняющие код или читающие локальные файлы; допустимы и без «//».
_DANGEROUS_SCHEME = re.compile(r"^(?:javascript|data|vbscript|file|about|blob):", re.IGNORECASE)

_MAX_DECODE_ROUNDS = 3
_MAX_ISSUES = 5


def _normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def is_sensitive_name(name):
    """Похоже ли имя ключа или параметра на секрет («api_key», «X-Auth-Token»)."""
    normalized = _normalize_name(name)
    if not normalized or normalized in _NON_SENSITIVE_NAMES:
        return False
    if set(normalized.split("_")) & _SENSITIVE_WORDS:
        return True
    return normalized.endswith(_SENSITIVE_ENDINGS)


def validate_external_url(url, *, what="Ссылка"):
    """Ссылки диагностики открываются в браузере — только http(s) без паролей.

    Пустое значение — не ошибка: необязательные сервисы остаются пустыми.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{what} должна начинаться с http:// или https://")
    if parts.username or parts.password:
        raise ValueError(f"Удалите логин и пароль из {what.lower()}")
    return url


def _fully_decode(value):
    for _ in range(_MAX_DECODE_ROUNDS):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def find_url_secrets(url):
    """Секреты внутри одной ссылки: userinfo и ключи в query/фрагменте.

    Ловит имена параметров и ключей состояния Grafana/OpenSearch (в том
    числе percent-кодированные); возвращает список описаний находок.
    """
    findings = []
    parts = urlsplit(url)
    if parts.username or parts.password:
        findings.append("логин/пароль в ссылке (user:pass@host)")
    decoded = _fully_decode(url)
    names = set(_PARAM_LIKE_NAMES.findall(decoded))
    names.update(_JSON_LIKE_NAMES.findall(decoded))
    hits = sorted({name for name in names if is_sensitive_name(name)})
    if hits:
        findings.append("похоже на ключ доступа: " + ", ".join(hits))
    return findings


def find_text_secrets(text):
    """Секреты в тексте TOML-конфигурации: ключи и ссылки с учётными данными."""
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        key_match = _TOML_KEY_LINE.match(line)
        if key_match:
            key = next(group for group in key_match.groups() if group is not None)
            if is_sensitive_name(key):
                findings.append(f"строка {line_number}: ключ «{key}» похож на секрет")
        for url in _URL_IN_TEXT.findall(line):
            for finding in find_url_secrets(url):
                findings.append(f"строка {line_number}: {finding} — «{url[:100]}»")
    return findings


def _string_values(text):
    for line in text.splitlines():
        for match in _TOML_STRING_VALUE.finditer(line):
            yield next(group for group in match.groups() if group is not None)


def find_config_issues(text):
    """Все проблемы config.toml: секреты и неподдерживаемые схемы ссылок."""
    issues = find_text_secrets(text)
    candidates = list(_URL_IN_TEXT.findall(text))
    candidates.extend(
        value for value in _string_values(text) if _DANGEROUS_SCHEME.match(value)
    )
    for url in candidates:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            issues.append(
                f"ссылка со схемой «{parts.scheme}» не поддерживается — «{url[:100]}»"
            )
    return issues[:_MAX_ISSUES]
