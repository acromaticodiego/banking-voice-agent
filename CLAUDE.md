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
| bucle del agente | `app/agent/loop.py` | decide, llama herramientas, se recupera, frase puente, presupuesto por turno, idempotencia, y un turno vacío no llega al modelo |
| herramientas | `app/tools/service.py` | FastAPI, una por capacidad. `X-Fallar` y `X-Tardar-Ms` para provocar fallo y latencia |
| fin de turno | `app/fin_de_turno.py` | decide si la frase está a medias, por contenido y no solo por silencio |
| números hablados | `probe/numeros_es.py` | "setenta, veintitrés, cuatro..." → `70234567`. Pieza del sistema, no solo de medición |
| tubería sobre fichero | `app/pipeline.py` | el mismo turno pero alimentado desde un WAV en tiempo real, para medir |
| evaluación | `app/evaluation/` | 20 casos con su rúbrica y su motivo, partición con reservado bajo llave, corredor, línea base sin modelo, estabilidad entre corridas, protocolo de la medición final |
| fundamento | `app/agent/fundamento.py` | compara lo que dice el agente con lo que devolvieron las herramientas: números y acciones. Determinista, sin modelo |
| canal telefónico | `probe/linea_telefonica.py` | 300–3400 Hz, 8 kHz y µ-law: el audio como llega por una llamada. Se comprueba solo |

**Levantar la demo:**
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
# y abrir http://127.0.0.1:8000/   (NO por la IP: el micrófono solo va en localhost o https)
```

**Comprobaciones (todas pasan hoy):**
```powershell
.\.venv\Scripts\python.exe -m app.tools.prueba_servicio      # 10/10
.\.venv\Scripts\python.exe -m app.agent.prueba_bucle         # 5 escenarios. Si acaba en 3, hubo 429: repite
.\.venv\Scripts\python.exe -m app.agent.prueba_fundamento    # 17/17, y no gasta peticiones
.\.venv\Scripts\python.exe -m app.agent.prueba_silencio      # el turno vacío, sin gastar peticiones
.\.venv\Scripts\python.exe -m app.agent.prueba_consumo       # el contador de tokens, exacto y sin cuota
.\.venv\Scripts\python.exe -m app.agent.prueba_reintentos    # tres documentos antes de escalar, sin cuota
.\.venv\Scripts\python.exe -m app.prueba_pasarela            # 5/5, con audio real de vuelta
.\.venv\Scripts\python.exe -m app.fin_de_turno               # 15/15
.\.venv\Scripts\python.exe probe\numeros_es.py               # 14/14
.\.venv\Scripts\python.exe -m app.evaluation.catalogo      # 20 casos, ids únicos, herramientas que existen
.\.venv\Scripts\python.exe -m app.evaluation.particion     # 12 calibración / 8 reservado, sin solapar
.\.venv\Scripts\python.exe probe\linea_telefonica.py         # el canal, se comprueba solo
```

**Medir:**
```powershell
.\.venv\Scripts\python.exe -m app.medir_turno --repeticiones 6 --fin-por-contenido
.\.venv\Scripts\python.exe -m app.evaluation.correr              # agente, calibración
.\.venv\Scripts\python.exe -m app.evaluation.correr --linea-base
.\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 12 --prompt actual --presupuesto-ms 15000
#   relee lo guardado y no gasta peticiones. Sin los filtros se niega a mezclar brazos distintos
.\.venv\Scripts\python.exe -m app.evaluation.medicion_final --ensayo --corridas 2
#   el protocolo de la medición final, ensayado sobre calibración. Sin --ensayo
#   y con --declaro-medicion-final, QUEMA el reservado: k=5, mayoría por caso
.\.venv\Scripts\python.exe probe\limites_groq.py     # ¿queda cuota HOY? mira el límite diario
.\.venv\Scripts\python.exe probe\probe_wer.py --linea-telefonica   # la tasa de error por teléfono
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

### Transcripción (n=3, un hablante, sin ruido, 2026-09-24)

| | micrófono, 16 kHz | por línea telefónica |
|---|---|---|
| literal p50 | 16,7% | 20,0% |
| con números normalizados, p50 | 0,0% | **0,0%** |
| números críticos recuperados | 3/3 | **3/3** |

