# Proyecto: Agente de voz para verificación y servicio telefónico

Estoy en `C:\Users\ASUS\Desktop\agente_llamada` (Windows, Docker, PowerShell).

## Quién soy

Juan Diego Ossa, Ingeniero Mecatrónico, ~2,5 años como Backend & AI Engineer.
Python (FastAPI), Node/NestJS, PostgreSQL, Redis, Docker, AWS (EC2, S3, ECS),
PyTorch, YOLOv8, OpenCV, pgvector. Entre marzo y agosto de 2026 construí una
plataforma de gestión de llamadas de emergencia: NestJS, transcripción con
Deepgram, integración de LLM, telefonía FreeSWITCH, desplegada en AWS ECS.

Tengo cuatro proyectos de portafolio: detección de accidentes de tráfico,
control de acceso facial con 8 microservicios, clasificación de aguacates, y
un agente de verificación de identidad documental (KYC) con explicaciones
auditables. Los tres primeros son visión por computador.

Este proyecto es para aplicar a vacantes de **Ingeniero de IA Agéntica** en
fintech y banca.

## QUÉ DEBE DEMOSTRAR, Y QUÉ NO

**Debe demostrar** lo único que no enseña ninguno de mis proyectos: un agente
que **mantiene una conversación, decide qué preguntar, llama herramientas, se
recupera cuando algo falla, y trabaja contra un reloj**. Mi proyecto de KYC es
deliberadamente no agéntico —una sola llamada de texto, sin herramientas, sin
bucle— y eso deja un hueco que aquí se tapa.

**No debe demostrar** microservicios: ya lo hice con 8 en el control de acceso.
Ni visión por computador: ya lo hice tres veces. Si este proyecto acaba
pareciéndose a esos, ha fallado.

## QUÉ ES ESTE SISTEMA, EN CORTO

Alguien llama por teléfono. El agente habla con esa persona, **verifica quién
es**, entiende qué necesita, lo resuelve consultando sistemas reales, y decide:
resolver, escalar a un humano o negarse. Cuando cuelga, queda un expediente con
**lo que dijo, qué herramienta llamó, con qué argumentos, qué le devolvió, y
qué evidencia justificó cada acción**.

No es un chatbot con voz. Es un sistema con presupuesto de latencia, con
herramientas y con rastro auditable.

## REGLAS DE TRABAJO (no negociables)

1. NUNCA `git push` sin preguntarme. Una autorización no se extiende a la
   siguiente. Commitear en local sin preguntar sí está bien.
2. Rama de feature, nunca commits a `main`. **Cada tanda de trabajo nueva va
   en su propia rama**, porque yo abro el PR y lo fusiono.
3. NINGUNA atribución a Claude en los commits.
4. Commits y documentación EN ESPAÑOL. Nombres de rama y código en inglés.
5. Estoy en PowerShell: nada de `&&`, `rm -rf`, `export VAR=x`, `2>/dev/null`.
6. VERIFICA CONTRA EL STACK LEVANTADO, no solo que compile.
7. **Commitea ANTES de mutar código.** `git checkout -- app/` borra lo no
   commiteado; ya me costó rehacer trabajo.

## MÉTODO (viene del proyecto anterior y funciona)

- **Todo número va con su tamaño de muestra, su procedencia y la fecha.**
- **Rompe tus propios tests a propósito**: muta el código que el test dice
  proteger y comprueba que falla por ESE motivo. En el proyecto anterior
  destapó una docena de tests que pasaban sin cubrir nada.
- **Coherente no es correcto.** Un resultado que cuadra consigo mismo puede
  estar mal. Compara siempre contra la verdad cuando la tengas.
- **Sé fiel al informar.** Si algo quedó sin comprobar, dilo.
- **Documenta el porqué, no el qué.**
- **Las decisiones que cuestan discusión van a `docs/adr/`**, con lo que se
  descartó y por qué.

## ARQUITECTURA

```
navegador (micrófono, WebRTC)  ──audio──┐
Twilio Media Streams (opcional) ────────┤
                                        ▼
                        ┌──────────────────────────────┐
                        │   PASARELA DE TIEMPO REAL    │  Python, asyncio
                        │   · detección de turno (VAD) │  SIN ESTADO
                        │   · barge-in                 │
                        │   · presupuesto por turno    │
                        └───────────┬──────────────────┘
                                    │
      ┌──────────────┬──────────────┼──────────────┬─────────────────┐
      ▼              ▼              ▼              ▼                 ▼
ASR streaming     AGENTE           TTS        HERRAMIENTAS      EXPEDIENTE
Deepgram          LLM con          Aura-2 /   (HTTP, una        PostgreSQL
Nova-3            herramientas     Piper      por capacidad)
                      │
                      ▼
            estado de sesión: Redis
```

**La pasarela no guarda estado.** Todo lo de la sesión vive en Redis, así que
se pueden levantar N instancias detrás de un balanceador y cualquiera atiende
cualquier turno. Eso es lo que hace esto escalable, y es una frase que hay que
poder defender, no repetir.

**Las herramientas son servicios HTTP independientes**, una por capacidad:
consultar identidad, preguntas de control, estado de tarjeta, movimientos,
escalar a un humano. Detrás de una interfaz, para que mañana se cambien por un
core bancario de verdad sin tocar el agente. **Esto NO es una arquitectura de
microservicios**: es un monolito de tiempo real con las herramientas fuera,
porque una herramienta es justamente lo que tiene que poder sustituirse.

Una de esas herramientas puede ser **mi propio sistema de KYC documental**.
Los dos proyectos se cuentan entonces como una sola línea de trabajo.

## DECISIONES QUE HAY QUE TOMAR Y DEJAR ESCRITAS

Cada una es un ADR, con sus alternativas descartadas:

