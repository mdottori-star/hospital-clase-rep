# === CÓDIGO VIEJO (comentado): SQLite local ===
# import sqlite3
# DB_PATH = "hospital.db"
# def run_query(sql: str, params: tuple = ()):
#     with sqlite3.connect(DB_PATH) as conn:
#         return pd.read_sql_query(sql, conn, params=params)

import os
import pandas as pd
from sqlalchemy import create_engine, text
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

# === NUEVO: PostgreSQL en Render (sin fallback) ===
def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        # No más SQLite: si no hay URL, fallamos explícitamente para detectar el problema
        raise RuntimeError("Falta la variable de entorno DATABASE_URL (PostgreSQL).")
    if "sslmode" not in db_url:
        db_url += "?sslmode=require"
    return create_engine(db_url, pool_pre_ping=True)

engine = get_engine()

def run_query(sql: str, params: dict | None = None):
    """SQL parametrizado en PostgreSQL (con esquema hospital)."""
    return pd.read_sql(text(sql), engine, params=params or {})

# === Preload Especialidades (PostgreSQL / esquema hospital) ===
esp_df = run_query("""
    SELECT id, nombre AS especialidad
    FROM hospital.especialidades
    ORDER BY nombre
""")

app = Dash(__name__)
server = app.server  # necesario para gunicorn en Render

app.layout = html.Div([
    html.H1("Dashboard Hospitalario — Demo (PostgreSQL)"),
    html.Div([
        html.Label("Especialidad"),
        dcc.Dropdown(
            id="esp-dd",
            options=[{"label": r.especialidad, "value": int(r.id)} for r in esp_df.itertuples()],
            value=int(esp_df.id.iloc[0]) if len(esp_df) else None,
            clearable=False
        ),
    ], style={"maxWidth": 400, "marginBottom": "12px"}),
    dcc.DatePickerRange(id="rango-fechas", display_format="YYYY-MM-DD"),
    html.Div(style={"height": "12px"}),
    dcc.Graph(id="g-atenciones-dia"),
    dcc.Graph(id="g-top-medicos"),
    dcc.Graph(id="g-estado"),
], style={"fontFamily": "Arial, sans-serif", "padding": "16px"})

@app.callback(
    Output("g-atenciones-dia", "figure"),
    Output("g-top-medicos", "figure"),
    Output("g-estado", "figure"),
    Input("esp-dd", "value"),
    Input("rango-fechas", "start_date"),
    Input("rango-fechas", "end_date"),
)
def update_figs(esp_id, start_date, end_date):
    if esp_id is None:
        return px.scatter(title="Sin datos"), px.scatter(title="Sin datos"), px.scatter(title="Sin datos")

    params = {"esp_id": esp_id}
    where_parts = ["pr.especialidad_id = :esp_id"]
    if start_date:
        where_parts.append("date(t.fecha_hora) >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where_parts.append("date(t.fecha_hora) <= :end_date")
        params["end_date"] = end_date
    where_clause = " AND ".join(where_parts)

    # 1) Atenciones por día
    q1 = f"""
        SELECT date(t.fecha_hora) AS dia, COUNT(*) AS atenciones
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY date(t.fecha_hora)
        ORDER BY dia
    """

    # 2) Top 5 profesionales
    q2 = f"""
        SELECT (pr.apellido || ', ' || pr.nombre) AS medico, COUNT(*) AS atenciones
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY pr.id, pr.apellido, pr.nombre
        ORDER BY atenciones DESC
        LIMIT 5
    """

    # 3) Distribución por estado
    q3 = f"""
        SELECT t.estado, COUNT(*) AS n
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY t.estado
        ORDER BY n DESC
    """

    df1 = run_query(q1, params)
    fig1 = px.bar(df1, x="dia", y="atenciones", title="Atenciones por día")

    df2 = run_query(q2, params)
    fig2 = px.bar(df2, x="medico", y="atenciones", title="Top 5 médicos")

    df3 = run_query(q3, params)
    fig3 = px.pie(df3, names="estado", values="n", title="Estados de turno")

    return fig1, fig2, fig3

if __name__ == "__main__":
    app.run(debug=True)
