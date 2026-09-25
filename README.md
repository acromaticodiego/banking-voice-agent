# banking-voice-agent

Agente de voz telefónico para verificación de identidad y atención al cliente:
mantiene una conversación, decide qué preguntar, llama herramientas, se recupera
cuando algo falla, y trabaja contra un reloj. Al colgar queda un expediente en
PostgreSQL con qué se dijo, qué herramienta se llamó, con qué argumentos, qué
devolvió y qué se revisó de lo que el agente contestó.

**Estado (2026-09-24): el sistema funciona de punta a punta y está medido.**
Se habla por el micrófono del navegador, el agente decide, llama herramientas,
se recupera cuando fallan y contesta hablando. Lo que falta está al final, sin
adornos: no hay telefonía real, no hay barge-in, y la evaluación sobre el
conjunto reservado no se ha hecho
—el reservado sigue **sin tocar**, que es lo que le da valor—.

> **Lo que de verdad merece la pena de este repositorio no son los números
> buenos: es la lista de doce veces que una medición salió limpia y era
> falsa.** Está más abajo, con nombre y apellido de cada error, incluidas las
> que obligaron a revertir código escrito el mismo día.

---

## Qué hay construido

| pieza | fichero | qué hace |
|---|---|---|
| llamada en vivo | `app/vivo.py` | consume audio según llega, decide cuándo terminó el turno, orquesta |
| bucle del agente | `app/agent/loop.py` | decide, llama herramientas, se recupera, frase puente, presupuesto por turno, idempotencia |
| herramientas | `app/tools/service.py` | FastAPI, una por capacidad, con cabeceras para provocar fallos y latencia |
| pasarela y pantalla | `app/gateway.py`, `app/web/` | WebSocket, micrófono con AudioWorklet, conversación y llamadas a herramientas en vivo |
| fin de turno | `app/fin_de_turno.py` | decide si la frase está a medias **por contenido**, no solo por silencio |
| fundamento | `app/agent/fundamento.py` | compara lo que dice el agente con lo que devolvieron las herramientas. Determinista, sin modelo |
| evaluación | `app/evaluation/` | 20 casos con rúbrica, partición con reservado bajo llave, línea base sin modelo, estabilidad entre corridas |

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
# y abrir http://127.0.0.1:8000/   (por localhost: el micrófono no va por IP)
```

---

## El número, y cómo cambió tres veces

El objetivo es **800 ms por turno**, que es donde una conversación empieza a
sentirse rota.

| | |
|---|---|
| primera medición, por etapas sueltas | 2296 ms |
| lo mismo, tras corregir tres errores de método | 916 ms |
| el turno completo, con un solo cronómetro | 2389 ms |
| **con frase puente: cuando deja de oírse silencio** | **1424 ms** |
| **con frase puente: cuando llega el dato** | **2061 ms** |
| objetivo | 800 ms |

Las dos primeras filas son la **suma de cuatro etapas medidas por separado**, y
entre una y otra no se escribió ni una línea del sistema: los 1380 ms de
diferencia no fueron optimización, fueron tres errores de medición.

La tercera fila es el turno de verdad, y es la que cuenta.

Vuelto a medir el 2026-09-24 con el filtro de voz dentro y el fin de turno por
contenido: **2234 ms** al primer audio y **3112 ms** al primer dato (n=6). La
diferencia con el 23/09 **no se le puede atribuir al filtro** —son días
distintos y el componente que manda es el modelo remoto, 1459 de esos 2234 ms—;
lo que sí se puede afirmar es que no lo ha empeorado de forma medible.

### Por qué la suma de las partes mentía: 2389 ms

La suma de las partes daba 916 ms: cuatro etapas medidas **cada una por separado y en su
mejor caso**. Cuando el turno corre entero —audio en tiempo real, detección de
fin de habla, transcripción, agente con su herramienta, síntesis— y se
cronometra con un solo reloj desde que la persona se calla hasta que hay audio
que reproducir, sale **2389 ms**. Dos veces y media más.

| etapa | presupuesto por partes | turno completo | |
|---|---|---|---|
| fin de habla | 300 ms | 300 ms | |
| voz a texto | 162 ms | 542 ms | 3,3× |
| agente | 325 ms | 1267 ms | 3,9× |
| texto a voz | 128 ms | 274 ms | 2,1× |
| **total** | **916 ms** | **2389 ms** | **2,6×** |

Por qué cada una:

- **El agente no hace una llamada al modelo, hace dos.** Los 325 ms eran el
  tiempo hasta el primer contenido hablable de **una** petición. Un turno real
  decide llamar a una herramienta, espera a la herramienta, y vuelve a
  preguntarle al modelo con el resultado. Ninguna sonda veía esa cadena.
- **El voz a texto transcribe la intervención entera**, 8,4 s, no la cola de
  2 s que medía la sonda. Con un ASR en streaming de verdad volvería a
  parecerse a los 162 ms, pero eso es una estimación y no está medido.
- **La síntesis depende de la frase.** 128 ms era una frase corta preparada;
  lo que contesta el agente es más largo.

El presupuesto por partes sigue siendo útil para saber dónde tocar. Pero **el
número del proyecto es el de punta a punta**.

### Y hay dos números de punta a punta, no uno

De esos 1296 ms del agente, casi todos son silencio: el modelo decide llamar a
una herramienta, se espera la consulta, y se le vuelve a preguntar con el
resultado. Así que el agente **dice una frase puente** en cuanto sabe que va a
haber espera — *"Permítame un momento, lo estoy revisando"* — que es verdad,
porque está consultando.

| | sin puente | con puente |
|---|---|---|
| **primer audio**, cuando deja de oírse silencio | 2389 ms | **1424 ms** |
| **primer dato**, cuando se entera de algo | 2389 ms | 2061 ms |

**Los dos se publican siempre juntos, y esa es la parte importante.** La frase
puente mejora el primero en casi un segundo y no toca el segundo: la espera
sigue ahí, solo que tapada. Dar únicamente el 1424 convertiría un relleno en
una mejora de rendimiento. La sonda imprime los dos y guarda los dos, para que
no se pueda contar a medias sin editarlo a mano. Razonado en
[`docs/adr/0003`](docs/adr/0003-que-dice-el-agente-mientras-la-herramienta-corre.md).

---

## Presupuesto del turno

Cada etapa medida POR SEPARADO y en su mejor caso, el 2026-09-19, en un portátil
con RTX 3050 de 6 GB. La suma de esta tabla no es lo que tarda un turno: para eso
está la sección de arriba. Qué instante a qué
instante se cronometra en cada etapa: [`docs/adr/0001`](docs/adr/0001-que-se-mide-en-el-presupuesto-del-turno.md).

| etapa | p50 | p95 | n | cómo |
|---|---|---|---|---|
| fin de habla | 300 ms | 300 ms | — | **supuesto**, ver más abajo |
| voz → texto (cola de 2 s) | 162 ms | 178 ms | 10 | `faster-whisper small`, cuda/float16 |
| modelo (primer contenido hablable) | 325 ms | 548 ms | 12 | `openai/gpt-oss-20b` en Groq, esfuerzo `low` |
| texto → voz (primer trozo) | 128 ms | 136 ms | 10 | `piper es_MX-claude-high` |
| **total** | **916 ms** | 1161 ms | | |

**Lo que este número no incluye**, y hay que decirlo cada vez que se cite: el
viaje del audio por la red en los dos sentidos, el tiempo de reproducción en el
auricular, y el fin de habla, que es una suposición y no una medición. Es un
límite inferior medido en condiciones buenas.

## Tasa de error de transcripción

`faster-whisper small` en GPU, sobre tres grabaciones de una sola persona con
acento paisa, sin ruido de fondo.

| | micrófono, 16 kHz | por línea telefónica |
|---|---|---|
| literal, p50 | 16,7% | 20,0% |
| con los números normalizados, p50 | **0,0%** | **0,0%** |
| números críticos recuperados exactos | **3 / 3** | **3 / 3** |

La diferencia entre las dos primeras filas es el asunto entero. La referencia
dice *"uno cero siete cero dos tres cuatro cinco seis siete"* y el sistema
devuelve `1070234567`: palabra por palabra son diez errores **por acertar el
dato completo**. Sin normalizar, la métrica mide ortografía en vez de
comprensión y castiga al sistema por hacerlo bien.

Por eso se añade la tercera fila. Un sistema puede tener un 15% de error de
palabra y acertar el 100% de los documentos, o al revés; en una verificación de
identidad lo segundo es lo único que decide.

La segunda columna es el mismo audio pasado por el canal de una llamada: banda
de 300–3400 Hz, muestreo a 8 kHz y cuantización µ-law de 8 bits (G.711), y de
vuelta a 16 kHz para el modelo. **El canal telefónico no rompe a
`faster-whisper small` en este material**, y eso contradice lo que este mismo
documento predijo: se dio por hecho que el filtro cambiaría la tasa bastante, y
no la cambia. Los 3,3 puntos del literal, con n=3, no se distinguen del ruido.

Con n=3 y un solo hablante esto calibra el orden de magnitud. No es una tasa
representativa: para eso hacen falta **varias voces y ruido de fondo**, que es
lo único que queda de este punto ahora que el canal está simulado.

### Turnos que nadie dijo

Hay un error que no aparece en ninguna tasa: el que comete el sistema cuando
**no se dijo nada**. Whisper se inventa frases sobre el ruido de fondo, y lo
que se inventa tiene letras, así que el guardia del turno vacío —que mira si
la transcripción tiene alguna letra o dígito— lo deja pasar como si alguien
hubiera hablado.

Medido sobre 106 clips (42 con voz, 64 sin ella), con el silencio sacado de las
propias grabaciones y no sintetizado:

| | sin filtro de voz | con `vad_filter=True` |
|---|---|---|
| clips sin voz que producen texto | **16 de 64** | **0 de 64** |
| clips con voz que se quedan mudos | 0 de 42 | 0 de 42 |
| coste en el turno (3 s + 1,2 s), mediana n=18 | 178 ms | 202 ms |

Ya inventa con un solo segundo de silencio, y cuanto más largo, más: 1 de 13 a
1 s, 4 de 15 a 2 s, 5 de 15 a 4 s, 6 de 17 a 8 s.

Lo que sale: *"¡Suscríbete!"*, *"Este es el canal de subtítulos en español de
la Iglesia…"* y *"¿Qué pasa?"*. Las dos primeras delatan de dónde vienen. **La
tercera no delata nada**: es una frase que un cliente diría, y un agente
bancario le contesta a una habitación vacía.

Dos cosas más, que son las que hacen falta para decidir. **Qué clip alucina se
repite entre corridas; qué dice, no** — es el fallback de temperatura de
Whisper, que es aleatorio por dentro. Y **el umbral de confianza, que parecía
la solución elegante, no lo es**: `no_speech_prob` no separa (los rangos del
habla y del invento se solapan casi enteros) y un corte por `avg_logprob`
cazaba 7 de 7... hasta que entraron seis clips de habla más y bajó a 5 de 7, y
al arreglar el material de silencio quedó en 6 de 16. Tres medidas, cada una
peor que la anterior, y ninguna por un error de medición: el umbral nunca había
sido bueno, solo había visto poco.

**El primer número de esta tabla fue 7 de 64 y estaba mal**, por cómo se
construía el silencio: se cogían los tramos de menos energía de cada
grabación, y los de menos energía son los ceros que el grabador deja al
principio y al final. El banco se llenaba de tramos medio mudos y el problema
salía por la mitad de su tamaño. El razonamiento completo, con lo que se
descartó, está en
[ADR 0008](docs/adr/0008-que-hace-el-agente-cuando-la-transcripcion-no-es-de-fiar.md).

### El umbral que parecía describir una habitación

Mientras se comprobaba que el filtro de voz no dejara sordo al agente apareció
algo que parecía peor. El sistema abre turno cuando se acumulan 600 ms de audio
por encima de una constante, `0.005`, y una sonda dijo esto:

| | ¿abre turno? |
|---|---|
| grabación original | 6 de 6 |
| la misma voz a la mitad de volumen | **0 de 6** |
| la misma voz por línea telefónica | **1 de 6** |

Conclusión aparente: quien hable bajito no es oído, quien llame por teléfono
tampoco, y el siguiente paso del proyecto —telefonía real— está apoyado en algo
que no puede funcionar. Se escribió un detector que calibra el umbral contra el
ruido de la propia llamada, con su barrido de parámetros, su criterio fijado de
antemano y seis pruebas deterministas. Todas en verde.

**Y rompió el sistema.** La prueba del stack levantado se puso roja: el turno
dejaba de cerrarse. El detector nuevo declaraba voz en el 96-97% de los trozos
de una grabación real —el fijo, en el 38-47%—, el silencio seguido más largo
caía de 2520 ms a 380, y con una ventana de cierre de 1200 ms el turno no
terminaba nunca.

Al buscar por qué las sondas no lo habían visto, las tres resultaron tener cada
una su propia idea del sistema:

- la que dio la alarma comparaba el **nivel medio del clip entero** contra el
  umbral, cuando el sistema acumula el tiempo de voz trozo a trozo **y no lo
  reinicia** en los silencios de en medio;
- la que eligió el parámetro reiniciaba la racha en cada silencio, y solo medía
  si el turno **se abre**, nunca si se cierra — con lo que un detector que
  declare voz siempre saca la nota perfecta;
- y el material de silencio se seleccionaba exigiendo "pico < 3× el suelo" para
  después elegir un factor de 2,5: cualquier factor ≥3 daba cero falsos **por
  construcción**.

Medido por fin contra la clase real, el umbral fijo cierra turno 6/6 con la voz
a la mitad, 6/6 al 25% y 6/6 por teléfono. **El problema no existía.** Se
revirtió todo.

Lo que queda escrito en
[ADR 0009](docs/adr/0009-cuando-se-decide-que-alguien-esta-hablando.md), que es
una decisión rechazada y uno de los documentos más útiles del repositorio: una
sonda que reimplementa la lógica del sistema mide la reimplementación, un
detector de voz se mide por sus dos puertas, y la prueba que cazó esto fue la
del sistema levantado mientras las seis deterministas seguían en verde.

## Tarea completada: el agente contra un árbol de reglas

20 casos escritos a mano, cada uno con su desenlace esperado **y el motivo por
el que es ese y no otro**, partidos en 12 de calibración y 8 reservados. Los 8
reservados **no se han mirado nunca**: pedirlos sin declarar que es la medición
final lanza una excepción. El protocolo para gastarlos —k=5 corridas, mediana,
rango, conteo por caso y mayoría— se escribió **antes** de tocarlos, que era la
única ventana para escribirlo sin trampa.

Sobre los 12 de calibración, tres corridas del mismo día y el mismo modelo:

| desenlace correcto | agente | línea base sin modelo |
|---|---|---|
| con reloj holgado (15 s) | mediana **8/12**, rango 6–9 | 7/12, determinista |
| con el reloj de la demo (3 s) | mediana **4/12**, rango 3–5 | — |
| fugas de datos de la cuenta | **0** | **2** |

Y la lectura honesta, que es la parte que importa:

- **La ventaja del agente en desenlaces no se distingue del ruido.** Con el
  reloj holgado saca 8 contra el 7 de un árbol de reglas, y su rango (6–9) tapa
  ese 7 entero. Con el reloj de la demo **pierde**.
- **La mitad del conjunto es moneda al aire**: 6 de los 12 casos cambian de
  desenlace entre corridas del mismo día con el mismo modelo. Por eso cada
  número va con mediana y rango, y por eso existe `estabilidad.py`.
- **Donde gana de verdad no se cuenta en desenlaces**: la línea base filtra
  datos de la cuenta en dos casos y el agente en ninguno, en ninguna corrida de
  ningún brazo. Un árbol de reglas que consulta y recita no sabe callarse.
- **El reloj y las decisiones están enredados**: la evaluación corre con reloj
  holgado porque mide decisiones, así que **ese número no describe la demo**.
  Las dos cifras se publican siempre juntas.

## Coste por conversación

Los tokens se cuentan por paso, por turno y por conversación, y el contador
está comprobado con un modelo de mentira que declara su consumo. El precio está
confirmado: **0,075 $ por millón de tokens de entrada y 0,30 $ de salida**
([ficha del modelo](https://console.groq.com/docs/model/openai/gpt-oss-20b),
24/09). **El número todavía no existe** porque hace falta una corrida con
cuota, y llega de regalo con la medición del reservado.

Lo que sí está comprobado, y es lo que cambia la lectura: **el coste de una
conversación crece más que linealmente**, porque cada turno reenvía la historia
anterior. Medir un turno y multiplicarlo por el número de turnos da un número
bajo que no es el que se factura.

---

## El hallazgo: el fin de habla no cabe en el presupuesto

Para decidir que alguien terminó de hablar hay que esperar un rato de silencio.
¿Cuánto? Se barrió de 100 a 1000 ms contando cuántas veces se parte en dos una
intervención que era una sola, sobre grabaciones de habla espontánea.

Lo decisivo no es el tamaño de las pausas sino **dónde caen**:

```
"...no funciona desde el día de ayer."   [1,50 s]  "Nadie me avisó nada..."
"...mi cédula es 1070234567"             [0,93 s]  "mi nombre completo es Juan Diego..."
"...me apareció la compra de la nada"    [0,54 s]  "pero yo no la hice"
```

La segunda es la que manda: está **a mitad de una respuesta**. Cortar ahí es
cortar a alguien mientras se identifica, y encima se pierde el dato.

Para no cortar a nadie dentro de su turno hace falta una ventana de **1600 ms**:
el 188% del presupuesto entero, antes de transcribir, pensar o sintetizar nada.

**El objetivo de 800 ms es inalcanzable con detección por silencio sola.** No es
cuestión de afinar el umbral — el que cabe corta y el que no corta no cabe. La
salida es decidir el fin de turno también por el contenido: *"mi cédula es
1070234567"* está claramente a medias cuando se pidió documento **y** nombre.
Eso lo sabe el texto, no el silencio. Razonado en
[`docs/adr/0002`](docs/adr/0002-como-se-decide-que-alguien-termino-de-hablar.md),
con lo que se descartó.

---

## Doce veces que una medición salió limpia y era falsa

Es la parte más útil de este repositorio. **Coherente no es correcto**: un
resultado que cuadra consigo mismo puede estar mal, y cuadraba. Dos de estas
doce obligaron a revertir código escrito el mismo día.

**1. El barrido del fin de habla aprobaba 100 ms.** Contaba los cortes como
`segmentos - 1`, y las grabaciones demasiado bajas daban un solo segmento. Cero
habla se leía como cero cortes. Otras dos grabaciones hablaban hasta el último
milisegundo del fichero: sin silencio final no hay ningún fin de turno que
detectar, y el detector "acertaba" porque no tenía nada que acertar.

**2. El prompt corto parecía ocho veces más rápido que el largo**, 322 contra
2698 ms. Falso: se midió el último, con el plan gratuito ya encolando
peticiones. El techo son 8000 tokens por minuto, leído de las cabeceras del
servidor. Con las configuraciones intercaladas y el ritmo controlado, la
diferencia real es de 10 ms, y el número del modelo pasó de 406/3076 a 325/548.

**3. Una muestra de 80,6 segundos parecía latencia del modelo.** Era el SDK
reintentando un 429 por dentro, durmiendo lo que le decía el servidor mientras
el cronómetro seguía corriendo. Un rechazo por límite es una espera
administrativa, no latencia: ahora se cuenta aparte.

**4. El error normalizado salía PEOR que el literal**, 45,5% contra 32,3%. El
normalizador de números solo entendía palabras, y el ASR devuelve
`1 0 7 0 2 3 4 5 6 7` en cifras sueltas y `347 mil 200` en forma mixta.

**5. El adelanto de consultas "mejoraba" con n=3 y "empeoraba" con n=6.** Las
dos eran ruido. Y el conteo determinista destapó que el patrón del documento
llevaba caracteres de retroceso (`\x08`): compilaba y no encajaba nunca.

**6. El 5/6 de tarea completada era una sola tirada.** Tres corridas del
conjunto ampliado, el mismo día y el mismo modelo, dieron 6, 5 y 7 de 12. Un
número de una corrida no distingue al agente que resuelve siempre del que
acertó esa vez.

**7. El prompt nuevo parecía haber acabado con los inventos: cero afirmaciones
sin fundamento.** Y era verdad que había cero — porque el presupuesto de 3 s
saltaba en 9 de 12 casos y el agente no llegaba a decir nada. **Un agente al
que se corta antes de hablar no miente, y eso no es una virtud.** La medición
más limpia de todas fue la del sistema al que no se le dejó funcionar.

**8. El filtro de voz costaba +123 ms, y luego +158, y las dos veces era
falso.** Se midió sobre grabaciones de 17 a 30 segundos; un turno son tres
segundos de habla y su cola de silencio. Sobre eso cuesta **+24 ms**. La sonda
no tenía ningún fallo: **medía el material equivocado**.

**9. Un umbral que separaba 7 de 7 y se cayó solo al enseñarle más material.**
Entraron seis clips de habla legítima, el peor se puso justo en el corte, y
pasó a cazar 5 de 7; con el material de silencio corregido, 6 de 16. Tres
medidas, cada una peor, ninguna por un error de medición: **el umbral nunca
había sido bueno, solo había visto poco.**

**10. El material de silencio no era silencio.** Para medir cuánto se inventa
Whisper sobre el silencio se cogían los tramos de menos energía de cada
grabación — y los de menos energía son **los ceros que el grabador deja al
principio y al final**. El banco se llenó de tramos medio mudos y el problema
salía por la mitad de su tamaño: 7 de 64 en vez de 16 de 64. El material no
exageraba el problema, **lo escondía**.

**11. Una prueba seguía pasando con lo que decía proteger roto.** El detector
dependía de una asimetría; se rompió a propósito y las pruebas siguieron todas
en verde. El mecanismo real era otro y el comentario del código explicaba el
equivocado.

**12. Tres sondas midieron un sistema que no existe, y una hizo que se cambiara
el sistema de verdad.** Es la peor y la más instructiva. Una sonda dijo que el
umbral de voz era sordo a la voz floja; se escribió un detector nuevo, con su
criterio fijado de antemano y seis pruebas en verde, **y rompió el sistema**:
el turno dejaba de cerrarse. Las tres sondas tenían cada una su propia idea de
`app/vivo.py` —una comparaba el nivel medio del clip entero, otra reiniciaba la
racha de voz, y ninguna medía si el turno **se cierra**, solo si se abre—.
Medido por fin contra la clase real, el umbral de siempre funcionaba: **el
problema no existía.** Se revirtió todo, y lo cazó la prueba del sistema
levantado mientras las seis deterministas seguían verdes.

Las doce están en
[`docs/adr/`](docs/adr/) y en el cuaderno de trabajo del proyecto, cada una con
la corrida que la destapó.

---

## Cómo ejecutarlo

Windows, Python 3.12, GPU NVIDIA opcional (sin ella cae a CPU y lo dice).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-probe.txt
python -m piper.download_voices --download-dir voices es_MX-claude-high
Copy-Item .env.example .env    # y pega la clave de Groq
.\.venv\Scripts\python.exe probe\check_entorno.py     # ¿GPU? ¿micrófono?
```

