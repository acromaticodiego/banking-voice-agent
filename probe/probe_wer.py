r"""Métrica 4: tasa de error de transcripción en español, con acento paisa.

Se mide sobre las grabaciones de lectura, que son las únicas que tienen verdad
escrita. Las espontáneas no sirven aquí: nadie sabe palabra por palabra qué se
dijo en ellas, y una referencia inventada a posteriori no es una referencia.

Se dan **tres números**, y los tres hacen falta:

  · `literal` — palabra contra palabra, solo quitando mayúsculas y puntuación.
    Castiga que el sistema escriba "1070234567" donde la referencia dice "uno
    cero siete cero...". Son diez errores por acertar.

  · `normalizado` — con los números pasados a cifras en los dos lados. Es la
    cifra honesta de comprensión, y es la que se publica.

  · `datos` — de los números que importan (documento, importe, tarjeta),
    cuántos se recuperan exactos. Un sistema puede tener un 15% de error de
    palabra y acertar el 100% de los documentos, o al revés, y para una
    verificación de identidad lo segundo es lo único que decide.

La tasa de error es la distancia de edición entre listas de palabras, dividida
por el número de palabras de la referencia: la definición de siempre.

Uso:  .\.venv\Scripts\python.exe probe\probe_wer.py [--modelo small]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ARTEFACTOS, Medicion, guardar  # noqa: E402
from numeros_es import normalizar, sin_tildes  # noqa: E402
from linea_telefonica import a_linea_telefonica  # noqa: E402
from probe_whisper_local import cargar_modelo, leer_wav  # noqa: E402


def limpiar(texto: str) -> list[str]:
    """Minúsculas, sin puntuación. Las tildes SE MANTIENEN: comerse una tilde
    es un error de verdad en español y no hay por qué perdonarlo."""
    texto = texto.lower().replace("...", " ")
    texto = re.sub(r"[^\wáéíóúüñ\s]", " ", texto)
    return texto.split()


def distancia(referencia: list[str], hipotesis: list[str]) -> int:
    """Distancia de edición entre dos listas de palabras."""
    anterior = list(range(len(hipotesis) + 1))
    for i, palabra_ref in enumerate(referencia, start=1):
        actual = [i]
        for j, palabra_hip in enumerate(hipotesis, start=1):
            actual.append(min(
                anterior[j] + 1,                                        # borrar
                actual[j - 1] + 1,                                      # insertar
                anterior[j - 1] + (palabra_ref != palabra_hip),         # sustituir
            ))
        anterior = actual
    return anterior[-1]


def tasa(referencia: str, hipotesis: str) -> tuple[float, int, int]:
    ref, hip = limpiar(referencia), limpiar(hipotesis)
    errores = distancia(ref, hip)
    return (errores / len(ref) if ref else 0.0), errores, len(ref)


def cifras(texto: str) -> list[str]:
    """Los números que hay en el texto, ya en cifras."""
    return re.findall(r"\d+", normalizar(sin_tildes(texto.lower())))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="small")
    # La tasa de error del proyecto esta medida con un microfono de portatil en
    # una habitacion callada, a 16 kHz y con todo el espectro. Nada de eso
    # llega por telefono, asi que ese numero no es optimista: es de otro
    # problema. Con esto se pasa el MISMO audio por la banda de 300-3400 Hz, se
    # muestrea a 8 kHz y se cuantiza en mu-law, que es lo que hace una linea.
    parser.add_argument("--linea-telefonica", action="store_true",
                        help="pasa el audio por el canal de una llamada antes "
                             "de transcribirlo")
    args = parser.parse_args()
    canal = "linea telefonica (300-3400 Hz, 8 kHz, mu-law)" if args.linea_telefonica else "microfono, 16 kHz"

    muestras = []
    for json_ruta in sorted(ARTEFACTOS.glob("muestra-*.json")):
        datos = json.loads(json_ruta.read_text(encoding="utf-8"))
        verdad = datos.get("transcripcion_verdadera")
        wav = ARTEFACTOS / datos["fichero"]
        if verdad and wav.exists():
            muestras.append((datos["fichero"], verdad, wav))

    if not muestras:
        print("No hay grabaciones de lectura con transcripción verdadera.",
              file=sys.stderr)
        return 2

    print(f"Cargando faster-whisper '{args.modelo}'...")
    modelo, dispositivo, _, _ = cargar_modelo(args.modelo)
    print(f"  {dispositivo}\n")

    literal = Medicion(
        etapa="wer", implementacion=f"faster-whisper {args.modelo} ({dispositivo}) [literal]",
        que_mide="errores de palabra sobre palabras de la referencia, sin tocar los números",
        unidad="%",
        notas="Castiga escribir 1070234567 donde la referencia dice las cifras en letra.",
    )
    normal = Medicion(
        etapa="wer", implementacion=f"faster-whisper {args.modelo} ({dispositivo}) [normalizado]",
        que_mide="lo mismo, con los números pasados a cifras en los dos lados",
        unidad="%",
    )

    aciertos_datos = fallos_datos = 0
    for fichero, verdad, wav in muestras:
        audio, frecuencia, _dur = leer_wav(wav)
        if args.linea_telefonica:
            audio = a_linea_telefonica(audio, frecuencia)
        segmentos, _ = modelo.transcribe(audio, language="es", beam_size=5)
        dicho = "".join(s.text for s in segmentos).strip()

        t_lit, e_lit, n_lit = tasa(verdad, dicho)
        t_nor, e_nor, n_nor = tasa(normalizar(verdad), normalizar(dicho))
        literal.muestras_ms.append(t_lit * 100)
        normal.muestras_ms.append(t_nor * 100)

        esperadas, obtenidas = cifras(verdad), cifras(dicho)
        for numero in esperadas:
            if numero in obtenidas:
                aciertos_datos += 1
            else:
                fallos_datos += 1

        print(f"{fichero}")
        print(f"  referencia : {verdad}")
        print(f"  transcrito : {dicho}")
        print(f"  literal     {t_lit * 100:5.1f}%  ({e_lit} errores sobre {n_lit} palabras)")
        print(f"  normalizado {t_nor * 100:5.1f}%  ({e_nor} errores sobre {n_nor} palabras)")
        print(f"  números     esperados {esperadas} / obtenidos {obtenidas}")
        print()

    total_datos = aciertos_datos + fallos_datos
    print("Resultado:")
    print(literal.linea().replace("ms", " %"))
    print(normal.linea().replace("ms", " %"))
    if total_datos:
        print(f"  datos  números recuperados exactos: {aciertos_datos}/{total_datos} "
              f"({aciertos_datos / total_datos * 100:.0f}%)")

    print(f"\nTamaño de muestra: {len(muestras)} grabaciones de una sola persona, por {canal}.")
    print("Calibra el orden de magnitud. NO es una tasa de error representativa:")
    print("para eso harían falta varias voces, ruido de fondo y línea telefónica.")

    normal.notas = (f"{len(muestras)} grabaciones, un solo hablante, sin ruido, "
                    f"por {canal}. "
                    f"Números recuperados exactos: {aciertos_datos}/{total_datos}.")
    literal.notas += f" Canal: {canal}."
    sufijo = "-telefono" if args.linea_telefonica else ""
    destino = guardar([normal, literal], f"wer-{args.modelo}{sufijo}")
    print(f"\nGuardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
