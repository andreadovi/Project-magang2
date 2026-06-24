# app.py
import streamlit as st
import pandas as pd
import io

from scheduler import generate_mixing_schedule, unpivot_filling_plan
from pivot import build_pivot, pivot_to_excel
from template_generator import (
    generate_template_master_mixer,
    generate_template_master_produk,
    generate_template_filling_plan,
)

st.set_page_config(page_title="Mixing Scheduler", layout="wide")
st.title("🧪 Mixing Scheduler")

# Session state defaults
for key in ["master_mixer", "master_produk", "filling_plan", "schedule_result"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📂 Upload Data")

    # Download Template
    with st.expander("📥 Download Template Excel", expanded=True):
        st.caption("Download template, isi data, lalu upload di bawah.")
        st.download_button(
            label="⬇️ Template Master Mixer",
            data=generate_template_master_mixer(),
            file_name="template_master_mixer.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.download_button(
            label="⬇️ Template Master Produk",
            data=generate_template_master_produk(),
            file_name="template_master_produk.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.download_button(
            label="⬇️ Template Filling Plan (Kalender)",
            data=generate_template_filling_plan(),
            file_name="template_filling_plan.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.divider()

    # Upload Master Mixer
    st.subheader("1. Master Mixer")
    f_mixer = st.file_uploader("Upload (.xlsx)", type=["xlsx"], key="up_mixer")
    if f_mixer:
        try:
            df = pd.read_excel(f_mixer)
            st.session_state.master_mixer = df
            st.success(f"✅ {len(df)} mixer dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    # Upload Master Produk
    st.subheader("2. Master Produk")
    f_produk = st.file_uploader("Upload (.xlsx)", type=["xlsx"], key="up_produk")
    if f_produk:
        try:
            df = pd.read_excel(f_produk)
            st.session_state.master_produk = df
            st.success(f"✅ {len(df)} produk dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    # Upload Filling Plan
    st.subheader("3. Filling Plan")
    f_filling = st.file_uploader("Upload (.xlsx)", type=["xlsx"], key="up_filling")
    if f_filling:
        try:
            df = pd.read_excel(f_filling)
            st.session_state.filling_plan = df
            st.success(f"✅ {len(df)} baris dimuat.")
        except Exception as e:
            st.error(f"Gagal baca file: {e}")

    st.divider()

    # Tombol Generate
    ready = all([
        st.session_state.master_mixer  is not None,
        st.session_state.master_produk is not None,
        st.session_state.filling_plan  is not None,
    ])

    if st.button("⚡ Generate Jadwal Mixing", disabled=not ready, use_container_width=True):
        st.session_state.schedule_result = None
        with st.spinner("Memproses..."):
            try:
                filling_input = unpivot_filling_plan(st.session_state.filling_plan)
                if filling_input.empty:
                    st.warning("Filling Plan kosong. Pastikan ada data CS > 0.")
                else:
                    result = generate_mixing_schedule(
                        st.session_state.master_mixer,
                        st.session_state.master_produk,
                        filling_input,
                    )
                    st.session_state.schedule_result = result
                    st.success("✅ Jadwal berhasil dibuat!")
            except Exception as e:
                st.error(f"Error: {e}")
                st.exception(e)

    if not ready:
        st.info("Upload ketiga file untuk mengaktifkan Generate.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.schedule_result is None:
    st.info("👈 Upload data dan klik **Generate Jadwal Mixing** untuk memulai.")
    st.stop()

result      = st.session_state.schedule_result
schedule_df = result["schedule"]
warnings    = result["warnings"]
shifted     = result["shifted"]
unscheduled = result["unscheduled"]

# Ringkasan
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jadwal Mixing", len(schedule_df))
col2.metric("Produk Unik",
            schedule_df["Kode_Produk"].nunique() if not schedule_df.empty else 0)
col3.metric("Peringatan", len(warnings))
col4.metric("Tidak Terjadwal", len(unscheduled))

st.divider()

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

# Jadwal detail
st.subheader("📋 Jadwal Mixing Detail")
if schedule_df.empty:
    st.warning("Tidak ada jadwal yang berhasil dibuat.")
else:
    st.dataframe(schedule_df, use_container_width=True, height=400)
    csv_buf = io.StringIO()
    schedule_df.to_csv(csv_buf, index=False)
    st.download_button(
        label="⬇️ Download Jadwal (CSV)",
        data=csv_buf.getvalue().encode("utf-8"),
        file_name="jadwal_mixing.csv",
        mime="text/csv",
    )

st.divider()

# Pivot
st.subheader("📅 Pivot Jadwal Mixing")

if schedule_df.empty:
    st.info("Tidak ada data untuk pivot.")
    st.stop()

try:
    all_dates  = pd.to_datetime(schedule_df["Tanggal_Mixing"])
    fill_dates = pd.to_datetime(schedule_df["Tanggal_Filling"])
    date_min   = all_dates.min()
    date_max   = max(all_dates.max(), fill_dates.max())
    date_range = (
        pd.date_range(start=date_min, end=date_max)
        .strftime("%Y-%m-%d")
        .tolist()
    )
except Exception as e:
    st.error(f"Gagal menghitung date_range: {e}")
    st.stop()

try:
    pivot_df, meta = build_pivot(
        schedule_df,
        st.session_state.master_mixer,
        st.session_state.master_produk,
        date_range,
    )
except Exception as e:
    st.error(f"Gagal membuat pivot: {e}")
    st.exception(e)
    st.stop()

if pivot_df.empty:
    st.warning("Pivot kosong.")
    st.stop()

st.dataframe(pivot_df, use_container_width=True, height=500)

try:
    excel_bytes = pivot_to_excel(pivot_df, meta, st.session_state.master_mixer)
    st.download_button(
        label="⬇️ Download Pivot (Excel)",
        data=excel_bytes,
        file_name="pivot_jadwal_mixing.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception as e:
    st.error(f"Gagal export Excel: {e}")

st.divider()
st.caption("Mixing Scheduler — dibuat dengan ❤️ menggunakan Streamlit")
