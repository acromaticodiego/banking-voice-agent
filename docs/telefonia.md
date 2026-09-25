# Atender una llamada de teléfono de verdad

Lo que falta para que el agente conteste una llamada desde un móvil **no es
código**: el canal está escrito y comprobado (`app/telefonia/`, y las pruebas
`app.prueba_telefonia` y `app.prueba_pasarela`). Lo que falta es un número y un
túnel, y eso son diez minutos de configuración.

Este documento existe para que esos diez minutos no se conviertan en dos horas.

## Qué está comprobado y qué no

| | estado |
|---|---|
| G.711 µ-law, los bytes que viajan por la línea | verificado contra la biblioteca estándar en los **65 536 valores** |
| el protocolo de Twilio Media Streams | emulado con un cliente de mentira, entero |
| una grabación real por el canal completo | el documento **sobrevive** (16 kHz → 8 kHz → µ-law → vuelta → Whisper) |
| el endpoint `/twilio` con un socket de verdad | **230 trozos de audio de vuelta** y su marca de fin |
| el TwiML que Twilio pide al entrar la llamada | responde contra el servidor levantado |
| **que Twilio abra el socket y que el número suene** | **NO comprobado.** Necesita cuenta, número y túnel |

Esa última fila es la única que este documento resuelve.

## Lo que cuesta: cero, con un aviso

La cuenta de prueba de Twilio incluye **75 minutos de voz** y **un número**,
durante **30 días**. Para grabar la demo sobra: una llamada de verificación son
dos minutos.

Dos límites del trial que conviene conocer antes de pelearse con ellos:

- **Solo puedes llamar desde números verificados.** El tuyo se verifica por SMS
  al crear la cuenta, así que si llamas desde tu móvil no hay nada que hacer.
- **Twilio reproduce un aviso corto antes de ejecutar tu TwiML**, del tipo "you
  have a trial account". Sale en la grabación y **solo se quita pagando**. Para
  el vídeo, se corta en edición: es el primer par de segundos.

Y una cosa que no es un límite pero lo parece: **no necesitas telefonía
permanente.** Necesitas grabar el vídeo. El vídeo dura para siempre; el trial,
30 días.

## Los pasos

### 1. La cuenta y el número

1. Crear la cuenta en `twilio.com` y verificar tu móvil por SMS (te lo pide él
   solo). Ese número queda como *Verified Caller ID*, que es el que podrá
   llamar.
2. Comprar un número con capacidad de **voz** en tu país (Console → Phone
   Numbers → Buy a number). Con el crédito del trial no se paga.

### 2. El túnel

Twilio tiene que alcanzar tu portátil, y exige **`wss://` con certificado
válido** — no acepta `ws://` ni un certificado autofirmado. Un túnel lo
resuelve, y **ngrok ya está en esta máquina**, versión 3.39.11:

```
C:\Users\ASUS\Desktop\ngrok-v3-stable-windows-amd64\ngrok.exe
```

Le falta una sola cosa: el **authtoken**. ngrok v3 no arranca sin él, y sale de
una cuenta gratuita en `ngrok.com` (Setup & Installation → copiar el token).
Una vez y para siempre:

```powershell
$ngrok = "C:\Users\ASUS\Desktop\ngrok-v3-stable-windows-amd64\ngrok.exe"
& $ngrok config add-authtoken <tu-token>
& $ngrok http 8000
```

Eso imprime una URL del tipo `https://algo.ngrok-free.app`. **Cámbiale el
esquema para el WebSocket**: `wss://algo.ngrok-free.app/twilio`.

### 3. Decirle al sistema cuál es su URL pública

En el `.env`:

```
TWILIO_STREAM_URL=wss://algo.ngrok-free.app/twilio
```

Se puede dejar vacío —entonces se deduce de la cabecera `Host` de la petición,
que funciona detrás de un túnel—, pero es mejor ponerlo: una URL sacada de una
cabecera es una URL que alguien puede cambiar desde fuera.

### 4. Apuntar el número al sistema

En la consola de Twilio, en el número comprado, sección **Voice → A call comes
in**:

- tipo: **Webhook**
- URL: `https://algo.ngrok-free.app/twilio/voz`
- método: **HTTP POST**

Es `/twilio/voz` —el que devuelve el XML— y **no** `/twilio`, que es el
WebSocket. Confundirlos da un error de TwiML que no dice gran cosa.

### 5. Levantar todo, comprobar, y llamar

```powershell
docker compose up -d                                          # expediente y estado
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
& $ngrok http 8000                                            # en otra ventana
```

Y antes de marcar, la comprobación que existe justo para no depurar esto por
teléfono:

```powershell
.\.venv\Scripts\python.exe probe\check_telefonia.py
```

Mira cinco cosas: que la pasarela responda, que el TwiML salga, que haya un
túnel abierto, que `TWILIO_STREAM_URL` tenga la forma correcta, **y que apunte
al túnel que está abierto ahora mismo** — la trampa de ngrok gratuito, que
cambia de URL en cada arranque. Si algo falta, imprime el comando que lo
arregla.

Con todo en verde, llamar al número desde el móvil verificado.

## Si algo no va

| síntoma | causa casi siempre |
|---|---|
| la llamada entra y se corta enseguida | el webhook apunta a `/twilio` en vez de `/twilio/voz`, o el túnel está caído |
| suena el aviso del trial y luego silencio | el `TWILIO_STREAM_URL` es `ws://` en vez de `wss://`, o apunta al túnel de una sesión anterior de ngrok (la URL cambia en cada arranque del plan gratuito) |
| entra pero el agente no contesta nada | mira la consola: si Groq devolvió 429, el agente escala a un humano y eso es lo correcto. El límite es de 200 000 tokens al día |
| se oye metálico o acelerado | algo va mal en el remuestreo. Las tres conversiones están en un solo sitio, `app/telefonia/media_streams.py`, y tienen prueba |
| entra y en la consola sale un aviso de formato | Twilio cambió el códec. El puente lo anota y sigue en vez de cortar; el aviso lleva el formato que llegó y el que se esperaba |

## Lo que queda después

- **Barge-in.** El puente ya sabe mandar `clear` para tirar el audio que Twilio
  tenga en cola, que es la mitad que depende de nosotros. La otra mitad es
  decidir *cuándo* interrumpir, y eso es el punto 6 del plan.
- **Las teclas (DTMF).** Llegan y se anotan, no se usan. Un menú de tonos sería
  otra conversación, no esta.
- **Medir la latencia por la línea de verdad.** Todos los números de latencia
  del proyecto son por `localhost`. Una llamada real añade el viaje de la red
  en los dos sentidos, y eso no está medido — es el punto que más se acerca a
  "cuánto tarda de verdad".
