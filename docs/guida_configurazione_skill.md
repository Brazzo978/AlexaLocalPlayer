# Guida alla configurazione della skill Alexa

Questa guida descrive in dettaglio come creare e configurare una skill Alexa che si integri con il
servizio esposto da **Alexa Local Player**. I passaggi sono organizzati in tre fasi:

1. Preparazione dell'infrastruttura AWS necessaria.
2. Creazione della skill nella Alexa Developer Console.
3. Collegamento della skill al server locale (o container) che ospita Alexa Local Player.

> **Prerequisiti**
>
> * Un account Amazon Developer (developer.amazon.com) con accesso alla console.
> * Un account AWS attivo con permessi per creare risorse IAM, Lambda e API Gateway.
> * L'endpoint HTTP pubblico del servizio Alexa Local Player (ad esempio tramite tunnel HTTPS,
>   reverse proxy o pubblicazione su internet).

## 1. Preparazione dell'infrastruttura AWS

### 1.1 Creare un ruolo IAM per la funzione Lambda (opzionale ma consigliato)

1. Accedete alla console AWS e aprite il servizio **IAM**.
2. Create un nuovo ruolo scegliendo "**Lambda**" come servizio che utilizzerà il ruolo.
3. Allegare le policy minime necessarie, ad esempio `AWSLambdaBasicExecutionRole` per permettere
   l'invio dei log su CloudWatch.
4. Salvate il ruolo con un nome esplicativo (es. `AlexaLocalPlayerLambdaRole`).

> Se volete che la Lambda chiami API esterne protette (VPN, VPC, ecc.), configurate qui i permessi
> aggiuntivi e le impostazioni di rete (VPC, subnet, security group).

### 1.2 Creare una funzione AWS Lambda

1. Aprite il servizio **AWS Lambda** e cliccate su "**Create function**".
2. Selezionate "**Author from scratch**" e compilate i campi:
   * **Function name**: `alexa-local-player-skill` (o simile).
   * **Runtime**: `Python 3.11` (coerente con il progetto).
   * **Architecture**: `x86_64`.
   * **Permissions**: scegliete "Use an existing role" e selezionate il ruolo creato al punto 1.1
     (in alternativa lasciate che la console ne generi uno automaticamente).
3. Create la funzione e, una volta aperta la schermata di dettaglio, sostituite il codice di esempio
   con un handler che inoltra le richieste al server Alexa Local Player. Esempio minimo:

   ```python
   import json
   import os
   import urllib.request

   LOCAL_PLAYER_URL = os.environ.get("LOCAL_PLAYER_URL")

   def lambda_handler(event, context):
       # Qui dovreste trasformare l'IntentRequest in una chiamata HTTP verso il vostro server
       # Alexa Local Player. Questo è un esempio estremamente semplificato.
       song = event["request"].get("intent", {}).get("slots", {}).get("SongName", {}).get("value")
       if not song:
           return _simple_response("Dimmi il titolo del brano da riprodurre.")

       req = urllib.request.Request(
           f"{LOCAL_PLAYER_URL}/api/v1/songs/request",
           data=json.dumps({"song": song}).encode("utf-8"),
           headers={"Content-Type": "application/json"},
           method="POST",
       )
       with urllib.request.urlopen(req, timeout=10) as response:
           payload = json.loads(response.read())

       stream_url = payload.get("stream_url")
       if not stream_url:
           return _simple_response("Non riesco a trovare il brano richiesto.")

       return {
           "version": "1.0",
           "response": {
               "directives": [
                   {
                       "type": "AudioPlayer.Play",
                       "playBehavior": "REPLACE_ALL",
                       "audioItem": {
                           "stream": {
                               "token": song,
                               "url": stream_url,
                               "offsetInMilliseconds": 0,
                           }
                       },
                   }
               ],
               "shouldEndSession": True,
           },
       }

   def _simple_response(text):
       return {
           "version": "1.0",
           "response": {
               "outputSpeech": {
                   "type": "PlainText",
                   "text": text,
               },
               "shouldEndSession": True,
           },
       }
   ```

4. Nella sezione **Configuration → Environment variables**, aggiungete `LOCAL_PLAYER_URL` con il
   valore dell'endpoint pubblico (es. `https://example.com`).
5. Nel tab **Configuration → General configuration** aumentate il timeout a **10-15 secondi**, così
   la skill ha tempo di attendere la risposta del server.
