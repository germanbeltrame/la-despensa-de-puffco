import streamlit as st
from supabase import Client

from calculos import es_cuenta_distribuidor, movimientos_cuenta, total_cargos
from database import leer_detalles_pedidos, leer_pagos_cliente, leer_pedidos_cliente, leer_productos
from ui import dinero, mostrar_kpis, mostrar_libro
from views.catalogo import pagina_catalogo


def _cuenta(sb: Client, cliente: dict) -> None:
    st.caption("Solo lectura. No se pueden cargar pagos ni modificar pedidos.")
    pedidos = leer_pedidos_cliente(sb, int(cliente["id"]))
    pagos = leer_pagos_cliente(sb, int(cliente["id"]))
    if pedidos is None or pagos is None:
        return
    comprado = total_cargos(pedidos, cliente)
    pagado = round(sum(float(item.get("monto_usd_descontado") or 0) for item in pagos), 2)
    saldo = round(comprado - pagado, 2)
    detalle = "Cargo de los pedidos"
    if es_cuenta_distribuidor(cliente):
        detalle = "Cargo neto, sin su parte de la ganancia"
    mostrar_kpis(
        [
            ("Total comprado", dinero(comprado), detalle),
            ("Total pagado", dinero(pagado), "Abonos en USD"),
            ("Saldo pendiente", dinero(saldo), "Cargo menos abonos"),
        ]
    )
    nombres, por_pedido = _nombres_y_detalle(sb, pedidos)
    st.subheader("Estado de cuenta", icon=":material/menu_book:")
    mostrar_libro(movimientos_cuenta(pedidos, pagos, cliente, por_pedido, nombres))


def _nombres_y_detalle(sb: Client, pedidos: list) -> tuple[dict, dict]:
    if not pedidos:
        return {}, {}
    detalles = leer_detalles_pedidos(sb, [int(item["id"]) for item in pedidos])
    productos = leer_productos(sb, "id,nombre")
    if detalles is None or productos is None:
        return {}, {}
    nombres = {int(item["id"]): item["nombre"] for item in productos}
    por_pedido: dict[int, list] = {}
    for linea in detalles:
        por_pedido.setdefault(int(linea["pedido_id"]), []).append(linea)
    return nombres, por_pedido


def pagina_portal(sb: Client, cliente: dict) -> None:
    if st.session_state.get("portal_seccion") not in ("Catálogo", "Cuenta corriente"):
        st.session_state["portal_seccion"] = "Catálogo"
    seccion = st.segmented_control(
        "Sección del portal",
        ["Catálogo", "Cuenta corriente"],
        key="portal_seccion",
        label_visibility="collapsed",
    )
    if seccion == "Cuenta corriente":
        _cuenta(sb, cliente)
        return
    pagina_catalogo(cliente)
