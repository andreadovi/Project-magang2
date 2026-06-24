# scheduler.py
import re
import math
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


def round_up_to_batch(kg, kapasitas_per_batch):
    if kapasitas_per_batch <= 0:
        return kg
    n_batch = math.ceil(kg / kapasitas_per_batch)
    return n_batch * kapasitas_per_batch


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
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip()

    norm_cols   = [c.lower().replace(" ", "_") for c in df.columns]
    has_tanggal = any("tanggal" in c or "filling_date" in c for c in norm_cols)
    has_target  = any("target" in c or "qty" in c or "quantity" in c for c in norm_cols)
    if has_tanggal and has_target:
        return df

    fixed_cols = []
    for c in df.columns:
        cl = c.lower().replace(" ", "_")
        if any(k in cl for k in ["kode", "nama", "urgent", "prioritas", "priority"]):
            fixed_cols.append(c)

    value_cols = [c for c in df.columns if c not in fixed_cols]
    if not value_cols:
        return df

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

    def parse_col(header):
        header = str(header).strip()
        m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", header)
        if m:
            try:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if y < 100: y += 2000
                tanggal = datetime(y, mo, d)
            except Exception:
                return None, None
        else:
            m2 = re.search(r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", header)
            if m2:
                try:
                    tanggal = datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
                except Exception:
                    return None, None
            else:
                return None, None
        ms    = re.search(r"[Ss](\d)", header)
        shift = int(ms.group(1)) if ms else 1
        return tanggal.strftime("%Y-%m-%d"), shift

    parsed = melted["_col_header"].apply(lambda h: pd.Series(parse_col(h)))
    melted["Tanggal_Filling"] = parsed[0]
    melted["Shift_Filling"]   = parsed[1]
    melted = melted[melted["Tanggal_Filling"].notna()].drop(columns=["_col_header"])

    rename = {}
    for c in melted.columns:
        cl = c.lower().replace(" ", "_")
        if "kode" in cl and "produk" in cl:
            rename[c] = "Kode_Produk"
        elif any(k in cl for k in ["urgent", "prioritas", "priority"]):
            rename[c] = "Urgent"
    melted = melted.rename(columns=rename)

    if "Urgent"        not in melted.columns: melted["Urgent"]        = "Normal"
    if "Shift_Filling" not in melted.columns: melted["Shift_Filling"] = 1
    melted["Shift_Filling"] = (
        pd.to_numeric(melted["Shift_Filling"], errors="coerce").fillna(1).astype(int)
    )
    return melted.reset_index(drop=True)


# ─── Candidate Slots ──────────────────────────────────────────────────────────

def get_candidate_slots(fill_date, fill_shift, rest_days, window_days=6):
    deadline_dt = fill_date - timedelta(days=max(rest_days, 0))
    fill_d_str  = fill_date.strftime("%Y-%m-%d")
    all_slots   = []

    for delta in range(window_days):
        d           = deadline_dt - timedelta(days=delta)
        d_str       = d.strftime("%Y-%m-%d")
        day_penalty = 100 if d.weekday() == 6 else 0

        for shift in [3, 2, 1]:
            if rest_days == 0 and d_str == fill_d_str and shift >= fill_shift:
                continue
            all_slots.append((d_str, shift, delta, shift, day_penalty))

    all_slots.sort(key=lambda x: (x[4], x[2], -x[3]))
    return [(d_str, shift) for d_str, shift, _, _, _ in all_slots]


def get_consecutive_slots(start_date_str, start_shift, mixer,
                          n_slots_needed, slot_used, mixer_locked,
                          mixer_max_kg_fn, kap_batch, kode,
                          fill_date_str, rest_days):
    """
    Cek apakah tersedia n_slots_needed slot BERURUTAN mulai dari
    (start_date_str, start_shift) pada mixer yang sama.
    Berurutan = S1→S2→S3 di hari yang sama, TIDAK lompat ke hari lain
    kecuali melanjutkan dari S3 ke hari berikutnya S1.

    Return list of (date_str, shift) jika semua slot tersedia,
    atau None jika tidak cukup.
    """
    slots = []
    d_str = start_date_str
    shift = start_shift
    d_dt  = datetime.strptime(d_str, "%Y-%m-%d")

    for _ in range(n_slots_needed):
        # Cek batas: tidak boleh melewati fill_date
        if d_str > fill_date_str:
            return None

        slot_key = (d_str, shift, mixer)

        # Slot harus kosong atau sudah dikunci produk ini
        if slot_key in mixer_locked and mixer_locked[slot_key] != kode:
            return None

        rem = mixer_max_kg_fn(mixer) - slot_used.get(slot_key, 0.0)
        if rem < kap_batch:
            return None

        slots.append((d_str, shift))

        # Maju ke slot berikutnya (berurutan)
        if shift < 3:
            shift += 1
        else:
            # Lanjut ke hari berikutnya shift 1
            d_dt  = d_dt + timedelta(days=1)
            d_str = d_dt.strftime("%Y-%m-%d")
            shift = 1

    return slots


# ─── Main Scheduler ───────────────────────────────────────────────────────────

def generate_mixing_schedule(master_mixer_df, master_produk_df, filling_plan_df):
    warnings_list = []
    shifted_list  = []
    unscheduled   = []
    schedule_rows = []

    # ── Normalisasi master mixer ──
    mixer_df = apply_col_map(master_mixer_df, MIXER_COL_MAP)
    check_required_cols(mixer_df, ["Mixer", "Kapasitas_kg", "Batch_per_Shift"], "Master Mixer")
    mixer_df["Mixer"]           = mixer_df["Mixer"].astype(str).str.strip()
    mixer_df["Kapasitas_kg"]    = pd.to_numeric(mixer_df["Kapasitas_kg"],    errors="coerce").fillna(500)
    mixer_df["Batch_per_Shift"] = pd.to_numeric(mixer_df["Batch_per_Shift"], errors="coerce").fillna(2)
    if "Grup_Cleaning" not in mixer_df.columns: mixer_df["Grup_Cleaning"] = "DEFAULT"
    mixer_df["Grup_Cleaning"] = mixer_df["Grup_Cleaning"].astype(str).str.strip()
    valid_mixer_set = set(mixer_df["Mixer"].tolist())

    # ── Normalisasi master produk ──
    produk_df = apply_col_map(master_produk_df, PRODUK_COL_MAP)
    check_required_cols(produk_df, ["Kode_Produk", "Kg_per_CS"], "Master Produk")
    produk_df["Kode_Produk"] = produk_df["Kode_Produk"].astype(str).str.strip()
    produk_df["Kg_per_CS"]   = pd.to_numeric(produk_df["Kg_per_CS"], errors="coerce").fillna(0)
    if "Resting_Days"     not in produk_df.columns: produk_df["Resting_Days"]     = 0
    if "Nama_Produk"      not in produk_df.columns: produk_df["Nama_Produk"]      = produk_df["Kode_Produk"]
    if "Kode_MC_Liquid"   not in produk_df.columns: produk_df["Kode_MC_Liquid"]   = ""
    if "Grup_Cleaning"    not in produk_df.columns: produk_df["Grup_Cleaning"]    = "DEFAULT"
    if "Mixer_Kompatibel" not in produk_df.columns: produk_df["Mixer_Kompatibel"] = ",".join(valid_mixer_set)
    produk_df["Resting_Days"]     = pd.to_numeric(produk_df["Resting_Days"], errors="coerce").fillna(0)
    produk_df["Grup_Cleaning"]    = produk_df["Grup_Cleaning"].astype(str).str.strip()
    produk_df["Mixer_Kompatibel"] = produk_df["Mixer_Kompatibel"].astype(str).str.strip()
    kode_to_row = {row["Kode_Produk"]: row for _, row in produk_df.iterrows()}

    # ── Normalisasi filling plan ──
    fp = apply_col_map(filling_plan_df, FILLING_COL_MAP)
    check_required_cols(fp, ["Kode_Produk", "Target_CS", "Tanggal_Filling"], "Filling Plan")
    fp["Kode_Produk"]     = fp["Kode_Produk"].astype(str).str.strip()
    fp["Target_CS"]       = pd.to_numeric(fp["Target_CS"], errors="coerce").fillna(0)
    fp["Tanggal_Filling"] = pd.to_datetime(fp["Tanggal_Filling"])
    if "Shift_Filling" not in fp.columns: fp["Shift_Filling"] = 1
    if "Urgent"        not in fp.columns: fp["Urgent"]        = "Normal"
    fp["Shift_Filling"] = pd.to_numeric(fp["Shift_Filling"], errors="coerce").fillna(1).astype(int)
    fp["Urgent"]        = fp["Urgent"].astype(str).str.strip()

    # ── Helper kapasitas ──
    def mixer_kapasitas_batch(mixer):
        row = mixer_df[mixer_df["Mixer"] == mixer]
        return float(row.iloc[0]["Kapasitas_kg"]) if not row.empty else 0.0

    def mixer_max_kg(mixer):
        row = mixer_df[mixer_df["Mixer"] == mixer]
        if row.empty: return 0.0
        r = row.iloc[0]
        return float(r["Kapasitas_kg"]) * float(r["Batch_per_Shift"])

    # ── State ──
    slot_used    = {}
    last_grup    = {}
    mixer_locked = {}

    def slot_remaining(date_str, shift, mixer):
        return max(0.0, mixer_max_kg(mixer) - slot_used.get((date_str, shift, mixer), 0.0))

    def use_slot(date_str, shift, mixer, kg):
        key = (date_str, shift, mixer)
        slot_used[key] = slot_used.get(key, 0.0) + kg

    def needs_cleaning(mixer, grup_produk):
        prev = last_grup.get(mixer)
        return False if prev is None else prev != grup_produk

    # ── Urutkan: Urgent dulu ──
    fp["_urgent_sort"] = fp["Urgent"].apply(lambda x: 0 if x == "Urgent" else 1)
    fp = fp.sort_values(["_urgent_sort", "Tanggal_Filling", "Shift_Filling"]).reset_index(drop=True)

    # ── Proses setiap item ──
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

        total_kg      = kg_needed(target_cs, kg_per_cs)
        fill_date_str = fill_date.strftime("%Y-%m-%d")
        scheduled     = False

        for (cdate, cshift) in get_candidate_slots(fill_date, fill_shift, rest_days, window_days=6):
            if scheduled:
                break

            for mixer in compat_mixers:
                if scheduled:
                    break

                kap_batch = mixer_kapasitas_batch(mixer)
                if kap_batch <= 0:
                    continue

                # Hitung berapa slot berurutan yang dibutuhkan
                kg_dibutuhkan = round_up_to_batch(total_kg, kap_batch)
                n_slots       = math.ceil(kg_dibutuhkan / mixer_max_kg(mixer)) if mixer_max_kg(mixer) > 0 else 1
                n_slots       = max(n_slots, 1)

                # Cek apakah tersedia n_slots berurutan mulai (cdate, cshift)
                consec = get_consecutive_slots(
                    cdate, cshift, mixer,
                    n_slots, slot_used, mixer_locked,
                    mixer_max_kg, kap_batch, kode,
                    fill_date_str, rest_days
                )

                if consec is None:
                    continue

                # Semua slot tersedia → assign
                cleaning_needed  = needs_cleaning(mixer, grup_clean)
                remaining_kg     = kg_dibutuhkan

                for i, (d_str, s) in enumerate(consec):
                    kg_slot = min(remaining_kg, mixer_max_kg(mixer))
                    # Bulatkan ke kelipatan batch
                    kg_slot      = round_up_to_batch(
                        min(remaining_kg, mixer_max_kg(mixer)), kap_batch
                    )
                    kg_slot      = min(kg_slot, mixer_max_kg(mixer))
                    slot_key     = (d_str, s, mixer)
                    use_slot(d_str, s, mixer, kg_slot)
                    mixer_locked[slot_key] = kode
                    remaining_kg          -= min(remaining_kg, kg_slot)
                    last_grup[mixer]       = grup_clean

                    schedule_rows.append({
                        "Tanggal_Mixing":  d_str,
                        "Shift_Mixing":    s,
                        "Mixer":           mixer,
                        "Kode_Produk":     kode,
                        "Kode_MC_Liquid":  kode_mc,
                        "Nama_Produk":     nama,
                        "Grup_Cleaning":   grup_clean,
                        "Kg_Mixing":       round(kg_slot, 3),
                        "Resting_Days":    rest_days,
                        "Tanggal_Filling": fill_date_str,
                        "Shift_Filling":   fill_shift,
                        "Urgent":          job["Urgent"],
                        # Cleaning hanya di slot pertama
                        "Cleaning":        cleaning_needed if i == 0 else False,
                    })

                scheduled = True

        if not scheduled:
            if is_urgent:
                unscheduled.append(
                    f"{kode} - {nama} [URGENT]: Tidak ada slot berurutan yang cukup "
                    f"untuk {round(total_kg, 1)} kg."
                )
            else:
                new_fill_date = fill_date + timedelta(days=1)
                shifted_list.append({
                    "Kode_Produk":        kode,
                    "Nama_Produk":        nama,
                    "Original_Fill_Date": fill_date_str,
                    "New_Fill_Date":      new_fill_date.strftime("%Y-%m-%d"),
                    "Shift_Filling":      fill_shift,
                    "Alasan":             f"Tidak ada slot berurutan untuk {round(total_kg, 1)} kg",
                })
                warnings_list.append(
                    f"⚠️ {kode} - {nama}: Filling digeser ke "
                    f"{new_fill_date.strftime('%d/%m/%Y')} "
                    f"karena tidak ada slot berurutan yang cukup."
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
