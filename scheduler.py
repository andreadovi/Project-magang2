# scheduler.py
import re
import pandas as pd
from datetime import datetime, timedelta


# ─── Helpers ──────────────────────────────────────────────────────────────────

def parse_mixer_compat(raw, valid_mixer_set):
    raw_str = str(raw).strip()
    if not raw_str or raw_str.lower() in ["nan", "none", "0", ""]:
        return []
    parts = [m.strip() for m in raw_str.split(",")]
    return [m for m in parts if m in valid_mixer_set]


def kg_needed(target_cs, kg_per_cs):
    try:
        return float(target_cs) * float(kg_per_cs)
    except Exception:
        return 0.0


def normalize_columns(df):
    df = df.copy()
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"[^\w]", "", regex=True)
    )
    return df


def apply_col_map(df, col_map):
    df = normalize_columns(df)
    rename = {}
    for col in df.columns:
        key = col.lower()
        if key in col_map:
            rename[col] = col_map[key]
    return df.rename(columns=rename)


def check_required_cols(df, required, label):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"[{label}] Kolom wajib tidak ditemukan: {missing}. "
            f"Kolom yang ada: {list(df.columns)}"
        )


# ─── Column Maps ──────────────────────────────────────────────────────────────

FILLING_COL_MAP = {
    "kode_produk":     "Kode_Produk",
    "kodeproduk":      "Kode_Produk",
    "kode":            "Kode_Produk",
    "product_code":    "Kode_Produk",
    "target_cs":       "Target_CS",
    "targetcs":        "Target_CS",
    "target":          "Target_CS",
    "qty":             "Target_CS",
    "quantity":        "Target_CS",
    "jumlah_cs":       "Target_CS",
    "tanggal_filling": "Tanggal_Filling",
    "tanggalfilling":  "Tanggal_Filling",
    "tgl_filling":     "Tanggal_Filling",
    "tanggal":         "Tanggal_Filling",
    "filling_date":    "Tanggal_Filling",
    "shift_filling":   "Shift_Filling",
    "shiftfilling":    "Shift_Filling",
    "shift":           "Shift_Filling",
    "urgent":          "Urgent",
    "prioritas":       "Urgent",
    "priority":        "Urgent",
}

MIXER_COL_MAP = {
    "mixer":           "Mixer",
    "nama_mixer":      "Mixer",
    "kapasitas_kg":    "Kapasitas_kg",
    "kapasitas":       "Kapasitas_kg",
    "capacity_kg":     "Kapasitas_kg",
    "batch_per_shift": "Batch_per_Shift",
    "batch":           "Batch_per_Shift",
    "grup_cleaning":   "Grup_Cleaning",
    "grup":            "Grup_Cleaning",
    "group":           "Grup_Cleaning",
}

PRODUK_COL_MAP = {
    "kode_produk":      "Kode_Produk",
    "kodeproduk":       "Kode_Produk",
    "kode":             "Kode_Produk",
    "nama_produk":      "Nama_Produk",
    "namaproduk":       "Nama_Produk",
    "nama":             "Nama_Produk",
    "kode_mc_liquid":   "Kode_MC_Liquid",
    "kode_mc":          "Kode_MC_Liquid",
    "mc_liquid":        "Kode_MC_Liquid",
    "kg_per_cs":        "Kg_per_CS",
    "kgpercs":          "Kg_per_CS",
    "kg_cs":            "Kg_per_CS",
    "resting_days":     "Resting_Days",
    "restingdays":      "Resting_Days",
    "resting":          "Resting_Days",
    "grup_cleaning":    "Grup_Cleaning",
    "grup":             "Grup_Cleaning",
    "mixer_kompatibel": "Mixer_Kompatibel",
    "mixer_compatible": "Mixer_Kompatibel",
    "mixer":            "Mixer_Kompatibel",
}


# ─── Unpivot Filling Plan ─────────────────────────────────────────────────────

