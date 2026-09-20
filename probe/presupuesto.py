"""Suma las etapas medidas y dice si el turno cabe en 800 ms.

Lee los JSON más recientes de `artifacts/` y compone el presupuesto según el
ADR 0001:

    turno = fin_de_habla + asr_final + primer_token + primer_byte_de_audio

Dos avisos que van impresos en la salida a propósito, para que nadie cite el
número sin ellos:

  · `fin_de_habla` NO está medido. Es una suposición declarada, porque depende
    de un detector que todavía no existe y de un umbral que se decidirá sobre
    datos en otro ADR. Se pasa por parámetro y sale escrito en el informe.
  · El resultado es un límite inferior de lo que percibe quien llama: no
    incluye el viaje del audio por la red ni el tramo de reproducción.

Los p95 no se suman: sumar percentiles da un número que no es el p95 de la
suma, y además es pesimista porque supone que todas las etapas tienen su mal
día a la vez. Se suman y se etiquetan como "peor caso por etapas", que es lo
que son.

Uso:  python probe/presupuesto.py [--fin-de-habla-ms 400]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ARTEFACTOS

OBJETIVO_MS = 800


def ultimo(patron: str) -> dict | None:
    ficheros = sorted(ARTEFACTOS.glob(f"{patron}-*.json"))
    if not ficheros:
        return None
    return json.loads(ficheros[-1].read_text(encoding="utf-8"))


def elegir(informe: dict | None, contiene: str, excluye: str = "(total)") -> dict | None:
    """Saca del informe la medición cuya implementación contenga `contiene`."""
    if not informe:
        return None
    candidatas = [
        m for m in informe["mediciones"]
        if contiene in m["implementacion"] and excluye not in m["implementacion"]
        and not m.get("error") and m["resumen"]["n"] > 0
    ]
    return candidatas[0] if candidatas else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fin-de-habla-ms", type=float, default=400.0,
                        help="suposición declarada, no medida: cuánto tarda el detector "
                             "de fin de habla en decidir que la persona calló")
    parser.add_argument("--voz", default="es_MX-claude-high")
    parser.add_argument("--llm", default="prompt=corto",
                        help="qué configuración del modelo entra en el presupuesto")
    parser.add_argument("--modelo-asr", default="small")
    args = parser.parse_args()

    etapas = []
    faltan = []

    etapas.append({
        "etapa": "fin de habla",
        "fuente": "SUPOSICIÓN, no medida",
        "p50": args.fin_de_habla_ms,
        "p95": args.fin_de_habla_ms,
        "detalle": "umbral de silencio por decidir sobre datos (ADR pendiente)",
    })

    asr = elegir(ultimo(f"whisper-{args.modelo_asr}"), "cola 2s")
    if asr:
        etapas.append({"etapa": "voz a texto (cola)", "fuente": asr["implementacion"],
                       "p50": asr["resumen"]["p50"], "p95": asr["resumen"]["p95"],
                       "detalle": asr["que_mide"]})
    else:
        faltan.append("voz a texto: ejecuta probe/probe_whisper_local.py")

    # Se pide la configuración por su nombre completo: desde que se miden
    # varias a la vez, coger "la primera que encaje" dependía del orden del
    # fichero y podía meter en el presupuesto una que no se eligió.
    informe_llm = ultimo("groq")
    llm = elegir(informe_llm, f"{args.llm} [herramienta]")
    if llm:
        etapas.append({"etapa": "modelo (primer token)", "fuente": llm["implementacion"],
                       "p50": llm["resumen"]["p50"], "p95": llm["resumen"]["p95"],
                       "detalle": llm["que_mide"]})
    else:
        faltan.append("modelo: ejecuta probe/probe_groq.py")

    tts = elegir(ultimo("piper"), args.voz)
    if tts:
        etapas.append({"etapa": "texto a voz (primer trozo)", "fuente": tts["implementacion"],
                       "p50": tts["resumen"]["p50"], "p95": tts["resumen"]["p95"],
                       "detalle": tts["que_mide"]})
    else:
        faltan.append("texto a voz: ejecuta probe/probe_piper.py")

    print("PRESUPUESTO DEL TURNO (ADR 0001)")
    print("=" * 72)
    print(f"{'etapa':<28}{'p50 ms':>10}{'p95 ms':>10}   fuente")
    print("-" * 72)
    for e in etapas:
        print(f"{e['etapa']:<28}{e['p50']:>10.1f}{e['p95']:>10.1f}   {e['fuente']}")
    print("-" * 72)

    if faltan:
        print("\nINCOMPLETO. Falta medir:")
        for f in faltan:
            print(f"  · {f}")
        print("\nNo doy veredicto con etapas sin medir.")
        return 1

    suma50 = sum(e["p50"] for e in etapas)
    suma95 = sum(e["p95"] for e in etapas)
    print(f"{'TOTAL':<28}{suma50:>10.1f}{suma95:>10.1f}")
    print(f"{'objetivo':<28}{OBJETIVO_MS:>10}{OBJETIVO_MS:>10}")
    print(f"{'margen':<28}{OBJETIVO_MS - suma50:>10.1f}{OBJETIVO_MS - suma95:>10.1f}")

    print("\nVeredicto:")
    if suma95 <= OBJETIVO_MS:
        print(f"  Cabe. Incluso en el peor caso por etapas quedan "
              f"{OBJETIVO_MS - suma95:.0f} ms de margen.")
    elif suma50 <= OBJETIVO_MS:
        print(f"  Cabe en el caso típico ({suma50:.0f} ms) pero no en el peor caso por "
              f"etapas ({suma95:.0f} ms). Hay que recortar donde más pese.")
    else:
        print(f"  NO cabe: {suma50:.0f} ms en el caso típico contra {OBJETIVO_MS} ms de "
              f"objetivo. Hay que cambiar el enfoque, no afinarlo.")

    print("\nLo que este número NO incluye, y hay que decirlo al citarlo:")
    print("  · el viaje del audio por la red en los dos sentidos")
    print("  · el tiempo de reproducción en el auricular")
    print(f"  · el fin de habla es una suposición de {args.fin_de_habla_ms:.0f} ms, "
          "no una medición")
    print("  · el p95 de la suma no es la suma de los p95: la columna p95 es el peor")
    print("    caso por etapas, que supone que todas fallan a la vez")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
