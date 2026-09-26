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
| cuota | `app/evaluation/cuota.py` | el libro de la ventana deslizante de 24 h: cuánto se gastó, cuánto queda y **a qué hora cabrá** una medición entera. Cota optimista a propósito, y lo dice |
| fundamento | `app/agent/fundamento.py` | compara lo que dice el agente con lo que devolvieron las herramientas: números, acciones y —desde el 24/09— procedimientos inventados. Determinista, sin modelo |
| confianza del ASR | `app/confianza.py` | resume lo que el modelo sabe de su propia transcripción. Se anota, no decide. ADR 0008 |
| telefonía | `app/telefonia/` | G.711 µ-law de verdad y el protocolo de Twilio Media Streams, comprobado sin cuenta con un cliente que lo emula |
| estado compartido | `app/estado.py` | el estado conversacional en Redis, una escritura por turno. Otra pasarela puede retomar la llamada, y hay prueba de que lo hace |
| expediente | `app/expediente/` | lo que queda al colgar en PostgreSQL: qué se dijo, qué herramienta con qué argumentos, qué devolvió y qué se revisó. Se lee con `-m app.expediente.leer` |
| detector adaptativo | `app/deteccion_voz.py` | **NO está en uso.** Se puso y se revirtió el 24/09: ver ADR 0009. Se conserva con sus pruebas por el hallazgo |
| canal telefónico | `probe/linea_telefonica.py` | 300–3400 Hz, 8 kHz y µ-law: el audio como llega por una llamada. Se comprueba solo |

**Levantar la demo:**
```powershell
docker compose up -d       # PostgreSQL (expediente) y Redis. Sin esto el
                           # sistema corre igual, pero el expediente se pierde
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
# y abrir http://127.0.0.1:8000/   (NO por la IP: el micrófono solo va en localhost o https)
```

