"""Migra ventas y pagos de las solapas de clientes con ficha propia.

No lee PAGO ni Ganancia real de la hoja Pedidos.
No modifica el stock. Pide confirmación antes de escribir en Supabase.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

from migrar_clientes import ALIAS, EXCEL, SOLAPAS_INTERNAS, clave, es_nombre_valido

ART = timezone(timedelta(hours=-3))


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def canonico(nombre: str) -> str:
    return ALIAS.get(clave(nombre), clave(nombre))


def numero(valor) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, str):
        limpio = valor.strip().replace(",", ".")
        if not limpio:
            return None
        valor = limpio
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def es_fecha(valor) -> bool:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return False
    if isinstance(valor, datetime):
        return True
    if isinstance(valor, pd.Timestamp):
        return not pd.isna(valor)
    return False


def fecha_iso(valor) -> str:
    if not es_fecha(valor):
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


def texto_celda(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return ""
    texto = " ".join(str(valor).replace("\xa0", " ").split())
    if texto.casefold() in {"nan", "none", "obs", "obs.", "observaciones", "tc", "saldo actual:"}:
        return ""
    return texto


def clientes_supabase(sb) -> dict[str, dict]:
    filas = []
    inicio = 0
    while True:
        lote = (
            sb.table("clientes")
            .select("id,nombre,es_distribuidor,porcentaje_ganancia")
            .range(inicio, inicio + 999)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < 1000:
            return {clave(fila["nombre"]): fila for fila in filas}
        inicio += 1000


def pedidos_de_referencia() -> dict[str, list[dict]]:
    tabla = pd.read_excel(EXCEL, sheet_name="Pedidos")
    grupos: dict[str, list[dict]] = {}
    for _, fila in tabla.iterrows():
        if not es_nombre_valido(fila.get("Clientes")):
            continue
        destino = canonico(str(fila["Clientes"]))
        detalle = texto_celda(fila.get("Inversion inicial"))
        grupos.setdefault(destino, []).append(
            {
                "total": numero(fila.get("PEDIDO")),
                "margen": numero(fila.get("GANANCIA")),
                "fecha": pd.to_datetime(fila.get("fecha"), errors="coerce"),
                "detalle": detalle,
                "usado": False,
            }
        )
    return grupos


def tomar_referencia(grupos: dict[str, list[dict]], destino: str, total: float, fecha) -> dict | None:
    candidatos = [
        item
        for item in grupos.get(destino, [])
        if not item["usado"] and item["total"] is not None and abs(item["total"] - total) < 0.02
    ]
    if not candidatos:
        return None
    momento = pd.to_datetime(fecha, errors="coerce")

    def distancia(item) -> float:
        if pd.isna(momento) or pd.isna(item["fecha"]):
            return 10**12
        return abs((item["fecha"] - momento).total_seconds())

    elegido = min(candidatos, key=distancia)
    elegido["usado"] = True
    return elegido


def reparte_comision(hoja: pd.DataFrame) -> bool:
    if len(hoja) < 2:
        return False
    marca = str(hoja.iloc[1, 2]) if hoja.shape[1] > 2 else ""
    return "quotient(2" in marca.casefold()


def interpretar_pago(fila: pd.Series, pago_usd: float) -> dict:
    numeros = []
    notas = []
    for valor in fila.iloc[6:]:
        if isinstance(valor, str) or texto_celda(valor):
            nota = texto_celda(valor)
            if nota:
                notas.append(nota)
            continue
        cantidad = numero(valor)
        if cantidad is None:
            continue
        numeros.append(cantidad)

    cotizacion = next((n for n in numeros if 800 <= n <= 8000), None)
    pesos = next((n for n in numeros if n >= 10000), None)
    if cotizacion and pesos and pago_usd > 0 and abs((pesos / cotizacion) - pago_usd) / pago_usd <= 0.03:
        return {
            "moneda": "ARS",
            "monto_original": round(pesos, 2),
            "cotizacion": round(cotizacion, 2),
            "monto_usd_descontado": pago_usd,
            "observaciones": " · ".join(notas) or None,
        }
    if numeros:
        notas.extend(f"{n:g}" for n in numeros)
    return {
        "moneda": "USD",
        "monto_original": pago_usd,
        "cotizacion": 1.0,
        "monto_usd_descontado": pago_usd,
        "observaciones": " · ".join(notas) or None,
    }


def leer_solapas(sb) -> tuple[list[dict], list[dict], list[str]]:
    catalogo = clientes_supabase(sb)
    referencia = pedidos_de_referencia()
    libro = pd.ExcelFile(EXCEL)
    ventas = []
    pagos = []
    avisos = []

    for solapa in libro.sheet_names:
        if clave(solapa) in SOLAPAS_INTERNAS or not es_nombre_valido(solapa):
            continue
        cliente = catalogo.get(canonico(solapa))
        if cliente is None:
            avisos.append(f"La solapa {solapa} no coincide con un cliente de Supabase.")
            continue

        hoja = pd.read_excel(EXCEL, sheet_name=solapa, header=None)
        mitad = reparte_comision(hoja)
        if mitad and not cliente.get("es_distribuidor"):
            avisos.append(
                f"{cliente['nombre']} tiene comisión partida en la ficha, pero en Supabase no es distribuidor. "
                "La ganancia real queda al 100% del margen."
            )

        for indice in range(2, len(hoja)):
            fila = hoja.iloc[indice]
            total = numero(fila.iloc[1]) if len(fila) > 1 else None
            if es_fecha(fila.iloc[0]) and total is not None and total > 0:
                comision = numero(fila.iloc[2]) if len(fila) > 2 else None
                origen = tomar_referencia(referencia, canonico(solapa), total, fila.iloc[0])
                if origen and origen["margen"] is not None:
                    margen = origen["margen"]
                    detalle = origen["detalle"]
                elif comision is not None and mitad:
                    margen = round(comision * 2, 2)
                    detalle = ""
                elif comision is not None:
                    margen = comision
                    detalle = ""
                else:
                    margen = 0.0
                    detalle = ""
                    avisos.append(f"{cliente['nombre']}: venta de {total:.2f} sin margen bruto. Se cargó en 0.")
                real = round(margen * factor_ganancia(cliente), 2)
                ventas.append(
                    {
                        "cliente_id": int(cliente["id"]),
                        "cliente_nombre": cliente["nombre"],
                        "fecha": fecha_iso(fila.iloc[0]),
                        "total_venta_usd": total,
                        "costo_total_usd": round(total - margen, 2),
                        "ganancia_bruta_usd": margen,
                        "ganancia_real_usd": real,
                        "detalle": detalle,
                    }
                )

            pago = numero(fila.iloc[5]) if len(fila) > 5 else None
            if es_fecha(fila.iloc[4] if len(fila) > 4 else None) and pago is not None and pago > 0:
                datos = interpretar_pago(fila, pago)
                pagos.append(
                    {
                        "cliente_id": int(cliente["id"]),
                        "cliente_nombre": cliente["nombre"],
                        "fecha": fecha_iso(fila.iloc[4]),
                        **datos,
                    }
                )
    return ventas, pagos, avisos


def resumen(ventas: list[dict], pagos: list[dict]) -> list[dict]:
    nombres = sorted(
        {item["cliente_nombre"] for item in ventas} | {item["cliente_nombre"] for item in pagos},
        key=str.casefold,
    )
    filas = []
    for nombre in nombres:
        comprado = round(sum(item["total_venta_usd"] for item in ventas if item["cliente_nombre"] == nombre), 2)
        pagado = round(sum(item["monto_usd_descontado"] for item in pagos if item["cliente_nombre"] == nombre), 2)
        filas.append(
            {
                "nombre": nombre,
                "comprado": comprado,
                "pagado": pagado,
                "saldo": round(comprado - pagado, 2),
            }
        )
    return filas


def imprimir(ventas: list[dict], pagos: list[dict], avisos: list[str]) -> None:
    print(f"Ventas a migrar: {len(ventas)}")
    print(f"Pagos a migrar: {len(pagos)}")
    print("El stock no se modifica. Todavía no se escribió nada en Supabase.")
    print()
    cuentas = resumen(ventas, pagos)
    print(f"{'Cliente':<32} {'Comprado':>14} {'Pagado':>14} {'Saldo':>14}")
    for cuenta in cuentas:
        print(
            f"{cuenta['nombre']:<32} {cuenta['comprado']:>14,.2f} "
            f"{cuenta['pagado']:>14,.2f} {cuenta['saldo']:>14,.2f}"
        )
    print()
    print(f"Clientes: {len(cuentas)}")
    print(f"Total comprado: US$ {sum(c['comprado'] for c in cuentas):,.2f}")
    print(f"Total pagado: US$ {sum(c['pagado'] for c in cuentas):,.2f}")
    print(f"Saldo pendiente: US$ {sum(c['saldo'] for c in cuentas):,.2f}")
    if avisos:
        print()
        print("Avisos:")
        for aviso in avisos:
            print(f"  - {aviso}")


def confirmar() -> bool:
    print()
    try:
        respuesta = input("¿Insertar estas ventas y pagos en Supabase? Escribí si para confirmar: ")
    except EOFError:
        print("Sin confirmación. No se insertó nada.")
        return False
    return respuesta.strip().casefold() in {"si", "sí", "s", "yes"}


def ya_cargados(sb, tabla: str, monto: str) -> set[tuple]:
    marcas = set()
    inicio = 0
    while True:
        lote = sb.table(tabla).select(f"cliente_id,fecha,{monto}").range(inicio, inicio + 999).execute().data or []
        for fila in lote:
            marcas.add((int(fila["cliente_id"]), str(fila["fecha"])[:19], round(float(fila[monto]), 2)))
        if len(lote) < 1000:
            return marcas
        inicio += 1000


def tiene_detalle(sb) -> bool:
    try:
        sb.table("pedidos").select("detalle").limit(1).execute()
        return True
    except Exception:
        return False


def insertar(sb, ventas: list[dict], pagos: list[dict]) -> tuple[int, int]:
    guardar_detalle = tiene_detalle(sb)
    if not guardar_detalle:
        print("La tabla pedidos no tiene columna de texto. El detalle quedó fuera de la cabecera.")
    existentes_ventas = ya_cargados(sb, "pedidos", "total_venta_usd")
    existentes_pagos = ya_cargados(sb, "pagos", "monto_usd_descontado")
    nuevas_ventas = []
    nuevos_pagos = []
    for venta in ventas:
        marca = (venta["cliente_id"], venta["fecha"][:19], venta["total_venta_usd"])
        if marca in existentes_ventas:
            continue
        existentes_ventas.add(marca)
        fila = {
            "cliente_id": venta["cliente_id"],
            "fecha": venta["fecha"],
            "total_venta_usd": venta["total_venta_usd"],
            "costo_total_usd": venta["costo_total_usd"],
            "ganancia_bruta_usd": venta["ganancia_bruta_usd"],
            "ganancia_real_usd": venta["ganancia_real_usd"],
        }
        if guardar_detalle and venta["detalle"]:
            fila["detalle"] = venta["detalle"]
        nuevas_ventas.append(fila)
    for pago in pagos:
        marca = (pago["cliente_id"], pago["fecha"][:19], pago["monto_usd_descontado"])
        if marca in existentes_pagos:
            continue
        existentes_pagos.add(marca)
        nuevos_pagos.append(
            {
                "cliente_id": pago["cliente_id"],
                "fecha": pago["fecha"],
                "moneda": pago["moneda"],
                "monto_original": pago["monto_original"],
                "cotizacion": pago["cotizacion"],
                "monto_usd_descontado": pago["monto_usd_descontado"],
                "observaciones": pago["observaciones"],
            }
        )

    for inicio in range(0, len(nuevas_ventas), 100):
        sb.table("pedidos").insert(nuevas_ventas[inicio : inicio + 100]).execute()
    for inicio in range(0, len(nuevos_pagos), 100):
        sb.table("pagos").insert(nuevos_pagos[inicio : inicio + 100]).execute()
    return len(nuevas_ventas), len(nuevos_pagos)


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
    ventas, pagos, avisos = leer_solapas(sb)
    imprimir(ventas, pagos, avisos)
    if not confirmar():
        return
    cantidad_ventas, cantidad_pagos = insertar(sb, ventas, pagos)
    print()
    print(f"Ventas insertadas: {cantidad_ventas}")
    print(f"Pagos insertados: {cantidad_pagos}")
    print("Stock sin cambios.")


if __name__ == "__main__":
    main()
