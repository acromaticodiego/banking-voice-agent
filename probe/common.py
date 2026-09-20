"""Utilidades compartidas por las sondas de latencia.

Existe por una regla del proyecto: *todo número va con su tamaño de muestra, su
procedencia y la fecha*. Si cada sonda imprimiera sus milisegundos por su
cuenta acabaríamos con cifras sueltas que nadie puede auditar tres semanas
después. Aquí se obliga a que cada medición lleve su contexto pegado.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARTEFACTOS = RAIZ / "artifacts"


def percentil(muestras: list[float], p: float) -> float:
    """Percentil por interpolación lineal.

    Implementado a mano y no con numpy para que la sonda pueda ejecutarse en un
    entorno mínimo: la primera medición no debería depender de instalar medio
    ecosistema científico.
    """
    if not muestras:
        raise ValueError("no hay muestras para calcular el percentil")
    ordenadas = sorted(muestras)
    if len(ordenadas) == 1:
        return ordenadas[0]
    posicion = (len(ordenadas) - 1) * p
    bajo = int(posicion)
    alto = min(bajo + 1, len(ordenadas) - 1)
    peso = posicion - bajo
    return ordenadas[bajo] * (1 - peso) + ordenadas[alto] * peso


def describe_host() -> dict:
    """Procedencia de la medición: en qué máquina salieron estos números."""
    gpu = "no detectada"
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if salida.returncode == 0 and salida.stdout.strip():
            gpu = salida.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "sistema": f"{platform.system()} {platform.release()}",
        "procesador": platform.processor(),
        "python": sys.version.split()[0],
        "gpu": gpu,
    }


@dataclass
class Medicion:
    """Una etapa medida n veces, con todo lo necesario para discutir el número.

    `muestras_ms` guarda los valores crudos y no solo el resumen: un p95 sobre
    cinco muestras no significa lo mismo que sobre cincuenta, y quien lea esto
    después tiene derecho a recalcularlo.
    """

    etapa: str                 # "asr", "llm", "tts"
    implementacion: str        # "faster-whisper small (GPU)", "groq llama-3.1-8b-instant"
    que_mide: str              # la frase exacta de qué instante a qué instante
    muestras_ms: list[float] = field(default_factory=list)
    unidad: str = "ms"
    notas: str = ""
    coste_usd: float | None = None
    error: str | None = None

    @property
    def n(self) -> int:
        return len(self.muestras_ms)

    def resumen(self) -> dict:
        if not self.muestras_ms:
            return {"n": 0, "p50": None, "p95": None, "min": None, "max": None}
        return {
            "n": self.n,
            "p50": round(percentil(self.muestras_ms, 0.50), 1),
            "p95": round(percentil(self.muestras_ms, 0.95), 1),
            "min": round(min(self.muestras_ms), 1),
            "max": round(max(self.muestras_ms), 1),
        }

    def linea(self) -> str:
        if self.error:
            return f"  {self.etapa:<5} {self.implementacion:<38} ERROR: {self.error}"
        r = self.resumen()
        if r["n"] == 0:
            return f"  {self.etapa:<5} {self.implementacion:<38} sin muestras"
        return (
            f"  {self.etapa:<5} {self.implementacion:<38} "
            f"p50 {r['p50']:>7.1f} ms   p95 {r['p95']:>7.1f} ms   n={r['n']}"
        )


def guardar(mediciones: list[Medicion], nombre: str) -> Path:
    """Vuelca las mediciones a JSON con fecha y procedencia."""
    ARTEFACTOS.mkdir(exist_ok=True)
    fecha = datetime.now(timezone.utc).astimezone()
    destino = ARTEFACTOS / f"{nombre}-{fecha:%Y%m%d-%H%M%S}.json"
    payload = {
        "fecha": fecha.isoformat(),
        "host": describe_host(),
        "mediciones": [
            {**asdict(m), "resumen": m.resumen()} for m in mediciones
        ],
    }
    destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


def cargar_env() -> dict:
    """Lee `.env` sin depender de python-dotenv.

    Deliberadamente tonto: una clave por línea, `CLAVE=valor`, sin comillas ni
    interpolación. Si algún día hace falta más, se cambia por la librería.
    """
    valores = dict(os.environ)
    fichero = RAIZ / ".env"
    if fichero.exists():
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            valores[clave.strip()] = valor.strip()
    return valores
