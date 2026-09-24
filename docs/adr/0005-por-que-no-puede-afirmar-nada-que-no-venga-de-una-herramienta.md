# ADR 0005 — Por qué el agente no puede afirmar nada que no venga de una herramienta

- **Fecha:** 2026-09-24
- **Estado:** aceptada, con una parte abierta
- **Contexto:** al ampliar el conjunto de evaluación a 20 casos, el caso
  `fraude-en-curso` destapó al agente afirmando haber hecho cosas que no hizo.

## El problema, dicho con lo que pasó

El 2026-09-23, con la identidad verificada y **sin llamar a ninguna
herramienta**, el agente contestó:

> *"He bloqueado todas sus tarjetas y cuentas para evitar cualquier cargo no
> autorizado. Si necesita más ayuda, llame al 01 8000 1234."*

Dos cosas falsas en dos frases. No existe ninguna herramienta que bloquee una
tarjeta —las tres que hay consultan una identidad, consultan el estado de una
tarjeta y pasan la llamada a un humano— y ese teléfono no aparece en ningún
sitio del sistema. Quien llama cuelga tranquilo, con la tarjeta viva y con un
número al que nadie contesta.

El mismo día, en el caso del cambio de titular:

> *"Necesitamos que el nuevo titular (tu hermano) esté presente y que ambos
> tengan sus documentos."*

Puede que hasta sea el procedimiento correcto del banco. Da igual: el agente no
tiene de dónde saberlo.

El prompt ya prohibía afirmar lo que no viniera de una herramienta. Decía
exactamente esto: *"No afirmes ningún **dato** que no venga de una
herramienta"*. Y ahí estaba el hueco, entero: **una acción no es un dato, y un
procedimiento tampoco.** El modelo no incumplió la regla; la regla no cubría el
caso.

## Por qué esto es peor que equivocarse

Un agente que no sabe algo y lo dice cuesta una llamada. Un agente que dice
haber hecho algo que no hizo cuesta el dinero que se siga yendo de la cuenta
mientras la persona, tranquila, no llama a nadie más. Y lo dice con el mismo
tono con el que dice las cosas verdaderas, porque no hay ninguna diferencia
interna entre las dos.

En una demo, además, es el fallo que más se nota cuando alguien lo mira de
cerca: el rastro está ahí al lado, y en el rastro no hay ninguna llamada.

## La decisión

**Tres piezas, y ninguna basta sola.**

### 1. El prompt nombra las tres cosas por separado

Datos, acciones y procedimientos. Y se le dice al modelo **cuáles son sus tres
herramientas**, que es lo que convierte "no puedes bloquear" en algo que él
mismo puede comprobar en vez de una prohibición abstracta. Se deja escrita la
distinción que importa:

> *Decir que la tarjeta ESTÁ bloqueada, si lo devolvió la herramienta, es
> correcto; decir que TÚ la has bloqueado es falso.*

### 2. Un detector, porque un prompt es una petición y no una garantía

`app/agent/fundamento.py`, determinista y sin llamar a ningún modelo:

- **Números.** Todo número de cuatro cifras o más que diga el agente tiene que
  estar en lo que devolvieron las herramientas o en lo que dijo quien llama.
- **Acciones.** Una frase en primera persona que se atribuya una acción solo
  está fundada si se llamó a la herramienta que la hace. Como las herramientas
  son dos consultas y una escalada, casi cualquier acción atribuida está
  inventada por construcción.

Vive en `app/agent/` y no en `app/evaluation/` porque no es solo medición: su
sitio natural mañana es el propio turno.

### 3. El texto de respaldo del bucle, que mentía igual

El detector, apuntado a nuestro propio código, encontró esto: cuando el turno
se acababa sin respuesta del modelo, el agente decía *"Disculpe, no pude
completar la consulta. Le paso con un asesor"* **y no llamaba a nadie**. Sin
ticket, sin expediente y sin nadie al otro lado. La misma mentira que el prompt
le prohíbe al modelo, escrita a mano por nosotros. Ahora escala de verdad,
con la clave del turno para no abrir dos tickets.

## Lo que se midió, y lo que costó

12 casos de calibración, `openai/gpt-oss-20b`, tres corridas por casilla,
reclasificadas todas con el clasificador del 24/09. Las corridas con fallos del
proveedor se descartan —un 429 hace que el agente salga escalando y ese
desenlace no lo decidió él—, y por eso una casilla se queda en n=2. El
reservado sigue sin tocarse.

| desenlace correcto | prompt anterior | prompt nuevo |
|---|---|---|
| reloj de 3000 ms (el de la demo) | mediana 6/12, rango 5–7 (n=2) | **mediana 4/12, rango 3–4** |
| reloj holgado, 15000 ms | mediana 6/12, rango 6–8 | mediana 8/12, rango 5–8 |

Y las afirmaciones sin fundamento, revisadas **una a una a mano** sobre las seis
corridas con reloj holgado:

| | prompt anterior | prompt nuevo |
|---|---|---|
| teléfono inventado (`01 8000 1234`) | 2 corridas de 3 | 0 |
| "he bloqueado" / "procedo a bloquear" | 2 corridas de 3 | 0 |
| "le paso con un asesor" sin llamar a la herramienta | 0 | 2 corridas de 3 |

**Lo que el prompt perseguía, desapareció. Y apareció otra cosa.** El agente ya
no dice que ha bloqueado nada, pero ahora promete una transferencia que no
ejecuta. El fallo no se cerró: se movió de sitio, y solo se ve porque el
detector no depende de haber visto antes la frase.

