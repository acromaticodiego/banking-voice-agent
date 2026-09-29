# banking-voice-agent

Agente de voz telefónico para verificación de identidad y atención al cliente:
mantiene una conversación, decide qué preguntar, llama herramientas, se recupera
cuando algo falla, y trabaja contra un reloj. Al colgar queda un expediente en
PostgreSQL con qué se dijo, qué herramienta se llamó, con qué argumentos, qué
devolvió y qué se revisó de lo que el agente contestó.

**Estado (2026-09-29): el sistema funciona de punta a punta y está medido,
incluido el conjunto reservado.** Se habla por el micrófono del navegador, el
agente decide, llama herramientas, se recupera cuando fallan y contesta
hablando. Cinco de las seis métricas por las que el proyecto quiere ser juzgado
están medidas y la sexta está empezada. Lo que falta está al final, sin
adornos: no hay una llamada real por la red telefónica —el canal está
implementado y verificado, falta la cuenta— y el barge-in está hecho por
teléfono pero apagado en el navegador.

**El conjunto reservado se midió el 2026-09-26 y está quemado.** Ocho casos que
el sistema no había visto nunca, cinco corridas, protocolo escrito dos días
antes de tocarlo. Resultado: mediana **5/8** contra **4/8** del árbol de reglas,
y **1 fuga de datos contra 4**. No se puede volver a medir, y cada vez que se
cita esa cifra hay que decir con qué versión del agente se midió
(`7ff8a93`) y que todo arreglo posterior está informado por ese resultado.

> **Lo que de verdad merece la pena de este repositorio no son los números
> buenos: es la lista de quince veces que una medición salió limpia y era
> falsa.** Está más abajo, con nombre y apellido de cada error, incluidas las
> que obligaron a revertir código escrito el mismo día y la que casi hace
> publicar que un arreglo de seguridad costaba cuatro puntos cuando no costaba
> ninguno.

---

## Qué hay construido

| pieza | fichero | qué hace |
|---|---|---|
| llamada en vivo | `app/vivo.py` | consume audio según llega, decide cuándo terminó el turno, orquesta |
| bucle del agente | `app/agent/loop.py` | decide, llama herramientas, se recupera, frase puente, presupuesto por turno, idempotencia |
| herramientas | `app/tools/service.py` | FastAPI, una por capacidad, con cabeceras para provocar fallos y latencia |
| pasarela y pantalla | `app/gateway.py`, `app/web/` | WebSocket, micrófono con AudioWorklet, conversación y llamadas a herramientas en vivo |
| fin de turno | `app/fin_de_turno.py` | decide si la frase está a medias **por contenido**, no solo por silencio |
| fundamento | `app/agent/fundamento.py` | compara lo que dice el agente con lo que devolvieron las herramientas: números, acciones y procedimientos. Determinista, sin modelo |
| evaluación | `app/evaluation/` | 20 casos con rúbrica, partición con reservado bajo llave, línea base sin modelo, estabilidad entre corridas, protocolo de la medición final |
| telefonía | `app/telefonia/` | G.711 µ-law propio y el protocolo de Twilio Media Streams, comprobado sin cuenta con un cliente que lo emula |
| expediente | `app/expediente/` | lo que queda al colgar, en PostgreSQL: qué se dijo, qué herramienta con qué argumentos, qué devolvió y qué se revisó |
| estado compartido | `app/estado.py` | el estado conversacional en Redis, una escritura por turno. Otra pasarela retoma la llamada, y hay prueba de que lo hace |
| cuota | `app/evaluation/cuota.py` | el libro de la ventana deslizante de 24 h: cuánto queda y **a qué hora cabrá** una medición entera |

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

> **Este 0,0% describe una voz, no el sistema.** Con una segunda persona sube al
> 18–27%, y está medido dos secciones más abajo. Se deja aquí porque es la cifra
> que este documento llegó a publicar como la métrica del proyecto, y borrarla
> sería esconder cómo se cayó.

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
representativa: para eso hacen falta **varias voces y ruido de fondo**.

### Y con otra voz, ese 0,0% se cae (2026-09-27)

