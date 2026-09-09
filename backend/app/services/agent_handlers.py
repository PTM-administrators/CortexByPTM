from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.models.integrations import Integration
from app.models.user import User
from app.services import (
    accounting_engine,
    accounting_engine_arca,
    agent_state,
    alert_engine,
    conversation_state,
    data_source,
    esplorazione,
    narrazione,
    previsione,
    segnalazione_automatica,
    view_rendering,
    vista_automatica,
)
from app.services.integration_providers import find_first_database_integration
from app.services.llm import AgentDecision
from app.tools import scraper_tool
from app.services.agent_widgets import (
    _chart_andamento,
    _chart_composizione,
    _chart_confronto,
    _chart_periodo,
    _nome_periodo,
    _periodo_richiesto,
    _widget_elenco,
    _widget_quadro_generale,
    _widget_saldo,
    _widget_spiegazione,
)


def _find_integration(db: Session, user: User, providers: tuple[str, ...]) -> Integration | None:
    return (
        db.query(Integration)
        .filter(Integration.organization_id == user.organization_id, Integration.provider.in_(providers))
        .order_by(Integration.created_at)
        .first()
    )


def _motore_contabile(connection_string: str):
    """Sceglie fra i due motori (Sampeyre / Arca)."""
    try:
        if accounting_engine_arca.is_arca_schema(connection_string):
            return accounting_engine_arca
    except Exception:
        pass
    return accounting_engine


def _find_database_integration(db: Session, user: User) -> Integration | None:
    """Prima integrazione dell'azienda che espone un database."""
    return find_first_database_integration(db, user.organization_id)


def ricorda_contesto_visualizzazione(user: User, modo: str, tipo: str, anno: int, mese: int) -> None:
    conversation_state.imposta_ultimo_contesto_visualizzazione(
        user.id, {"modo": modo, "tipo": tipo, "periodi": [[anno, mese]]}
    )


def handle_email(db: Session, current_user: User, decision: AgentDecision) -> dict[str, Any]:
    if decision.missing_fields:
        return {"action": "email_tool", "reply": decision.reply, "pending_action": None}

    integration = _find_integration(db, current_user, ("gmail",))
    if integration is None:
        return {
            "action": "email_tool",
            "reply": (
                "Non hai ancora collegato un'integrazione Gmail/SMTP: configurala nella "
                "pagina Integrazioni, poi riprova."
            ),
            "pending_action": None,
        }

    action = agent_state.create_pending_action(current_user.id, "email_tool", decision.arguments)
    return {
        "action": "email_tool",
        "reply": decision.reply,
        "pending_action": {"id": action.id, "tool": "email_tool", "preview": decision.arguments},
    }


def handle_search(decision: AgentDecision) -> dict[str, Any]:
    query = decision.arguments.get("query", "")
    risultato = scraper_tool.web_search(query)
    if "error" in risultato:
        reply = f'{decision.reply} Non sono riuscito a completare la ricerca ({risultato["error"]}).'
    else:
        reply = f"{decision.reply} Ricerca eseguita (nessun riassunto automatico ancora — arriva nel prossimo passo della Fase D)."
    return {"action": "scraper_tool", "reply": reply, "pending_action": None}


def handle_esplora(db: Session, current_user: User, decision: AgentDecision, message: str) -> dict[str, Any]:
    integration = _find_database_integration(db, current_user)
    if integration is None:
        return {
            "action": "esplora_tool",
            "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
            "pending_action": None,
        }
    connection_string = decrypt_credentials(integration.credentials).get("connection_string")
    if not connection_string:
        return {
            "action": "esplora_tool",
            "reply": "L'integrazione collegata non ha un database esplorabile.",
            "pending_action": None,
        }

    termine = decision.arguments.get("termine") or message
    try:
        trovato = esplorazione.cerca(connection_string, termine)
    except Exception as exc:
        return {
            "action": "esplora_tool",
            "reply": f"Non sono riuscito a cercare tra i dati collegati: {exc}",
            "pending_action": None,
        }

    if trovato is None:
        disponibili = esplorazione.tabelle_note(connection_string)
        if disponibili:
            elenco = ", ".join(r["tabella"] for r in disponibili[:8])
            reply = f'Non ho trovato dati su "{termine}". Le tabelle che riesco a leggere sono: {elenco}.'
        else:
            reply = f'Non ho trovato dati su "{termine}" in questo database.'
        return {"action": "esplora_tool", "reply": reply, "pending_action": None}

    if trovato["tipo"] == "andamento":
        widget = {
            "type": "line",
            "title": f"{trovato['tabella']} — andamento di {trovato['colonna_numero']}",
            "labels": [p["periodo"] for p in trovato["andamento"]],
            "series": [{"name": trovato["colonna_numero"], "data": [p["totale"] for p in trovato["andamento"]]}],
        }
        reply = f'Ecco l\'andamento di "{trovato["tabella"]}" — {trovato["righe_totali"]} righe totali.'
        return {"action": "esplora_tool", "reply": reply, "pending_action": None, "widget": widget}

    items = [{"label": "Righe totali", "value": trovato["righe"]}]
    if trovato.get("somma") is not None:
        items.append({"label": f"Totale {trovato['colonna_numero']}", "value": trovato["somma"], "format": "currency"})
    widget = {"type": "cards", "title": f'Tabella "{trovato["tabella"]}"', "items": items}
    return {
        "action": "esplora_tool",
        "reply": f'Ecco cosa ho trovato in "{trovato["tabella"]}".',
        "pending_action": None,
        "widget": widget,
    }