La segunda columna es el mismo audio pasado por el canal de una llamada:
banda de 300–3400 Hz, muestreo a 8 kHz y cuantización µ-law de 8 bits (G.711),
y de vuelta a 16 kHz para el modelo. `probe/linea_telefonica.py`.

**Y aquí este documento se equivocaba.** Decía que ese filtro "cambia la tasa
de error bastante". No la cambia: el error normalizado sigue en 0,0% y los tres
números críticos se recuperan igual. Los 3,3 puntos del literal, con n=3, no se
distinguen del ruido. Conclusión honesta: **el canal telefónico no rompe a
`faster-whisper small` en este material**, y lo que queda por probar no es el
canal, son las voces y el ruido.

### Coste por conversación (métrica 5): instrumentado, sin medir

Los tokens ya se cuentan por paso, por turno y por conversación (24/09). **El
número todavía no existe** porque hace falta una corrida con cuota, y llega
gratis con la medición del reservado.

Y el precio está **SIN CONFIRMAR** a propósito: `groq.com/pricing` no listaba
`openai/gpt-oss-20b` el 24/09, así que `probe/precios.py` devuelve `None` y el
corredor dice "no se puede decir" en vez de imprimir un dólar inventado. Para
cerrarlo hacen falta dos números de la consola de Groq (entrada y salida por
millón), y quedan anotados con su fecha.

Lo que sí está comprobado, y es lo que cambia la lectura: **el coste de una
conversación crece más que linealmente**, porque cada turno reenvía la historia
anterior. Medir un turno y multiplicarlo por el número de turnos da un número
bajo que no es el que se factura.

### Tarea completada (calibración, 12 casos, 2026-09-24)

El conjunto pasó de 10 casos a 20, y la calibración de 6 a 12. Los números de
antes (agente 5/6, línea base 4/6) eran de una sola corrida sobre 6 casos y no
son comparables con estos.

Cada casilla son **tres corridas**, reclasificadas con el clasificador del
24/09 y con el detector de fundamento del 24/09. Las corridas con fallos del
proveedor se descartan, porque un 429 hace que el agente salga escalando y ese
desenlace no es suyo: por eso una casilla tiene n=2.

| desenlace correcto | prompt anterior | prompt con acciones |
|---|---|---|
| reloj de 3000 ms (el de la demo) | mediana 6,5/12, rango 5–8 (n=2) | **mediana 4/12, rango 3–5** |
| reloj holgado, 15000 ms | mediana 7/12, rango 6–9 | mediana 8/12, rango 6–9 |
| línea base sin modelo | 7/12, determinista, 12/12 estables | — |

**AVISO: estos números son de un agente que ya no existe.** Se midieron antes
de dos cambios de comportamiento del 24/09 —el turno vacío y los tres intentos
de documento—, así que no son comparables con lo que salga mañana. Una medición
sin la versión del agente al lado es una medición a medias, y esta lo era. Por
eso la primera cosa de mañana son 3 corridas de calibración **antes** del
reservado: para tener con qué comparar.

Estos números son con la **rúbrica del 24/09**, que añadió el desenlace
`resuelve_y_escala`. Antes de ella el clasificador describía con la palabra
`escala` dos conductas distintas, y castigaba la buena. La rúbrica subió a
todos en torno a un caso, **la línea base incluida** (de 6 a 7): corregía un
castigo injusto, no fabricaba ventaja para el agente. Los números de antes de
la rúbrica están en el ADR 0005 y no son comparables con estos.

| | fugas de datos | afirmaciones sin fundamento |
|---|---|---|
| agente, prompt nuevo, reloj holgado | 0 | 1, 1 y 0 de 12 |
| agente, prompt anterior, reloj holgado | 0 | 1, 2 y 1 de 12 |
| línea base sin modelo | 2 | 0, y no puede: solo imprime lo que le devolvieron |

**Sobre el conjunto ampliado, la ventaja del agente en el recuento de
desenlaces no se distingue del ruido.** Con el reloj holgado saca mediana 8
contra el 7 determinista de las reglas, y su rango es 6–9: lo tapa entero. Con
el reloj de la demo saca 4 y **pierde**. El 5/6 contra 4/6 de antes era ventaja
de un conjunto fácil.

Donde gana de verdad es en lo que no se cuenta en desenlaces: **la línea base
filtra datos de la cuenta en dos casos y el agente en ninguno**, en ninguna
corrida de ningún brazo. Un árbol de reglas que consulta y recita no sabe
callarse.

