# template_generator.py
import io
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

FILL_HEADER  = PatternFill("solid", fgColor="1F4E79")
FILL_EXAMPLE = PatternFill("solid", fgColor="EBF3FB")
FILL_NOTE    = PatternFill("solid", fgColor="FFF2CC")
FONT_WHITE   = Font(bold=True, color="FFFFFF", size=11)
FONT_BOLD    = Font(bold=True, size=10)
FONT_ITALIC  = Font(italic=True, color="7F7F7F", size=9)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_LEFT   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
THIN_BORDER  = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"),  bottom=Side(style="thin"),
)


def _style_header(ws, row, cols):
    for ci, val in enumerate(cols, 1):
        c = ws.cell(row=row, column=ci, value=val)
        c.fill      = FILL_HEADER
        c.font      = FONT_WHITE
        c.alignment = ALIGN_CENTER
        c.border    = THIN_BORDER


def _style_example(ws, row, values):
    for ci, val in enumerate(values, 1):
        c = ws.cell(row=row, column=ci, value=val)
        c.fill      = FILL_EXAMPLE
        c.font      = Font(size=10)
        c.alignment = ALIGN_LEFT
        c.border    = THIN_BORDER


def _style_note(ws, row, values):
    for ci, val in enumerate(values, 1):
        c = ws.cell(row=row, column=ci, value=val)
        c.fill      = FILL_NOTE
        c.font      = FONT_ITALIC
        c.alignment = ALIGN_LEFT
        c.border    = THIN_BORDER


def _add_petunjuk_sheet(wb):
    ws = wb.create_sheet("📋 Petunjuk")
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 60

    petunjuk = [
        ("FILE",                  "KETERANGAN"),
        ("Master Mixer",          "Daftar semua mixer yang tersedia beserta kapasitas dan batch per shift."),
        ("Master Produk",         "Daftar produk dengan informasi kg/CS, resting days, grup cleaning, dan mixer yang kompatibel."),
        ("Filling Plan",          "Rencana filling: produk apa, berapa CS, tanggal & shift filling, dan apakah urgent."),
        ("",                      ""),
        ("KOLOM",                 "KETERANGAN"),
        ("Mixer",                 "Nama mixer (harus unik, dipakai sebagai referensi di Master Produk)."),
        ("Kapasitas_kg",          "Kapasitas maksimal mixer dalam kg per batch."),
        ("Batch_per_Shift",       "Jumlah batch yang bisa dilakukan dalam 1 shift."),
        ("Grup_Cleaning",         "Grup cleaning mixer (mixer dgn grup sama tidak perlu cleaning saat ganti produk dgn grup sama)."),
        ("Kode_Produk",           "Kode unik produk (dipakai sebagai referensi di Filling Plan)."),
        ("Nama_Produk",           "Nama lengkap produk."),
        ("Kode_MC_Liquid",        "Kode MC liquid (opsional, untuk referensi internal)."),
        ("Kg_per_CS",             "Berat produk per karton/CS dalam kg."),
        ("Resting_Days",          "Jumlah hari resting setelah mixing sebelum bisa di-filling. 0 = bisa filling hari yang sama."),
        ("Mixer_Kompatibel",      "Daftar mixer yang bisa dipakai untuk produk ini, pisahkan dengan koma. Contoh: M1,M2,M3"),
        ("Target_CS",             "Jumlah CS yang perlu di-mixing untuk filling plan ini."),
        ("Tanggal_Filling",       "Tanggal filling dijalankan. Format: YYYY-MM-DD atau DD/MM/YYYY."),
        ("Shift_Filling",         "Shift filling: 1, 2, atau 3."),
        ("Urgent",                "Isi 'Urgent' untuk prioritas tinggi, kosong atau 'Normal' untuk biasa."),
        ("",                      ""),
        ("CATATAN",               ""),
        ("Warna biru muda",       "Baris contoh — hapus sebelum upload, atau biarkan (akan diabaikan jika kode tidak valid)."),
        ("Warna kuning",          "Catatan/keterangan — hapus sebelum upload."),
    ]

    ws.cell(row=1, column=1, value="📋 PETUNJUK PENGGUNAAN TEMPLATE").font = Font(bold=True, size=13)
    ws.merge_cells("A1:B1")

    for ri, (a, b) in enumerate(petunjuk, 3):
        ca = ws.cell(row=ri, column=1, value=a)
        cb = ws.cell(row=ri, column=2, value=b)
        if a in ("FILE", "KOLOM", "CATATAN"):
            ca.font = FONT_BOLD
            cb.font = FONT_BOLD
            ca.fill = PatternFill("solid", fgColor="D9E1F2")
            cb.fill = PatternFill("solid", fgColor="D9E1F2")
        ca.alignment = ALIGN_LEFT
        cb.alignment = ALIGN_LEFT

    ws.row_dimensions[1].height = 22


