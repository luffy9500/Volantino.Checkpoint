from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core import analyze, extract_pdf_pages, load_expected_rows, results_to_dataframe, summary

TITLE = "Volantino Checkpoint"


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    return output.getvalue()


def render_ui() -> None:
    st.set_page_config(page_title=TITLE, layout="wide")
    st.title(TITLE)
    pdf_file = st.file_uploader("Upload PDF", type=["pdf"])
    excel_file = st.file_uploader("Upload Excel", type=["xlsx", "xls"])

    if st.button("Analizza volantino", type="primary", disabled=not (pdf_file and excel_file)):
        try:
            with st.spinner("Validazione file e analisi in corso..."):
                expected_df = load_expected_rows(excel_file)
                pages = extract_pdf_pages(pdf_file.read())
                results = analyze(expected_df, pages)
                report_df = results_to_dataframe(results)
                counters = summary(report_df)
        except Exception as exc:
            st.error(f"Errore durante l'analisi: {exc}")
            return

        st.subheader("Tabella risultati")
        st.dataframe(report_df, use_container_width=True)
        st.subheader("Sintesi finale")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Totale referenze", counters["totale"])
        c2.metric("OK", counters["ok"])
        c3.metric("Anomalie alta gravità", counters["alta"])
        c4.metric("Anomalie media gravità", counters["media"])
        c5.metric("Anomalie bassa gravità", counters["bassa"])

        st.download_button(
            label="Download report Excel",
            data=to_excel_bytes(report_df),
            file_name="volantino_checkpoint_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    render_ui()