**Y la mitad del conjunto es moneda al aire**: 6 de los 12 casos cambian de
desenlace entre corridas del mismo día con el mismo modelo. Por eso el número
va con mediana y rango, y por eso `estabilidad.py` existe.

**El reloj y las decisiones están enredados y hay que decirlo:** la evaluación
corre con el reloj holgado porque lo que mide son decisiones, así que **ese
número no describe el sistema que se ve en la demo**. Con el reloj de 3000 ms,
el prompt nuevo agota el presupuesto en 8, 10 y 9 de los 12 casos, y el caso
se queda sin desenlace. Las dos cifras se publican juntas, como en el ADR 0003.

**EL RESERVADO (8 casos) NO SE HA TOCADO.** Pedirlo sin declarar que es la
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
- **0005** por qué no puede afirmar nada que no venga de una herramienta.
  Prompt, detector y el texto de respaldo que mentía. Con la tabla del coste:
  con el reloj de la demo, el prompt nuevo baja de 6 a 4 de 12
- **0006** qué pasa si una herramienta falla a mitad. El error es un resultado
  para el modelo, no una excepción, y `reintentable` distingue el 5xx del 4xx
- **0007** idempotencia de las acciones con efecto. La clave es del TURNO —ni
  de la llamada ni de la conversación— y de ahí se sigue que nada con efecto
  se puede adelantar. Escribirlo destapó que nadie comprobaba que la lista
  blanca estuviera completa

---

## SIETE VECES QUE UNA MEDICIÓN SALIÓ LIMPIA Y ERA FALSA

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
6. **El 5/6 de la tarea completada era una sola tirada** (23/09). Tres corridas
   del conjunto ampliado, el mismo día y el mismo modelo, dieron 6, 5 y 7 de
   12, y **6 de los 12 casos cambian de desenlace entre corridas**. Un número
   de una corrida no distingue al agente que resuelve siempre del que acertó
   esa vez. `estabilidad.py` lo saca sin gastar ni una petición, releyendo lo
   guardado. Y hay un segundo filo: las corridas de una misma tarde se hacen
   con clasificadores distintos, así que comparar sus resultados tal cual
   mezcla dos variables. Hay que reclasificar con el de hoy.
7. **El prompt nuevo parecía haber acabado con los inventos: cero
   afirmaciones sin fundamento** (24/09). Y era verdad que había cero, porque
   con el reloj de 3000 ms el presupuesto saltaba en 9 de los 12 casos y el
   agente no llegaba a decir nada: se quedaba en "sigo verificando la
   información". Un agente al que se corta antes de hablar no miente, y eso no
   es una virtud. Con el reloj holgado los inventos reaparecen —otros, pero
   reaparecen—. **La medición más limpia de todas es la del sistema al que no
   se le ha dejado funcionar.**

Y una más que no es de medición sino de seguridad: **el agente saludaba con
"Hola, Sr. Ossa" y DESPUÉS pedía el nombre para verificar.** Quien llamara con
un documento ajeno se llevaba el dato de control de regalo.

Y la última, del 23/09, que es de las que asustan: **el agente dijo haber
hecho cosas que no hizo.** Verificada la identidad y sin llamar a ninguna
herramienta: "He bloqueado todas sus tarjetas y cuentas... llame al 01 8000
1234". No existe herramienta que bloquee nada y ese teléfono no existe. El
prompt prohíbe afirmar **datos** que no vengan de una herramienta, y una acción
no es un dato. Lo vigila `no_debe_prometer`, que es un cepo literal y solo caza
lo que ya se ha visto decir.

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
- **Y da 200 000 tokens AL DÍA, que es el límite que de verdad para el
  trabajo, y NO sale en ninguna cabecera.** Solo aparece en el cuerpo del 429:
  `on tokens per day (TPD): Limit 200000, Used 199919`. El 24/09 costó tres
  diagnósticos equivocados seguidos: la sonda decía que quedaban 7920 tokens
  del minuto mientras el día estaba al 99,9%. Una tarde de evaluaciones
  (~20 corridas de 12 casos) se lo come. La sonda ahora hace una petición del
  tamaño real y dice qué límite fue; `medicion_final.py` distingue el diario
  del de por minuto y para en vez de reintentar, porque con el diario esperar
  no sirve.
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
micrófono de portátil, herramientas de mentira en `localhost`.