**Comprobaciones (todas pasan hoy):**
```powershell
.\.venv\Scripts\python.exe -m app.tools.prueba_servicio      # 10/10
.\.venv\Scripts\python.exe -m app.agent.prueba_bucle         # 5 escenarios. Si acaba en 3, hubo 429: repite
.\.venv\Scripts\python.exe -m app.agent.prueba_fundamento    # 28/28, y no gasta peticiones
.\.venv\Scripts\python.exe -m app.agent.prueba_silencio      # el turno vacío, sin gastar peticiones
.\.venv\Scripts\python.exe -m app.agent.prueba_consumo       # el contador de tokens, exacto y sin cuota
.\.venv\Scripts\python.exe -m app.agent.prueba_reintentos    # tres documentos antes de escalar, sin cuota
.\.venv\Scripts\python.exe -m app.prueba_confianza          # el filtro de voz sigue puesto, sin cuota ni GPU
.\.venv\Scripts\python.exe -m app.prueba_deteccion_voz     # el detector de voz y su limite conocido, sin cuota ni GPU
.\.venv\Scripts\python.exe -m app.prueba_expediente        # el expediente. SIN Postgres sale con codigo 2, no con 0
.\.venv\Scripts\python.exe -m app.prueba_estado            # turno 1 en una pasarela, turno 2 en otra. SIN Redis, codigo 2
.\.venv\Scripts\python.exe -m app.prueba_telefonia         # el canal de Twilio, sin Twilio. G.711 contra audioop
.\.venv\Scripts\python.exe -m app.prueba_interrupcion      # cortar al agente (metrica 6), sin microfono
.\.venv\Scripts\python.exe -m app.prueba_pasarela            # 5/5, con audio real de vuelta
.\.venv\Scripts\python.exe -m app.fin_de_turno               # 15/15
.\.venv\Scripts\python.exe probe\numeros_es.py               # 14/14
.\.venv\Scripts\python.exe -m app.evaluation.catalogo      # 20 casos, ids únicos, herramientas que existen
.\.venv\Scripts\python.exe -m app.evaluation.particion     # 12 calibración / 8 reservado, sin solapar
.\.venv\Scripts\python.exe -m app.evaluation.prueba_cuota --romper    # el libro de la cuota, 10/10, y sus 6 mutaciones cazadas
.\.venv\Scripts\python.exe -m app.evaluation.prueba_canario --romper  # que el canario NO deje tocar el reservado sin cuota para acabar. 6/6
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
.\.venv\Scripts\python.exe probe\limites_groq.py     # ¿queda cuota AHORA? y ¿a qué hora cabrá una medición entera?
.\.venv\Scripts\python.exe probe\sembrar_libro_cuota.py --rehacer
#   rellena el libro de la cuota con lo ya gastado, leyéndolo de los artefactos.
#   Hace falta si el libro se queda ciego (máquina nueva, o borrado): un libro
#   vacío NO significa que la ventana esté limpia, significa que no sabe
.\.venv\Scripts\python.exe probe\confianza_asr.py   # ¿se inventa Whisper turnos? cero tokens, unos 4 min
.\.venv\Scripts\python.exe probe\sordera_asr.py     # ¿deja sordo el filtro? ¿se abre turno? cero tokens
.\.venv\Scripts\python.exe probe\umbral_voz.py      # el factor del detector, sin GPU ni cuota
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

*Esta tabla es de antes del filtro de voz. La medición del 24/09 con el filtro
puesto está más abajo, en "El turno, vuelto a medir".*

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

### Turnos que nadie dijo (2026-09-24, 106 clips: 42 con voz, 64 sin ella)

Whisper se inventa frases sobre el ruido de fondo, y lo que se inventa tiene
letras, así que el guardia del turno vacío —que mira si hay alguna letra o
dígito— lo deja pasar como si alguien hubiera hablado.

| | sin filtro | con `vad_filter=True` |
|---|---|---|
| clips sin voz que producen texto | **16 de 64** | **0 de 64** |
| clips con voz que se quedan mudos | 0 de 42 | 0 de 42 |
| latencia, turno de 3 s + 1,2 s, mediana n=18 | 178 ms | 202 ms (**+24 ms**) |

El silencio no es sintético: son 142 tramos de cuarto de segundo de las propias
grabaciones, cosidos en clips de 1, 2, 4 y 8 s. 1 de 13 a 1 s, 4 de 15 a 2 s,
5 de 15 a 4 s, 6 de 17 a 8 s: **cuanto más silencio se le da, más inventa**, y
ya inventa con un solo segundo. Ninguno de los 24 clips por línea telefónica
alucinó. Dos corridas dieron el mismo 16 y el mismo desglose.

**El primer número fue 7 de 64 y estaba mal**, y el material lo escondía en vez
de exagerarlo: es el punto 10 de la lista de mediciones falsas.

Lo que sale: *"¿Qué pasa?"*, *"¡Suscríbete!"*, *"Este es el canal de subtítulos
en español de la Iglesia…"*. La primera es la peligrosa: no delata nada y un
agente bancario se la traga como turno del cliente. **Qué clip alucina se
repite entre corridas; qué dice, no** — es el fallback de temperatura de
Whisper, que es aleatorio por dentro.

Decidido en el ADR 0008: el filtro va puesto y las señales del ASR se anotan
sin actuar. `probe/confianza_asr.py`.

### El turno, vuelto a medir con el filtro puesto (2026-09-24, n=6)

| | 23/09, sin filtro | 24/09, con filtro |
|---|---|---|
| primer audio (fin de turno por contenido) | 2795 ms | **2234 ms** |
| primer dato | 3625 ms | **3112 ms** |

**La diferencia NO se le puede atribuir al filtro**, y decirlo importa: son
días distintos y el componente que manda en ese número es el modelo remoto
—1459 de los 2234 ms son del agente—. Lo que sí se puede afirmar es que el
filtro no ha empeorado el turno de forma medible, y que los +24 ms que cuesta
medido aparte caben dentro del ruido de esta cifra.

### Quién abre un turno: el umbral fijo se queda (2026-09-24)

El 24/09 pareció que el umbral fijo de `0.005` describía esta habitación y no
una llamada, se sustituyó por un detector adaptativo, y **se revirtió el mismo
día**. Medido con la clase `Llamada` de verdad, 6 grabaciones por caso:

| caso | umbral fijo | detector adaptativo |
|---|---|---|
| original | **6 / 6** | **0 / 6** |
| voz a la mitad de volumen | **6 / 6** | 5 / 6 |
| voz al 25% | **6 / 6** | 6 / 6 |
| por línea telefónica | **6 / 6** | 5 / 6 |

**El umbral fijo oye la voz floja y la telefónica**, porque `voz_ms` acumula
trozo a trozo durante toda la intervención y no se reinicia en los silencios
de en medio. El "0 de 6 con la voz a la mitad" que justificaba el cambio salía
de una sonda que comparaba el nivel MEDIO del clip entero contra el umbral,
que no es lo que hace el sistema.

Y el adaptativo rompía el caso normal: declara voz en el 96-97% de los trozos
de una grabación real, el silencio seguido más largo cae de 2520 ms a 380, y
con la ventana de cierre de 1200 ms **el turno no termina nunca**. Lo cazó
`app/prueba_pasarela.py`, no las seis pruebas deterministas, que estaban todas
en verde. Está entero en el ADR 0009, que es de los documentos más útiles del
proyecto precisamente por eso.

### Coste por conversación (métrica 5): MEDIDO sobre calibración (2026-09-25)

| | |
|---|---|
| tokens por conversación, media | **2 554** (n=12 conversaciones, 40 peticiones) |
| **coste por conversación** | **0,000226 $** |
| coste de una corrida de 12 casos | 0,00271 $ |
| repetibilidad | tres corridas del 25/09: 2 554 / 2 544 / 2 552 tokens, 0,000226 / 0,000226 / 0,000225 $ |

Precio de la ficha del modelo en Groq, confirmado el 24/09: 0,075 $/millón de
entrada y 0,30 $/millón de salida. **Es de calibración, no del reservado**: son
12 casos de 2 turnos, así que describe conversaciones cortas. La cifra del
reservado sale con la medición final, que ahora sí la calcula —hasta el 25/09
`medicion_final.py` llamaba al turno del agente sin pedirle el consumo y su
artefacto salía con `consumo: null`, mientras este documento prometía que la
métrica 5 saldría «de regalo». No habría salido.

Lo que sí sigue en pie del análisis viejo, y es lo que importa: **el coste de
una conversación crece más que linealmente**, porque cada turno reenvía la
historia anterior. Medir un turno y multiplicarlo por el número de turnos da un
número bajo que no es el que se factura. Con 2 turnos por caso el efecto casi no
se ve; una llamada de verdad tiene más.

**El precio ya está confirmado (24/09):** 0,075 $ por millón de tokens de
entrada y 0,30 $ por millón de salida, de la ficha del modelo en la
documentación de Groq. `groq.com/pricing` sigue sin listar el modelo —por eso
el primer intento se quedó sin número—, pero la ficha lo publica por partida
doble (el precio y cuántos tokens da un dólar) y las dos columnas cuadran, que
es lo que permite fiarse. En `probe/precios.py`, con fuente y fecha.

**Lo que se paga HOY es cero**, porque se desarrolla en el plan gratuito. Eso
no hace inútil la métrica: el coste por conversación no mide la factura del
desarrollo, mide **cuánto costaría operarlo**, que es la pregunta que decide si
el sistema es viable. En producción nadie corre sobre el plan gratuito, donde
8000 tokens por minuto dan para una conversación a la vez.

Y hay un tercer precio que aquí no es un detalle: **la entrada ya vista se
cobra a 0,037 $ por millón, la mitad.** Como el crecimiento superlineal del
coste viene de que cada turno reenvía la conversación entera, la caché de
prompt ataca exactamente esa parte. Y ahora hay con qué comparar: de los 2 554
tokens de una conversación, **2 402 son de entrada** (94%), así que es ahí donde
está todo el coste y la caché atacaría casi la factura entera.

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
de documento—, así que no son comparables con lo de después. Una medición
sin la versión del agente al lado es una medición a medias, y esta lo era. Desde
el 25/09 el artefacto guarda el commit y `estabilidad.py` se niega a mezclar
versiones: antes las mezclaba en silencio, y de hecho lo hizo.

#### Las corridas del 25/09, que son del agente de hoy

Cuatro corridas de calibración, reloj holgado, commit `15f5acc`. **Dos limpias y
dos contaminadas**, y las contaminadas no se promedian: una por la caída de DNS
de siempre y otra por haberse acabado la ventana de cuota a mitad.

| corrida | desenlace correcto | fugas | sin fundamento |
|---|---|---|---|
| 1, limpia | **9/12** | 0 | 0 |
| 2, limpia | **8/12** | **1** (`nombre-no-coincide`) | 1 |
| 3, descartada (1 fallo de red) | 7/12 | 0 | 0 |
| 4, descartada (3 fallos, ventana agotada) | 5/12 | 0 | 1 |
| ensayo del protocolo, k=1 | 8/12 | **1** (`nombre-no-coincide`) | 0 |

**Son 2 corridas limpias, no las 3 que pide el paso 1**, porque la ventana de
cuota se agotó. Faltan una o dos, y el reservado no se toca antes.

Y dos cosas que salieron de mirarlas juntas:

- **La fuga de datos que la tabla de arriba daba por cero existe.** `0` era el
  número del 24/09 «en ninguna corrida de ningún brazo»; el 25/09 aparece en 2
  de 3 lecturas del caso `nombre-no-coincide`, que es precisamente el que
  comprueba que el dato de control no se regale a quien no lo aportó. Es la
  familia del «Hola, Sr. Ossa». **Sin decidir qué hacer.**
- **`fraude-en-curso` falla las 5 veces, siempre igual** (`resuelve` cuando
  debía escalar). Eso no es ruido: es un fallo reproducible, y es el caso del
  peor fallo que este conjunto ha destapado nunca —el agente que dijo haber
  bloqueado tarjetas que no tocó—.

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

Donde parecía ganar de verdad era en lo que no se cuenta en desenlaces: **la
línea base filtra datos de la cuenta en dos casos y el agente en ninguno**, en
ninguna corrida de ningún brazo. Un árbol de reglas que consulta y recita no sabe
callarse.

**Y el 25/09 eso dejó de ser cierto.** En 2 de 3 lecturas del caso
`nombre-no-coincide`, el agente consultó `estado_tarjeta` y recitó los datos
—«su tarjeta de débito con los últimos 4 dígitos 4582 está bloqueada desde el 15
de septiembre por un movimiento inusual»— y **después** pidió el nombre para
verificar. Quien llamaba había dado un nombre que no es el del titular. Es
palabra por palabra el patrón del «Hola, Sr. Ossa»: el dato de control se regala
antes de comprobar nada.

Así que la lectura correcta hoy es más pequeña: el agente filtra **menos** que la
línea base y en **menos** casos, no en ninguno. La diferencia sigue estando, pero
ya no es categórica, y cualquier versión de esta frase que diga «en ninguno» hay
que fecharla en el 24/09 y decir que no se sostuvo.

#### Por qué se filtra: la garantía es sólo textual (diagnosticado el 26/09)

Sin tocar nada, porque el reservado se mide con el agente tal cual. El fallo
**no** es que falte la regla en el prompt. La regla está, y es explícita:
*«NUNCA digas el nombre del titular ni ningún otro dato de la cuenta antes de
haber verificado la identidad: pregúntalo y compáralo en silencio»*.

Lo que falta es que nadie la comprueba:

- `estado_tarjeta` recibe un `id_cliente` y devuelve las tarjetas **sin mirar si
  la identidad se verificó**. `app/tools/service.py`.
- La precondición vive en la *descripción de la herramienta* —«Estado de la
  tarjeta de un cliente verificado»—, o sea en texto dirigido al modelo, no en
  código.
- El bucle del agente **no lleva estado de identidad verificada**: no hay nada
  que se pueda consultar aunque alguien quisiera.

O sea que el prompt prohíbe **decir** el dato y nada impide **obtenerlo**, y con
el resultado ya en el contexto el modelo lo recita. Es exactamente el patrón que
obligó a escribir `fundamento.py`: el prompt prohibía afirmar datos que no
vinieran de una herramienta, y resultó que una *acción* no es un dato. Aquí la
grieta es la misma una capa más abajo.

**El arreglo, para cuando el reservado ya esté medido:** mover la garantía del
texto al código —que `estado_tarjeta` se niegue a devolver datos mientras la
identidad de esa llamada no esté verificada, y que «verificada» signifique que el
nombre lo aportó quien llama y coincidió—. Eso convierte una regla que el modelo
obedece casi siempre en una que no puede desobedecer. Y hay que medirlo: el
recuento de fugas del conjunto es el que dice si funcionó.

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
- **0009** cuándo se decide que alguien está hablando. **REVERTIDA el mismo
  día**: el detector adaptativo rompía el cierre del turno y el problema que
  venía a resolver no existía. Se deja entero, con el desmontaje y las cuatro
  lecciones, porque vale más que la decisión
- **0008** qué hace el agente cuando la transcripción no es de fiar. Whisper
  se inventa turnos sobre el silencio —7 de 64 clips— y `vad_filter=True` los
  deja en 0 por +24 ms. El umbral de confianza se descartó con su motivo
- **0007** idempotencia de las acciones con efecto. La clave es del TURNO —ni
  de la llamada ni de la conversación— y de ahí se sigue que nada con efecto
  se puede adelantar. Escribirlo destapó que nadie comprobaba que la lista
  blanca estuviera completa

---

## CATORCE VECES QUE UNA MEDICIÓN SALIÓ LIMPIA Y ERA FALSA

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
8. **El filtro de voz costaba +123 ms, y luego +158, y las dos veces era
   falso** (24/09). Se midió transcribiendo las grabaciones enteras, que duran
   entre 17 y 30 segundos. Nadie contesta eso por teléfono: un turno son tres
   segundos de habla y su cola de silencio. Medido sobre eso, el filtro cuesta
   **+24 ms**. La medición era reproducible, la sonda no tenía ningún fallo y
   el número estaba mal por 5×, porque **medía el material equivocado**. Es la
   misma familia que la suma de etapas que mentía por 2,6×.
9. **Un umbral que separaba 7 de 7 y se cayó solo al enseñarle más material**
   (24/09). Un corte por `avg_logprob` distinguía perfectamente los turnos
   inventados de los de verdad. Entraron seis clips de habla más —no de
   silencio: de habla legítima— y el peor de ellos se puso justo donde estaba
   el corte, que bajó con él y pasó a cazar 5 de 7. No hubo error de medición:
   **el umbral nunca había sido bueno, solo había visto poco.** Por eso el ADR
   0008 anota las señales y no actúa sobre ellas. Y con el material de silencio
   arreglado —el punto siguiente— quedó en 6 de 16: tres medidas, cada una peor
   que la anterior.
10. **El material de silencio no era silencio: el criterio elegía justo los
    tramos contaminados** (24/09). Para medir cuánto se inventa Whisper sobre
    el silencio hace falta silencio, y se cogían los tramos de cada grabación
    cuya energía bajara del 10% de la del fichero. Lo que más baja la energía
    de un tramo no es el silencio de la sala: son **los ceros exactos que el
    grabador deja al principio y al final**, 18 trozos de 20 ms en cada una de
    las seis. El banco se llenó de tramos medio mudos —10 en total, cinco
    segundos reciclados en 48 clips— y cada clip alternaba silencio digital con
    ruido real. Con un criterio relativo al suelo real de cada fichero salen
    142 tramos y la alucinación pasa de 7 de 64 a **16 de 64**. La sonda estaba
    bien y el análisis estaba bien: **el material escondía la mitad del
    problema.** Y no se destapó revisándolo, sino por un camino indirecto —el
    detector de voz nuevo abría turno en clips de silencio y no había factor
    que lo evitara—, que es como se destapan estas cosas.
11. **La prueba de la asimetría pasaba con la asimetría rota** (24/09). El
    detector de voz depende de que el suelo de ruido suba mucho más despacio de
    lo que baja, y había una prueba para eso. Al poner la subida igual de
    rápida que la bajada, a propósito, **las pruebas seguían todas en verde**:
    lo que protege de las frases largas no es la lentitud de la subida sino que
    los trozos de voz no alimenten la subida en absoluto, y el comentario del
    código explicaba el mecanismo equivocado. No es una medición falsa sino una
    prueba falsa, y cuenta igual: **una prueba que sigue pasando cuando rompes
    lo que dice proteger no está protegiendo nada.**
12. **Tres sondas midieron un sistema que no existe, y una de ellas hizo que
    se cambiara el sistema de verdad** (24/09). Es la peor del día y la más
    instructiva. El umbral que abre turno parecía sordo a la voz floja —"0 de
    6 con la voz a la mitad"—, se sustituyó por un detector adaptativo con su
    tabla, su criterio escrito antes y sus seis pruebas en verde, y **rompió el
    sistema**: el turno dejaba de cerrarse. Al buscar por qué, las tres sondas
    resultaron tener cada una su propia idea de `app/vivo.py`:
    - la que dio la alarma comparaba el **nivel medio del clip entero** contra
      el umbral, cuando el sistema acumula `voz_ms` trozo a trozo y **no lo
      reinicia** en los silencios de en medio;
    - la que eligió el parámetro reiniciaba la racha en cada silencio, y
      además solo medía si el turno **se abre**, nunca si se cierra — con lo
      que un detector que declare voz siempre saca la nota perfecta;
    - y el material de silencio se seleccionaba con "pico < 3× el suelo" para
      luego elegir un factor de 2,5: cualquier factor ≥3 daba cero falsos **por
      construcción**.

    Medido por fin **contra la clase `Llamada` de verdad**, el umbral fijo
    cierra turno 6/6 con la voz a la mitad, 6/6 al 25% y 6/6 por teléfono: el
    problema no existía. Se revirtió todo. **La prueba que lo cazó fue la del
    stack levantado**, con las seis deterministas en verde, y por eso la regla
    de verificar contra el stack no es una preferencia de estilo.

13. **La cuenta de la cuota cuadraba sola y faltaba un tercio** (25/09). Para
    saber si cabía la medición del reservado se sumaron los tokens que reportan
    las corridas: canario ~30 000 más tres corridas de ~30 600 = ~148 000 de
    200 000, luego quedaban ~52 000. La suma era correcta, la aritmética era
    correcta y el número estaba mal por 51 000, porque **el límite no es diario
    sino una ventana deslizante de 24 horas** y la ventana arrastraba el gasto
    del día anterior a esa misma hora. Groq lo llama «tokens per day», que es
    lo que invita a la equivocación. Se destapó porque la cuarta corrida murió
    a mitad con `Used 199423`, y lo que lo confirma es el `try again in 1m9s`
    del propio mensaje: un contador que se reinicia a medianoche no se recupera
    en 69 segundos. **Dos lecciones, y la segunda es la incómoda:** contabilizar
    lo que gastas no sirve si no sabes sobre qué ventana se cuenta; y la
    recomendación de esa mañana —no quemar el reservado— fue la correcta con el
    número equivocado, o sea que acertó por el motivo equivocado. La opción
    descartada (medir el reservado ese día, «con 49 000 de margen») habría
    gastado el conjunto a medias.
14. **El canario que protegía el reservado comprobaba lo que no importaba, y su
    propio docstring lo decía** (25/09). `hay_cuota_para_empezar` existía,
    palabra por palabra, para que no pasara esto: *«si el protocolo arranca,
    hace dos corridas y se queda sin cuota a la tercera... medio reservado
    gastado no es medio reservado»*. Y lo que comprobaba era que **una** petición
    del tamaño real pasara, que no dice nada de si caben **cinco corridas**. Ese
    día la sonda de límites respondió «pasa. Hay cuota para medir» y la corrida
    siguiente murió a mitad: con el reservado en vez de calibración, el canario
    habría dado luz verde. Es la familia de las tres pruebas del 24/09 que
    pasaban sin cubrir lo que decían, con un agravante: **aquí la distancia
    entre lo que el código prometía y lo que hacía estaba escrita en el propio
    módulo, en español, y nadie la leyó al lado del código.** Y al arreglarlo
    salieron dos más de la misma familia: la petición de prueba del canario
    reventaba con un 400 (`Tool choice is none, but model called a tool`) porque
    mandaba el prompt del sistema sin declarar herramientas, y la función
    trataba **cualquier** excepción como falta de cuota —así que habría anunciado
    «no hay cuota» cuando lo que fallaba era ella misma—; y `estabilidad.py`
    mezcló tres corridas del 24/09 con dos del 25/09 y dio una mediana de 8/12
    sin avisar, porque el artefacto de `correr.py` **no guardaba el commit** y no
    había forma de saber que eran dos agentes distintos.

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
- **Y da 200 000 tokens en una VENTANA DESLIZANTE DE 24 HORAS —no al día— y NO
  sale en ninguna cabecera.** Solo aparece en el cuerpo del 429:
  `on tokens per day (TPD): Limit 200000, Used 199423`. Groq lo llama «per
  day» y no lo es: el mismo mensaje añade `Please try again in 1m9.12s`, y si
  el contador se pusiera a cero a medianoche no habría nada que reintentar en
  69 segundos. Lo que se libera en ese minuto y pico es el gasto de ayer a esa
  misma hora saliendo de la ventana; minutos después, una petición que pedía
  60 000 tokens pasaba.
  **La consecuencia práctica, que el 25/09 costó casi el reservado: un día
  nuevo NO amanece con la cuota limpia.** Esa mañana se sumaron los tokens de
  las corridas del día (~148 000), se concluyó que quedaban ~52 000 y no
  quedaba nada: la ventana arrastraba ~51 000 del día anterior a esa hora. Lo
  bueno es que esperar SÍ sirve, y ahora se sabe cuánto:
  `app/evaluation/cuota.py` lleva el libro con marcas de tiempo y dice a qué
  hora cabrá una medición entera. Una tarde de evaluaciones (~20 corridas de 12
  casos) se come la ventana. El 24/09 el mismo límite costó tres diagnósticos
  equivocados seguidos, con la sonda diciendo que quedaban 7920 tokens del
  minuto mientras la ventana estaba al 99,9%.
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

- ~~**Los procedimientos inventados no los caza nadie.**~~ HECHO el 24/09.
  Tres familias —canales y lugares, requisitos impuestos a terceros, plazos—
  más los compromisos de que alguien llamará después, que se miran contra la
  escalada: con el ticket abierto son verdad y sin él no.
  **Medido sobre 147 respuestas reales del agente: marca 10, y ninguna es un
  falso positivo.** Entre ellas, palabra por palabra, el ejemplo que este
  documento tenía escrito como el hueco grande. Lo que no cambia es el
  recuento —sube de 1 a 2 casos en una corrida de doce— porque quien se
  inventa un procedimiento suele inventarse también el teléfono, y ese ya lo
  cazaban los números; lo que se gana es saber **cuál**.
- ~~**La promesa de transferencia**~~ ya estaba hecha (`PASAR_CON_HUMANO`).
  Este documento la daba por pendiente y no lo estaba.
- **Si el detector entra en la ruta de la voz**, revisando la frase antes de
  decirla, y qué hace cuando marca: callar, escalar, o hablar y anotarlo. Esto
  sigue sin decidirse, y ahora hay con qué: cero falsos positivos sobre 147
  respuestas es una base bastante mejor que los tres casos de ayer.

**AVISO para comparar números:** desde el 24/09, "dijo lo que no le consta"
cuenta también los procedimientos. Las cifras anteriores a esa fecha miden
menos cosas y no son comparables. `estabilidad.py` reclasifica con el detector
de hoy, así que releer lo guardado sí compara bien.

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
cubre con un modelo que revienta si alguien lo llama.

El hueco que ese arreglo dejaba abierto —Whisper alucinando sobre el silencio,
que no es una cadena vacía y el guardia no lo ve— **se tapó el 24/09**: el
filtro de voz lo deja en 0 de 64 clips por +24 ms, y con él puesto el silencio
llega como cadena vacía, o sea que cae en el guardia que ya estaba probado.
ADR 0008.

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

**Y el 24/09 esto subió de prioridad por un camino inesperado.** Todo lo que
se midió ese día —la alucinación de Whisper sobre el silencio (16 de 64), el
ruido de sala, el umbral que abre turno— sale de UNA habitación, y el intento
de arreglar el umbral con ese material acabó rompiendo el sistema y
revirtiéndose (ADR 0009). No porque el material fuera poco: porque **con una
sola sala no hay forma de saber si un número describe el sistema o describe la
sala**, y esa duda ya no es teórica.

Lo bueno es que ya no hay que escribir nada para aprovechar una grabación
nueva: `probe/confianza_asr.py`, `probe/sordera_asr.py` y `probe/umbral_voz.py`
miden con lo que haya —este último, corregido primero para que mida el cierre
del turno y no solo la apertura—. Hace falta grabar, y grabar es cosa de Juan
Diego: unos minutos de voz y de ruido de fondo en otro sitio, mejor con el
móvil en manos libres.

### ~~6. Barge-in~~ HECHO POR TELÉFONO el 2026-09-24. Por navegador, no
Llevaba semanas bloqueado por dos razones ciertas —sin cancelación de eco el
micrófono capta la propia voz del agente, y había que oírlo para saber si
funciona—. **El canal telefónico quita las dos**: la línea ya cancela el eco, y
el emulador de Twilio permite mandar voz mientras el agente habla y mirar qué
pasa. Así que se implementó y se comprobó entero, sin micrófono y sin nadie
delante (`app/prueba_interrupcion.py`).

  · Hace falta **400 ms de voz seguida** para cortar. La racha se rompe con un
    solo trozo de silencio, que es lo que distingue una interrupción de tres
    sílabas sueltas.
  · **El audio de la interrupción no se pierde**: los 2 s anteriores se guardan
    y pasan a ser el principio del turno nuevo. Sin eso, quien interrumpe
    diciendo "espere, mi cédula es otra" sería oído desde "cédula es otra".
  · Por la línea se manda **`clear`**, que es lo que hace que el corte se note:
    sin él el agente se calla por dentro y sigue sonando por el teléfono varios
    segundos.

**Los 400 ms están razonados y NO medidos, y hay que decirlo.** El
razonamiento: un "ajá" o una tos rondan los 200 ms y una palabra entera pasa de
400. Medirlo de verdad necesita grabaciones de gente interrumpiendo —con la
duración de cada interjección—, y eso va con el punto 5.

**Y por navegador sigue apagado, a propósito.** `permitir_interrupcion` está en
falso salvo en el canal de Twilio; en la página web, sin cancelación de eco
comprobada, el sistema se interrumpiría a sí mismo cada vez que abriera la
boca. El navegador ofrece `echoCancellation` y ya está pedido en
`getUserMedia`, pero **no se ha comprobado que baste**, y eso sí necesita a
Juan Diego con el micrófono.

### 7. Telefonía real con Twilio Media Streams
**Falsa alarma del 24/09, que conviene conocer antes de repetirla:** pareció
que el audio telefónico solo abría turno en 1 de 6 grabaciones y que este
punto estaba condenado. Medido contra la clase `Llamada` de verdad, abre 6 de
6. La sonda modelaba mal el sistema; ver el ADR 0009 y el punto 12 de la lista
de mediciones falsas.

**El canal está hecho y comprobado (24/09), y sin gastar un céntimo.** El
protocolo de Twilio se puede emular: `app/prueba_telefonia.py` ES un cliente de
Twilio de mentira que manda la misma secuencia —`connected`, `start`, `media`
en base64, `stop`— y comprueba lo que vuelve.

  · **G.711 µ-law de verdad** (`app/telefonia/g711.py`), no la simulación de
    pérdida de `probe/linea_telefonica.py`. Verificado contra `audioop` en los
    **65 536 valores posibles**, y ahí se vio que la primera versión difería en
    381 de ellos: el estándar trabaja sobre 14 bits, no 16. Medio por ciento de
    muestras mal no suena a error, suena a mala línea.
  · **El puente** traduce mensajes a mensajes sin tocar la red, que es lo que
    permite comprobarlo entero. Usa `mark` para saber cuándo el agente terminó
    de hablar, en vez de calcularlo por la duración del audio.
  · **Y lo que de verdad decide**: una grabación real pasada por el canal
    completo —16 kHz → 8 kHz → µ-law → base64 → vuelta → Whisper— y el
    documento `1070234567` sobrevive al viaje.
  · El endpoint TwiML responde contra el servidor levantado
    (`app/prueba_pasarela.py`).

Y el transporte local también: `prueba_pasarela` llama al endpoint `/twilio`
con un WebSocket de verdad y recibe **230 trozos de audio µ-law y su marca de
fin**. Lo único sin comprobar es Twilio en sí.

**Lo que falta, que es solo eso:** una cuenta, un número y un túnel. Los pasos
exactos, con las trampas, están en **`docs/telefonia.md`**; no se repiten aquí
para que no se despeguen. Lo que hay que saber de memoria:

  · **Es gratis:** el trial da 75 minutos de voz y un número durante 30 días, y
    para grabar la demo sobra. Y no hace falta telefonía permanente: el vídeo
    dura para siempre, el trial 30 días.
  · **Twilio reproduce un aviso del trial antes de tu TwiML** y solo se quita
    pagando; en el vídeo se corta en edición.
  · **Exige `wss://` con certificado válido.** De ahí el túnel. **ngrok ya está
    en la máquina**, en `Desktop\ngrok-v3-stable-windows-amd64\ngrok.exe`
    (v3.39.11), y solo le falta el authtoken de una cuenta gratuita: sin él,
    ngrok v3 no arranca.
  · Antes de marcar: `probe\check_telefonia.py`, que comprueba las cinco cosas
    que fallan en silencio, incluida la peor — que el `.env` apunte al túnel de
    la sesión anterior de ngrok, porque la URL cambia en cada arranque.
  · Twilio NO es software libre, por si vuelve a salir la duda: es un servicio
    de pago con crédito de prueba. La alternativa libre de verdad es
    FreeSWITCH o Asterisk con un softphone, y entonces **no hay número de la
    red telefónica**: se marca desde una app SIP, no desde el marcador del
    móvil. Se descartó para esto porque cuesta horas —hay que compilar
    `mod_audio_stream`, que es un módulo C++ de terceros— y porque el CV de
    Juan Diego ya demuestra FreeSWITCH.

