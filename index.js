const Alexa = require('ask-sdk-core');
const http = require('http');
const https = require('https');
const { URL } = require('url');

const API_BASE_URL = process.env.LOCAL_PLAYER_BASE_URL || process.env.LOCAL_PLAYER_URL;
const DEFAULT_REPROMPT = 'Dimmi il titolo di un brano o chiedimi di riprodurre l\'ultima canzone.';

function buildFullUrl(pathname) {
    const base = API_BASE_URL || '';
    if (!base) {
        throw new Error('La variabile d\'ambiente LOCAL_PLAYER_BASE_URL non è configurata.');
    }

    const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
    const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
    return `${normalizedBase}${normalizedPath}`;
}

function requestJson(targetUrl, options = {}) {
    const url = new URL(targetUrl);
    const payload = options.body ? JSON.stringify(options.body) : undefined;
    const transport = url.protocol === 'https:' ? https : http;

    const requestOptions = {
        method: options.method || 'GET',
        hostname: url.hostname,
        path: `${url.pathname}${url.search}`,
        port: url.port || (url.protocol === 'https:' ? 443 : 80),
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
    };

    if (payload) {
        requestOptions.headers['Content-Length'] = Buffer.byteLength(payload);
    }

    return new Promise((resolve, reject) => {
        const req = transport.request(requestOptions, (res) => {
            let data = '';
            res.setEncoding('utf8');

            res.on('data', (chunk) => {
                data += chunk;
            });

            res.on('end', () => {
                if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
                    if (!data) {
                        resolve({});
                        return;
                    }

                    try {
                        resolve(JSON.parse(data));
                    } catch (error) {
                        reject(new Error(`Risposta non valida dal server (${error.message}).`));
                    }
                } else {
                    reject(new Error(`Richiesta fallita con codice ${res.statusCode}: ${data}`));
                }
            });
        });

        req.on('error', (error) => {
            reject(error);
        });

        if (payload) {
            req.write(payload);
        }

        req.end();
    });
}

async function fetchSong(songTitle) {
    const url = buildFullUrl('/api/v1/songs/request');
    const body = { song: songTitle };
    return requestJson(url, { method: 'POST', body });
}

function buildAudioPlayerResponse(handlerInput, title, streamUrl) {
    return handlerInput.responseBuilder
        .speak(`Riproduco ${title}.`)
        .addAudioPlayerPlayDirective('REPLACE_ALL', streamUrl, title, 0, null)
        .getResponse();
}

const LaunchRequestHandler = {
    canHandle(handlerInput) {
        return Alexa.getRequestType(handlerInput.requestEnvelope) === 'LaunchRequest';
    },
    handle(handlerInput) {
        const speechText = 'Dimmi il brano da suonare, per esempio: suona Burn di Ellie Goulding';
        return handlerInput.responseBuilder
            .speak(speechText)
            .reprompt('Prova a dire: suona Burn di Ellie Goulding.')
            .getResponse();
    },
};

const PlaySongIntentHandler = {
    canHandle(handlerInput) {
        return (
            Alexa.getRequestType(handlerInput.requestEnvelope) === 'IntentRequest' &&
            Alexa.getIntentName(handlerInput.requestEnvelope) === 'PlaySongIntent'
        );
    },
    async handle(handlerInput) {
        const songSlot = Alexa.getSlot(handlerInput.requestEnvelope, 'SongName');
        const songName = songSlot && songSlot.value ? songSlot.value.trim() : '';

        if (!songName) {
            return handlerInput.responseBuilder
                .speak('Dimmi quale brano vuoi ascoltare.')
                .reprompt(DEFAULT_REPROMPT)
                .getResponse();
        }

        let payload;
        try {
            payload = await fetchSong(songName);
        } catch (error) {
            console.error('Errore PlaySongIntent:', error);
            return handlerInput.responseBuilder
                .speak('Si è verificato un problema nel richiedere il brano. Riprova più tardi.')
                .getResponse();
        }

        const streamUrl = payload.stream_url;
        if (!streamUrl) {
            return handlerInput.responseBuilder
                .speak('Non riesco a trovare il brano richiesto.')
                .getResponse();
        }

        const sessionAttributes = handlerInput.attributesManager.getSessionAttributes();
        sessionAttributes.lastSong = {
            title: payload.song || songName,
            streamUrl,
        };
        handlerInput.attributesManager.setSessionAttributes(sessionAttributes);

        return buildAudioPlayerResponse(handlerInput, payload.song || songName, streamUrl);
    },
};

