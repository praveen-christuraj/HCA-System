"""Print-grade operation exports with wrapping, repeating headers and page numbers."""
from fastapi import Response
from fpdf import FPDF
from fpdf.fonts import FontFace
from app.utils.exporters import _pdf_safe, timestamped_filename
from app.utils.time import utcnow


class TicketPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.cell(0, 6, f"HCA System | Page {self.page_no()} / {{nb}}", align="R")


def _pdf(title, filters, orientation="L"):
    pdf = TicketPDF(orientation=orientation)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, 16)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, _pdf_safe("HCA System - " + title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.multi_cell(0, 5, _pdf_safe(f"Generated {utcnow():%Y-%m-%d %H:%M} UTC\nFilters: {filters}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    return pdf


def _response(pdf, name):
    return Response(bytes(pdf.output()), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{timestamped_filename(name, "pdf")}"'})


def ticket_register_pdf(headers, rows, filters):
    pdf = _pdf("Operation Entry Register", "; ".join(f"{k}={v}" for k,v in filters.items() if v) or "All accessible tickets")
    pdf.set_font("Helvetica", size=7)
    with pdf.table(col_widths=(45,16,30,28,28,25,22,23,30,30), line_height=4,
                   headings_style=FontFace(emphasis="BOLD", color=255, fill_color=(18,49,95)), repeat_headings=1) as table:
        for values in [headers, *rows]:
            r = table.row()
            for value in values: r.cell(_pdf_safe(str(value if value is not None else "")))
    return _response(pdf, "operation-entries")


def reference_pdf(kind, headers, rows, filters):
    pdf = _pdf(kind.replace("_", " ").title(), filters, orientation="P")
    pdf.set_font("Helvetica", size=9)
    for i, values in enumerate(rows):
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 6, f"Record {i + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        for key, value in zip(headers, values):
            pdf.multi_cell(0, 5, _pdf_safe(f"{key}: {value if value is not None else ''}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    return _response(pdf, kind)


def ticket_snapshot_pdf(ticket_number, rows):
    pdf = _pdf("Operation Ticket " + ticket_number, "Saved ticket snapshot", orientation="P")
    pdf.set_font("Helvetica", size=8)
    with pdf.table(col_widths=(100,90), line_height=4, headings_style=FontFace(emphasis="BOLD", color=255, fill_color=(18,49,95))) as table:
        for values in [["Field", "Value"], *rows]:
            r = table.row()
            for value in values: r.cell(_pdf_safe(str(value if value is not None else "")))
    return _response(pdf, "operation-ticket")


def table_pdf(title, name, headers, rows, filters="", orientation="L"):
    """Generic print-grade register/report table (Operation Tracking exports)."""
    pdf = _pdf(title, filters or "All accessible records", orientation=orientation)
    pdf.set_font("Helvetica", size=7 if len(headers) > 8 else 8)
    with pdf.table(line_height=4, headings_style=FontFace(emphasis="BOLD", color=255, fill_color=(18,49,95)), repeat_headings=1) as table:
        for values in [headers, *rows]:
            r = table.row()
            for value in values: r.cell(_pdf_safe(str(value if value is not None else "")))
    return _response(pdf, name)
