# Paradox Wiki Bot

[![CI](https://github.com/Ingwalde/Paradox-Wiki-Bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Ingwalde/Paradox-Wiki-Bot/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/docker-ghcr.io-2496ED?logo=docker&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![mypy](https://img.shields.io/badge/mypy-checked-2A6DB2)
![Coverage](https://img.shields.io/badge/coverage-81%25*-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Discord-бот з українським інтерфейсом для пошуку сторінок Paradox-вікі
(контент вікі переважно англійський). Дані лежать локально в SQLite, тож пошук
не залежить від доступності вікі й відповідає за частки мілісекунди.

```text
Discord (prefix + admin slash) → paradox_bot/bot.py → paradox_bot/search.py ─┐
                                          │                                   ├─ databases/<game>.db (SQLite)
                                          └→ paradox_bot/pdx_tools.py ────────┘         ↑
                                                     │                    scripts/import_wiki.py
                                                     └→ https://pdx.tools/api/saves     (MediaWiki API)
```

## Architecture

Один пакет `paradox_bot/`, розділений за відповідальністю, `main.py` —
тонкий entrypoint (TOKEN, запуск).

| Модуль | Відповідає за |
|---|---|
| `config.py` | `Settings` (типізований dataclass, читається з env один раз) + логування |
| `games.py` | `GameInfo`/`GAMES` — єдине джерело правди про підтримувані ігри (ключ команди, стиль, wiki-піддомен) |
| `search.py` | SQLite-пошук: `Pages` + `Redirects`, ранжування, fuzzy-підказки, випадкова сторінка |
| `pdx_tools.py` | Аплоад сейву на pdx.tools, дедуп повторних завантажень |
| `feedback.py` | ✅/❌ голоси: тільки збереження в SQLite |
| `stats.py` | Лог пошукових запитів для `-trending` |
| `bot.py` | `ParadoxBot` і тільки він: інтенти, підключення когів, event-хендлери |
| `search_flow.py` | Сценарій пошуку: запит → відповідь → запис у stats/контекст/лог-канал |
| `search_context.py` | Памʼять «яке повідомлення було відповіддю на який запит» (для ✅/❌) |
| `ui/` | Презентація: `views.py` (кнопки, пагінація, embed'и), `text.py` (українські рядки) |
| `cogs/` | Cog-и для статичних команд: `tools`, `help`, `extras` (`-random`/`-trending`/факт дня), `admin` (slash) |
| `web.py` | Keep-alive/health HTTP-ендпоінт (aiohttp, у тому ж event loop) |
| `storage.py` | Спільне підключення до записуваних SQLite-баз: WAL + схема |

Залежності односторонні: `ui/` не знає про `bot.py`, коги не імпортують
`ParadoxBot` (для `/admin status` є `Protocol` з трьох потрібних полів). Через
це `bot.py` імпортує коги нормально, на рівні модуля, а не всередині
`setup_hook()`, як доводилось робити раніше, щоб обійти цикл.

Динамічні по-ігрові команди (`-eu4`, `-eu5`, …) реєструються напряму на боті,
не через Cog — вони породжуються цик­лом по `GAMES`, а не декоратором, тож
заганяти їх у Cog-стиль додало б тертя без користі.

## Команди

| Команда | Опис |
|---|---|
| `-eu4 <запит>`, `-eu5`, `-hoi4`, `-stl`, `-imp`, `-vic3`, `-ck3` | Пошук у вікі гри (кілька слів дозволено) |
| `-random <гра>` | Випадкова стаття |
| `-trending <гра>` | Топ запитів за останній тиждень |
| `-tools` | Завантажити сейв на [pdx.tools](https://pdx.tools) |
| `-help` | Довідка |
| `/admin status` | Здоров'я бота, статистика БД по іграх (лише для адміністраторів сервера) |
| `/admin feedback` | Останні ✅/❌ голоси (лише для адміністраторів сервера) |

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install               # опційно, але рекомендовано
cp .env.example .env             # заповніть TOKEN (обов'язково)
python main.py
```

В консолі має з'явитися `Logged in as <ім'я бота>`. Далі в Discord: `-help`,
потім `-eu4 holy roman empire`.

Бот піднімає keep-alive HTTP-ендпоінт на `PORT` (за замовчуванням 8080):
`GET /` і `GET /health` повертають `200 I'm alive!`.

## Де взяти токени і ключі

### 1. `TOKEN` — токен Discord-бота (обов'язково)

1. [discord.com/developers/applications](https://discord.com/developers/applications)
   → **New Application**.
2. Вкладка **Bot** → **Reset Token** → скопіювати. Токен показується **один раз**;
   якщо загубили — треба скидати заново.
3. Там же, **Privileged Gateway Intents** → увімкнути **MESSAGE CONTENT INTENT**.
   Без нього бот під'єднається і буде онлайн, але **не бачитиме тексту повідомлень**,
   тобто жодна префіксна команда не спрацює (`-eu4`, `-tools`, ...). Це
   найчастіша причина «бот онлайн, але мовчить». Свідомо не прибрано —
   `/admin` наразі єдина slash-команда, решта лишається на префіксах.
4. Вкладка **OAuth2 → URL Generator**: scope `bot` і `applications.commands`
   (для `/admin`), права *Send Messages*, *Embed Links*, *Add Reactions*,
   *Read Message History*. Відкрити згенероване посилання і додати бота на
   сервер.

Токен кладеться в `.env`, а не в код. `.env` уже в `.gitignore`.

### 2. `LOG_CHANNEL_ID` — канал для дзеркалення запитів (необов'язково)

Discord → **Налаштування → Додатково → Режим розробника** увімкнути →
правий клік на каналі → **Копіювати ID каналу**.

Без цієї змінної бот працює нормально, лише пише в лог попередження і не дзеркалить
запити в Discord.

### 3. `PDX_TOOLS_USER_ID` / `PDX_TOOLS_API_KEY` (необов'язково)

Потрібні лише для команди `-tools`. Реєстрація на [pdx.tools](https://pdx.tools)
(вхід через Steam) → сторінка акаунта → згенерувати API-ключ. Автентифікація —
HTTP basic auth: user id як логін, ключ як пароль. Ендпоінт, заголовки й формат
відповіді звірені з [pdx.tools/docs/api](https://pdx.tools/docs/api/) і перевірені
наживо (успішний аплоад і коректна обробка дубліката).

Без ключів `-tools` чесно повідомляє, що завантаження не налаштоване.

### 4. `DEV_GUILD_ID` (необов'язково, для розробки)

ID тестового сервера — з ним `/admin`-команди синхронізуються миттєво.
Без нього синхронізація глобальна і може зайняти до години.

### 5. `DAILY_FACT_CHANNEL_ID` (необов'язково)

Канал, куди раз на день (12:00 UTC) постить випадкову статтю з випадкової гри.
Порожньо — функція вимкнена.

### 6. API вікі — ключ не потрібен

MediaWiki Action API (`https://<game>.paradoxwikis.com/api.php`) анонімний.
`scripts/import_wiki.py` ним і користується для наповнення `databases/<game>.db`
(`python scripts/import_wiki.py eu5`, реюзабельно для будь-якої гри з
`paradox_bot/games.py`).

## Якщо не працює

| Симптом | Причина |
|---|---|
| Бот онлайн, але не реагує на префіксні команди | Не увімкнено **MESSAGE CONTENT INTENT** |
| `TOKEN is not set` і вихід | Немає `.env` або порожній `TOKEN` |
| `Improper token has been passed` | Токен невірний — скиньте його в Developer Portal |
| `/admin` не з'являється в Discord | Глобальна синхронізація до години; задайте `DEV_GUILD_ID` для миттєвої |
| `/admin` є, але недоступна | Потрібні права адміністратора на сервері |
| Бот не відповідає в конкретному каналі | Немає прав *Send Messages* / *Embed Links* |
| `-tools` каже «не налаштоване» | Немає `PDX_TOOLS_USER_ID` / `PDX_TOOLS_API_KEY` |

Детальні логи — у `logs/bot.log` (рівень DEBUG, з ротацією); у консолі лише INFO.

## Конфігурація

Усі параметри читаються з `.env` в `Settings.from_env()` — див. `.env.example`.

| Змінна | Обов'язкова | Опис |
|---|---|---|
| `TOKEN` | так | Токен Discord-бота |
| `LOG_CHANNEL_ID` | ні | Канал, куди дзеркаляться запити |
| `DB_DIR` | ні | Каталог з `eu4.db`, `eu5.db`, … (типово `databases`) |
| `DATA_DIR` | ні | Де лежать записувані бази (аплоади, фідбек, статистика); у Docker — том |
| `BOT_PREFIX` | ні | Префікс команд (типово `-`) |
| `PORT` | ні | Порт keep-alive/health (типово 8080) |
| `DEV_GUILD_ID` | ні | Сервер для миттєвої синхронізації `/admin` |
| `DAILY_FACT_CHANNEL_ID` | ні | Канал для щоденного авто-поста (12:00 UTC) |
| `PDX_TOOLS_USER_ID`, `PDX_TOOLS_API_KEY` | ні | Ключі pdx.tools |
| `PDX_TOOLS_API_URL`, `PDX_TOOLS_SAVE_URL` | ні | Ендпоінт і шаблон посилання pdx.tools |

## Дані

`databases/<game>.db`: `Pages(title, url, image_url, lang)` та
`Redirects(redirect_title, redirect_url, target_page_url)` — обидві таблиці
беруть участь у пошуку (ранжування: точний збіг → з початку → входження
всередині), плюс fuzzy-підказки на порожньому результаті.

Наповнюються через `python scripts/import_wiki.py <гра>` (MediaWiki Action
API, без ключа). Безпечно перезапускати — таблиці перебудовуються з нуля.

Пошук сканує таблиці цілком: `LIKE '%запит%'` має провідний `%`, який жоден
B-tree індекс обслужити не може. На ~2000 рядків це ≈3 мс у робочому потоці.
Плани щодо індексованої нормалізованої колонки — у [ROADMAP.md](ROADMAP.md).

⚠️ Колонка `lang` недостовірна (значна частина рядків позначена як
«Українська», хоча веде на англійські сторінки) і пошуком не читається.

## Тестування та якість

```bash
ruff check main.py paradox_bot/ tests/ scripts/
mypy
pytest -q --cov=paradox_bot --cov-report=term-missing
```

144 тести: чисті функції (`search.py`, `pdx_tools.py`, `feedback.py`,
`stats.py`, `config.py`, `storage.py`), формат embed'ів і view, усі гілки
команд у `cogs/`, і `-tools`-аплоад проти реального локального
`aiohttp`-сервера (basic auth, заголовки, побайтова цілісність тіла).

Команди тестуються через `.callback(cog, ctx)` з фейковими `ctx`/`interaction`
з `tests/conftest.py`, які просто записують, що було б надіслано. Discord-клієнт,
gateway і HTTP-шар не мокаються взагалі.

\* Coverage-бейдж (80%) — по всьому пакету, з гейтом `fail_under = 78` у CI.
Непокрите — майже виключно event-хендлери й прямі виклики Discord API в
`bot.py`; підняти цифру означає протестувати їх, а не розріджувати розрив
моками.

| Модуль | Покриття |
|---|---|
| `admin.py`, `config.py`, `games.py`, `storage.py`, `web.py` | 100% |
| `search.py` | 97% |
| `extras.py` | 95% |
| `help.py`, `tools.py`, `feedback.py` | 94% |
| `stats.py` | 90% |
| `pdx_tools.py` | 88% |
| `bot.py` | 43% (хелпери й view; event-хендлери й Discord-виклики — ні) |

pre-commit (`pre-commit install`): ruff, mypy, `detect-private-key`,
`check-added-large-files`.

## Деплой

Docker на VPS (Oracle Cloud, Hetzner тощо), як і решта проєктів тут. Платформи
застосунків на кшталт Replit Autoscale не підходять: бот тримає постійне
gateway-з'єднання і **ніколи не отримує вхідних HTTP-запитів**, тому деплой,
що прокидається на запит, згортається до нуля і бот іде офлайн.

Зараз бот працює **на локальній машині** через self-hosted GitHub Actions
runner. Причина не архітектурна, а буденна: безкоштовна квота Oracle — два
AMD-інстанси, обидва зайняті іншими проєктами. Ця схема переїжджає на VPS без
змін у коді — достатньо перевести `deploy.yml` назад на `runs-on: ubuntu-latest`
із scp/ssh.

**Чому runner, а не SSH з Actions.** Машина за NAT, вхідне з'єднання туди
неможливе. Runner опитує GitHub сам, тож нічого відкривати не треба.

**Разово на хості:**

```bash
mkdir -p data logs        # у каталозі проєкту
cp .env.example .env      # заповнити TOKEN
```

Runner ставиться в `.runner/` усередині проєкту (у `.gitignore`):

```powershell
# 1. Розпакувати actions-runner для win-x64 у .runner\
# 2. Токен реєстрації: gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token
cd .runner
.\config.cmd --url https://github.com/<owner>/<repo> --token <TOKEN> `
             --name paradox-local --labels paradox-bot --work _work
```

Автозапуск — **завдання планувальника при вході в систему**, не служба Windows:
движок Docker Desktop живе в сесії користувача, і служба під `NETWORK SERVICE`
до нього не достукається.

```powershell
# Виконувати з кореня проєкту (попередній блок лишає вас у .runner — поверніться).
# Шлях до run.cmd — абсолютний: -Argument резолвиться відносно
# -WorkingDirectory, тож відносний '.runner\run.cmd' дав би
# <проєкт>\.runner\.runner\run.cmd, і задача падала б на кожному тригері.
$runnerDir = (Resolve-Path .runner).Path
$a = New-ScheduledTaskAction -Execute cmd.exe `
     -Argument "/c `"$runnerDir\run.cmd`"" -WorkingDirectory $runnerDir

# Два тригери: перший піднімає runner при вході, другий раз на 5 хвилин
# перевіряє, чи він живий. Самого AtLogOn мало — процес, що просто вийшов,
# лишався мертвим до наступного логіну, і деплой мовчки висів у черзі.
# MultipleInstances IgnoreNew робить повторний тригер безпечним: поки runner
# працює, новий запуск ігнорується. Побічний ефект: поки все справно,
# LastTaskResult дорівнює 0x800710E0 («екземпляр уже виконується»), тож
# судити про здоровʼя за цим кодом не можна — дивіться State і статус
# runner'а на GitHub.
$triggers = @(
  New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
)
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
     -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
     -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask "ParadoxBot GitHub Runner" -Action $a -Trigger $triggers `
  -Settings $s -Force
```

⚠️ **Docker Desktop → Settings → General → «Start Docker Desktop when you sign
in»** має бути увімкнено — інакше після ребуту движок не піднімається взагалі.

Але сама галочка проблему не закриває: runner і движок стартують одночасно, і
runner виграє гонку — деплой, що чекав у черзі під час ребуту, дійде до
`docker compose pull` раніше, ніж демон буде готовий. Тому `scripts/deploy.sh`
чекає на движок до 3 хвилин, перш ніж щось робити.

**Далі автоматично.** Мердж у `main` → CI ганяє лінт, типи, гейти й тести →
збирає образ, сканує Trivy і пушить у GHCR з тегом `sha-<commit>` →
`deploy.yml` на runner'і копіює `docker-compose.yml` у `DEPLOY_DIR`, тягне саме
той образ, який CI перевірив, і піднімає його.

Деплой цілиться в конкретний SHA, а не в `:latest`, після `up -d` звіряє, що
запущений контейнер справді має щойно завантажений digest, і чекає, доки
healthcheck стане `healthy` — інакше падає з останніми 50 рядками логів.
Невдалий `pull` теж зупиняє деплой: без цього compose тихо підняв би старий
образ і відрапортував успіх.

**Увімкнення деплою.** Дві змінні репозиторію (Settings → Secrets and variables
→ Actions → **Variables**): `DEPLOY_ENABLED=true` і `DEPLOY_DIR` — шлях до
каталогу з `.env`, `data/` і `logs/`. Без `DEPLOY_ENABLED` джоб пропускається;
інакше на кожному пуші в `main` він висів би в черзі без runner'а й слав листа
про помилку. Змінні, а не секрети, бо в `if:` на рівні джоба GitHub дає лише
`github`/`needs`/`vars`/`inputs`.

**Безпека self-hosted runner'а на публічному репо.** Джоб виконується на
особистій машині, тому замок навмисно параноїдальний: тільки успішний CI,
тільки подія `push`, тільки гілка `main`. `workflow_run` запускається лише з
копії workflow у default-гілці, а PR із форку не може пушити в `main` — отже
чужий код тут виконатися не може.

**Дані.** `DATA_DIR=/app/data` монтується томом, тож `pdx_tools.db`,
`feedback.db` і `stats.db` переживають редеплой. Ігрові бази в `databases/` —
навпаки, read-only контент усередині образу.

**Локально:** `docker compose up --build`.

## Моніторинг

Бот тримає постійне gateway-з'єднання і сам по собі мовчить, коли падає, —
дізнатися про це можна лише ззовні.

**Що вже працює само.** `restart: unless-stopped` піднімає контейнер після
краху процесу й після ребуту сервера. Docker healthcheck кожні 30 с б'є в
`/health`; він **позначає** контейнер unhealthy, але сам нікого не сповіщає й
не перезапускає — Docker цього навмисно не робить.

**UptimeRobot** закриває решту: помічає і смерть процесу, і зависання event
loop (health-ендпоінт живе в тому ж циклі, що й бот, — саме тому зависання
видно), і недоступність сервера.

1. [uptimerobot.com](https://uptimerobot.com) → **Add New Monitor**.
2. Type — **HTTP(s)**, URL — `http://<адреса-сервера>:8080/health`,
   інтервал 5 хв (безкоштовний тариф).
3. **Alert Contacts** — пошта, Telegram або Discord-вебхук. Для Discord:
   канал → Integrations → Webhooks → Copy URL, і додати до URL `/slack`,
   інакше UptimeRobot шле формат, який Discord не приймає.
4. Порт `8080` має бути відкритий у файрволі сервера (в Oracle Cloud це
   і Security List інстансу, і локальний `iptables`/`ufw`).

Ендпоінт нічого не розкриває: віддає рядок `I'm alive!` і не читає стан бази.

Повноцінні метрики (Prometheus + Grafana, як у `Find-Music-Bot`) — у
[ROADMAP.md](ROADMAP.md), поки надлишкові для цього масштабу.

## Відомі обмеження

- Префіксні команди (`-eu4`, `-tools`, …) лишаються на `message_content` —
  привілейованому інтенті, який після 100 гільдій потребує верифікації
  Discord. Свідомий вибір: `/admin` — єдина slash-команда, решта інтерфейсу
  не мігрувала (див. CHANGELOG 0.1.0).
- Порівняння двох сейвів на pdx.tools не реалізоване — офіційний API цього
  не підтримує (документація прямо радить сторонній сервіс для такого
  сценарію).
- Колонка `lang` у базах недостовірна й не використовується.
