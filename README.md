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

## El resultado que justifica haber medido primero

El objetivo era **800 ms por turno**, que es donde una conversación empieza a
sentirse rota. La primera medición dijo 2296 ms. La cifra actual es **916 ms**,
y entre una y otra no se escribió ni una línea del sistema: solo se corrigió
cómo se medía.

| | p50 |
|---|---|
| primera medición | 2296 ms |
| tras corregir el método | **916 ms** |
| objetivo | 800 ms |

Los 1380 ms de diferencia no eran optimización. Eran tres errores de medición.

---

## Presupuesto del turno

Medido el 2026-09-19 en un portátil con RTX 3050 de 6 GB. Qué instante a qué
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
