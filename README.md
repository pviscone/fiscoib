# fiscoib — Calcolo fiscale Interactive Brokers → Quadro RW / RT / RM

Strumento a riga di comando che, a partire dal report **Flex Query XML** di
Interactive Brokers, calcola per un residente fiscale italiano in **regime
dichiarativo**:

- **Quadro RT** — plusvalenze/minusvalenze su azioni (quotate e OTC) e CFD, con
  metodo **LIFO** e conversione ai cambi ufficiali del giorno (imposta 26%).
- **Quadro RM** — dividendi esteri (lordo/netto frontiera), interessi attivi
  (imposta 26%).
- **Quadro RW / IVAFE** — monitoraggio delle attività estere e imposta 0,2%.

Produce: facsimile dei quadri, report **Excel** dettagliato, **PDF**
riepilogativo, ed export **CSV/JSON**.

> ⚠️ **AVVISO IMPORTANTE.** Questo software è uno strumento di supporto al calcolo
> e **non sostituisce un commercialista**. Numerosi trattamenti sono
> normativamente **incerti** (frontiera dividendi, IVAFE su CFD/OTC, dividend
> adjustment sui CFD, PIL da prestito titoli). I default sono prudenti e ogni caso
> dubbio genera un *warning*. **Verifica tutti i valori con un professionista**
> prima di presentare la dichiarazione.

---

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python -m fiscoib ESTRATTO.xml --anno 2025 --out ./out
```

Più file (storico pluriennale — necessario per il LIFO di titoli comprati in anni
diversi e per le minusvalenze riportabili):

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

Esempio `prior-losses.json`:

```json
{ "2023": 1500.00, "2022": 800.00 }
```

Esempio `overrides.json` (cambi medi mensili ufficiali AdE, 1 EUR = X valuta):

```json
[ { "currency": "USD", "year": 2025, "month": 12, "rate": 1.0512 } ]
```

---

## Come esportare il Flex Query da Interactive Brokers

1. **Client Portal** → *Performance & Reports* → *Flex Queries*.
2. Crea una **Activity Flex Query** (formato **XML**).
3. Includi almeno queste sezioni:
   - **Trades** (livello *Execution*)
   - **Cash Transactions** (Dividends, Payment In Lieu, Withholding Tax, Interest)
   - **Open Positions** (livello *Lot*, data al 31/12)
   - **Cash Report** (per valuta)
   - **Corporate Actions**
4. Periodo: una Activity Flex copre **max 365 giorni** per file. Per lo storico
   completo scarica **un file per anno** e passali tutti insieme al comando (il
   software li unisce e deduplica per `transactionID`).

I cambi ufficiali vengono scaricati automaticamente dalla **Banca d'Italia** e
salvati in una cache locale (`out/rates_cache.sqlite`): alle esecuzioni successive
si scaricano solo le date mancanti. Per il Quadro RW/IVAFE è integrata la tabella
dei cambi medi mensili ufficiali dell'Agenzia delle Entrate (estendibile via
`--overrides`).

---

## Cambi valuta — regole applicate

- **Plusvalenze (RT) e dividendi/interessi (RM)**: cambio di riferimento
  **giornaliero** Banca d'Italia/BCE alla data dell'operazione / pay date.
- **Quadro RW / IVAFE**: cambio **medio mensile** (dicembre per i valori al 31/12).
- Il campo `fxRateToBase` di IBKR **non** è fiscalmente valido e non viene usato.

## Test

```bash
python -m pytest tests/ -q
```

I test verificano i casi limite (LIFO multi-lotto, short, dividendo con ritenuta,
IVAFE pro-rata, titolo comprato e venduto in anno) contro valori calcolati a mano.

---

## Limitazioni note (da gestire in futuro)

- **Titoli trasferiti dentro IBKR senza storico di acquisto.** Il motore LIFO
  ricostruisce i lotti dai soli trade presenti nei file. Se una posizione è stata
  *trasferita* in IBKR da un altro intermediario (nessun trade di apertura nello
  storico), una successiva vendita genera un lotto **short "fantasma"** con
  plusvalenza errata, senza alcun avviso. Finché non si trasferiscono titoli non
  è un problema; in futuro andrà aggiunto un warning che intercetti gli short non
  spiegati su titoli azionari e/o il caricamento manuale del costo di carico
  storico.

---

## Riferimenti normativi principali

- Monitoraggio RW: art. 4 D.L. 167/1990; IVAFE: art. 19 D.L. 201/2011.
- Plusvalenze: artt. 67–68 TUIR; LIFO: art. 67 c.1-bis TUIR.
- Dividendi esteri: art. 18 TUIR; Interpello AdE 111/2020 (lordo frontiera).
- Cambi: art. 110 c.9 TUIR; cambi di riferimento Banca d'Italia.

I numeri di rigo dei quadri (RT21, RM31, ecc.) vanno sempre verificati sulle
**istruzioni ministeriali dell'anno d'imposta**, perché cambiano di anno in anno.
