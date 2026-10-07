import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

SECCIONES = [
    {
        "menu": "Inventario y Costos",
        "icono": "box-seam",
        "material": ":material/inventory_2:",
    },
    {
        "menu": "Clientes",
        "icono": "people",
        "material": ":material/group:",
    },
    {
        "menu": "Nuevas Ventas",
        "icono": "cart-plus",
        "material": ":material/add_shopping_cart:",
    },
    {
        "menu": "Registrar Pago",
        "icono": "credit-card",
        "material": ":material/credit_card:",
    },
    {
        "menu": "Cuentas Corrientes",
        "icono": "file-earmark-text",
        "material": ":material/receipt_long:",
    },
    {
        "menu": "Gastos Operativos",
        "icono": "wallet2",
        "material": ":material/account_balance_wallet:",
    },
    {
        "menu": "Reportes",
        "icono": "bar-chart",
        "material": ":material/bar_chart:",
    },
    {
        "menu": "Configuración",
        "icono": "gear",
        "material": ":material/settings:",
    },
]

ESTILO_MENU = {
    "container": {"padding": "0.15rem 0 0 0", "background-color": "transparent"},
    "icon": {"color": "#52525B", "font-size": "1.05rem"},
    "nav-link": {
        "font-size": "0.92rem",
        "font-weight": "500",
        "text-align": "left",
        "margin": "3px 0",
        "padding": "0.6rem 0.75rem",
        "border-radius": "8px",
        "color": "#18181B",
        "--hover-color": "#F4F4F5",
    },
    "nav-link-selected": {
        "background-color": "#18181B",
        "color": "#FFFFFF",
        "font-weight": "600",
    },
}

ESTILOS = """
<style>
html, body, .stApp, [data-testid="stAppViewContainer"] {
  font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
}
#MainMenu, footer, [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stMainMenu"], .stAppDeployButton {
  display: none !important;
}
/* En Streamlit 1.64 el botón >> vive dentro del encabezado. Si se oculta
   el header o el toolbar, en el celular no queda forma de reabrir el menú. */
header[data-testid="stHeader"],
[data-testid="stToolbar"] {
  background: transparent !important;
  height: 0 !important;
  min-height: 0 !important;
  overflow: visible !important;
  pointer-events: none !important;
  border: 0 !important;
}
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  pointer-events: auto !important;
  position: fixed !important;
  top: 0.6rem !important;
  left: 0.6rem !important;
  z-index: 1000002 !important;
  background: #FFFFFF !important;
  color: #18181B !important;
  border: 1px solid #E4E4E7 !important;
  border-radius: 8px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12) !important;
  width: 2.4rem !important;
  height: 2.4rem !important;
  align-items: center !important;
  justify-content: center !important;
}
.block-container {
  padding-top: 1.5rem;
  padding-bottom: 2.5rem;
  max-width: 1280px;
}
@media (max-width: 768px) {
  [data-testid="stMain"] .block-container {
    padding-top: 3.25rem;
  }
}
section[data-testid="stSidebar"] {
  border-right: 1px solid #E4E4E7;
}
section[data-testid="stSidebar"] .nav-link-selected,
section[data-testid="stSidebar"] .nav-link-selected span,
section[data-testid="stSidebar"] .nav-link-selected i {
  color: #FFFFFF !important;
}
[data-testid="stMetric"],
[data-testid="stVerticalBlockBorderWrapper"] {
  background: #FFFFFF;
  border: 1px solid #E4E4E7 !important;
  border-radius: 12px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
[data-testid="stMetricLabel"] p {
  font-size: 0.78rem;
  font-weight: 500;
  color: #71717A;
}
[data-testid="stMetricValue"] {
  font-weight: 650;
  letter-spacing: -0.03em;
}
[data-testid="stMetricDelta"] {
  color: #71717A;
  font-size: 0.75rem;
}
.stButton > button,
.stFormSubmitButton > button,
.stDownloadButton > button {
  border-radius: 8px;
  padding: 0.45rem 0.95rem;
  font-weight: 550;
  transition: transform 0.15s ease, box-shadow 0.15s ease, background-color 0.15s ease;
}
.stButton > button:hover,
.stFormSubmitButton > button:hover,
.stDownloadButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
[data-testid="stDataFrame"] {
  background: #FFFFFF;
  border: 1px solid #E4E4E7;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
  border-radius: 12px;
}
.st-key-banner_simulacion {
  position: sticky;
  top: 0.75rem;
  z-index: 30;
}
.st-key-banner_simulacion [data-testid="stVerticalBlockBorderWrapper"] {
  background: #FFFBEB !important;
  border-color: #D97706 !important;
}
</style>
"""


