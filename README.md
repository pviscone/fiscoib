# fiscoib — dal report Interactive Brokers ai Quadri RW / RT / RM

**fiscoib** prende il report annuale di **Interactive Brokers** (il file *Flex Query
XML*) e calcola, per un residente fiscale italiano in **regime dichiarativo**, i tre
quadri che servono per la dichiarazione dei redditi:

- **Quadro RT** — plusvalenze e minusvalenze (imposta sostitutiva 26%);
- **Quadro RM** — dividendi esteri e interessi (imposta sostitutiva 26%);
- **Quadro RW / IVAFE** — monitoraggio delle attività estere e imposta patrimoniale 0,2%.

In uscita produce: un **facsimile dei quadri**, un **report Excel** dettagliato riga
per riga, un **PDF** riepilogativo e gli export **CSV/JSON**.

> ⚠️ **AVVISO IMPORTANTE.** Questo software è uno strumento di supporto al calcolo e
> **non sostituisce un commercialista**. Diversi trattamenti fiscali sono
> normativamente **incerti** (frontiera dividendi, IVAFE su CFD/OTC, dividend
> adjustment sui CFD, PIL da prestito titoli): il programma adotta i default più
> prudenti e **segnala con un *warning* ogni caso dubbio**. Verifica sempre i valori
> con un professionista prima di presentare la dichiarazione. Il software è fornito
> "così com'è", senza alcuna garanzia.

---

## Indice