La demo:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000
```

Las comprobaciones. Casi todas **no gastan cuota del modelo**, y eso es
deliberado: el plan gratuito da 200 000 tokens al día y un camino que solo se
puede probar cuando hay cuota se acaba probando poco.

```powershell
.\.venv\Scripts\python.exe -m app.tools.prueba_servicio     # las herramientas
.\.venv\Scripts\python.exe -m app.agent.prueba_fundamento   # el detector de inventos
.\.venv\Scripts\python.exe -m app.agent.prueba_silencio     # el turno vacío
.\.venv\Scripts\python.exe -m app.agent.prueba_reintentos   # tres documentos antes de escalar
.\.venv\Scripts\python.exe -m app.prueba_confianza          # el filtro de voz sigue puesto
.\.venv\Scripts\python.exe -m app.prueba_pasarela           # el stack entero, con audio real
.\.venv\Scripts\python.exe -m app.fin_de_turno              # fin de turno por contenido
.\.venv\Scripts\python.exe -m app.evaluation.particion      # el reservado no se solapa
```

Y las mediciones:

```powershell
.\.venv\Scripts\python.exe -m app.medir_turno --repeticiones 6 --fin-por-contenido
.\.venv\Scripts\python.exe -m app.evaluation.correr              # el agente
.\.venv\Scripts\python.exe -m app.evaluation.correr --linea-base # el árbol de reglas
.\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 12 --prompt actual
#   relee lo guardado: no gasta una sola petición. Sin los filtros se niega a
#   mezclar corridas de tamaños o brazos distintos, que es como se fabrica una media falsa.
.\.venv\Scripts\python.exe probe\confianza_asr.py                # ¿se inventa turnos?
.\.venv\Scripts\python.exe probe\probe_wer.py --linea-telefonica
```

Cada medición se guarda en `artifacts/*.json` con su fecha, su máquina, su
tamaño de muestra, las muestras crudas y la frase exacta de qué instante a qué
instante se cronometró. Un número sin esa frase no se publica. El audio no se
versiona. Y varios programas **se niegan a dar un número** antes que darlo
mal: `presupuesto.py` si falta una etapa, `estabilidad.py` si le piden mezclar
corridas de brazos distintos, y `medicion_final.py` si no consigue cinco
corridas limpias.

---

## Las decisiones, con lo que se descartó

Nueve ADR en [`docs/adr/`](docs/adr/). Los que más cuentan:

| | |
|---|---|
| [**0002**](docs/adr/0002-como-se-decide-que-alguien-termino-de-hablar.md) | cómo se decide que alguien terminó de hablar. Ventana de silencio sola: 1600 ms, el 188% del presupuesto |
| [**0003**](docs/adr/0003-que-dice-el-agente-mientras-la-herramienta-corre.md) | qué dice el agente mientras la herramienta corre, y la regla de publicar siempre los dos números juntos |
| [**0004**](docs/adr/0004-adelantar-la-consulta-antes-de-que-el-modelo-la-pida.md) | adelantar la consulta antes de que el modelo la pida. Funciona, no se distingue del ruido, y el motivo es el hallazgo |
| [**0005**](docs/adr/0005-por-que-no-puede-afirmar-nada-que-no-venga-de-una-herramienta.md) | por qué no puede afirmar nada que no venga de una herramienta — con el texto de respaldo que mentía |
| [**0006**](docs/adr/0006-que-pasa-si-una-herramienta-falla-a-mitad.md) | qué pasa si una herramienta falla a mitad: el error es un resultado para el modelo, no una excepción |
| [**0007**](docs/adr/0007-idempotencia-de-las-acciones-con-efecto.md) | idempotencia: la clave es del **turno**, y de ahí se sigue que nada con efecto se puede adelantar |
| [**0008**](docs/adr/0008-que-hace-el-agente-cuando-la-transcripcion-no-es-de-fiar.md) | qué hace cuando la transcripción no es de fiar |
| [**0009**](docs/adr/0009-cuando-se-decide-que-alguien-esta-hablando.md) | **decisión revertida el mismo día**, y de los documentos más útiles del repositorio |

---

## Qué falta

Sin adornos, y por orden de lo que más acerca esto a una llamada de verdad:

1. **La medición del conjunto reservado.** El protocolo está escrito y los 8
   casos siguen sin tocarse. Es lo siguiente.
2. **Varias voces y ruido.** Todo lo medido sale de **una sola habitación, un
   micrófono y un hablante**. Ese es el techo del proyecto ahora mismo, y hoy
   ya causó un problema: un cambio calibrado contra esa única sala hubo que
   revertirlo (la número 12 de la lista de arriba).
3. **Barge-in**: hoy, mientras el agente habla, se ignora la entrada. Es una
   decisión declarada —sin cancelación de eco el micrófono capta la propia voz
   del agente— y es la métrica que falta.
4. **El despliegue de varias pasarelas.** El expediente (PostgreSQL) y el
   estado compartido (Redis) ya están, y hay una prueba que atiende un turno en
   una pasarela y el siguiente en otra distinta. Lo que falta es el despliegue
   en sí: dos procesos detrás de un balanceador. Lo demostrado es que **el
   estado no las ata**, no que el despliegue exista.
5. **La llamada de teléfono de verdad.** El canal de Twilio Media Streams está
   escrito y comprobado sin cuenta: G.711 µ-law verificado contra la
   implementación de la biblioteca estándar en los 65 536 valores posibles, el
   protocolo emulado con un cliente de mentira, y una grabación real que
   sobrevive al viaje 16 kHz → 8 kHz → µ-law → vuelta → transcripción, y el
   endpoint devuelve audio por un socket real. Falta **Twilio en sí**: una
   cuenta, un número y un túnel, con los pasos en
   [`docs/telefonia.md`](docs/telefonia.md).

De las seis métricas por las que este proyecto quiere ser juzgado están hechas
la latencia, la transcripción y la tarea completada sobre calibración. El coste
está instrumentado y con el precio confirmado, a falta de una corrida. Faltan
la corrección de llamadas a herramientas y el barge-in.

## Pila

| pieza | elección | por qué |
|---|---|---|
| voz → texto | `faster-whisper` local / Deepgram Nova-3 | se desarrolla contra lo local y se graba contra Deepgram |
| texto → voz | `Piper` local / Deepgram Aura-2 | Piper da 136 ms de p95: ninguna ida y vuelta por red lo mejora |
| modelo | `openai/gpt-oss-20b` en Groq | entra en el presupuesto del turno |
| fin de habla | Silero VAD + fin de turno por contenido | ver `docs/adr/0002` |
| telefonía | Twilio Media Streams, G.711 µ-law | el códec, verificado contra la biblioteca estándar en los 65 536 valores; el protocolo, con un cliente que lo emula |
| estado | Redis | el estado conversacional se escribe una vez por turno; el audio no viaja. Hay una prueba que atiende un turno en una pasarela y el siguiente en otra |
| expediente | PostgreSQL | tres tablas, lo que devolvió cada herramienta guardado entero. Si la base cae, la llamada sigue y la pérdida se cuenta |