Es lo primero que se mide con material grabado fuera de la habitación de
siempre. Una segunda persona, mismo guion, mismo micrófono:

| | la voz de siempre | otra voz |
|---|---|---|
| error normalizado, sin filtro | 0,0% | **27,3%** |
| error normalizado, con `vad_filter` | 0,0% | **18,2%** |
| **números críticos recuperados** | 3/3 | **1/1** |

**El 0,0% describía una voz, no el sistema**, y esa era exactamente la métrica
que este documento publicaba. Con otra persona el error normalizado se va al
18–27%.

**Y lo que sí se sostiene es justo lo que importa: el documento sale entero.**
Whisper destroza las palabras —*«ya amo porque me lo quedan a la tarjeta»* por
*«llamo porque me bloquearon la tarjeta»*— y acierta las cifras. Para un agente
que verifica una identidad, la cifra es el dato y la palabra es el envoltorio,
así que la conclusión operativa no cambia; la cifra publicable, sí.

Aquí el filtro de voz **mejora** la transcripción, al contrario que en las
degradaciones de voz lejana. Con n=1 por voz esto es orden de magnitud, no una
tasa: hacen falta más personas.

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

> **Y ese «0 de 64» también describía una habitación.** Repetido el 2026-09-27
> con 33 segundos de ruido grabados a propósito en otra sala —196 tramos, contra
> los 142 reciclados de la primera—, sin filtro alucina **8 de 64** y **con
> filtro se cuela 1**. La decisión no cambia: el filtro sigue valiendo la pena,
> pasa de 8 a 1 por +19 ms. Lo que cambia es la frase con la que se cuenta, que
> ya no puede ser «lo elimina» sino «lo reduce casi del todo». Y lo que se cuela
> es del tipo peligroso —*«¡Muy bien!»*—, que es el mismo caso que el *«¿Qué
> pasa?»* de abajo: no delata nada.

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
el que es ese y no otro**, partidos en 12 de calibración y 8 reservados. El
protocolo para gastar los reservados —k=5 corridas, mediana, rango, conteo por
caso y mayoría— se escribió **dos días antes** de tocarlos, que era la única
ventana para escribirlo sin trampa. Pedirlos sin declarar que es la medición
final lanza una excepción.

### El reservado, medido una vez (2026-09-26). Está quemado

Agente `7ff8a93`, cinco corridas y **las cinco limpias** —ninguna descartada—,
reloj de 15 s. El protocolo se siguió tal cual estaba escrito, sin tocarle nada
al ver el resultado.

| | agente | línea base sin modelo |
|---|---|---|
| desenlace correcto | mediana **5/8**, rango 5–6 | **4/8**, determinista |
| casos estables entre corridas | 5/8 | 8/8 |
| **fugas de datos de la cuenta** | **1** | **4** |
| coste por conversación | **0,000190 $** (n=40) | — |

**Lo que se puede afirmar:** sobre el único conjunto donde la comparación no
está contaminada, la ventaja del agente **sí se distingue**. Gana en los dos
ejes y esta vez sin solaparse —rango 5–6 contra el 4 determinista— y filtra
datos en 1 de 8 casos contra 4 de 8. Un árbol de reglas que consulta y recita
no sabe callarse.

**Lo que NO se puede afirmar:** que ese 5/8 y el 9/12 de calibración sean
comparables. Son conjuntos distintos, de tamaños distintos, y con 8 casos un
caso vale 12,5 puntos.

**Y uno de los tres fallos se deja fallando a propósito.**
`documento-no-existe` espera `escala` y el agente pide repetir: está haciendo
exactamente lo que se le mandó el 24/09 —probar tres documentos antes de pasar
a un humano, porque al teléfono la gente se equivoca—. El caso tiene 2 turnos,
así que **es inacertable por diseño para el agente de hoy**. La rúbrica dice una
cosa defendible y el sistema hace otra defendible; se deja el desacuerdo escrito
en vez de ajustar la vara después de ver el resultado.

### Sobre calibración, que es donde se itera

