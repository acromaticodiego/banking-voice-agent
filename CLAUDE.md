# Proyecto: Agente de voz para verificación y servicio telefónico

Directorio: `C:\Users\ASUS\Desktop\agente_llamada` (Windows, PowerShell).
Repositorio: https://github.com/acromaticodiego/banking-voice-agent

## Quién soy

Juan Diego Ossa, Ingeniero Mecatrónico, ~2,5 años como Backend & AI Engineer.
Python (FastAPI), Node/NestJS, PostgreSQL, Redis, Docker, AWS, PyTorch, YOLOv8,
OpenCV, pgvector. Entre marzo y agosto de 2026 construí una plataforma de
gestión de llamadas de emergencia: NestJS, Deepgram, LLM, FreeSWITCH, AWS ECS.

Tengo cuatro proyectos de portafolio: tres de visión por computador y un agente
de verificación de identidad documental (KYC) con explicaciones auditables.
Este es para vacantes de **Ingeniero de IA Agéntica** en fintech y banca.

**Qué demuestra este y no los otros:** un agente que mantiene una conversación,
decide qué preguntar, llama herramientas, se recupera cuando algo falla y
trabaja contra un reloj. El de KYC es deliberadamente no agéntico —una llamada,
sin herramientas, sin bucle— y este tapa ese hueco.

**Qué NO debe demostrar:** microservicios (ya lo hice con 8) ni visión por
computador (ya lo hice tres veces).

---

## ESTADO: qué existe y funciona

Todo lo de abajo está fusionado en `main` y verificado contra el stack
levantado, no solo compilando.

### El sistema

| pieza | fichero | qué hace |
|---|---|---|
| llamada en vivo | `app/vivo.py` | consume audio según llega, detecta fin de turno, orquesta |
| pasarela | `app/gateway.py` | sirve la página y atiende el WebSocket. No guarda estado |
| pantalla | `app/web/index.html` | micrófono con AudioWorklet, remuestreo a 16 kHz en el navegador, cola de reproducción, conversación y llamadas a herramientas en vivo |
| bucle del agente | `app/agent/loop.py` | decide, llama herramientas, se recupera, frase puente, presupuesto por turno, idempotencia |
| herramientas | `app/tools/service.py` | FastAPI, una por capacidad. `X-Fallar` y `X-Tardar-Ms` para provocar fallo y latencia |
| fin de turno | `app/fin_de_turno.py` | decide si la frase está a medias, por contenido y no solo por silencio |
| números hablados | `probe/numeros_es.py` | "setenta, veintitrés, cuatro..." → `70234567`. Pieza del sistema, no solo de medición |
| tubería sobre fichero | `app/pipeline.py` | el mismo turno pero alimentado desde un WAV en tiempo real, para medir |
| evaluación | `app/evaluation/` | catálogo, partición con reservado bajo llave, corredor, línea base sin modelo |

