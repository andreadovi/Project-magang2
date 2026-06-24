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
    job_counter   = [0]  # mutable counter untuk Job_ID

    def next_job_id():
        job_counter[0] += 1
        return job_counter[0]

    mixer_df  = master_mixer.copy()
    produk_df = master_produk.copy()
    plan_df   = filling_plan.copy().reset_index(drop=True)

    mixer_df["Mixer"] = mixer_df["Mixer"].astype(str).str.strip()

    produk_df["Mixer_List"] = produk_df["Mixer_Kompatibel"].apply(
        lambda x: [m.strip() for m in str(x).split(",")]
    )
    if "Resting_Days" not in produk_df.columns:
        produk_df["Resting_Days"] = 0
    produk_df["Resting_Days"] = produk_df["Resting_Days"].fillna(0).astype(int)
    produk_df["_kode_str"]    = produk_df["Kode_Produk"].astype(str).str.strip()

    nama_map = produk_df.set_index("_kode_str")["Nama_Produk"].to_dict()
    if "Kode_MC_Liquid" in produk_df.columns:
        mc_map = produk_df.set_index("_kode_str")["Kode_MC_Liquid"].to_dict()
    else:
        mc_map = {}

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

    def commit_assignments(best_assignments, chosen_mixer, kode, nama,
                           grup_produk, kg_per_cs, resting_days, job_id,
                           fill_date, fill_shift, try_fill_date, try_fill_shift,
                           target_cs):
        """Helper: commit assignments ke schedule_rows dan mixer state."""
        for a in best_assignments:
            mx   = chosen_mixer
            sidx = a["shift_idx"]

            cur_last = mixer_last_grup[mx]
            if cur_last is not None and cur_last != grup_produk:
                clean_idx    = sidx - 1
                newly_marked = mark_cleaning(mx, clean_idx)
                if newly_marked:
                    cd, cs_shift = index_to_shift(clean_idx)
                    schedule_rows.append({
                        "Job_ID":          0,
                        "Tanggal":         cd,
                        "Shift":           cs_shift,
                        "Mixer":           mx,
                        "Produk":          "— CLEANING —",
                        "Kode_Produk":     "",
                        "Nama_Produk":     "",
                        "Batches":         "-",
                        "Kapasitas_Mixer": get_mixer_capacity(mx),
                        "Total_CS":        0,
                        "Total_kg":        0,
                        "Cleaning":        True,
                        "Resting_Days":    0
                    })

            actual_cs = round(a["kg"] / kg_per_cs, 2)
            book_batches(mx, sidx, a["batches"], grup_produk,
                         kode, nama, a["kg_per_batch"], a["kg"], actual_cs)

            s_date, s_shift = a["date"], a["shift"]
            schedule_rows.append({
                "Job_ID":          job_id,   # FIX: unik per job
                "Tanggal":         s_date,
                "Shift":           s_shift,
                "Mixer":           mx,
                "Produk":          nama,
                "Kode_Produk":     kode,
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

    def try_all_candidates(kode, nama, fill_date, fill_shift, is_urgent,
                           target_kg, grup_produk, resting_days, mixer_compat,
                           kg_per_cs, target_cs, job_id):
        """Coba semua candidate filling slots, return True jika berhasil."""
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

        for try_fd, try_fs in candidate_slots:
            try_dl = get_deadline_idx(try_fd, try_fs, resting_days, min_lead_shifts)
            try_el = get_earliest_idx(try_fd, try_fs, max_shelf_days)

            if range_earliest_idx is not None:
                try_el = max(try_el, range_earliest_idx)
            if range_latest_idx is not None:
                try_dl = min(try_dl, range_latest_idx)

            if try_dl < try_el:
                continue

            best_a  = None
            best_mx = None

            for mixer_name in mixer_compat:
                if mixer_name not in mixer_schedule:
                    continue
                cap = get_mixer_capacity(mixer_name)
                bps = get_batch_per_shift(mixer_name)
                if cap <= 0:
                    continue

                a = try_schedule_on_mixer(
                    mixer_name, mixer_schedule,
                    try_dl, try_el,
                    target_kg, cap, bps, grup_produk
                )
                if a is not None:
                    if best_a is None or \
                       len(a) < len(best_a) or \
                       (len(a) == len(best_a) and
                            a[-1]["shift_idx"] > best_a[-1]["shift_idx"]):
                        best_a  = a
                        best_mx = mixer_name

            if best_a is None:
                continue

            commit_assignments(best_a, best_mx, kode, nama, grup_produk,
                               kg_per_cs, resting_days, job_id,
                               fill_date, fill_shift, try_fd, try_fs, target_cs)
            return True

        return False

    # ── Batas index dari date_range ───────────────────────────
    range_earliest_idx = None
    range_latest_idx   = None
    if date_range:
        range_earliest_idx = shift_index(date_range[0], 1)
        range_latest_idx   = shift_index(date_range[-1], SHIFTS_PER_DAY)

    # ── Normalize plan_df ─────────────────────────────────────
    plan_df["_kode_str"]      = plan_df["Kode_Produk"].astype(str).str.strip()
    plan_df["Kode_MC_Liquid"] = plan_df["_kode_str"].map(mc_map).fillna(plan_df["_kode_str"])
    plan_df["_sidx"]          = plan_df.apply(
        lambda r: shift_index(r["Tanggal_Filling"], r["Shift_Filling"]), axis=1)
    plan_df["_urgent_sort"]   = plan_df["Urgent"].apply(
        lambda x: 0 if x == "Urgent" else 1)
    plan_df = plan_df.sort_values(["_urgent_sort", "_sidx"]).reset_index(drop=True)

    # ── Build job list — coba gabung per MC liquid + slot + urgent ──
    job_key_cols = ["Kode_MC_Liquid", "Tanggal_Filling", "Shift_Filling", "Urgent"]
    seen_keys    = {}
    for idx, row in plan_df.iterrows():
        key = (str(row["Kode_MC_Liquid"]).strip(),
               str(row["Tanggal_Filling"]),
               int(row["Shift_Filling"]),
               row["Urgent"])
        seen_keys.setdefault(key, []).append(idx)

    job_list = []
    for key, indices in seen_keys.items():
        mc_liquid, fill_date, fill_shift, urgent = key
        fill_shift  = int(fill_shift)
        total_cs    = plan_df.loc[indices, "Target_CS"].astype(float).sum()
        kode_list   = list(plan_df.loc[indices, "_kode_str"].unique())
        first_kode  = next(
            (k for k in kode_list if not produk_df[produk_df["_kode_str"] == k].empty),
            kode_list[0]
        )
        all_mixers = []
        for kd in kode_list:
            pr = produk_df[produk_df["_kode_str"] == kd]
            if not pr.empty:
                for m in [x.strip() for x in str(pr["Mixer_Kompatibel"].values[0]).split(",")]:
                    if m not in all_mixers:
                        all_mixers.append(m)

        job_list.append({
            "Kode_Produk":          first_kode,
            "Kode_MC_Liquid":       mc_liquid,
            "Kode_List":            kode_list,
            "Nama_Produk":          nama_map.get(first_kode, first_kode),
            "Target_CS":            total_cs,
            "Tanggal_Filling":      fill_date,
            "Shift_Filling":        fill_shift,
            "Urgent":               urgent,
            "Mixer_Kompatibel_All": ",".join(all_mixers),
            "Row_Indices":          indices,
        })

    job_list.sort(key=lambda j: (
        0 if j["Urgent"] == "Urgent" else 1,
        shift_index(j["Tanggal_Filling"], j["Shift_Filling"])
    ))

    # ── Schedule each job ─────────────────────────────────────
    for job in job_list:
        kode       = str(job["Kode_Produk"]).strip()
        fill_date  = str(job["Tanggal_Filling"])
        fill_shift = int(job["Shift_Filling"])
        is_urgent  = job["Urgent"] == "Urgent"
        target_cs  = float(job["Target_CS"])

        prod_row = produk_df[produk_df["_kode_str"] == kode]
        if prod_row.empty:
            unscheduled.append(f"Produk {kode} tidak ditemukan di Master Produk.")
            continue

        nama          = prod_row["Nama_Produk"].values[0]
        kg_per_cs     = float(prod_row["Kg_per_CS"].values[0])
        target_kg_raw = target_cs * kg_per_cs
        grup_produk   = prod_row["Grup_Cleaning"].values[0]
        resting_days  = int(prod_row["Resting_Days"].values[0])
        mixer_compat  = [m.strip() for m in str(job["Mixer_Kompatibel_All"]).split(",")]

        min_cap = min(
            (get_mixer_capacity(m) for m in mixer_compat if m in mixer_schedule),
            default=500
        )
        if min_cap <= 0:
            min_cap = 500
        target_kg = math.ceil(target_kg_raw / min_cap) * min_cap
        if target_kg == 0:
            target_kg = min_cap

        job_deadline = get_deadline_idx(fill_date, fill_shift, resting_days, min_lead_shifts)
        job_earliest = get_earliest_idx(fill_date, fill_shift, max_shelf_days)
        if range_earliest_idx is not None:
            job_earliest = max(job_earliest, range_earliest_idx)
        if range_latest_idx is not None:
            job_deadline = min(job_deadline, range_latest_idx)

        if job_deadline < job_earliest:
            unscheduled.append(
                f"{kode} - {nama}: Window mixing tidak valid. "
                f"Cek resting_days atau perluas date_range.")
            continue

        # Coba jadwalkan sebagai 1 job gabungan
        jid       = next_job_id()
        scheduled = try_all_candidates(
            kode, nama, fill_date, fill_shift, is_urgent,
            target_kg, grup_produk, resting_days, mixer_compat,
            kg_per_cs, target_cs, jid
        )

        # Kalau tidak muat gabung dan ada > 1 baris, split per baris
        if not scheduled and len(job["Row_Indices"]) > 1:
            for row_idx in job["Row_Indices"]:
                row            = plan_df.loc[row_idx]
                sub_kode       = str(row["_kode_str"]).strip()
                sub_cs         = float(row["Target_CS"])
                sub_fill_date  = str(row["Tanggal_Filling"])
                sub_fill_shift = int(row["Shift_Filling"])
                sub_urgent     = row["Urgent"] == "Urgent"

                sub_prod = produk_df[produk_df["_kode_str"] == sub_kode]
                if sub_prod.empty:
                    unscheduled.append(f"Produk {sub_kode} tidak ditemukan di Master Produk.")
                    continue

                sub_nama      = sub_prod["Nama_Produk"].values[0]
                sub_kg_per_cs = float(sub_prod["Kg_per_CS"].values[0])
                sub_grup      = sub_prod["Grup_Cleaning"].values[0]
                sub_resting   = int(sub_prod["Resting_Days"].values[0])
                sub_mixers    = [m.strip() for m in
                                 str(sub_prod["Mixer_Kompatibel"].values[0]).split(",")]

                sub_min_cap = min(
                    (get_mixer_capacity(m) for m in sub_mixers if m in mixer_schedule),
                    default=500
                )
                if sub_min_cap <= 0:
                    sub_min_cap = 500
                sub_target_kg = math.ceil(sub_cs * sub_kg_per_cs / sub_min_cap) * sub_min_cap
                if sub_target_kg == 0:
                    sub_target_kg = sub_min_cap

                sub_jid       = next_job_id()
                sub_scheduled = try_all_candidates(
                    sub_kode, sub_nama, sub_fill_date, sub_fill_shift, sub_urgent,
                    sub_target_kg, sub_grup, sub_resting, sub_mixers,
                    sub_kg_per_cs, sub_cs, sub_jid
                )

                if not sub_scheduled:
                    unscheduled.append(
                        f"{sub_kode} - {sub_nama}: Tidak bisa dijadwalkan "
                        f"(split job, target {sub_cs} CS, "
                        f"filling {sub_fill_date} Shift {sub_fill_shift})"
                    )

        elif not scheduled:
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
            "Job_ID", "Tanggal", "Shift", "Mixer", "Produk", "Kode_Produk",
            "Nama_Produk", "Batches", "Kapasitas_Mixer", "Total_CS", "Total_kg",
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
