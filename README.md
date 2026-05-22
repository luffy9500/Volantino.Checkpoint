# Volantino Checkpoint (MVP)

## 1) Architettura tecnica

Per massimizzare velocità di delivery dell’MVP ho scelto **Streamlit + backend Python integrato** in un’unica app:

- **UI + orchestrazione**: Streamlit (`app.py`)
- **Parsing Excel**: `pandas` + `openpyxl`
- **Parsing PDF**: `pdfplumber`
- **OCR fallback**: `pytesseract` (solo pagine senza testo selezionabile)
- **Confronto descrizioni**: `rapidfuzz`
- **Regole prezzo/formato**: `regex`
- **Output**: report Excel scaricabile (`.xlsx`)

Pipeline:
1. Upload PDF + Excel.
2. Validazione colonne Excel obbligatorie.
3. Estrazione testo pagina per pagina dal PDF.
4. Per ogni riga Excel:
   - ricerca in pagina attesa (codice/EAN/descrizione/formato);
   - confronto prezzo/descrizione/formato;
   - fallback ricerca altre pagine per identificare “Pagina errata”.
5. Classificazione esito + gravità.
6. Render tabella risultati + sintesi + export Excel.

## 2) Struttura cartelle progetto

```text
Volantino.Checkpoint/
├── app.py
├── requirements.txt
└── README.md
```


## 3) Struttura colonne input Excel (obbligatoria)

Il file Excel di input deve contenere **tutte** queste colonne (nomi esatti):

| Colonna | Tipo atteso | Descrizione | Esempio |
|---|---|---|---|
| `Pagina` | Intero | Numero pagina del volantino dove il prodotto deve comparire | `5` |
| `Codice articolo` | Testo | Codice interno prodotto | `ART-001234` |
| `EAN` | Testo/numero | Codice EAN del prodotto | `8001234567890` |
| `Descrizione corretta` | Testo | Descrizione attesa da confrontare col PDF | `Pasta di semola 500 g` |
| `Formato` | Testo | Grammatura / formato / confezione | `6x500 g` |
| `Prezzo corretto` | Numero/testo prezzo | Prezzo promo atteso | `2,99` |
| `Note` | Testo | Note promo opzionali (riportate in output) | `Sottocosto dal 12 al 14` |

> Se una o più colonne mancano, l'app blocca l'analisi e mostra l'elenco delle colonne mancanti.

## 4) Codice MVP incluso

Il file `app.py` include:
- UI richiesta (titolo, upload PDF, upload Excel, bottone “Analizza volantino”, tabella risultati, download report Excel);
- validazione colonne Excel obbligatorie;
- OCR opzionale su pagine senza testo;
- classificazione esiti:
  - OK
  - Prezzo errato
  - Descrizione diversa
  - Formato diverso
  - Referenza non trovata
  - Pagina errata
  - Da verificare manualmente
- assegnazione gravità:
  - Alta, Media, Bassa, OK
- output con colonne:
  - Pagina
  - Codice articolo
  - EAN
  - Descrizione Excel
  - Formato Excel
  - Prezzo Excel
  - Testo trovato nel PDF
  - Prezzo PDF rilevato
  - Esito
  - Gravità
  - Note controllo
- sintesi finale:
  - totale referenze
  - numero OK
  - numero anomalie alta/media/bassa gravità

## 5) Esecuzione locale

1. (Consigliato) crea un virtualenv.
2. Installa dipendenze:
   ```bash
   pip install -r requirements.txt
   ```
3. Installa Tesseract a livello sistema operativo (necessario per OCR fallback).
4. Avvia l’app:
   ```bash
   streamlit run app.py
   ```

## 6) Deploy web app e miglioramenti futuri

### Deploy su Vercel

Sì, puoi renderlo web app deployata, ma **Streamlit non è il target ideale di Vercel** (Vercel è ottimizzato per Next.js/serverless).

Opzioni consigliate:

1. **Più rapida (consigliata per questo MVP):** deploy Streamlit su Streamlit Community Cloud, Render o Railway.
2. **Se vuoi Vercel:** tenere frontend in **Next.js su Vercel** e spostare il backend Python (parsing PDF/OCR/Excel) su un servizio separato (es. FastAPI su Render/Railway/Fly), collegato via API.

Per OCR con Tesseract su cloud, verifica sempre disponibilità del binario di sistema nel provider scelto.

### Miglioramenti futuri

- Estrazione layout-aware (coordinate box prodotto/prezzo per ridurre falsi positivi).
- Dizionario sinonimi/categorie GDO per matching più robusto.
- Gestione avanzata promo complesse (3x2, sottocosto, bundle, prezzo al kg/l).
- Configurazione soglie fuzzy da UI per categoria merceologica.
- Audit log, autenticazione utenti, versionamento report.
- Batch processing multipli volantini e storico KPI qualità pre-stampa.


## 7) Modalità Vercel (API)

È stata aggiunta una versione compatibile Vercel basata su **FastAPI**:

- entrypoint serverless: `api/index.py`
- configurazione routing: `vercel.json`
- endpoint disponibili:
  - `GET /` (root, info endpoint)
  - `GET /api/health`
  - `POST /api/analyze` (multipart con campi `pdf_file` e `excel_file`)

### Esempio chiamata API

```bash
curl -X POST http://localhost:3000/api/analyze \
  -F "pdf_file=@volantino.pdf" \
  -F "excel_file=@referenze.xlsx"
```

> Nota: su Vercel l'OCR Tesseract può non essere disponibile come binario di sistema. In quel caso conviene usare OCR esterno o deploy su Render/Railway con immagine container custom.
