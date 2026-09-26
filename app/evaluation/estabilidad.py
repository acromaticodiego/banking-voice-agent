r"""Cuánto de un resultado es el agente y cuánto es la tirada de dados.

Existe por un susto del 2026-09-23. Tres corridas seguidas del mismo conjunto
de 12 casos, el mismo modelo, el mismo día, dieron 6, 5 y 7 aciertos. Ninguna
mentía: cada una era una medición correcta de una sola tirada. Pero decir "el
agente saca 7 de 12" con eso es lo mismo que tirar un dado una vez y decir que
el dado vale 4.

Lo que hace este módulo no cuesta ni una petición: relee lo que quedó guardado
de cada corrida y **lo reclasifica con el clasificador de hoy**. Eso importa
más de lo que parece. Las corridas de una tarde se hacen con clasificadores
distintos, porque el clasificador también se arregla por el camino; comparar
sus `obtenido` tal cual mezcla dos variables y no se puede saber cuál movió el
número. Reclasificando, la única variable que queda es el agente.

  .\.venv\Scripts\python.exe -m app.evaluation.estabilidad
  .\.venv\Scripts\python.exe -m app.evaluation.estabilidad --casos 8   # reservado

Para la medición final del reservado esto no es un adorno: **un caso inestable
que cae del lado bueno vale lo mismo en la tabla que uno que el agente resuelve
siempre**, y son cosas distintas. La medición honesta del reservado son varias
corridas, con la mediana y el rango, y decidido ANTES de quemarlo.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.agent.fundamento import revisar
from app.evaluation.catalogo import por_id
from app.evaluation.correr import acierta, clasificar

RAIZ = Path(__file__).resolve().parents[2]


def sin_fundamento(datos: dict) -> str:
    """Cuántos casos de esa corrida dijeron algo que no les constaba.

    Se recalcula aquí en vez de leer el campo guardado, por la misma razón que
    los desenlaces se reclasifican: el detector también se arregla por el
    camino, y comparar corridas con dos versiones suyas mezcla variables. Con
    el de hoy, todas se miden igual.

    Las corridas de antes del 2026-09-24 no guardaban lo que devolvieron las
    herramientas. Sin esas fuentes, el detector daría por inventado cualquier
    número que el agente leyó correctamente, así que no se calcula y se dice.
    """
    if not all("resultados" in r for r in datos["resultados"]):
        return "sin fundamento: no medible (no se guardaron las herramientas)"
    marcados = 0
    for r in datos["resultados"]:
        revision = revisar(r["dijo"], r["resultados"],
                           por_id(r["id"]).turnos, r["herramientas"])
        marcados += 0 if revision.limpio else 1
    return f"sin fundamento: {marcados}/{datos['total']}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quien", default="agente",
                        choices=["agente", "base"])
    parser.add_argument("--conjunto", default="calibracion",
                        choices=["calibracion", "reservado"])
    parser.add_argument("--casos", type=int, default=None,
                        help="solo las corridas con este número de casos. Sin "
                             "esto se mezclarían corridas de conjuntos de "
                             "tamaños distintos, que no son comparables.")
    parser.add_argument("--prompt", choices=["actual", "anterior"],
                        default=None,
                        help="solo las corridas con esta versión del prompt")
    parser.add_argument("--version", default=None,
                        help="solo las corridas hechas con esta versión del "
                             "agente: la huella (app/agent, app/tools, catálogo "
                             "y partición) o «commit <corto>» para las que no "
                             "la tengan. Acepta varias separadas por coma, y "
                             "eso significa que HAS COMPROBADO con git "
                             "rev-parse que son el mismo agente")
    parser.add_argument("--desde", default=None,
                        help="solo las corridas guardadas desde esta fecha "
                             "(AAAAMMDD). Hace falta porque «sin anotar» mete "
                             "en el mismo saco todas las corridas anteriores al "
                             "2026-09-25, y esas sí son de agentes distintos: "
                             "el 24/09 cambiaron el turno vacío y los tres "
                             "intentos de documento")
    parser.add_argument("--presupuesto-ms", type=float, default=None,
                        help="solo las corridas con este reloj de turno")
    parser.add_argument("--incluir-contaminadas", action="store_true",
                        help="incluir corridas con fallos del proveedor. Por "
                             "defecto se descartan: un 429 hace que el agente "
                             "salga escalando, así que el desenlace no es suyo")
    args = parser.parse_args()

    patron = f"evaluacion-{args.conjunto}-{args.quien}-*.json"
    corridas = []
    # Una corrida con 429 del proveedor NO es una corrida mala: es una corrida
    # de otra cosa. El agente sale de un fallo del modelo escalando a un
    # humano, así que esos casos tienen un desenlace que él no decidió, y
    # promediarlos con los buenos baja la mediana y sube la inestabilidad sin
    # que nada de eso sea del agente. Pasó el 2026-09-24: una corrida con 22
    # fallos dio 3/12 y se habría colado en la comparación de los prompts.
    contaminadas = 0
    for fichero in sorted((RAIZ / "artifacts").glob(patron)):
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        if args.casos and datos["total"] != args.casos:
            continue
        # La fecha sale del nombre del fichero, no del `mtime`: un git checkout
        # o una copia cambian el mtime y no cambian el nombre.
        if args.desde:
            marca = fichero.stem.split("-")[-2:]
            if not marca or marca[0] < args.desde:
                continue
        # Las corridas de antes del 2026-09-24 no guardaban ni el prompt ni el
        # presupuesto, así que se etiquetan con lo que eran entonces: el prompt
        # de antes y el reloj de 3000 ms. Inventarles un "desconocido" las
        # dejaría fuera de toda comparación, y describirlas mal sería peor.
        prompt = datos.get("prompt", "anterior")
        presupuesto = datos.get("presupuesto_ms", 3000.0)
        if args.prompt and prompt != args.prompt:
            continue
        if args.presupuesto_ms and presupuesto != args.presupuesto_ms:
            continue
        if args.version:
            version = (datos.get("huella_agente")
                       or f"commit {datos.get('commit', 'sin anotar')}")
            if version not in [v.strip() for v in args.version.split(",")]:
                continue
        if datos.get("incidencias") and not args.incluir_contaminadas:
            contaminadas += 1
            continue
        corridas.append((fichero.name, datos))

    if contaminadas:
        print(f"({contaminadas} corrida(s) descartadas por llevar fallos del "
              f"proveedor. --incluir-contaminadas para verlas de todos modos)\n")

    if not corridas:
        print(f"No hay corridas guardadas que encajen con {patron}"
              + (f" y {args.casos} casos" if args.casos else ""))
        return 1

    tamanos = {d["total"] for _, d in corridas}
    if len(tamanos) > 1:
        # Mezclar un conjunto de 6 con uno de 12 da una media que no es de
        # nada. Se dice y se sale, en vez de imprimir un número inventado.
        print(f"Hay corridas de tamaños distintos: {sorted(tamanos)}. "
              f"Usa --casos N para quedarte con uno.")
        return 1

    # Lo mismo con las condiciones: el 2026-09-24 el prompt se alargó y el
    # reloj del turno se relajó, y las dos cosas mueven el número. Tres
    # corridas de un brazo y tres del otro, metidas en el mismo saco, dan una
    # mediana de nada con una estabilidad falsa. Mejor negarse que promediar.
    #
    # Y la versión de lo medido, que faltaba y es la que más duele. El
    # 2026-09-25 esta misma llamada mezcló tres corridas del 24/09 con dos del
    # 25/09 y dio una mediana de 8/12 sin decir una palabra: el prompt y el
    # presupuesto coincidían, pero el agente de en medio había cambiado dos
    # veces (el turno vacío y los tres intentos de documento).
    #
    # Se compara la HUELLA del agente y no el commit, y la diferencia importó a
    # las pocas horas de escribir esto. El 26/09 las tres corridas limpias
    # salieron con dos commits distintos —los de en medio arreglaron el libro de
    # la cuota y el canario, o sea el instrumento— y el agente era byte por byte
    # el mismo. Comparar por commit las habría separado por un motivo
    # equivocado: acierta en la dirección segura, pero bloquea una comparación
    # legítima. La huella cubre app/agent, app/tools, el catálogo y la
    # partición, que es lo que de verdad participa en el resultado.
    # Pasar varias versiones a `--version` es declarar «he comprobado que son el
    # mismo agente», así que la dimensión se colapsa a propósito y se avisa más
    # abajo. La alternativa —negarse igual— obligaría a no poder comparar nunca
    # corridas legítimas separadas por un commit que solo tocó una sonda.
    declaradas_iguales = bool(args.version and "," in args.version)

    def version_de(d: dict) -> str:
        if declaradas_iguales:
            return f"varias, declaradas iguales: {args.version}"
        return d.get("huella_agente") or f"commit {d.get('commit', 'sin anotar')}"

    condiciones = {(d.get("prompt", "anterior"),
                    d.get("presupuesto_ms", 3000.0),
                    version_de(d)) for _, d in corridas}
    if len(condiciones) > 1:
        print("Estas corridas no se hicieron en las mismas condiciones:")
        for prompt, presupuesto, version in sorted(condiciones):
            print(f"    prompt {prompt}, presupuesto {presupuesto:.0f} ms, "
                  f"agente {version}")
        print("  Filtra con --prompt, --presupuesto-ms y --version. "
              "Promediarlas daría una mediana de dos experimentos distintos y "
              "una tabla de estabilidad que mide el cambio de condiciones, no "
              "al agente.")
        if any("sin anotar" in v for _, _, v in condiciones):
            print("  Las corridas anteriores al 2026-09-25 no guardaban con qué "
                  "agente se midieron y salen como «sin anotar».")
        print("\n  Si has COMPROBADO que son el mismo agente, pásalas juntas: "
              "--version \"a,b\". La comprobación es esta, y hay que hacerla, no "
              "suponerla:")
        for camino in ("app/agent", "app/tools", "app/evaluation/catalogo.py",
                       "app/evaluation/particion.py"):
            print(f"      git rev-parse <commitA>:{camino} <commitB>:{camino}")
        return 1

    tabla: dict[str, list[str]] = defaultdict(list)
    for _, datos in corridas:
        for r in datos["resultados"]:
            obtenido = clasificar(r["dijo"], r["herramientas"])
            # Se juzga con la rúbrica del catálogo de HOY, no con el `esperado`
            # que guardó la corrida, por lo mismo que se reclasifica: si la
            # rúbrica cambió, comparar corridas con dos rúbricas distintas
            # mezcla variables.
            tabla[r["id"]].append("OK" if acierta(por_id(r["id"]), obtenido)
                                  else obtenido)

    n = len(corridas)
    prompt, presupuesto, version = condiciones.pop()
    print(f"{args.quien} sobre {args.conjunto}: {n} corrida(s) de "
          f"{tamanos.pop()} casos, prompt {prompt}, presupuesto "
          f"{presupuesto:.0f} ms, agente {version}, reclasificadas con el "
          f"clasificador de hoy\n")
    if "sin anotar" in version:
        print("  AVISO: estas corridas no guardaron con qué versión del agente "
              "se midieron, así que pueden ser de agentes distintos. Las de "
              "aquí en adelante sí lo guardan.\n")
    if args.version and "," in args.version:
        print(f"  Se están juntando {len(args.version.split(','))} versiones "
              f"porque quien llamó lo pidió explícitamente: {args.version}.")
        print("  Eso vale SOLO si se comprobó con git rev-parse que el agente "
              "es el mismo. Si no se comprobó, este número mezcla dos "
              "experimentos.\n")
    for nombre, datos in corridas:
        print(f"    {nombre}   {sin_fundamento(datos)}")
    print()

    estables, inestables = [], []
    for identificador, vueltas in tabla.items():
        siempre = len(set(vueltas)) == 1
        (estables if siempre else inestables).append(identificador)
        print(f"  {'estable  ' if siempre else 'INESTABLE'} "
              f"{identificador:<34} {vueltas}")

    por_corrida = [sum(1 for c in tabla if tabla[c][i] == "OK")
                   for i in range(n)]
    print(f"\n  aciertos por corrida : {por_corrida}")
    if n > 1:
        print(f"  mediana              : {statistics.median(por_corrida):g}"
              f"/{len(tabla)}")
        print(f"  rango                : {min(por_corrida)}-{max(por_corrida)}")
    print(f"  estables             : {len(estables)}/{len(tabla)}")
    print(f"  inestables           : {len(inestables)}/{len(tabla)}"
          + (f"  -> {sorted(inestables)}" if inestables else ""))
    if n == 1:
        print("\n  UNA SOLA CORRIDA. No hay forma de saber qué parte de esto "
              "es el agente y qué parte es la temperatura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
