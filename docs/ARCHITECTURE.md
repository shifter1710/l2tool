# Архитектура l2tool

Документ описывает устройство сервиса целиком: точки входа, слои, потоки
данных, хранилища и модель безопасности. Схемы выполнены в Mermaid и
рендерятся на GitHub. При изменении архитектуры обновляйте этот файл вместе
с кодом.

## 1. Общий контекст

l2tool — локальный инструмент специалиста L2-поддержки. Он разбирает текст
заявки, нормализует телефоны, даты и регион, а затем собирает готовые ссылки
на Grafana и OpenSearch. Ключевая особенность: **сам инструмент не ходит в
Grafana и OpenSearch по API** — он только формирует URL; переход выполняет
браузер пользователя с его же правами и куками.

```mermaid
flowchart LR
    user(["Специалист L2"])

    subgraph local["Локальный компьютер специалиста"]
        browser["Браузер<br/>127.0.0.1:8765"]
        webapp["webapp.py<br/>FastAPI + uvicorn"]
        cli["gtool.py · lost_calls_table.py<br/>CLI"]
        store["Локальные данные:<br/>config.toml · diagnostic_sources.json<br/>tickets/ · history/ · cases/<br/>parser_issues/ · *.parsed.json"]
    end

    subgraph obs["Observability-стенд (внутренний)"]
        grafana["Grafana<br/>дашборды + Explore / Loki"]
        opensearch["OpenSearch Dashboards<br/>Discover"]
    end

    user -->|"вставляет текст заявки"| browser
    user -->|"файл заявки / выгрузка"| cli
    browser -->|"HTTP только localhost"| webapp
    cli --> store
    webapp --> store
    browser -.->|"переход по сформированной ссылке"| grafana
    browser -.->|"переход по сформированной ссылке"| opensearch
```

## 2. Слои и компоненты

Код разделён на три слоя. `core/` — доменная логика (разбор заявки, время,
история, экспорт), `services/` — сборка URL под конкретную платформу,
`modules/` — диагностические запросы: что и по каким полям искать в каждом
сервисе. Точки входа не зависят от реализации сервисов: CLI получает модули
через реестр `services/registry.py`, веб — переиспользует `run_ticket` из
`gtool.py`.

```mermaid
flowchart TB
    subgraph entries["Точки входа"]
        webapp["webapp.py<br/>веб-интерфейс (FastAPI, port 8765)"]
        gtool["gtool.py<br/>CLI: заявка → ссылки, история, case JSON"]
        lostcli["lost_calls_table.py<br/>CLI: пакетная обработка выгрузок"]
    end

    subgraph core["core/ — доменная логика"]
        direction TB
        parser["parser.py + ticket_fields.py<br/>разбор полей заявки"]
        timetz["timezones.py + time_windows.py<br/>регион → таймзона · UTC-окна"]
        products["products.py<br/>профили продуктов"]
        dynamic["dynamic_sources.py<br/>пользовательские блоки<br/>diagnostic_sources.json"]
        history["history.py<br/>YAML-архивы + index.json"]
        caseexp["case_export.py<br/>case JSON для l2-local-ai"]
        pdiag["parser_diagnostics.py<br/>parser_issues.jsonl"]
        lostcore["lost_calls_table.py<br/>очистка выгрузок + ссылки"]
        config["config.py<br/>чтение config.toml"]
    end

    subgraph services["services/ — сборка URL по платформам"]
        registry["registry.py<br/>реестр 11 сервисов"]
        grafanaurl["grafana.py<br/>слияние параметров дашборда"]
        lokiurl["loki_explore.py<br/>Grafana Explore URL"]
        osurl["opensearch.py<br/>Discover URL, периоды поиска"]
    end

    subgraph modules["modules/ — 11 диагностических модулей"]
        primary["zapis · sip_stack · bff · secretary<br/>myconnect · myconnect_call · noise"]
        recording["recording_mgw · recording_vss_crs<br/>recording_crs · recording_collector<br/>требуют call UUID"]
    end

    webapp --> gtool
    webapp --> dynamic
    webapp --> lostcore
    gtool --> parser
    gtool --> history
    gtool --> caseexp
    gtool --> pdiag
    gtool --> registry
    lostcli --> lostcore
    parser --> timetz
    dynamic --> products
    dynamic --> osurl
    registry --> primary
    primary --> grafanaurl
    primary --> lokiurl
    primary --> osurl
    recording --> lokiurl
    lokiurl --> config
    osurl --> config
    grafanaurl --> config
    lostcore --> primary
```

