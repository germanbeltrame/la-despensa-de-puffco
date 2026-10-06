import json
from datetime import date, datetime, time, timedelta, timezone
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
from supabase import Client

from calculos import formatear_fecha, parse_fecha
from database import eliminar_gasto, leer_gastos, registrar_gasto
from ui import avisar, dinero

ART = timezone(timedelta(hours=-3))


@st.cache_data(ttl=3600, show_spinner=False)
def cotizacion_blue() -> float | None:
    """Venta del dólar blue. Si la consulta falla, la cotización se carga a mano."""
    try:
        pedido = Request(
            "https://dolarapi.com/v1/dolares/blue",
            headers={"User-Agent": "LaDespensaDePuffco"},
        )
        with urlopen(pedido, timeout=5) as respuesta:
            datos = json.load(respuesta)
        venta = float(datos.get("venta") or 0)
    except Exception:
        return None
    if venta <= 0:
        return None
    return venta


def pagina_gastos(sb: Client) -> None:
    if st.session_state.pop("gasto_limpiar", False):
        st.session_state["gasto_concepto"] = ""
        st.session_state["gasto_monto"] = 0.0
        st.session_state["gasto_notas"] = ""
        st.session_state["gasto_fecha"] = datetime.now(ART).date()
    st.session_state.setdefault("gasto_moneda", "USD")

    _formulario(sb)
    _historial(sb)


def _formulario(sb: Client) -> None:
    with st.container(border=True):
        st.markdown("**Nuevo gasto**")
        fecha = st.date_input("Fecha", format="DD/MM/YYYY", key="gasto_fecha")
        concepto = st.text_input("Concepto", key="gasto_concepto", placeholder="Alquiler, flete interno, insumos")
        moneda = st.radio("Moneda", ["USD", "ARS"], horizontal=True, key="gasto_moneda")
        monto_original = st.number_input(
            "Monto original",
            min_value=0.0,
            step=0.01,
            key="gasto_monto",
        )
        if moneda == "ARS":
            blue = cotizacion_blue()
            if "gasto_cotizacion" not in st.session_state:
                st.session_state["gasto_cotizacion"] = float(blue or 0)
            cotizacion = st.number_input(
                "Cotización (ARS por 1 USD)",
                min_value=0.0,
                step=0.01,
                key="gasto_cotizacion",
                help="Arranca con el blue del día y se puede corregir a mano.",
            )
            if blue:
                st.caption(f"Blue del día: {blue:,.2f} ARS por USD.")
            else:
                st.caption("No se pudo leer el blue. Cargá la cotización a mano.")
            monto_usd = round(float(monto_original) / float(cotizacion), 2) if cotizacion > 0 else 0.0
        else:
            cotizacion = 1.0
            monto_usd = round(float(monto_original), 2)
        if monto_usd > 0:
            st.metric("Equivalente en USD", dinero(monto_usd))
        notas = st.text_input("Notas", key="gasto_notas", placeholder="Opcional")
        if not st.button("Registrar gasto", type="primary"):
            return
        if not isinstance(fecha, date):
            st.warning("Elegí la fecha del gasto.")
            return
        if moneda == "ARS" and cotizacion <= 0:
            st.warning("Para pesos, la cotización tiene que ser mayor a cero.")
            return
        if monto_usd <= 0:
            st.warning("Ingresá un monto mayor a cero.")
            return
        momento = datetime.combine(fecha, time(12, 0), tzinfo=ART)
        error = registrar_gasto(
            sb,
            {
                "fecha": momento.isoformat(),
                "concepto": concepto,
                "moneda": moneda,
                "monto_original": round(float(monto_original), 2),
                "cotizacion": 1.0 if moneda == "USD" else round(float(cotizacion), 2),
                "monto_usd": monto_usd,
                "observaciones": " ".join(str(notas or "").split()) or None,
            },
        )
        if error:
            st.error(error)
            return
        st.session_state["gasto_limpiar"] = True
        st.cache_data.clear()
        avisar("success", f"Gasto registrado por {dinero(monto_usd)}.")


def _historial(sb: Client) -> None:
    gastos = leer_gastos(sb)
    if gastos is None:
        return
    st.subheader("Historial")
    if not gastos:
        st.info("Todavía no hay gastos cargados.")
        return
    ordenados = sorted(gastos, key=lambda item: parse_fecha(item.get("fecha")), reverse=True)
    tabla = pd.DataFrame(
        [
            {
                "Fecha": formatear_fecha(item.get("fecha")),
                "Concepto": item.get("concepto") or "",
                "Moneda": item.get("moneda") or "",
                "Monto original": float(item.get("monto_original") or 0),
                "Cotización": float(item.get("cotizacion") or 0),
                "USD": float(item.get("monto_usd") or 0),
                "Notas": item.get("observaciones") or "",
            }
            for item in ordenados
        ]
    )
    st.dataframe(
        tabla,
        hide_index=True,
        width="stretch",
        column_config={
            "Monto original": st.column_config.NumberColumn("Monto original", format="%,.2f"),
            "Cotización": st.column_config.NumberColumn("Cotización", format="%,.2f"),
            "USD": st.column_config.NumberColumn("USD", format="US$ %,.2f"),
        },
    )
    opciones = {}
    for item in ordenados:
        etiqueta = (
            f"{formatear_fecha(item.get('fecha'))} · {item.get('concepto')} · {dinero(item.get('monto_usd'))}"
        )
        if etiqueta in opciones:
            etiqueta = f"{etiqueta} · #{int(item['id'])}"
        opciones[etiqueta] = int(item["id"])
    elegido = st.selectbox("Gasto a eliminar", list(opciones), key="gasto_a_eliminar")
    if st.button("Eliminar gasto", key="btn_eliminar_gasto"):
        error = eliminar_gasto(sb, opciones[elegido])
        if error:
            st.error(error)
            return
        st.cache_data.clear()
        avisar("success", "Gasto eliminado.")
