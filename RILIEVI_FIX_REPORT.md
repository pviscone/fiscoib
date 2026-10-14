# Report consolidato — audit fiscale e fix applicati

Data: 2026-10-14 · Suite test: **58/58 verdi** · Demo rigenerato in `out_demo/`
Fonti normative verificate: vedi `NORMATIVA_RIFERIMENTI.md`

L'audit ha coinvolto 5 agenti paralleli (motore plusvalenze, redditi+FX, RW/IVAFE,
parsing, config/report) con verifica online delle norme; le tesi in conflitto sono state
dirime direttamente sulle fonti primarie (Circolare AdE 3/E/2024, scheda IVAFE AdE).

---

## 1. Rettifica dell'audit: l'IVAFE NON era errorata

Il sospetto iniziale (config IVAFE 0,2% errata dal 2024) è stato **refutato sulle fonti
primarie**: la L. 213/2023 ha portato al 4 per mille solo i prodotti in Stati black list
(art. 1 c. 91 lett. b → comma 20-bis art. 19 D.L. 201/2011). **L'ordinaria resta 2‰.**
→ `config.py` era ed è corretta; il demo 2024 non andava rifatto per questo motivo.
Un agente aveva sostenuto il contrario citando l'inesistente "art. 24 c. 4" —
falso positivo dell'audit, scartato.

## 2. ERRORE STRUTTURALE corretto: ETF/OICR

**Prima**: LIFO su tutto, plus/minus OICR mescolati nel saldo RT compensabile.
**Ora** (`models.py`, `lots.py`, `capital_gains.py`):
- `Instrument.is_fund` (sub_category ETF / assetCategory FUND);
- OICR → **costo medio ponderato** (lotto aggregato progressivo), azioni → LIFO;
- gain OICR > 0 → scorporati in `RTResult.oicr_gains` (redditi di capitale, lettera H,
  26%, **mai compensati** con minus);
- loss OICR → restano in RT come redditi diversi (asimmetria corretta);
- SAME-day ordering: tie-breaker `openCloseIndicator`;
- `SHORT_SPURIO`: warning finale su lotti short inspiegati (titoli trasferiti senza
  storico) — prima promesso in un commento e mai implementato.

Test: ETF 2 prezzi → medio; isolamento plus OICR / minus in RT; short spurio segnalato;
azioni ancora LIFO.

## 3. Parsing: eliminati i drop silenziosi

| Rilievo | Fix in `flex_parser.py` |
|---|---|
| Colonne fiscali opzionali assenti → importi opachi a 0 | Validazione obbligatorie per sezione → errore esplicito |
| Dedup off se transactionID assenti | Warning CRITICAL `IDS_MANCANTI` + dedup per content-hash |
| Duplicati discordi scartati muti | `DUP_DISCORDANTE` con i due valori |
| OpenPosition duplicate cross-file (IVAFE doppia) | Dedup per tupla identificativa cross-file (+ CashReport) |
| TradeCancel scartate in silenzio | Warning CRITICAL `TRADE_CANCELLED` per riga |
| Date non parsabili → None muto | Warning `DATA_IMPVERSABILE` con contesto |
| buySell sconosciuti → drop muto | Prefissi con parentetici accettati; `BUY_SELL_SCONOSCIUTO` CRITICAL |

`pipeline.run` passa ora `warnings=warnings` a `load()` (integrazione completata).

## 4. Quadro RM (redditi di capitale)

- Titoli di Stato white list: **12,5% codice A** se ISIN/simbolo in `--gov-bonds`; altrimenti
  26% codice I e warning CRITICAL per emittente (`GOVBONDS_DA_CLASSIFICARE`).
- Lettere: gov `A`, corporate `I`, PIL `C`, dividendi `H`, interessi `G`.
- Codice paese AdE numerico (`country_ade`: US→069, IE→040; nuovo `ade_tables.py`).
- WHT: aggregazione algebrica (gestito reversal), match ±3 giorni, `WHT_SPAIATA` CRITICAL.
- Totali = somma dei q2 per riga (niente discrepanze centesimali).

## 5. Quadro RW / report / CLI

- **Soglia 200 €**: IVAFE ≤200 € → "VERSAMENTO NON DOVUTO" ed esclusa dal totale (teorica vs da versare, ovunque: facsimile/PDF/Excel/JSON).
- Codici tributo F24: RT **1100** aggiunto, RM 1242 confermato.
- Sanzioni dinamiche 3–15% vs 6–30% (config `account_is_blacklist`).
- Liquidità: codice valorizzazione '3' (nominale).
- Righe RW: `stato_estero_ade` numerico (fallback ISO + warning se ignoto).
- Header RW con aliquota da config (niente hardcode).
- Nota 730 → Quadro M rigo M31.
- CLI: `--stato` validato ISO-2, `--quota` 0–100, `--prior-losses` mancante → errore fatale, nuovo `--gov-bonds`, warning anno fuori range/zero eventi.

## 6. Documentazione

- README: retificate le citazioni inappropriate (interpello 344/2020 → art. 68 c.6 TUIR;
  111/2020 nella collocazione corretta), aggiunte sezioni OICR, 12,5% titoli di Stato,
  soglia 200 €, Quadro M/730, mappa implementazione aggiornata, tabella opzioni + `--gov-bonds`.
- `NORMATIVA_RIFERIMENTI.md`: link ufficiali per ogni istituto (RT, RM, RW/IVAFE, cambi, IBKR).

## 7. Rischi/residui noti (segnalati, non drop)

1. **`is_fund` euristica**: un ETF con metadati mancanti nel Flex cadrebbe nel ramo LIFO/RT — verificare nel report la classe di ogni strumento.
2. `SHORT_SPURIO` non distingue short intenzionale da storico mancante → verifica manuale.
3. Paese dei Bond Interest senza ISIN ricade su `config.account_country`.
4. Dibattito LIFO vs costo medio per **azioni pure**: criterio prevalente LIFO (tenuto), le istruzioni AdE richiamano anche il costo medio di art. 68 c. 6 — posizione da monitorare.
5. Credito d'imposta estero: posizione AdE (non scomputabile) vs Cass. 25698/2022 e 10204/2024 — il "credito teorico" esposto serve a quantificarlo; decisione del contribuente.
6. Override cambi mensili copre solo dicembre 2024; gli altri mesi usano il proxy BdI (verificato coincidente su dicembre, non garantito altrove).

## 8. Verifica finale eseguita

- `./.venv/bin/python -m pytest tests/ -q` → **58 passed** (era 24 prima dell'audit).
- Demo rigenerato: `out_demo/` ora mostra RT con tributo 1100, righe RM con codici AdE
  069/040 e lettere, IVAFE teorica €65,14 esplicitata **non dovuta** (≤200 €) ed esclusa
  dal totale, RW a 3 cifre AdE.
