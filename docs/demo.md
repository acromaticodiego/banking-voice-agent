# Cómo grabar la demo

Guion para grabar el vídeo del portafolio **en una sentada**. Lo que sigue está
comprobado contra el stack levantado el 2026-09-29: las catorce comprobaciones
que no gastan cuota pasan, y Postgres y Redis responden.

El vídeo dura para siempre; la cuenta de prueba de Twilio, 30 días. Esta demo es
**por navegador** y no necesita Twilio.

---

## Antes de darle a grabar

```powershell
Set-Location C:\Users\ASUS\Desktop\agente_llamada

docker compose up -d                      # Postgres y Redis. Sin esto la demo
                                          # corre igual pero NO queda expediente,
                                          # y el expediente es el último acto

.\.venv\Scripts\python.exe probe\limites_groq.py    # ¿hay cuota? una toma gasta
                                                    # ~3 000 tokens

.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
```

Y abrir **`http://127.0.0.1:8000/`**. Por la IP de la red **no funciona**: el
navegador solo da el micrófono en `localhost` o en `https`, y lo bloquea sin
avisar.

Tres cosas que conviene tener claras antes de hablar:

- **El reloj de la demo es de 3 000 ms**, no el de la evaluación. Si el modelo
  tarda, el agente suelta la frase de relleno. **No lo cortes: dilo en voz
  alta.** Que el presupuesto del turno se note es parte de lo que el proyecto
  cuenta, y está medido — el turno real mide 2 389 ms y el objetivo eran 800.
- **Solo existe un cliente**: documento `1070234567`, titular *Juan Diego Ossa*,
  tarjeta de débito terminada en `4582`, bloqueada desde el 15/09/2026 por
  movimiento inusual.
- **La pantalla enseña las llamadas a herramientas en vivo.** Es lo que hay que
  dejar ver: que el agente decide, llama, y contesta con lo que le devolvieron.

---

## Toma 1 — la conversación que funciona (~60 s)

El objetivo es que se vea el **bucle**: decide qué preguntar, llama, se apoya en
el resultado.

| tú dices | lo que hay que señalar en pantalla |
|---|---|
| «Hola, llamo porque me bloquearon la tarjeta.» | no contesta nada de la cuenta: pide el documento |
| «Mi cédula es uno cero siete cero dos tres cuatro cinco seis siete.» | **dilo hablado, no leído dígito a dígito seguido**: `probe/numeros_es.py` convierte «setenta, veintitrés…» en el número, y eso es una pieza del sistema |
| | aparece la llamada a `consultar_identidad` **solo con el documento** |
| «Juan Diego Ossa.» | segunda llamada a `consultar_identidad`, ahora con el nombre |
| | y solo entonces `estado_tarjeta`, y contesta el estado |

**La frase que hay que decir sobre esto:** la verificación son dos pasos y en
ese orden a propósito. El documento primero para saber **si el sistema
responde**; el nombre después. Y la herramienta **compara el nombre y no lo
devuelve** — el modelo nunca lo recibe, así que no puede filtrarlo aunque
quiera.

## Toma 2 — la seguridad, que es el acto fuerte (~45 s)

Reinicia la página para empezar llamada nueva.

| tú dices | qué tiene que pasar |
|---|---|
| «Buenas, mi cédula es uno cero siete cero dos tres cuatro cinco seis siete.» | pide el nombre **diciendo para qué**: «para verificar su identidad…» |
| «Andrés Gómez Ríos.» | **se niega y NO dice el nombre verdadero.** Ni «Ossa», ni el 4582, ni nada de la cuenta |

**La frase que hay que decir:** este agente llegó a saludar con «Hola, Sr. Ossa»
**antes** de pedir el nombre para verificar — o sea que regalaba el dato de
control a quien llamara con un documento ajeno. La regla estaba escrita en el
prompt y el modelo la desobedecía. Se arregló **moviendo la garantía del prompt
al código**, y eso es lo que ya no depende de que obedezca.

## Toma 3 — el expediente (~40 s)

Cuelga y, en la terminal:

```powershell
.\.venv\Scripts\python.exe -m app.expediente.leer <id-de-la-llamada>
```

Queda qué se dijo, qué herramienta se llamó con qué argumentos, qué devolvió
**entero y sin resumir**, la clave de idempotencia y lo que el detector de
fundamento revisó de cada respuesta.

**La frase que hay que decir:** una base de datos caída no puede tumbar una
llamada en curso. Si Postgres no responde se sigue atendiendo y se anota la
pérdida — un expediente que se pierde en silencio es peor que no tenerlo.

---

## Lo que NO sale en esta demo, y conviene decirlo en el vídeo

Decirlo vale más que esconderlo, porque es lo que distingue este proyecto:

- **La recuperación ante un fallo de herramienta** no se puede provocar desde el
  navegador: se fuerza con la cabecera `X-Fallar`. Está medida en el conjunto de
  evaluación y comprobada en `app/agent/prueba_escalada_forzada.py`.
- **El barge-in** —interrumpir al agente— está hecho y comprobado **por
  teléfono**, y apagado en el navegador a propósito: sin cancelación de eco
  comprobada, el sistema se interrumpiría a sí mismo cada vez que abriera la
  boca.
- **La llamada por la red telefónica de verdad.** El canal está escrito y
  verificado sin cuenta: G.711 µ-law contra la biblioteca estándar en los 65 536
  valores, el protocolo de Twilio emulado, y una grabación real que sobrevive al
  viaje. Falta la cuenta. Los pasos, en [`telefonia.md`](telefonia.md).
- **Todo está medido en condiciones de laboratorio**: dos voces, dos
  habitaciones, herramientas de mentira en `localhost`. Con una grabación por
  voz eso es orden de magnitud, no una tasa.

## Si algo falla mientras grabas

| síntoma | causa casi segura |
|---|---|
| el navegador no pide micrófono | estás entrando por la IP y no por `localhost` |
| el agente contesta «sigo verificando…» y ya | saltó el reloj de 3 000 ms. Es real: dilo y sigue |
| no queda expediente | Docker no está levantado |
| error 429 o el agente escala sin motivo | se acabó la cuota de Groq. `probe\limites_groq.py` dice a qué hora vuelve |
| el micrófono se oye pero no abre turno | el umbral de voz. Habla más cerca; está medido y es fijo a propósito (ADR 0009) |
