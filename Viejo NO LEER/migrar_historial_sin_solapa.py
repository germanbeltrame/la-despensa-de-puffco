"""Migra pedidos históricos de clientes que no tienen solapa propia.

No lee las columnas PAGO ni Ganancia real. No descuenta stock.
El margen bruto sale del valor numérico de la columna GANANCIA.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

from migrar_clientes import ALIAS, EXCEL, SOLAPAS_INTERNAS, clave, es_nombre_valido, presentar

ART = timezone(timedelta(hours=-3))


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def canonico(nombre: str) -> str:
    return ALIAS.get(clave(nombre), clave(nombre))


def solapas_de_clientes() -> set[str]:
    libro = pd.ExcelFile(EXCEL)
    return {
        clave(nombre)
        for nombre in libro.sheet_names
        if clave(nombre) not in SOLAPAS_INTERNAS and es_nombre_valido(nombre)
    }


def numero(valor) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def fecha_iso(valor) -> str:
    if valor is None or pd.isna(valor):
        return datetime.now(ART).isoformat()
    momento = pd.Timestamp(valor).to_pydatetime()
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ART)
    return momento.isoformat()


def factor_ganancia(cliente: dict) -> float:
    porcentaje = float(cliente.get("porcentaje_ganancia") or 0)
    if cliente.get("es_distribuidor") or porcentaje == 50:
        return 0.5
    return 1.0


def clientes_supabase(sb) -> dict[str, dict]:
    filas = []
    inicio = 0
    while True:
        lote = sb.table("clientes").select("id,nombre,es_distribuidor,porcentaje_ganancia").range(inicio, inicio + 999).execute().data or []
        filas.extend(lote)
        if len(lote) < 1000:
            break
        inicio += 1000
    return {clave(fila["nombre"]): fila for fila in filas}


def pedidos_existentes(sb) -> set[tuple]:
    marcas = set()
    inicio = 0
    while True:
        lote = (
            sb.table("pedidos")
            .select("cliente_id,fecha,total_venta_usd")
            .range(inicio, inicio + 999)
            .execute()
            .data
            or []
        )
        for fila in lote:
            marcas.add((int(fila["cliente_id"]), str(fila["fecha"]), round(float(fila["total_venta_usd"]), 2)))
        if len(lote) < 1000:
            return marcas
        inicio += 1000


def armar_pedidos(sb) -> tuple[list[dict], list[str]]:
    solapas = solapas_de_clientes()
    catalogo = clientes_supabase(sb)
    tabla = pd.read_excel(EXCEL, sheet_name="Pedidos")
    for columna in ("fecha", "Clientes", "PEDIDO", "GANANCIA"):
        if columna not in tabla.columns:
            raise RuntimeError(f"La hoja Pedidos no tiene la columna {columna}.")

    pedidos = []
    omitidos = []
    for _, fila in tabla.iterrows():
        nombre = fila["Clientes"]
        if not es_nombre_valido(nombre):
            continue
        destino = canonico(str(nombre))
        if destino in solapas:
            continue
        cliente = catalogo.get(destino)
        if cliente is None:
            omitidos.append(f"Sin cliente en Supabase: {presentar(str(nombre))}")
            continue
        total = numero(fila["PEDIDO"])
        margen = numero(fila["GANANCIA"])
        if total is None or margen is None:
            omitidos.append(f"Fila incompleta de {cliente['nombre']}: falta PEDIDO o GANANCIA.")
            continue
        real = round(margen * factor_ganancia(cliente), 2)
        detalle = fila.get("Inversion inicial")
        if not isinstance(detalle, str) or not detalle.strip():
            detalle = ""
        else:
            detalle = " ".join(detalle.replace("\xa0", " ").split())
        pedidos.append(
            {
                "cliente_id": int(cliente["id"]),
                "cliente_nombre": cliente["nombre"],
                "fecha": fecha_iso(fila["fecha"]),
                "total_venta_usd": total,
                "costo_total_usd": round(total - margen, 2),
                "ganancia_bruta_usd": margen,
                "ganancia_real_usd": real,
                "detalle": detalle,
            }
        )
    return pedidos, sorted(set(omitidos))


def insertar(sb, pedidos: list[dict]) -> list[dict]:
    ya_cargados = pedidos_existentes(sb)
    nuevos = []
    for pedido in pedidos:
        marca = (pedido["cliente_id"], pedido["fecha"], pedido["total_venta_usd"])
        if marca in ya_cargados:
            continue
        ya_cargados.add(marca)
        nuevos.append(pedido)

    for inicio in range(0, len(nuevos), 100):
        lote = nuevos[inicio : inicio + 100]
        sb.table("pedidos").insert(
            [
                {
                    "cliente_id": item["cliente_id"],
                    "fecha": item["fecha"],
                    "total_venta_usd": item["total_venta_usd"],
                    "costo_total_usd": item["costo_total_usd"],
                    "ganancia_bruta_usd": item["ganancia_bruta_usd"],
                    "ganancia_real_usd": item["ganancia_real_usd"],
                    "detalle": item.get("detalle") or None,
                }
                for item in lote
            ]
        ).execute()
    return nuevos


def reportar(pedidos: list[dict], omitidos: list[str]) -> None:
    print(f"Pedidos procesados: {len(pedidos)}")
    print("El stock de productos no se modificó.")
    print()
    print("Clientes impactados:")
    nombres = sorted({pedido["cliente_nombre"] for pedido in pedidos}, key=str.casefold)
    for nombre in nombres:
        print(f"  - {nombre}")
    total = round(sum(pedido["total_venta_usd"] for pedido in pedidos), 2)
    print()
    print(f"Clientes: {len(nombres)}")
    print(f"Total vendido: US$ {total:,.2f}")
    if omitidos:
        print()
        print("Filas no migradas:")
        for linea in omitidos:
            print(f"  - {linea}")


def main() -> None:
    configurar_consola()
    if not EXCEL.exists():
        raise FileNotFoundError(f"No se encontró el Excel: {EXCEL}")

    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    url = os.getenv("SUPABASE_URL", "").strip().strip('"')
    clave_api = os.getenv("SUPABASE_KEY", "").strip().strip('"')
    if not url or not clave_api:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en el archivo .env.")

    sb = create_client(url, clave_api)
    pedidos, omitidos = armar_pedidos(sb)
    insertados = insertar(sb, pedidos)
    reportar(insertados, omitidos)


if __name__ == "__main__":
    main()