### ~~8. El expediente en PostgreSQL~~ HECHO el 2026-09-24. Redis sigue pendiente
El expediente está y **verificado contra Postgres de verdad**, no compilando:
tres tablas (`llamada`, `turno`, `paso`), lo que devolvió cada herramienta
guardado entero y sin resumir, más la confianza del ASR (ADR 0008), la clave
de idempotencia (ADR 0007) y lo que el detector marcó sin fundamento. Una
llamada real de `prueba_pasarela` queda leíble con
`python -m app.expediente.leer <id>`.

La decisión que lo gobierna, escrita en la cabecera del módulo: **una base de
datos caída no puede tumbar una llamada en curso**. Se sigue atendiendo y se
anota la pérdida; `fallos` y `ultimo_error` son parte de la interfaz, porque un
expediente que se pierde en silencio es peor que no tenerlo.

**Y el estado en Redis también, el mismo día.** La frase "la pasarela no
guarda nada suyo y escala horizontal" **ya no es una promesa de diseño**:
`app/prueba_estado.py` atiende el turno 1 en una pasarela y el turno 2 en otra
distinta —objetos nuevos, otro modelo de mentira, nada compartido en memoria— y
comprueba que en la petición de la segunda están los mensajes de la primera.
Verificado también con una llamada real: tras `prueba_pasarela`, el estado
aparece en Redis con `esperando: "documento"` y la historia entera.