def unpivot_filling_plan(df):
    """
    Konversi Filling Plan format kalender (wide) ke format panjang (long).
    Jika sudah format panjang (ada kolom Tanggal_Filling & Target_CS),
    dikembalikan langsung tanpa perubahan.
    """
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    # Cek apakah sudah format panjang
    norm_cols = [c.lower().replace(" ", "_") for c in df.columns]
    has_tanggal = any("tanggal" in c or "filling_date" in c for c in norm_cols)
    has_target  = any("target" in c or "qty" in c or "quantity" in c for c in norm_cols)
    if has_tanggal and has_target:
        return df

    # Deteksi kolom tetap
    fixed_cols = []
    for c in df.columns:
        cl = c.lower().replace(" ", "_")
        if any(k in cl for k in ["kode", "nama", "urgent", "prioritas", "priority"]):
            fixed_cols.append(c)

    value_cols = [c for c in df.columns if c not in fixed_cols]

    if not value_cols:
        return df

    # Melt ke format panjang
    melted = df.melt(
        id_vars=fixed_cols,
        value_vars=value_cols,
        var_name="_col_header",
        value_name="Target_CS",
    )

    melted["Target_CS"] = pd.to_numeric(melted["Target_CS"], errors="coerce")
    melted = melted[melted["Target_CS"].notna() & (melted["Target_CS"] > 0)].copy()

    if melted.empty:
        return pd.DataFrame(columns=[
            "Kode_Produk", "Target_CS", "Tanggal_Filling", "Shift_Filling", "Urgent"
        ])

    # Parse header kolom → Tanggal_Filling + Shift_Filling
    def parse_col(header):
        header = str(header).strip()

        # Format DD/MM/YYYY atau DD-MM-YYYY
        m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", header)
        if m:
            try:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if y < 100:
                    y += 2000
                tanggal = datetime(y, mo, d)
            except Exception:
                return None, None
        else:
            # Format YYYY-MM-DD
            m2 = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", header)
            if m2:
                try:
                    tanggal = datetime(
                        int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
                    )
                except Exception:
                    return None, None
            else:
                return None, None

        ms = re.search(r"[Ss](\d)", header)
        shift = int(ms.group(1)) if ms else 1
        return tanggal.strftime("%Y-%m-%d"), shift

    parsed = melted["_col_header"].apply(lambda h: pd.Series(parse_col(h)))
    melted["Tanggal_Filling"] = parsed[0]
    melted["Shift_Filling"]   = parsed[1]
    melted = melted[melted["Tanggal_Filling"].notna()].copy()
    melted = melted.drop(columns=["_col_header"])

    # Rename kolom tetap
    rename = {}
    for c in melted.columns:
        cl = c.lower().replace(" ", "_")
        if "kode" in cl and "produk" in cl:
            rename[c] = "Kode_Produk"
        elif any(k in cl for k in ["urgent", "prioritas", "priority"]):
            rename[c] = "Urgent"
    melted = melted.rename(columns=rename)

    if "Urgent" not in melted.columns:
        melted["Urgent"] = "Normal"
    if "Shift_Filling" not in melted.columns:
        melted["Shift_Filling"] = 1

    melted["Shift_Filling"] = (
        pd.to_numeric(melted["Shift_Filling"], errors="coerce")
        .fillna(1).astype(int)
    )

    return melted.reset_index(drop=True)


# ─── Main Scheduler ───────────────────────────────────────────────────────────

