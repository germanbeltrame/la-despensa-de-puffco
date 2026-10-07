import io
import json
from datetime import date, datetime, time, timedelta, timezone
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
from supabase import Client

from calculos import formatear_fecha, parse_fecha
from database import eliminar_gasto, leer_conceptos_gasto, leer_gastos, registrar_gasto
from ui import avisar, dinero

ART = timezone(timedelta(hours=-3))
COLUMNAS_GASTOS = ["Fecha", "Concepto", "Moneda", "Monto", "Notas"]


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
        st.session_state["gasto_monto"] = 0.0
        st.session_state["gasto_notas"] = ""
        st.session_state["gasto_fecha"] = datetime.now(ART).date()
    st.session_state.setdefault("gasto_moneda", "USD")
    conceptos = leer_conceptos_gasto(sb)
    if conceptos is None:
        _historial(sb)
        return
    _formulario(sb, conceptos)
    _importador(sb, conceptos)
    _historial(sb)


def _nombres_concepto(conceptos: list) -> list[str]:
    nombres = []
    for item in conceptos:
        nombre = " ".join(str(item.get("nombre") or "").split())
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    nombres.sort(key=str.casefold)
    return nombres


def _formulario(sb: Client, conceptos: list) -> None:
    nombres = _nombres_concepto(conceptos)
    with st.container(border=True):
        st.markdown("**Nuevo gasto**")
        if not nombres:
            st.warning("No hay conceptos de gasto. Cargalos en Configuración.")
            return
        if st.session_state.get("gasto_concepto") not in nombres:
            st.session_state["gasto_concepto"] = nombres[0]
        fecha = st.date_input("Fecha", format="DD/MM/YYYY", key="gasto_fecha")
        concepto = st.selectbox("Concepto", nombres, key="gasto_concepto")
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


def _fecha_excel(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if float(valor) < 20000:
            return None
        return (datetime(1899, 12, 30) + timedelta(days=float(valor))).date()
    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        return None
    cabeza = texto[:10]
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cabeza, formato).date()
        except ValueError:
            continue
    return None


def _numero_excel(valor) -> float | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "")
    if not texto or texto.lower() == "nan":
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _texto_excel(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.lower() == "nan":
        return ""
    return " ".join(texto.split())


def plantilla_gastos() -> bytes:
    tabla = pd.DataFrame(columns=COLUMNAS_GASTOS)
    archivo = io.BytesIO()
    tabla.to_excel(archivo, index=False, sheet_name="Gastos")
    return archivo.getvalue()


def importar_gastos(sb: Client, filas: pd.DataFrame, conceptos: list) -> tuple[int, list[str]]:
    faltantes = [columna for columna in COLUMNAS_GASTOS if columna not in filas.columns]
    if faltantes:
        return 0, [f"Faltan columnas: {', '.join(faltantes)}."]
    oficiales = {}
    for item in conceptos:
        nombre = " ".join(str(item.get("nombre") or "").split())
        if nombre:
            oficiales[nombre.casefold()] = nombre
    blue = cotizacion_blue()
    cargados = 0
    errores: list[str] = []
    for indice, fila in filas.iterrows():
        numero = int(indice) + 2
        fecha_txt = _texto_excel(fila["Fecha"])
        concepto_txt = _texto_excel(fila["Concepto"])
        moneda_txt = _texto_excel(fila["Moneda"]).upper()
        monto = _numero_excel(fila["Monto"])
        notas = _texto_excel(fila["Notas"])
        if not fecha_txt and not concepto_txt and monto in (None, 0) and not notas and not moneda_txt:
            continue
        dia = _fecha_excel(fila["Fecha"])
        if dia is None:
            errores.append(f"Fila {numero}: la fecha tiene que estar en formato DD/MM/YYYY.")
            continue
        concepto = oficiales.get(concepto_txt.casefold())
        if not concepto:
            errores.append(f"Fila {numero}: el concepto '{concepto_txt or 'vacío'}' no está en Configuración.")
            continue
        if moneda_txt not in ("USD", "ARS"):
            errores.append(f"Fila {numero}: la moneda tiene que ser USD o ARS.")
            continue
        if monto is None or monto <= 0:
            errores.append(f"Fila {numero}: el monto tiene que ser mayor a cero.")
            continue
        if moneda_txt == "ARS":
            if not blue:
                errores.append(f"Fila {numero}: no se pudo leer el blue para convertir los pesos.")
                continue
            cotizacion = round(float(blue), 2)
            monto_usd = round(float(monto) / cotizacion, 2)
        else:
            cotizacion = 1.0
            monto_usd = round(float(monto), 2)
        if monto_usd <= 0:
            errores.append(f"Fila {numero}: el equivalente en dólares quedó en cero.")
            continue
        momento = datetime.combine(dia, time(12, 0), tzinfo=ART)
        error = registrar_gasto(
            sb,
            {
                "fecha": momento.isoformat(),
                "concepto": concepto,
                "moneda": moneda_txt,
                "monto_original": round(float(monto), 2),
                "cotizacion": cotizacion,
                "monto_usd": monto_usd,
                "observaciones": notas or None,
            },
        )
        if error:
            errores.append(f"Fila {numero}: {error}")
            continue
        cargados += 1
    return cargados, errores


def _importador(sb: Client, conceptos: list) -> None:
    with st.expander("Importar Gastos desde Excel"):
        st.caption(
            "Columnas: Fecha (DD/MM/YYYY), Concepto, Moneda (USD o ARS), Monto y Notas. "
            "El concepto tiene que existir en Configuración. Los pesos se convierten con el blue del día."
        )
        st.download_button(
            "Descargar plantilla",
            data=plantilla_gastos(),
            file_name="gastos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="descargar_plantilla_gastos",
        )
        archivo = st.file_uploader("Archivo Excel", type=["xlsx"], key="archivo_importar_gastos")
        if not st.button("Importar gastos", type="primary", disabled=archivo is None):
            return
        try:
            filas = pd.read_excel(archivo)
        except Exception as exc:
            st.error(f"No se pudo leer el Excel. {exc}")
            return
        cargados, errores = importar_gastos(sb, filas, conceptos)
        detalle = " ".join(errores[:5])
        if cargados == 0:
            st.error(detalle or "El archivo no tiene gastos para importar.")
            return
        st.cache_data.clear()
        resumen = f"Se importaron {cargados} gastos."
        if errores:
            avisar("warning", f"{resumen} {detalle}")
            return
        avisar("success", resumen)


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
