# Come funziona la tassazione — meccanismi, esempi e glossario

Questa guida spiega in linguaggio semplice i meccanismi di tassazione italiana sui
redditi finanziari esteri: quelli che `fiscoib` applica e che incontra chiunque investa
con un conto estero (es. Interactive Brokers) in **regime dichiarativo**. Non richiede
competenze tecniche: ogni meccanismo ha un esempio numerico e i termini tecnici sono
nel [glossario](#7-glossario).

- **Fonti ufficiali:** ogni sezione cita le norme pertinenti; i link alle fonti
  primarie (Agenzia delle Entrate, Normattiva, Banca d'Italia) sono raccolti in
  [`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md).
- **Uso del programma** (installazione, opzioni, output): [`README.md`](README.md).

> ⚠️ Guida a scopo illustrativo: **non sostituisce il parere di un professionista**.
> Dove la norma non è univoca il programma adotta l'interpretazione più prudente e la
> segnala con un *warning* (vedi [§6](#6-i-casi-incerti-e-i-default-prudenti)).

---

## Indice

1. [Il quadro generale](#1-il-quadro-generale)
2. [Plusvalenze e minusvalenze (Quadro RT)](#2-plusvalenze-e-minusvalenze-quadro-rt)
3. [Dividendi e interessi (Quadro RM)](#3-dividendi-e-interessi-quadro-rm)
4. [Attività estere: monitoraggio e IVAFE (Quadro RW)](#4-attività-estere-monitoraggio-e-ivafe-quadro-rw)
5. [I cambi valuta](#5-i-cambi-valuta)
6. [I casi incerti e i default prudenti](#6-i-casi-incerti-e-i-default-prudenti)
7. [Glossario](#7-glossario)

---

## 1. Il quadro generale

Chi investe con un broker estero deve ogni anno compilare tre quadri distinti, perché
la legge italiana tratta in modo diverso tre fatti diversi:

| Cosa è successo | Cosa si dichiara | Quadro | Tassazione |
|---|---|---|---|
| Hai **venduto** un titolo con guadagno (o perdita) | Plusvalenza / minusvalenza | **RT** | 26% sul guadagno netto |
| Hai **incassato** un dividendo o un interesse | Reddito di capitale | **RM** | 26% sull'incasso |
| **Detieni** attività all'estero | Monitoraggio + patrimoniale | **RW** | IVAFE 0,2% sul valore |

Tre regole da tenere a mente:

1. **Si tassa ciò che si realizza o si incassa**, non il semplice valore che sale o
   scende. Finché non vendi un titolo non c'è plusvalenza; finché non incassi un
   dividendo non c'è reddito.
2. **I quadri sono isolati tra loro.** Una minusvalenza (RT) **non** abbassa l'imposta
   sui dividendi (RM): sono regole del TUIR, non scelte del software.
3. **Tutto si converte in euro** ai cambi ufficiali della Banca d'Italia
   (vedi [§5](#5-i-cambi-valuta)).

**Perché serve un programma dedicato.** Il report di Interactive Brokers non è pronto
per il fisco italiano: calcola le plusvalenze col metodo FIFO (l'Italia impone il
**LIFO**, almeno per azioni e CFD), è espresso in valuta estera (servono i **cambi
ufficiali** giorno per giorno) e non applica le regole del TUIR. I suoi numeri di
plus/minus quindi **non sono utilizzabili** e vanno ricostruiti da zero: è quello che
fa `fiscoib`, mostrando riga per riga come arriva a ogni valore.

---

## 2. Plusvalenze e minusvalenze (Quadro RT)

### Che cosa sono

La **plusvalenza** è il guadagno realizzato vendendo un titolo a più di quanto era
costato (comprese le commissioni); la **minusvalenza** è la perdita realizzata
vendendolo a meno. Nascono solo con la vendita ("realizzo"): il valore del titolo a
fine anno non conta.

### Il metodo LIFO

Se hai comprato lo stesso titolo in momenti diversi, alla vendita devi decidere
**quali** quote hai venduto. L'Italia impone il metodo **LIFO**: si considerano cedute
per prime le quote comprate **più di recente** (art. 67 c. 1-bis TUIR). Interactive
Brokers usa invece il FIFO, quindi il suo risultato va ignorato.

**Esempio (LIFO vs FIFO).** Compri 100 azioni a 150 € il 1° marzo e altre 50 a 180 €
il 15 luglio; il 20 settembre vendi 120 azioni a 200 € (commissioni omesse per
semplicità):

```
LIFO (regola italiana):
  corrispettivo venduto = 120 × 200            = 24.000 €
  costo fiscalmente rilevante = 50 × 180 + 70 × 150 = 19.500 €
  plusvalenza = 24.000 − 19.500                =  4.500 €

Con il FIFO di IBKR (100 × 150 + 20 × 180 = 18.600 €) la plusvalenza sarebbe 5.400 €:
diverse, e quella che va in dichiarazione è solo la prima.
```

> Nota interpretativa: per le azioni le istruzioni ministeriali richiamano anche il
> costo medio di carico (art. 68 c. 6 TUIR); il criterio prevalente resta il LIFO ed è
> quello adottato dal programma. Posizione da monitorare anno per anno.

### La formula

```
RT21  Corrispettivi = prezzo di vendita
RT22  Costi         = prezzo di acquisto + TUTTE le commissioni (acquisto e vendita)
      Differenza    = RT21 − RT22
```

- Le **commissioni** (oneri accessori) sono interamente deducibili: entrano nei costi
  (art. 68 c. 6 TUIR), incluse quelle di vendita.
- Gli **interessi passivi / di margine** (es. interessi su prestiti del broker per il
  trading con leva) **non sono deducibili** per la persona fisica e non entrano nel
  calcolo: il programma li ignora con una nota.

**Esempio.** Compri 10 azioni a 100 € (commissione 5 €), le vendi a 130 €
(commissione 5 €):

```
RT21 = 10 × 130 = 1.300 €   RT22 = 10 × 100 + 5 + 5 = 1.010 €
Plusvalenza = 290 €   →   Imposta 26% = 75,40 €
```

### Cosa succede al saldo dell'anno

Si sommano algebricamente tutte le plusvalenze e minusvalenze realizzate nell'anno:

| Situazione | Conseguenza |
|---|---|
| Saldo **positivo** | Si sottraggono le minusvalenze pregresse e si paga il 26% sul risultato (righi RT26–RT27) |
| Saldo **negativo** | È una **minusvalenza dell'anno**: riportabile nei 4 anni successivi, altrimenti si perde |

Le **minusvalenze pregresse** si possono usare nei **4 anni** successivi a quello in
cui sono state realizzate e si consumano partendo dalle più vecchie, così non scadono.
Vanno passate al programma con `--prior-losses` e devono risultare da dichiarazioni
precedenti: se non sono mai state dichiarate, non esistono.

**Esempio.** Saldo 2025: plusvalenze nette 5.000 €; minusvalenze pregresse dichiarate:
3.000 € dal 2023.

```
Imponibile = 5.000 − 3.000 = 2.000 €
Imposta 26% = 520 €   (versata col modello F24, codice tributo 1100)
Se il saldo 2025 fosse stato −1.000 €: niente imposta; 1.000 € di minusvalenza
riportabile fino al 2029.
```

### Eccezione: ETF e fondi (quote OICR)

Per le quote di organismi di investimento collettivo (ETF e fondi) valgono regole
diverse dalle azioni:

| Aspetto | Azioni e CFD | Quote OICR (ETF/fondi) |
|---|---|---|
| Costo fiscalmente rilevante | LIFO | **Costo medio ponderato** |
| Plusvalenza | Reddito diverso (RT), compensabile | **Reddito di capitale** al 26%: **mai** compensabile con minusvalenze |
| Minusvalenza | Reddito diverso (RT) | Reddito diverso: resta nel Quadro RT e compensa solo redditi diversi |

L'asimmetria è voluta dalla norma (art. 44 c. 1 lett. g TUIR, letta con la Risposta
AdE 157/2018): la plusvalenza su ETF **non si può abbattere** nemmeno se hai
minusvalenze disponibili. Il programma riconosce gli strumenti OICR e scorpora le plus
automaticamente: il Quadro RT risultante contiene solo redditi diversi (azioni, CFD
ecc.), mentre le plus OICR compaiono a parte come componente dedicata.

**Esempio (costo medio ponderato).** Compri 10 quote di un ETF a 100 € e poi 10 quote
a 120 €; vendi 10 quote a 130 €:

```
Costo medio = (10 × 100 + 10 × 120) / 20 = 110 €
Plusvalenza = 10 × (130 − 110) = 200 €  →  reddito di capitale, imposta 26% = 52 €
(non compensabile con eventuali minusvalenze in sospeso)
```

### Pro-rata titoli di Stato negli ETF obbligazionari (aliquota effettiva)

Se l'ETF investe in obbligazioni, i risultati del fondo **non** sono tassati tutti al
26% né tutti al 12,5%: partecipano dell'aliquota ridotta del 12,5% in proporzione alla
**quota media di titoli di Stato italiani ed esteri "white list"** detenuti dal fondo
durante il *tuo* periodo di possesso (art. 2, comma 1-quater, D.L. 138/2011; Circolare
AdE 19/E/2014):

```
Aliquota effettiva = 26% − 13,5% × quota media govies white list
```

| Quota govies del fondo | Aliquota effettiva |
|---|---|
| 100% (ETF solo BTP/white list) | 12,50% |
| 70% | 16,55% |
| 50% | 19,25% |
| 30% | 21,95% |
| 0% (solo corporate) | 26,00% |

Vale sia per le **plusvalenze da vendita** sia per le **distribuzioni** del fondo: sono
entrambe "risultati maturati" dell'OICR. La componente corporate (e i govies *non* white
list, es. emergenti fuori lista) resta sempre al 26%.

**Come fornire il dato al programma.** La quota media non è nello statement IBKR:
è pubblicata dal gestore sul proprio portale fiscale (es. iShares, Vanguard). Il
comando `python -m fiscoib.build_inputs estratto.xml --anno 2024` genera lo scheletro
`fund_gov_quota.bozza.json` con tutti gli ETF/fondi rilevati nello statement: occorre
solo riempire le quote. Il file si passa poi con `--fund-gov-quota`:

```json
{
  "IE00B4L5Y983": {"2023": 0.55, "2024": 0.58},
  "IE00B3RBWM25": 0.575
}
```

- Chiave = ISIN, simbolo o conid IBKR del fondo (basta uno che combaci).
- Forma estesa: quota media **per anno solare**; sul tuo periodo di possesso il
  programma calcola la media pesata sui giorni di ogni anno.
- Forma breve (un solo numero): quota trattata come costante per qualunque periodo.

**Convenzioni prudenti del programma** (mai meno imposta del dovuto in caso di dato
mancante):

- anni del possesso **non coperti** dal file → conteggiati con quota 0 sulle frazioni
  di periodo corrispondenti + warning `PRORATA_ANNI_PARZIALI`;
- fondo assente dal file (o file non passato) → aliquota piena 26% + warning
  `PRORATA_DA_CLASSIFICARE`;
- per gli ETF il periodo di possesso considerato è [primo acquisto, vendita] del lotto
  a costo medio ponderato;
- per le distribuzioni, il cui periodo di maturazione non è noto, si usa la quota
  media dell'anno solare di pagamento.

**Esempio.** Vendi un ETF obbligazionario misto in gain di 2.000 €, detenuto dal
1° luglio 2024 al 30 giugno 2025; quota govies media 2024 = 40%, 2025 = 60%:

```
Giorni 2024 = 184, giorni 2025 = 181
Quota media = (0,40 × 184 + 0,60 × 181) / 365 = 49,92%
Aliquota effettiva = 26% − 13,5% × 49,92% = 19,26%
Imposta = 2.000 × 19,26% = 385,22 €   (vs 520 € al 26% pieno: risparmio 134,78 €)
```

Nel report la quota e l'aliquota effettiva sono esposte riga per riga (facsimile,
foglio `OICR_RedditoCapitale` e CSV `rm_oicr_guadagni.csv`), così il dato è
verificabile contro quello pubblicato dal gestore.

### Normativa

Artt. 67 e 68 TUIR (redditi diversi, LIFO, costi e oneri accessori, riporto delle
minusvalenze nei 4 anni); art. 44 c. 1 lett. g TUIR e Risposta AdE 157/2018 (quote
OICR); art. 2 c. 1-quater D.L. 138/2011 e Circolare AdE 19/E/2014 (pro-rata titoli
di Stato negli OICR); Risposta AdE 344/2020 (conversione in euro operazione per
operazione). Fonti e link: [`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md),
sezione 1.

---

## 3. Dividendi e interessi (Quadro RM)

### La regola base

Dividendi esteri e interessi attivi sono **redditi di capitale**: si tassano al **26%**
su quanto **incassato nell'anno**. Vale il principio di cassa: conta la data del
pagamento, non quella di maturazione. Non si compensano con le minusvalenze.

### Il punto delicato: il "frontiera" dei dividendi esteri

Sul dividendo estero lo Stato estero applica già una **ritenuta alla fonte** (WHT: ad
esempio il 15% per gli USA). Poi c'è il 26% italiano. La domanda è: il 26% si calcola
sul dividendo **lordo** o su quello **netto** della ritenuta estera?

| Metodo | Base del 26% | Chi lo sostiene | Default |
|---|---|---|---|
| **Lordo** | dividendo pieno | Agenzia delle Entrate | ✅ (`--frontiera lordo`) |
| **Netto** | dividendo − ritenuta estera | giurisprudenza, più favorevole ma contestato | opzionale (`--frontiera netto`) |

**Esempio.** Dividendo lordo 100 €, ritenuta estera 15 € (incassi 85 €):

| Metodo | Base imponibile | Imposta italiana 26% |
|---|---|---|
| Lordo (default) | 100 € | 26 € |
| Netto | 85 € | 22,10 € |

### La ritenuta estera e il credito d'imposta

Nel regime a imposta sostitutiva il **credito per le imposte pagate all'estero non è
scomputabile** in dichiarazione (posizione dell'Agenzia delle Entrate, art. 165 TUIR).
La giurisprudenza di legittimità è però favorevole al riconoscimento del credito
(Cass. 25698/2022 e Cass. 10204/2024). Il programma lo calcola solo come **importo
teorico informativo**, da valutare con un professionista per un'eventuale istanza di
rimborso (esito incerto).

### Tipi di reddito e aliquote: le lettere del rigo RM31

Dividendi e interessi si distinguono per "tipo di reddito" (lettera del rigo):

| Lettera | Contenuto | Aliquota |
|---|---|---|
| **A** | Cedole di titoli di Stato italiani ed esteri in *white list* e di organismi sovranazionali | **12,5%** |
| **C** | Altri redditi di capitale (es. *Payment In Lieu*, se trattato in RM) | 26% |
| **G** | Interessi attivi su liquidità / deposito | 26% |
| **H** | Dividendi e utili esteri; **plusvalenze su quote OICR** (vedi §2) | 26% (= aliquota effettiva se ETF con pro-rata govies) |
| **I** | Cedole di obbligazioni societarie e altri bond | 26% |

- Il **12,5%** si applica solo se l'emittente è nella lista fornita con `--gov-bonds`
  (ISIN/simboli di titoli di Stato): senza lista, ogni emittente obbligazionario viene
  tassato al 26% con un warning da verificare.
- Gli **interessi passivi / di margine** non sono deducibili: il programma li ignora
  con una nota.

**Esempio (cedola di Stato vs corporate).** Incassi una cedola di 100 € da un BTP e
100 € da un bond societario:

```
Cedola BTP (lettera A, se in white list): 100 × 12,5% = 12,50 €
Cedola corporate (lettera I):                      100 × 26%   = 26,00 €
```

### Dove va in dichiarazione

Rigo **RM31**, Sezione II-A del Modello Redditi PF. Nel **Modello 730** lo stesso
contenuto va nel **Quadro M, rigo M31** (stesse lettere e colonne). L'imposta si versa
col modello **F24, codice tributo 1242**.

### Normativa

Artt. 18 e 44 TUIR (redditi di capitale); art. 45 c. 1 TUIR (cambio del giorno
d'incasso); art. 25 DPR 600/1973 (principio di cassa); art. 165 TUIR (credito
d'imposta estero); art. 31 DPR 601/1973 e D.L. 138/2011 (cedole di Stato al 12,5%);
Risposta AdE 111/2020 (base lordo frontiera). Fonti e link:
[`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md), sezione 2.

---

## 4. Attività estere: monitoraggio e IVAFE (Quadro RW)

### L'obbligo di monitoraggio

Vanno dichiarate **tutte** le attività estere detenute nell'anno, anche se in perdita o
mai movimentate. È un obbligo di **segnalazione**, distinto dal pagamento dell'imposta:
l'omessa compilazione del Quadro RW comporta sanzioni dal 3% al 15% del valore (6%–30%
se lo Stato è a fiscalità privilegiata).

### L'IVAFE

L'IVAFE è l'imposta patrimoniale sui prodotti finanziari esteri: **0,2% annuo** sul
valore (0,4% solo per le attività in Stati a fiscalità privilegiata, dal 2024). Si
calcola in modo **proporzionale al periodo e alla quota di possesso**:

```
IVAFE = valore_finale_EUR × 0,2% × (giorni di possesso / 365) × (quota di possesso / 100)
```

**Esempio.** ETF dal valore di 20.000 € acquistato il 1° luglio (184 giorni di
possesso), conto cointestato al 50%:

```
IVAFE = 20.000 × 0,2% × 184/365 × 50% ≈ 10,08 €
```

**Soglia dei 200 €.** Se l'IVAFE complessiva dell'anno **non supera 200 € il
versamento non è dovuto**, ma il Quadro RW si compila comunque a solo monitoraggio. Il
prospetto del programma distingue sempre *IVAFE teorica* da *IVAFE da versare*.

**Esempio.** 50.000 USD di azioni detenute tutto l'anno, quota 100%, cambio medio di
dicembre 1,0479 (1 EUR = 1,0479 USD):

```
Valore finale = 50.000 / 1,0479 ≈ 47.714 €
IVAFE = 47.714 × 0,2% ≈ 95,43 €   →   ≤ 200 €: compilazione RW sì, versamento no
```

### Come si valuta

La valorizzazione usa il **cambio medio mensile** (non quello giornaliero) del mese di
riferimento:

| Situazione | Valore usato |
|---|---|
| Titolo in portafoglio al 31/12 | Valore di mercato al 31/12 |
| Titolo venduto durante l'anno | Valore all'ultima vendita |
| Valore iniziale | Valore al 1/1 se già detenuto, altrimenti valore di acquisto |

Nel quadro lo Stato estero si indica con il **codice numerico AdE a 3 cifre**
(es. US = 069, IE = 040), affiancato al codice ISO. Il **codice bene** (colonna 3)
identifica la natura dell'attività:

| Codice | Tipo di attività |
|---|---|
| **20** | Conto deposito titoli estero (azioni quotate e liquidità) |
| **2** | Partecipazioni non quotate (azioni OTC) |
| **9** | Contratti derivati / rapporti finanziari (CFD) |

### Nota: i conti correnti esteri

Per i conti correnti esteri (diversi dal deposito titoli) è dovuta un'**imposta fissa
di 34,20 €**, con franchigia se la giacenza media annua non supera 5.000 €. `fiscoib`
non calcola questa voce: va gestita a parte.

### Normativa

Art. 4 D.L. 167/1990 (monitoraggio) e art. 5 (sanzioni); art. 19 D.L. 201/2011 (IVAFE:
aliquota 2‰, valorizzazione, pro-rata, soglia 200 €); L. 213/2023 (4‰ solo black
list); Circolare AdE 38/E/2013 (cambio medio mensile). Fonti e link:
[`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md), sezione 3.

---

## 5. I cambi valuta

Gli importi in valuta estera si convertono in euro con cambi diversi a seconda del
quadro, come impone l'Agenzia delle Entrate:

| Quadro | Cambio da usare | Quando |
|---|---|---|
| **RT** e **RM** | **Riferimento giornaliero** | Data dell'operazione / del pagamento |
| **RW / IVAFE** | **Medio mensile** | Mese di determinazione del valore (dicembre per i valori al 31/12) |

- La fonte è la **Banca d'Italia**; il programma scarica i tassi e li memorizza in una
  cache locale, recuperando solo le date mancanti. Se un giorno non ha cambio (festivo),
  usa l'ultimo disponibile precedente.
- I cambi medi mensili ufficiali AdE possono essere inseriti a mano
  (`--overrides`); il programma ne ha alcuni già integrati.
- **Convenzione del tasso**: indica *quante unità di valuta estera valgono 1 EUR*
  (es. EUR/USD ≈ 1,08), quindi `euro = importo_estero / tasso`.
- Il campo `fxRateToBase` del file IBKR **non** è fiscalmente valido e non viene usato.

**Esempio.** Dividendo di 200 USD pagato il 4 aprile, cambio Banca d'Italia del giorno
EUR/USD = 1,0850:

```
Controvalore = 200 / 1,0850 ≈ 184,33 €  →  base su cui si calcola il 26%
```

### Normativa

Provvedimento AdE 98668/2020 (pubblicazione cambi ai fini fiscali); Circolare AdE
38/E/2013 (cambio medio mensile per il Quadro RW). Fonti e link:
[`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md), sezione 4.

---

## 6. I casi incerti e i default prudenti

Su alcuni punti la normativa non è univoca. Il programma adotta l'interpretazione più
prudente/difendibile, la segnala con un *warning* e permette di cambiarla da riga di
comando:

| Caso incerto | Default prudente | Opzione per cambiarlo |
|---|---|---|
| Base imponibile dei dividendi esteri | **Lordo** frontiera (posizione AdE) | `--frontiera netto` |
| IVAFE su CFD | Solo monitoraggio, IVAFE non applicata | `--ivafe-cfd` |
| IVAFE su azioni OTC | Solo monitoraggio | `--ivafe-otc` |
| Rettifica dividendi (*dividend adjustment*) su CFD | Redditi diversi (Quadro RT) | `--cfd-divadj RM` |
| Dividendo sostitutivo su titoli prestati (*Payment In Lieu*) | Reddito di capitale (Quadro RM) | `--pil RT` |

Il dettaglio dei singoli casi è nelle sezioni 2–4 di questa guida; le stesse scelte,
con i loro effetti, sono concentrate nel codice in `fiscoib/config.py`.

---

## 7. Glossario

**Aliquota sostitutiva** — Imposta piatta applicata ai redditi finanziari al posto
dell'IRPEF progressiva. Per RT e RM è il 26%.

**CFD (Contract for Difference)** — Contratto differenziale: strumento derivato che
replica l'andamento di un titolo senza possederlo. Plus/minus in RT (redditi diversi);
nel Quadro RW ha il codice bene 9.

**Codice bene (RW)** — Numero che identifica la natura dell'attività nel Quadro RW:
20 = deposito titoli estero, 2 = partecipazione non quotata, 9 = derivato/rapporto
finanziario.

**Codice tributo** — Codice che identifica la voce da pagare nel modello F24. Per
questo strumento: **1100** (imposta sulle plusvalenze, Quadro RT) e **1242** (redditi
di capitale esteri, Quadro RM).

**Costo medio ponderato** — Costo unitario medio degli acquisti, pesato sulle
quantità. Si usa per le quote OICR (ETF, fondi), non per le azioni.

**Credito d'imposta estero** — Imposta pagata all'estero che in teoria si potrebbe
recuperare. In regime di imposta sostitutiva non è scomputabile in dichiarazione
(posizione AdE): il software la espone solo come importo teorico.

**Dividend adjustment (CFD)** — Rettifica che il broker applica a un CFD quando il
titolo sottostante stacca un dividendo. Trattamento di default: redditi diversi (RT).

**Dividendo** — Parte dell'utile di una società distribuita agli azionisti. Reddito di
capitale (Quadro RM), 26%.

**F24** — Modello con cui si pagano le imposte. Codici usati: 1100 (RT), 1242 (RM).

**Flex Query** — Formato di report personalizzabile di Interactive Brokers (file XML)
che il programma legge.

**Frontiera (lordo / netto)** — Criterio con cui si calcola il 26% sul dividendo
estero: sul **lordo** (dividendo pieno, posizione AdE) o sul **netto** della ritenuta
estera (più favorevole, contestato).

**Interessi passivi / di margine** — Interessi pagati su somme prese a prestito dal
broker per il trading con leva. Non deducibili per la persona fisica: non riducono le
plusvalenze.

**IVAFE** — Imposta sul Valore delle Attività Finanziarie Estere: patrimoniale annua
dello 0,2% (0,4% per i paesi a fiscalità privilegiata) sul valore delle attività
estere, pro-rata su giorni e quota di possesso. Non dovuta se complessiva ≤ 200 €.

**LIFO (Last In, First Out)** — Metodo imposto dall'Italia per i lotti di azioni: alla
vendita si considerano cedute per prime le quote acquistate più di recente. IBKR usa il
FIFO: per questo i suoi numeri non bastano e il ricalcolo è necessario.

**Minusvalenza** — Perdita realizzata vendendo un titolo a meno del suo costo
fiscalmente rilevante.

**Minusvalenze pregresse** — Minusvalenze degli anni precedenti: riducono le
plusvalenze dei **4 anni** successivi, consumandosi prima le più vecchie. Se non
indicate in dichiarazione si perdono.

**Monitoraggio fiscale** — Obbligo di dichiarare nel Quadro RW le attività detenute
all'estero, anche se non producono reddito. Distinto dal pagamento dell'IVAFE.

**OICR** — Organismo di Investimento Collettivo del Risparmio: fondi comuni ed ETF.
Regime diverso dalle azioni: costo medio ponderato; plusvalenza = reddito di capitale
non compensabile.

**Pro-rata titoli di Stato (OICR)** — Riduzione dell'aliquota sui risultati di un
ETF/fondo in proporzione alla quota media di titoli di Stato white list nel fondo:
aliquota effettiva = 26% − 13,5% × quota govies (art. 2 c. 1-quater D.L. 138/2011).
Dato da un file JSON (`--fund-gov-quota`), perché non presente nello statement IBKR
(vedi §2).

**Oneri accessori** — Commissioni e spese collegate all'operazione di acquisto o
vendita. Deducibili: aumentano il costo fiscalmente rilevante.

**Payment In Lieu of Dividends (PIL)** — "Dividendo sostitutivo" pagato a chi presta i
propri titoli. Trattamento di default: reddito di capitale (RM).

**Plusvalenza** — Guadagno realizzato vendendo un titolo a più del suo costo
fiscalmente rilevante.

**Principio di cassa** — Regola dei redditi di capitale (RM): il reddito si tassa
nell'anno in cui viene **incassato**, non in cui matura.

**Pro-rata** — Frazione di anno proporzionale ai giorni di possesso
(`giorni di possesso / 365`), usata nell'IVAFE.

**Quadro RM** — Sezione della dichiarazione per i redditi di capitale esteri
(dividendi e interessi), rigo RM31, imposta 26%.

**Quadro RT** — Sezione della dichiarazione per plusvalenze e minusvalenze finanziarie
(redditi diversi), imposta 26%.

**Quadro RW** — Sezione della dichiarazione per il monitoraggio delle attività estere
e l'IVAFE.

**Quota di possesso** — Percentuale dell'attività effettivamente posseduta (es. 50%
per un conto cointestato). Riduce proporzionalmente l'IVAFE.

**Realizzo** — Il verificarsi della plusvalenza/minusvalenza con la vendita. Finché il
titolo non è venduto, il guadagno è solo "sulla carta" e non si tassa.

**Redditi di capitale** — Redditi da impiego di denaro o titoli (dividendi, interessi,
plusvalenze su OICR). Quadro RM, 26%, non compensabili con le minusvalenze.

**Redditi diversi** — Redditi da operazioni speculative (compravendita di azioni,
CFD). Quadro RT, 26%, con compensazione di plus e minus.

**Regime dichiarativo** — Il contribuente stesso calcola e dichiara le imposte a fine
anno (a differenza del regime amministrato, in cui provvede la banca). È il presupposto
di questo software.

**Ritenuta alla fonte (WHT — Withholding Tax)** — Imposta trattenuta dallo Stato
estero sul reddito al momento del pagamento, prima che arrivi al contribuente.

**Soglia dei 200 €** — Sotto questa soglia l'IVAFE complessiva non si versa, ma il
Quadro RW va compilato lo stesso.

**Stati a fiscalità privilegiata (black list)** — Paesi con regimi fiscali
particolarmente favorevoli: IVAFE al 0,4% e sanzioni per omesso monitoraggio
raddoppiate.

**White list** — Elenco dei paesi con scambio di informazioni adeguato con l'Italia:
le cedole dei loro titoli di Stato sono tassate al 12,5%.

---

## Nota finale

I **numeri di rigo** (RT21, RM31…) e le istruzioni ministeriali vanno sempre verificati
sulle istruzioni dell'anno d'imposta effettivo, perché cambiano di anno in anno.
L'elenco completo e commentato dei riferimenti normativi, con link alle fonti
ufficiali, è in [`NORMATIVA_RIFERIMENTI.md`](NORMATIVA_RIFERIMENTI.md).
