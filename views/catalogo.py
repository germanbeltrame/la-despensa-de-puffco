import pandas as pd
import streamlit as st

from calculos import precio_de_venta
from database import esta_activo, leer_catalogo_cliente, leer_catalogo_publico, texto_error
from ui import avisar, dinero, miniatura

POR_PAGINA = 12
ANCHO_TARJETA = 250
ALTO_FOTO = 150


def _foto(url) -> str | None:
    texto = str(url or "").strip()
    if texto.startswith("https://") or texto.startswith("http://"):
        return texto.replace('"', "").replace("'", "")
    return None


@st.dialog("Foto del producto", width="large")
def _ampliar_foto(nombre: str, url: str) -> None:
    st.image(url, width="stretch")
    st.caption(nombre)


def _foto_catalogo(cliente_id: int, producto_id: int, nombre: str, url) -> None:
    segura = _foto(url)
    clave = f"cat_foto_{cliente_id}_{producto_id}"
    if not segura:
        miniatura(None, ALTO_FOTO)
        return
    st.markdown(
        f"""
        <style>
        .st-key-{clave} button {{
          background-image: url("{segura}");
          background-size: cover;
          background-position: center;
          width: 100% !important;
          height: {ALTO_FOTO}px;
          padding: 0 !important;
          border: 0 !important;
          border-radius: 8px !important;
          color: transparent !important;
          box-shadow: none !important;
        }}
        .st-key-{clave} button p,
        .st-key-{clave} button span {{
          visibility: hidden;
        }}
        .st-key-{clave} button:hover {{
          transform: none;
          filter: brightness(0.94);
          box-shadow: none !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Ampliar foto", key=clave, width="stretch"):
        _ampliar_foto(nombre, segura)


def _opciones(productos: list[dict], campo: str) -> list[str]:
    valores = {(item.get(campo) or "").strip() for item in productos}
    return ["Todas", *sorted(valor for valor in valores if valor)]


def _filtros(productos: list[dict]) -> tuple[str, str, str]:
    categorias = _opciones(productos, "categoria")
    marcas = _opciones(productos, "marca")
    if str(st.session_state.get("cat_buscar") or "").strip():
        st.session_state["cat_categoria"] = "Todas"
        st.session_state["cat_marca"] = "Todas"
    if st.session_state.get("cat_categoria") not in categorias:
        st.session_state["cat_categoria"] = "Todas"
    if st.session_state.get("cat_marca") not in marcas:
        st.session_state["cat_marca"] = "Todas"
    with st.container(horizontal=True, vertical_alignment="bottom"):
        busqueda = st.text_input(
            "Buscar",
            key="cat_buscar",
            placeholder="Nombre, marca o categoría",
            type="search",
            live=True,
            width="stretch",
        )
        categoria = st.selectbox("Categoría", categorias, key="cat_categoria", width="stretch")
        marca = st.selectbox("Marca", marcas, key="cat_marca", width="stretch")
    texto = (busqueda or "").strip().lower()
    if texto:
        return texto, "Todas", "Todas"
    return texto, categoria, marca


def _coincide(producto: dict, texto: str, categoria: str, marca: str) -> bool:
    nombre = producto.get("nombre") or ""
    marca_producto = (producto.get("marca") or "").strip()
    categoria_producto = (producto.get("categoria") or "").strip()
    if texto and texto not in " ".join((nombre, marca_producto, categoria_producto)).lower():
        return False
    if categoria != "Todas" and categoria_producto != categoria:
        return False
    if marca != "Todas" and marca_producto != marca:
        return False
    return True


def _carrito(cliente_id: int) -> dict:
    clave = f"carrito_cliente_{int(cliente_id)}"
    st.session_state.setdefault(clave, {})
    return st.session_state[clave]


def _catalogo_publico(productos: list[dict]) -> None:
    texto, categoria, marca = _filtros(productos)
    filas = []
    for producto in productos:
        if not _coincide(producto, texto, categoria, marca):
            continue
        filas.append(
            {
                "Foto": _foto(producto.get("imagen_url")),
                "Nombre": producto.get("nombre") or "",
                "Marca": (producto.get("marca") or "").strip(),
                "Categoría": (producto.get("categoria") or "").strip(),
            }
        )
    st.caption(f"{len(filas)} productos")
    if not productos:
        st.warning("Todavía no hay productos cargados.")
        return
    if not filas:
        st.warning("Ningún producto coincide con los filtros.")
        return
    st.dataframe(
        pd.DataFrame(filas),
        hide_index=True,
        width="stretch",
        height="auto" if len(filas) <= 12 else 560,
        row_height=52,
        column_config={
            "Foto": st.column_config.ImageColumn("Foto", width="small"),
            "Nombre": st.column_config.TextColumn("Nombre", width="large"),
            "Marca": st.column_config.TextColumn("Marca"),
            "Categoría": st.column_config.TextColumn("Categoría"),
        },
        column_order=["Foto", "Nombre", "Marca", "Categoría"],
        key="catalogo_publico",
    )


def _cantidad(cliente_id: int, producto_id: int, libre: int) -> int:
    clave = f"cat_cant_{cliente_id}_{producto_id}"
    tope = max(libre, 1)
    actual = int(st.session_state.get(clave) or 1)
    actual = min(max(actual, 1), tope)
    st.session_state[clave] = actual
    return actual


def _agregar(cliente: dict, producto: dict, cantidad: int) -> None:
    carrito = _carrito(int(cliente["id"]))
    clave = str(int(producto["id"]))
    en_carrito = int((carrito.get(clave) or {}).get("cantidad") or 0)
    libre = int(producto.get("stock_actual") or 0) - en_carrito
    nombre = producto.get("nombre") or "Ese producto"
    if libre <= 0 or cantidad > libre:
        st.warning(f"No hay stock libre suficiente de {nombre}.")
        return
    precio, _origen = precio_de_venta(producto, cliente)
    actual = carrito.get(clave, {"nombre": nombre, "cantidad": 0, "precio": precio})
    actual["nombre"] = nombre
    actual["precio"] = round(float(precio), 2)
    actual["cantidad"] = en_carrito + int(cantidad)
    carrito[clave] = actual
    st.rerun()


def _tarjeta(cliente: dict, producto: dict) -> None:
    producto_id = int(producto["id"])
    cliente_id = int(cliente["id"])
    nombre = producto.get("nombre") or "Sin nombre"
    marca = (producto.get("marca") or "").strip() or "Sin marca"
    precio, _origen = precio_de_venta(producto, cliente)
    en_carrito = int((_carrito(cliente_id).get(str(producto_id)) or {}).get("cantidad") or 0)
    libre = int(producto.get("stock_actual") or 0) - en_carrito
    cantidad = _cantidad(cliente_id, producto_id, libre)
    _foto_catalogo(cliente_id, producto_id, nombre, producto.get("imagen_url"))
    st.markdown(nombre)
    st.caption(f"{marca} · {dinero(precio)}")
    if libre <= 0:
        st.caption("Sin stock.")
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("−", key=f"cat_menos_{cliente_id}_{producto_id}", disabled=cantidad <= 1 or libre <= 0):
            st.session_state[f"cat_cant_{cliente_id}_{producto_id}"] = cantidad - 1
            st.rerun()
        st.markdown(str(cantidad))
        if st.button("+", key=f"cat_mas_{cliente_id}_{producto_id}", disabled=libre <= 0 or cantidad >= max(libre, 1)):
            st.session_state[f"cat_cant_{cliente_id}_{producto_id}"] = cantidad + 1
            st.rerun()
        if st.button(
            "Agregar",
            icon=":material/add_shopping_cart:",
            key=f"cat_agregar_{cliente_id}_{producto_id}",
            disabled=libre <= 0,
        ):
            _agregar(cliente, producto, cantidad)


def _pagina(cliente_id: int, firma: str, total: int) -> tuple[int, int]:
    clave_firma = f"cat_firma_{cliente_id}"
    clave_pagina = f"cat_pagina_{cliente_id}"
    if st.session_state.get(clave_firma) != firma:
        st.session_state[clave_firma] = firma
        st.session_state[clave_pagina] = 0
    paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)
    pagina = min(int(st.session_state.get(clave_pagina) or 0), paginas - 1)
    st.session_state[clave_pagina] = pagina
    if paginas > 1:
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button("Anterior", disabled=pagina <= 0, key=f"cat_anterior_{cliente_id}"):
                st.session_state[clave_pagina] = pagina - 1
                st.rerun()
            st.caption(f"{pagina * POR_PAGINA + 1}–{min(total, (pagina + 1) * POR_PAGINA)} de {total}")
            if st.button("Siguiente", disabled=pagina >= paginas - 1, key=f"cat_siguiente_{cliente_id}"):
                st.session_state[clave_pagina] = pagina + 1
                st.rerun()
    inicio = pagina * POR_PAGINA
    return inicio, inicio + POR_PAGINA


def _catalogo_cliente(productos: list[dict], cliente: dict) -> None:
    texto, categoria, marca = _filtros(productos)
    filtrados = [item for item in productos if item.get("id") is not None and _coincide(item, texto, categoria, marca)]
    st.caption(f"{len(filtrados)} productos")
    if not productos:
        st.warning("Todavía no hay productos cargados.")
        return
    if not filtrados:
        st.warning("Ningún producto coincide con los filtros.")
        return
    firma = f"{texto}|{categoria}|{marca}|{len(filtrados)}"
    inicio, fin = _pagina(int(cliente["id"]), firma, len(filtrados))
    with st.container(horizontal=True):
        for producto in filtrados[inicio:fin]:
            with st.container(border=True, width=ANCHO_TARJETA):
                _tarjeta(cliente, producto)


def _panel_carrito(cliente: dict) -> None:
    carrito = _carrito(int(cliente["id"]))
    st.subheader("Carrito", icon=":material/shopping_cart:")
    with st.container(border=True):
        if not carrito:
            st.caption("Todavía no agregaste productos.")
        total = 0.0
        for clave, linea in list(carrito.items()):
            subtotal = round(float(linea["precio"]) * int(linea["cantidad"]), 2)
            total += subtotal
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{linea['nombre']}** · {int(linea['cantidad'])}")
                st.write(dinero(subtotal))
                if st.button("Quitar", key=f"catalogo_quitar_{cliente['id']}_{clave}", type="tertiary"):
                    carrito.pop(clave, None)
                    st.rerun()
        st.metric("Total del pedido", dinero(round(total, 2)))
        if st.button(
            "Enviar pedido a aprobación",
            type="primary",
            icon=":material/rocket_launch:",
            width="stretch",
            disabled=not carrito,
            key=f"enviar_pedido_{cliente['id']}",
        ):
            carrito.clear()
            avisar(
                "success",
                "Pedido enviado a aprobación. No se descontó stock ni se cargó en la cuenta corriente.",
            )


def pagina_catalogo(cliente: dict | None) -> None:
    try:
        if cliente is None:
            productos = leer_catalogo_publico()
        else:
            productos = leer_catalogo_cliente()
    except Exception as exc:
        st.error(f"No se pudo leer el catálogo. {texto_error(exc)}")
        return
    visibles = [item for item in productos if esta_activo(item)]
    visibles.sort(key=lambda item: (item.get("nombre") or "").lower())
    if cliente is None:
        _catalogo_publico(visibles)
        return
    _catalogo_cliente(visibles, cliente)
    _panel_carrito(cliente)