def handle_crea_vista(db: Session, current_user: User, decision: AgentDecision, message: str) -> dict[str, Any]:
    integration = _find_database_integration(db, current_user)
    if integration is None:
        return {
            "action": "crea_vista_tool",
            "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
            "pending_action": None,
        }
    connection_string = decrypt_credentials(integration.credentials).get("connection_string")
    if not connection_string:
        return {
            "action": "crea_vista_tool",
            "reply": "L'integrazione collegata non ha un database esplorabile.",
            "pending_action": None,
        }

    args = decision.arguments
    termine = args.get("termine") or message
    try:
        risultato = vista_automatica.crea_o_riusa_vista(
            db,
            integration,
            connection_string,
            termine,
            mode=args.get("mode"),
            colonna_data=args.get("colonna_data"),
            colonna_titolo=args.get("colonna_titolo"),
            colonna_sottotitolo=args.get("colonna_sottotitolo"),
            colonna_badge=args.get("colonna_badge"),
        )
    except Exception as exc:
        return {
            "action": "crea_vista_tool",
            "reply": f"Non sono riuscito a creare la vista: {exc}",
            "pending_action": None,
        }
    if risultato is None:
        return {
            "action": "crea_vista_tool",
            "reply": f'Non ho trovato una tabella che sembri corrispondere a "{termine}".',
            "pending_action": None,
        }

    vista, creata_ora, _nome_tabella = risultato
    try:
        source = data_source.resolve(integration)
        widget = view_rendering.render_view_data(vista, source)
    except Exception as exc:
        return {
            "action": "crea_vista_tool",
            "reply": f'Ho creato la vista "{vista.name}" ma non riesco a mostrarla: {exc}',
            "pending_action": None,
        }

    verbo = "Creata" if creata_ora else "Ecco"
    reply = (
        f'{verbo} la vista "{vista.name}" — la trovi anche nella pagina Viste, e la puoi ririchiamare '
        f'in qualunque momento scrivendo "mostrami {vista.name.lower()}".'
    )
    return {"action": "crea_vista_tool", "reply": reply, "pending_action": None, "widget": widget}


def handle_crea_segnalazione(db: Session, current_user: User, decision: AgentDecision, message: str) -> dict[str, Any]:
    integration = _find_database_integration(db, current_user)
    if integration is None:
        return {
            "action": "crea_segnalazione_tool",
            "reply": "Non hai ancora un database collegato: collegane uno nella pagina Integrazioni.",
            "pending_action": None,
        }
    connection_string = decrypt_credentials(integration.credentials).get("connection_string")
    if not connection_string:
        return {
            "action": "crea_segnalazione_tool",
            "reply": "L'integrazione collegata non ha un database esplorabile.",
            "pending_action": None,
        }

    args = decision.arguments
    termine = args.get("termine") or message
    condition_type = args.get("condition_type")
    operatore = args.get("operatore")
    soglia = args.get("soglia")

    try:
        if condition_type:
            risultato = segnalazione_automatica.crea_o_riusa_segnalazione(
                db,
                integration,
                connection_string,
                termine,
                condition_type,
                colonna=args.get("colonna"),
                colonna_data=args.get("colonna_data"),
                operatore=operatore,
                soglia=float(soglia) if soglia is not None else None,
                giorni_tolleranza=int(args.get("giorni_tolleranza") or 0),
                colonna_gruppo=args.get("colonna_gruppo"),
                soglia_deviazioni=float(args.get("soglia_deviazioni") or 2.0),
            )
        elif operatore is not None and soglia is not None:
            risultato = segnalazione_automatica.crea_o_riusa_segnalazione_soglia(
                db, integration, connection_string, termine, operatore, float(soglia)
            )
        else:
            giorni_tolleranza = int(args.get("giorni_tolleranza") or 0)
            risultato = segnalazione_automatica.crea_o_riusa_segnalazione_scadenza(
                db, integration, connection_string, termine, giorni_tolleranza
            )
    except Exception as exc:
        return {
            "action": "crea_segnalazione_tool",
            "reply": f"Non sono riuscito a creare la segnalazione: {exc}",
            "pending_action": None,
        }
    if risultato is None:
        return {
            "action": "crea_segnalazione_tool",
            "reply": (
                f'Non ho trovato una tabella con una colonna adatta che corrisponda a "{termine}". '
                "Puoi configurarla a mano nella pagina Segnalazioni."
            ),
            "pending_action": None,
        }

    regola, creata_ora, scattate = risultato
    verbo = "Creata" if creata_ora else "Trovata"
    parola_riga = "riga" if len(scattate) == 1 else "righe"
    reply = (
        f'{verbo} la segnalazione "{regola.name}" — con i criteri attuali oggi scatterebbe su '
        f"{len(scattate)} {parola_riga}. La trovi nella pagina Segnalazioni."
    )
    widget = {
        "type": "narrative",
        "title": regola.name,
        "text": "; ".join(s["dettaglio"] for s in scattate[:5]) or "Nessuna riga scattata al momento.",
    }
    return {"action": "crea_segnalazione_tool", "reply": reply, "pending_action": None, "widget": widget}


