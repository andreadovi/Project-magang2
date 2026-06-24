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
    return (d1.isocalendar()[1] == d2.isocalendar()[1]
            and d1.year == d2.year)


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


def try_schedule_on_mixer(mixer_name, mixer_schedule, deadline_idx,
                           earliest_idx, target_kg, cap, batch_per_shift,
                           grup_produk):
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
        last_grup = (mixer_schedule[mixer_name][used_before[0]]["grup"]
                     if used_before else None)

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
    job_counter   = [0]

    def next_job_id():
        job_counter[0] += 1
        return job_counter[0]

    mixer_df  = master_mixer.copy()
    produk_df = master_produk.copy()
    plan_df   = filling_plan.copy().reset_index(drop=True)

    mixer_df["Mixer"] = mixer_df["Mixer"].astype(str).str.strip()

    if "Resting_Days" not in produk_df.columns:
        produk_df["Resting_Days"] = 0
    produk_df["Resting_Days"] = produk_df["Resting_Days"].fillna(0).astype(int)
    produk_df["_kode_str"]    = produk_df["Kode_Produk"].astype(str).str.strip()

    nama_map = produk_df.set_index("_kode_str")["Nama_Produk"].to_dict()
    mc_map   = (produk_df.set_index("_kode_str")["Kode_MC_Liquid"].to_dict()
                if "Kode_MC_Liquid" in produk_df.columns else {})

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

    def commit_assignments(best_a, best_mx, kode, nama, grup_produk,
                           kg_per_cs, resting_days, job_id,
                           fill_date, fill_shift,
                           try_fd, try_fs, target_cs, reason=""):
        for a in best_a:
            mx   = best_mx
            sidx = a["shift_idx"]
            cur_last = mixer_last_grup[mx]
            if cur_last is not None and cur_last != grup_produk:
                clean_idx    = sidx - 1
                newly_marked = mark_cleaning(mx, clean_idx)
                if newly_marked:
                    cd, cs_s = index_to_shift(clean_idx)
                    schedule_rows.append({
                        "Job_ID":          0,
                        "Tanggal":         cd,
                        "Shift":           cs_s,
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
            schedule_rows.append({
                "Job_ID":          job_id,
                "Tanggal":         a["date"],
                "Shift":           a["shift"],
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
        if try_fd != fill_date or try_fs != fill_shift:
            shifted.append({
                "Kode_Produk":  kode,
                "Nama_Produk":  nama,
                "Target_CS":    target_cs,
                "Filling_Asal": f"{fill_date} Shift {fill_shift}",
                "Filling_Baru": f"{try_fd} Shift {try_fs}",
                "Alasan":       reason or "Kapasitas mixer penuh"
            })

    def find_best_mixer(mixer_compat, try_dl, try_el,
                        target_kg, grup_produk):
        best_a  = None
        best_mx = None
        for mx in mixer_compat:
            if mx not in mixer_schedule:
                continue
            cap = get_mixer_capacity(mx)
            bps = get_batch_per_shift(mx)
            if cap <= 0:
                continue
            a = try_schedule_on_mixer(
                mx, mixer_schedule,
                try_dl, try_el,
                target_kg, cap, bps, grup_produk)
            if a is not None:
                if (best_a is None
                        or len(a) < len(best_a)
                        or (len(a) == len(best_a)
                            and a[-1]["shift_idx"] > best_a[-1]["shift_idx"])):
                    best_a  = a
                    best_mx = mx
        return best_a, best_mx

    def try_all_candidates(kode, nama, fill_date, fill_shift, is_urgent,
                           target_kg, grup_produk, resting_days,
                           mixer_compat, kg_per_cs, target_cs, job_id,
                           reason=""):
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
            try_dl = get_deadline_idx(try_fd, try_fs, resting_days,
                                      min_lead_shifts)
            try_el = get_earliest_idx(try_fd, try_fs, max_shelf_days)
            if range_earliest_idx is not None:
                try_el = max(try_el, range_earliest_idx)
            if range_latest_idx is not None:
                try_dl = min(try_dl, range_latest_idx)
            if try_dl < try_el:
                continue

            best_a, best_mx = find_best_mixer(
                mixer_compat, try_dl, try_el, target_kg, grup_produk)
            if best_a is None:
                continue

            commit_assignments(
                best_a, best_mx, kode, nama, grup_produk,
                kg_per_cs, resting_days, job_id,
                fill_date, fill_shift, try_fd, try_fs,
                target_cs, reason)
            return True

        return False

    # ── Batas index dari date_range ─────────────────────────────────────────
    range_earliest_idx = None
    range_latest_idx   = None
    if date_range:
        range_earliest_idx = shift_index(date_range[0], 1)
        range_latest_idx   = shift_index(date_range[-1], SHIFTS_PER_DAY)

    # ── Normalize plan_df ───────────────────────────────────────────────────
    plan_df["_kode_str"]       = plan_df["Kode_Produk"].astype(str).str.strip()
    plan_df["Kode_MC_Liquid"]  = plan_df["_kode_str"].map(mc_map).fillna(
        plan_df["_kode_str"])
    plan_df["_sidx"]           = plan_df.apply(
        lambda r: shift_index(r["Tanggal_Filling"], r["Shift_Filling"]), axis=1)
    plan_df["_urgent_sort"]    = plan_df["Urgent"].apply(
        lambda x: 0 if x == "Urgent" else 1)
    plan_df = plan_df.sort_values(
        ["_urgent_sort", "_sidx"]).reset_index(drop=True)

    # ── Build job list ──────────────────────────────────────────────────────
    # Grup C: kode + mc_liquid + tanggal_filling sama → coba gabung
    # Beda shift dalam 1 hari = 1 job, deadline per shift disimpan terpisah
    seen_keys = {}
    for idx, row in plan_df.iterrows():
        kode      = str(row["_kode_str"]).strip()
        mc_liquid = str(row["Kode_MC_Liquid"]).strip()
        tanggal   = str(row["Tanggal_Filling"])
        key       = (kode, mc_liquid, tanggal)
        seen_keys.setdefault(key, []).append(idx)

    job_list = []
    for key, indices in seen_keys.items():
        kode, mc_liquid, tanggal = key

        rows_in_group = plan_df.loc[indices]
        total_cs      = rows_in_group["Target_CS"].astype(float).sum()
        is_urgent     = (rows_in_group["Urgent"] == "Urgent").any()

        # Sub-deadlines: per shift, sorted paling awal dulu
        sub_deadlines = sorted([
            (str(r["Tanggal_Filling"]), int(r["Shift_Filling"]),
             float(r["Target_CS"]))
            for _, r in rows_in_group.iterrows()
        ], key=lambda x: shift_index(x[0], x[1]))

        # Deadline paling ketat = shift paling awal
        earliest_fill_date  = sub_deadlines[0][0]
        earliest_fill_shift = sub_deadlines[0][1]

        prod_row   = produk_df[produk_df["_kode_str"] == kode]
        all_mixers = []
        if not prod_row.empty:
            for m in [x.strip() for x in
                      str(prod_row["Mixer_Kompatibel"].values[0]).split(",")]:
                if m not in all_mixers:
                    all_mixers.append(m)

        job_list.append({
            "Kode_Produk":         kode,
            "Kode_MC_Liquid":      mc_liquid,
            "Nama_Produk":         nama_map.get(kode, kode),
            "Target_CS":           total_cs,
            "Tanggal_Filling":     earliest_fill_date,
            "Shift_Filling":       earliest_fill_shift,
            "Urgent":              "Urgent" if is_urgent else "Tidak Urgent",
            "Mixer_Kompatibel_All": ",".join(all_mixers),
            "Row_Indices":         indices,
            "Sub_Deadlines":       sub_deadlines,  # [(date, shift, cs), ...]
        })

    # Sort: urgent first, deadline paling awal
    job_list.sort(key=lambda j: (
        0 if j["Urgent"] == "Urgent" else 1,
        shift_index(j["Tanggal_Filling"], j["Shift_Filling"])
    ))

    # ── Schedule each job ───────────────────────────────────────────────────
    for job in job_list:
        kode          = str(job["Kode_Produk"]).strip()
        fill_date     = str(job["Tanggal_Filling"])
        fill_shift    = int(job["Shift_Filling"])
        is_urgent     = job["Urgent"] == "Urgent"
        total_cs      = float(job["Target_CS"])
        sub_deadlines = job["Sub_Deadlines"]  # [(date, shift, cs), ...]

        prod_row = produk_df[produk_df["_kode_str"] == kode]
        if prod_row.empty:
            unscheduled.append(
                f"Produk {kode} tidak ditemukan di Master Produk.")
            continue

        nama         = prod_row["Nama_Produk"].values[0]
        kg_per_cs    = float(prod_row["Kg_per_CS"].values[0])
        grup_produk  = prod_row["Grup_Cleaning"].values[0]
        resting_days = int(prod_row["Resting_Days"].values[0])
        mixer_compat = [m.strip() for m in
                        str(job["Mixer_Kompatibel_All"]).split(",")]

        min_cap = min(
            (get_mixer_capacity(m)
             for m in mixer_compat if m in mixer_schedule),
            default=500)
        if min_cap <= 0:
            min_cap = 500

        # ── Tahap 1: Coba gabung semua CS sebelum deadline shift paling awal
        total_kg = math.ceil(total_cs * kg_per_cs / min_cap) * min_cap
        if total_kg == 0:
            total_kg = min_cap

        jid       = next_job_id()
        scheduled = try_all_candidates(
            kode, nama, fill_date, fill_shift, is_urgent,
            total_kg, grup_produk, resting_days, mixer_compat,
            kg_per_cs, total_cs, jid)

        if scheduled:
            continue

        # ── Tahap 2: Tidak bisa gabung semua → schedule per sub-deadline
        # Setiap sub-deadline = 1 job terpisah dengan deadline shift-nya sendiri
        all_sub_scheduled = True
        for sub_fill_date, sub_fill_shift, sub_cs in sub_deadlines:
            sub_kg = math.ceil(sub_cs * kg_per_cs / min_cap) * min_cap
            if sub_kg == 0:
                sub_kg = min_cap

            sub_jid       = next_job_id()
            sub_scheduled = try_all_candidates(
                kode, nama,
                sub_fill_date, sub_fill_shift,
                is_urgent,
                sub_kg, grup_produk, resting_days, mixer_compat,
                kg_per_cs, sub_cs, sub_jid,
                reason="Tidak muat digabung — dijadwal per shift filling")

            if not sub_scheduled:
                all_sub_scheduled = False
                unscheduled.append(
                    f"{kode} - {nama}: Tidak bisa dijadwalkan "
                    f"(target {sub_cs} CS, "
                    f"filling {sub_fill_date} Shift {sub_fill_shift})")

        # ── Tahap 3: Kalau masih ada yang tidak terjadwal,
        #            coba lagi dengan window lebih longgar (geser 1 shift)
        if not all_sub_scheduled:
            warnings.append(
                f"⚠️ {kode} - {nama}: Sebagian sub-job tidak terjadwal. "
                f"Pertimbangkan memperluas date_range atau mengurangi target CS.")

    # ── Build schedule_df ───────────────────────────────────────────────────
    if schedule_rows:
        schedule_df = pd.DataFrame(schedule_rows)
        schedule_df = schedule_df.sort_values(
            ["Tanggal", "Shift", "Mixer"]).reset_index(drop=True)
        schedule_df = schedule_df[[
            "Job_ID", "Tanggal", "Shift", "Mixer",
            "Produk", "Kode_Produk", "Nama_Produk",
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
