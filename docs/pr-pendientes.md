# Textos para los dos PR pendientes (29/09)

Copiar y pegar. Las dos ramas están **sin empujar** y la segunda **nace de la
primera**, así que el orden importa: primero `feature/verification-order`, y
cuando esté fusionada, `feature/transfer-guard-coverage`.

```powershell
git push -u origin feature/verification-order
# abrir el PR, fusionarlo, y despues:
git push -u origin feature/transfer-guard-coverage
```

---

## PR 1 — `feature/verification-order` → `main` (13 commits)

**Título:** El orden de la verificación, el guardia de la transferencia y la
segunda voz

**Cuerpo:**

Tres tandas que se acumularon sin PR, en orden cronológico.

### 1. El orden de la verificación (27/09)

El arreglo de la fuga de datos había dejado una regresión: el agente pedía el
nombre **antes** del documento y antes de intentar ninguna consulta, así que en
`core-caido-a-mitad` no llamaba a nada, nunca descubría que el core estaba caído
y no podía escalar. Ahora el documento va primero —para saber si existe y **si
el sistema responde**— y el nombre después.

Con eso el agente pasó de `herramientas: []` a llamar de verdad. Y entonces
pedía que repitieran el documento, que no arregla una herramienta caída: la
causa no era que faltara la regla en el prompt, sino que **el resultado no decía
cuál aplicaba**. Ahora el fallo trae su propio `_que_hacer`. Es la lección de la
fuga una capa más allá: **la garantía que vive solo en el prompt se desobedece;
la que viene dentro del resultado, no.**

Costó 2 puntos de 12, reproducibles (7/12 las tres corridas), y el diagnóstico
de por qué está en la tanda siguiente.

### 2. El guardia de la transferencia (27–28/09), con [ADR 0010](docs/adr/0010-si-el-agente-dice-que-pasa-la-llamada-la-llamada-se-pasa.md)

**Si el agente dice que pasa la llamada, la llamada se pasa.** El fallo estaba
en tres casos —`tarjeta-falla-tras-verificar` 0 de 5 en el reservado— y en uno de
ellos el agente dice lo correcto palabra por palabra y no llama a nadie. Un
agente que suena impecable y no ha hecho nada.

Solo aplica a la transferencia, porque **de todas las acciones que el detector
vigila es la única que tiene una herramienta detrás**: hay promesas que se pueden
hacer verdad y promesas que solo se pueden prohibir. Lleva la clave del turno
(ADR 0007), así que un reintento no abre dos tickets, y queda marcado como
forzado para que el asesor que lo recibe sepa que el agente lo prometió sin
ejecutarlo.

Dos huecos del detector salieron al escribirlo, y el segundo se corrigió aquí: un
ofrecimiento condicional abría un ticket que nadie pidió. **El mismo falso
positivo costaba un número en un informe y pasó a costar el trabajo de una
persona** — un detector que pasa de contar a actuar cambia el precio de sus
errores.

Medido: mediana 8/12, rango 6–9.

### 3. Segunda voz y segunda sala (27/09), sin gastar un token

Rompieron dos números que este repositorio publicaba:

- **el 0,0% de error de transcripción describía una voz, no el sistema.** Con
  otra persona se va al 18–27%. Lo que sí se sostiene es lo que importa: los
  números críticos salen enteros, y para verificar una identidad la cifra es el
  dato y la palabra es el envoltorio.
- **el filtro de voz no deja la alucinación en 0 de 64 sino en 1.** La decisión
  del ADR 0008 no cambia —pasa de 8 a 1 por +19 ms— pero la frase ya no puede
  ser «lo elimina».

También: el conteo de escaladas forzadas, que **es la métrica 3 empezada** y sale
gratis con cada corrida; y una sonda del umbral que metía la toma de sala en el
lote de voz.

---

## PR 2 — `feature/transfer-guard-coverage` → `main` (11 commits)

**Título:** El esquema que mentía sobre su propia herramienta, y el cuarto hueco
del cepo literal

**Cuerpo:**

### El resultado

Tres corridas de la huella `acf3cbc7`: **mediana 9/12, rango 7–9**. Los dos
cambios del 28/09 recuperan los 2 puntos que costó el arreglo del orden **sin
devolver lo que el orden compró**.

| huella | qué es | mediana | rango |
|---|---|---|---|
| `c7815dae` | fuga cerrada | 9/12 | 9–9 |
| `00a2543d` | + orden de verificación | 7/12 | 7–7 |
| `7a0202aa` | + guardia | 8/12 | 6–9 |
| **`acf3cbc7`** | **+ enclítico + prompt del porqué + esquema** | **9/12** | **7–9** |

Dos de los cuatro casos "inestables" **no lo son del agente, son del reloj**: se
les acabó el presupuesto del turno y se quedaron sin desenlace; donde el agente
llegó a decidir, los acierta.

### Lo que va dentro

**El guardia ya caza el pronombre enclítico.** «Voy a transferir**le**» no casaba
—todas las formas exigían el pronombre delante— y en español, con infinitivo, lo
natural es pegarlo detrás. Se admite **solo detrás de «voy a»**, que es afirmativo
por construcción: suelto haría que «no puedo transferirle» abriera un ticket que
nadie pidió. La prueba lleva la frase real y cinco formas que el modelo aún no ha
dicho.

**El agente vuelve a decir POR QUÉ pide el nombre.** Había dejado de hacerlo con
el arreglo del orden, y eran exactamente los 2 puntos perdidos. Se leyó al
principio como un hueco del clasificador y **no lo era**: sus fixtures seguían
pasando. Ahora los dos casos aciertan 3 de 3.

**El esquema mentía sobre su propia herramienta.** Declaraba `nombre_declarado`
como `"string"` mientras el servicio ya aceptaba `null`. La verificación va en
dos pasos y el primero no lleva nombre, así que el modelo **tiene** que poder
decir «todavía no lo tengo» — y Groq rechazaba la petición entera con un 400. El
agente salía escalando: **un fallo del proveedor contado como decisión del
agente.** Contaminó 2 corridas antes de verse. Pedirle al modelo que nunca mande
`null` es una petición; aceptarlo es una garantía.

**Y la comprobación que faltaba:** nadie miraba si el esquema anunciado y la
herramienta decían lo mismo. Ahora se comparan campo por campo, y a la primera
encontró un segundo desacuerdo que **sí debe existir**: `clave_idempotencia` la
pone el bucle y el modelo no puede ponerla —si pudiera, reutilizaría la clave de
otro turno—. La protección del ADR 0007 dependía de eso y nadie lo comprobaba.

### Lo que NO va dentro, a propósito

**El cuarto hueco del guardia.** El 29/09 el agente dijo «permítame
transferirle» y el guardia no disparó. Estaba escrito como eje pendiente en
`fundamento.py` el día anterior y se cumplió a la corrida siguiente. **No se
parchea**: van tres parches a la misma expresión en tres días y el cuarto
aplazaría el problema en vez de arreglarlo. El arreglo de fondo —que la intención
de transferir no se busque en el texto— está nombrado en el ADR 0010 y no está
diseñado.

### Documentación

ADR 0010, README al día (el reservado medido, la segunda voz, quince mediciones
falsas, y las dos tablas que publicaban números ya caídos con su aviso al lado) y
`docs/demo.md`, el guion para grabar la demo en una sentada.