6. Salvate e testate la funzione con un **test event** modellato su una richiesta Alexa standard.

> In alternativa alla Lambda, potete configurare direttamente l'endpoint HTTPS nel developer portal
> se il vostro server Alexa Local Player è raggiungibile da internet con certificato valido.

### 1.3 (Opzionale) Pubblicare l'endpoint via API Gateway

Se volete aggiungere un ulteriore livello di sicurezza o caching:

1. Aprite il servizio **API Gateway** e create una nuova API HTTP.
2. Create una integrazione con la funzione Lambda creata al punto 1.2.
3. Abilitate **IAM authorizer** o API Key se volete controllare gli accessi.
4. Distribuite l'API e prendete nota dell'URL pubblico generato.
5. Utilizzate questo URL in `LOCAL_PLAYER_URL` o direttamente nella Developer Console come endpoint.

## 2. Creazione della skill nella Alexa Developer Console

1. Accedete a [developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask).
2. Cliccate su **"Create Skill"**.
3. Inserite il nome della skill (es. "Alexa Local Player") e selezionate la lingua desiderata.
4. Scegliete un modello di interazione di tipo **Custom** e l'hosting "**Provision your own**" (dato
   che userete Lambda o un endpoint personale).
5. Una volta creata la skill, nella sezione **Interaction Model → Invocation** impostate la frase di
   invocazione (es. "local player").
6. Nella sezione **Intents**, create un nuovo intent (es. `PlaySongIntent`) con uno slot di tipo
   `AMAZON.MusicRecording` o `AMAZON.SearchQuery` per catturare il titolo del brano.
7. Aggiungete alcuni sample utterance come:
   * "riproduci {SongName}"
   * "metti la canzone {SongName}"
   * "voglio ascoltare {SongName}"
8. Salva e clicca su **Build Model** per generare l'interaction model.

## 3. Collegare la skill all'endpoint del server

### 3.1 Configurare l'endpoint nella Developer Console

1. Aprite la sezione **Endpoint** della skill.
2. Se usate AWS Lambda:
   * Selezionate la regione (es. `EU-West` per l'Italia) e incollate l'ARN della Lambda creata.
3. Se usate un HTTPS custom endpoint:
   * Selezionate `HTTPS`.
   * Inserite l'URL pubblico del vostro server Alexa Local Player.
   * Scegliete "My development endpoint is a sub-domain of a domain that has a wildcard certificate"
     (o l'opzione appropriata in base al certificato a disposizione).

### 3.2 Configurare gli Account Linking (opzionale)

Se volete limitare l'uso della skill ad un gruppo di utenti:

1. Andate su **Account Linking** e abilitatelo.
2. Configurate l'OAuth provider desiderato (Cognito, provider personalizzato, ecc.).
3. Utilizzate i token ricevuti dalla skill per autorizzare l'accesso al vostro server.

## 4. Test e pubblicazione

1. Nella Developer Console, aprite la sezione **Test** e attivate il toggle su "Development".
2. Utilizzate il simulatore integrato per inviare frasi come "Alexa, chiedi a local player di
   riprodurre Yesterday".
3. Verificate nei log CloudWatch (Lambda) o nel server locale che le richieste vengano inoltrate
   correttamente.
4. Una volta soddisfatti del funzionamento, completate i requisiti della sezione **Distribution** per
   la pubblicazione (icone, descrizioni, policy, ecc.).

## 5. Suggerimenti di sicurezza e manutenzione

* **HTTPS obbligatorio**: la skill accetta solo endpoint con certificato valido. Se usate tunneling,
  assicuratevi che sia fornito da un servizio che offre TLS (es. Ngrok, Cloudflare Tunnel, ecc.).
* **Monitoring**: configurate allarmi CloudWatch per la Lambda e l'API Gateway per essere avvisati in
  caso di errori o timeout.
* **Versionamento**: utilizzate le funzionalità di versioning della Developer Console per tenere traccia
  delle modifiche al modello di interazione.
* **Log**: Alexa Local Player può essere configurato con `LOG_LEVEL=DEBUG` per diagnosticare i problemi
  durante i test.

Seguendo questi passaggi disporrete di una skill Alexa funzionante che utilizza il server locale per
recuperare e riprodurre brani senza dipendere dai servizi cloud musicali di Amazon.