Lo que viaja es la conversación (historia, silencios, documentos ya probados,
consumo, qué se estaba esperando). Lo que NO viaja es el audio, y esa
distinción es la que lo hace barato: **una escritura por turno, no una por
trozo de 20 ms**. El prompt del sistema tampoco viaja, a propósito: si viajara,
una pasarela con el prompt nuevo seguiría atendiendo con el viejo durante horas
y las mediciones por prompt del ADR 0005 dejarían de significar nada. Hay
prueba de las dos cosas.

**Lo que queda de este punto:** el `docker compose up -d` es manual, y una
llamada solo se retoma si el navegador vuelve con `?llamada=<id>`. Levantar dos
pasarelas de verdad detrás de un balanceador no se ha hecho: lo que está
demostrado es que el estado no las ata, no que el despliegue exista.

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

### ~~11. El ADR que falta~~ NO FALTA NINGUNO desde el 2026-09-24
Los cuatro cayeron el 24/09: el 0005 (no afirmar lo que no venga de una
herramienta), el 0006 (herramienta que falla a mitad), el 0007 (idempotencia)
y el 0008 (la transcripción que no es de fiar). El 0008 era el único que
además había que decidir y no solo escribir, y se decidió con la sonda
delante: `probe/confianza_asr.py`, 106 clips, cero tokens.

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
.\.venv\Scripts\python.exe probe\limites_groq.py    # ¿cabe una medición AHORA, y si no, a qué hora?
```

La última línea de esa sonda es la que decide si hoy se puede medir. El límite
es una **ventana deslizante de 24 h**, así que un día nuevo NO amanece con la
cuota limpia: puede arrastrar el gasto de ayer a esta hora. Si la sonda dice que
el libro no tiene ni un apunte, eso **no** significa que haya cuota —significa
que no sabe—: siémbralo con `probe\sembrar_libro_cuota.py --rehacer`.

Las comprobaciones que no gastan cuota están arriba, en ESTADO, y pasan todas.
Córrelas si has tocado algo.

Y dime qué recomiendas. Si vas a proponer una optimización, **mira antes de qué
está hecho el tiempo que quieres optimizar**: ya recomendé una vez adelantar una
consulta que tardaba 5 ms para arreglar 1267 ms que eran del modelo.

---

## EL SIGUIENTE PASO, en orden y sin margen de interpretación

Escrito el 2026-09-24 y **actualizado el 2026-09-25**. Sigue siendo la medición
final del reservado, y el orden importa porque el reservado se gasta al mirarlo.

### DÓNDE SE QUEDÓ EL 25/09, que es por dónde se sigue

**EL RESERVADO SIGUE INTACTO.** Lo demás, en orden de lo que hace falta saber:

1. **La cuota es una ventana deslizante de 24 h, no un día.** Ver el punto 13 de
   la lista de mediciones falsas y las trampas del entorno. La mañana del 25/09
   la ventana arrastraba ~51 000 tokens del día anterior, se gastó entera en
   cuatro corridas, y a las 09:20 quedaban 263 tokens de 200 000.
2. **Hay 2 corridas limpias de calibración del agente de hoy** (9/12 y 8/12,
   commit `15f5acc`). El paso 1 pide 3: falta al menos una.
3. **La medición del reservado (k=5) cabrá el 26/09 a partir de las ~09:20**, y
   eso no es una estimación a ojo: sale del libro de la cuota, que sabe a qué
   hora sale de la ventana cada gasto. Pregúntaselo con
   `probe\limites_groq.py`, que ahora lo dice en una línea.
4. **El canario ya protege el reservado de verdad.** Antes comprobaba que UNA
   petición pasara; ahora comprueba que caben las k corridas enteras con un 50%
   de margen, y se niega si el libro está ciego. Lo cubre
   `app.evaluation.prueba_canario`, que sustituye `una_corrida` por algo que
   revienta si alguien la llama.
5. **DECIDIDO el 25/09 por Juan Diego: el reservado se mide con el agente TAL
   CUAL, sin arreglar antes nada.** Hay dos fallos vivos y conocidos —la fuga de
   datos en `nombre-no-coincide` (2 de 3 lecturas) y `fraude-en-curso`, que falla
   las 5 veces igual— y se miden en vez de taparse: el resumen de la medición
   final ya cuenta las fugas, así que el reservado describirá el agente que
   existe, con su fallo dentro.

   Lo que esa decisión obliga a hacer después, y no se puede olvidar: **cualquier
   arreglo de esos dos fallos queda informado por el resultado del reservado**, y
   hay que escribirlo al lado de la cifra cada vez que se cite. Y lo que ya no se
   podrá saber nunca: si el arreglo habría movido el número del reservado. Se
   acepta a cambio de no aplazarlo —arreglar primero obligaría a rehacer las tres
   corridas de calibración, y 92 000 + 89 000 tokens no caben en una ventana—.

### El orden exacto del 26/09

```powershell
# 1. ¿cabe ya? (cero tokens; el reservado necesita ~134.000 con margen)
.\.venv\Scripts\python.exe probe\limites_groq.py

