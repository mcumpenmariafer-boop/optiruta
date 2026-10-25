"""Generación de la hoja de ruta en PDF para el conductor (Tema 5.4)."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AZUL = colors.HexColor("#1B3A5C")
NARANJA = colors.HexColor("#F2994A")


def hoja_de_ruta(ruta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title=f"Hoja de ruta {ruta.codigo}")
    estilos = getSampleStyleSheet()
    estilos["Title"].textColor = AZUL
    elementos = [
        Paragraph(f"OptiRuta · Hoja de ruta {ruta.codigo}", estilos["Title"]),
        Paragraph(
            f"<b>Fecha:</b> {ruta.fecha:%d/%m/%Y} &nbsp; <b>Vehículo:</b> {ruta.vehiculo.placa} "
            f"({ruta.vehiculo.get_tipo_display()}) &nbsp; <b>Conductor:</b> "
            f"{ruta.vehiculo.conductor.usuario.get_full_name() if ruta.vehiculo.conductor else '-'}",
            estilos["Normal"],
        ),
        Paragraph(
            f"<b>Distancia optimizada:</b> {ruta.km_estimados} km (manual: {ruta.km_sin_optimizar} km) "
            f"&nbsp; <b>Tiempo estimado:</b> {ruta.minutos_estimados} min &nbsp; "
            f"<b>Carga:</b> {ruta.peso_total_kg} kg / {ruta.bultos_total} bultos",
            estilos["Normal"],
        ),
        Spacer(1, 0.4 * cm),
    ]
    filas = [["#", "Hora", "Pedido", "Cliente / Dirección", "Ventana", "Kg", "Firma"]]
    for p in ruta.paradas.select_related("pedido__punto_entrega").order_by("orden"):
        pe = p.pedido.punto_entrega
        filas.append([
            p.orden,
            p.hora_estimada.strftime("%H:%M") if p.hora_estimada else "-",
            f"{p.pedido.codigo}\n{p.pedido.prioridad}",
            Paragraph(f"<b>{pe.cliente_nombre}</b><br/>{pe.direccion}<br/><i>{pe.referencia}</i>",
                      estilos["BodyText"]),
            p.pedido.ventana_horaria,
            f"{p.pedido.peso_kg}",
            "",
        ])
    tabla = Table(filas, colWidths=[0.8 * cm, 1.3 * cm, 2.3 * cm, 7 * cm, 2.4 * cm, 1.3 * cm, 2.6 * cm],
                  repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
        ("ROWHEIGHT", (0, 1), (-1, -1), 1.1 * cm),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 0.5 * cm))
    elementos.append(Paragraph(
        "Orden calculado con el algoritmo Vecino Más Cercano + 2-opt respetando prioridades y ventanas "
        "horarias. Documento digital: imprímalo solo si es necesario.", estilos["Italic"]))
    doc.build(elementos)
    return buffer.getvalue()
