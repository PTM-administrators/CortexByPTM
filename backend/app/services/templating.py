"""
Sostituzione {{colonna}} -> valore reale di una riga. Usata sia dalle azioni
per riga delle Viste salvate (api/views.py, es. il testo di un'email di
sollecito) sia dai messaggi delle Segnalazioni proattive
(services/alert_engine.py) — stessa sintassi in tutto il sistema, un solo
posto che la implementa.
"""
import re


def applica_template(template: str, riga: dict) -> str:
    """Taglia-incolla, non generazione: se la colonna non esiste nella riga
    lascia il segnaposto visibile invece di fallire silenziosamente."""

    def sostituisci(match: re.Match) -> str:
        chiave = match.group(1).strip()
        if chiave not in riga:
            return match.group(0)
        return str(riga[chiave])

    return re.sub(r"\{\{(.*?)\}\}", sostituisci, template or "")