**Parte 1 — Capire cosa fa (per tutti)**
- [In breve](#in-breve)
- [I tre quadri in parole semplici](#i-tre-quadri-in-parole-semplici)
- [Come vengono fatti i calcoli](#come-vengono-fatti-i-calcoli)
  - [Quadro RT — plusvalenze e minusvalenze](#quadro-rt--plusvalenze-e-minusvalenze)
  - [Quadro RM — dividendi e interessi](#quadro-rm--dividendi-e-interessi)
  - [Quadro RW / IVAFE — monitoraggio](#quadro-rw--ivafe--monitoraggio)
- [I cambi valuta usati](#i-cambi-valuta-usati)
- [I casi fiscalmente incerti e i default prudenti](#i-casi-fiscalmente-incerti-e-i-default-prudenti)
- [Limitazioni note](#limitazioni-note)

**Parte 2 — Usarlo e validarlo (tecnica)**
- [Requisiti e installazione](#requisiti-e-installazione)
- [Come esportare il Flex Query da Interactive Brokers](#come-esportare-il-flex-query-da-interactive-brokers)
- [Uso](#uso)
- [Come leggere l'output](#come-leggere-loutput)
- [Architettura del codice](#architettura-del-codice)
- [Mappa: regola fiscale → dove è implementata](#mappa-regola-fiscale--dove-è-implementata)
- [Test](#test)
- [Riferimenti normativi](#riferimenti-normativi)

---
---

# Parte 1 — Capire cosa fa

## In breve

Chi investe con un broker estero come Interactive Brokers deve, ogni anno:

1. **dichiarare le plusvalenze/minusvalenze** realizzate vendendo titoli (Quadro RT);
2. **dichiarare i redditi di capitale** — dividendi e interessi — incassati (Quadro RM);
3. **monitorare le attività estere** e pagare l'imposta patrimoniale IVAFE (Quadro RW).

Il problema è che il report di Interactive Brokers **non è pronto per il fisco
italiano**: usa il metodo FIFO (l'Italia impone il **LIFO**), è in valuta estera
(servono i **cambi ufficiali italiani**, giorno per giorno) e non applica le regole
del TUIR. `fiscoib` rifà tutti i conti secondo le regole italiane e mostra, riga per
riga, **come** arriva a ogni numero — così il risultato è verificabile.

## I tre quadri in parole semplici

| Quadro | Cosa dichiara | Imposta |
|---|---|---|
| **RT** | Guadagni/perdite realizzati **vendendo** titoli (azioni, CFD) | 26% sul guadagno netto |
| **RM** | Soldi **incassati** da dividendi e interessi | 26% sull'incasso |
| **RW / IVAFE** | Il **valore** di ciò che detieni all'estero (monitoraggio + patrimoniale) | 0,2% sul valore |

Le tre cose sono indipendenti: una **perdita** su una vendita (RT) **non** si può usare
per abbassare le tasse su un **dividendo** (RM). È una regola del TUIR, non una scelta
del software.

## Come vengono fatti i calcoli

Per ogni quadro qui sotto trovi: **la regola**, **la formula usata**, un **esempio
numerico** e il **riferimento normativo**. Gli importi in valuta estera sono sempre
convertiti in euro ai cambi ufficiali (vedi [I cambi valuta usati](#i-cambi-valuta-usati)).

### Quadro RT — plusvalenze e minusvalenze

**La regola.** Quando vendi un titolo, il guadagno tassabile è *quanto incassi* meno
*quanto ti era costato* (comprese le commissioni). Se hai comprato lo stesso titolo in
momenti diversi, l'Italia impone il metodo **LIFO**: si considerano vendute per prime
le quote comprate **più di recente** (art. 67 c.1-bis TUIR). Interactive Brokers usa
invece il FIFO, quindi i suoi valori di plus/minus **non sono utilizzabili**: il
software li ricostruisce da zero dai singoli trade.

**La formula.** Per ogni vendita ("chiusura"), convertita in euro ai cambi del giorno:

```
Corrispettivi (RT21) = prezzo di vendita
Costi        (RT22) = prezzo di acquisto + TUTTE le commissioni (acquisto + vendita)
Plus/minus          = RT21 − RT22
```

Le commissioni sono interamente deducibili (art. 68 c. 6 TUIR: il costo di acquisto è
assunto al lordo di ogni onere accessorio di diretta imputazione). Gli **interessi
passivi / di margine NON sono deducibili** e non entrano nel calcolo (per una persona
fisica).

**Attenzione — ETF e fondi (quote OICR): regole diverse.** Per le quote di ETF/fondi
esteri **non** vale il LIFO e **non** valgono le compensazioni quadro RT:

- il calcolo dei lotti usa il **costo medio ponderato** (lo strumento lo tratta in
  automatico: categoria `ETF`/`FUND` nel Flex);
- la **plusvalenza** da cessione di quote OICR è un **reddito di capitale** (art. 44
  c.1 lett. g TUIR): non è compensabile con nessuna minusvalenza e va dichiarata tra i
  redditi di capitale (il software la espone separatamente, come componente
  `oicr_gains`, lettera H, aliquota 26%);
- la **minusvalenza** da quote OICR è invece un reddito **diverso**: resta nel Quadro
  RT e compensa solo plus/minus di natura diversi.

Lo scorporo avviene automaticamente: il Quadro RT prodotto riguarda solo i redditi
diversi (azioni, CFD ecc.) e non include le plus OICR.

Sul **saldo annuo** di tutte le chiusure:
- se è **positivo**, si sottraggono le eventuali **minusvalenze pregresse** (utilizzabili
  nei **4 anni** successivi a quello in cui sono state realizzate; si consumano prima le
  più vecchie per non farle scadere) e sul risultato si applica il **26%**;
- se è **negativo**, è una **minusvalenza dell'anno** da riportare nei 4 anni successivi
  (va indicata in dichiarazione, altrimenti si perde).

**Esempio.** Compri 10 azioni a 100 € (commissione 5 €) e le vendi a 130 € (commissione 5 €):

```
RT21 = 10 × 130            = 1.300 €
RT22 = 10 × 100 + 5 + 5    = 1.010 €
Plusvalenza                =   290 €
Imposta 26%                = 75,40 €
```

**Riferimenti:** artt. 67–68 TUIR; LIFO art. 67 c.1-bis TUIR; deducibilità commissioni
art. 68 c. 6 TUIR. Per le plusvalenze in valuta estera (cambio da applicare a ogni
singola operazione) v. Risposta AdE a interpello n. 344 del 2020, che riguarda proprio
la cessione di partecipazioni in valuta estera — non citarla a sostegno della
deducibilità delle commissioni, che discende direttamente dall'art. 68.

### Quadro RM — dividendi e interessi

**La regola.** Dividendi esteri e interessi attivi sono **redditi di capitale**: si
tassano al **26%** su quanto incassato, per **cassa** (conta l'anno del pagamento). Il
software li aggancia alle eventuali **ritenute estere** applicate alla fonte.

**Il punto delicato — "frontiera".** Sul dividendo estero lo Stato estero trattiene già
una ritenuta (es. 15% negli USA). Poi c'è il 26% italiano. La domanda è: il 26% si
calcola sul dividendo **lordo** o su quello **al netto** della ritenuta estera?

| Metodo | Base del 26% | Chi lo sostiene | Default |
|---|---|---|---|
| **Lordo** | dividendo pieno | Agenzia delle Entrate | ✅ (`--frontiera lordo`) |
| **Netto frontiera** | dividendo − ritenuta estera | giurisprudenza, più favorevole ma **contestato** | opzionale (`--frontiera netto`) |

Nel regime dichiarativo a imposta sostitutiva **il credito per le imposte estere non è
scomputabile** (art. 165 TUIR): il software lo calcola solo come **importo teorico
informativo**, eventualmente recuperabile con un'istanza di rimborso (esito incerto).

**Esempio (metodo lordo, default).** Dividendo lordo 100 €, ritenuta estera 15 €
(incassi 85 €):

```
Base imponibile     = 100 €        (lordo)
Imposta italiana 26% = 26 €
Credito estero teorico = 15 €       (solo informativo, non scomputato)
```

Con il metodo **netto frontiera** la base sarebbe 100 − 15 = 85 € e l'imposta 22,10 €.

Gli **interessi attivi** (su liquidità, codice G; cedole obbligazionarie corporate,
codice I) si tassano al 26% allo stesso modo. Le **cedole di titoli di Stato italiani
ed esteri in white list** e di organismi internazionali sovranazionali si tassano invece
al **12,50%** (codice A): lo script li riconosce se fornisci l'elenco ISIN/simboli con
`--gov-bonds` (senza elenco segnala un warning per ogni emittente obbligazionario).
Gli **interessi passivi / di margine non sono deducibili** e vengono ignorati con una
nota.

**Riga/lettere usate:** rigo RM31 della Sezione II-A del Redditi PF (lettere: A, C, G,
H, I). Se compili il **Modello 730**, lo stesso contenuto va nel **Quadro M, rigo
M31** (stesse lettere e colonne).

**Riferimenti:** art. 18 e art. 44 TUIR (redditi di capitale); art. 165 TUIR (credito
d'imposta estero); base imponibile lordo frontiera: istruzioni rigo RM31 col. 3
("al lordo di eventuali ritenute subite nello Stato estero") e Risposta AdE n.
111/2020. Per il credito d'imposta estero la posizione AdE esclude lo scomputo in
imposta sostitutiva, ma la giurisprudenza di legittimità (Cass. n. 25698/2022 e Cass.
n. 10204/2024) riconosce il credito quando la tassazione sostitutiva è obbligatoria.

### Quadro RW / IVAFE — monitoraggio

**La regola.** Vanno monitorate **tutte** le attività estere detenute nell'anno (anche
se in perdita o non movimentate) e su di esse si paga l'**IVAFE**, l'imposta
patrimoniale sui prodotti finanziari esteri: **0,2%** annuo (0,4% se il paese è in black
list), **pro-rata** sui giorni di possesso. **Se l'IVAFE complessiva non supera 200 € il
versamento non è dovuto** (il rigo RW si compila comunque a solo monitoraggio
dell'attività): il prospetto distingue quindi *teorica* e *da versare*.

Nel quadro lo **Stato estero è riportato col codice numerico AdE a 3 cifre** (tabella
"Elenco Paesi e Territori esteri": US=069, IE=040...), affiancato al consueto ISO.

**La valorizzazione** usa il cambio **medio mensile** ufficiale (non quello giornaliero):
- titolo ancora in portafoglio al 31/12 → **valore di mercato al 31/12**;
- titolo venduto durante l'anno → valore all'**ultima vendita**;
- valore iniziale → valore al 1/1 se già detenuto, altrimenti valore di acquisto.

**La formula:**

```
IVAFE = valore_finale_EUR × aliquota × (giorni_possesso / 365) × (quota_possesso% / 100)
```

**Codici "bene"** (colonna 3 del Quadro RW):

| Codice | Tipo di attività |
|---|---|
| **20** | Conto deposito titoli estero (azioni quotate e liquidità) |
| **2**  | Partecipazioni non quotate (azioni OTC) |
| **9**  | Contratti derivati / rapporti finanziari (CFD) |

**Esempio.** 50.000 USD di azioni in portafoglio tutto l'anno, cambio medio di dicembre
1,0479 (1 EUR = 1,0479 USD):

```
Valore finale = 50.000 / 1,0479 ≈ 47.714 €
IVAFE = 47.714 × 0,2% × (365/365) × 100%  ≈ 95,43 €
```

**Riferimenti:** monitoraggio art. 4 D.L. 167/1990; IVAFE art. 19 D.L. 201/2011.

## I cambi valuta usati

L'Agenzia delle Entrate impone cambi diversi a seconda del quadro. Il software usa i
cambi ufficiali della **Banca d'Italia** e li scarica automaticamente:

- **RT e RM** → cambio di **riferimento giornaliero** alla data dell'operazione / del
  pagamento;
- **RW / IVAFE** → cambio **medio mensile** (dicembre per i valori al 31/12), integrabile
  con i valori ufficiali del provvedimento AdE del mese;
- il campo `fxRateToBase` presente nel file IBKR **non** è fiscalmente valido e **non**
  viene usato.

Convenzione dei tassi Banca d'Italia: il cambio indica *quante unità di valuta estera
valgono 1 EUR* (es. EUR/USD ≈ 1,08), quindi `euro = importo_estero / cambio`.

## I casi fiscalmente incerti e i default prudenti

Per i punti su cui la normativa non è univoca, il software sceglie l'interpretazione
**più difendibile/prudente** e stampa un **warning**. Puoi cambiare ogni scelta da riga
di comando.

| Caso incerto | Default prudente | Opzione per cambiarlo |
|---|---|---|
| Base imponibile dividendi | lordo frontiera (posizione AdE) | `--frontiera netto` |
| IVAFE su CFD | solo monitoraggio, IVAFE non applicata | `--ivafe-cfd` |
| IVAFE su azioni OTC | solo monitoraggio | `--ivafe-otc` |
| Dividend adjustment su CFD | tra i redditi diversi (Quadro RT) | `--cfd-divadj RM` |
| Payment In Lieu of Dividends | reddito di capitale (Quadro RM) | `--pil RT` |

## Limitazioni note

- **Titoli trasferiti dentro IBKR senza storico di acquisto.** Il motore ricostruisce
  i lotti dai soli trade presenti nei file. Se una posizione è stata *trasferita* da un
  altro intermediario (nessun trade di apertura nello storico), una successiva vendita
  apre uno **short "fantasma"**: il software lo rileva a fine elaborazione ed emette un
  warning `SHORT_SPURIO` (simbolo e quantità), che va assolutamente verificato
  caricando a mano il costo storico corretto (il valore calcolato in assenza sarebbe
  errato).
- **Operazioni societarie complesse** (fusioni, spin-off, cambio simbolo) non sono
  gestite automaticamente: split e raggruppamenti sì, gli altri casi generano un warning
  e vanno verificati a mano.
- **Integrità del file di input.** All'apertura il software verifica la presenza delle
  colonne fiscali essenziali della Flex Query (importi, commissioni, date, ID
  transazione) e **fallisce o segnala con warning CRITICAL** qualunque dato mancante,
  duplicato o non riconducibile (cancellazioni, date non parsabili, valori `buySell`
  sconosciuti): in questi casi il risultato va riesaminato prima dell'uso.

---
---

# Parte 2 — Usarlo e validarlo

Questa parte è per chi vuole **eseguire** il programma o **verificarne il codice**.
Richiede un minimo di dimestichezza con il terminale e con Python.

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

### Opzioni principali

| Opzione | Default | Descrizione |
|---|---|---|
| `--anno` | (obblig.) | Anno d'imposta da dichiarare |
| `--stato` | `IE` | Codice stato estero del conto (IE = IBKR Ireland, US = IBKR LLC) |
| `--quota` | `100` | Quota di possesso % (es. 50 se cointestato) |
| `--frontiera` | `lordo` | Base imponibile dividendi: `lordo` (posizione AdE) o `netto` |
| `--ivafe-cfd` | off | Applica IVAFE anche ai CFD (default: solo monitoraggio) |
| `--ivafe-otc` | off | Applica IVAFE anche alle azioni OTC |
| `--cfd-divadj` | `RT` | Dividend adjustment CFD: `RT` o `RM` |
| `--pil` | `RM` | Payment In Lieu of Dividends: `RM` o `RT` |
| `--offline` | off | Non scarica cambi online (usa solo cache/override) |
| `--overrides` | – | JSON coi cambi medi mensili ufficiali AdE |
| `--prior-losses` | – | JSON `{anno: importo}` di minusvalenze pregresse riportabili |
| `--gov-bonds` | – | JSON lista di ISIN/simboli di titoli di Stato white list (cedole al 12,5% codice A; senza lista, ogni emittente obbligazionario genera warning) |

Esempio `prior-losses.json`:

```json
{ "2023": 1500.00, "2022": 800.00 }
```

Esempio `overrides.json` (cambi medi mensili ufficiali AdE, 1 EUR = X valuta):

```json
[ { "currency": "USD", "year": 2025, "month": 12, "rate": 1.0512 } ]
```

I cambi vengono scaricati dalla Banca d'Italia e messi in cache locale
(`out/rates_cache.sqlite`): alle esecuzioni successive si scaricano solo le date
mancanti.

## Come leggere l'output

Nella cartella `--out` vengono creati:

| File | Contenuto |
|---|---|
| `quadri_facsimile.txt` | Facsimile leggibile dei tre quadri con i righi valorizzati |
| `report_2025.xlsx` | Report Excel **riga per riga** (ogni chiusura, dividendo, posizione) |
| `riepilogo_2025.pdf` | PDF riepilogativo |
| `rt_plusvalenze.csv`, `rm_dividendi.csv`, `rw_monitoraggio.csv` | Export CSV per quadro |
| `risultati.json` | Tutti i risultati in formato strutturato |

L'Excel è pensato **apposta per la validazione**: mostra per ogni operazione i cambi
usati, i valori in valuta e in euro e il dettaglio del calcolo, così ogni numero finale
è ricostruibile a mano.

La cartella `out_demo/` nel repository contiene un **esempio di output** generato su dati
fittizi, per vedere il formato senza dover eseguire nulla.

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

Principi che aiutano la lettura e la validazione:

- **gli importi restano sempre in valuta originale** fino ai motori, che li convertono in
  euro con i cambi ufficiali: la base currency di IBKR non viene mai usata;
- **ogni scelta fiscale incerta è in un unico posto** (`config.py`) e genera un warning
  (`warnings.py`);
- **ogni motore ha una docstring** che spiega la regola fiscale applicata e la convenzione
  sui righi del quadro.

## Mappa: regola fiscale → dove è implementata

Per chi vuole verificare che il codice faccia davvero ciò che dichiara, ecco dove cercare
ciascuna regola:

| Regola fiscale | File · funzione principale |
|---|---|
| Lettura del Flex Query XML di IBKR (validazione colonne, dedup ID/hash, warning anti-drop) | `parsing/flex_parser.py` · `load`, `parse_file` |
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

## Test

```bash
python -m pytest -q
```

I test (58) verificano i casi limite contro valori calcolati a mano: LIFO multi-lotto e
short, costo medio ponderato OICR, separazione plus OICR / minus in RT, dividendo con
ritenuta (lordo/netto), IVAFE pro-rata e soglia 200 €, titolo comprato e venduto nello
stesso anno, cambi con fallback su giorni festivi, validazioni d'ingresso e dedup.

## Riferimenti normativi

- Monitoraggio RW: art. 4 D.L. 167/1990 — IVAFE: art. 19 D.L. 201/2011 (aliquota 2‰
  ordinaria; 4‰ solo black list dal 2024, art. 1 c. 91 lett. b L. 213/2023).
- Plusvalenze: artt. 67–68 TUIR — LIFO: art. 67 c.1-bis TUIR — commissioni: art. 68
  c. 6 TUIR — plusvalenze in valuta estera: Risposta AdE n. 344/2020 (incipit
  specifico su valute; non la base della deducibilità commissioni).
- Quote OICR/ETF: plusvalenza = reddito di capitale (art. 44 c. 1 lett. g TUIR);
  costo medio ponderato; minus solo verso redditi diversi.
- Redditi di capitale: artt. 18 e 44 TUIR — credito d'imposta estero: art. 165 TUIR —
  lordo frontiera: istruzioni rigo RM31 col. 3 e Risposta AdE n. 111/2020 —
  cedole titoli di Stato 12,5%: art. 31 DPR 601/1973 e D.L. 138/2011.
- Cambi: cambio del giorno per RT/RM, medio mensile per RW (Circ. AdE 38/E/2013);
  tassi di riferimento Banca d'Italia.

L'elenco completo e commentato dei riferimenti, con i link alle fonti ufficiali, è in
[`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md).

> I **numeri di rigo** dei quadri (RT21, RM31, ecc.) e le **istruzioni** vanno sempre
> verificati sulle **istruzioni ministeriali dell'anno d'imposta**, perché cambiano di
> anno in anno.