def aplicar_estilos() -> None:
    st.markdown(ESTILOS, unsafe_allow_html=True)


def marcar_cierre() -> None:
    st.session_state["cerrar_sesion"] = True


def _marca(detalle: str) -> None:
    st.markdown("**La Despensa de PUFFCO**")
    st.caption(detalle)


def _boton_salir() -> None:
    st.button(
        "Cerrar sesión",
        key="btn_cerrar_sesion",
        icon=":material/logout:",
        width="stretch",
        on_click=marcar_cierre,
    )


def menu_lateral(email: str | None = None) -> dict:
    opciones = [item["menu"] for item in SECCIONES]
    with st.sidebar:
        _marca("Micro ERP")
        seccion = option_menu(
            None,
            opciones,
            icons=[item["icono"] for item in SECCIONES],
            default_index=0,
            styles=ESTILO_MENU,
            key="menu_principal",
        )
        if email:
            st.divider()
            st.caption(email)
            _boton_salir()
    if seccion not in opciones:
        seccion = opciones[0]
    return next(item for item in SECCIONES if item["menu"] == seccion)


def barra_invitado() -> tuple[str, str] | None:
    with st.sidebar:
        _marca("Catálogo público")
        st.divider()
        st.markdown("**Ingresar**")
        aviso = st.session_state.pop("aviso_auth", None)
        if aviso:
            st.warning(aviso)
        with st.form("ingreso"):
            email = st.text_input("Email", placeholder="nombre@correo.com")
            clave = st.text_input("Contraseña", type="password")
            enviar = st.form_submit_button(
                "Ingresar",
                type="primary",
                icon=":material/login:",
                width="stretch",
            )
        st.caption("Administrador o cliente. Sin sesión no se muestran precios ni stock.")
    if enviar:
        return email.strip(), clave
    return None


def _formulario_clave(sufijo: str) -> str | None:
    with st.form(f"form_clave_{sufijo}"):
        nueva = st.text_input("Nueva contraseña", type="password")
        repetir = st.text_input("Repetir contraseña", type="password")
        enviar = st.form_submit_button("Guardar contraseña", type="primary")
    if not enviar:
        return None
    if not nueva:
        st.warning("Escribí la nueva contraseña.")
        return None
    if nueva != repetir:
        st.warning("Las contraseñas no coinciden.")
        return None
    if len(nueva) < 8:
        st.warning("Usá al menos 8 caracteres.")
        return None
    return nueva


def panel_clave_cliente(usuario: dict) -> str | None:
    if usuario.get("rol") != "cliente":
        return None
    propuesta = None
    with st.sidebar:
        with st.expander("Cambiar contraseña"):
            propuesta = _formulario_clave("perfil")
    if usuario.get("debe_cambiar_clave") and not st.session_state.get("omitir_cambio_clave"):
        with st.container(border=True):
            st.markdown("**Tenés una clave temporal.**")
            st.caption("Podés cambiarla ahora o seguir con la que te pasó el administrador.")
            if propuesta is None:
                propuesta = _formulario_clave("aviso")
            if st.button("Ahora no", key="omitir_clave"):
                st.session_state["omitir_cambio_clave"] = True
                st.rerun()
    return propuesta


def banner_simulacion(nombre: str) -> bool:
    with st.container(border=True, key="banner_simulacion"):
        texto, accion = st.columns([3.4, 1.7], vertical_alignment="center")
        texto.markdown(f":material/warning: **Estás simulando la vista del cliente: {nombre}**")
        return accion.button(
            "Volver a vista administrador",
            icon=":material/arrow_back:",
            type="primary",
            width="stretch",
            key="volver_admin",
        )


def barra_cliente(usuario: dict) -> None:
    cliente = usuario["cliente"]
    with st.sidebar:
        _marca("Portal de clientes")
        st.divider()
        st.markdown(f"**{cliente['nombre']}**")
        st.caption("Distribuidor" if cliente.get("es_distribuidor") else "Cliente")
        st.caption(usuario["email"])
        _boton_salir()


def avisar(nivel: str, texto: str) -> None:
    st.session_state["aviso"] = (nivel, texto)
    st.rerun()


