from __future__ import annotations

import io

from fastapi import FastAPI, File, HTTPException, UploadFile

from core import analyze, extract_pdf_pages, load_expected_rows, results_to_dataframe, results_to_json, summary

app = FastAPI(title="Volantino Checkpoint API")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Volantino Checkpoint API",
        "status": "ok",
        "health": "/api/health",
        "analyze": "POST /api/analyze",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze_volantino(pdf_file: UploadFile = File(...), excel_file: UploadFile = File(...)) -> dict:
    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="pdf_file deve essere un PDF")

    if not excel_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="excel_file deve essere un file Excel")

    try:
        expected_df = load_expected_rows(io.BytesIO(await excel_file.read()))
        pages = extract_pdf_pages(await pdf_file.read())
        results = analyze(expected_df, pages)
        report_df = results_to_dataframe(results)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "summary": summary(report_df),
        "results": results_to_json(results),
    }