## 3. Разбор заявки (core/parser.py)

Парсер превращает произвольный текст заявки в словарь контекста `ctx`, на
котором работают все модули. Поля извлекаются построчными регулярками из
`ticket_fields.py`; номера нормализуются к формату `7XXXXXXXXXX`; даты и
времена поддерживаются в нескольких форматах, включая русские месяцы и
компактные даты `ddMMyyyy`.

```mermaid
flowchart TB
    text["Текст заявки"] --> fields["extract_ticket_fields<br/>8 полей: phone_a · phone_b · msisdn<br/>event_datetime · event_date · event_time<br/>region · submitted_at"]
    fields --> phones["Нормализация номеров<br/>10 цифр → 7… · 8… → 7…<br/>частичный номер 7XXX…<br/>«не указан» / «все» → пусто"]
    fields --> dates["Даты и время<br/>dd.mm.yyyy · диапазоны дат<br/>«12 марта 2026» · ddMMyyyy<br/>с HH:ММ до HH:ММ · несколько времён"]
    phones --> scope["Классификация<br/>общая проблема: «вчера», «все время»<br/>→ прошлый день 08:00–20:00"]
    dates --> scope
    fields --> submitted["submitted_at (МСК) → локальная дата<br/>для заявок «только время»"]
    submitted --> ctx["ctx: нормализованные поля,<br/>event_datetimes[], event_time_range,<br/>problem_scope, region"]
    ctx --> tz["timezones.resolve_timezone(region)<br/>≈80 регионов России → IANA-зона<br/>по умолчанию Europe/Moscow"]
```

Результаты разбора проверяются `core/parser_diagnostics.py`: нераспознанные
номера и даты попадают в `parser_issues/parser_issues.jsonl`, а заявка без
корректных полей не доходит до сборки ссылок.

## 4. Поток веб-диагностики `/analyze`

Веб-форма отправляет текст заявки, продукт и окно поиска. Дальше развилка:
если для продукта созданы пользовательские блоки (`diagnostic_sources.json`),
работает динамический конструктор; иначе — статический профиль из
`config.toml` через модули.

```mermaid
sequenceDiagram
    participant B as Браузер
    participant W as webapp.py
    participant P as core/parser.py
    participant D as core/dynamic_sources.py
    participant G as gtool.run_ticket
    participant M as modules/*
    participant H as core/history.py

    B->>W: POST /analyze (текст, продукт, окно, правки, CSRF)
    W->>W: validate_csrf · parse_window · validate_product
    alt есть пользовательские блоки (is_managed)
        W->>G: run_ticket(parse_text с правками полей)
        G->>P: parse + таймзона + диагностика полей
        G-->>W: ctx (ошибки разбора → failed)
        W->>D: build_product_links(product, "number", ctx)
        D-->>W: ссылки, названия, ошибки блоков
    else статический профиль config.toml
        W->>G: run_ticket(open=модули продукта)
        G->>P: parse + таймзона + диагностика полей
        G->>H: find_matches по index.json
        G->>M: build(ctx) для каждого модуля
        M-->>G: готовые URL
        G-->>W: RunResult(status: success/partial/failed)
    end
    opt успех + галочка «сохранить историю»
        W->>H: save_ticket_history → YAML + index.json
    end
    W-->>B: index.html: поля, предупреждения, ссылки,<br/>совпадения истории, формы правок и UUID-этапа
```

## 5. Динамические источники (конструктор блоков)

Страница «Настройки источников» позволяет собрать собственный диагностический
блок из одной вставленной ссылки. Ссылка классифицируется по платформе, в ней
находится пример номера или UUID, и сохраняется стратегия подстановки.

