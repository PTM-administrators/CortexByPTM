"""
Cortex che agisce da solo, senza che l'utente chieda nulla — la richiesta
esplicita dell'utente del 18 agosto 2026 ("Cortex di per sé non fa nulla"):
prima di questo, ogni funzione (Segnalazioni comprese, nonostante il nome)
scattava solo quando l'utente apriva una pagina o scriveva in chat.

Due controlli, entrambi richiamati a intervalli da app.services.scheduler:

- `controlla_segnalazioni`: valuta le regole già configurate (Segnalazioni,
  vedi alert_engine) su OGNI azienda, e manda un'email per ogni segnalazione
  NUOVA (mai notificata prima — vedi models.NotificaInviata). Una condizione
  che resta vera nel tempo non genera un'email ad ogni ciclo. Se la regola ha
  anche un template d'azione collegato (AlertRule.azione_template), prepara
  pure una bozza pronta (AzionePendente — vedi _prepara_azione_se_configurata)
  invece di limitarsi ad avvisare: il lavoro vero (es. il sollecito già
  scritto per un debitore scaduto), non solo la notifica che qualcosa va
  guardato — un amministratore la conferma con un click su Cortex, non deve
  scriverla da zero.
- `invia_riepilogo_mattutino`: un'email al giorno (non di più) con la
  liquidità attuale, per le aziende che hanno sia Gmail sia un database
  contabile collegati.

Entrambe usano l'integrazione Gmail/SMTP che l'azienda ha già collegato per
l'invio manuale (agent_brain/api/agent.py) — nessuna configurazione nuova:
un'azienda che non ha Gmail semplicemente non riceve notifiche (non è un
errore, e non viene ritentata a vuoto: vedi _integrazione_gmail).
"""
import json
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.models.alert_rule import AlertRule
from app.models.azione_pendente import AzionePendente
from app.models.integrations import Integration
from app.models.notifica_inviata import NotificaInviata
from app.models.organization import Organization
from app.services import accounting_engine, accounting_engine_arca, alert_engine, data_source
from app.services.integration_providers import find_first_database_integration
from app.services.templating import applica_template
from app.tools import email_tool

ORA_RIEPILOGO_MATTUTINO = 8  # ora locale del server: deciso con l'utente il 18 agosto 2026 ("ogni mattina")


def _integrazione_gmail(db: Session, organization_id: int) -> Integration | None:
    return (
        db.query(Integration)
        .filter(Integration.organization_id == organization_id, Integration.provider == "gmail")
        .order_by(Integration.created_at)
        .first()
    )


def _integrazione_contabile(db: Session, organization_id: int) -> Integration | None:
    """Prima integrazione database dell'azienda — stessa convenzione già
    usata da agent_brain._find_database_integration per visualize_tool."""
    return find_first_database_integration(db, organization_id)


def _gia_notificata(db: Session, organization_id: int, chiave: str) -> bool:
    return (
        db.query(NotificaInviata)
        .filter(NotificaInviata.organization_id == organization_id, NotificaInviata.chiave == chiave)
        .first()
        is not None
    )


def _segna_notificata(db: Session, organization_id: int, chiave: str) -> None:
    db.add(NotificaInviata(organization_id=organization_id, chiave=chiave))
    db.commit()


def _invia(gmail: Integration, subject: str, body: str) -> bool:
    """Manda a se stessa (l'indirizzo della stessa casella collegata):
    nessun destinatario separato da configurare, coerente con "nessuna
    configurazione nuova" — un errore SMTP reale (auth, connessione) non
    deve interrompere il ciclo per le altre aziende, solo questa notifica
    salta (verrà ritentata al prossimo ciclo, non essendo stata segnata)."""
    credenziali = decrypt_credentials(gmail.credentials)
    destinatario = credenziali.get("username", "")
    if not destinatario:
        return False
    try:
        email_tool.send_email(
            smtp_host=credenziali.get("smtp_host", ""),
            smtp_port=int(credenziali.get("smtp_port", 587) or 587),
            username=credenziali.get("username", ""),
            password=credenziali.get("password", ""),
            to_address=destinatario,
            subject=subject,
            body=body,
        )
        return True
    except Exception:
        return False