**Levantar la demo:**
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
# y abrir http://127.0.0.1:8000/   (NO por la IP: el micrófono solo va en localhost o https)
```

**Comprobaciones (todas pasan hoy):**
```powershell
.\.venv\Scripts\python.exe -m app.tools.prueba_servicio      # 10/10
.\.venv\Scripts\python.exe -m app.agent.prueba_bucle         # 4 escenarios
.\.venv\Scripts\python.exe -m app.prueba_pasarela            # 5/5, con audio real de vuelta
.\.venv\Scripts\python.exe -m app.fin_de_turno               # 15/15
.\.venv\Scripts\python.exe probe\numeros_es.py               # 12/12
.\.venv\Scripts\python.exe -m app.evaluation.catalogo
.\.venv\Scripts\python.exe -m app.evaluation.particion
```

**Medir:**
```powershell
.\.venv\Scripts\python.exe -m app.medir_turno --repeticiones 6 --fin-por-contenido
.\.venv\Scripts\python.exe -m app.evaluation.correr              # agente, calibración
.\.venv\Scripts\python.exe -m app.evaluation.correr --linea-base
.\.venv\Scripts\python.exe probe\presupuesto.py
```

---

## LOS NÚMEROS, con su procedencia

Todos en un portátil con RTX 3050 de 6 GB, `openai/gpt-oss-20b` en Groq,
`faster-whisper small` en GPU, `piper es_MX-claude-high`.

### Latencia del turno (2026-09-23, n=6)

| | |
|---|---|
| suma de etapas medidas por separado | 916 ms |
| **el turno de verdad, un solo cronómetro** | **2389 ms** |
| con frase puente: cuando deja de oírse silencio | 1424 ms |
| con frase puente: cuando llega el dato | 2061 ms |
| con fin de turno por contenido: primer audio / primer dato | 2795 / 3625 ms |
| objetivo | 800 ms |

**El objetivo de 800 ms no se cumple y hay que decirlo así.** La suma de partes
mentía por 2,6×: las sondas medían cada etapa aislada y en su mejor caso, y un
turno encadena dos llamadas al modelo con una herramienta en medio.

### Transcripción (n=3, un hablante, sin ruido)

| | p50 |
|---|---|
| literal | 16,7% |
| con números normalizados | 0,0% |
| números críticos recuperados | 3/3 |

### Tarea completada (calibración, 6 casos)

| | correcto | fugas de datos |
|---|---|---|
| **agente** | **5/6** | 0 |
| línea base sin modelo | 4/6 | 1 |

**EL RESERVADO (4 casos) NO SE HA TOCADO.** Pedirlo sin declarar que es la
medición final lanza una excepción.

---

## ADRs — las decisiones con lo que se descartó

- **0001** qué se mide exactamente en el presupuesto del turno
- **0002** cómo se decide que alguien terminó de hablar. Ventana de silencio
  sola: 1600 ms para no cortar a nadie, el 188% del presupuesto. Implementado
  por contenido el 23/09, cuesta 1225 ms
- **0003** qué dice el agente mientras la herramienta corre. Frase puente, y la
  regla de publicar siempre los dos números juntos
- **0004** adelantar la consulta antes de que el modelo la pida. Funciona, no
  se distingue del ruido, y el motivo es el hallazgo

---

## CINCO VECES QUE UNA MEDICIÓN SALIÓ LIMPIA Y ERA FALSA

Es la parte más valiosa del proyecto y el mejor material de entrevista.
**Coherente no es correcto.**

1. **El barrido del fin de habla aprobaba 100 ms.** Contaba cortes como
   `segmentos - 1`, y las grabaciones mudas daban un solo segmento.
2. **El prompt corto parecía 8× más rápido.** Se midió el último, con el plan
   gratuito ya encolando. Diferencia real: 10 ms.
3. **Una muestra de 80,6 s parecía latencia del modelo.** Era el SDK
   reintentando un 429 por dentro con el cronómetro corriendo.
4. **El error normalizado salía PEOR que el literal.** El normalizador solo
   entendía palabras y el ASR devuelve `1 0 7 0 2 3` y `347 mil 200`.
5. **El adelanto de consultas "mejoraba" con n=3 y "empeoraba" con n=6.** Las
   dos eran ruido. Y el conteo determinista destapó que el patrón del documento
   llevaba caracteres de retroceso (`\x08`): compilaba y no encajaba nunca.

Y una sexta que no es de medición sino de seguridad: **el agente saludaba con
"Hola, Sr. Ossa" y DESPUÉS pedía el nombre para verificar.** Quien llamara con
un documento ajeno se llevaba el dato de control de regalo.

---

## REGLAS DE TRABAJO (no negociables)

1. NUNCA `git push` sin preguntarme. Una autorización no se extiende a la
   siguiente. Commitear en local sin preguntar sí está bien.
2. Rama de feature, nunca commits a `main`. **Cada tanda nueva, su rama**,
   porque yo abro el PR y lo fusiono.
3. NINGUNA atribución a Claude en los commits.
4. Commits y documentación EN ESPAÑOL. Ramas y código en inglés.
5. Estoy en PowerShell: nada de `&&`, `rm -rf`, `export VAR=x`, `2>/dev/null`.
6. VERIFICA CONTRA EL STACK LEVANTADO, no solo que compile.
7. **Commitea ANTES de mutar código.**

## MÉTODO (funciona, no lo cambies)

- **Todo número va con su tamaño de muestra, su procedencia y la fecha.**
- **Rompe tus propios tests a propósito.** En este proyecto ha destapado tres
  tests que pasaban sin cubrir nada.
- **Coherente no es correcto.** Ver la lista de arriba.
- **Sé fiel al informar.** Si algo quedó sin comprobar, dilo. Si una
  recomendación mía resultó equivocada, dilo también.
- **No ajustes la vara al resultado.** Hay un caso de evaluación que el agente
  falla por desacuerdo razonable y se deja fallando, con el desacuerdo escrito.
- **Documenta el porqué, no el qué.**

## TRAMPAS DEL ENTORNO — no las redescubras

- **Los heredocs de bash se comen los escapes.** `\n` se convierte en salto de
  línea real y `\b` en un byte 0x08. Ha roto código cuatro veces, una de ellas
  silenciosamente (el patrón del documento). **Para cualquier parche con
  escapes, usa la herramienta de escritura de ficheros, no un heredoc.**
- **No se pueden lanzar procesos en segundo plano** (EPERM al hacer spawn). Los
  servidores se levantan con `uvicorn.Server` en un hilo dentro del propio
  script de prueba.
- **El DNS hacia `api.groq.com` se cae cada pocos minutos.** No es el código:
  se reintenta y a la segunda va.
- **El plan gratuito de Groq da 8000 tokens por minuto.** Midiendo seguido se
  revienta y las peticiones hacen cola: aparece una meseta de ~2,7 s que parece
  latencia del modelo. `probe/limites_groq.py` lo lee de las cabeceras.
- **`reasoning_effort` solo acepta `low`, `medium`, `high`.** Con `medium` el
  turno con herramienta pasa de 406 a 2928 ms.
- **`getUserMedia` solo existe en `https` o `localhost`.** Por la IP de la red
  el navegador bloquea el micrófono sin avisar.
- **`faster-whisper` en GPU necesita `nvidia-cublas-cu12` y `nvidia-cudnn-cu12`
  en el entorno virtual, y sus rutas ANTEPUESTAS AL PATH del proceso.**
  `os.add_dll_directory` sola no basta. Sin eso, el modelo carga en `cuda` y
  revienta en la primera inferencia.
- El audio normalizado va en ±1, no en enteros de 16 bits. Poner un umbral en
  la escala equivocada no da un detector malo: da uno sordo.

---

## LO QUE FALTA, Y EL CRITERIO: ACERCARLO A LA REALIDAD

De las seis métricas por las que el proyecto quiere ser juzgado están hechas la
1 (latencia), la 2 (tarea completada, solo calibración) y la 4 (transcripción).
Faltan la 3 (corrección de llamadas a herramientas), la 5 (coste por
conversación) y la 6 (barge-in).

**Todo lo medido hasta ahora está en condiciones de laboratorio**, y eso es el
límite del proyecto ahora mismo: una sola voz, sin ruido, sin línea telefónica,
micrófono de portátil, herramientas de mentira en `localhost`. Los pasos
siguientes están ordenados por cuánto acercan el sistema a una llamada de
verdad.

### 1. Ampliar el conjunto de evaluación antes de quemar el reservado
Con 4 casos reservados, un fallo son 25 puntos porcentuales. Subir a ~20 casos
totales, ~8 reservados. Añadir: alguien que da mal el documento dos veces,
alguien que cambia de tema a mitad, alguien enfadado, alguien que da datos de
otra persona, silencio total, y dos casos donde lo correcto sea negarse por
motivos distintos. **El reservado se mide UNA VEZ y se anota fecha y modelo.**

### 2. Voz de verdad: varias personas, ruido y línea telefónica
La tasa de transcripción tiene n=3 y un solo hablante en una habitación
silenciosa. Para que signifique algo: varias voces, ruido de fondo, y **audio
pasado por el filtro de una línea telefónica** (banda de 300–3400 Hz, 8 kHz).
Ese filtro se simula con `scipy` en diez líneas y cambia la tasa de error
bastante. Es el cambio que más acerca el número a la realidad por el menor
esfuerzo.

### 3. Barge-in, que exige cancelación de eco
Hoy, mientras el agente habla, **se ignora la entrada**, y está declarado como
decisión: sin cancelación de eco el micrófono capta la propia voz del agente y
el sistema se contesta a sí mismo. El navegador ofrece `echoCancellation` y ya
está pedido en `getUserMedia`, pero no se ha comprobado que baste. Es la
métrica 6 y es lo que más se nota en una demo: poder interrumpir al agente.

### 4. Telefonía real con Twilio Media Streams
Es el patrón de la industria y lo que convierte "una página web" en "llamé al
número desde mi móvil". Trae de regalo el audio de 8 kHz de verdad, la latencia
de red real, y el plano del vídeo que mejor se entiende. Crédito de prueba.

### 5. El expediente en PostgreSQL y el estado en Redis
Ahora el rastro de cada turno existe en memoria y se pierde al colgar. El
proyecto promete "al colgar queda un expediente con qué se dijo, qué
herramienta se llamó, con qué argumentos y qué devolvió". Eso hay que
escribirlo. Y mover el estado de `Llamada` a Redis es lo que permite defender
la frase de que la pasarela no guarda nada y escala horizontal — **hoy es
verdad por diseño pero no está demostrado**.

### 6. Coste por conversación (métrica 5)
Contar tokens y peticiones por llamada y sacar el dólar. Los tokens ya se leen
de la respuesta de Groq para el regulador de ritmo, así que es barato.

### 7. Deepgram, que sigue sin usarse
La clave está puesta y no se ha gastado un céntimo. Nova-3 en streaming
quitaría la doble transcripción que hoy cuesta ~500 ms en la ruta crítica, y
daría la tasa de error en español con acento paisa contra un sistema comercial.
Medir el coste por minuto desde la primera llamada.

### 8. Los ADR que faltan
Qué hace el agente cuando la transcripción tiene poca confianza; por qué no
puede afirmar nada que no venga de una herramienta; qué pasa si una herramienta
falla a mitad (implementado, sin escribir); idempotencia (implementada, sin
escribir).

---

## CÓMO EMPEZAR UNA SESIÓN NUEVA

```powershell
Set-Location C:\Users\ASUS\Desktop\agente_llamada
git status
.\.venv\Scripts\python.exe -m app.evaluation.correr        # ¿sigue en 5/6?
```

Y dime qué recomiendas. Si vas a proponer una optimización, **mira antes de qué
está hecho el tiempo que quieres optimizar**: ya recomendé una vez adelantar una
consulta que tardaba 5 ms para arreglar 1267 ms que eran del modelo.
