from __future__ import annotations

import io

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from core import analyze, extract_pdf_pages, load_expected_rows, results_to_dataframe, results_to_json, summary

app = FastAPI(title="Volantino Checkpoint API")


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return """
<!doctype html>
<html lang="it">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Volantino Checkpoint</title>
    <style>
      body { font-family: Arial, sans-serif; background:#f6f8fa; margin:0; padding:32px; }
      .card { max-width:760px; margin:0 auto; background:white; border-radius:12px; padding:24px; box-shadow:0 8px 30px rgba(0,0,0,0.08); }
      h1 { margin-top:0; }
      label { display:block; margin:12px 0 6px; font-weight:600; }
      input { width:100%; padding:8px; }
      button { margin-top:16px; padding:10px 16px; border:none; border-radius:8px; background:#0d6efd; color:#fff; cursor:pointer; }
      pre { background:#111827; color:#e5e7eb; padding:12px; border-radius:8px; overflow:auto; }
      .small { color:#4b5563; font-size:14px; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Volantino Checkpoint</h1>
      <p class="small">Web API deployata su Vercel. Carica PDF + Excel e ottieni il risultato JSON.</p>
      <form id="analyze-form">
        <label for="pdf">PDF volantino</label>
        <input id="pdf" name="pdf_file" type="file" accept="application/pdf" required />

        <label for="excel">Excel referenze</label>
        <input id="excel" name="excel_file" type="file" accept=".xlsx,.xls" required />

        <button type="submit">Analizza volantino</button>
      </form>

      <h3>Output</h3>
      <pre id="out">In attesa di input...</pre>
      <p class="small">Endpoint disponibili: <code>GET /api/health</code>, <code>POST /api/analyze</code>.</p>
    </div>

    <script>
      const form = document.getElementById('analyze-form');
      const out = document.getElementById('out');

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        out.textContent = 'Analisi in corso...';
        const data = new FormData(form);
        try {
          const res = await fetch('/api/analyze', { method: 'POST', body: data });
          const json = await res.json();
          out.textContent = JSON.stringify(json, null, 2);
        } catch (err) {
          out.textContent = 'Errore: ' + err;
        }
      });
    </script>
  </body>
</html>
"""


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
