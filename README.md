# fiscoib — dal report Interactive Brokers ai Quadri RW / RT / RM

**fiscoib** prende il report annuale di Interactive Brokers (il file *Flex Query XML*)
e calcola, per un residente fiscale italiano in **regime dichiarativo**, i tre quadri
che servono per la dichiarazione dei redditi:

- **Quadro RT** — plusvalenze e minusvalenze (imposta sostitutiva 26%);
- **Quadro RM** — dividendi esteri e interessi (imposta sostitutiva 26% / 12,5%);
- **Quadro RW / IVAFE** — monitoraggio delle attività estere e imposta patrimoniale 0,2%.

Produce un **facsimile dei quadri**, un **report Excel** riga per riga, un **PDF**
riepilogativo e gli export **CSV/JSON**.

> ⚠️ **AVVISO.** Questo software è uno strumento di supporto al calcolo e **non
> sostituisce un commercialista**. Dove la norma non è univoca il programma adotta
> l'interpretazione più prudente e la segnala con un *warning*. Verifica sempre i
> valori con un professionista prima di presentare la dichiarazione. Il software è
> fornito "così com'è", senza garanzie.

**Documentazione**

| File | Contenuto |
|---|---|
| [`GUIDA_TASSAZIONE.md`](GUIDA_TASSAZIONE.md) | Come funziona la tassazione: meccanismi dei tre quadri, esempi numerici, casi incerti, glossario |
| [`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md) | Riferimenti normativi con link alle fonti ufficiali |
| Questo file | Installazione, uso, output, architettura del codice |

**Indice**

- [Requisiti e installazione](#requisiti-e-installazione)
- [Come esportare il Flex Query da Interactive Brokers](#come-esportare-il-flex-query-da-interactive-brokers)
- [Uso](#uso)
- [Come leggere l'output](#come-leggere-loutput)
- [Cambi valuta: fonte e cache](#cambi-valuta-fonte-e-cache)
- [Limitazioni note](#limitazioni-note)
- [Architettura del codice](#architettura-del-codice)
- [Mappa: regola fiscale → dove è implementata](#mappa-regola-fiscale--dove-è-implementata)
- [Test](#test)

---

## Requisiti e installazione

Serve **Python 3.9+**. Nella cartella del progetto:

```bash
python3 -m venv .venv
source .venv/bin/activate         # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Come esportare il Flex Query da Interactive Brokers

1. **Client Portal** → *Performance & Reports* → *Flex Queries*.
2. Crea una **Activity Flex Query** in formato **XML**.
3. Includi almeno queste sezioni:
   - **Trades** (livello *Execution*)
   - **Cash Transactions** (Dividends, Payment In Lieu, Withholding Tax, Interest)
   - **Open Positions** (livello *Lot*, data al 31/12)
   - **Cash Report** (per valuta)
   - **Corporate Actions**
4. Una Activity Flex copre **max 365 giorni** per file: per lo storico completo scarica
   **un file per anno** e passali tutti insieme al comando. Il software li unisce e
   deduplica per `transactionID`. Lo storico pluriennale serve perché il LIFO e le
   minusvalenze riportabili guardano indietro nel tempo.

## Uso

```bash
python -m fiscoib ESTRATTO.xml --anno 2025 --out ./out
```

Con più anni di storico:

```bash
python -m fiscoib ib_2023.xml ib_2024.xml ib_2025.xml --anno 2025 --out ./out
```

### Opzioni

| Opzione | Default | Descrizione |
|---|---|---|
| `--anno` | (obblig.) | Anno d'imposta da dichiarare |
| `--out` | `./out` | Cartella di output |
| `--stato` | `IE` | Codice ISO alpha-2 dello stato del conto (IE = IBKR Ireland, US = IBKR LLC) |
| `--quota` | `100` | Quota di possesso % (0 < quota ≤ 100; es. 50 se cointestato) |
| `--frontiera` | `lordo` | Base imponibile dividendi: `lordo` (posizione AdE) o `netto` |
| `--ivafe-cfd` | off | Applica IVAFE anche ai CFD (default: solo monitoraggio) |
| `--ivafe-otc` | off | Applica IVAFE anche alle azioni OTC |
| `--cfd-divadj` | `RT` | Dividend adjustment CFD: `RT` o `RM` |
| `--pil` | `RM` | Payment In Lieu of Dividends: `RM` o `RT` |
| `--offline` | off | Non scaricare cambi online (usa solo cache/override) |
| `--db` | `<out>/rates_cache.sqlite` | Path della cache SQLite dei cambi |
| `--overrides` | – | JSON coi cambi medi mensili ufficiali AdE |
| `--no-ade-builtin` | off | Non usare la tabella cambi AdE integrata |
| `--prior-losses` | – | JSON `{anno: importo}` di minusvalenze pregresse riportabili |
| `--gov-bonds` | – | JSON con la lista di ISIN/simboli di titoli di Stato white list (cedole al 12,5%, codice A; senza lista ogni emittente obbligazionario genera warning) |

Esempio `prior-losses.json`:

```json
{ "2023": 1500.00, "2022": 800.00 }
```

Esempio `overrides.json` (cambi medi mensili ufficiali AdE, convenzione 1 EUR = X valuta):

```json
[ { "currency": "USD", "year": 2025, "month": 12, "rate": 1.0512 } ]
```

Le opzioni `--frontiera`, `--ivafe-cfd`, `--ivafe-otc`, `--cfd-divadj`, `--pil`
corrispondono ai casi fiscalmente incerti: la spiegazione di ogni scelta è in
[`GUIDA_TASSAZIONE.md`](GUIDA_TASSAZIONE.md), sezione 6.

## Come leggere l'output

Nella cartella `--out` vengono creati:

| File | Contenuto |
|---|---|
| `quadri_facsimile.txt` | Facsimile leggibile dei tre quadri con i righi valorizzati |
| `report_<anno>.xlsx` | Report Excel **riga per riga** (ogni chiusura, dividendo, posizione) |
| `riepilogo_<anno>.pdf` | PDF riepilogativo |
| `rt_plusvalenze.csv`, `rm_dividendi.csv`, `rw_monitoraggio.csv` | Export CSV per quadro |
| `risultati.json` | Tutti i risultati in formato strutturato |

L'Excel è pensato per la **validazione**: mostra per ogni operazione i cambi usati, i
valori in valuta e in euro e il dettaglio del calcolo, così ogni numero finale è
ricostruibile a mano.

La cartella `out_demo/` nel repository contiene un **esempio di output** generato su
dati fittizi, per vedere il formato senza eseguire nulla.

## Cambi valuta: fonte e cache

I tassi ufficiali vengono scaricati dalla **Banca d'Italia** e tenuti in una cache
locale (`rates_cache.sqlite`): alle esecuzioni successive si scaricano solo le date
mancanti. La logica fiscale (giornaliero per RT/RM, medio mensile per RW) è spiegata in
[`GUIDA_TASSAZIONE.md`](GUIDA_TASSAZIONE.md), sezione 5. Per lavorare senza rete usa
`--offline`; per forzare i medi mensili ufficiali usa `--overrides` (e
`--no-ade-builtin` per disattivare quelli integrati).

## Limitazioni note

- **Titoli trasferiti dentro IBKR senza storico di acquisto.** Il motore ricostruisce
  i lotti dai soli trade presenti nei file. Se una posizione è stata *trasferita* da un
  altro intermediario (nessun trade di apertura nello storico), una successiva vendita
  apre uno **short "fantasma"**: il software lo rileva a fine elaborazione ed emette un
  warning `SHORT_SPURIO` (simbolo e quantità), che va verificato caricando a mano il
  costo storico corretto. Il warning non distingue lo short intenzionale dallo storico
  mancante: serve verifica manuale.
- **Classificazione ETF/OICR.** Il riconoscimento di ETF/fondi si basa sui metadati del
  Flex (`sub_category`/`assetCategory`): se mancano, lo strumento ricade nel ramo
  azioni/LIFO. Controlla nel report la classe attribuita a ogni strumento.
- **Operazioni societarie complesse** (fusioni, spin-off, cambio simbolo) non sono
  gestite automaticamente: split e raggruppamenti sì, gli altri casi generano warning e
  vanno verificati a mano.
- **Emittenti obbligazionari senza ISIN**: il paese del Bond Interest ricade su quello
  del conto (`--stato`); verificare il rigo prodotto.
- **Cambi medi mensili**: gli override AdE integrati coprono dicembre 2024; gli altri
  mesi usano il proxy Banca d'Italia, eventualmente correggibile via `--overrides`.
- **Integrità del file di input.** All'apertura il software verifica le colonne
  fiscali essenziali della Flex Query (importi, commissioni, date, ID transazione) e
  **fallisce o segnala con warning CRITICAL** qualunque dato mancante, duplicato o non
  riconducibile (cancellazioni, date non parsabili, valori `buySell` sconosciuti): in
  questi casi il risultato va riesaminato prima dell'uso.

## Architettura del codice

Il flusso è lineare — dal file al risultato — ed è orchestrato da
`fiscoib/pipeline.py`:

```
file Flex XML
   │  parsing/flex_parser.py  →  parsing/models.py   (eventi normalizzati)
   ▼
1) engines/lots.py        ricostruzione lotti LIFO  →  chiusure realizzate
2) engines/income.py      Quadro RM (dividendi, interessi) + componenti per RT
3) engines/capital_gains  Quadro RT (plus/minus, minusvalenze pregresse)
4) engines/monitoring.py  Quadro RW / IVAFE
   │  fx/rates.py  fornisce i cambi ufficiali (cache SQLite)
   ▼
reports/*  →  facsimile, Excel, PDF, CSV, JSON
```

Principi di progetto:

- **gli importi restano in valuta originale** fino ai motori, che li convertono in euro
  ai cambi ufficiali: la base currency di IBKR non viene mai usata;
- **ogni scelta fiscale incerta è in un unico posto** (`config.py`) e genera un warning
  (`warnings.py`);
- **ogni motore ha una docstring** che spiega la regola fiscale applicata e la
  convenzione sui righi del quadro.

## Mappa: regola fiscale → dove è implementata

| Regola fiscale | File · funzione principale |
|---|---|
| Lettura del Flex Query XML (validazione colonne, dedup ID/hash, warning anti-drop) | `parsing/flex_parser.py` · `load`, `parse_file` |
| Modello dati normalizzato degli eventi (incl. distinzione OICR/ETF) | `parsing/models.py` |
| Metodo **LIFO** (azioni) e **costo medio ponderato** (OICR), ricostruzione lotti | `engines/lots.py` · `LotBook.process_trade`, `build_closures` |
| Split / raggruppamenti (corporate action) | `engines/lots.py` · `LotBook.process_corporate_action` |
| **Quadro RT**: RT21/RT22, plus/minus, commissioni deducibili; plus OICR scorporate | `engines/capital_gains.py` · `compute_rt` |
| Minusvalenze pregresse (4 anni, oldest-first) e riporto | `engines/capital_gains.py` · `compute_rt` |
| **Quadro RM**: dividendi lordo/netto frontiera; titoli di Stato 12,5% (codice A) | `engines/income.py` · `compute_rm` |
| Ritenute estere (match ±3 gg) e credito teorico | `engines/income.py` · `compute_rm` |
| Codici Stato estero numerici AdE | `ade_tables.py` · `iso2_to_ade` |
| **Quadro RW / IVAFE**: valorizzazione, pro-rata giorni, codici bene, soglia 200 € | `engines/monitoring.py` · `compute_rw` |
| Cambi ufficiali giornalieri e medi mensili (+ override AdE) | `fx/rates.py` · `RatesProvider`; `fx/ade_overrides.py` |
| Scelte fiscali e default prudenti | `config.py` · `FiscoConfig` |
| Warning sui casi incerti | `warnings.py` |
| Orchestrazione dell'intera pipeline | `pipeline.py` · `run` |

Il dettaglio normativo dietro ogni regola è in
[`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md).

## Test

```bash
python -m pytest -q
```

I test (58) verificano i casi limite contro valori calcolati a mano: LIFO multi-lotto e
short, costo medio ponderato OICR, separazione plus OICR / minus in RT, dividendo con
ritenuta (lordo/netto), IVAFE pro-rata e soglia 200 €, titolo comprato e venduto nello
stesso anno, cambi con fallback su giorni festivi, validazioni d'ingresso e dedup.
