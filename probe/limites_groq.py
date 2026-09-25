"""¿Qué límites tiene esta cuenta de Groq, y quedan cerca?

Existe por una sospecha concreta: en las mediciones del modelo aparece una
meseta de ~2,7 s que no se parece a la varianza de inferencia. Las muestras
salen bimodales —trece por debajo de 705 ms y dos en torno a 3 s— y eso tiene
pinta de cola, no de modelo lento.

Antes de culpar al modelo o de pagar un plan, se le pregunta al servidor.
Groq devuelve los límites en las cabeceras de cada respuesta.

## Por qué esta sonda mentía por omisión (2026-09-24)

Las cabeceras traen **solo los límites por minuto**: `limit-tokens: 8000`. El
que de verdad para el trabajo no sale ahí. El 24/09 las evaluaciones empezaron
a fallar con 429 mientras esta sonda decía tranquilamente que quedaban 7920
tokens, y el diagnóstico fue equivocado tres veces seguidas —"es el límite por
minuto, espaciando las corridas se arregla"— hasta que se leyó el cuerpo del
error:

    Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199919

**200 000 tokens**, y no aparece en ninguna cabecera. Una sonda que enseña los
límites que no importan y calla el que manda es peor que no tener sonda, porque
da confianza. Así que ahora, además de las cabeceras, se hace una petición del
tamaño de las de verdad —con el prompt del sistema y las herramientas— y si el
servidor la rechaza, se enseña **qué límite** fue, cuánto se ha gastado y cuándo
se recupera.

## Y por qué seguía mintiendo, de otra manera (2026-09-25)

Dos cosas más, y las dos costaron caro:

**No es «al día», es una ventana deslizante de 24 horas.** El mensaje del 429 lo
dice sin querer: `Used 199423 ... Please try again in 1m9.12s`. Si el contador se
pusiera a cero a medianoche no habría nada que reintentar en 69 segundos; lo que
se libera en ese minuto y pico es el gasto de ayer a esta misma hora saliendo de
la ventana. Minutos después, una petición que pedía 60 000 tokens pasaba. De
creer que era un día calendario salió la idea de que «hoy la cuota está
renovada», y la mañana del 25/09 no estaba renovada: arrastraba ~51 000 tokens
del día anterior.

**Y «pasa. Hay cuota para medir» era la frase peligrosa.** Que UNA petición pase
no dice nada de si caben cinco corridas de una medición: el 25/09 esta sonda
respondió eso y la siguiente corrida murió a mitad con `Used 199423` de 200 000.
Si ese día se hubiera elegido medir el reservado, se habría gastado a medias.
Así que ahora la sonda consulta el libro de `app/evaluation/cuota.py`, dice
cuánto queda de la ventana y **cuándo cabría una medición entera**, y no vuelve a
decir que hay cuota para medir por el hecho de que una petición pase.
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import cargar_env  # noqa: E402

from groq import Groq  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.agent.loop import HERRAMIENTAS, SISTEMA  # noqa: E402
from app.evaluation import cuota  # noqa: E402
from app.evaluation.particion import calibracion  # noqa: E402

entorno = cargar_env()
# Sin reintentos: aquí lo que se busca es justamente el rechazo. Con reintentos
# el SDK se lo come por dentro y la sonda no se enteraría de nada.
cliente = Groq(api_key=entorno["GROQ_API_KEY"].strip(), max_retries=0)
modelo = entorno.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

print(f"modelo: {modelo}\n")

respuesta = cliente.chat.completions.with_raw_response.create(
    model=modelo,
    messages=[{"role": "user", "content": "di solo: hola"}],
    max_tokens=5,
)

print("  cabeceras (SOLO llevan los límites por minuto):")
interesantes = [c for c in respuesta.headers if "ratelimit" in c.lower()
                or "retry" in c.lower()]
if not interesantes:
    print("    el servidor no devolvió cabeceras de límite.")
for cabecera in sorted(interesantes):
    print(f"    {cabecera}: {respuesta.headers[cabecera]}")

# Y ahora una del tamaño de las de verdad. Las de la evaluación llevan el
# prompt del sistema, las tres herramientas y varios turnos de historia: son
# dos órdenes de magnitud más grandes que un "di hola", y el límite diario solo
# se ve cuando alguien pide de verdad.
print("\n  una petición del tamaño real (prompt del sistema + herramientas):")
try:
    cliente.chat.completions.create(
        model=modelo,
        messages=[{"role": "system", "content": SISTEMA},
                  {"role": "user", "content": "Hola, mi cédula es 1070234567"}],
        tools=HERRAMIENTAS, tool_choice="auto", max_tokens=400,
        reasoning_effort="low",
    )
    print("    pasa: una petición del tamaño real entra.")
    print("    OJO: esto NO dice que haya sitio para una medición entera. El "
          "25/09 dijo justo esto y la corrida siguiente murió a mitad.")
except Exception as exc:  # noqa: BLE001
    texto = str(exc)
    print(f"    RECHAZADA: {type(exc).__name__}")
    cual = re.search(r"on (tokens per day \(TPD\)|tokens per minute \(TPM\)|"
                     r"requests per day \(RPD\)|requests per minute \(RPM\))",
                     texto)
    gastado = re.search(r"Limit (\d+), Used (\d+)", texto)
    cuando = re.search(r"try again in ([\dhms.]+)", texto)
    if cual:
        print(f"    el límite que manda: {cual.group(1)}")
    if gastado:
        limite, usado = int(gastado.group(1)), int(gastado.group(2))
        print(f"    gastado: {usado} de {limite} "
              f"({100 * usado / limite:.1f}%)")
    if cuando:
        print(f"    se recupera en: {cuando.group(1)}")
    if not (cual or gastado):
        print(f"    {texto[:300]}")
    if gastado:
        # El `Used` del 429 es la única cifra real del gasto de la ventana. Ya
        # que ha costado un rechazo, se aprovecha para poner el libro al día.
        desajuste = cuota.corregir_con_429(texto)
        if desajuste:
            print(f"    el libro no veía {desajuste} de esos tokens: anotados")
    print("\n    Es una VENTANA DESLIZANTE de 24 h, no un día calendario, así "
          "que esperar SÍ sirve: el gasto sale de la ventana 24 h después de "
          "hacerse. Y no aparece en ninguna cabecera, así que la parte de "
          "arriba seguirá diciendo que queda cuota de sobra.")

# --------------------------------------------- lo que el libro sabe de la ventana
print("\n  la ventana de 24 h, según el libro de app/evaluation/cuota.py:")
if cuota.libro_ciego():
    print("    NI UN APUNTE. Eso no significa que la ventana esté limpia: "
          "significa que el libro no sabe.")
    print("    Si acabas de añadir el libro a un proyecto que ya venía "
          "gastando, siémbralo: probe\\sembrar_libro_cuota.py --rehacer")
else:
    apuntes = cuota.entradas()
    print(f"    {cuota.gastado()} tokens gastados de {cuota.LIMITE_VENTANA} en "
          f"{len(apuntes)} apunte(s), quedan ~{cuota.disponible()}")
    print(f"    el apunte más viejo sale de la ventana a las "
          f"{time.strftime('%H:%M del %d/%m', time.localtime(apuntes[0]['cuando'] + cuota.VENTANA_S))}")
    print("    (es una cota OPTIMISTA: el libro solo ve lo que pasa por el "
          "código instrumentado)")

# Y la pregunta que de verdad importa antes de tocar el reservado.
RESERVADO_K5 = 89_250  # 8 casos, 14 turnos, k=5, a 1275 tokens/turno (25/09)
for cuantos, que in ((cuota.estimar(calibracion()), "una corrida de calibración"),
                     (RESERVADO_K5, "la medición final del reservado (k=5)")):
    con_margen = int(cuantos * 1.5)
    espera = cuota.espera_para(con_margen)
    if espera == 0:
        cuando = "CABE ahora"
    elif espera is None:
        cuando = "no cabe en una ventana entera"
    else:
        cuando = (f"cabrá dentro de {espera / 3600:.1f} h, sobre las "
                  f"{time.strftime('%H:%M', time.localtime(time.time() + espera))}")
    print(f"    {que}: ~{cuantos} tokens (~{con_margen} con margen) -> {cuando}")