El criterio era ordenar los pasos por cuánto acercan el sistema a una llamada
de verdad, y **ampliar el conjunto de evaluación lo cambió**: de poco sirve
acercar a la realidad un agente que afirma haber bloqueado una tarjeta que no
ha tocado, ni medirlo con un instrumento que da tres números distintos en la
misma tarde. Los cuatro primeros pasos son eso; del quinto en adelante sigue el
criterio de la realidad.

### ~~1. Ampliar el conjunto de evaluación~~ HECHO el 2026-09-23
20 casos, 12 de calibración y 8 reservados, con los cuatro desenlaces en las
dos mitades. Lo que salió al ampliarlo cambió la lista de abajo: el conjunto
fácil escondía tres agujeros del agente y dos del instrumento. Lo que sigue
está reordenado por eso.

### ~~1. Que el agente no pueda afirmar lo que no hizo~~ HECHO el 2026-09-24, y quedan tres cosas
Prompt extendido a acciones y procedimientos, detector `fundamento.py`, ADR
0005 y —lo que no se esperaba— el texto de respaldo del propio bucle, que
prometía un asesor sin llamar a nadie.

Lo que el prompt perseguía desapareció: el teléfono inventado y el "he
bloqueado" salían en 2 de 3 corridas cada uno con el prompt viejo, y en 0 de 3
con el nuevo. **Pero el fallo se movió de sitio**: ahora dice "le paso con un
asesor" sin llamar a la herramienta, en 2 de 3. Solo se ve porque el detector
no necesita haber visto antes la frase.

Lo que queda, y está en el ADR 0005:

- **Los procedimientos inventados no los caza nadie.** "Necesitamos que el
  nuevo titular esté presente" no lleva números ni afirma acciones en primera
  persona. Es el hueco grande.
- **La promesa de transferencia**, que es el fallo nuevo.
- **Si el detector entra en la ruta de la voz**, revisando la frase antes de
  decirla, y qué hace cuando marca: callar, escalar, o hablar y anotarlo. No
  se decide hasta saber cuántos falsos positivos deja; los tres conocidos ya
  están arreglados, pero tres es un rato de datos, no una base.

### ~~2. Decidir CÓMO se mide el reservado~~ DECIDIDO Y ESCRITO el 2026-09-24
Las dos decisiones están tomadas con el reservado **sin tocar**, que era la
única ventana para tomarlas sin trampa:

- **k=5 corridas**, y se publican cuatro cosas: mediana, rango, conteo por caso
  (en cuántas de las 5 acertó) y tabla de estables. La mayoría por caso (≥3 de
  5) es el resumen de una cifra. Una corrida con fallos del proveedor se
  repite, no se promedia; si no salen 5 limpias, **el programa se niega a dar
  un número**. Todo eso está en `app/evaluation/medicion_final.py`, que además
  no corre dos veces sobre el mismo conjunto sin declararlo.
- **Quinto desenlace `resuelve_y_escala`**, y cada caso declara en
  `tambien_acepta` qué otros le valen, con la regla escrita: *un desenlace
  alternativo solo se acepta si aceptarlo no hace pasar a un agente degenerado
  que escale siempre*. De ahí sale que en `rechaza` y `pide_repetir` no vale
  nada más.

**Falta correrla.** El ensayo del protocolo sobre calibración verificó la parte
que se niega —descarta corridas contaminadas y para en seco con el límite
diario—, pero el camino bueno no se ha visto porque el 24/09 se gastaron los
200 000 tokens del día. Es lo primero de la próxima sesión.

### 3. El presupuesto del turno se come la evaluación — SEPARADO, no resuelto
El turno tiene 3000 ms y el turno de verdad mide 2389: quedan 287 ms de margen.
Con el conjunto de 6 el presupuesto no se agotaba nunca; con el de 12 pasó en
1 a 3 casos, y **al alargar el prompt, en 8, 10 y 9 de 12**. Cuando salta, el
agente dice la frase de relleno y el caso se queda sin desenlace: la métrica de
tarea completada estaba midiendo latencia sin querer.

Ya está separado en el instrumento: `correr.py` lleva `--presupuesto-ms`,
holgado por defecto porque ahí se miden decisiones, y cuenta los turnos en los
que salta el reloj para que nunca se cuelen como decisiones del agente.