```mermaid
flowchart TB
    form["Форма блока:<br/>название · продукт · уровень<br/>пример ссылки · значение-пример<br/>окно в минутах"] --> validate["validate_source"]

    subgraph classify["Классификация ссылки"]
        platform{"Что в ссылке?"}
        os["OpenSearch Discover<br/>извлечь indexPattern из фрагмента"]
        dash["Grafana дашборд<br/>путь /d/… или /d-solo/…"]
        explore["Grafana Explore<br/>параметры panes / left (JSON)"]
    end

    validate --> platform
    platform -->|indexPattern найден| os
    platform -->|/d/ в пути| dash
    platform -->|"panes / left"| explore

    subgraph strategy["Стратегия подстановки — _detect_samples"]
        s1["raw — полный номер 7XXXXXXXXXX"]
        s2["national — номер без семёрки"]
        s3["hash16 — sha256-хеш, первые 16 знаков"]
        s4["uuid — UUID целиком"]
        s5["compact_uuid — UUID без дефисов"]
    end

    os --> strategy
    dash --> strategy
    explore --> strategy
    strategy --> store["diagnostic_sources.json<br/>атомарная запись, права 0600,<br/>продукт попадает в managed_products"]

    subgraph runtime["При диагностике: build_source_links"]
        numbers["уровень number:<br/>1 слот → ссылка на каждый номер заявки<br/>2 слота → номера А и Б"]
        uuids["уровень uuid:<br/>замена примера на UUID звонка"]
        timerange["временной диапазон:<br/>Grafana — UTC-окна из заявки<br/>OpenSearch — Europe/Moscow ± минуты блока"]
    end

    store --> numbers
    store --> uuids
    numbers --> timerange
    uuids --> timerange
    timerange --> links["Готовые ссылки продукта"]
```

Импорт и экспорт конфигурации: экспорт отдаёт текущий `diagnostic_sources.json`
как скачиваемый файл; импорт валидирует все блоки целиком, добавляет новые и
пропускает точные дубликаты (совпадают название, продукт, уровень и ссылка).

## 6. Вторичная диагностика по UUID

После первичной диагностики продукта «Запись», когда UUID звонка уже найден,
запускается отдельный этап. Динамическим продуктам доступны их UUID-блоки;
статическому профилю «Запись» — цепочка модулей Loki.

```mermaid
flowchart TB
    start["POST /secondary<br/>effective_text + call_uuid"] --> kind{Продукт}
    kind -->|"пользовательские блоки"| dyn["build_product_links(level=uuid)<br/>по блокам из diagnostic_sources.json"]
    kind -->|"статический профиль «Запись»"| mode{"Режим"}
    mode -->|mgw| mgw["recording_mgw<br/>unit=mgw.service"]
    mode -->|pipeline| chain["recording_mgw → recording_vss_crs<br/>→ recording_crs → recording_collector"]
    mgw --> loki["loki_explore: строится Explore URL<br/>селектор + фильтр по UUID | json<br/>окно из заявки, иначе последний час"]
    chain --> loki
    dyn --> out["Ссылки второго этапа на странице"]
    loki --> out
```

CLI-эквивалент: `gtool.py --open recording_mgw,… --call-uuid …`.

## 7. Пакетная обработка потерянных звонков

Отдельный сценарий для табличных выгрузок (XLSX, XLSM, CSV, TSV), доступный
из веба (`POST /batch`) и CLI (`lost_calls_table.py`).

```mermaid
flowchart TB
    input["Таблица с колонками:<br/>Номер пользователя · Номер другой стороны<br/>Старт звонка (UTC) · Продолжительность · Направление"] --> resolve["resolve_headers:<br/>псевдонимы RU/EN, нормализация Ё и пробелов"]
    resolve --> filter["Отбрасывание звонков старше 5 суток (120 ч)"]
    filter --> rows{"Строка корректна?"}
    rows -->|нет| warn["Строка без ссылок + предупреждение в вывод"]
    rows -->|да| links3["Три ссылки на строку:<br/>Zapis · SIP stack prod (МСК ± окно) · MGW<br/>оба номера без ведущей 7"]
    links3 --> out["Итоговый XLSX: 5 исходных колонок + 3 ссылки<br/>веб: временный файл, удаление после скачивания<br/>CLI: <имя>.cleaned.xlsx рядом с исходным"]
    warn --> out
```

