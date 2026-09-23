# ADR 0004 — Adelantar la consulta antes de que el modelo la pida

- **Fecha:** 2026-09-23
- **Estado:** implementada, **sin efecto medible**, y el motivo es lo valioso
- **Contexto:** intento de bajar los 2061 ms del "primer dato"

## La idea

Un turno con herramienta es: el modelo decide llamar → la herramienta responde
→ el modelo contesta con el resultado. La consulta va **detrás** de la primera
decisión. Si en lo que dijo la persona ya hay un documento, la consulta puede
salir a la vez que se le pregunta al modelo, y cuando la pida ya estará hecha.

Solo se adelantan herramientas de **lectura pura**. Adelantar una escalada
sería abrir un ticket que nadie pidió.

## Lo que se midió, en orden

**1. La primera recomendación estaba mal.** Propuse esto para atacar los
1267 ms del agente sin mirar de qué estaban hechos. La herramienta de mentira
contesta en 5 ms: los 1267 son **dos llamadas al modelo**, no la consulta.
Adelantar algo que ya es instantáneo no ahorra nada.

Por eso la herramienta tiene `X-Tardar-Ms` desde el principio. Con 400 ms, que
es lo que tardaría un core bancario, el problema ya existe.

**2. Con n=3 parecía funcionar. Con n=6 salió al revés.** El adelanto
"empeoraba" el turno en 600 ms, lo cual es imposible: es una lectura en
paralelo cuyo resultado se reutiliza. Lo que pasa es que **las dos llamadas al
modelo varían más que lo que se ahorra**, y con el plan gratuito de Groq
encolando peticiones, la varianza se come el efecto. Ni la mejora de n=3 ni el
empeoramiento de n=6 eran reales.

Así que la métrica pasó a ser otra: **cuántas consultas se sirven ya hechas**.
Eso es determinista y no depende de la varianza del modelo.

**3. Dos fallos silenciosos, y el conteo los destapó.** Salía 0 de 6:

- El patrón que busca el documento llevaba **caracteres de retroceso** (0x08)
  donde debían ir bordes de palabra, porque se escribió con un heredoc que se
  comió los escapes. Compilaba sin protestar y no encajaba con nada, nunca.
- El normalizador convertía `"70 23 4 5 6 7"` —como sale del ASR cuando alguien
  dicta su cédula por grupos— en **115**, sumándolo como cardinal. Nadie dice
  un número así.

Arreglados los dos, en aislado el adelanto se usa **1 de 1**, servido a 0 ms.
El mecanismo funciona.

## Por qué sigue sin servir de nada, y esto es lo importante

En la tubería real sigue en **0 de 6**. El motivo lo enseña la transcripción:

```
dijo: "claro que sí, mirá mis datos son mi cédula es 70 234"
```

**El detector de fin de habla cortó a la persona a mitad de la cédula.** No hay
documento completo que adelantar porque no llegó a decirlo. El agente reaccionó
bien —pidió que repitiera en vez de inventárselo— pero la llamada ya se
estropeó.

Es exactamente lo que el [ADR 0002](0002-como-se-decide-que-alguien-termino-de-hablar.md)
había predicho: una ventana de silencio corta que cabe en el presupuesto corta
a la gente justo cuando se está identificando. Aquí se ve ocurriendo.

## La decisión

**El adelanto se queda**, apagado por defecto (`--adelantar`). Funciona, está
probado, y en cuanto el fin de turno deje de cortar valdrá lo que cuesta una
consulta de lectura. Pero **no se publica como mejora de latencia**, porque
medido de punta a punta no se distingue del ruido.

**Y la prioridad cambia.** No es optimizar latencia: es decidir el fin de turno
por el contenido y no solo por el silencio. Mientras el sistema corte a la
gente a mitad del documento, ahorrar 400 ms no arregla nada.

## Lo que se descartó

**Descartado: adelantar también `estado_tarjeta`.** Necesita el `id_cliente`,
que solo existe después de verificar la identidad. Adivinarlo sería inventar.

**Descartado: dar por buena la mejora de n=3.** Era lo cómodo y era mentira. La
comprobación de que sirve tiene que ser determinista, no estadística sobre una
muestra que no aguanta.