def controlla_segnalazioni(db: Session) -> int:
    """Ritorna quante email sono state inviate (usato per verifica/log)."""
    regole = db.query(AlertRule).filter(AlertRule.attiva.is_(True)).all()
    regole_per_org: dict[int, list[AlertRule]] = defaultdict(list)
    for regola in regole:
        regole_per_org[regola.organization_id].append(regola)

    inviate = 0
    for organization_id, regole_org in regole_per_org.items():
        gmail = _integrazione_gmail(db, organization_id)
        if gmail is None:
            continue  # nessun canale collegato: niente da segnare, ripartirà da sola quando Gmail verrà collegato

        for regola in regole_org:
            integrazione = db.get(Integration, regola.integration_id)
            if integrazione is None:
                continue
            try:
                source = data_source.resolve(integrazione)
                # _con_riga, non la valuta_regola pubblica: qui serve anche la
                # riga intera per poter preparare un'azione (vedi sotto), non
                # solo il messaggio già pronto per un umano.
                segnalazioni = alert_engine.valuta_regola_con_riga(regola, source)
            except Exception:
                continue  # sorgente irraggiungibile ora: non deve bloccare le altre regole

            azione_template = json.loads(regola.azione_template or "{}")

            for s in segnalazioni:
                chiave = f"segnalazione:{s['regola_id']}:{s['pk']}"
                if not _gia_notificata(db, organization_id, chiave):
                    corpo = f"{s['messaggio']}\n\nDettaglio: {s['dettaglio']}\nRegola: {s['regola_nome']}"
                    oggetto_notifica = f"[Cortex] Segnalazione: {s['regola_nome']}"
                    if azione_template.get("to_colonna"):
                        corpo += "\n\nHo preparato una bozza pronta per questo caso — confermala su Cortex."
                    if _invia(gmail, oggetto_notifica, corpo):
                        inviate += 1
                        # Segnata SOLO se l'invio è riuscito: un SMTP momentaneamente
                        # irraggiungibile deve far ritentare questa segnalazione al
                        # prossimo ciclo, non "consumarla" a vuoto per sempre.
                        _segna_notificata(db, organization_id, chiave)

                _prepara_azione_se_configurata(db, organization_id, regola, s, azione_template)
    return inviate


def _prepara_azione_se_configurata(
    db: Session, organization_id: int, regola: AlertRule, segnalazione: dict, azione_template: dict
) -> None:
    """Se la regola ha un template d'azione collegato (vedi
    AlertRule.azione_template), prepara una bozza pronta (AzionePendente,
    non inviata) per questa segnalazione — il "lavoro vero" oltre alla
    notifica: un sollecito già scritto con i dati reali della riga, che un
    amministratore conferma con un click invece di scriverlo da zero.
    Chiave di deduplicazione separata da quella della notifica ("azione:"
    invece di "segnalazione:"): le due cose sono indipendenti, una bozza
    già preparata non va rifatta anche se in futuro la notifica interna
    dovesse fallire o essere disattivata."""
    colonna_destinatario = azione_template.get("to_colonna")
    if not colonna_destinatario:
        return  # nessuna azione collegata a questa regola, solo la notifica

    chiave = f"azione:{regola.id}:{segnalazione['pk']}"
    if _gia_notificata(db, organization_id, chiave):
        return

    riga = segnalazione["riga"]
    destinatario = riga.get(colonna_destinatario)
    if not destinatario:
        return  # la riga non ha un indirizzo in quella colonna: niente da preparare

    oggetto = applica_template(azione_template.get("oggetto_template", ""), riga).strip() or regola.name
    corpo = applica_template(azione_template.get("corpo_template", ""), riga).strip()
    if not corpo:
        return  # template vuoto: nulla da proporre, meglio niente che una bozza vuota

    db.add(
        AzionePendente(
            organization_id=organization_id,
            origine=f"{regola.name} — {segnalazione['messaggio']}",
            to_address=destinatario,
            subject=oggetto,
            body=corpo,
        )
    )
    _segna_notificata(db, organization_id, chiave)


def _fmt_euro(valore: float) -> str:
    return f"{valore:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _riepilogo_testo(connection_string: str) -> str | None:
    """Poche righe con la liquidità attuale — stesso dato già mostrato in
    Contabilità (compute_saldi), non un calcolo nuovo. None se
    l'integrazione non ha uno schema contabile riconoscibile."""
    try:
        e_arca = accounting_engine_arca.is_arca_schema(connection_string)
    except Exception:
        e_arca = False
    motore = accounting_engine_arca if e_arca else accounting_engine
    try:
        saldi = motore.compute_saldi(connection_string)
    except Exception:
        return None
    if not saldi:
        return None
    righe = [f"- {conto}: {_fmt_euro(valore)}" for conto, valore in saldi.items()]
    totale = sum(saldi.values())
    return "Liquidità attuale:\n" + "\n".join(righe) + f"\n\nTotale: {_fmt_euro(totale)}"


def invia_riepilogo_mattutino(db: Session) -> int:
    """Al massimo un'email al giorno per azienda, e solo dopo
    ORA_RIEPILOGO_MATTUTINO — anche se il ciclo passa più volte dopo quel
    momento nello stesso giorno."""
    if datetime.now().hour < ORA_RIEPILOGO_MATTUTINO:
        return 0

    oggi = date.today().isoformat()
    inviate = 0
    for org in db.query(Organization).all():
        chiave = f"riepilogo:{oggi}"
        if _gia_notificata(db, org.id, chiave):
            continue
        gmail = _integrazione_gmail(db, org.id)
        if gmail is None:
            continue
        integrazione = _integrazione_contabile(db, org.id)
        if integrazione is None:
            continue
        connection_string = decrypt_credentials(integrazione.credentials).get("connection_string")
        if not connection_string:
            continue
        corpo = _riepilogo_testo(connection_string)
        if corpo is None:
            continue
        if _invia(gmail, f"[Cortex] Riepilogo mattutino — {oggi}", corpo):
            inviate += 1
            _segna_notificata(db, org.id, chiave)  # solo su invio riuscito, stesso motivo di controlla_segnalazioni
    return inviate