const PlayLastIntentHandler = {
    canHandle(handlerInput) {
        return (
            Alexa.getRequestType(handlerInput.requestEnvelope) === 'IntentRequest' &&
            Alexa.getIntentName(handlerInput.requestEnvelope) === 'PlayLastIntent'
        );
    },
    handle(handlerInput) {
        const sessionAttributes = handlerInput.attributesManager.getSessionAttributes();
        const lastSong = sessionAttributes.lastSong;

        if (!lastSong) {
            return handlerInput.responseBuilder
                .speak('Non ho ancora un brano da riprodurre. Dimmi il titolo di una canzone.')
                .reprompt(DEFAULT_REPROMPT)
                .getResponse();
        }

        return buildAudioPlayerResponse(handlerInput, lastSong.title, lastSong.streamUrl);
    },
};

const HelpIntentHandler = {
    canHandle(handlerInput) {
        return (
            Alexa.getRequestType(handlerInput.requestEnvelope) === 'IntentRequest' &&
            Alexa.getIntentName(handlerInput.requestEnvelope) === 'AMAZON.HelpIntent'
        );
    },
    handle(handlerInput) {
        const speechText =
            'Puoi chiedermi di riprodurre una canzone dicendo: suona seguito dal titolo, oppure di riprodurre l\'ultimo brano richiesto.';

        return handlerInput.responseBuilder
            .speak(speechText)
            .reprompt(DEFAULT_REPROMPT)
            .getResponse();
    },
};

const CancelAndStopIntentHandler = {
    canHandle(handlerInput) {
        if (Alexa.getRequestType(handlerInput.requestEnvelope) !== 'IntentRequest') {
            return false;
        }
        const intentName = Alexa.getIntentName(handlerInput.requestEnvelope);
        return intentName === 'AMAZON.CancelIntent' || intentName === 'AMAZON.StopIntent';
    },
    handle(handlerInput) {
        return handlerInput.responseBuilder
            .speak('A presto!')
            .getResponse();
    },
};

const FallbackIntentHandler = {
    canHandle(handlerInput) {
        return (
            Alexa.getRequestType(handlerInput.requestEnvelope) === 'IntentRequest' &&
            Alexa.getIntentName(handlerInput.requestEnvelope) === 'AMAZON.FallbackIntent'
        );
    },
    handle(handlerInput) {
        return handlerInput.responseBuilder
            .speak('Non sono sicuro di aver capito. Dimmi quale brano vuoi ascoltare.')
            .reprompt(DEFAULT_REPROMPT)
            .getResponse();
    },
};

const SessionEndedRequestHandler = {
    canHandle(handlerInput) {
        return Alexa.getRequestType(handlerInput.requestEnvelope) === 'SessionEndedRequest';
    },
    handle(handlerInput) {
        console.log('Session ended:', handlerInput.requestEnvelope);
        return handlerInput.responseBuilder.getResponse();
    },
};

const IntentReflectorHandler = {
    canHandle(handlerInput) {
        return Alexa.getRequestType(handlerInput.requestEnvelope) === 'IntentRequest';
    },
    handle(handlerInput) {
        const intentName = Alexa.getIntentName(handlerInput.requestEnvelope);
        return handlerInput.responseBuilder
            .speak(`Hai appena attivato l'intent ${intentName}.`)
            .getResponse();
    },
};

const ErrorHandler = {
    canHandle() {
        return true;
    },
    handle(handlerInput, error) {
        console.error('Errore gestito:', error);
        return handlerInput.responseBuilder
            .speak('Si è verificato un errore. Riprova più tardi.')
            .reprompt(DEFAULT_REPROMPT)
            .getResponse();
    },
};

exports.handler = Alexa.SkillBuilders.custom()
    .addRequestHandlers(
        LaunchRequestHandler,
        PlaySongIntentHandler,
        PlayLastIntentHandler,
        HelpIntentHandler,
        CancelAndStopIntentHandler,
        FallbackIntentHandler,
        SessionEndedRequestHandler,
        IntentReflectorHandler
    )
    .addErrorHandlers(ErrorHandler)
    .lambda();