def mostrar_aviso() -> None:
    aviso = st.session_state.pop("aviso", None)
    if not aviso:
        return
    nivel, texto = aviso
    if nivel == "success":
        st.success(texto)
    elif nivel == "warning":
        st.warning(texto)
    else:
        st.error(texto)


def mostrar_kpis(tarjetas: list[tuple[str, str, str]]) -> None:
    with st.container(horizontal=True):
        for etiqueta, valor, detalle in tarjetas:
            st.metric(
                etiqueta,
                valor,
                detalle,
                delta_color="gray",
                delta_arrow="off",
                border=True,
            )


def dinero(valor) -> str:
    return f"US$ {float(valor):,.2f}"


def dinero_con_signo(valor) -> str:
    numero = round(float(valor or 0), 2)
    if numero < 0:
        return f"-US$ {abs(numero):,.2f}"
    return f"US$ {numero:,.2f}"


def mostrar_libro(filas: list[dict]) -> None:
    if not filas:
        st.info("Todavía no hay movimientos en la cuenta.")
        return
    tabla = pd.DataFrame(
        [
            {
                "Fecha": fila["Fecha"],
                "Tipo / Comprobante": fila["Tipo / Comprobante"],
                "Detalle": fila["Detalle"],
                "Importe USD": dinero_con_signo(fila["importe"]),
                "Saldo vivo (US$)": dinero_con_signo(fila["Saldo vivo (US$)"]),
            }
            for fila in filas
        ]
    )
    st.caption("Del movimiento más reciente al más antiguo. El saldo vivo es el acumulado después de cada operación.")
    st.dataframe(
        tabla,
        hide_index=True,
        width="stretch",
        column_config={
            "Fecha": st.column_config.TextColumn("Fecha", width="small"),
            "Tipo / Comprobante": st.column_config.TextColumn("Tipo / Comprobante", width="medium"),
            "Detalle": st.column_config.TextColumn("Detalle", width="large"),
            "Importe USD": st.column_config.TextColumn("Importe USD", width="small"),
            "Saldo vivo (US$)": st.column_config.TextColumn("Saldo vivo (US$)", width="small"),
        },
    )


def etiqueta_busqueda(producto: dict, precio: float) -> str:
    partes = [str(producto.get("nombre") or "").strip() or "Sin nombre"]
    marca = str(producto.get("marca") or "").strip()
    categoria = str(producto.get("categoria") or "").strip()
    if marca:
        partes.append(marca)
    if categoria:
        partes.append(categoria)
    partes.append(f"stock {int(producto.get('stock_actual') or 0)}")
    partes.append(dinero(precio))
    return " · ".join(partes)


def dinero_md(valor) -> str:
    return dinero(valor).replace("$", r"\$")


def estilo_stock(valor) -> str:
    cantidad = int(valor or 0)
    if cantidad <= 0:
        fondo, tinta = "#FEE2E2", "#B91C1C"
    elif cantidad <= 2:
        fondo, tinta = "#FEF3C7", "#A16207"
    else:
        fondo, tinta = "#DCFCE7", "#15803D"
    return f"background-color: {fondo}; color: {tinta}; font-weight: 700;"


def estilo_tipo_cliente(valor) -> str:
    if valor == "Distribuidor":
        return "background-color: #EDE9FE; color: #6D28D9; font-weight: 600;"
    return "background-color: #F4F4F5; color: #3F3F46; font-weight: 600;"


def fila_click(clave: str) -> int | None:
    click = st.session_state.get(clave)
    if click is None:
        return None
    fila = click["row"] if isinstance(click, dict) else getattr(click, "row", None)
    if fila is None:
        return None
    return int(fila)


def columna_usd(etiqueta: str):
    return st.column_config.NumberColumn(etiqueta, format="US$ %,.2f", alignment="right")


def miniatura(url, ancho: int = 64) -> None:
    limpia = str(url or "").strip()
    if limpia:
        st.image(limpia, width=ancho)
        return
    st.markdown(
        f"<div style='width:{ancho}px;height:{ancho}px;border:1px dashed #E4E4E7;border-radius:8px;background:#FAFAFA'></div>",
        unsafe_allow_html=True,
    )


def checkbox_tiene_ficha(clave: str) -> None:
    st.checkbox(
        "Tiene ficha",
        key=clave,
        help="Si está marcado, el saldo de este cliente entra en la deuda global.",
    )


def sembrar(clave: str, valor) -> None:
    if clave not in st.session_state:
        st.session_state[clave] = valor
