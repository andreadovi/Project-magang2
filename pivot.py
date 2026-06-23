import pandas as pd
import io
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def date_to_day(date_str):
    return DAYS_ID[datetime.strptime(str(date_str), "%Y-%m-%d").weekday()]


def build_pivot(schedule_df, master_mixer, master_produk, date_range):
    if schedule_df.empty:
        return pd.DataFrame(), {}

    col_keys   = []
    col_labels = []
    for d in date_range:
        day_name = date_to_day(d)
        dt       = datetime.strptime(d, "%Y-%m-%d")
        date_lbl = dt.strftime("%d %b")
        for s in [1, 2, 3]:
            col_keys.append((d, s))
            col_labels.append(f"{day_name} {date_lbl} S{s}")

    mixer_order = list(master_mixer["Mixer"])
    sched_rows  = schedule_df[~schedule_df["Cleaning"]].copy() if "Cleaning" in schedule_df.columns else schedule_df.copy()
    sched_rows  = sched_rows[["Mixer", "Kode_Produk", "Produk"]].drop_duplicates()

    rows = []
    for mixer in mixer_order:
        mixer_sched = sched_rows[sched_rows["Mixer"] == mixer]
        for _, r in mixer_sched.iterrows():
            rows.append((mixer, r["Kode_Produk"], r["Produk"]))

    pivot_data      = {}
    cleaning_cells  = set()
    resting_cells   = set()
    scheduled_mixer = {}

    for _, row in schedule_df.iterrows():
        mx       = row["Mixer"]
        date     = row["Tanggal"]
        shift    = int(row["Shift"])
        cleaning = row.get("Cleaning", False)

        if cleaning:
            for r in rows:
                if r[0] == mx:
                    cleaning_cells.add((mx, r[1], date, shift))
            continue

        kode         = row["Kode_Produk"]
        kg           = float(row["Total_kg"]) if row["Total_kg"] else 0
        resting_days = int(row.get("Resting_Days", 0))

        if kode not in scheduled_mixer:
            scheduled_mixer[kode] = mx

        key = (mx, kode)
        if key not in pivot_data:
            pivot_data[key] = {}
        pivot_data[key][(date, shift)] = pivot_data[key].get((date, shift), 0) + kg

        if resting_days > 0:
            mix_dt = datetime.strptime(date, "%Y-%m-%d")
            for rd in range(1, resting_days + 1):
                rest_dt  = mix_dt + timedelta(days=rd)
                rest_str = rest_dt.strftime("%Y-%m-%d")
                for rs in [1, 2, 3]:
                    resting_cells.add((mx, kode, rest_str, rs))

    records = []
    for row_mixer, kode, nama in rows:
        if kode not in scheduled_mixer:
            continue
        if scheduled_mixer[kode] != row_mixer:
            continue

        rec = {"Mixer": row_mixer, "Kode_Produk": kode, "Nama_Produk": nama}
        for (d, s), label in zip(col_keys, col_labels):
            val = pivot_data.get((row_mixer, kode), {}).get((d, s), "")
            rec[label] = val if val != 0 else ""
        records.append(rec)

    pivot_df = pd.DataFrame(records)

    return pivot_df, {
        "col_keys":       col_keys,
        "col_labels":     col_labels,
        "cleaning_cells": cleaning_cells,
        "resting_cells":  resting_cells,
        "rows":           rows
    }


