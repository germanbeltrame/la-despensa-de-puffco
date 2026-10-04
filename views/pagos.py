import streamlit as st
from supabase import Client

from calculos import cargo_cuenta, formatear_fecha, parse_fecha, total_cargos
from database import (
    esta_activo,
    leer_clientes,
    leer_detalles_pedidos,
    leer_pagos_cliente,
    leer_pedidos_cliente,
    leer_productos,
    registrar_pago,
)
from ui import avisar, dinero, dinero_md

MODO_GENERAL = "Pago General / A Cuenta"
MODO_PEDIDO = "Imputar a Pedido Específico"


def pagina_pagos(sb: Client) -> None:
    if st.session_state.pop("pago_limpiar", False):
        st.session_state["pago_monto_usd"] = 0.0
        st.session_state["pago_monto_ars"] = 0.0
        st.session_state["pago_notas"] = ""
        st.session_state["pago_modo"] = MODO_GENERAL
        st.session_state.pop("pago_pedido_id", None)
    st.session_state.setdefault("pago_moneda", "USD")

    clientes = leer_clientes(sb)
    if clientes is None:
        return
    clientes = sorted(
        [item for item in clientes if esta_activo(item)],
        key=lambda item: item["nombre"].lower(),
    )
    if not clientes:
        st.warning("No hay clientes activos.")
        return

    cliente = _elegir_cliente(clientes)
    if cliente is None:
        return
    pedidos = leer_pedidos_cliente(sb, int(cliente["id"]))
    pagos = leer_pagos_cliente(sb, int(cliente["id"]))
    if pedidos is None or pagos is None:
        return
    detalles = []
    if pedidos:
        detalles = leer_detalles_pedidos(sb, [int(item["id"]) for item in pedidos])
        if detalles is None:
            return
    productos = leer_productos(sb, "id,nombre")
    if productos is None:
        return
    nombres = {int(item["id"]): item["nombre"] for item in productos}
    pendientes = pedidos_con_saldo(pedidos, pagos, cliente, detalles or [], nombres)

    _resumen_deuda(cliente, pedidos, pagos)
    _tabla_pendientes(pendientes)
    _formulario(sb, cliente, pendientes)


def _elegir_cliente(clientes: list) -> dict | None:
    opciones = [int(item["id"]) for item in clientes]
    if st.session_state.get("pago_cliente_id") not in opciones:
        st.session_state["pago_cliente_id"] = opciones[0]
    fijo = st.session_state.get("pago_cliente_fijo")
    if fijo not in opciones:
        fijo = None
    if fijo is not None:
        cliente = next(item for item in clientes if int(item["id"]) == int(fijo))
        tipo = "Distribuidor" if cliente.get("es_distribuidor") else "Cliente Estándar"
        with st.container(border=True):
            columna_nombre, columna_cancelar = st.columns([3, 1.5], vertical_alignment="center")
            columna_nombre.markdown(f"**{cliente['nombre']}** [{tipo}]")
            if columna_cancelar.button("Cambiar / Cancelar cliente", key="pago_cancelar_cliente", width="stretch"):
                st.session_state["pago_cliente_fijo"] = None
                st.session_state["pago_limpiar"] = True
                st.rerun()
        return cliente
    cliente_id = st.selectbox(
        "Cliente",
        opciones,
        format_func=lambda valor: next(item["nombre"] for item in clientes if int(item["id"]) == valor),
        key="pago_cliente_id",
    )
    if st.button("Confirmar Cliente", type="primary", key="pago_confirmar_cliente"):
        st.session_state["pago_cliente_fijo"] = int(cliente_id)
        st.rerun()
    return None


def _resumen_deuda(cliente: dict, pedidos: list, pagos: list) -> None:
    comprado = total_cargos(pedidos, cliente)
    cobrado = round(sum(float(item.get("monto_usd_descontado") or 0) for item in pagos), 2)
    saldo = round(comprado - cobrado, 2)
    color = "#B91C1C" if saldo > 0.009 else "#16A34A"
    with st.container(border=True):
        st.markdown("Saldo pendiente del cliente (USD)")
        st.markdown(
            f"<p style='font-size:2.4rem;font-weight:700;color:{color};margin:0 0 0.8rem 0'>{dinero(saldo)}</p>",
            unsafe_allow_html=True,
        )
        comprado_col, cobrado_col = st.columns(2)
        comprado_col.metric("Total comprado", dinero(comprado))
        cobrado_col.metric("Total cobrado", dinero(cobrado))


def pedidos_con_saldo(pedidos: list, pagos: list, cliente: dict, detalles: list, nombres: dict) -> list[dict]:
    ordenados = sorted(pedidos, key=lambda item: parse_fecha(item.get("fecha")))
    restante = {int(item["id"]): round(cargo_cuenta(item, cliente), 2) for item in ordenados}
    general = 0.0
    for pago in pagos:
        usd = round(float(pago.get("monto_usd_descontado") or 0), 2)
        pedido_id = pago.get("pedido_id")
        if pedido_id is not None and int(pedido_id) in restante:
            aplicado = min(restante[int(pedido_id)], usd)
            restante[int(pedido_id)] = round(restante[int(pedido_id)] - aplicado, 2)
            usd = round(usd - aplicado, 2)
        general = round(general + max(usd, 0.0), 2)
    for pedido in ordenados:
        if general <= 0:
            break
        pid = int(pedido["id"])
        aplicado = min(restante[pid], general)
        restante[pid] = round(restante[pid] - aplicado, 2)
        general = round(general - aplicado, 2)

    por_pedido: dict[int, list] = {}
    for detalle in detalles:
        por_pedido.setdefault(int(detalle["pedido_id"]), []).append(detalle)
    vivos = []
    for pedido in reversed(ordenados):
        saldo = round(restante[int(pedido["id"])], 2)
        if saldo <= 0.009:
            continue
        vivos.append(
            {
                "id": int(pedido["id"]),
                "fecha": formatear_fecha(pedido.get("fecha")),
                "detalle": texto_pedido(pedido, por_pedido.get(int(pedido["id"]), []), nombres),
                "total": round(cargo_cuenta(pedido, cliente), 2),
                "saldo": saldo,
            }
        )
    return vivos