## 8. Реестр сервисов и модули

`services/registry.py` сопоставляет ключ сервиса платформе и модулю.
`SEARCH_PERIOD` модуля — период по умолчанию; `minutes_before` / `minutes_after`
из `config.toml` пересчитывают его относительно времени звонка.

| Ключ | Модуль | Платформа | Что ищет | Нужен UUID |
| --- | --- | --- | --- | --- |
| `zapis` | `find_call_in_logs` | Grafana дашборд | звонок по номерам А/Б, пары участников | — |
| `sip_stack` | `sip_stack_opensearch` | OpenSearch | логи SIP stack по `msisdn` | — |
| `bff` | `bff_logs_opensearch` | OpenSearch | логи BFF по хешу номера (sha256/16) | — |
| `secretary` | `secretary_loki` | Grafana Explore | логи Секретаря по номеру в фильтре | — |
| `myconnect` | `profile_not_found_myconnect` | OpenSearch | `profile not found` по `msisdn` + фраза | — |
| `myconnect_call` | `attached_call_myconnect` | OpenSearch | `master:<msisdn>` + участник SIP | — |
| `noise` | `noise_loki` | Grafana Explore | логи Шумоподавления по 10-значному номеру | — |
| `recording_mgw` | `recording_mgw` | Grafana Explore | `mgw.service` по UUID | да |
| `recording_vss_crs` | `recording_vss_crs` | Grafana Explore | `vss.service` по UUID | да |
| `recording_crs` | `recording_crs` | Grafana Explore | `crs.service` по UUID | да |
| `recording_collector` | `recording_collector` | Grafana Explore | контейнер collector по UUID | да |

Профили продуктов (`core/products.py`): `recording` → zapis, sip_stack, bff;
`secretary` → secretary; `calls` → myconnect, myconnect_call; `noise` → noise;
`assistant` → пусто. Первый пользовательский блок для продукта переводит его
в вебе на динамическую конфигурацию; `config.toml` остаётся для CLI.

## 9. Время и периоды поиска

```mermaid
flowchart LR
    ctx["ctx из заявки"] --> w1{"Что распознано"}
    w1 -->|"диапазон «с … до …»"| range["UTC-окна диапазона"]
    w1 -->|"одно/несколько времён"| times["UTC-окно ± window минут<br/>для каждого времени — отдельная ссылка"]
    w1 -->|"только дата"| day["08:00–20:00 местного времени"]
    w1 -->|"ничего"| none["ссылка без замены времени<br/>или период блока/модуля по умолчанию"]
    range --> graf["Grafana: from/to в UTC"]
    times --> graf
    day --> graf
    none --> osd["OpenSearch: время в Europe/Moscow,<br/>− minutes_before / + minutes_after"]
    times --> osd
    range --> osd
    day --> osd
```

Отдельное предупреждение срабатывает, когда событие старше 5 суток: Loki хранит
логи только 5 дней.

## 10. Хранилища и локальные данные

Всё хранится на машине специалиста; перечисленные пути игнорируются Git.

```mermaid
flowchart TB
    subgraph files["Файловая структура"]
        configtoml["config.toml<br/>URL сервисов, периоды, index patterns<br/>(legacy-секции grafana/opensearch)"]
        dsjson["diagnostic_sources.json<br/>пользовательские блоки, 0600, атомарная запись"]
        tickets["tickets/current.txt<br/>текст текущей заявки"]
        sidecar["*.parsed.json рядом с заявкой<br/>нормализованный контекст + ссылки"]
        cases["cases/*.json<br/>экспорт --export-case"]
        histdir["history/YYYY/MM/*.yaml<br/>архивы заявок + ссылки<br/>history/index.json — номер → пути"]
        pissues["parser_issues/parser_issues.jsonl<br/>нераспознанные строки заявок"]
        cleaned["*.cleaned.xlsx<br/>обработанные выгрузки"]
    end

    gtoolCli["gtool.py"] --> tickets
    gtoolCli --> sidecar
    gtoolCli --> cases
    gtoolCli --> histdir
    gtoolCli --> pissues
    webapp2["webapp.py"] --> dsjson
    webapp2 --> histdir
    modules2["modules/*"] --> configtoml
    dynamic2["dynamic_sources.py"] --> dsjson
    lost2["lost_calls_table.py"] --> cleaned
```

