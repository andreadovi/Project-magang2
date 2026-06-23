import pandas as pd
from datetime import datetime, timedelta
import math

SHIFTS_PER_DAY    = 3
BATCHES_PER_SHIFT = 2
MIN_LEAD_SHIFTS   = 2
MAX_SHELF_DAYS    = 6


def shift_index(date_str, shift):
    d     = datetime.strptime(str(date_str), "%Y-%m-%d")
    epoch = datetime(2000, 1, 1)
    return (d - epoch).days * SHIFTS_PER_DAY + (int(shift) - 1)


def index_to_shift(idx):
    epoch = datetime(2000, 1, 1)
    d     = epoch + timedelta(days=idx // SHIFTS_PER_DAY)
    shift = (idx % SHIFTS_PER_DAY) + 1
    return d.strftime("%Y-%m-%d"), shift


def same_week(date_str1, date_str2):
    d1 = datetime.strptime(str(date_str1), "%Y-%m-%d")
    d2 = datetime.strptime(str(date_str2), "%Y-%m-%d")
    return d1.isocalendar()[1] == d2.isocalendar()[1] and d1.year == d2.year


def get_deadline_idx(fill_date, fill_shift, resting_days,
                     min_lead_shifts=MIN_LEAD_SHIFTS):
    fill_idx = shift_index(fill_date, fill_shift)
    if resting_days == 0:
        return fill_idx - min_lead_shifts
    else:
        return fill_idx - (resting_days * SHIFTS_PER_DAY) - min_lead_shifts


def get_earliest_idx(fill_date, fill_shift, max_shelf_days=MAX_SHELF_DAYS):
    fill_idx = shift_index(fill_date, fill_shift)
    return fill_idx - (max_shelf_days * SHIFTS_PER_DAY)


def try_schedule_on_mixer(mixer_name, mixer_schedule, deadline_idx, earliest_idx,
                           target_kg, cap, batch_per_shift, grup_produk):
    remaining_kg = target_kg
    search_idx   = deadline_idx
    assignments  = []

    while remaining_kg > 0:
        if search_idx < 0 or search_idx < earliest_idx:
            return None

        state = mixer_schedule[mixer_name].get(search_idx, {
            "batches_used": 0, "grup": None,
            "cleaning": False, "items": []
        })

        if state.get("cleaning", False):
            assignments  = []
            remaining_kg = target_kg
            search_idx  -= 1
            continue

        avail = batch_per_shift - state.get("batches_used", 0)

        if avail <= 0:
            assignments  = []
            remaining_kg = target_kg
            search_idx  -= 1
            continue

        used_before = sorted(
            [s for s in mixer_schedule[mixer_name]
             if s < search_idx
             and not mixer_schedule[mixer_name][s].get("cleaning", False)
             and mixer_schedule[mixer_name][s].get("grup") is not None],
            reverse=True
        )
        last_grup = mixer_schedule[mixer_name][used_before[0]]["grup"] if used_before else None

        if last_grup is not None and last_grup != grup_produk:
            assignments  = []
            remaining_kg = target_kg
            search_idx  -= 1
            continue

        use_kg      = min(avail * cap, remaining_kg)
        use_batches = math.ceil(use_kg / cap)
        actual_kg   = use_batches * cap
        s_date, s_shift = index_to_shift(search_idx)
        assignments.insert(0, {
            "mixer":        mixer_name,
            "shift_idx":    search_idx,
            "batches":      use_batches,
            "kg_per_batch": cap,
            "kg":           actual_kg,
            "cs":           0,
            "last_grup":    last_grup,
            "date":         s_date,
            "shift":        s_shift
        })
        remaining_kg -= actual_kg
        search_idx   -= 1

    return assignments if remaining_kg <= 0 else None


def generate_mixing_schedule(master_mixer, master_produk, filling_plan,
                              date_range=None,
                              min_lead_shifts=MIN_LEAD_SHIFTS,
                              max_shelf_days=MAX_SHELF_DAYS):
    warnings      = []
    shifted       = []
    unscheduled   = []
    schedule_rows = []

    mixer_df  = master_mixer.copy()
    produk_df = master_produk.copy()
    plan_df   = filling_plan.copy()

    mixer_df["Mixer"] = mixer_df["Mixer"].astype(str).str.strip()

    produk_df["Mixer_List"] = produk_df["Mixer_Kompatibel"].apply(
        lambda x: [m.strip() for m in str(x).split(",")]
    )
    if "Resting_Days" not in produk_df.columns:
        produk_df["Resting_Days"] = 0
    produk_df["Resting_Days"] = produk_df["Resting_Days"].fillna(0).astype(int)

    # Normalize kode di master produk
    produk_df["_kode_str"] = produk_df["Kode_Produk"].astype(str).str.strip()

    # ── Mixer state ───────────────────────────────────────────
    mixer_schedule  = {row["Mixer"]: {} for _, row in mixer_df.iterrows()}
    mixer_last_grup = {row["Mixer"]: None for _, row in mixer_df.iterrows()}

    def get_mixer_capacity(mixer_name):
        row = mixer_df[mixer_df["Mixer"] == mixer_name]
        return float(row["Kapasitas_kg"].values[0]) if not row.empty else 0

    def get_batch_per_shift(mixer_name):
        row = mixer_df[mixer_df["Mixer"] == mixer_name]
        if not row.empty and "Batch_per_Shift" in row.columns:
            return int(row["Batch_per_Shift"].values[0])
        return BATCHES_PER_SHIFT

    def get_shift_state(mixer_name, sidx):
        if sidx not in mixer_schedule[mixer_name]:
            mixer_schedule[mixer_name][sidx] = {
                "batches_used": 0, "grup": None,
                "items": [], "cleaning": False
            }
        return mixer_schedule[mixer_name][sidx]

    def mark_cleaning(mixer_name, sidx):
        state = get_shift_state(mixer_name, sidx)
        if state.get("cleaning", False):
            return False
        state["cleaning"]     = True
        state["batches_used"] = get_batch_per_shift(mixer_name)
        return True

    def book_batches(mixer_name, sidx, n_batches, grup, kode, nama,
                     kg_per_batch, total_kg, total_cs):
        state = get_shift_state(mixer_name, sidx)
        state["batches_used"] += n_batches
        state["grup"]          = grup
        state["items"].append({
            "kode": kode, "nama": nama,
            "batches": n_batches,
            "kg_per_batch": kg_per_batch,
            "total_kg": total_kg,
            "total_cs": total_cs
        })
        mixer_last_grup[mixer_name] = grup

    # ── Batas index dari date_range ───────────────────────────
    range_earliest_idx = None
    range_latest_idx   = None
    if date_range:
        range_earliest_idx = shift_index(date_range[0], 1)
        range_latest_idx   = shift_index(date_range[-1], SHIFTS_PER_DAY)

    # ── Merge MC liquid info ke plan ──────────────────────────
    if "Kode_MC_Liquid" in produk_df.columns:
        mc_map = produk_df.set_index("_kode_str")["Kode_MC_Liquid"].to_dict()
    else:
        mc_map = {}

    plan_df["_kode_str"]     = plan_df["Kode_Produk"].astype(str).str.strip()
    plan_df["Kode_MC_Liquid"] = plan_df["_kode_str"].map(mc_map).fillna(
        plan_df["_kode_str"]
    )

    # ── Lookup nama produk dari master ────────────────────────
    nama_map = produk_df.set_index("_kode_str")["Nama_Produk"].to_dict()

    # ── Group by MC liquid + filling slot + urgent ────────────
    group_cols   = ["Kode_MC_Liquid", "Tanggal_Filling", "Shift_Filling", "Urgent"]
    grouped_rows = []

    for group_key, grp in plan_df.groupby(group_cols, sort=False):
        mc_liquid, fill_date, fill_shift, urgent = group_key
        total_cs   = grp["Target_CS"].astype(float).sum()
        kode_list  = list(grp["_kode_str"].unique())
        first_kode = kode_list[0]

        all_mixers = []
        for kd in kode_list:
            pr = produk_df[produk_df["_kode_str"] == kd]
            if not pr.empty:
                for m in [x.strip() for x in str(pr["Mixer_Kompatibel"].values[0]).split(",")]:
                    if m not in all_mixers:
                        all_mixers.append(m)

        grouped_rows.append({
            "Kode_Produk":          first_kode,
            "Kode_MC_Liquid":       mc_liquid,
            "Kode_List":            kode_list,
            "Nama_Produk":          nama_map.get(first_kode, first_kode),  # FIX
            "Target_CS":            total_cs,
            "Tanggal_Filling":      fill_date,
            "Shift_Filling":        fill_shift,
            "Urgent":               urgent,
            "Mixer_Kompatibel_All": ",".join(all_mixers)
        })

    plan_grouped = pd.DataFrame(grouped_rows)

    # ── Merge job yang boleh digabung (same MC liquid + urgent) ──
    merge_cols  = ["Kode_MC_Liquid", "Urgent"]
    merged_jobs = []

    for merge_key, grp in plan_grouped.groupby(merge_cols, sort=False):
        mc_liquid, urgent = merge_key
        total_cs          = grp["Target_CS"].sum()

        sidx_series = grp.apply(
            lambda r: shift_index(r["Tanggal_Filling"], r["Shift_Filling"]), axis=1)
        min_idx     = sidx_series.idxmin()

        earliest_fill_date  = grp.loc[min_idx, "Tanggal_Filling"]
        earliest_fill_shift = grp.loc[min_idx, "Shift_Filling"]
        first_row           = grp.iloc[0]
        kode                = first_row["Kode_Produk"]

        merged_jobs.append({
            "Kode_Produk":          kode,
            "Kode_MC_Liquid":       mc_liquid,
            "Nama_Produk":          nama_map.get(kode, kode),  # FIX
            "Target_CS":            total_cs,
            "Tanggal_Filling":      earliest_fill_date,
            "Shift_Filling":        earliest_fill_shift,
            "Urgent":               urgent,
            "Mixer_Kompatibel_All": first_row["Mixer_Kompatibel_All"]
        })

    plan_merged = pd.DataFrame(merged_jobs)

    plan_merged["_sidx"] = plan_merged.apply(
        lambda r: shift_index(r["Tanggal_Filling"], r["Shift_Filling"]), axis=1)
    plan_merged["_urgent_sort"] = plan_merged["Urgent"].apply(
        lambda x: 0 if x == "Urgent" else 1)
    plan_merged = plan_merged.sort_values(["_urgent_sort", "_sidx"]).reset_index(drop=True)

    # ── Schedule each job ─────────────────────────────────────
    for _, item in plan_merged.iterrows():
        kode       = str(item["Kode_Produk"]).strip()
        mc_liquid  = str(item["Kode_MC_Liquid"]).strip()
        fill_date  = str(item["Tanggal_Filling"])
        fill_shift = int(item["Shift_Filling"])
        is_urgent  = item["Urgent"] == "Urgent"
        target_cs  = float(item["Target_CS"])

        prod_row = produk_df[produk_df["_kode_str"] == kode]
        if prod_row.empty:
            unscheduled.append(
                f"Produk {kode} tidak ditemukan di Master Produk.")
            continue

        # FIX: Ambil nama dan atribut dari master produk
        nama          = prod_row["Nama_Produk"].values[0]
        kg_per_cs     = float(prod_row["Kg_per_CS"].values[0])
        target_kg_raw = target_cs * kg_per_cs
        grup_produk   = prod_row["Grup_Cleaning"].values[0]
        resting_days  = int(prod_row["Resting_Days"].values[0])

        if "Mixer_Kompatibel_All" in item and pd.notna(item["Mixer_Kompatibel_All"]):
            mixer_compat = [m.strip() for m in str(item["Mixer_Kompatibel_All"]).split(",")]
        else:
            mixer_compat = prod_row["Mixer_List"].values[0]

        min_cap = min(
            (get_mixer_capacity(m) for m in mixer_compat if m in mixer_schedule),
            default=500
        )
        if min_cap <= 0:
            min_cap = 500
        target_kg = math.ceil(target_kg_raw / min_cap) * min_cap
        if target_kg == 0:
            target_kg = min_cap

        job_deadline = get_deadline_idx(fill_date, fill_shift,
                                        resting_days, min_lead_shifts)
        job_earliest = get_earliest_idx(fill_date, fill_shift, max_shelf_days)

        if range_earliest_idx is not None:
            job_earliest = max(job_earliest, range_earliest_idx)
        if range_latest_idx is not None:
            job_deadline = min(job_deadline, range_latest_idx)

        if job_deadline < job_earliest:
            unscheduled.append(
                f"{kode} - {nama}: Window mixing tidak valid. "
                f"Cek resting_days atau perluas date_range."
            )
            continue

        candidate_slots = [(fill_date, fill_shift)]
        if not is_urgent:
            d = datetime.strptime(fill_date, "%Y-%m-%d")
            for delta in range(0, 7):
                nd     = d + timedelta(days=delta)
                nd_str = nd.strftime("%Y-%m-%d")
                if not same_week(fill_date, nd_str):
                    break
                start_s = fill_shift + 1 if delta == 0 else 1
                for s in range(start_s, SHIFTS_PER_DAY + 1):
                    candidate_slots.append((nd_str, s))

        scheduled = False

        for try_fill_date, try_fill_shift in candidate_slots:
            try_deadline = get_deadline_idx(try_fill_date, try_fill_shift,
                                            resting_days, min_lead_shifts)
            try_earliest = get_earliest_idx(try_fill_date, try_fill_shift, max_shelf_days)

            if range_earliest_idx is not None:
                try_earliest = max(try_earliest, range_earliest_idx)
            if range_latest_idx is not None:
                try_deadline = min(try_deadline, range_latest_idx)

            if try_deadline < try_earliest:
                continue

            best_assignments = None
            chosen_mixer     = None

            for mixer_name in mixer_compat:
                if mixer_name not in mixer_schedule:
                    continue
                cap             = get_mixer_capacity(mixer_name)
                batch_per_shift = get_batch_per_shift(mixer_name)
                if cap <= 0:
                    continue

                assignments = try_schedule_on_mixer(
                    mixer_name, mixer_schedule,
                    try_deadline, try_earliest,
                    target_kg, cap, batch_per_shift, grup_produk
                )

                if assignments is not None:
                    if best_assignments is None or \
                       len(assignments) < len(best_assignments) or \
                       (len(assignments) == len(best_assignments) and
                            assignments[-1]["shift_idx"] > best_assignments[-1]["shift_idx"]):
                        best_assignments = assignments
                        chosen_mixer     = mixer_name

            if best_assignments is None:
                continue

            # ── Commit ───────────────────────────────────────
            for a in best_assignments:
                mixer_name = chosen_mixer
                sidx       = a["shift_idx"]

                current_last_grup = mixer_last_grup[mixer_name]
                if current_last_grup is not None and current_last_grup != grup_produk:
                    clean_idx    = sidx - 1
                    newly_marked = mark_cleaning(mixer_name, clean_idx)
                    if newly_marked:
                        cd, cs_shift = index_to_shift(clean_idx)
                        schedule_rows.append({
                            "Tanggal":         cd,
                            "Shift":           cs_shift,
                            "Mixer":           mixer_name,
                            "Produk":          "— CLEANING —",
                            "Kode_Produk":     "",
                            "Nama_Produk":     "",
                            "Batches":         "-",
                            "Kapasitas_Mixer": get_mixer_capacity(mixer_name),
                            "Total_CS":        0,
                            "Total_kg":        0,
                            "Cleaning":        True,
                            "Resting_Days":    0
                        })

                actual_cs = round(a["kg"] / kg_per_cs, 2)
                book_batches(mixer_name, sidx, a["batches"], grup_produk,
                             kode, nama, a["kg_per_batch"], a["kg"], actual_cs)

                s_date, s_shift = a["date"], a["shift"]
                # FIX: Kode_Produk dan Produk diisi dari master, bukan mc_liquid
                schedule_rows.append({
                    "Tanggal":         s_date,
                    "Shift":           s_shift,
                    "Mixer":           mixer_name,
                    "Produk":          nama,       # FIX: nama asli dari master
                    "Kode_Produk":     kode,       # FIX: kode asli dari master
                    "Nama_Produk":     nama,
                    "Batches":         a["batches"],
                    "Kapasitas_Mixer": a["kg_per_batch"],
                    "Total_CS":        actual_cs,
                    "Total_kg":        round(a["kg"], 2),
                    "Cleaning":        False,
                    "Resting_Days":    resting_days
                })

            if try_fill_date != fill_date or try_fill_shift != fill_shift:
                shifted.append({
                    "Kode_Produk":  kode,
                    "Nama_Produk":  nama,
                    "Target_CS":    target_cs,
                    "Filling_Asal": f"{fill_date} Shift {fill_shift}",
                    "Filling_Baru": f"{try_fill_date} Shift {try_fill_shift}",
                    "Alasan":       "Kapasitas mixer penuh"
                })

            scheduled = True
            break

        if not scheduled:
            unscheduled.append(
                f"{kode} - {nama}: Tidak bisa dijadwalkan "
                f"(target {target_cs} CS / {target_kg} kg, "
                f"filling {fill_date} Shift {fill_shift}, "
                f"window {max_shelf_days} hari)"
            )

    if schedule_rows:
        schedule_df = pd.DataFrame(schedule_rows)
        schedule_df = schedule_df.sort_values(
            ["Tanggal", "Shift", "Mixer"]).reset_index(drop=True)
        schedule_df = schedule_df[[
            "Tanggal", "Shift", "Mixer", "Produk", "Kode_Produk", "Nama_Produk",
            "Batches", "Kapasitas_Mixer", "Total_CS", "Total_kg",
            "Resting_Days", "Cleaning"
        ]]
    else:
        schedule_df = pd.DataFrame()

    return {
        "schedule":    schedule_df,
        "warnings":    warnings,
        "shifted":     shifted,
        "unscheduled": unscheduled
    }