def build_filling_pivot(filling_plan, master_produk):
    """
    Build pivot jadwal filling:
    Rows  = (Kode_Produk, Nama_Produk) — satu baris per produk
    Cols  = per tanggal x 3 shift (range dari filling_plan)
    Value = Target_CS
    """
    if filling_plan.empty:
        return pd.DataFrame(), {}

    # Ambil semua tanggal filling, sort
    all_dates = sorted(filling_plan["Tanggal_Filling"].unique())

    col_keys   = []
    col_labels = []
    for d in all_dates:
        day_name = date_to_day(d)
        dt       = datetime.strptime(str(d), "%Y-%m-%d")
        date_lbl = dt.strftime("%d %b")
        for s in [1, 2, 3]:
            col_keys.append((d, s))
            col_labels.append(f"{day_name} {date_lbl} S{s}")

    # Urutan produk dari master_produk supaya konsisten
    mp_kodes = list(master_produk["Kode_Produk"].astype(str).str.strip())
    plan_kodes = list(filling_plan["Kode_Produk"].astype(str).str.strip().unique())
    # Urutkan sesuai master_produk, sisanya append di belakang
    ordered_kodes = [k for k in mp_kodes if k in plan_kodes]
    ordered_kodes += [k for k in plan_kodes if k not in ordered_kodes]

    # Build lookup CS: (kode, date, shift) -> CS
    cs_lookup = {}
    for _, row in filling_plan.iterrows():
        kode  = str(row["Kode_Produk"]).strip()
        date  = str(row["Tanggal_Filling"])
        shift = int(row["Shift_Filling"])
        cs    = float(row["Target_CS"])
        key   = (kode, date, shift)
        cs_lookup[key] = cs_lookup.get(key, 0) + cs

    # Build nama lookup
    nama_lookup = {}
    for _, row in master_produk.iterrows():
        kode = str(row["Kode_Produk"]).strip()
        nama_lookup[kode] = row["Nama_Produk"]
    # Fallback dari filling_plan
    for _, row in filling_plan.iterrows():
        kode = str(row["Kode_Produk"]).strip()
        if kode not in nama_lookup:
            nama_lookup[kode] = row.get("Nama_Produk", kode)

    # Build urgent lookup — produk urgent di salah satu slot → tandai semua
    urgent_lookup = {}
    for _, row in filling_plan.iterrows():
        kode = str(row["Kode_Produk"]).strip()
        if row.get("Urgent", "") == "Urgent":
            urgent_lookup[kode] = True

    records = []
    for kode in ordered_kodes:
        nama   = nama_lookup.get(kode, kode)
        urgent = "✓" if urgent_lookup.get(kode, False) else ""
        rec    = {
            "Urgent":      urgent,
            "Kode_Produk": kode,
            "Nama_Produk": nama
        }
        total = 0
        for (d, s), label in zip(col_keys, col_labels):
            val = cs_lookup.get((kode, d, s), "")
            rec[label] = val if val != 0 else ""
            if val != "":
                total += val
        rec["Total_CS"] = total
        records.append(rec)

    filling_pivot_df = pd.DataFrame(records)

    return filling_pivot_df, {
        "col_keys":   col_keys,
        "col_labels": col_labels
    }


def _write_mixing_sheet(ws, pivot_df, meta, master_mixer):
    """Tulis sheet jadwal mixing ke worksheet yang sudah ada."""
    col_keys       = meta["col_keys"]
    cleaning       = meta["cleaning_cells"]
    resting        = meta["resting_cells"]
    rows           = meta["rows"]
    DATA_START_COL = 4

    hdr_fill    = PatternFill("solid", fgColor="1F4E79")
    hdr_font    = Font(bold=True, color="FFFFFF")
    subhdr_fill = PatternFill("solid", fgColor="2E75B6")
    subhdr_font = Font(bold=True, color="FFFFFF")
    clean_fill  = PatternFill("solid", fgColor="BDD7EE")
    rest_fill   = PatternFill("solid", fgColor="FFE699")
    mixer_fill  = PatternFill("solid", fgColor="D9E1F2")
    alt_fill    = PatternFill("solid", fgColor="EBF1DE")
    empty_fill  = PatternFill("solid", fgColor="FFFFFF")
    center      = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin        = Side(style="thin", color="BFBFBF")
    border      = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Row 1 fixed headers
    for col, label in [(1, "Mixer"), (2, "Kode\nProduk"), (3, "Nama Produk")]:
        cell           = ws.cell(row=1, column=col, value=label)
        cell.fill      = hdr_fill
        cell.font      = hdr_font
        cell.alignment = center
        ws.merge_cells(start_row=1, end_row=2, start_column=col, end_column=col)

    # Row 1 date headers — merge 3 shift per tanggal
    date_groups = {}
    for i, (d, s) in enumerate(col_keys):
        date_groups.setdefault(d, []).append(DATA_START_COL + i)

    for d, cols in date_groups.items():
        day_name  = date_to_day(d)
        dt_lbl    = datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
        start_col = cols[0]
        end_col   = cols[-1]
        cell      = ws.cell(row=1, column=start_col, value=f"{day_name}, {dt_lbl}")
        cell.fill      = subhdr_fill
        cell.font      = subhdr_font
        cell.alignment = center
        if end_col > start_col:
            ws.merge_cells(start_row=1, end_row=1,
                           start_column=start_col, end_column=end_col)

    # Row 2 shift headers
    for i, (d, s) in enumerate(col_keys):
        col        = DATA_START_COL + i
        cell       = ws.cell(row=2, column=col, value=f"Shift {s}")
        cell.fill  = subhdr_fill
        cell.font  = subhdr_font
        cell.alignment = center

    # Data rows
    mixer_list = list(master_mixer["Mixer"])
    cur_row    = 3

    for mixer in mixer_list:
        mixer_rows = [
            (m, k, n) for m, k, n in rows
            if m == mixer and
            not pivot_df[(pivot_df["Mixer"] == m) & (pivot_df["Kode_Produk"] == k)].empty
        ]
        if not mixer_rows:
            continue
        mixer_start = cur_row

        for ri, (m, kode, nama) in enumerate(mixer_rows):
            ws.cell(row=cur_row, column=1, value=mixer if ri == 0 else "")
            ws.cell(row=cur_row, column=2, value=kode).alignment = center
            ws.cell(row=cur_row, column=3, value=nama).alignment = center

            row_bg = alt_fill if ri % 2 == 0 else empty_fill

            for i, (d, s) in enumerate(col_keys):
                col  = DATA_START_COL + i
                cell = ws.cell(row=cur_row, column=col)
                cell.alignment = center
                cell.border    = border

                if (mixer, kode, d, s) in cleaning:
                    cell.fill  = clean_fill
                    cell.value = ""
                elif (mixer, kode, d, s) in resting:
                    cell.fill  = rest_fill
                    cell.value = ""
                else:
                    day_name = date_to_day(d)
                    dt_lbl   = datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
                    label    = f"{day_name} {dt_lbl} S{s}"
                    if label in pivot_df.columns:
                        val_series = pivot_df.loc[
                            (pivot_df["Mixer"] == mixer) &
                            (pivot_df["Kode_Produk"] == kode), label
                        ]
                        v = val_series.values[0] if len(val_series) > 0 else ""
                    else:
                        v = ""
                    cell.value = v if v != "" else ""
                    cell.fill  = row_bg

            cur_row += 1

        if cur_row - 1 > mixer_start:
            ws.merge_cells(start_row=mixer_start, end_row=cur_row - 1,
                           start_column=1, end_column=1)
        cell_mixer           = ws.cell(row=mixer_start, column=1)
        cell_mixer.fill      = mixer_fill
        cell_mixer.font      = Font(bold=True)
        cell_mixer.alignment = center

    # Legend
    cur_row += 1
    ws.cell(row=cur_row, column=1, value="Keterangan:").font = Font(bold=True)
    legends = [
        (clean_fill, "Cleaning (ganti grup produk)"),
        (rest_fill,  "Resting period (di gudang, mixer bebas dipakai)")
    ]
    for i, (fill, label) in enumerate(legends):
        col  = 2 + i * 2
        cell = ws.cell(row=cur_row, column=col)
        cell.fill   = fill
        cell.border = border
        ws.cell(row=cur_row, column=col + 1, value=label)

    # Column widths
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 22
    for i in range(len(col_keys)):
        ws.column_dimensions[get_column_letter(DATA_START_COL + i)].width = 10
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 22


