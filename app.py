from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import pdfplumber
import pytesseract
import streamlit as st
from rapidfuzz import fuzz

TITLE = "Volantino Checkpoint"

PRICE_PATTERN = re.compile(r"(?:€\s*)?(\d{1,3}(?:[\.,]\d{2}))")
FORMAT_PATTERN = re.compile(r"\b(\d+\s?(?:ml|cl|l|kg|g|gr|pz|pcs|x\s?\d+))\b", re.IGNORECASE)

REQUIRED_COLUMNS = [
    "Pagina",
    "Codice articolo",
    "EAN",
    "Descrizione corretta",
    "Formato",
    "Prezzo corretto",
    "Note",
]


@dataclass
class CheckResult:
    pagina: int
    codice_articolo: str
    ean: str
    descrizione_excel: str
    formato_excel: str
    prezzo_excel: Decimal | None
    testo_trovato_pdf: str
    prezzo_pdf_rilevato: Decimal | None
    esito: str
    gravita: str
    note_controllo: str


NORMALIZED_STATUS = {
    "OK": "OK",
    "PREZZO ERRATO": "Prezzo errato",
    "DESCRIZIONE DIVERSA": "Descrizione diversa",
    "FORMATO DIVERSO": "Formato diverso",
    "REFERENZA NON TROVATA": "Referenza non trovata",
    "PAGINA ERRATA": "Pagina errata",
    "DA VERIFICARE MANUALMENTE": "Da verificare manualmente",
}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def parse_price(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace("€", "").strip()
    text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def extract_first_price(text: str) -> Decimal | None:
    match = PRICE_PATTERN.search(text)
    return parse_price(match.group(1)) if match else None


def extract_format(text: str) -> str:
    match = FORMAT_PATTERN.search(text)
    return normalize_text(match.group(1)) if match else ""


def validate_excel_columns(df: pd.DataFrame) -> list[str]:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    return missing


def load_expected_rows(excel_file: io.BytesIO) -> pd.DataFrame:
    df = pd.read_excel(excel_file)
    missing = validate_excel_columns(df)
    if missing:
        raise ValueError(f"Colonne mancanti nel file Excel: {', '.join(missing)}")

    work = df.copy()
    work["Pagina"] = pd.to_numeric(work["Pagina"], errors="coerce")
    return work


def extract_pdf_pages(pdf_bytes: bytes, ocr_dpi: int = 200) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
                continue
            page_image = page.to_image(resolution=ocr_dpi).original
            ocr_text = pytesseract.image_to_string(page_image)
            pages.append((ocr_text or "").strip())
    return pages


def find_best_line_in_page(page_text: str, description: str, codice: str, ean: str, formato: str) -> tuple[str, int]:
    best_line = ""
    best_score = 0
    desc_norm = normalize_text(description)
    codice_norm = normalize_text(codice)
    ean_norm = normalize_text(ean)
    formato_norm = normalize_text(formato)

    for line in page_text.splitlines():
        line_norm = normalize_text(line)
        if not line_norm:
            continue

        score = fuzz.token_set_ratio(desc_norm, line_norm)
        if codice_norm and codice_norm in line_norm:
            score += 30
        if ean_norm and ean_norm in line_norm:
            score += 35
        if formato_norm and formato_norm in line_norm:
            score += 20

        score = min(score, 100)

        if score > best_score:
            best_score = score
            best_line = line

    return best_line, best_score


def search_in_other_pages(pages: list[str], target_page: int, description: str, codice: str, ean: str, formato: str) -> tuple[int | None, str, int]:
    best_page = None
    best_line = ""
    best_score = 0
    for idx, page_text in enumerate(pages, start=1):
        if idx == target_page:
            continue
        line, score = find_best_line_in_page(page_text, description, codice, ean, formato)
        if score > best_score:
            best_score = score
            best_page = idx
            best_line = line
    return best_page, best_line, best_score


def classify_result(description: str, formato_excel: str, prezzo_excel: Decimal | None, found_line: str, score: int) -> tuple[str, str, str, Decimal | None]:
    if not found_line:
        return NORMALIZED_STATUS["REFERENZA NON TROVATA"], "Alta", "Nessuna corrispondenza nella pagina prevista", None

    line_norm = normalize_text(found_line)
    desc_score = fuzz.token_set_ratio(normalize_text(description), line_norm)
    format_pdf = extract_format(line_norm)
    price_pdf = extract_first_price(line_norm)

    if score < 70:
        return NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Media", f"Matching ambiguo (score={score})", price_pdf

    if prezzo_excel is not None and price_pdf != prezzo_excel:
        return NORMALIZED_STATUS["PREZZO ERRATO"], "Alta", f"Prezzo atteso {prezzo_excel}, rilevato {price_pdf}", price_pdf

    if formato_excel and format_pdf and normalize_text(formato_excel) != format_pdf:
        return NORMALIZED_STATUS["FORMATO DIVERSO"], "Alta", f"Formato atteso '{formato_excel}', rilevato '{format_pdf}'", price_pdf

    if desc_score < 75:
        return NORMALIZED_STATUS["DESCRIZIONE DIVERSA"], "Media", f"Descrizione molto diversa (score={desc_score:.1f})", price_pdf

    if 75 <= desc_score < 88:
        return NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Bassa", f"Differenze minori descrizione (score={desc_score:.1f})", price_pdf

    return NORMALIZED_STATUS["OK"], "OK", "Nessuna anomalia", price_pdf


def analyze_rows(expected_df: pd.DataFrame, pages: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []

    for _, row in expected_df.iterrows():
        pagina = int(row["Pagina"]) if not pd.isna(row["Pagina"]) else -1
        codice = str(row["Codice articolo"] or "").strip()
        ean = str(row["EAN"] or "").strip()
        descr = str(row["Descrizione corretta"] or "").strip()
        formato = str(row["Formato"] or "").strip()
        prezzo_excel = parse_price(row["Prezzo corretto"])
        note = str(row["Note"] or "").strip()

        if pagina < 1 or pagina > len(pages):
            results.append(
                CheckResult(pagina, codice, ean, descr, formato, prezzo_excel, "", None, NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Media", "Pagina Excel non valida")
            )
            continue

        target_text = pages[pagina - 1]
        best_line, score = find_best_line_in_page(target_text, descr, codice, ean, formato)

        if score < 70:
            other_page, other_line, other_score = search_in_other_pages(pages, pagina, descr, codice, ean, formato)
            if other_page is not None and other_score >= 75:
                price_pdf = extract_first_price(other_line)
                results.append(
                    CheckResult(
                        pagina,
                        codice,
                        ean,
                        descr,
                        formato,
                        prezzo_excel,
                        other_line,
                        price_pdf,
                        NORMALIZED_STATUS["PAGINA ERRATA"],
                        "Media",
                        f"Possibile match trovato a pagina {other_page} (score={other_score})",
                    )
                )
                continue

        esito, gravita, note_controllo, price_pdf = classify_result(descr, formato, prezzo_excel, best_line, score)
        final_note = note_controllo if not note else f"{note_controllo}. Note promo: {note}"

        results.append(
            CheckResult(
                pagina,
                codice,
                ean,
                descr,
                formato,
                prezzo_excel,
                best_line,
                price_pdf,
                esito,
                gravita,
                final_note,
            )
        )

    return results


def results_to_dataframe(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Pagina": r.pagina,
                "Codice articolo": r.codice_articolo,
                "EAN": r.ean,
                "Descrizione Excel": r.descrizione_excel,
                "Formato Excel": r.formato_excel,
                "Prezzo Excel": str(r.prezzo_excel) if r.prezzo_excel is not None else "",
                "Testo trovato nel PDF": r.testo_trovato_pdf,
                "Prezzo PDF rilevato": str(r.prezzo_pdf_rilevato) if r.prezzo_pdf_rilevato is not None else "",
                "Esito": r.esito,
                "Gravità": r.gravita,
                "Note controllo": r.note_controllo,
            }
            for r in results
        ]
    )


def summarize(results_df: pd.DataFrame) -> dict[str, int]:
    return {
        "totale": len(results_df),
        "ok": int((results_df["Esito"] == "OK").sum()),
        "alta": int((results_df["Gravità"] == "Alta").sum()),
        "media": int((results_df["Gravità"] == "Media").sum()),
        "bassa": int((results_df["Gravità"] == "Bassa").sum()),
    }


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
                results = analyze_rows(expected_df, pages)
                report_df = results_to_dataframe(results)
                counters = summarize(report_df)
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