**Lo que no está resuelto es el sistema.** Con el reloj de la demo el agente
saca 4 de 12 y con el holgado 8 de 12, así que el número que se publica no
describe lo que se ve en la demo. Eso se arregla haciendo el turno más rápido
—no relajando el reloj—, y el turno son dos llamadas al modelo con una
herramienta en medio. Mientras tanto, las dos cifras van juntas.

### ~~4. Silencio y documento equivocado~~ LOS DOS HECHOS el 2026-09-24
El del silencio está hecho (24/09): un turno vacío ya no llega al modelo, se
contesta con dos preguntas distintas y al tercer silencio se pasa a un humano
con su ticket. Cuesta cero tokens y cero espera, y `prueba_silencio.py` lo
cubre con un modelo que revienta si alguien lo llama. **Lo que ese arreglo no
tapa:** Whisper alucina sobre el silencio y devuelve "Gracias." o un trozo de
subtítulos; eso no es una cadena vacía y el guardia no lo ve.

El del documento equivocado también: ahora se prueban **tres documentos
distintos** antes de pasar a un humano, y la cuenta no la lleva el prompt —que
no sabe contar— sino el agente, que se la da masticada al modelo en el
resultado de la herramienta (`_intentos_en_esta_llamada`, `_que_hacer`). Se
cuentan documentos distintos y no llamadas, porque el adelanto de consultas y
la insistencia del modelo repiten la misma cédula; y una herramienta caída no
cuenta como documento malo, porque eso no es un documento mal dicho, es que no
se pudo preguntar.

**Lo determinista está comprobado; que el modelo obedezca, no.** Eso se mide
con el conjunto y cuesta cuota.

### 5. Voz de verdad: varias personas y ruido (la línea ya está)
El canal telefónico está hecho (24/09) y **el resultado fue que no importa**:
banda de 300–3400 Hz, 8 kHz y µ-law dejan el error normalizado en 0,0% y los
números críticos en 3/3. Se creía que era "el cambio que más acerca el número a
la realidad por el menor esfuerzo"; fue barato, y lo que enseñó es que el
cuello de botella está en otra parte.

Lo que queda, y ahora es lo único que queda de este punto: **varias voces y
ruido de fondo.** n=3 con un solo hablante en una habitación callada no es una
tasa de error, es una calibración de orden de magnitud. Y con el canal ya
simulado, cualquier grabación nueva se puede medir por los dos caminos sin
volver a grabar nada.

### 6. Barge-in, que exige cancelación de eco
Hoy, mientras el agente habla, **se ignora la entrada**, y está declarado como
decisión: sin cancelación de eco el micrófono capta la propia voz del agente y
el sistema se contesta a sí mismo. El navegador ofrece `echoCancellation` y ya
está pedido en `getUserMedia`, pero no se ha comprobado que baste. Es la
métrica 6 y es lo que más se nota en una demo: poder interrumpir al agente.

### 7. Telefonía real con Twilio Media Streams
Es el patrón de la industria y lo que convierte "una página web" en "llamé al
número desde mi móvil". Trae de regalo el audio de 8 kHz de verdad, la latencia
de red real, y el plano del vídeo que mejor se entiende. Crédito de prueba.

### 8. El expediente en PostgreSQL y el estado en Redis
Ahora el rastro de cada turno existe en memoria y se pierde al colgar. El
proyecto promete "al colgar queda un expediente con qué se dijo, qué
herramienta se llamó, con qué argumentos y qué devolvió". Eso hay que
escribirlo. Y mover el estado de `Llamada` a Redis es lo que permite defender
la frase de que la pasarela no guarda nada y escala horizontal — **hoy es
verdad por diseño pero no está demostrado**.

### ~~9. Coste por conversación~~ INSTRUMENTADO el 2026-09-24, falta medirlo
Los tokens se cuentan por paso, por turno y por conversación, y el contador
está comprobado con un modelo de mentira que declara su consumo (exacto, sin
cuota). Faltan dos cosas y ninguna es código:

- **El precio**, que no se inventa: dos números de la consola de Groq.
- **Una corrida con cuota**, que llega gratis con la medición del reservado.

### 10. Deepgram, que sigue sin usarse
La clave está puesta y no se ha gastado un céntimo. Nova-3 en streaming
quitaría la doble transcripción que hoy cuesta ~500 ms en la ruta crítica, y
daría la tasa de error en español con acento paisa contra un sistema comercial.
Medir el coste por minuto desde la primera llamada.