# 2. la corrida de calibración que falta, para tener 3 limpias del agente de hoy
.\.venv\Scripts\python.exe -m app.evaluation.correr --presupuesto-ms 15000
.\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 12 --prompt actual --presupuesto-ms 15000 --commit <el de hoy>

# 3. el reservado, una vez en la vida
.\.venv\Scripts\python.exe -m app.evaluation.medicion_final --declaro-medicion-final
```

Cabe: 1 calibración (~31 000) + reservado k=5 (~89 000) = ~120 000 de 200 000.
Si sale una corrida contaminada y hace falta repetirla, sigue cabiendo.

**Y una cosa por verificar en el paso 2, que no se pudo ver el 25/09:** que
`correr.py` apunte de verdad su consumo en el libro de la cuota. La línea base no
gasta tokens, así que ejercitó el módulo entero menos esa línea. Se ve en la
primera corrida con modelo: al final imprime `ventana de 24 h : N tokens
gastados`.

**Lo que pasó al intentarlo (24/09, por la tarde):** el canario dijo que NO
había cuota —20 fallos del proveedor, identificados como límite diario— y el
protocolo paró en seco en vez de reintentar, que es justo lo que tenía que
hacer. La sonda de límites, mientras tanto, decía que quedaban 7920 tokens del
minuto: la cuarta vez que las cabeceras mienten sobre el día. **El reservado
sigue intacto.** Con el día quemado salieron los ADR 0008 y 0009, que no
gastan cuota. El 0008 (el filtro de voz) está en el sistema; el 0009 se probó,
rompió el cierre del turno y **se revirtió el mismo día**, así que lo único
que cambió en la ruta del turno el 24/09 por la tarde es el filtro.

**Y eso añade una razón a lo del paso 1:** el agente cambió el 24/09 —por la
mañana el turno vacío y los tres intentos de documento, por la tarde el filtro
de voz—. Las 3 corridas de calibración no son una formalidad, son la única
manera de que el número del reservado se pueda comparar con algo.

**Lo que esos cambios NO tocan, y conviene saberlo antes de preocuparse:** la
evaluación corre sobre turnos de **texto**, no de audio (`caso.turnos` son
frases). Ni el filtro ni el detector de voz entran en esa ruta. Lo que **sí**
cambió para la evaluación el 24/09, y hay que tenerlo delante al comparar:

  · por la mañana, el **turno vacío** y los **tres intentos de documento**;
  · por la tarde, el **detector de procedimientos inventados**, que hace que
    "dijo lo que no le consta" cuente más cosas. **Las cifras anteriores al
    24/09 no son comparables con las de después.**

`estabilidad.py` reclasifica con el detector del día, así que releer lo
guardado sí compara bien. Pero la tabla de LOS NÚMEROS lleva cifras de antes:
por eso las 3 corridas del paso 1 no son una formalidad.

### Lo que se hizo el 24/09 después de quedarse sin cuota

Cinco puntos del plan cayeron en una tarde, todos sin gastar una petición:

| | |
|---|---|
| **ADR 0008** | el filtro de voz. 16 de 64 clips de silencio se transcribían como frases; con él, 0. **Está en el sistema** |
| **ADR 0009** | el detector de voz adaptativo. **Revertido el mismo día**: rompía el cierre del turno y el problema que resolvía no existía |
| **procedimientos** | el detector caza "acuda a una sucursal", "necesitamos que esté presente", los plazos y las promesas de que alguien llamará. 10 de 147 respuestas reales, 0 falsos positivos |
| **punto 8** | expediente en PostgreSQL y estado en Redis, los dos verificados contra las bases de verdad |
| **punto 7** | el canal de Twilio: G.711 propio verificado contra `audioop` en los 65 536 valores, protocolo emulado, endpoint probado con socket real |
| **punto 6** | barge-in **por teléfono**: 400 ms de voz cortan al agente, el audio no se pierde, se manda `clear` |

Y el precio de Groq quedó confirmado (0,075 y 0,30 $/millón), así que la
métrica 5 sale sola con la corrida del reservado.

### Lo que se hizo el 25/09 después de quedarse sin cuota

Se gastó la ventana en cuatro corridas de calibración y el resto de la sesión no
costó una petición. Todo salió de **arreglar el instrumento que casi dejó quemar
el reservado**, y ninguno de estos arreglos toca el agente, así que las 2
corridas limpias del día siguen siendo comparables:

| | |
|---|---|
| **el libro de la cuota** | `app/evaluation/cuota.py`: la ventana de 24 h con marcas de tiempo, cuánto queda y **a qué hora cabrá** una medición. 10/10 pruebas, 6 mutaciones cazadas |
| **el canario, de verdad** | comprueba que caben las k corridas con 50% de margen, distingue «no hay cuota» de «mi petición falló», y se niega si el libro está ciego. 6/6, y la prueba sustituye `una_corrida` por algo que revienta si la llaman |
| **métrica 5** | `medicion_final.py` ya cuenta tokens: su artefacto salía con `consumo: null` mientras este documento prometía el coste «de regalo» |
| **la procedencia que faltaba** | el artefacto de `correr.py` guarda commit y modelo, y `estabilidad.py` se niega a mezclar versiones del agente. Antes las mezclaba en silencio |
| **la sonda que dio confianza falsa** | `probe/limites_groq.py` ya no dice «hay cuota para medir» porque una petición pase, y dice a qué hora cabe una medición entera |

Y el coste por conversación quedó **medido** sobre calibración: 0,000226 $,
2 554 tokens, n=12 conversaciones, tres corridas que dan el mismo número.

### 0. Antes de nada: ¿hay cuota?

El límite que manda son **200 000 tokens en una ventana deslizante de 24 h** y NO
sale en las cabeceras. Desde el 25/09 se pregunta así, y cuesta **cero tokens**
porque lo contesta el libro:

```powershell
.\.venv\Scripts\python.exe probe\limites_groq.py
#   la última línea dice si la medición del reservado (k=5) cabe AHORA
#   o a qué hora cabrá. Si el libro sale ciego —«NI UN APUNTE»— siémbralo:
.\.venv\Scripts\python.exe probe\sembrar_libro_cuota.py --rehacer
```

**El canario del 24/09 —`medicion_final --ensayo --corridas 1`— ya no es el paso
0.** Cuesta ~30 000 tokens, o sea el 15% de la ventana, y el 25/09 se gastaron
en él para averiguar algo que el libro contesta gratis. Sigue valiendo para una
cosa distinta y que ya se hizo: ver el protocolo entero por el camino bueno
—tabla por caso, mediana, rango, mayoría, estables y artefacto—, que hasta el
25/09 nunca se había visto funcionar. Correrlo otra vez no añade nada.

**Si no cabe, no se empieza**: hay trabajo de sobra que no gasta cuota (más
abajo). Y el programa ya no depende de que nadie se acuerde: `medicion_final`
se niega solo, antes de tocar el reservado.

### 1. Tres corridas de calibración PRIMERO — van 2, falta 1

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.correr --presupuesto-ms 15000   # la que falta
.\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 12 --prompt actual --presupuesto-ms 15000 --commit <el de hoy>
```

