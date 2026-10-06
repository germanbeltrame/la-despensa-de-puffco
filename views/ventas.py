import streamlit as st
from supabase import Client

from calculos import factor_ganancia, precio_de_venta
from database import (
    crear_pedido,
    datos_cliente,
    esta_activo,
    insertar_cliente,
    leer_clientes,
    leer_fletes,
    leer_productos,
)
from ui import avisar, checkbox_tiene_ficha, dinero, etiqueta_busqueda, miniatura

FACTOR_GASTOS = 1.065


def alta_rapida_cliente(sb: Client) -> None:
    with st.popover("+ Nuevo cliente", type="primary", width="stretch"):
        with st.form("alta_rapida_cliente", clear_on_submit=True):
            nombre = st.text_input("Nombre del cliente")
            es_distribuidor = st.checkbox("Distribuidor")
            checkbox_tiene_ficha("alta_rapida_ficha")
            guardar = st.form_submit_button("Guardar", type="primary")
        if not guardar:
            return
        nuevo_id, error = insertar_cliente(
            sb,
            nombre,
            es_distribuidor,
            tiene_ficha=bool(st.session_state.get("alta_rapida_ficha")),
        )
        if error:
            st.warning(error)
            return
        st.session_state["cliente_venta_pendiente"] = nuevo_id
        avisar("success", f"Cliente {datos_cliente(nombre, es_distribuidor)['nombre']} registrado y seleccionado.")


def partida(valor) -> tuple[int, float | None]:
    if isinstance(valor, dict):
        return int(valor.get("cantidad") or 0), float(valor.get("precio") or 0)
    return int(valor or 0), None


def tarifa_producto(producto: dict, flete_por_id: dict) -> float:
    tarifa = producto.get("precio_kg")
    if tarifa not in (None, ""):
        return float(tarifa)
    if not producto.get("flete_id"):
        return 0.0
    flete = flete_por_id.get(int(producto["flete_id"]))
    return float(flete["costo_usd_kg"]) if flete else 0.0


def costo_unitario_venta(producto: dict, flete_por_id: dict) -> float:
    if producto.get("calcular_costo") is False and producto.get("costo_total_usd") not in (None, ""):
        return round(float(producto["costo_total_usd"]), 2)
    base = float(producto.get("costo_fob") or 0) + float(producto.get("peso_kg") or 0) * tarifa_producto(
        producto, flete_por_id
    )
    return round(base * FACTOR_GASTOS, 2)


def sembrar_numero(clave: str, valor, tope: int | None = None) -> None:
    if clave not in st.session_state:
        st.session_state[clave] = valor
    if tope is not None and int(st.session_state[clave]) > tope:
        st.session_state[clave] = tope


def pagina_ventas(sb: Client) -> None:
    if st.session_state.pop("venta_limpiar", False):
        st.session_state["venta_notas"] = ""
        st.session_state["carrito"] = {}

    productos = leer_productos(sb)
    clientes = leer_clientes(sb)
    fletes = leer_fletes(sb)
    if productos is None or clientes is None or fletes is None:
        return

    productos = [item for item in productos if esta_activo(item)]
    clientes = sorted(
        [item for item in clientes if esta_activo(item)],
        key=lambda item: item["nombre"].lower(),
    )
    flete_por_id = {int(item["id"]): item for item in fletes}
    st.session_state.setdefault("carrito", {})
    por_id = {int(item["id"]): item for item in productos}

    izquierda, derecha = st.columns([2, 1])
    with izquierda:
        cliente = _cabecera_cliente(sb, clientes)
        if cliente is None:
            lineas = []
        else:
            _fila_carga(productos, cliente, flete_por_id)
            lineas = _carrito(por_id, cliente, flete_por_id)

    total_venta = round(sum(linea["precio"] * linea["cantidad"] for linea in lineas), 2)
    costo_total = round(sum(linea["costo"] * linea["cantidad"] for linea in lineas), 2)
    ganancia_bruta = round(total_venta - costo_total, 2)
    factor = factor_ganancia(cliente) if cliente else 1.0
    ganancia_real = round(ganancia_bruta * factor, 2)
    margen = round(ganancia_real / total_venta * 100, 1) if total_venta else 0.0

    with derecha:
        _resumen(sb, cliente, lineas, total_venta, costo_total, ganancia_bruta, ganancia_real, margen)


def _tipo_cliente(cliente: dict) -> str:
    return "Distribuidor" if cliente.get("es_distribuidor") else "Cliente Estándar"


