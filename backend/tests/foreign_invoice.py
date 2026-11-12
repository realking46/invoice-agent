"""A made-up Swiss insurer invoice: unfamiliar layout, CHF, the word INVOICE printed before the vendor name.
Modelled on a real invoice that was rejected for the wrong reason before the reading-coverage rule existed."""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make(path):
    c = canvas.Canvas(path, pagesize=A4); W, H = A4
    c.setFont("Helvetica-Bold", 10); c.drawString(W - 110, H - 60, "INVOICE")
    c.setFont("Helvetica-Bold", 20); c.drawString(50, H - 64, "alpenblick")
    c.setFont("Helvetica-Bold", 8); c.drawString(50, H - 100, "Alpenblick Versicherung AG")
    c.setFont("Helvetica", 8)
    for i, t in enumerate(["Bahnhofstrasse 12", "8001 Zuerich - Switzerland", "Phone: +41 44 000 00 00"]):
        c.drawString(50, H - 112 - 11 * i, t)
    c.drawString(W - 170, H - 100, "Invoice n° ID 774410")
    c.drawString(50, H - 190, "BILLING ADDRESS:"); c.drawString(50, H - 201, "A. Customer, Seestrasse 5, 6003 Luzern")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(50, H - 250, "Plan"); c.drawString(330, H - 250, "From"); c.drawString(400, H - 250, "To"); c.drawString(500, H - 250, "Price")
    c.setFont("Helvetica", 8)
    c.drawString(50, H - 264, "Student health insurance plan SHP-1022"); c.drawString(330, H - 264, "01.03.2026")
    c.drawString(400, H - 264, "31.03.2026"); c.drawString(500, H - 264, "CHF 54.90")
    c.setFont("Helvetica-Bold", 8); c.drawString(50, H - 284, "Total to be paid incl. 5% federal stamp"); c.drawString(500, H - 284, "CHF 54.90")
    c.save()
    return path
