import os
import re
import pandas as pd
from sqlalchemy import create_engine, text
from dash import Dash, dcc, html, Input, Output
import plotly.express as px

# === Conexión a PostgreSQL ===
def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Falta la variable de entorno DATABASE_URL (PostgreSQL).")
    if "sslmode" not in db_url:
        db_url += "?sslmode=require"
    return create_engine(db_url, pool_pre_ping=True)

engine = get_engine()

def run_query(sql: str, params: dict | None = None):
    return pd.read_sql(text(sql), engine, params=params or {})

# === Cargar datos base ===
esp_df = run_query("SELECT id, nombre AS especialidad FROM hospital.especialidades ORDER BY nombre")
prof_df = run_query("SELECT id, (apellido || ', ' || nombre) AS nombre FROM hospital.profesionales ORDER BY apellido, nombre")
pac_df = run_query("SELECT id, (apellido || ', ' || nombre) AS nombre FROM hospital.pacientes ORDER BY apellido, nombre")

# === Inicializar app ===
app = Dash(__name__)
server = app.server

app.layout = html.Div([
    html.H1("Dashboard Hospitalario — Demo con Formulario"),
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

    html.Hr(),
    html.H3("Registrar nuevo turno"),
    html.Div([
        html.Label("Profesional"),
        dcc.Dropdown(
            id="dd-profesional",
            options=[{"label": r.nombre, "value": int(r.id)} for r in prof_df.itertuples()],
            placeholder="Selecciona el profesional",
            style={"maxWidth": 400}
        ),
        html.Br(),

        html.Label("Paciente"),
        dcc.Dropdown(
            id="dd-paciente",
            options=[{"label": r.nombre, "value": int(r.id)} for r in pac_df.itertuples()],
            placeholder="Selecciona el paciente",
            style={"maxWidth": 400}
        ),
        html.Br(),

        html.Label("Fecha del turno"),
        dcc.DatePickerSingle(
            id="input-fecha",
            display_format="YYYY-MM-DD",
            placeholder="Selecciona la fecha"
        ),
        html.Br(),

        html.Label("Hora del turno"),
        dcc.Input(
            id="input-hora",
            type="text",
            placeholder="HH:MM",
            style={"maxWidth": 100}
        ),
        html.Br(),

        html.Label("Estado del turno"),
        dcc.Input(id="input-estado", type="text", placeholder="ej. confirmado", style={"maxWidth": 200}),
        html.Br(),

        html.Button("Guardar turno", id="btn-guardar", n_clicks=0),
        html.Div(id="mensaje-guardar", style={"marginTop": "10px", "color": "green"})
    ]),

    dcc.Graph(id="g-atenciones-dia"),
    dcc.Graph(id="g-top-medicos"),
    dcc.Graph(id="g-estado"),
], style={"fontFamily": "Arial, sans-serif", "padding": "16px"})

# === Callback: actualización de gráficos ===
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

    q1 = f'''
        SELECT date(t.fecha_hora) AS dia, COUNT(*) AS atenciones
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY date(t.fecha_hora)
        ORDER BY dia
    '''
    q2 = f'''
        SELECT (pr.apellido || ', ' || pr.nombre) AS medico, COUNT(*) AS atenciones
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY pr.id, pr.apellido, pr.nombre
        ORDER BY atenciones DESC
        LIMIT 5
    '''
    q3 = f'''
        SELECT t.estado, COUNT(*) AS n
        FROM hospital.turnos t
        JOIN hospital.profesionales pr ON pr.id = t.profesional_id
        WHERE {where_clause}
        GROUP BY t.estado
        ORDER BY n DESC
    '''

    df1 = run_query(q1, params)
    fig1 = px.bar(df1, x="dia", y="atenciones", title="Atenciones por día")
    df2 = run_query(q2, params)
    fig2 = px.bar(df2, x="medico", y="atenciones", title="Top 5 médicos")
    df3 = run_query(q3, params)
    fig3 = px.pie(df3, names="estado", values="n", title="Estados de turno")

    return fig1, fig2, fig3

# === Callback: insertar nuevo turno ===
@app.callback(
    Output("mensaje-guardar", "children"),
    Input("btn-guardar", "n_clicks"),
    Input("dd-profesional", "value"),
    Input("dd-paciente", "value"),
    Input("input-fecha", "date"),
    Input("input-hora", "value"),
    Input("input-estado", "value"),
    prevent_initial_call=True
)
def guardar_turno(n_clicks, profesional_id, paciente_id, fecha, hora, estado):
    if not (profesional_id and paciente_id and fecha and hora and estado):
        return "⚠️ Completa todos los campos antes de guardar."

    if not re.match(r"^\d{2}:\d{2}$", hora):
        return "⚠️ Formato de hora inválido (usa HH:MM, por ejemplo 14:30)."

    fecha_hora = f"{fecha} {hora}:00"
    sql = text("INSERT INTO hospital.turnos (profesional_id, paciente_id, fecha_hora, estado) VALUES (:prof, :pac, :fecha_hora, :estado)")

    try:
        with engine.begin() as conn:
            conn.execute(sql, {"prof": profesional_id, "pac": paciente_id, "fecha_hora": fecha_hora, "estado": estado})
        return f"✅ Turno registrado correctamente para {fecha_hora}."
    except Exception as e:
        return f"❌ Error al guardar: {e}"

if __name__ == "__main__":
    app.run(debug=True)