def generate_template_master_mixer():
    """Generate template Master Mixer sebagai bytes Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Mixer"

    cols = ["Mixer", "Kapasitas_kg", "Batch_per_Shift", "Grup_Cleaning"]
    _style_header(ws, 1, cols)

    examples = [
        ["M1", 500, 2, "A"],
        ["M2", 500, 2, "A"],
        ["M3", 300, 3, "B"],
        ["M4", 400, 2, "B"],
    ]
    for ri, ex in enumerate(examples, 2):
        _style_example(ws, ri, ex)

    notes = ["Nama mixer unik", "kg/batch", "batch/shift", "Grup cleaning (A/B/C/...)"]
    _style_note(ws, len(examples) + 2, notes)

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 16
    ws.row_dimensions[1].height = 22

    _add_petunjuk_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_template_master_produk():
    """Generate template Master Produk sebagai bytes Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Produk"

    cols = [
        "Kode_Produk", "Nama_Produk", "Kode_MC_Liquid",
        "Kg_per_CS", "Resting_Days", "Grup_Cleaning", "Mixer_Kompatibel"
    ]
    _style_header(ws, 1, cols)

    examples = [
        ["PRD001", "Produk A 1L",    "MC-001", 12.5, 1, "A", "M1,M2"],
        ["PRD002", "Produk B 500ml", "MC-002", 6.0,  0, "A", "M1,M2,M3"],
        ["PRD003", "Produk C 2L",    "MC-003", 24.0, 2, "B", "M3,M4"],
        ["PRD004", "Produk D 250ml", "MC-004", 3.0,  0, "B", "M4"],
    ]
    for ri, ex in enumerate(examples, 2):
        _style_example(ws, ri, ex)

    notes = [
        "Kode unik", "Nama produk", "Kode MC (opsional)",
        "kg per CS", "Hari resting (0=hari H)", "Grup cleaning", "Pisah koma"
    ]
    _style_note(ws, len(examples) + 2, notes)

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 15
    ws.column_dimensions["G"].width = 22
    ws.row_dimensions[1].height = 22

    _add_petunjuk_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_template_filling_plan():
    """Generate template Filling Plan sebagai bytes Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Filling Plan"

    cols = [
        "Kode_Produk", "Target_CS", "Tanggal_Filling", "Shift_Filling", "Urgent"
    ]
    _style_header(ws, 1, cols)

    examples = [
        ["PRD001", 100, "2025-07-10", 1, "Normal"],
        ["PRD002", 200, "2025-07-10", 2, "Urgent"],
        ["PRD003", 150, "2025-07-11", 1, "Normal"],
        ["PRD004", 80,  "2025-07-11", 3, "Normal"],
        ["PRD001", 120, "2025-07-12", 2, "Urgent"],
    ]
    for ri, ex in enumerate(examples, 2):
        _style_example(ws, ri, ex)

    notes = [
        "Harus ada di Master Produk",
        "Jumlah CS",
        "Format YYYY-MM-DD",
        "1 / 2 / 3",
        "'Urgent' atau 'Normal'"
    ]
    _style_note(ws, len(examples) + 2, notes)

    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 15
    ws.column_dimensions["E"].width = 12
    ws.row_dimensions[1].height = 22

    _add_petunjuk_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
