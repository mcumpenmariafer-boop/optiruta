"""Reporte de eficiencia en PDF (Tema 5.4): KPIs, gráfico, comparativa por vehículo y antes/después."""
from io import BytesIO

from django.utils import timezone
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ASFALTO = colors.HexColor("#14324F")
SENAL = colors.HexColor("#F5B400")
VERDE = colors.HexColor("#1E8E5A")
ROJO = colors.HexColor("#D64545")
GRIS = colors.HexColor("#9AA7B3")
LINEA = colors.HexColor("#D3DCD6")
FONDO = colors.HexColor("#F4F7F5")


def _n(valor, dec=1):
    return f"{float(valor or 0):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", " ")


def _tabla(filas, anchos, cabecera=ASFALTO, alinear_derecha_desde=1):
    t = Table(filas, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cabecera),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (alinear_derecha_desde, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FONDO]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _grafico_km(por_dia):
    """Barras agrupadas: km en orden de llegada (manual) vs km optimizados, por día."""
    d = Drawing(17 * cm, 6.2 * cm)
    if not por_dia:
        d.add(String(8.5 * cm, 3 * cm, "Sin rutas cerradas en el periodo", textAnchor="middle", fontSize=9))
        return d
    g = VerticalBarChart()
    g.x, g.y, g.width, g.height = 1.2 * cm, 1.1 * cm, 15.3 * cm, 4.4 * cm
    g.data = [[float(x["km_sin_optimizar"]) for x in por_dia], [float(x["km"]) for x in por_dia]]
    g.categoryAxis.categoryNames = [x["fecha"].strftime("%d/%m") for x in por_dia]
    g.categoryAxis.labels.fontSize = 7
    g.valueAxis.labels.fontSize = 7
    g.valueAxis.valueMin = 0
    g.bars[0].fillColor, g.bars[1].fillColor = GRIS, SENAL
    g.bars.strokeColor = None
    g.barSpacing, g.groupSpacing = 1, 6
    d.add(g)
    ley = Legend()
    ley.x, ley.y = 1.4 * cm, 6 * cm
    ley.alignment, ley.columnMaximum, ley.fontSize, ley.dxTextSpace = "right", 1, 8, 4
    ley.colorNamePairs = [(GRIS, "Orden de llegada (manual)"), (SENAL, "Ruta optimizada")]
    ley.deltax = 140
    d.add(ley)
    return d


