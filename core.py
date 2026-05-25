from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import pdfplumber
import pytesseract
from pytesseract import TesseractNotFoundError
from rapidfuzz import fuzz

PRICE_PATTERN = re.compile(r"(?:€\s*)?(\d{1,3}(?:[\.,]\d{2}))")
FORMAT_PATTERN = re.compile(r"\b(\d+\s?(?:ml|cl|l|kg|g|gr|pz|pcs|x\s?\d+))\b", re.IGNORECASE)
REQUIRED_COLUMNS = ["Pagina", "Codice articolo", "EAN", "Descrizione corretta", "Formato", "Prezzo corretto", "Note"]


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
    text = str(value).replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def extract_first_price(text: str) -> Decimal | None:
    m = PRICE_PATTERN.search(text)
    return parse_price(m.group(1)) if m else None


def extract_format(text: str) -> str:
    m = FORMAT_PATTERN.search(text)
    return normalize_text(m.group(1)) if m else ""


def load_expected_rows(excel_file: io.BytesIO) -> pd.DataFrame:
    df = pd.read_excel(excel_file)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel file Excel: {', '.join(missing)}")
    out = df.copy()
    out["Pagina"] = pd.to_numeric(out["Pagina"], errors="coerce")
    return out


def extract_pdf_pages(pdf_bytes: bytes, ocr_dpi: int = 200) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
                continue

            img = page.to_image(resolution=ocr_dpi).original
            try:
                ocr_text = (pytesseract.image_to_string(img) or "").strip()
            except TesseractNotFoundError:
                ocr_text = ""
            pages.append(ocr_text)
    return pages


def find_best_line_in_page(page_text: str, description: str, codice: str, ean: str, formato: str) -> tuple[str, int]:
    best_line, best_score = "", 0
    desc, cod, e, form = map(normalize_text, [description, codice, ean, formato])
    for line in page_text.splitlines():
        ln = normalize_text(line)
        if not ln:
            continue
        score = fuzz.token_set_ratio(desc, ln)
        if cod and cod in ln:
            score += 30
        if e and e in ln:
            score += 35
        if form and form in ln:
            score += 20
        score = min(score, 100)
        if score > best_score:
            best_score, best_line = score, line
    return best_line, best_score


def analyze(expected_df: pd.DataFrame, pages: list[str]) -> list[CheckResult]:
    res: list[CheckResult] = []
    for _, row in expected_df.iterrows():
        pagina = int(row["Pagina"]) if not pd.isna(row["Pagina"]) else -1
        codice, ean = str(row["Codice articolo"] or "").strip(), str(row["EAN"] or "").strip()
        desc, form = str(row["Descrizione corretta"] or "").strip(), str(row["Formato"] or "").strip()
        prezzo, note = parse_price(row["Prezzo corretto"]), str(row["Note"] or "").strip()
        if pagina < 1 or pagina > len(pages):
            res.append(CheckResult(pagina, codice, ean, desc, form, prezzo, "", None, NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Media", "Pagina Excel non valida"))
            continue
        line, score = find_best_line_in_page(pages[pagina - 1], desc, codice, ean, form)
        if not line:
            res.append(CheckResult(pagina, codice, ean, desc, form, prezzo, "", None, NORMALIZED_STATUS["REFERENZA NON TROVATA"], "Alta", "Nessuna corrispondenza nella pagina prevista"))
            continue
        ln = normalize_text(line)
        desc_score = fuzz.token_set_ratio(normalize_text(desc), ln)
        price_pdf = extract_first_price(ln)
        form_pdf = extract_format(ln)
        if score < 70:
            esito, grav, n = NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Media", f"Matching ambiguo (score={score})"
        elif prezzo is not None and price_pdf != prezzo:
            esito, grav, n = NORMALIZED_STATUS["PREZZO ERRATO"], "Alta", f"Prezzo atteso {prezzo}, rilevato {price_pdf}"
        elif form and form_pdf and normalize_text(form) != form_pdf:
            esito, grav, n = NORMALIZED_STATUS["FORMATO DIVERSO"], "Alta", f"Formato atteso '{form}', rilevato '{form_pdf}'"
        elif desc_score < 75:
            esito, grav, n = NORMALIZED_STATUS["DESCRIZIONE DIVERSA"], "Media", f"Descrizione molto diversa (score={desc_score:.1f})"
        elif desc_score < 88:
            esito, grav, n = NORMALIZED_STATUS["DA VERIFICARE MANUALMENTE"], "Bassa", f"Differenze minori descrizione (score={desc_score:.1f})"
        else:
            esito, grav, n = NORMALIZED_STATUS["OK"], "OK", "Nessuna anomalia"
        if note:
            n = f"{n}. Note promo: {note}"
        res.append(CheckResult(pagina, codice, ean, desc, form, prezzo, line, price_pdf, esito, grav, n))
    return res


def results_to_dataframe(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([{ 
        "Pagina": r.pagina, "Codice articolo": r.codice_articolo, "EAN": r.ean,
        "Descrizione Excel": r.descrizione_excel, "Formato Excel": r.formato_excel,
        "Prezzo Excel": str(r.prezzo_excel) if r.prezzo_excel is not None else "",
        "Testo trovato nel PDF": r.testo_trovato_pdf,
        "Prezzo PDF rilevato": str(r.prezzo_pdf_rilevato) if r.prezzo_pdf_rilevato is not None else "",
        "Esito": r.esito, "Gravità": r.gravita, "Note controllo": r.note_controllo,
    } for r in results])


def summary(df: pd.DataFrame) -> dict[str, int]:
    return {"totale": len(df), "ok": int((df["Esito"] == "OK").sum()), "alta": int((df["Gravità"] == "Alta").sum()), "media": int((df["Gravità"] == "Media").sum()), "bassa": int((df["Gravità"] == "Bassa").sum())}


def results_to_json(results: list[CheckResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        item = asdict(r)
        item["prezzo_excel"] = str(r.prezzo_excel) if r.prezzo_excel is not None else None
        item["prezzo_pdf_rilevato"] = str(r.prezzo_pdf_rilevato) if r.prezzo_pdf_rilevato is not None else None
        out.append(item)
    return out
