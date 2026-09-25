r"""¿Está todo listo para que entre una llamada de verdad? (cero coste)

Existe por una razón concreta: las tres cosas que hacen perder la tarde montando
telefonía **no dan ningún error claro**. El webhook apuntando al sitio
equivocado da un error de TwiML que no dice nada; el túnel con otra URL que la
del `.env` deja la llamada en silencio; y ngrok del plan gratuito **cambia de
URL en cada arranque**, así que lo que funcionó ayer hoy no.

Esto lo comprueba todo antes de marcar, y dice qué falta y cómo se arregla. No
llama por teléfono ni gasta crédito: solo mira lo que ya hay levantado.

Uso:
  .\.venv\Scripts\python.exe probe\check_telefonia.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import cargar_env  # noqa: E402

PUERTO_LOCAL = 8000
API_NGROK = "http://127.0.0.1:4040/api/tunnels"

bien = 0
mal: list[str] = []


def ok(texto: str) -> None:
    global bien
    bien += 1
    print(f"  ok    {texto}")


def falta(texto: str, arreglo: str) -> None:
    mal.append(f"{texto}\n          -> {arreglo}")
    print(f"  FALTA {texto}")
    print(f"          -> {arreglo}")


def pedir(url: str, metodo: str = "GET", tiempo: float = 8.0) -> tuple[int, str]:
    peticion = urllib.request.Request(url, method=metodo)
    with urllib.request.urlopen(peticion, timeout=tiempo) as respuesta:
        return respuesta.status, respuesta.read().decode("utf-8", "replace")


def main() -> int:
    print("¿Puede entrar una llamada de teléfono?\n")

    # 1. La pasarela, en local.
    try:
        estado, cuerpo = pedir(f"http://127.0.0.1:{PUERTO_LOCAL}/")
        if estado == 200:
            ok(f"la pasarela responde en el puerto {PUERTO_LOCAL}")
        else:
            falta(f"la pasarela contesta {estado}",
                  "mira la consola donde corre uvicorn")
    except Exception as exc:  # noqa: BLE001
        falta(f"la pasarela no responde ({type(exc).__name__})",
              r".\.venv\Scripts\python.exe -m uvicorn app.gateway:app --port 8000")
        print("\n  Sin la pasarela no se puede comprobar nada más.")
        return 1

    # 2. El TwiML, en local.
    try:
        estado, xml = pedir(f"http://127.0.0.1:{PUERTO_LOCAL}/twilio/voz", "POST")
        if estado == 200 and "<Connect>" in xml:
            ok("el endpoint del TwiML contesta (/twilio/voz)")
        else:
            falta("el TwiML no sale bien", f"contestó {estado}: {xml[:90]}")
    except Exception as exc:  # noqa: BLE001
        falta(f"el TwiML no responde ({type(exc).__name__})",
              "revisa que app/gateway.py tenga la ruta /twilio/voz")
        xml = ""

    # 3. El túnel.
    publica = None
    try:
        _, crudo = pedir(API_NGROK, tiempo=4.0)
        tuneles = json.loads(crudo).get("tunnels") or []
        publicas = [t.get("public_url") for t in tuneles
                    if str(t.get("public_url", "")).startswith("https://")]
        if publicas:
            publica = publicas[0]
            ok(f"hay un túnel abierto: {publica}")
        else:
            falta("ngrok está corriendo pero sin túnel https",
                  "ngrok http 8000")
    except Exception:  # noqa: BLE001
        falta("no hay ningún túnel abierto (ngrok no responde en :4040)",
              r'"C:\Users\ASUS\Desktop\ngrok-v3-stable-windows-amd64\ngrok.exe" http 8000'
              "\n             (y antes, una vez:  ngrok config add-authtoken <token>)")

    # 4. La URL que el sistema va a decirle a Twilio.
    entorno = cargar_env()
    configurada = (entorno.get("TWILIO_STREAM_URL") or "").strip()
    if not configurada:
        print("  aviso TWILIO_STREAM_URL está vacío: la URL se deducirá de la "
              "cabecera Host.")
        print("          Funciona detrás del túnel, pero es mejor ponerla.")
    else:
        if not configurada.startswith("wss://"):
            falta(f"TWILIO_STREAM_URL no empieza por wss:// ({configurada[:40]})",
                  "Twilio rechaza ws:// y los certificados autofirmados")
        elif not configurada.endswith("/twilio"):
            falta(f"TWILIO_STREAM_URL no acaba en /twilio ({configurada[:60]})",
                  "el WebSocket vive en /twilio; /twilio/voz es el XML")
        else:
            ok("TWILIO_STREAM_URL tiene la forma correcta")

        # La trampa de verdad: el túnel de hoy no es el de ayer.
        if publica:
            anfitrion_tunel = publica.replace("https://", "")
            if anfitrion_tunel not in configurada:
                falta("TWILIO_STREAM_URL apunta a OTRO túnel que el que está "
                      "abierto ahora",
                      f"ponlo a  wss://{anfitrion_tunel}/twilio  "
                      f"(ngrok cambia de URL en cada arranque)")
            else:
                ok("y coincide con el túnel que está abierto ahora")

    # 5. Y lo que Twilio verá de verdad: el TwiML pedido por la URL pública.
    if publica:
        try:
            estado, xml_publico = pedir(f"{publica}/twilio/voz", "POST")
            if estado == 200 and "wss://" in xml_publico:
                ok("por el túnel, el TwiML sale con una URL wss")
                if "ngrok" in xml_publico or (configurada and configurada in xml_publico):
                    ok("y apunta a donde tiene que apuntar")
                else:
                    falta("el TwiML sale con una URL que no es del túnel",
                          f"revisa TWILIO_STREAM_URL: {xml_publico[:120]}")
            else:
                falta(f"por el túnel el TwiML contesta {estado}",
                      xml_publico[:100])
        except Exception as exc:  # noqa: BLE001
            falta(f"el túnel no llega a la pasarela ({type(exc).__name__})",
                  "¿ngrok apunta al puerto 8000?")

    print()
    if mal:
        print(f"{len(mal)} cosa(s) por arreglar antes de llamar. "
              f"Los pasos completos: docs/telefonia.md")
        return 1
    print(f"Todo listo ({bien} comprobaciones). En la consola de Twilio, el "
          f"número tiene que\napuntar a  {publica or 'https://<tu-tunel>'}"
          f"/twilio/voz  por HTTP POST.")
    print("Y recuerda: en cuenta de prueba, Twilio dice un aviso antes de "
          "pasar la llamada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