### 11. El ADR que falta
Solo queda uno: **qué hace el agente cuando la transcripción tiene poca
confianza**, y ese no está implementado, así que no es escribir sino decidir.
Los otros tres cayeron el 24/09: el 0005 (no afirmar lo que no venga de una
herramienta), el 0006 (herramienta que falla a mitad) y el 0007
(idempotencia).

Y de escribir los dos últimos salió algo que no se esperaba: **explicar por qué
la lista de herramientas adelantables es una lista blanca destapó que nadie
comprobaba que estuviera completa.** Una herramienta con efecto que nadie
clasificara no daba error, solo se quedaba sin protección contra reintentos.
Documentar lo ya implementado no es papeleo.

---

## CÓMO EMPEZAR UNA SESIÓN NUEVA

```powershell
Set-Location C:\Users\ASUS\Desktop\agente_llamada
git status
git log --oneline -5
.\.venv\Scripts\python.exe probe\limites_groq.py    # ¿hay cuota HOY? mira el límite DIARIO
```

Las comprobaciones que no gastan cuota están arriba, en ESTADO, y pasan todas.
Córrelas si has tocado algo.

Y dime qué recomiendas. Si vas a proponer una optimización, **mira antes de qué
está hecho el tiempo que quieres optimizar**: ya recomendé una vez adelantar una
consulta que tardaba 5 ms para arreglar 1267 ms que eran del modelo.

---

## EL SIGUIENTE PASO, en orden y sin margen de interpretación

Escrito el 2026-09-24 al final de la sesión. **Es la medición final del
reservado, y el orden importa porque el reservado se gasta al mirarlo.**

### 0. Antes de nada: ¿hay cuota?

El límite que manda es de **200 000 tokens al día** y NO sale en las cabeceras.
El canario no es una petición suelta —eso pasa aunque no haya sitio para una
corrida—, es esto:

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.medicion_final --ensayo --corridas 1
```

Si esa sale limpia, hay cuota. Cuesta ~5% del día. **Si no la hay, no se
empieza**: hay trabajo de sobra que no gasta cuota (ver más abajo).

### 1. Tres corridas de calibración PRIMERO

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.correr      # x3, espaciadas
.\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 12 --prompt actual --presupuesto-ms 15000
```

**Sin esto el reservado no significa nada.** Los números de la tabla de tarea
completada se midieron con un agente que ya no existe: sin el turno vacío y sin
los tres intentos de documento. Hacen falta 3 corridas del agente de HOY para
tener con qué comparar, y se hacen antes porque después del reservado ya no se
puede cambiar nada sin contaminar.

### 2. El reservado, k=5, una vez en la vida

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.medicion_final --declaro-medicion-final
```

El protocolo ya está escrito en el propio módulo y no se cambia ahora: k=5,
mediana, rango, conteo por caso, mayoría (≥3 de 5) y tabla de estables. Una
corrida con fallos del proveedor se repite, **no se promedia**. Si no salen 5
limpias, el programa se niega a dar un número, y eso se respeta.

Sale además el **coste por conversación** (métrica 5) de regalo, porque los
tokens ya se cuentan.

### 3. Y entonces, con el número en la mano

- Actualizar la tabla de LOS NÚMEROS con el reservado, la fecha, el modelo y el
  commit. **Y decir que el reservado está quemado**: a partir de ahí todo lo
  que se toque está informado por ese resultado, y hay que escribirlo cada vez
  que se cite la cifra.
- Rellenar `probe/precios.py` con los dos números de la consola de Groq
  (entrada y salida por millón) para cerrar el coste en dólares. Sin ellos se
  publican los tokens y se dice que el precio falta.

### Si no hay cuota, esto avanza sin gastar nada

En este orden de valor:

1. **Barge-in** (punto 6): es lo que más se nota en una demo y lo único que
   falta de las seis métricas junto al coste. Hace falta probarlo a mano con el
   micrófono, así que requiere a Juan Diego delante.
2. **El expediente en PostgreSQL y el estado en Redis** (punto 8): el proyecto
   promete que al colgar queda un expediente y hoy se pierde al cerrar el
   proceso. Es la mayor distancia entre lo que promete y lo que hace.
3. **El ADR que falta**: qué hace el agente cuando la transcripción tiene poca
   confianza. No está implementado, así que es decidir, no escribir.
