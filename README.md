# AI News Discord Bot

Bot Discord che ogni 12 ore pubblica in un canale testuale le principali notizie sugli sviluppi dell'intelligenza artificiale, aggregate da feed RSS curati (EN + IT).

## Features
- RSS feed curati (EN + IT) con retry automatico + caching ETag/Last-Modified
- Curatela AI del digest: Gemini valuta rilevanza, score e motivo editoriale
- Riassunti AI uniformi (lingua configurabile, default IT) via Gemini (free tier)
- **Dedup semantica via embedding** (Gemini `gemini-embedding-001`, cosine similarity) + fallback SequenceMatcher
- **Grouping multi-fonte**: duplicati intra-ciclo si uniscono in un unico embed con `Anche su: …`
- **Stato persistente in SQLite** (`state.db`) — sopravvive ai redeploy se il volume è persistente
- **Digest + thread**: ogni ciclo apre un thread, le news finiscono dentro (canale pulito)
- **Priority tag 🔥** per keyword ad alto impatto (launch, acquisition, funding, lawsuit, …)
- **Tempo di lettura stimato** nel footer dell'embed
- **Button "Leggi di più"** con riassunto esteso (ephemeral, solo per chi clicca)
- **Slash commands**: `/news-now`, `/mute-source`, `/unmute-source`, `/list-muted`
- **Admin runtime config**: curatela AI e mute globali modificabili da Discord
- **Reactions 👍/👎** come feedback per fonte (aggregate in `source_stats`)
- Thumbnail/immagini negli embed (media:thumbnail o og:image)
- Filtro keyword AI (regex word-boundary) su feed italiani generalisti
- Protezione prompt injection sul contenuto feed

## Setup Discord
1. https://discord.com/developers/applications → **New Application**
2. Tab **Bot** → **Reset Token** → copia il token (`DISCORD_TOKEN`)
3. Tab **OAuth2 → URL Generator**:
   - Scopes: `bot`, **`applications.commands`** *(necessario per le slash command)*
   - Permissions: `Send Messages`, `Embed Links`, `Add Reactions`, `Create Public Threads`, `Send Messages in Threads`
   - Apri l'URL e invita il bot nel server
4. In Discord: Developer Mode → click destro sul canale → **Copy Channel ID** → `DISCORD_CHANNEL_ID`

> Se stai migrando da una versione precedente, devi **re-invitare** il bot aggiungendo lo scope `applications.commands`, altrimenti le slash command non appariranno.

## Setup Gemini
1. https://aistudio.google.com/apikey → **Create API key** (free tier sufficiente per riassunti + embeddings)
2. Copia la chiave in `GEMINI_API_KEY`
3. Se manca, riassunti e dedup semantico avanzato si disattivano automaticamente; il bot continua a funzionare con fallback lessicale.

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `DISCORD_TOKEN` | — | Token bot Discord (obbligatorio) |
| `DISCORD_CHANNEL_ID` | — | ID canale (obbligatorio) |
| `GEMINI_API_KEY` | — | Chiave Gemini (opzionale) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modello per i riassunti |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | Modello per gli embeddings |
| `SUMMARY_LANGUAGE` | `it` | Lingua dei riassunti (`it`, `en`, `es`, `fr`, `de`, `pt`) |
| `STATE_DB_PATH` | `state.db` | Path SQLite (su Railway/Fly punta al volume) |
| `FETCH_TIMES_UTC` | — | Opzionale: `HH:MM,HH:MM` UTC. Se impostato, sovrascrive l'intervallo di 12h con orari fissi (es. `07:00,19:00`). |
| `ENABLE_AI_SUMMARY` | `true` | Attiva riassunti AI |
| `ENABLE_AI_CURATION` | `true` | Attiva filtro editoriale AI-assisted prima della pubblicazione |
| `AI_CURATION_MIN_SCORE` | `70` | Score minimo per pubblicare una news valutata dalla curatela |
| `AI_CURATION_CONCURRENCY` | `1` | Chiamate Gemini di curatela in parallelo |
| `AI_CURATION_MIN_INTERVAL_SECONDS` | `13.0` | Intervallo minimo tra chiamate di curatela |
| `ENABLE_SMART_DEDUP` | `true` | Attiva dedup semantica |
| `ENABLE_EMBEDDING_DEDUP` | `true` | Usa embedding (altrimenti solo lessicale) |
| `ENABLE_THUMBNAILS` | `true` | Attiva estrazione og:image |
| `ENABLE_FEED_RETRY` | `true` | Retry + ETag sui feed |
| `ENABLE_THREAD_DIGEST` | `true` | Un thread per ciclo invece di messaggi flat |
| `ENABLE_READ_MORE` | `true` | Button "Leggi di più" sugli embed |
| `ENABLE_REACTION_FEEDBACK` | `true` | 👍/👎 alimentano `source_stats` |
| `SIMILARITY_THRESHOLD` | `0.82` | Soglia dedup lessicale (fallback) |
| `EMBEDDING_SIMILARITY_THRESHOLD` | `0.88` | Soglia cosine similarity embedding |
| `DEDUP_WINDOW_HOURS` | `48` | Finestra titoli recenti |
| `AI_SUMMARY_CONCURRENCY` | `1` | Chiamate Gemini in parallelo (free tier: tieni basso) |
| `AI_SUMMARY_MIN_INTERVAL_SECONDS` | `13.0` | Intervallo minimo tra chiamate summary (free tier RPM) |
| `EMBEDDING_CONCURRENCY` | `2` | Chiamate embedding in parallelo |
| `EMBEDDING_MIN_INTERVAL_SECONDS` | `0.5` | Intervallo minimo tra chiamate embedding |
| `NEWS_NOW_COOLDOWN_SECONDS` | `300` | Cooldown `/news-now` per canale |
| `RATE_LIMIT_SECONDS` | `1.5` | Pausa tra un embed e il successivo (rispetto rate-limit Discord) |
| `READING_WPM` | `200` | Parole/minuto per tempo di lettura |
| `FETCH_INTERVAL_HOURS` | `12` | Frequenza cicli (ignorato se `FETCH_TIMES_UTC` è impostato) |
| `LOOKBACK_HOURS` | `12` | Finestra di raccolta entry dai feed |
| `STATE_TTL_DAYS` | `14` | Quanti giorni ricordiamo un URL già pubblicato |
| `FEEDBACK_TTL_DAYS` | `45` | Retention messaggi→feedback |
| `WATCHDOG_MAX_DOWN_SECONDS` | `600` | Se il gateway Discord resta disconnesso oltre questa soglia, il processo esce (Fly riavvia) |