Tres corridas del agente de hoy (`acf3cbc7`, 29/09), con la fuga de datos
cerrada en el código y el guardia de la transferencia puesto:

| desenlace correcto | agente | línea base sin modelo |
|---|---|---|
| con reloj holgado (15 s) | mediana **9/12**, rango 7–9 | 5/12, determinista |
| con el reloj de la demo (3 s) | mediana **4/12**, rango 3–5 | — |
| casos estables entre corridas | 8/12 (**10/12** descontando el reloj) | 12/12 |
| fugas de datos de la cuenta | **0 de 3 corridas** | **0** |

> **Dos de esos «inestables» no son del agente, son del reloj.** En la corrida
> del medio a dos casos se les acabó el presupuesto del turno y se quedaron sin
> desenlace; en las otras dos, donde el agente sí llegó a decidir, los acierta.
> El recuento de turnos con el reloj agotado se publica por eso — sin él, esto
> sería una medición de latencia disfrazada de tarea completada.

Y la lectura honesta, que es la parte que importa:

- **El reloj y las decisiones están enredados**: la evaluación corre con reloj
  holgado porque mide decisiones, así que **ese número no describe la demo**.
  Con el reloj de 3 s el presupuesto salta en 8 a 10 de los 12 casos y el caso
  se queda sin desenlace. Las dos cifras se publican siempre juntas.
- **La estabilidad importa tanto como la mediana.** Antes de cerrar la fuga, 6
  de los 12 casos cambiaban de desenlace entre corridas del mismo día con el
  mismo modelo. Por eso cada número va con mediana y rango, y por eso existe
  `estabilidad.py`, que relee lo guardado sin gastar una petición.
- **Cerrar la fuga no costó desenlaces, y de regalo estabilizó el sistema**: de
  8/12 casos estables a 11/12, con las tres corridas dando 9 exactamente. La
  hipótesis —**no comprobada**, y se apunta como hipótesis— es que quitarle al
  modelo una decisión discrecional le quita también su varianza.
- **Una versión del agente no es un commit.** Dos corridas solo son comparables
  si la **huella** —el hash de `app/agent`, `app/tools` y el catálogo— es la
  misma. `estabilidad.py` se niega a mezclar huellas distintas; antes las
  mezclaba en silencio, y de hecho lo hizo.

### La fuga de datos: cómo una frase publicada se cayó y luego se hizo verdad

Este documento llegó a decir que **la línea base filtra datos de la cuenta y el
agente en ninguno, en ninguna corrida de ningún brazo**. Era cierto el 24/09 y
dejó de serlo el 25/09: en 2 de 3 lecturas del caso `nombre-no-coincide` el
agente consultó el estado de la tarjeta y lo recitó —*«su tarjeta terminada en
4582 está bloqueada desde el 15 de septiembre…»*— y **después** pidió el nombre
para verificar. Quien llamaba había dado un nombre que no es el del titular.

La regla estaba en el prompt, explícita: *«NUNCA digas el nombre del titular ni
ningún otro dato de la cuenta antes de haber verificado la identidad»*. El
diagnóstico fue que **el prompt prohibía DECIR el dato y nada impedía
OBTENERLO**: la herramienta devolvía las tarjetas sin mirar si la identidad
estaba verificada, la precondición vivía en la *descripción* dirigida al
modelo, y el bucle no llevaba estado de identidad verificada.

**El arreglo fue mover la garantía del texto al código.** Hoy
`consultar_identidad` recibe el nombre declarado, **compara y no lo devuelve**;
el identificador de cliente solo sale cuando la verificación pasa. El modelo no
puede filtrar lo que nunca tiene, y eso ya no depende de que obedezca.

Dos cosas que salieron de hacerlo y valen más que el arreglo:

- **El invariante de la prueba no cazaba nada al principio.** Borraba el nombre
  del texto antes de buscarlo, así que al reintroducir la fuga a propósito
  seguía en verde: eliminaba justo la cadena que tenía que detectar. Es una
  prueba que pasa sin cubrir nada, cometida **dentro de la prueba escrita para
  evitarlo**.
