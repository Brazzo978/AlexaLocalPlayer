# Alexa Local Player

Questo progetto fornisce un servizio web leggero che consente ad una skill Alexa di richiedere
brani musicali presenti (o generabili) in un server locale senza dover ricorrere ai servizi
cloud di Amazon. Quando la skill invia il nome di una canzone, il server esegue uno script
personalizzabile (per esempio `scripts/XYZ.py -S <Titolo>`) che ha il compito di generare o
scaricare il file audio nella cartella `/temp`. Non appena il file è disponibile viene esposto
tramite un endpoint HTTP così che la skill possa riprodurlo.

## Struttura del progetto

```
.
├── app/                # Codice del servizio Flask
│   ├── config.py       # Gestione delle variabili di configurazione
│   ├── server.py       # Entry-point HTTP
│   └── song_manager.py # Logica di orchestrazione del download dei brani
├── scripts/            # Script di esempio per simulare il download
│   └── XYZ.py
├── requirements.txt    # Dipendenze Python del progetto
├── Dockerfile          # Configurazione per il deploy in container
└── README.md
```

## Requisiti

* Python 3.11+
* Pip
* (Opzionale) Docker 24+

Il servizio salva e legge i file dalla cartella `/temp`. Se eseguite il server al di fuori di un
container assicuratevi che la directory esista e sia scrivibile dal processo.

## Configurazione

Il comportamento del server può essere personalizzato tramite variabili d'ambiente:

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `TEMP_DIR` | `/temp` | Cartella in cui cercare il file generato. |
| `SONG_COMMAND` | `python3 scripts/XYZ.py -S {song}` | Comando eseguito alla richiesta del brano. Il placeholder `{song}` viene sostituito con il titolo ricevuto. |
| `POLL_INTERVAL` | `1.0` | Secondi tra un controllo e l'altro nella cartella temporanea. |
| `TIMEOUT_SECONDS` | `120` | Tempo massimo di attesa per la disponibilità del file audio. |
| `ALLOWED_EXTENSIONS` | `.mp3,.m4a,.wav,.flac` | Estensioni ammesse per il file della canzone. |
| `PUBLIC_BASE_URL` | *calcolato automaticamente* | Base URL usato per costruire il link pubblico del file audio. Impostatelo se il servizio è dietro proxy o tunnel. |

## Avvio rapido (senza Docker)

1. Creare ed attivare un virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Installare le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```
3. Creare la cartella dei file temporanei (se non esiste):
   ```bash
   mkdir -p /temp
   ```
4. Avviare il server Flask:
   ```bash
   python -m app.server
   ```
5. Effettuare una richiesta di prova:
   ```bash
   curl -X POST http://localhost:8000/api/v1/songs/request \
        -H 'Content-Type: application/json' \
        -d '{"song": "My Test Song"}'
   ```
   La risposta conterrà l'URL per riprodurre il file generato (ad es. `http://localhost:8000/songs/my-test-song.mp3`).

Lo script di esempio `scripts/XYZ.py` simula il download creando un file `.mp3` con contenuto fittizio.
Sostituitelo con il vostro processo reale di recupero del brano (ad esempio download da NAS, conversione,
integrazione con librerie locali, ecc.).

## Deploy con Docker

1. Costruire l'immagine:
   ```bash
   docker build -t alexa-local-player .
   ```
2. Avviare il container esponendo la porta 8000 e montando una cartella locale come `/temp`:
   ```bash
   docker run --rm -p 8000:8000 \
      -v $(pwd)/temp-data:/temp \
      alexa-local-player
   ```

   *Suggerimento:* assicuratevi che `temp-data` contenga o possa contenere i file audio prodotti
   dallo script chiamato dal server.

3. Testare il servizio come descritto nella sezione precedente.

### Esecuzione dietro proxy HTTPS

Quando il server è pubblicato su Internet tramite un reverse proxy (ad esempio Nginx,
Caddy o Traefik) è importante che gli URL restituiti al dispositivo Alexa usino lo
stesso dominio HTTPS pubblico del proxy. In uno scenario tipico il proxy termina TLS e
inoltra le richieste HTTP al container sulla porta 8000.

Un esempio di comando `docker run` potrebbe essere:

```bash
docker run -d --name alexa-player \
  -p 8000:8000 \
  -v /srv/alexa/temp:/temp \
  -v /opt/alexa/mock_song.sh:/root/mock_song.sh:ro \
  -e TEMP_DIR=/temp \
  -e SONG_COMMAND="/root/mock_song.sh {song}" \
  -e PUBLIC_BASE_URL="https://il-tuo-dominio.example.com" \
  -e PLAYER_API="https://il-tuo-dominio.example.com" \
  -e ASK_SKILL_ID="amzn1.ask.skill.xxxxx" \
  -e VERIFY_ALEXA=true \
  alexa-local-player:latest
```

Assicuratevi che `https://il-tuo-dominio.example.com` sia raggiungibile pubblicamente e
con un certificato valido: è l'URL che Alexa utilizzerà per scaricare il file audio
(`stream_url`). Se il proxy risponde su una porta diversa dalla 443, includetela nel
valore di `PUBLIC_BASE_URL`/`PLAYER_API` (ad esempio `https://dominio:8443`).

### Utilizzo in produzione

* Configurate `PUBLIC_BASE_URL` con l'indirizzo pubblico raggiungibile dalla skill Alexa (es. tunnel HTTPS).
* Proteggete gli endpoint con un layer aggiuntivo (API Gateway, token di sicurezza, VPN, ecc.)
  perché il servizio non implementa autenticazione nativa.
* Aggiornate `SONG_COMMAND` in modo che punti allo script reale utilizzato per recuperare le canzoni.

## Integrazione con la skill Alexa

Per una guida dettagliata alla configurazione della skill e delle risorse AWS correlate consultate
[`docs/guida_configurazione_skill.md`](docs/guida_configurazione_skill.md).

Di seguito un riepilogo sintetico del flusso di integrazione:

1. Nella skill, configurate l'endpoint HTTPS (o tramite tunneling) che punti al server o alla Lambda.
2. Quando la skill riceve il titolo del brano, invia una richiesta `POST` a
   `https://<server>/api/v1/songs/request` con payload JSON `{ "song": "Titolo" }`.
3. Il server risponde con `stream_url`, un link diretto al file audio.
4. Passate `stream_url` al `AudioPlayer` dell'SDK Alexa per avviare la riproduzione.

## Troubleshooting

* **`500` in risposta alla richiesta** – controllate i log del server: potrebbero esserci errori nello
  script configurato o permessi mancanti sulla cartella temporanea.
* **Timeout nell'attesa del file** – aumentate `TIMEOUT_SECONDS` o assicuratevi che lo script generi il
  file nella posizione attesa.
* **La skill non riesce a raggiungere il file audio** – impostate `PUBLIC_BASE_URL` con l'URL esatto con
  cui la skill raggiunge il server (incluso protocollo e porta).

## Sviluppo

Per contribuire:

1. Seguite i passi dell'"Avvio rapido" usando un virtual environment.
2. Modificate il codice e riavviate il server con `python -m app.server`.
3. Utilizzate `LOG_LEVEL=DEBUG` per ottenere log più dettagliati durante lo sviluppo.

## Licenza

Questo progetto è distribuito secondo i termini della licenza inclusa nel file `LICENSE`.
