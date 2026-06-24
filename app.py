# app.py
import streamlit as st
import pandas as pd
import io
from datetime import timedelta

from scheduler import generate_mixing_schedule
from pivot import build_pivot, pivot_to_excel

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Mixing Scheduler", layout="wide")
st.title("🧪 Mixing Scheduler")

# ─── Session state defaults ───────────────────────────────────────────────────
for key in ["master_mixer", "master_produk", "filling_plan", "schedule_result"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Upload & Master Data
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Data")

    # ── Master Mixer ─────────────────────────────────────────────────────────
    st.subheader("1. Master Mixer")
    f_mixer = st.file_uploader("Upload Master Mixer (.xlsx)", type=["xlsx"], key="up_mixer")
    if f_mixer:
        try:
            df = pd.read_excel(f_mixer)
            st.session_state.master_mixer = df
            st.success(f"✅ {len(df)} mixer dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    # ── Master Produk ─────────────────────────────────────────────────────────
    st.subheader("2. Master Produk")
    f_produk = st.file_uploader("Upload Master Produk (.xlsx)", type=["xlsx"], key="up_produk")
    if f_produk:
        try:
            df = pd.read_excel(f_produk)
            st.session_state.master_produk = df
            st.success(f"✅ {len(df)} produk dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    # ── Filling Plan ──────────────────────────────────────────────────────────
    st.subheader("3. Filling Plan")
    f_filling = st.file_uploader("Upload Filling Plan (.xlsx)", type=["xlsx"], key="up_filling")
    if f_filling:
        try:
            df = pd.read_excel(f_filling)
            st.session_state.filling_plan = df
            st.success(f"✅ {len(df)} item filling dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    st.divider()

    # ── Tombol Generate ───────────────────────────────────────────────────────
    ready = all([
        st.session_state.master_mixer is not None,
        st.session_state.master_produk is not None,
        st.session_state.filling_plan is not None,
    ])

    if st.button("⚡ Generate Jadwal Mixing", disabled=not ready, use_container_width=True):
        # Reset hasil sebelumnya
        st.session_state.schedule_result = None

        with st.spinner("Menjadwalkan mixing..."):
            try:
                result = generate_mixing_schedule(
                    st.session_state.master_mixer,
                    st.session_state.master_produk,
                    st.session_state.filling_plan,
                )
                st.session_state.schedule_result = result
                st.success("✅ Jadwal berhasil dibuat!")
            except Exception as e:
                st.error(f"Error saat generate: {e}")
                st.exception(e)

    if not ready:
        st.info("Upload ketiga file untuk mengaktifkan Generate.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN — Tampilkan Hasil
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.schedule_result is None:
    st.info("👈 Upload data dan klik **Generate Jadwal Mixing** untuk memulai.")
    st.stop()

result      = st.session_state.schedule_result
schedule_df = result["schedule"]
warnings    = result["warnings"]
shifted     = result["shifted"]
unscheduled = result["unscheduled"]

# ─── Ringkasan ────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jadwal Mixing", len(schedule_df))
col2.metric("Produk Unik", schedule_df["Kode_Produk"].nunique() if not schedule_df.empty else 0)
col3.metric("Peringatan", len(warnings))
col4.metric("Tidak Terjadwal", len(unscheduled))

st.divider()

# ─── Warnings ────────────────────────────────────────────────────────────────
if warnings:
    with st.expander(f"⚠️ Peringatan ({len(warnings)})", expanded=True):
        for w in warnings:
            st.warning(w)

if unscheduled:
    with st.expander(f"❌ Tidak Terjadwal ({len(unscheduled)})", expanded=True):
        for u in unscheduled:
            st.error(u)

if shifted:
    with st.expander(f"📅 Filling Digeser ({len(shifted)})", expanded=False):
        st.dataframe(pd.DataFrame(shifted), use_container_width=True)

# ─── Tabel Jadwal Mentah ──────────────────────────────────────────────────────
st.subheader("📋 Jadwal Mixing Detail")
if schedule_df.empty:
    st.warning("Tidak ada jadwal yang berhasil dibuat.")
else:
    st.dataframe(schedule_df, use_container_width=True, height=400)

    # Download CSV
    csv_buf = io.StringIO()
    schedule_df.to_csv(csv_buf, index=False)
    st.download_button(
        label="⬇️ Download Jadwal (CSV)",
        data=csv_buf.getvalue().encode("utf-8"),
        file_name="jadwal_mixing.csv",
        mime="text/csv",
    )

st.divider()

# ─── Pivot / Gantt View ───────────────────────────────────────────────────────
st.subheader("📅 Pivot Jadwal Mixing")

if schedule_df.empty:
    st.info("Tidak ada data untuk ditampilkan sebagai pivot.")
else:
    # Hitung date_range dari hasil schedule
    try:
        all_dates  = pd.to_datetime(schedule_df["Tanggal_Mixing"])
        date_min   = all_dates.min()
        date_max   = all_dates.max()

        # Extend 
