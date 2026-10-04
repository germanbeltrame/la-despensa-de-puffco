"""Agrega pedidos.detalle si falta y lo llena con el texto original de cada venta.

No modifica stock, pagos ni montos. Solo escribe la columna de texto.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

import migrar_historial_con_solapa as con_solapa
import migrar_historial_sin_solapa as sin_solapa

ART = timezone(timedelta(hours=-3))
SQL = "alter table public.pedidos add column if not exists detalle text;"


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def dia_art(valor) -> str:
    texto = str(valor).replace("Z", "+00:00")
    momento = datetime.fromisoformat(texto)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ART)
    return momento.astimezone(ART).date().isoformat()


def columna_existe(sb) -> bool:
    try:
        sb.table("pedidos").select("detalle").limit(1).execute()
        return True
    except Exception:
        return False


def asegurar_columna(sb, url: str, clave: str) -> None:
    if columna_existe(sb):
        print("La columna pedidos.detalle ya existe.")
        return
    errores = []
    for ruta in ("/pg/query", "/pg-meta/default/query"):
        pedido = urllib.request.Request(
            url.rstrip("/") + ruta,
            data=json.dumps({"query": SQL}).encode(),
            headers={
                "apikey": clave,
                "Authorization": f"Bearer {clave}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                respuesta.read()
        except urllib.error.HTTPError as exc:
            errores.append(f"{ruta} respondió {exc.code}")
            continue
        except Exception as exc:
            errores.append(f"{ruta}: {exc.__class__.__name__}")
            continue
        if columna_existe(sb):
            print("Columna pedidos.detalle creada.")
            return
        errores.append(f"{ruta} no dejó la columna disponible")
    detalle = " ".join(errores) or "sin respuesta"
    raise RuntimeError(
        "No se pudo crear pedidos.detalle. "
        f"Ejecutá en el SQL editor: {SQL} ({detalle})"
    )


def cargar_pedidos(sb) -> list[dict]:
    filas = []
    inicio = 0
    while True:
        lote = (
            sb.table("pedidos")
            .select("id,cliente_id,fecha,total_venta_usd,detalle")
            .range(inicio, inicio + 999)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < 1000:
            return filas
        inicio += 1000


def textos_originales(sb) -> dict[tuple, list[str]]:
    grupos: dict[tuple, list[str]] = {}
    sin_ficha, _ = sin_solapa.armar_pedidos(sb)
    con_ficha, _, _ = con_solapa.leer_solapas(sb)
    for venta in sin_ficha + con_ficha:
        marca = (int(venta["cliente_id"]), dia_art(venta["fecha"]), round(float(venta["total_venta_usd"]), 2))
        grupos.setdefault(marca, []).append((venta.get("detalle") or "").strip())
    return grupos


def poblar(sb) -> None:
    grupos = textos_originales(sb)
    pedidos = sorted(cargar_pedidos(sb), key=lambda fila: int(fila["id"]))
    actualizados = 0
    sin_texto = 0
    ya_tenian = 0
    for pedido in pedidos:
        if str(pedido.get("detalle") or "").strip():
            ya_tenian += 1
            marca = (
                int(pedido["cliente_id"]),
                dia_art(pedido["fecha"]),
                round(float(pedido["total_venta_usd"]), 2),
            )
            cola = grupos.get(marca) or []
            if cola:
                cola.pop(0)
            continue
        marca = (
            int(pedido["cliente_id"]),
            dia_art(pedido["fecha"]),
            round(float(pedido["total_venta_usd"]), 2),
        )
        cola = grupos.get(marca) or []
        texto = cola.pop(0) if cola else ""
        if not texto:
            sin_texto += 1
            continue
        sb.table("pedidos").update({"detalle": texto}).eq("id", int(pedido["id"])).execute()
        actualizados += 1
    print(f"Pedidos con detalle cargado: {actualizados}")
    print(f"Pedidos que ya tenían texto: {ya_tenian}")
    print(f"Pedidos sin texto original: {sin_texto}")


def main() -> None:
    configurar_consola()
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    url = os.getenv("SUPABASE_URL", "").strip().strip('"')
    clave = os.getenv("SUPABASE_KEY", "").strip().strip('"')
    if not url or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en el archivo .env.")
    sb = create_client(url, clave)
    asegurar_columna(sb, url, clave)
    poblar(sb)


if __name__ == "__main__":
    main()