def generate_mixing_schedule(master_mixer_df, master_produk_df, filling_plan_df):
    warnings_list = []
    shifted_list  = []
    unscheduled   = []
    schedule_rows = []

    # Normalisasi master mixer
    mixer_df = apply_col_map(master_mixer_df, MIXER_COL_MAP)
    check_required_cols(mixer_df, ["Mixer", "Kapasitas_kg", "Batch_per_Shift"], "Master Mixer")

    mixer_df["Mixer"]           = mixer_df["Mixer"].astype(str).str.strip()
    mixer_df["Kapasitas_kg"]    = pd.to_numeric(mixer_df["Kapasitas_kg"],    errors="coerce").fillna(500)
    mixer_df["Batch_per_Shift"] = pd.to_numeric(mixer_df["Batch_per_Shift"], errors="coerce").fillna(2)
    if "Grup_Cleaning" not in mixer_df.columns:
        mixer_df["Grup_Cleaning"] = "DEFAULT"
    mixer_df["Grup_Cleaning"] = mixer_df["Grup_Cleaning"].astype(str).str.strip()

    valid_mixer_set = set(mixer_df["Mixer"].tolist())

    # Normalisasi master produk
    produk_df = apply_col_map(master_produk_df, PRODUK_COL_MAP)
    check_required_cols(produk_df, ["Kode_Produk", "Kg_per_CS"], "Master Produk")

    produk_df["Kode_Produk"] = produk_df["Kode_Produk"].astype(str).str.strip()
    produk_df["Kg_per_CS"]   = pd.to_numeric(produk_df["Kg_per_CS"], errors="coerce").fillna(0)
    if "Resting_Days" not in produk_df.columns:
        produk_df["Resting_Days"] = 0
    produk_df["Resting_Days"] = pd.to_numeric(
        produk_df["Resting_Days"], errors="coerce"
    ).fillna(0)
    if "Nama_Produk" not in produk_df.columns:
        produk_df["Nama_Produk"] = produk_df["Kode_Produk"]
    if "Kode_MC_Liquid" not in produk_df.columns:
        produk_df["Kode_MC_Liquid"] = ""
    if "Grup_Cleaning" not in produk_df.columns:
        produk_df["Grup_Cleaning"] = "DEFAULT"
    if "Mixer_Kompatibel" not in produk_df.columns:
        produk_df["Mixer_Kompatibel"] = ",".join(valid_mixer_set)

    produk_df["Grup_Cleaning"]    = produk_df["Grup_Cleaning"].astype(str).str.strip()
    produk_df["Mixer_Kompatibel"] = produk_df["Mixer_Kompatibel"].astype(str).str.strip()

    kode_to_row = {row["Kode_Produk"]: row for _, row in produk_df.iterrows()}

    # Normalisasi filling plan
    fp = apply_col_map(filling_plan_df, FILLING_COL_MAP)
    check_required_cols(fp, ["Kode_Produk", "Target_CS", "Tanggal_Filling"], "Filling Plan")

    fp["Kode_Produk"]     = fp["Kode_Produk"].astype(str).str.strip()
    fp["Target_CS"]       = pd.to_numeric(fp["Target_CS"], errors="coerce").fillna(0)
    fp["Tanggal_Filling"] = pd.to_datetime(fp["Tanggal_Filling"])
    if "Shift_Filling" not in fp.columns:
        fp["Shift_Filling"] = 1
    fp["Shift_Filling"] = pd.to_numeric(
        fp["Shift_Filling"], errors="coerce"
    ).fillna(1).astype(int)
    if "Urgent" not in fp.columns:
        fp["Urgent"] = "Normal"
    fp["Urgent"] = fp["Urgent"].astype(str).str.strip()

    # State kapasitas slot
    slot_used = {}
    last_grup = {}

    def mixer_max_kg(mixer):
        row = mixer_df[mixer_df["Mixer"] == mixer]
        if row.empty:
            return 0.0
        r = row.iloc[0]
        return float(r["Kapasitas_kg"]) * float(r["Batch_per_Shift"])

    def slot_remaining(date_str, shift, mixer):
        return max(
            0.0,
            mixer_max_kg(mixer) - slot_used.get((date_str, shift, mixer), 0.0)
        )

    def use_slot(date_str, shift, mixer, kg):
        key = (date_str, shift, mixer)
        slot_used[key] = slot_used.get(key, 0.0) + kg

    def needs_cleaning(mixer, grup_produk):
        prev = last_grup.get(mixer)
        return False if prev is None else prev != grup_produk

    def get_candidate_slots(fill_date, fill_shift, rest_days, window_days=6):
        deadline_dt = fill_date - timedelta(days=max(rest_days, 0))
        fill_d_str  = fill_date.strftime("%Y-%m-%d")
        all_slots   = []
        for delta in range(window_days):
            d     = deadline_dt - timedelta(days=delta)
            d_str = d.strftime("%Y-%m-%d")
            for shift in [3, 2, 1]:
                if rest_days == 0 and d_str == fill_d_str and shift >= fill_shift:
                    continue
                all_slots.append((d_str, shift, delta, shift))
        all_slots.sort(key=lambda x: (x[2], -x[3]))
        return [(d_str, shift) for d_str, shift, _, _ in all_slots]

    # Urutkan: Urgent dulu
    fp["_urgent_sort"] = fp["Urgent"].apply(lambda x: 0 if x == "Urgent" else 1)
    fp = fp.sort_values(
        ["_urgent_sort", "Tanggal_Filling", "Shift_Filling"]
    ).reset_index(drop=True)

    # Proses setiap item
    for _, job in fp.iterrows():
        kode       = job["Kode_Produk"]
        target_cs  = job["Target_CS"]
        fill_date  = job["Tanggal_Filling"]
        fill_shift = job["Shift_Filling"]
        is_urgent  = job["Urgent"] == "Urgent"

        if target_cs <= 0:
            continue

        if kode not in kode_to_row:
            unscheduled.append(f"{kode}: Tidak ditemukan di Master Produk.")
            continue

        prod       = kode_to_row[kode]
        nama       = str(prod["Nama_Produk"])
        kode_mc    = str(prod.get("Kode_MC_Liquid", ""))
        grup_clean = str(prod["Grup_Cleaning"])
        kg_per_cs  = float(prod["Kg_per_CS"])
        rest_days  = int(float(prod["Resting_Days"]))

        if kg_per_cs <= 0:
            unscheduled.append(f"{kode} - {nama}: Kg_per_CS = 0, skip.")
            continue

        compat_mixers = parse_mixer_compat(prod["Mixer_Kompatibel"], valid_mixer_set)
        if not compat_mixers:
            unscheduled.append(
                f"{kode} - {nama}: Tidak ada mixer valid "
                f"(Mixer_Kompatibel='{prod['Mixer_Kompatibel']}')."
            )
            continue

        total_kg     = kg_needed(target_cs, kg_per_cs)
        remaining_kg = total_kg
        assigned     = []

        for (cdate, shift) in get_candidate_slots(
            fill_date, fill_shift, rest_days, window_days=6
        ):
            if remaining_kg <= 0:
                break
            for mixer in compat_mixers:
                if remaining_kg <= 0:
                    break
                rem = slot_remaining(cdate, shift, mixer)
                if rem <= 0:
                    continue

                cleaning_needed = needs_cleaning(mixer, grup_clean)
                kg_this_slot    = min(remaining_kg, rem)

                use_slot(cdate, shift, mixer, kg_this_slot)
                remaining_kg    -= kg_this_slot
                last_grup[mixer] = grup_clean

                assigned.append({
                    "Tanggal_Mixing":  cdate,
                    "Shift_Mixing":    shift,
                    "Mixer":           mixer,
                    "Kode_Produk":     kode,
                    "Kode_MC_Liquid":  kode_mc,
                    "Nama_Produk":     nama,
                    "Grup_Cleaning":   grup_clean,
                    "Kg_Mixing":       round(kg_this_slot, 3),
                    "Resting_Days":    rest_days,
                    "Tanggal_Filling": fill_date.strftime("%Y-%m-%d"),
                    "Shift_Filling":   fill_shift,
                    "Urgent":          job["Urgent"],
                    "Cleaning":        cleaning_needed,
                })

        schedule_rows.extend(assigned)

        # Toleransi 1%
        if remaining_kg > round(total_kg * 0.01, 3):
            if is_urgent:
                unscheduled.append(
                    f"{kode} - {nama} [URGENT]: Kapasitas mixer tidak cukup. "
                    f"Sisa {round(remaining_kg, 1)} kg dari {round(total_kg, 1)} kg."
                )
            else:
                new_fill_date = fill_date + timedelta(days=1)
                shifted_list.append({
                    "Kode_Produk":        kode,
                    "Nama_Produk":        nama,
                    "Original_Fill_Date": fill_date.strftime("%Y-%m-%d"),
                    "New_Fill_Date":      new_fill_date.strftime("%Y-%m-%d"),
                    "Shift_Filling":      fill_shift,
                    "Alasan": (
                        f"Kapasitas mixer tidak cukup "
                        f"(sisa {round(remaining_kg, 1)} kg "
                        f"dari {round(total_kg, 1)} kg)"
                    ),
                })
                warnings_list.append(
                    f"⚠️ {kode} - {nama}: Filling digeser ke "
                    f"{new_fill_date.strftime('%d/%m/%Y')} "
                    f"karena kapasitas tidak cukup."
                )

    if schedule_rows:
        schedule_df = pd.DataFrame(schedule_rows)
        schedule_df = schedule_df.sort_values(
            ["Tanggal_Mixing", "Shift_Mixing", "Mixer"]
        ).reset_index(drop=True)
    else:
        schedule_df = pd.DataFrame(columns=[
            "Tanggal_Mixing", "Shift_Mixing", "Mixer",
            "Kode_Produk", "Kode_MC_Liquid", "Nama_Produk",
            "Grup_Cleaning", "Kg_Mixing", "Resting_Days",
            "Tanggal_Filling", "Shift_Filling", "Urgent", "Cleaning",
        ])

    return {
        "schedule":    schedule_df,
        "warnings":    warnings_list,
        "shifted":     shifted_list,
        "unscheduled": unscheduled,
    }
