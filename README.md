# AI News Discord Bot

Bot Discord che ogni 12 ore pubblica in un canale testuale le principali notizie sugli sviluppi dell'intelligenza artificiale, aggregate da feed RSS curati (EN + IT).

## Features
- RSS feed curati, zero API key richieste
- Embed Discord (titolo, link, descrizione, fonte, data) — blu per EN, verde per IT
- Dedup persistente via `posted_urls.json` (TTL 14 giorni)
- Filtro keyword AI su feed italiani generalisti
- Rate limit tra invii per rispettare le API Discord

## Setup Discord
1. https://discord.com/developers/applications → **New Application**
2. Tab **Bot** → **Reset Token** → copia il token (`DISCORD_TOKEN`)
3. Tab **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Embed Links`
   - Apri l'URL e invita il bot nel server
4. In Discord: attiva **Developer Mode** (Impostazioni → Avanzate) → click destro sul canale → **Copy Channel ID** → sarà `DISCORD_CHANNEL_ID`

## Esecuzione locale
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env           # poi compila DISCORD_TOKEN e DISCORD_CHANNEL_ID
python bot.py
```

Il primo ciclo parte immediatamente all'avvio, poi ogni 12 ore.

## Deploy su Railway (free tier)
1. Push del repo su GitHub
2. `railway.app` → New Project → **Deploy from GitHub repo**
3. Aggiungi le variabili `DISCORD_TOKEN` e `DISCORD_CHANNEL_ID` in **Variables**
4. Railway rileva `Procfile` e avvia il worker
5. Controlla i log: "Bot connesso come ..." + primo batch di embed nel canale

Alternative equivalenti: Fly.io (`fly launch` app tipo worker), Render (Background Worker).

## Personalizzare le fonti
Modifica `feeds.py`:
- `FEEDS_EN` — feed già dedicati all'AI (tutte le entry delle ultime 12h vengono pubblicate)
- `FEEDS_IT` — feed italiani generalisti (solo entry che contengono keyword da `AI_KEYWORDS`)

## Struttura
```
bot.py                # Entry point + scheduler
news_fetcher.py       # Fetch + parse + filtro date/keyword
discord_publisher.py  # Embed + invio
dedup.py              # posted_urls.json
feeds.py              # Lista feed + keyword
config.py             # Variabili ambiente
```
