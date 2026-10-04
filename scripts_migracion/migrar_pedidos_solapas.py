"""Reescribe total_venta_usd con el neto "a Rendir" de cada ficha de cliente.

No lee la solapa Pedidos. No inserta pedidos nuevos ni toca pagos ni stock.
En cada ficha usa la columna D (a Rendir). Si esa celda no es un número,
usa PEDIDO menos COMISION.
"""

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from calculos import cargo_cuenta
from migrar_clientes import ALIAS, EXCEL, SOLAPAS_INTERNAS, clave, es_nombre_valido
from migrar_historial_con_solapa import clientes_supabase, es_fecha, fecha_iso, numero

load_dotenv(RAIZ / ".env")


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def canonico(nombre: str) -> str:
    return ALIAS.get(clave(nombre), clave(nombre))


def a_rendir_de(fila) -> tuple[float, float] | None:
    pedido = numero(fila.iloc[1]) if len(fila) > 1 else None
    if pedido is None or pedido <= 0:
        return None
    rendir = numero(fila.iloc[3]) if len(fila) > 3 else None
    if rendir is not None and rendir >= 0:
        return pedido, rendir
    comision = numero(fila.iloc[2]) if len(fila) > 2 else None
    if comision is not None:
        return pedido, round(pedido - comision, 2)
    return pedido, pedido


def cargar_pedidos(sb) -> list[dict]:
    filas = []
    inicio = 0
    while True:
        lote = (
            sb.table("pedidos")
            .select("id,cliente_id,fecha,total_venta_usd,costo_total_usd,ganancia_bruta_usd,ganancia_real_usd")
            .range(inicio, inicio + 999)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < 1000:
            return filas
        inicio += 1000


def elegir(candidatos: list[dict], pedido_xls: float, rendir: float, usados: set) -> dict | None:
    libres = [pedido for pedido in candidatos if pedido["id"] not in usados]
    if not libres:
        return None

    def distancia(pedido: dict) -> float:
        total = float(pedido["total_venta_usd"])
        return min(abs(total - pedido_xls), abs(total - rendir))

    return min(libres, key=distancia)


def main() -> None:
    configurar_consola()
    if not EXCEL.exists():
        raise SystemExit(f"No está el archivo {EXCEL}")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    catalogo = clientes_supabase(sb)
    pedidos = cargar_pedidos(sb)
    por_cliente: dict[int, list[dict]] = {}
    for pedido in pedidos:
        por_cliente.setdefault(int(pedido["cliente_id"]), []).append(pedido)

    libro = pd.ExcelFile(EXCEL)
    usados: set = set()
    cambios = []
    ya = 0
    sin_fecha = []
    sin_par = []
    solapas = 0

    for solapa in libro.sheet_names:
        if clave(solapa) in SOLAPAS_INTERNAS or not es_nombre_valido(solapa):
            continue
        cliente = catalogo.get(canonico(solapa))
        if cliente is None:
            print(f"Solapa sin cliente en Supabase: {solapa}")
            continue
        solapas += 1
        hoja = pd.read_excel(EXCEL, sheet_name=solapa, header=None)
        for indice in range(2, len(hoja)):
            fila = hoja.iloc[indice]
            importes = a_rendir_de(fila)
            if importes is None:
                continue
            pedido_xls, rendir = importes
            if not es_fecha(fila.iloc[0]):
                sin_fecha.append((cliente["nombre"], pedido_xls, rendir))
                continue
            momento = pd.Timestamp(fecha_iso(fila.iloc[0]))
            candidatos = []
            for pedido in por_cliente.get(int(cliente["id"]), []):
                delta = abs(pd.Timestamp(pedido["fecha"]) - momento).total_seconds()
                if delta <= 2:
                    candidatos.append(pedido)
            elegido = elegir(candidatos, pedido_xls, rendir, usados)
            if elegido is None:
                sin_par.append((cliente["nombre"], str(momento)[:19], pedido_xls, rendir))
                continue
            usados.add(elegido["id"])
            actual = round(float(elegido["total_venta_usd"]), 2)
            nuevo = round(rendir, 2)
            if abs(actual - nuevo) < 0.005:
                ya += 1
                continue
            cambios.append((elegido, cliente, actual, nuevo))

    print(f"Solapas de clientes leídas: {solapas}")
    print(f"Pedidos en Supabase: {len(pedidos)}")
    print(f"Ya coincidían con a Rendir: {ya}")
    print(f"A actualizar: {len(cambios)}")
    print(f"Filas de ficha sin fecha (no se tocan): {len(sin_fecha)}")
    for item in sin_fecha:
        print(f"  sin fecha: {item[0]} pedido {item[1]:.2f} a rendir {item[2]:.2f}")
    print(f"Filas de ficha sin pedido equivalente: {len(sin_par)}")
    for item in sin_par:
        print(f"  sin par: {item}")
    print(f"Pedidos sin ficha individual (no se tocan): {len(pedidos) - len(usados)}")

    antes = round(sum(float(p["total_venta_usd"]) for p in pedidos), 2)
    despues = antes
    cargo_antes = 0.0
    cargo_despues = 0.0
    for pedido, cliente, actual, nuevo in cambios:
        despues += nuevo - actual
        cargo_antes += cargo_cuenta(pedido, cliente)
        simulado = dict(pedido)
        simulado["total_venta_usd"] = nuevo
        cargo_despues += cargo_cuenta(simulado, cliente)
    print(f"Suma total_venta_usd antes: {antes:,.2f}")
    print(f"Suma total_venta_usd después: {round(despues, 2):,.2f}")
    print(f"Cargo de los pedidos a cambiar, antes: {cargo_antes:,.2f}")
    print(f"Cargo de los pedidos a cambiar, después: {cargo_despues:,.2f}")
    if abs(cargo_despues - cargo_antes) > 25:
        raise SystemExit("El cargo de las cuentas se movería más de US$ 25. No se escribió nada.")

    coco = [item for item in cambios if clave(item[1]["nombre"]) == "coco salta"]
    if coco:
        print("Coco Salta, valor de su ficha (a Rendir), sin regla extra:")
        for pedido, cliente, actual, nuevo in coco:
            print(f"  {str(pedido['fecha'])[:19]}  {actual:,.2f} -> {nuevo:,.2f}")

    actualizados = 0
    for pedido, _cliente, _actual, nuevo in cambios:
        sb.table("pedidos").update({"total_venta_usd": nuevo}).eq("id", int(pedido["id"])).execute()
        actualizados += 1
        if actualizados % 50 == 0:
            print(f"  escritos {actualizados}")
    print(f"Pedidos actualizados: {actualizados}")


if __name__ == "__main__":
    main()
