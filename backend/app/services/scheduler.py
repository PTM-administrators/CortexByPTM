"""
Loop in background che fa scattare da solo i controlli periodici di Cortex
(vedi services/notifiche.py) — richiesta esplicita dell'utente il 18 agosto
2026 ("Cortex di per sé non fa nulla": tutto, Segnalazioni comprese
nonostante il nome "proattive", scattava solo aprendo una pagina o scrivendo
in chat). Avviato una sola volta all'avvio del server (vedi main.py,
lifespan) e vive per tutta la vita del processo.

Intervallo di 30 minuti scelto con l'utente il 18 agosto 2026: abbastanza
reattivo da sembrare "vivo", non così frequente da intasare la casella per
una condizione che resta vera a lungo (una segnalazione già notificata non
si ripete finché non cambia, vedi models.NotificaInviata). Lo stesso ciclo
controlla anche se è ora del riepilogo mattutino — la funzione stessa decide
se è già stato mandato oggi, non serve un secondo timer.
"""
import asyncio
import logging

from app.database import SessionLocal
from app.services import notifiche

logger = logging.getLogger("cortex.scheduler")

INTERVALLO_SECONDI = 30 * 60


def esegui_ciclo() -> tuple[int, int]:
    """Un giro di controllo, sincrono — separata dal loop asyncio per poter
    essere richiamata anche da uno script di verifica manuale, senza dover
    aspettare l'intervallo reale."""
    db = SessionLocal()
    try:
        segnalazioni_inviate = notifiche.controlla_segnalazioni(db)
        riepiloghi_inviati = notifiche.invia_riepilogo_mattutino(db)
        return segnalazioni_inviate, riepiloghi_inviati
    finally:
        db.close()


async def loop_controllo() -> None:
    while True:
        try:
            segnalazioni, riepiloghi = esegui_ciclo()
            if segnalazioni or riepiloghi:
                logger.info(
                    "Ciclo automatico: %s email di segnalazione, %s riepiloghi mattutini",
                    segnalazioni,
                    riepiloghi,
                )
        except Exception:
            logger.exception("Ciclo di controllo automatico fallito, riprovo al prossimo giro")
        await asyncio.sleep(INTERVALLO_SECONDI)