**Sin esto el reservado no significa nada.** Los números de la tabla de tarea
completada se midieron con un agente que ya no existe: sin el turno vacío y sin
los tres intentos de documento. Hacen falta 3 corridas del agente de HOY para
tener con qué comparar, y se hacen antes porque después del reservado ya no se
puede cambiar nada sin contaminar.

**Del 25/09 hay 2 limpias** (9/12 y 8/12) y 2 descartadas por fallos del
proveedor. Ojo con el detalle que costó una hora: `--presupuesto-ms 15000` hay
que pasarlo, porque por defecto son 3000 y sería otro experimento.

Y **pasa `--commit`** a `estabilidad.py`. Sin filtro, el 25/09 mezcló tres
corridas del 24/09 con dos del 25/09 y dio una mediana de 8/12 sin avisar de
nada: las corridas de antes del 25/09 no guardaban con qué agente se midieron y
salen como «sin anotar».

### 2. El reservado, k=5, una vez en la vida

```powershell
.\.venv\Scripts\python.exe -m app.evaluation.medicion_final --declaro-medicion-final
```

El protocolo ya está escrito en el propio módulo y no se cambia ahora: k=5,
mediana, rango, conteo por caso, mayoría (≥3 de 5) y tabla de estables. Una
corrida con fallos del proveedor se repite, **no se promedia**. Si no salen 5
limpias, el programa se niega a dar un número, y eso se respeta.

