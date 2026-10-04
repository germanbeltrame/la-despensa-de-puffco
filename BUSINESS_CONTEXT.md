# Contexto del negocio y reglas del sistema: La Despensa de PUFFCO

## 1. Visión del proyecto

Estamos migrando un sistema complejo de hojas de cálculo de Google Sheets / Excel hacia un **Micro ERP web** desarrollado con **Streamlit** (frontend) y **Supabase** (backend PostgreSQL).

El sistema gestiona:

- Inventario
- Costos de importación y logística
- Ventas (pedidos)
- Pagos en USD y ARS
- Cuentas corrientes (deudas)

---

## 2. Lógica financiera y modelo de costos (estricto)

Cada producto tiene un costo final compuesto por la siguiente fórmula:

1. **FOB base:** costo unitario del producto en origen (USD).
2. **Costo flete aéreo:** `Peso_kg * Tarifa_Aerea_por_kg` (USD).
3. **Comisiones / recaudadora (7% total):**
   - 3,5% fee por recepción de dinero.
   - 3,5% fee por giro al exterior.
4. **Costo total unitario:** `FOB Base + Costo_Flete_Aereo + Gastos_Financieros`.

**Regla clave:** si cambia la tarifa del flete aéreo global, el sistema debe recalcular dinámicamente el costo total de los productos sin modificar el FOB histórico.

Los porcentajes y la tarifa de flete viven en la tabla `configuracion` (`flete_aereo_usd_kg`, `fee_recepcion_pct`, `fee_giro_pct`) y no se copian dentro de cada producto.

---

## 3. Clientes y regla de ganancia para socios y distribuidores

No todos los clientes son iguales. Existen dos tipos principales en la tabla `clientes`:

### Clientes estándar (100% ganancia propia)

- `Ganancia_Bruta = Total_Venta - Costo_Total`
- `Ganancia_Real = Ganancia_Bruta * 1.0`

### Socios / distribuidores especiales (ej. Charly Distri, Tin UY)

- Tienen un flag `es_distribuidor = True` y un `porcentaje_ganancia` (ej. 50%).
- `Ganancia_Real = Ganancia_Bruta * (porcentaje_ganancia / 100)`
- El margen se divide automáticamente según ese porcentaje (al 50% cuando `porcentaje_ganancia` es 50).

En cada pedido se persisten `ganancia_bruta_usd` y `ganancia_real_usd` para no recalcular el pasado si más adelante cambia el porcentaje del cliente.

---

## 4. Gestión de cuentas corrientes (deudas y pagos)

- **Eliminación de pestañas individuales:** se elimina el concepto de "una pestaña por cliente". Todos los movimientos viven en tablas relacionales (`pedidos`, `detalle_pedidos`, `pagos`).
- **Multimoneda:** los pagos se pueden ingresar en **USD** (directos) o **ARS** (convertidos a USD según la cotización tomada al momento del cobro).
- **Cálculo de saldo pendiente:**

`Saldo_Actual = SUM(Total_Pedidos_USD) - SUM(Pagos_Ingresados_USD)`

En la base de datos eso corresponde a la suma de `pedidos.total_venta_usd` menos la suma de `pagos.monto_usd_descontado` del mismo cliente. La cotización y el monto original quedan guardados en el pago; el saldo siempre se expresa en USD.

---

## 5. Estructura de la base de datos (Supabase SQL)

El esquema inicial vive en `schema.sql`, en la raíz del proyecto. Tablas:

| Tabla | Rol |
|---|---|
| `configuracion` | Tarifa global de flete aéreo y fees de recepción y giro |
| `productos` | Catálogo: FOB, peso, precios, stock e imagen |
| `clientes` | Nombre, flag de distribuidor y porcentaje de ganancia |
| `pedidos` | Cabecera de venta: totales, costo y ganancias |
| `detalle_pedidos` | Ítems del pedido, con precio cobrado y costo unitario histórico |
| `pagos` | Caja: moneda, monto original, cotización y USD descontado |

El costo unitario cobrado en el momento de la venta se guarda en `detalle_pedidos.costo_unitario_historico`. Un cambio posterior de flete o de FOB no reescribe pedidos ya cerrados.