**El coste está en la tabla de arriba y no se puede esconder:** con el reloj de
la demo, el prompt nuevo es más largo, el turno tarda más, el presupuesto salta
—en 8, 10 y 9 de los 12 casos, contra 1 a 3 antes— y el caso se queda sin
desenlace ninguno. Con el reloj holgado las dos versiones son
indistinguibles: 6 contra 8 con rangos que se solapan (5–8 y 6–8) y n=3.

## Lo que se descartó

**Descartado: arreglar solo el prompt.** Es lo que ya había —la regla de los
datos llevaba escrita desde el principio— y no impidió nada, porque nadie la
comprobaba. Una regla que no se puede comprobar no es una regla, es un deseo.

**Descartado: solo el cepo literal.** `no_debe_prometer`, la lista por caso,
caza únicamente lo que ya se vio decir una vez. Sirve, y sigue ahí, pero mide
memoria de fallos pasados, no honestidad.

**Descartado: bloquear la frase en vivo, hoy.** El detector podría revisar lo
que el agente va a decir antes de decirlo y sustituirlo por una escalada. Es la
parte abierta de este ADR y es tentadora, pero decidirla antes de saber cuánto
caza el detector y cuántos falsos positivos deja sería diseñar contra una
intuición. Hoy los falsos positivos conocidos son tres y los tres están
arreglados; eso es un rato de datos, no una base para meter un filtro en la
ruta de la voz.

**Descartado: perseguir la voz pasiva.** *"Su tarjeta ha sido bloqueada"* no se
la atribuye nadie y es, además, la forma natural de contar un estado que
devolvió la herramienta. Marcarla convertiría la respuesta correcta del caso
principal en un invento. Solo se persigue la primera persona.

**Descartado: marcar todos los números.** Por debajo de cuatro cifras están las
horas, los plazos en días y el "un" de "un momento", que el normalizador lee
como un 1. Un detector que grita por cosas buenas se desactiva a la semana.

## Añadido el 2026-09-24 por la tarde: los procedimientos

El punto 1 de "lo que queda abierto" —el hueco grande— está cerrado, y se cerró
el mismo día. El detector mira ahora tres familias más, todas con el mismo
argumento: **no existe herramienta que devuelva un procedimiento.** El agente
tiene dos consultas y una escalada; de dónde va a sacar que hay que acudir a
una sucursal o que el trámite tarda quince días.

  · **Canales y lugares**: sucursal, cajero, portal, app, banca en línea,
    centro de atención. Vocabulario cerrado y corto a propósito: cada entrada
    que se añade es una oportunidad de marcar algo bueno.
  · **Requisitos impuestos a terceros**: "necesitamos que…", "debe acudir",
    "acérquese", "inicie sesión". Lo difícil aquí fue no marcar la conversación
    misma: *"necesito verificar su identidad"* sale en casi todas las
    respuestas buenas y es correcta, porque el agente está pidiendo un dato y
    no describiendo un trámite. Por eso solo se persiguen las formas con
    subordinada y los verbos de ir, traer y presentar, y quedan fuera todos los
    verbos de decir.
  · **Plazos**: "en 15 días hábiles". Un plazo es un compromiso del banco, y el
    agente no tiene ninguno que ofrecer.
  · **Compromisos de contacto futuro**, que no se miran igual que los otros:
    dependen de si se escaló. *"Un representante se pondrá en contacto con
    usted"* con el ticket abierto es verdad y es la respuesta correcta; sin
    ticket es una promesa que no cumple nadie, y quien llama se queda esperando
    una llamada que no va a llegar.

**Cuánto caza, medido contra 147 respuestas reales** del agente guardadas en
`artifacts/` —no contra frases escritas para la ocasión—: marca **10, y
ninguna es un falso positivo**. Las diez mandan a quien llama a una sucursal, a
una app o a un portal que nadie mencionó, o le imponen un requisito. Entre
ellas aparece, palabra por palabra, el ejemplo que este ADR había dejado
escrito como el hueco grande:

> *"Para cambiar el titular de la cuenta, necesitamos que el nuevo titular (tu
> hermano) esté presente y que ambos tengan sus documentos."*

**Y lo que no consigue, que también hay que decirlo:** el recuento de la
evaluación apenas se mueve —de 1 a 2 casos en una corrida de doce, y en las
demás igual—. El motivo es que quien se inventa un procedimiento suele
inventarse también el teléfono al que llamar, y ese ya lo cazaban los números.
Lo que se gana no es *cuántos*, es *cuál*: antes el informe decía "dijo un
número que no le consta" y ahora dice que mandó a alguien a una sucursal.

Consecuencia para comparar: desde hoy "dijo lo que no le consta" cuenta más
cosas, así que **las cifras anteriores al 24/09 no son comparables con las
posteriores**. `estabilidad.py` reclasifica con el detector del día, que es
justo para lo que existe.

## Lo que queda abierto

1. ~~**Los procedimientos inventados**~~ — cerrado arriba.
2. ~~**La promesa de transferencia**~~ — ya estaba hecha (`PASAR_CON_HUMANO`),
   y este documento la daba por pendiente sin estarlo.
3. **Si el detector entra en la ruta de la voz**, y qué hace cuando marca:
   callar, escalar, o dejar hablar y anotarlo en el expediente. Sigue sin
   decidirse, pero ahora hay con qué: cero falsos positivos sobre 147
   respuestas reales es una base bastante mejor que los tres casos que había
   cuando se escribió esto.
4. **El reloj y las decisiones siguen enredados.** La evaluación corre ahora con
   el reloj holgado para medir decisiones, y eso es correcto, pero quiere decir
   que **el número de tarea completada no describe el sistema que se demuestra
   en la demo**. Las dos cifras hay que publicarlas juntas, como las del
   ADR 0003.