## Slash commands

| Comando | Permesso | Descrizione |
|---------|----------|-------------|
| `/news-now` | Manage Server | Forza un ciclo immediato (cooldown 5 min) |
| `/mute-source <source>` | Manage Server | Silenzia una fonte nel canale corrente |
| `/unmute-source <source>` | Manage Server | Riattiva una fonte |
| `/mute-source-global <source>` | Manage Server | Silenzia una fonte per tutto il bot |
| `/unmute-source-global <source>` | Manage Server | Riattiva una fonte silenziata globalmente |
| `/list-muted` | Tutti | Elenca fonti silenziate globalmente e nel canale |
| `/curation-status` | Manage Server | Mostra stato curatela AI, soglia attiva e mute globali |
| `/curation-set <enabled> [min_score]` | Manage Server | Modifica curatela AI globale e soglia 0-100 |
| `/stats` | Tutti | Metriche runtime (uptime, cicli, notizie pubblicate, errori) + classifica feedback 👍/👎 per fonte |

Le impostazioni modificate da Discord sono globali per il bot e persistono in
SQLite (`state.db`). Se il deploy non usa un volume persistente, tornano ai
default `.env` dopo il redeploy.

## Esecuzione locale
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env           # compila DISCORD_TOKEN e DISCORD_CHANNEL_ID
python bot.py
```

Il primo ciclo parte immediatamente, poi ogni 12 ore.

## Deploy (free tier)

**Fly.io** (consigliato, volumi free fino a 3GB):
```bash
fly launch
fly volumes create botstate --size 1
# fly.toml: mount [mounts] source = "botstate", destination = "/data"
# env: STATE_DB_PATH=/data/state.db
fly deploy
```

> **Importante — secrets vs env**: `DISCORD_TOKEN` e `GEMINI_API_KEY` sono credenziali e NON vanno nel blocco `[env]` di `fly.toml` (finirebbero in git). Imposta come secrets cifrati:
> ```bash
> fly secrets set DISCORD_TOKEN=xxx DISCORD_CHANNEL_ID=123 GEMINI_API_KEY=yyy
> ```
> Sono disponibili come normali variabili d'ambiente a runtime. Il blocco `[env]` resta riservato a configurazione non-sensitive (`STATE_DB_PATH`, `FEED_CACHE_FILE`, flag `ENABLE_*`, ecc.).

**Railway**: funziona ma i volumi richiedono piano Hobby ($5/mo). Senza volume, `state.db` si resetta ad ogni redeploy → il bot ripubblica notizie già viste.

**Render**: Background Worker, disk persistente su piano paid.

## Test
```bash
.venv\Scripts\python.exe run_tests.py
```

Su Windows usa il Python della `.venv`: il `python` globale potrebbe non avere
le dipendenze di `requirements.txt` installate.

## Struttura
```
bot.py                # Entry point + scheduler + slash commands + reactions
news_fetcher.py       # Fetch RSS + retry/ETag + filtro date/keyword regex
ai_summarizer.py      # Riassunti Gemini (breve + esteso) + prompt-injection hardening
ai_curator.py         # Curatela AI: keep/score/reason/summary per digest
embeddings.py         # Wrapper Gemini embeddings + cosine similarity
dedup.py              # Semantic dedup (embedding + fallback lessicale)
storage.py            # SQLite: posted, muted_sources, source_stats, feedback
image_extractor.py    # Thumbnail da media:thumbnail / og:image
discord_publisher.py  # Digest + thread + embed + button + reactions
feeds.py              # Lista feed + AI_KEYWORDS + PRIORITY_KEYWORDS
config.py             # Variabili ambiente
run_tests.py          # Runner locale senza dipendenze aggiuntive
tests/                # Unit test base (dedup, embeddings, priority)
```

## Personalizzare le fonti
Modifica `feeds.py`:
- `FEEDS_EN` — feed AI-dedicated (tutte le entry nelle ultime 12h vengono pubblicate)
- `FEEDS_IT` — feed italiani generalisti (filtrati per `AI_KEYWORDS`)
- `PRIORITY_KEYWORDS` — keyword che segnano una news come 🔥 prioritaria
