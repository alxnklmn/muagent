# muagent — deploy на checkron сервер

Хост уже имеет docker-compose стек `checkron` (nginx, ss-local SOCKS5, certbot). 
Мы переиспользуем эту инфраструктуру, добавляя 2 сервиса: `muagent-hub` и `muagent-research`.

## Один раз: подготовка

```bash
cd ~
git clone https://github.com/alxnklmn/muagent.git
```

## ENV-переменные

Добавь в `~/checkron/.env`:

```env
# muagent
MUAGENT_BOT_TOKEN=...              # hub bot token (@oblivionares_bot)
MUAGENT_LLM_API_KEY=sk-or-...      # OpenRouter
MUAGENT_LLM_MODEL=deepseek/deepseek-chat-v3.1
MUAGENT_RESEARCH_BOT_TOKEN=...     # research bot (@oblvhordex1_bot)
MUAGENT_TAVILY_API_KEY=tvly-...
MUAGENT_HUB_USERNAME=oblivionares_bot
MUAGENT_DOMAIN=mu1.projectoblivion.xyz
MUAGENT_LOCAL_TZ=Europe/Moscow
```

`OUTBOUND_PROXY` уже есть в checkron `.env` — переиспользуем его.

## Nginx — добавить mu1.* в существующий конфиг

Текущий шаблон в `~/checkron/nginx/https.conf` хардкоден на один `@@DOMAIN@@`. 
Добавляем второй блок:

```bash
# Skopируй наш конфиг
cp ~/muagent/deploy/nginx-mu1.conf ~/checkron/nginx/mu1.conf

# В конец https.conf (внутри http { ... } блока, перед закрывающей }):
#   include /etc/nginx/conf.d/mu1.conf;
```

И в `docker-compose.yml` nginx volume:
```yaml
volumes:
  - ./nginx/mu1.conf:/etc/nginx/conf.d/mu1.conf:ro
```

## Сертификат для mu1.projectoblivion.xyz

DNS уже направлен. Запускаем certbot через существующий сервис:

```bash
cd ~/checkron
sudo docker compose --profile cert run --rm certbot certonly \
  --webroot --webroot-path=/var/www/certbot \
  -d mu1.projectoblivion.xyz \
  --email admin@projectoblivion.xyz \
  --agree-tos --no-eff-email
```

Сначала должен работать HTTP — добавь редирект-блок и подними nginx (без https-блока),
получи серт, потом включай https-блок.

## Старт сервисов

```bash
cd ~/checkron
sudo docker compose \
  -f docker-compose.yml \
  -f ~/muagent/deploy/docker-compose.muagent.yml \
  build muagent-hub muagent-research

sudo docker compose \
  -f docker-compose.yml \
  -f ~/muagent/deploy/docker-compose.muagent.yml \
  up -d muagent-hub muagent-research

# nginx перезагрузить чтоб подхватил mu1.conf
sudo docker compose restart nginx
```

## Проверка

```bash
# 1. health
curl https://mu1.projectoblivion.xyz/health
# должно: muagent ok

# 2. webhook был установлен?
sudo docker logs checkron-muagent-hub-1 | grep webhook
# должно: webhook registered: https://mu1.projectoblivion.xyz/webhook

# 3. напиши боту в Telegram /help — должен прийти ответ
```

## Обновление кода

```bash
cd ~/muagent
git pull
cd ~/checkron
sudo docker compose -f docker-compose.yml -f ~/muagent/deploy/docker-compose.muagent.yml build muagent-hub muagent-research
sudo docker compose -f docker-compose.yml -f ~/muagent/deploy/docker-compose.muagent.yml up -d muagent-hub muagent-research
```

## SQLite persistent volume

`muagent_data` volume хранит `db.sqlite3`. Чтобы сделать backup:

```bash
sudo docker run --rm -v checkron_muagent_data:/data -v "$(pwd)":/backup alpine \
  cp /data/db.sqlite3 /backup/muagent-backup-$(date +%Y%m%d).sqlite3
```