def reporte_eficiencia(datos, vehiculo_nombre=None):
    """Devuelve los bytes del PDF a partir del resultado de calcular_eficiencia()."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.4 * cm, title="Reporte de eficiencia OptiRuta")
    est = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=est["Title"], textColor=ASFALTO, fontSize=20, spaceAfter=2, alignment=0)
    sub = ParagraphStyle("s", parent=est["Normal"], textColor=colors.HexColor("#5B6B79"), fontSize=9.5)
    h2 = ParagraphStyle("h2", parent=est["Heading2"], textColor=ASFALTO, fontSize=12.5, spaceBefore=12, spaceAfter=6)
    nota = ParagraphStyle("n", parent=est["Normal"], fontSize=8, textColor=colors.HexColor("#5B6B79"))
    cifra = ParagraphStyle("c", parent=est["Normal"], fontSize=17, leading=20, textColor=ASFALTO,
                           fontName="Helvetica-Bold", alignment=TA_CENTER)
    etiqueta = ParagraphStyle("e", parent=est["Normal"], fontSize=7.5, leading=9, alignment=TA_CENTER,
                              textColor=colors.HexColor("#5B6B79"))
    r = datos["resumen"]
    periodo = (f"{datos['desde']:%d/%m/%Y}" if datos["desde"] == datos["hasta"]
               else f"{datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y}")
    elementos = [
        Paragraph("OptiRuta · Reporte de eficiencia", titulo),
        Paragraph(f"Periodo: <b>{periodo}</b> · Flota: <b>{vehiculo_nombre or 'todos los vehículos'}</b> · "
                  f"Generado el {timezone.localtime():%d/%m/%Y %H:%M}", sub),
        Spacer(1, 0.35 * cm),
    ]
    kpis = [
        (f"{_n(r['porcentaje_entrega'])} %", f"Entregas efectivas<br/>({r['pedidos_entregados']}/{r['pedidos_asignados']})"),
        (f"{_n(r['km_recorridos'], 0)} km", f"Recorridos en<br/>{r['rutas_cerradas']} rutas"),
        (f"{_n(r['ahorro_km'], 0)} km", f"Ahorrados por<br/>optimización (-{_n(r['ahorro_pct'])} %)"),
        (f"S/ {_n(r['ahorro_soles'], 0)}", "Combustible<br/>ahorrado"),
        (f"{_n(r['co2_evitado_kg'], 0)} kg", "CO<sub>2</sub> evitado"),
        (f"{r['tiempo_promedio_min']} min", "Tiempo promedio<br/>por ruta"),
    ]
    celdas = [[Paragraph(v, cifra) for v, _ in kpis], [Paragraph(e, etiqueta) for _, e in kpis]]
    franja = Table(celdas, colWidths=[2.95 * cm] * 6)
    franja.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("LINEAFTER", (0, 0), (-2, -1), 0.4, LINEA),
        ("BACKGROUND", (0, 0), (-1, -1), FONDO), ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("LINEBEFORE", (2, 0), (2, -1), 2.5, VERDE),
    ]))
    elementos += [franja, Paragraph("Kilómetros por día: manual vs optimizado", h2), _grafico_km(datos["por_dia"])]

    filas = [["Vehículo", "Conductor", "Rutas", "Entregados", "% entrega", "Km", "Ahorro km", "Pedidos/h"]]
    for v in datos["por_vehiculo"]:
        filas.append([v["placa"], v["conductor"], v["rutas"], f"{v['entregados']}/{v['asignados']}",
                      f"{_n(v['porcentaje_entrega'])} %", _n(v["km"]), _n(v["ahorro_km"]), _n(v["pedidos_por_hora"], 2)])
    if len(filas) == 1:
        filas.append(["—", "Sin rutas cerradas en el periodo", "", "", "", "", "", ""])
    elementos += [KeepTogether([Paragraph("Comparativa por vehículo", h2),
                                _tabla(filas, [2 * cm, 4.4 * cm, 1.3 * cm, 2 * cm, 1.9 * cm, 1.6 * cm, 1.9 * cm, 1.8 * cm],
                                       alinear_derecha_desde=2)])]

    manual, optimo = float(r["km_sin_optimizar"]), float(r["km_sin_optimizar"]) - float(r["ahorro_km"])
    rutas = r["rutas_cerradas"] or 1
    soles_km = float(r["ahorro_soles"]) / float(r["ahorro_km"]) if float(r["ahorro_km"]) else 0

    def mejora(a, b):
        return f"{_n(100 * (b - a) / a)} %" if a else "—"

    antes = [["Indicador", "Antes (orden de llegada)", "Con OptiRuta", "Mejora"],
             ["Km recorridos", _n(manual), _n(optimo), mejora(manual, optimo)],
             ["Km promedio por ruta", _n(manual / rutas), _n(optimo / rutas), mejora(manual / rutas, optimo / rutas)],
             ["Gasto en combustible (S/)", _n(manual * soles_km), _n(optimo * soles_km),
              mejora(manual * soles_km, optimo * soles_km)],
             ["Planillas de papel", str(r["pedidos_asignados"] * 2), "0", "-100,0 %" if r["pedidos_asignados"] else "—"]]
    elementos += [KeepTogether([Paragraph("Antes y después del sistema", h2),
                                _tabla(antes, [5.4 * cm, 4.2 * cm, 3.6 * cm, 3.6 * cm])])]

    if datos["por_zona"]:
        zonas = [["Zona", "Paradas", "Entregadas", "% entrega"]] + [
            [z["zona"], z["total"], z["entregados"], f"{_n(z['porcentaje_entrega'])} %"] for z in datos["por_zona"]]
        elementos += [KeepTogether([Paragraph("Entregas por zona", h2), _tabla(zonas, [7 * cm, 3.2 * cm, 3.2 * cm, 3.4 * cm])])]
    if datos["motivos_fallo"]:
        motivos = [["Motivo de no entrega", "Casos"]] + [[m["observacion"], m["total"]] for m in datos["motivos_fallo"]]
        elementos += [KeepTogether([Paragraph("Principales motivos de no entrega", h2),
                                    _tabla(motivos, [13.6 * cm, 3.2 * cm], cabecera=ROJO)])]
    elementos += [Spacer(1, 0.5 * cm), Paragraph(
        "El ahorro compara la ruta optimizada (vecino más cercano + 2-opt con prioridades y ventanas horarias) contra "
        "el orden en que llegaron los pedidos. Combustible: rendimiento por tipo de vehículo; CO<sub>2</sub>: factores IPCC 2006.", nota)]
    doc.build(elementos)
    return buffer.getvalue()
