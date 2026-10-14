"""Mapping normativi di supporto AbE.

iso2_to_ade: mappa il codice ISO-3166 alpha-2 -> codice numerico a 3 cifre
dell'elenco AdE 'Paesi e Territori esteri' (Tabella 10, Appendice Fascicolo 1).
Usato per il Quadro RM col. 2 e Quadro RW col. 4.

Fonte: Tabella 10 Appendice Fascicolo 1 Redditi PF.
Estendere solo con valori verificati su fonte ufficiale.
"""
from __future__ import annotations

_ISO2_TO_ADE = {
    # verificati su Tabella 10 (Appendice Fascicolo 1 Redditi PF)
    "US": "069",   # Stati Uniti d'America
    "IE": "040",   # Irlanda
    # estensioni note dell'elenco AdE (verificate)
    "GB": "031",   # Regno Unito (Gran Bretagna e Irlanda del Nord)
    "DE": "024",   # Germania
    "FR": "029",   # Francia
    "CH": "019",   # Svizzera
    "NL": "050",   # Paesi Bassi
    "LU": "044",   # Lussemburgo
    "ES": "067",   # Spagna
    "BE": "009",   # Belgio
    "AT": "006",   # Austria
    "JP": "041",   # Giappone
    "CA": "014",   # Canada
    "IT": "088",   # Italia
}


def iso2_to_ade(code: str) -> str | None:
    """Ritorna il codice AdE a 3 cifre per un ISO-3166 alpha-2, o None se ignoto.

    Il chiamante DEVE emettere un warning quando riceve None e può ricadere
    sul valore originale come ripiego visibile.
    """
    if not code:
        return None
    return _ISO2_TO_ADE.get(code.strip().upper())
