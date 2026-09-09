"""
Esportazione dei dati fuori da Cortex: righe di una tabella qualunque in
Excel, e il bilancio (l'unico report con un formato fisso da leggere così
com'è, non solo righe) in PDF. Compensa esplicitamente quanto il documento
originale di Sampeyre chiedeva come "programma desktop con dati in locale"
— passando al cloud, il dato deve poter uscire da Cortex quando serve, non
restarci intrappolato (vedi PLAN.md, Sezione 2).

L'export Excel è generico (qualunque tabella, di qualunque settore, da
database o API — vedi app.services.data_source): nessuna colonna o
formattazione specifica di dominio. Il PDF del bilancio è l'eccezione voluta:
è un documento con una struttura fissa (Conto Economico / Stato
Patrimoniale), non una tabella qualsiasi.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_INTESTAZIONE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
)


def _cella_leggibile(valore: Any) -> Any:
    """Excel non sa cosa farsene di un Decimal o capisce le date solo se
    sono un vero oggetto data — converte nei tipi che openpyxl maneggia."""
    if isinstance(valore, Decimal):
        return float(valore)
    if isinstance(valore, (date, datetime)):
        return valore.isoformat()
    if isinstance(valore, (dict, list)):
        return str(valore)
    return valore


def righe_a_excel(colonne: list[str], righe: list[dict[str, Any]], titolo: str = "Dati") -> bytes:
    """Un foglio Excel con intestazione in grassetto e le righe così come
    arrivano dalla sorgente dati — nessuna riga di questa funzione conosce lo
    schema di un settore specifico, funziona per qualunque tabella."""
    wb = Workbook()
    ws = wb.active
    ws.title = (titolo or "Dati")[:31]  # Excel limita il nome del foglio a 31 caratteri

    ws.append(colonne)
    for cella in ws[1]:
        cella.font = Font(bold=True)

    for riga in righe:
        ws.append([_cella_leggibile(riga.get(c)) for c in colonne])

    for colonna in ws.columns:
        larghezza = max((len(str(c.value)) for c in colonna if c.value is not None), default=10)
        ws.column_dimensions[colonna[0].column_letter].width = min(larghezza + 2, 50)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _tabella_valori(righe: list[list[str]]) -> Table:
    tabella = Table(righe, colWidths=[10 * cm, 5 * cm])
    tabella.setStyle(_INTESTAZIONE)
    return tabella


def bilancio_a_pdf(bilancio: dict[str, Any], organizzazione: str) -> bytes:
    """Il bilancio (Conto Economico + Stato Patrimoniale semplificato,
    calcolati da app.services.accounting_engine.compute_bilancio) come
    documento leggibile e stampabile."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    stili = getSampleStyleSheet()
    elementi = []

    elementi.append(Paragraph(f"Bilancio {bilancio['anno']}", stili["Title"]))
    elementi.append(Paragraph(organizzazione, stili["Normal"]))
    elementi.append(Spacer(1, 0.6 * cm))

    elementi.append(Paragraph("Conto Economico", stili["Heading2"]))
    ce = bilancio["conto_economico"]
    righe_ce = [["Voce", "Importo"]]
    for gruppo, valore in ce["per_gruppo"].items():
        righe_ce.append([gruppo, f"{valore:,.2f} €"])
    righe_ce.append(["Totale entrate", f"{ce['totale_entrate']:,.2f} €"])
    righe_ce.append(["Totale uscite", f"{ce['totale_uscite']:,.2f} €"])
    righe_ce.append(["di cui ammortamenti", f"{ce['totale_ammortamenti']:,.2f} €"])
    righe_ce.append(["Risultato d'esercizio", f"{ce['risultato']:,.2f} €"])
    elementi.append(_tabella_valori(righe_ce))
    elementi.append(Spacer(1, 0.8 * cm))

    elementi.append(Paragraph("Stato Patrimoniale (semplificato)", stili["Heading2"]))
    sp = bilancio["stato_patrimoniale_semplificato"]
    righe_sp = [["Voce", "Importo"]]
    for conto, valore in sp["liquidita"].items():
        righe_sp.append([f"Liquidità — {conto}", f"{valore:,.2f} €"])
    righe_sp.append(["Totale liquidità", f"{sp['totale_liquidita']:,.2f} €"])
    righe_sp.append(["Immobilizzazioni nette", f"{sp['immobilizzazioni_nette']:,.2f} €"])
    elementi.append(_tabella_valori(righe_sp))
    elementi.append(Spacer(1, 0.8 * cm))

    if bilancio.get("nota"):
        elementi.append(Paragraph(bilancio["nota"], stili["Italic"]))

    doc.build(elementi)
    return buffer.getvalue()
