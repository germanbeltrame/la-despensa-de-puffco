import streamlit as st

from auth import CLAVE_SESION, cambiar_clave_cliente, cerrar_sesion, iniciar_sesion, usuario_actual
from database import cliente_nuevo, conectar, leer_cliente_por_id, texto_error
from ui import (
    aplicar_estilos,
    banner_simulacion,
    barra_cliente,
    barra_invitado,
    menu_lateral,
    mostrar_aviso,
    panel_clave_cliente,
)
from views.catalogo import pagina_catalogo
from views.configuracion import pagina_configuracion
from views.clientes import pagina_clientes
from views.cuentas_corrientes import pagina_cuentas
from views.gastos import pagina_gastos
from views.inventario import pagina_inventario
from views.pagos import pagina_pagos
from views.portal import pagina_portal
from views.reportes import pagina_reportes
from views.ventas import pagina_ventas

def _cliente_con_sesion():
    """Cliente de datos con el JWT del login, para que RLS lo vea como authenticated."""
    sesion = st.session_state.get(CLAVE_SESION) or {}
    token = sesion.get("access_token")
    sb = cliente_nuevo()
    if token:
        sb.postgrest.auth(token)
    return sb


VISTAS = {
    "Inventario y Costos": pagina_inventario,
    "Clientes": pagina_clientes,
    "Nuevas Ventas": pagina_ventas,
    "Registrar Pago": pagina_pagos,
    "Cuentas Corrientes": pagina_cuentas,
    "Gastos Operativos": pagina_gastos,
    "Reportes": pagina_reportes,
    "Configuración": pagina_configuracion,
}


def main() -> None:
    st.set_page_config(
        page_title="La Despensa de PUFFCO",
        page_icon=":material/storefront:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    aplicar_estilos()
    st.session_state.setdefault("carrito", {})
    if st.session_state.pop("cerrar_sesion", False):
        cerrar_sesion()
    try:
        sb = conectar()
    except Exception as exc:
        st.error(f"No se pudo conectar con Supabase. {texto_error(exc)}")
        st.stop()

    usuario = usuario_actual(sb)
    if usuario is not None:
        sb = _cliente_con_sesion()
    if usuario is None:
        credenciales = barra_invitado()
        if credenciales:
            email, clave = credenciales
            try:
                iniciar_sesion(sb, email, clave)
            except ValueError as exc:
                st.sidebar.error(str(exc))
            except Exception:
                st.sidebar.error("No se pudo iniciar sesión.")
            else:
                st.rerun()
        st.title("Catálogo", icon=":material/storefront:")
        st.caption("Fotos, marca y categoría. Los precios y el stock se ven con la sesión iniciada.")
        mostrar_aviso()
        pagina_catalogo(None)
        return

    if usuario["rol"] == "admin":
        simulado = _cliente_simulado(sb)
        if simulado is not None:
            _portal(sb, simulado, usuario, simulacion=True)
            return
        actual = menu_lateral(usuario["email"])
        st.title(actual["menu"], icon=actual["material"])
        mostrar_aviso()
        VISTAS[actual["menu"]](sb)
        return

    _portal(sb, usuario["cliente"], usuario, simulacion=False)


def _cliente_simulado(sb):
    valor = st.session_state.get("impersonated_client_id")
    if valor in (None, ""):
        return None
    try:
        cliente_id = int(valor)
    except (TypeError, ValueError):
        st.session_state.pop("impersonated_client_id", None)
        return None
    try:
        cliente = leer_cliente_por_id(sb, cliente_id)
    except Exception as exc:
        st.error(f"No se pudo abrir la vista del cliente. {texto_error(exc)}")
        st.stop()
    if not cliente:
        st.session_state.pop("impersonated_client_id", None)
        return None
    return cliente


def _portal(sb, cliente: dict, usuario: dict, simulacion: bool) -> None:
    if simulacion:
        with st.sidebar:
            st.markdown("**La Despensa de PUFFCO**")
            st.caption("Vista de cliente")
            st.markdown(f"**{cliente['nombre']}**")
        if banner_simulacion(cliente["nombre"]):
            st.session_state.pop("impersonated_client_id", None)
            st.rerun()
    else:
        barra_cliente(usuario)
    tipo_precio = "distribuidor" if cliente.get("es_distribuidor") else "de lista"
    st.title(cliente["nombre"], icon=":material/storefront:")
    st.caption(f"Precio {tipo_precio}.")
    mostrar_aviso()
    if not simulacion:
        nueva_clave = panel_clave_cliente(usuario)
        if nueva_clave and usuario.get("user_id"):
            try:
                cambiar_clave_cliente(usuario["user_id"], nueva_clave)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.session_state["aviso"] = ("success", "Contraseña actualizada.")
                st.rerun()
    pagina_portal(sb, cliente)


main()
