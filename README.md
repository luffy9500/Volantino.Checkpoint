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

## 3) Codice MVP incluso

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

## 4) Esecuzione locale

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

## 5) Miglioramenti futuri

- Estrazione layout-aware (coordinate box prodotto/prezzo per ridurre falsi positivi).
- Dizionario sinonimi/categorie GDO per matching più robusto.
- Gestione avanzata promo complesse (3x2, sottocosto, bundle, prezzo al kg/l).
- Configurazione soglie fuzzy da UI per categoria merceologica.
- Audit log, autenticazione utenti, versionamento report.
- Batch processing multipli volantini e storico KPI qualità pre-stampa.