def handle_visualize(db: Session, current_user: User, decision: AgentDecision) -> dict[str, Any]:
    integration = _find_database_integration(db, current_user)
    if integration is None:
        return {
            "action": "visualize_tool",
            "reply": "Non hai ancora un database collegato con dati finanziari: collegane uno nella pagina Integrazioni.",
            "pending_action": None,
        }

    connection_string = decrypt_credentials(integration.credentials).get("connection_string")
    if not connection_string:
        return {
            "action": "visualize_tool",
            "reply": "L'integrazione collegata non ha un database esplorabile.",
            "pending_action": None,
        }

    args = decision.arguments
    tipo = args.get("tipo", "uscita")
    modo = args.get("modo")
    motore = _motore_contabile(connection_string)

    try:
        if modo == "saldo":
            saldi = motore.compute_saldi(connection_string)
            widget = _widget_saldo(saldi)
        elif modo == "elenco":
            anno, mese = _periodo_richiesto(args)
            righe = motore.list_movimenti(connection_string, anno, mese, tipo)
            widget = _widget_elenco(righe, _nome_periodo(anno, mese))
            ricorda_contesto_visualizzazione(current_user, "elenco", tipo, anno, mese)
        elif modo == "confronto":
            (anno1, mese1), (anno2, mese2) = args["periodi"]
            dati1 = motore.compute_spese_per_categoria(connection_string, anno1, mese1, tipo)
            dati2 = motore.compute_spese_per_categoria(connection_string, anno2, mese2, tipo)
            widget = _chart_confronto(dati1, dati2, _nome_periodo(anno1, mese1), _nome_periodo(anno2, mese2), tipo)
        elif modo == "periodo":
            anno, mese = _periodo_richiesto(args)
            dati = motore.compute_spese_per_categoria(connection_string, anno, mese, tipo)
            if args.get("composizione"):
                widget = _chart_composizione(dati, _nome_periodo(anno, mese), tipo)
            else:
                widget = _chart_periodo(dati, _nome_periodo(anno, mese), tipo)
            ricorda_contesto_visualizzazione(current_user, "periodo", tipo, anno, mese)
        elif modo == "andamento":
            anno = int(args["anno"]) if args.get("anno") else date.today().year
            dati = motore.compute_andamento_mensile(connection_string, anno, tipo)
            widget = _chart_andamento(dati, anno, tipo)
        elif modo == "spiegazione":
            anno, mese = _periodo_richiesto(args)
            risultato = narrazione.spiega_scostamento(motore, connection_string, anno, mese, tipo)
            widget = _widget_spiegazione(risultato)
            ricorda_contesto_visualizzazione(current_user, "spiegazione", tipo, anno, mese)
        elif modo == "quadro_generale":
            saldi_qg = motore.compute_saldi(connection_string)
            spiegazione_qg = narrazione.spiega_ultimo_periodo_con_dati(motore, connection_string, "uscita")
            previsione_qg = previsione.previsione_liquidita(motore, connection_string)
            segnalazioni_qg = alert_engine.valuta_tutte_le_regole(db, current_user.organization_id)
            widget = _widget_quadro_generale(saldi_qg, spiegazione_qg, previsione_qg, segnalazioni_qg)
        else:
            return {"action": "visualize_tool", "reply": "Non ho capito cosa mostrare.", "pending_action": None}
    except Exception as exc:
        return {
            "action": "visualize_tool",
            "reply": f"Non sono riuscito a calcolare la vista: il database collegato ha lo schema atteso? ({exc})",
            "pending_action": None,
        }

    vuoto = (
        widget.get("type") != "quadro_generale"
        and not widget.get("items")
        and not widget.get("rows")
        and not widget.get("labels")
        and not widget.get("text")
    )
    if vuoto:
        return {
            "action": "visualize_tool",
            "reply": f"{decision.reply} Non ho trovato movimenti per questo periodo.",
            "pending_action": None,
        }

    return {"action": "visualize_tool", "reply": decision.reply, "pending_action": None, "widget": widget}
