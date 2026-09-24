# banking-voice-agent

Agente de voz telefónico para verificación de identidad y atención al cliente:
mantiene una conversación, decide qué preguntar, llama herramientas, se recupera
cuando algo falla, y trabaja contra un reloj. Al colgar queda un expediente con
qué se dijo, qué herramienta se llamó, con qué argumentos, qué devolvió y qué
evidencia justificó cada decisión.

**Estado: día de medición terminado. El sistema todavía no está construido.**
Lo que hay en el repositorio son sondas que miden si el proyecto es viable antes
de escribirlo. Gastar poco para saber si conviene gastar mucho.

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

| | p50 | p95 |
|---|---|---|
| literal | 16,7% | 30,7% |
| con los números normalizados | **0,0%** | 9,0% |
| números críticos recuperados exactos | **3 / 3** | |

La diferencia entre las dos primeras filas es el asunto entero. La referencia
dice *"uno cero siete cero dos tres cuatro cinco seis siete"* y el sistema
devuelve `1070234567`: palabra por palabra son diez errores **por acertar el
dato completo**. Sin normalizar, la métrica mide ortografía en vez de
comprensión y castiga al sistema por hacerlo bien.

Por eso se añade la tercera fila. Un sistema puede tener un 15% de error de
palabra y acertar el 100% de los documentos, o al revés; en una verificación de
identidad lo segundo es lo único que decide.

Con n=3 y un solo hablante esto calibra el orden de magnitud. No es una tasa
representativa: para eso hacen falta varias voces, ruido y línea telefónica.

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

### El umbral que describía una habitación

Mientras se comprobaba que el filtro de voz no dejara sordo al agente apareció
algo peor, y no era del filtro. El sistema abría turno cuando un trozo de 20 ms
pasaba de una constante, `0.005`. Funcionaba **por una coincidencia**: el ruido
de la habitación de desarrollo mide 0,0011, trece decibelios por debajo.

| | ¿abre turno? |
|---|---|
| grabación original | 6 de 6 |
| la misma voz a la mitad de volumen | **0 de 6** |
| la misma voz por línea telefónica | **1 de 6** |

Quien hablara bajito no era oído, y quien llamara por teléfono tampoco — lo que
dejaba el siguiente paso del proyecto, telefonía real, construido sobre algo que
no podía funcionar. Y el fallo **no deja rastro**: el turno no llega a cerrarse,
así que no hay transcripción vacía y el guardia del turno vacío tampoco se
entera. De todos los fallos de este proyecto es el único invisible.

Ahora el umbral se calibra contra el ruido de la propia llamada. El factor se
eligió con un criterio escrito **antes** de ver la tabla —ningún clip de
silencio puede abrir turno; dentro de eso, oír toda la voz que el ASR entiende—
sobre 72 clips de habla degradada y 48 de silencio:

| | oye voz | abre silencios |
|---|---|---|
| umbral fijo 0,005 | 40 / 72 | 15 / 48 |
| factor 2,0 | 70 / 72 | 1 / 48 |
| **factor 2,5 (elegido)** | **63 / 72** | **0 / 48** |

El 2,0 oye siete clips más y se descartó igual, porque el criterio estaba
fijado de antemano. Lo que hace fácil el cambio es que el adaptativo gana al
fijo **en las dos direcciones a la vez**: no hay intercambio que discutir.
Razonado, con el límite que no arregla, en
[ADR 0009](docs/adr/0009-cuando-se-decide-que-alguien-esta-hablando.md).


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

## Tres veces que una medición salió limpia y era falsa

Es la parte más útil de este repositorio. **Coherente no es correcto**: un
resultado que cuadra consigo mismo puede estar mal, y cuadraba.

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

Y una cuarta, en la métrica de transcripción: la primera versión daba un error
normalizado **peor** que el literal, 45,5% contra 32,3%. El normalizador de
números solo entendía palabras, y el ASR devuelve `1 0 7 0 2 3 4 5 6 7` en
cifras sueltas y `347 mil 200` en forma mixta.

---

## Cómo ejecutarlo

Windows, Python 3.12, GPU NVIDIA opcional (sin ella cae a CPU y lo dice).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-probe.txt
python -m piper.download_voices --download-dir voices es_MX-claude-high
Copy-Item .env.example .env    # y pega la clave de Groq
```

```powershell
.\.venv\Scripts\python.exe probe\check_entorno.py     # ¿GPU? ¿micrófono?
.\.venv\Scripts\python.exe probe\grabadora.py         # grabar muestras de voz
.\.venv\Scripts\python.exe probe\probe_whisper_local.py
.\.venv\Scripts\python.exe probe\probe_groq.py
.\.venv\Scripts\python.exe probe\probe_piper.py
.\.venv\Scripts\python.exe probe\probe_vad.py
.\.venv\Scripts\python.exe probe\probe_wer.py
.\.venv\Scripts\python.exe probe\presupuesto.py       # el veredicto
```

`presupuesto.py` **se niega a dar un total** si falta una etapa por medir, y
sale con código 1. Un total incompleto es peor que ninguno, porque parece un
total.

Cada medición se guarda en `artifacts/*.json` con su fecha, su máquina, su
tamaño de muestra, las muestras crudas y la frase exacta de qué instante a qué
instante se cronometró. Un número sin esa frase no se publica. El audio no se
versiona.

---

## Qué falta

El sistema. No hay pasarela de tiempo real, ni Redis, ni PostgreSQL, ni
herramientas HTTP, ni bucle de agente, ni cliente de navegador. De las seis
métricas por las que este proyecto quiere ser juzgado, están hechas la de
latencia (por etapas, nunca de punta a punta) y la de transcripción. Faltan
tarea completada sobre un conjunto reservado, corrección de las llamadas a
herramientas, coste por conversación y barge-in.

De los seis ADR previstos hay dos.

## Pila

| pieza | elección | por qué |
|---|---|---|
| voz → texto | `faster-whisper` local / Deepgram Nova-3 | se desarrolla contra lo local y se graba contra Deepgram |
| texto → voz | `Piper` local / Deepgram Aura-2 | Piper da 136 ms de p95: ninguna ida y vuelta por red lo mejora |
| modelo | `openai/gpt-oss-20b` en Groq | entra en el presupuesto del turno |
| fin de habla | Silero VAD + fin de turno por contenido | ver `docs/adr/0002` |
| estado | Redis | la pasarela no guarda nada, así escala horizontal |
| expediente | PostgreSQL | |