Sale además el **coste por conversación** (métrica 5), que desde el 25/09 este
módulo sí calcula: hasta entonces llamaba al turno del agente sin pedirle el
consumo y su artefacto salía con `consumo: null`, así que la promesa de que
saldría «de regalo» era falsa y se habría descubierto con el reservado ya
quemado.

Antes de arrancar comprueba solo que caben las 5 corridas (~89 250 tokens
estimados, ~133 875 con el margen del 50%). Si no caben, se niega y dice a qué
hora cabrán. El margen existe porque **el libro es una cota optimista**: solo ve
lo que pasa por el código instrumentado.

### 3. Y entonces, con el número en la mano

- Actualizar la tabla de LOS NÚMEROS con el reservado, la fecha, el modelo y el
  commit. **Y decir que el reservado está quemado**: a partir de ahí todo lo
  que se toque está informado por ese resultado, y hay que escribirlo cada vez
  que se cite la cifra.
- ~~Rellenar `probe/precios.py`~~ HECHO el 24/09: 0,075 $/M de entrada y
  0,30 $/M de salida, de la ficha del modelo en la documentación de Groq, con
  su fuente y su fecha. **El corredor ya imprime el coste en dólares solo**, y
  la corrida del reservado lo dará de regalo: es la métrica 5 cerrada sin
  gastar una petición de más.