def _write_filling_sheet(ws, filling_pivot_df, meta):
    """Tulis sheet jadwal filling ke worksheet yang sudah ada."""
    if filling_pivot_df.empty:
        ws.cell(row=1, column=1, value="Tidak ada data filling.")
        return

    col_keys       = meta["col_keys"]
    col_labels     = meta["col_labels"]
    DATA_START_COL = 4  # Urgent | Kode | Nama | ... shift cols ... | Total

    hdr_fill    = PatternFill("solid", fgColor="1F4E79")
    hdr_font    = Font(bold=True, color="FFFFFF")
    subhdr_fill = PatternFill("solid", fgColor="375623")
    subhdr_font = Font(bold=True, color="FFFFFF")
    urgent_fill = PatternFill("solid", fgColor="FCE4D6")
    alt_fill    = PatternFill("solid", fgColor="EBF1DE")
    empty_fill  = PatternFill("solid", fgColor="FFFFFF")
    total_fill  = PatternFill("solid", fgColor="D9E1F2")
    center      = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin        = Side(style="thin", color="BFBFBF")
    border      = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Row 1: fixed headers (Urgent, Kode, Nama) — merge 2 baris
    for col, label in [(1, "Urgent"), (2, "Kode\nProduk"), (3, "Nama Produk")]:
        cell           = ws.cell(row=1, column=col, value=label)
        cell.fill      = hdr_fill
        cell.font      = hdr_font
        cell.alignment = center
        ws.merge_cells(start_row=1, end_row=2, start_column=col, end_column=col)

    # Row 1: date headers — merge 3 shift per tanggal
    date_groups = {}
    for i, (d, s) in enumerate(col_keys):
        date_groups.setdefault(d, []).append(DATA_START_COL + i)

    for d, cols in date_groups.items():
        day_name  = date_to_day(d)
        dt_lbl    = datetime.strptime(d, "%Y-%m-%d").strftime("%d %b")
        start_col = cols[0]
        end_col   = cols[-1]
        cell      = ws.cell(row=1, column=start_col, value=f"{day_name}, {dt_lbl}")
        cell.fill      = subhdr_fill
        cell.font      = subhdr_font
        cell.alignment = center
        if end_col > start_col:
            ws.merge_cells(start_row=1, end_row=1,
                           start_column=start_col, end_column=end_col)

    # Total header
    total_col = DATA_START_COL + len(col_keys)
    cell      = ws.cell(row=1, column=total_col, value="Total CS")
    cell.fill      = hdr_fill
    cell.font      = hdr_font
    cell.alignment = center
    ws.merge_cells(start_row=1, end_row=2,
                   start_column=total_col, end_column=total_col)

    # Row 2: shift headers
    for i, (d, s) in enumerate(col_keys):
        col        = DATA_START_COL + i
        cell       = ws.cell(row=2, column=col, value=f"Shift {s}")
        cell.fill  = subhdr_fill
        cell.font  = subhdr_font
        cell.alignment = center

    # Data rows
    for ri, (_, row) in enumerate(filling_pivot_df.iterrows()):
        cur_row   = ri + 3
        is_urgent = row["Urgent"] == "✓"
        row_bg    = urgent_fill if is_urgent else (alt_fill if ri % 2 == 0 else empty_fill)

        # Urgent
        cell           = ws.cell(row=cur_row, column=1, value=row["Urgent"])
        cell.alignment = center
        cell.fill      = row_bg
        cell.border    = border

        # Kode
        cell           = ws.cell(row=cur_row, column=2, value=row["Kode_Produk"])
        cell.alignment = center
        cell.fill      = row_bg
        cell.border    = border

        # Nama
        cell      = ws.cell(row=cur_row, column=3, value=row["Nama_Produk"])
        cell.fill = row_bg
        cell.border = border

        # Shift columns
        for i, label in enumerate(col_labels):
            col  = DATA_START_COL + i
            val  = row.get(label, "")
            cell = ws.cell(row=cur_row, column=col, value=val if val != "" else None)
            cell.alignment = center
            cell.border    = border
            cell.fill      = row_bg
            if val != "" and val is not None:
                cell.number_format = "0.##"

        # Total CS
        cell           = ws.cell(row=cur_row, column=total_col, value=row["Total_CS"])
        cell.alignment = center
        cell.fill      = total_fill
        cell.font      = Font(bold=True)
        cell.border    = border
        cell.number_format = "0.##"

    # Grand total row
    grand_row = len(filling_pivot_df) + 3
    ws.cell(row=grand_row, column=3, value="TOTAL").font = Font(bold=True)
    ws.cell(row=grand_row, column=3).fill = total_fill

    for i, label in enumerate(col_labels):
        col   = DATA_START_COL + i
        total = sum(
            float(r) for r in filling_pivot_df[label]
            if r != "" and r is not None and str(r).strip() != ""
        )
        cell = ws.cell(row=grand_row, column=col,
                       value=total if total > 0 else None)
        cell.alignment    = center
        cell.fill         = total_fill
        cell.font         = Font(bold=True)
        cell.border       = border
        cell.number_format = "0.##"

    grand_total = filling_pivot_df["Total_CS"].sum()
    cell = ws.cell(row=grand_row, column=total_col, value=grand_total)
    cell.alignment    = center
    cell.fill         = total_fill
    cell.font         = Font(bold=True)
    cell.border       = border
    cell.number_format = "0.##"

    # Legend
    ws.cell(row=grand_row + 2, column=1, value="Keterangan:").font = Font(bold=True)
    leg_cell = ws.cell(row=grand_row + 2, column=2)
    leg_cell.fill   = urgent_fill
    leg_cell.border = border
    ws.cell(row=grand_row + 2, column=3, value="Produk Urgent")

    # Column widths
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 22
    for i in range(len(col_keys)):
        ws.column_dimensions[get_column_letter(DATA_START_COL + i)].width = 10
    ws.column_dimensions[get_column_letter(total_col)].width = 10
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 22


def pivot_to_excel(pivot_df, meta, master_mixer, filling_plan=None, master_produk=None):
    """
    Generate Excel dengan 2 sheet:
    1. Jadwal Mixing
    2. Jadwal Filling (jika filling_plan disediakan)
    """
    wb = Workbook()

    # ── Sheet 1: Jadwal Mixing ────────────────────────────────
    ws_mix       = wb.active
    ws_mix.title = "Jadwal Mixing"
    if not pivot_df.empty:
        _write_mixing_sheet(ws_mix, pivot_df, meta, master_mixer)
    else:
        ws_mix.cell(row=1, column=1, value="Tidak ada jadwal mixing.")

    # ── Sheet 2: Jadwal Filling ───────────────────────────────
    ws_fill       = wb.create_sheet("Jadwal Filling")
    if filling_plan is not None and not filling_plan.empty:
        mp = master_produk if master_produk is not None else pd.DataFrame()
        filling_pivot_df, filling_meta = build_filling_pivot(filling_plan, mp)
        _write_filling_sheet(ws_fill, filling_pivot_df, filling_meta)
    else:
        ws_fill.cell(row=1, column=1, value="Tidak ada data filling.")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
