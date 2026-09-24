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
| confianza del ASR | `app/confianza.py` | resume lo que el modelo sabe de su propia transcripción. Se anota, no decide. ADR 0008 |
| detector adaptativo | `app/deteccion_voz.py` | **NO está en uso.** Se puso y se revirtió el 24/09: ver ADR 0009. Se conserva con sus pruebas por el hallazgo |
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
.\.venv\Scripts\python.exe -m app.prueba_confianza          # el filtro de voz sigue puesto, sin cuota ni GPU
.\.venv\Scripts\python.exe -m app.prueba_deteccion_voz     # el detector de voz y su limite conocido, sin cuota ni GPU
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

### Coste por conversación (métrica 5): instrumentado, sin medir

Los tokens ya se cuentan por paso, por turno y por conversación (24/09). **El
número todavía no existe** porque hace falta una corrida con cuota, y llega
gratis con la medición del reservado.

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
prompt ataca exactamente esa parte. Queda anotado para cuando haya un número
con el que comparar.

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

## DOCE VECES QUE UNA MEDICIÓN SALIÓ LIMPIA Y ERA FALSA

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

### 6. Barge-in, que exige cancelación de eco
Hoy, mientras el agente habla, **se ignora la entrada**, y está declarado como
decisión: sin cancelación de eco el micrófono capta la propia voz del agente y
el sistema se contesta a sí mismo. El navegador ofrece `echoCancellation` y ya
está pedido en `getUserMedia`, pero no se ha comprobado que baste. Es la
métrica 6 y es lo que más se nota en una demo: poder interrumpir al agente.

### 7. Telefonía real con Twilio Media Streams
**Falsa alarma del 24/09, que conviene conocer antes de repetirla:** pareció
que el audio telefónico solo abría turno en 1 de 6 grabaciones y que este
punto estaba condenado. Medido contra la clase `Llamada` de verdad, abre 6 de
6. La sonda modelaba mal el sistema; ver el ADR 0009 y el punto 12 de la lista
de mediciones falsas.

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
frases). Ni el filtro ni el detector entran en esa ruta, así que no
contaminan la comparación entre corridas; lo que sí cambió para la evaluación
fue el agente del 24/09 por la mañana (turno vacío y tres intentos de
documento).

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
- ~~Rellenar `probe/precios.py`~~ HECHO el 24/09: 0,075 $/M de entrada y
  0,30 $/M de salida, de la ficha del modelo en la documentación de Groq, con
  su fuente y su fecha. **El corredor ya imprime el coste en dólares solo**, y
  la corrida del reservado lo dará de regalo: es la métrica 5 cerrada sin
  gastar una petición de más.

### Si no hay cuota, esto avanza sin gastar nada

En este orden de valor:

1. **Barge-in** (punto 6): es lo que más se nota en una demo y lo único que
   falta de las seis métricas junto al coste. Hace falta probarlo a mano con el
   micrófono, así que requiere a Juan Diego delante.
2. **El expediente en PostgreSQL y el estado en Redis** (punto 8): el proyecto
   promete que al colgar queda un expediente y hoy se pierde al cerrar el
   proceso. Es la mayor distancia entre lo que promete y lo que hace.
3. ~~**El ADR que falta**~~ HECHO el 24/09 con el día de cuota ya quemado: es
   el ADR 0008, y salió con su medición de 106 clips sin gastar un token.

Y una que no estaba en la lista y ahora sí, porque el 0008 la dejó preparada:
**grabar voz en otra habitación** (punto 5). No hace falta cuota, solo un
micrófono y un rato de ruido de fondo; `probe/confianza_asr.py` mide con lo que
haya sin tocar código, y hoy todo el proyecto descansa sobre el suelo de ruido
de una sola sala callada.