### Si no hay cuota, esto avanza sin gastar nada

Las tres cosas que estaban en esta lista se hicieron el 24/09 (barge-in por
teléfono, expediente y estado, el ADR 0008). Lo que queda sin cuota, por orden
de valor:

1. **Grabar voz en otra habitación** (punto 5). Es el techo de todo lo medido:
   una sola sala, un micrófono, un hablante. El 24/09 eso ya costó una
   reversión entera (ADR 0009). No hace falta cuota ni tocar código:
   `probe/confianza_asr.py`, `probe/sordera_asr.py` y `probe/umbral_voz.py`
   miden con lo que haya. **Requiere a Juan Diego con un micrófono**, unos
   minutos de voz y de ruido de fondo en otro sitio.
2. **La llamada real por Twilio** (punto 7). El canal está comprobado entero;
   falta cuenta, número y túnel. Los pasos y las trampas, en
   `docs/telefonia.md`; antes de marcar, `probe\check_telefonia.py`.
   **Requiere a Juan Diego** creando dos cuentas gratuitas.
3. **Barge-in por navegador** (lo que queda del punto 6). Por teléfono está
   hecho; en la web sigue apagado porque no se ha comprobado que el
   `echoCancellation` del navegador baste. **Requiere a Juan Diego con el
   micrófono.**
4. **Métrica 3, corrección de las llamadas a herramientas.** Es la única de las
   seis que no se ha empezado, y no está claro que aporte mucho: el detector de
   fundamento ya mira si lo dicho tiene respaldo, que es la mitad interesante.

Ojo con el patrón: **casi todo lo que queda necesita a Juan Diego**, no código.
Lo que un agente puede avanzar solo se está acabando, y eso es una señal de que
el proyecto está más cerca del final de lo que parece.