- **Queda un límite conocido:** la prueba de haber verificado es tener el
  identificador de cliente, y el formato es adivinable. Cerrarlo pide un testigo
  aleatorio por llamada, y **no está hecho**.

## Coste por conversación

Los tokens se cuentan por paso, por turno y por conversación, y el contador
está comprobado con un modelo de mentira que declara su consumo. El precio está
confirmado: **0,075 $ por millón de tokens de entrada y 0,30 $ de salida**
([ficha del modelo](https://console.groq.com/docs/model/openai/gpt-oss-20b),
24/09).

| | reservado (26/09) | calibración (25/09) |
|---|---|---|
| tokens por conversación, media | **2 143** (n=40) | 2 554 (n=12) |
| **coste por conversación** | **0,000190 $** | 0,000226 $ |
| repetibilidad | — | tres corridas: 2 554 / 2 544 / 2 552 tokens |

La cifra del reservado sale de 40 conversaciones y es la buena para citar. Es
**más baja** que la de calibración porque esos casos tienen menos turnos (1,75
contra 2,00 de media), lo que confirma de paso que **lo que manda en el coste
son los turnos, no los casos**.

Y la métrica estuvo a punto de no existir: hasta el 25/09 el protocolo de la
medición final llamaba al turno del agente **sin pedirle el consumo**, y su
artefacto salía con `consumo: null` mientras la documentación prometía que el
coste saldría «de regalo» con el reservado. No habría salido, y se habría
descubierto con el conjunto ya quemado. Se arregló un día antes de gastarlo.

**Lo que se paga hoy es cero**, porque se desarrolla en el plan gratuito. Eso no
hace inútil la métrica: no mide la factura del desarrollo, mide **cuánto
costaría operarlo**, que es la pregunta que decide si el sistema es viable.

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

## Quince veces que una medición salió limpia y era falsa

Es la parte más útil de este repositorio. **Coherente no es correcto**: un
resultado que cuadra consigo mismo puede estar mal, y cuadraba. Dos de estas
quince obligaron a revertir código escrito el mismo día, una casi hizo gastar a
medias el conjunto reservado, y otra casi hizo publicar que un arreglo de
seguridad costaba cuatro puntos cuando no costaba ninguno.

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

**13. La cuenta de la cuota cuadraba sola y faltaba un tercio.** Para saber si
cabía la medición del reservado se sumaron los tokens de las corridas del día:
~148 000 de 200 000, luego quedaban ~52 000. La suma era correcta, la
aritmética era correcta, y el número estaba mal por 51 000 — porque **el límite
no es diario sino una ventana deslizante de 24 horas**, y arrastraba el gasto
del día anterior a esa misma hora. Groq lo llama «tokens per day», que es lo que
invita a equivocarse; lo delata que el propio mensaje de error diga «reinténtalo
en 1m9s», porque un contador que se pone a cero a medianoche no se recupera en
69 segundos. **Contabilizar lo que gastas no sirve si no sabes sobre qué ventana
se cuenta.** Y la parte incómoda: la recomendación de esa mañana —no quemar el
reservado— fue la correcta **con el número equivocado**.

**14. El canario que protegía el reservado comprobaba lo que no importaba, y su
propio docstring lo decía.** Existía, palabra por palabra, para que el protocolo
no arrancara y se quedara sin cuota a la tercera corrida, porque medio reservado
gastado no es medio reservado. Y lo que comprobaba era que **una** petición del
tamaño real pasara, que no dice nada de si caben **cinco corridas**. Ese día dio
luz verde y la corrida siguiente murió a mitad. Es la familia de las pruebas que
pasan sin cubrir lo que dicen, con un agravante: **la distancia entre lo que el
código prometía y lo que hacía estaba escrita en el propio módulo, en español, y
nadie la leyó al lado del código.**

**15. Arreglar la fuga de datos parecía costar cuatro puntos, y no costaba
ninguno.** Cerrada la fuga, el agente cayó de 9/12 a 5/12 y la explicación
sonaba razonable: el guardia había estropeado la conversación. Al leer lo que el
agente decía en los cuatro casos perdidos, **hacía exactamente lo correcto** y
el clasificador lo etiquetaba mal. Reclasificada la misma corrida con el
criterio corregido: **9/12, sin perder nada.** Lo valioso no es el fallo del
instrumento sino **cuándo apareció**: justo después de un cambio en el sistema y
en la dirección que hacía creíble culpar al cambio. Un fallo del instrumento que
aparece a la vez que una modificación se atribuye a la modificación, y el
instrumento se va de rositas — y aquí la conclusión falsa habría sido un
argumento para revertir un arreglo de seguridad. Por eso el arreglo del
clasificador va con tres condiciones comprobadas: textos literales de corridas
reales, que reclasificar no infle al agente viejo, y que ningún agente
degenerado apruebe. **Sin las tres, arreglar el instrumento justo después de ver
un resultado malo no se distingue de ajustar la vara, aunque sea correcto.**

Las quince están en [`docs/adr/`](docs/adr/) y en el cuaderno de trabajo del
proyecto, cada una con la corrida que la destapó.

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
deliberado: el plan gratuito da 200 000 tokens en una **ventana deslizante de
24 horas** —no al día, y esa distinción costó casi el conjunto reservado: es la
número 13 de la lista de arriba— y un camino que solo se puede probar cuando hay
cuota se acaba probando poco.

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

Diez ADR en [`docs/adr/`](docs/adr/). Los que más cuentan:

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
| [**0010**](docs/adr/0010-si-el-agente-dice-que-pasa-la-llamada-la-llamada-se-pasa.md) | si el agente dice que pasa la llamada, la llamada se pasa. **Hay promesas que se pueden hacer verdad y promesas que solo se pueden prohibir**, y la línea la traza qué herramienta existe |

---

## Qué falta

Sin adornos, y por orden de lo que más acerca esto a una llamada de verdad:

1. **Más voces.** Todo lo medido sale de **dos personas y dos habitaciones**, y
   con una grabación por voz eso es orden de magnitud, no una tasa. Es el techo
   del proyecto ahora mismo, y ya ha costado dos veces: un cambio calibrado
   contra una sola sala hubo que revertirlo (la número 12 de la lista de
   arriba), y al meter una segunda voz **se cayeron dos números publicados** —el
   0,0% de error normalizado describía una voz, no el sistema, y el filtro que
   dejaba la alucinación en 0 de 64 la deja en 1—. Las sondas ya miden con lo
   que haya: solo hace falta grabar.
2. **Que el agente EJECUTE lo que dice.** Es el fallo más importante que le
   queda, y el más difícil de ver porque la respuesta suena impecable: dice «voy
   a pasarle con un asesor humano» y no llama a la herramienta. Pasa en 1 de
   cada 12 casos. Desde el 27/09 hay un guardia que cumple esa promesa concreta
   y la marca como forzada ([ADR
   0010](docs/adr/0010-si-el-agente-dice-que-pasa-la-llamada-la-llamada-se-pasa.md)),
   pero se apoya en reconocer la frase en el texto, y ese patrón ya ha tenido
   **tres huecos en tres días**. El arreglo de verdad —que la intención no se
   busque en el texto— no está diseñado.
3. **Barge-in por navegador.** Interrumpir al agente ya funciona **por
   teléfono**: 400 ms de voz seguida le cortan la palabra, lo que dijo quien
   interrumpe no se pierde, y se manda `clear` para que la línea deje de sonar.
   Se comprobó sin micrófono, con el emulador. En el navegador sigue apagado a
   propósito: sin cancelación de eco comprobada, el sistema se interrumpiría a
   sí mismo.
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

De las seis métricas por las que este proyecto quiere ser juzgado **están
medidas cinco**: latencia, tarea completada —calibración **y reservado**—,
transcripción, coste por conversación y barge-in por teléfono. La sexta, la
corrección de las llamadas a herramientas, **está empezada**: cada corrida
cuenta ya en cuántos casos el agente prometió pasar la llamada sin ejecutarla,
y eso sale gratis con la medición.

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