def _cabecera_cliente(sb: Client, clientes: list) -> dict | None:
    if not clientes:
        alta_rapida_cliente(sb)
        st.warning("Todavía no hay clientes.")
        return None
    opciones = [int(item["id"]) for item in clientes]
    preferido = st.session_state.pop("cliente_venta_pendiente", None)
    if preferido in opciones:
        st.session_state["cliente_venta_id"] = preferido
    elif st.session_state.get("cliente_venta_id") not in opciones:
        st.session_state["cliente_venta_id"] = opciones[0]
    fijo = st.session_state.get("venta_cliente_fijo")
    if fijo not in opciones:
        fijo = None
    if fijo is not None:
        cliente = next(item for item in clientes if int(item["id"]) == int(fijo))
        with st.container(border=True):
            columna_nombre, columna_cancelar = st.columns([3, 1.5], vertical_alignment="center")
            columna_nombre.markdown(f"**{cliente['nombre']}** [{_tipo_cliente(cliente)}]")
            if columna_cancelar.button("Cambiar / Cancelar cliente", width="stretch"):
                st.session_state["venta_cliente_fijo"] = None
                st.session_state["venta_limpiar"] = True
                st.rerun()
        return cliente
    columna_cliente, columna_alta = st.columns([3, 1.2], vertical_alignment="bottom")
    with columna_cliente:
        cliente_id = st.selectbox(
            "Cliente",
            opciones,
            format_func=lambda valor: next(item["nombre"] for item in clientes if int(item["id"]) == valor),
            key="cliente_venta_id",
        )
    with columna_alta:
        alta_rapida_cliente(sb)
    if st.button("Confirmar Cliente", type="primary"):
        st.session_state["venta_cliente_fijo"] = int(cliente_id)
        st.rerun()
    return None


def _fila_carga(productos: list, cliente: dict | None, flete_por_id: dict) -> None:
    if not productos:
        st.warning("No hay productos en el inventario.")
        return
    ordenados = sorted(productos, key=lambda item: (item.get("nombre") or "").lower())
    por_id = {int(item["id"]): item for item in ordenados}
    ids = list(por_id)
    elegido = st.session_state.get("venta_producto_id")
    if elegido is not None and int(elegido) not in por_id:
        st.session_state["venta_producto_id"] = None
    producto_id = st.selectbox(
        "Buscar producto",
        ids,
        index=None,
        placeholder="puffco, proxy, pipa…",
        format_func=lambda valor: _etiqueta_producto(int(valor), por_id, cliente),
        filter_mode="contains",
        key="venta_producto_id",
        help="Escribí cualquier fragmento. La lista muestra todos los productos que coinciden, con stock y precio.",
    )
    if producto_id is None:
        return
    producto = por_id[int(producto_id)]
    sugerido, _origen = precio_de_venta(producto, cliente)
    origen = (int(producto["id"]), int(cliente["id"]) if cliente else 0)
    if st.session_state.get("venta_precio_origen") != origen:
        st.session_state["venta_precio"] = round(sugerido, 2)
        st.session_state["venta_cantidad"] = 1
        st.session_state["venta_precio_origen"] = origen
    en_carrito, _precio_previo = partida(st.session_state.carrito.get(int(producto["id"])))
    libre = int(producto.get("stock_actual") or 0) - en_carrito
    columna_foto, columna_cant, columna_precio, columna_boton = st.columns(
        [0.55, 0.9, 1.15, 1.3],
        vertical_alignment="bottom",
    )
    with columna_foto:
        miniatura(producto.get("imagen_url"), 48)
    with columna_cant:
        sembrar_numero("venta_cantidad", 1, max(libre, 1))
        cantidad = st.number_input(
            "Cantidad",
            min_value=1,
            max_value=max(libre, 1),
            step=1,
            key="venta_cantidad",
            disabled=libre <= 0,
        )
    with columna_precio:
        sembrar_numero("venta_precio", round(sugerido, 2))
        precio = st.number_input("Precio unitario", min_value=0.0, step=0.01, key="venta_precio")
    with columna_boton:
        agregar = st.button("+ Agregar al carrito", type="primary", disabled=libre <= 0, width="stretch")
    if libre <= 0:
        st.caption(f"{producto['nombre']} no tiene stock libre.")
    if not agregar or libre <= 0:
        return
    pid = int(producto["id"])
    st.session_state.carrito[pid] = {
        "cantidad": en_carrito + min(int(cantidad), libre),
        "precio": round(float(precio), 2),
    }
    st.rerun()


def _etiqueta_producto(valor: int, por_id: dict, cliente: dict | None) -> str:
    producto = por_id[int(valor)]
    precio, _origen = precio_de_venta(producto, cliente)
    return etiqueta_busqueda(producto, precio)