- **Por qué streaming y no petición-respuesta.** Esperar a que la persona
  termine de hablar para empezar a transcribir duplica la latencia percibida.
- **Cómo se decide que alguien terminó de hablar.** Es el parámetro que más
  cambia la sensación de la conversación y el que más fácil se ajusta a ojo.
  Hay que elegirlo sobre datos y decir sobre cuáles.
- **Qué hace el agente cuando la transcripción tiene poca confianza.** La
  respuesta correcta es pedir que repitan, no adivinar. Un agente que rellena
  huecos en una verificación de identidad es peligroso, no útil.
- **El agente no puede afirmar nada que no venga de una herramienta.** Ni un
  saldo, ni un nombre, ni una fecha. Viene del proyecto anterior y es lo que
  lo diferenciaba: lo que se afirma se comprueba.
- **Qué pasa si una herramienta falla a mitad de la llamada.** Igual que allí:
  ni inventar ni colgar. Escalar a un humano es admitir lo que no se sabe.
- **Idempotencia.** Si un turno se reintenta, una transferencia no puede
  ejecutarse dos veces.

## LO QUE SE MIDE

El proyecto se juzga por números, no por la demo:

1. **Latencia por turno, desglosada por etapa**, con p50 y p95. Cuánto se
   lleva la detección de fin de turno, cuánto el ASR, cuánto el modelo,
   cuánto la síntesis. **Este es el número de portada.**
2. **Tarea completada**, sobre un conjunto reservado de conversaciones
   guionadas, medido UNA SOLA VEZ.
3. **Corrección de las llamadas a herramientas**: si invocó la correcta y con
   los argumentos correctos.
4. **Tasa de error de transcripción** en español, con ruido y acento paisa.
5. **Coste por conversación**, en dólares y en peticiones.
6. **Barge-in**: qué proporción de interrupciones se manejan sin pisarse.

## EL CONJUNTO DE EVALUACIÓN

Conversaciones guionadas con el desenlace correcto anotado y **el motivo
escrito para poder discutirse**. Partido en calibración y reservado, con la
partición impuesta por la herramienta —pedir el reservado sin declarar que es
la medición final tiene que lanzar una excepción—, y el reservado se mide
**una sola vez**.

Tiene que haber casos donde lo correcto sea **negarse** y casos donde lo
correcto sea **escalar**. Un conjunto en el que todo se resuelve mide un
sistema de una sola salida y lo llama de tres.

Y una línea base sin modelo de lenguaje —un árbol de decisión sobre lo mismo—
para poder decir cuánto aporta el agente sobre los mismos casos.

## PILA, Y POR QUÉ

| pieza | elección | motivo |
|---|---|---|
| voz→texto | Deepgram **Nova-3** (streaming) | tengo 200 USD de crédito |
| texto→voz | Deepgram **Aura-2** | misma cuenta, misma red, menos ida y vuelta |
| modelo | **Groq** (plan gratuito) | la velocidad de inferencia entra en el presupuesto del turno |
| desarrollo | `faster-whisper`, `Piper`, `Ollama` | locales, ilimitados, gratis |
| estado | **Redis** | la pasarela no guarda nada |
| expediente | **PostgreSQL** | ya lo uso |
| canal | navegador WebRTC; Twilio Media Streams opcional | el segundo es el patrón de la industria |
| todo | **Docker Compose** | |

**Se desarrolla contra lo local y se graba contra Deepgram.** Los 200 dólares
se van en una tarde de pruebas si cada iteración sale a la nube.

## TRAMPAS QUE YA CONOZCO

- **El problema es el presupuesto de latencia, no el modelo.** Por encima de
  800 ms por turno la conversación se siente rota. Todo se diseña contra eso.
- **El modelo es lo caro en peticiones.** Una conversación son diez o quince
  llamadas, no una. Con el plan gratuito de Gemini (20 al día) no cabe ni una
  conversación y media. Por eso el bucle va en un modelo rápido y pequeño, y
  solo el razonamiento difícil sale a uno grande, una vez.
- **No guardar audio crudo.** Y redactar el número de documento en los
  registros. Un expediente de llamada no necesita la voz dentro.
- **`getUserMedia` solo existe en `https` o en `localhost`.** Por la IP de la
  red el navegador bloquea el micrófono sin avisar.
- **Medir el coste por minuto de Deepgram desde el primer día**, no cuando
  queden 20 dólares.
- Los heredocs de bash con `\n` dentro de cadenas Python se rompen. Para
  parches con escapes, usa la herramienta de escritura de ficheros.

## CÓMO EMPEZAR

**No construyas nada el primer día. Mide.**

1. Diez segundos de mi voz: cuánto tarda `faster-whisper` en mi máquina.
2. Cuánto tarda `Piper` en decir una frase.
3. Cuánto tarda Groq en responder algo corto.
4. Lo mismo contra Deepgram Nova-3 y Aura-2, y **cuánto costó**.
5. Suma las etapas y dime si el presupuesto de 800 ms es alcanzable.

Si no lo es, hay que cambiar el enfoque y lo sabemos en un día en vez de en
tres semanas. Es la misma lógica que la sonda del proyecto anterior: **gastar
poco para saber si conviene gastar mucho.**

Después de esa medición, dime qué recomiendas y en qué orden.

## DOS AVISOS SOBRE ESTE DOCUMENTO

- **Las condiciones de los planes gratuitos cambian.** Las de Groq, Twilio y
  cualquier otra hay que comprobarlas al crear la cuenta, no darlas por buenas
  porque estén escritas aquí.
- **Los 800 ms son un objetivo razonable, no una promesa.** Puede que en esta
  máquina no se alcancen, y eso es exactamente lo que tiene que descubrir el
  día de medición.