Case JSON (`core/case_export.py`) содержит нормализованные идентификаторы,
событие, выбранные модули и ссылки; исходный текст заявки, пути, токены и
конфигурация в него не попадают.

## 11. Маршруты веб-приложения

| Метод и путь | Назначение |
| --- | --- |
| `GET /` | главная: форма заявки, результаты, пакетная загрузка |
| `POST /analyze` | первичная диагностика заявки |
| `POST /secondary` | второй этап по UUID звонка |
| `POST /batch` | обработка таблицы потерянных звонков, скачивание XLSX |
| `GET /settings` | конструктор диагностических блоков |
| `POST /settings/source` | создание / сохранение блока |
| `POST /settings/source/delete` | удаление блока |
| `POST /settings/import` | импорт конфигурации из JSON |
| `GET /settings/export` | скачивание текущей конфигурации |
| `GET /healthz` | проверка живости |
| `GET /static/*` | styles.css, app.js |

Запуск: `.venv/bin/python webapp.py` (порт 8765, браузер открывается
автоматически; флаги `--port`, `--no-browser`).

## 12. Модель безопасности

```mermaid
flowchart TB
    subgraph guard["Защита на уровне приложения"]
        host["TrustedHostMiddleware<br/>только 127.0.0.1 и localhost"]
        csrf["CSRF-токен<br/>сравнение constant-time"]
        limits["Лимиты: заявка 200 000 символов,<br/>таблица 25 МБ, конфигурация 2 МБ"]
        csp["CSP: default-src 'self'<br/>script-src 'self' · без CDN и инлайна"]
        headers["no-store · X-Frame-Options: DENY<br/>Referrer-Policy: no-referrer<br/>nosniff · Permissions-Policy"]
        tmp["Временные файлы 0600,<br/>удаление после скачивания"]
    end

    subgraph data["Защита данных"]
        local["Ничего не отправляется во внешние сервисы:<br/>ссылки открывает браузер пользователя"]
        secrets["Токены и ключи в ссылках блокируются<br/>при вводе (access_token, api_key, auth, token)"]
        perms["diagnostic_sources.json · parser_issues ·<br/>case JSON пишутся с правами 0600"]
    end

    host --> webapp3["webapp.py"]
    csrf --> webapp3
    limits --> webapp3
    csp --> webapp3
    headers --> webapp3
    tmp --> webapp3
    webapp3 --> data
```

История успешных заявок выключена по умолчанию и включается галочкой;
`--dry-run` в CLI отключает и историю, и диагностику парсера.

## 13. Тесты, CI и ветки

- `tests/` — pytest по всем слоям: парсер, история, экспорт, ссылки сервисов,
  динамические источники, веб-маршруты (`TestClient` + `httpx`), таблицы.
- CI (`.github/workflows/ci.yml`): Python 3.12 → `ruff check .` → `pytest -q`.
- Локально: `python -m pip install -r requirements-dev.txt`,
  затем `python -m pytest -q` и `python -m ruff check .`.
- Ветки (`CONTRIBUTING.md`): `feature/*` и `temp/*` → PR в `dev`;
  перед выпуском `dev` вливается в `stage` (полная проверка), из `stage` —
  merge в `main` с тегом `vX.Y.Z`. Релизный workflow
  (`.github/workflows/release.yml`) на тег прогоняет тесты и публикует
  GitHub Release с исходниками.
- Текущие крупные задачи и их ветки — в `docs/tasks/`.

```mermaid
flowchart LR
    f["feature/имя"] -->|"PR"| d["dev"]
    t["temp/имя"] -->|"PR или удаление"| d
    d -->|"merge перед выпуском"| s["stage"]
    s -->|"merge + тег vX.Y.Z"| m["main"]
    m -->|"тег"| rel["GitHub Release<br/>(release.yml: тесты + публикация)"]
```