def _carrito(por_id: dict, cliente: dict | None, flete_por_id: dict) -> list:
    lineas = []
    faltantes = []
    for producto_id, guardado in list(st.session_state.carrito.items()):
        producto = por_id.get(int(producto_id))
        if producto is None:
            faltantes.append(int(producto_id))
            continue
        cantidad, precio_cargado = partida(guardado)
        if cantidad <= 0:
            faltantes.append(int(producto_id))
            continue
        if precio_cargado is None:
            precio_cargado, _origen = precio_de_venta(producto, cliente)
        lineas.append(
            {
                "producto": producto,
                "cantidad": cantidad,
                "precio": round(float(precio_cargado), 2),
                "costo": costo_unitario_venta(producto, flete_por_id),
            }
        )
    for producto_id in faltantes:
        st.session_state.carrito.pop(producto_id, None)
    if faltantes:
        st.warning("Se quitaron del carrito productos que ya no están en el inventario.")

    st.markdown("**Carrito**")
    if not lineas:
        st.caption("El carrito está vacío.")
        return []

    encabezado = st.columns([0.45, 2.1, 0.8, 1, 1, 0.9], vertical_alignment="center")
    for titulo, columna in zip(
        ["Foto", "Producto", "Cantidad", "Precio unit.", "Subtotal", ""],
        encabezado,
    ):
        if titulo:
            columna.markdown(f"**{titulo}**")
    for linea in lineas:
        producto = linea["producto"]
        pid = int(producto["id"])
        columnas = st.columns([0.45, 2.1, 0.8, 1, 1, 0.9], vertical_alignment="center")
        with columnas[0]:
            miniatura(producto.get("imagen_url"), 40)
        columnas[1].write(producto["nombre"])
        columnas[2].write(str(linea["cantidad"]))
        columnas[3].write(dinero(linea["precio"]))
        columnas[4].write(dinero(linea["precio"] * linea["cantidad"]))
        with columnas[5]:
            if st.button("Eliminar", key=f"quitar_{pid}", width="stretch"):
                st.session_state.carrito.pop(pid, None)
                st.rerun()
    return lineas


def _resumen(
    sb: Client,
    cliente: dict | None,
    lineas: list,
    total_venta: float,
    costo_total: float,
    ganancia_bruta: float,
    ganancia_real: float,
    margen: float,
) -> None:
    with st.container(border=True):
        st.metric("Total venta", dinero(total_venta))
        st.metric("Costo", dinero(costo_total))
        st.markdown("**Ganancia real**")
        st.markdown(
            (
                f"<p style='color:#16A34A;font-size:1.8rem;font-weight:700;margin:0 0 0.6rem 0'>"
                f"{dinero(ganancia_real)}</p>"
            ),
            unsafe_allow_html=True,
        )
        st.metric("Margen %", f"{margen:.1f}%")
        notas = st.text_area("Notas / Observaciones", key="venta_notas")
        if st.button("Confirmar Venta", type="primary", width="stretch"):
            _confirmar(sb, cliente, lineas, total_venta, costo_total, ganancia_bruta, ganancia_real, notas)


def _confirmar(
    sb: Client,
    cliente: dict | None,
    lineas: list,
    total_venta: float,
    costo_total: float,
    ganancia_bruta: float,
    ganancia_real: float,
    notas: str,
) -> None:
    if cliente is None:
        st.warning("Seleccioná un cliente.")
        return
    if not lineas:
        st.warning("El carrito está vacío.")
        return
    problemas = []
    for linea in lineas:
        producto = linea["producto"]
        stock = int(producto.get("stock_actual") or 0)
        if linea["cantidad"] > stock:
            problemas.append(f"{producto['nombre']} pide {linea['cantidad']} y hay stock {stock}")
    if problemas:
        st.warning("No se puede confirmar. " + "; ".join(problemas) + ".")
        return
    error, errores_stock = crear_pedido(
        sb,
        int(cliente["id"]),
        total_venta,
        costo_total,
        ganancia_bruta,
        ganancia_real,
        lineas,
        notas,
    )
    if error:
        st.error(error)
        return
    st.session_state["venta_limpiar"] = True
    st.session_state["carrito"] = {}
    if errores_stock:
        avisar(
            "warning",
            "Venta confirmada. Ganancia: "
            + dinero(ganancia_real)
            + ". No se pudo descontar el stock de: "
            + ", ".join(errores_stock)
            + ".",
        )
    avisar("success", f"Venta confirmada. Ganancia: {dinero(ganancia_real)}")
