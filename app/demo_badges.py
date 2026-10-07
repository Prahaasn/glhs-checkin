"""Printable fictional scan cards; tokens are supplied by the demo database."""
import io

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def render_badges(badges):
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=letter)
    document.setTitle("GLHS - Fictional local demo scan cards")
    pages = (len(badges) + 3) // 4
    for page in range(pages):
        document.setFillColor(HexColor("#135e43"))
        document.setFont("Helvetica-Bold", 22)
        document.drawString(32, 752, "GLHS | Local demo scan cards")
        document.setFillColor(black)
        document.setFont("Helvetica", 10)
        document.drawString(32, 732, "Fictional staff only. Print at Actual size / 100%. Each pair encodes the same badge.")
        document.drawString(32, 716, "Click the station input, scan, and wait for confirmation. USB scanner: keyboard + Enter.")
        for row, badge in enumerate(badges[page * 4:page * 4 + 4]):
            bottom = 555 - row * 140
            document.setStrokeColor(HexColor("#cddbd0"))
            document.roundRect(32, bottom, 548, 132, 8)
            document.setFillColor(HexColor("#1c302b"))
            document.setFont("Helvetica-Bold", 16)
            document.drawString(46, bottom + 109, badge["name"])
            document.setFont("Helvetica", 10)
            document.drawString(46, bottom + 94, badge["teacher_id"] + "  |  FICTIONAL DEMO")
            document.setFont("Helvetica", 8)
            document.drawString(46, bottom + 80, "CODE128 BARCODE - 1D OR 2D SCANNER")
            barcode = code128.Code128(badge["code"], barWidth=0.9, barHeight=40, quiet=True)
            if barcode.width > 405:
                raise ValueError("Demo badge token does not fit the printable card.")
            barcode.drawOn(document, 46, bottom + 33)
            document.setFont("Courier", 8)
            document.drawString(46, bottom + 19, badge["code"])
            widget = QrCodeWidget(badge["code"], barLevel="M", barBorder=4)
            bounds = widget.getBounds()
            size = 91
            drawing = Drawing(size, size, transform=[
                size / (bounds[2] - bounds[0]), 0, 0, size / (bounds[3] - bounds[1]), 0, 0])
            drawing.add(widget)
            renderPDF.draw(drawing, document, 476, bottom + 24)
            document.setFont("Helvetica", 8)
            document.drawCentredString(521, bottom + 14, "QR - 2D SCANNER")
        document.setFillColor(HexColor("#52685c"))
        document.setFont("Helvetica", 9)
        document.drawString(32, 112, "Arrival records IN. Departure records OUT. Repeated IN stays IN.")
        document.drawString(32, 97, "No scanner? Copy a card's token into the station input and press Enter.")
        document.drawString(32, 82, "These cards work only with this separate local demo database. They are not school badges.")
        document.drawRightString(580, 54, f"{page + 1} / {pages}")
        document.showPage()
    document.save()
    return output.getvalue()