def texto_pedido(pedido: dict, lineas: list, nombres: dict) -> str:
    partes = [
        f"{int(item['cantidad'])} x {nombres.get(int(item['producto_id']), 'Producto')}"
        for item in lineas
        if item.get("producto_id") is not None
    ]
    guardado = str(pedido.get("detalle") or "").split(" | ")[0].strip()
    cuerpo = guardado or ", ".join(partes) or "Pedido"
    if len(cuerpo) > 72:
        cuerpo = cuerpo[:69] + "..."
    return f"#{int(pedido['id'])} · {cuerpo}"


def _tabla_pendientes(pendientes: list[dict]) -> None:
    st.markdown("**Pedidos con saldo**")
    if not pendientes:
        st.caption("Este cliente no tiene pedidos con saldo pendiente.")
        return
    encabezado = st.columns([1.1, 2.8, 1, 1.3, 1.4], vertical_alignment="center")
    for titulo, columna in zip(["Fecha", "N° Pedido / Detalle", "Total USD", "Saldo pendiente USD", ""], encabezado):
        if titulo:
            columna.markdown(f"**{titulo}**")
    with st.container(height=360):
        for pedido in pendientes:
            columnas = st.columns([1.1, 2.8, 1, 1.3, 1.4], vertical_alignment="center")
            columnas[0].write(pedido["fecha"])
            columnas[1].write(pedido["detalle"])
            columnas[2].write(dinero(pedido["total"]))
            columnas[3].write(dinero(pedido["saldo"]))
            with columnas[4]:
                if st.button("Cobrar este pedido", key=f"cobrar_pedido_{pedido['id']}", width="stretch"):
                    st.session_state["pago_modo"] = MODO_PEDIDO
                    st.session_state["pago_pedido_id"] = pedido["id"]
                    st.session_state["pago_moneda"] = "USD"
                    st.session_state["pago_monto_usd"] = pedido["saldo"]
                    st.rerun()


def _formulario(sb: Client, cliente: dict, pendientes: list[dict]) -> None:
    with st.container(border=True):
        st.markdown("**Cobro**")
        modo = st.selectbox("Modo de pago", [MODO_GENERAL, MODO_PEDIDO], key="pago_modo")
        pedido_id = None
        if modo == MODO_PEDIDO:
            if not pendientes:
                st.warning("Este cliente no tiene pedidos abiertos para imputar.")
            else:
                ids = [item["id"] for item in pendientes]
                if st.session_state.get("pago_pedido_id") not in ids:
                    st.session_state["pago_pedido_id"] = ids[0]
                pedido_id = st.selectbox(
                    "Pedido",
                    ids,
                    format_func=lambda valor: next(
                        f"{item['detalle']} · {dinero(item['saldo'])}" for item in pendientes if item["id"] == valor
                    ),
                    key="pago_pedido_id",
                )
        moneda = st.segmented_control("Moneda", ["USD", "ARS"], key="pago_moneda", required=True)
        if moneda == "ARS":
            monto_ars = st.number_input("Monto entregado (ARS)", min_value=0.0, step=0.01, key="pago_monto_ars")
            cotizacion = st.number_input("Cotización (ARS por 1 USD)", min_value=0.0, step=0.01, key="pago_cotizacion")
            monto_usd = round(float(monto_ars) / float(cotizacion), 2) if cotizacion > 0 else 0.0
            if monto_ars > 0 and cotizacion > 0:
                st.metric("Equivalente en USD", dinero(monto_usd))
        else:
            cotizacion = 1.0
            monto_usd = st.number_input("Monto entregado (USD)", min_value=0.0, step=0.01, key="pago_monto_usd")
            monto_ars = float(monto_usd)
        notas = st.text_input("Observaciones", key="pago_notas", placeholder="Transferencia Galicia / Efectivo")
        if not st.button("Registrar y Aplicar Pago", type="primary"):
            return
        if moneda is None:
            st.warning("Elegí la moneda del pago.")
            return
        if moneda == "ARS" and cotizacion <= 0:
            st.warning("Para pesos, la cotización tiene que ser mayor a cero.")
            return
        if float(monto_usd) <= 0:
            st.warning("Ingresá un monto mayor a cero.")
            return
        if modo == MODO_PEDIDO and pedido_id is None:
            st.warning("Elegí el pedido al que se imputa el cobro.")
            return
        payload = {
            "cliente_id": int(cliente["id"]),
            "moneda": moneda,
            "monto_original": round(float(monto_ars if moneda == "ARS" else monto_usd), 2),
            "cotizacion": 1.0 if moneda == "USD" else round(float(cotizacion), 2),
            "monto_usd_descontado": round(float(monto_usd), 2),
            "observaciones": str(notas or "").strip() or None,
        }
        if modo == MODO_PEDIDO and pedido_id is not None:
            payload["pedido_id"] = int(pedido_id)
        aviso = registrar_pago(sb, payload)
        if aviso and not aviso.startswith("Se registró"):
            st.error(aviso)
            return
        st.session_state["pago_limpiar"] = True
        texto = f"Pago de {dinero_md(monto_usd)} registrado correctamente para {cliente['nombre']}."
        if aviso:
            avisar("warning", f"{texto} {aviso}")
        avisar("success", texto)
