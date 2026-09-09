"""
Cache di engine SQLAlchemy e tabelle riflesse, condivisa da tutti i motori
che parlano con un database esterno (Data Explorer, Viste, Segnalazioni, i
due profili contabili).

La reflection dello schema (introspezione delle colonne via ODBC) può
costare secondi interi su una tabella larga di un database aziendale vero —
misurato: **16 secondi** su una singola tabella di Arca con 108 colonne.
Rifarla ad ogni richiesta HTTP, come succedeva prima (ogni funzione creava
un `create_engine()` nuovo e lo buttava via a fine chiamata), rendeva tutto
il sistema quasi inutilizzabile su un database "serio" — un bilancio che
doveva essere immediato impiegava 20 secondi.

Cacheata per qualche minuto: abbastanza per non rifare l'introspezione ad
ogni click nella stessa sessione di lavoro, abbastanza corta da accorgersi
di una modifica allo schema del database esterno senza dover riavviare il
server. Thread-safe con un lock semplice: il volume di richieste di
un'azienda non giustifica altro.
"""
import threading
import time
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect
from sqlalchemy.engine import Engine

_TTL_SECONDI = 600  # 10 minuti: equilibrio tra "non rifare tutto ad ogni click" e "accorgersi di uno schema cambiato"

_lock = threading.Lock()
_engines: dict[str, Engine] = {}
_tabelle: dict[tuple[int, str], tuple[Table, float]] = {}
_nomi_tabelle: dict[int, tuple[list[str], float]] = {}


def get_engine(connection_string: str) -> Engine:
    """Un solo engine (pool di connessioni) per connection_string, riusato
    tra richieste — non uno nuovo ad ogni chiamata, mai chiuso a fine
    funzione: aprire una connessione a un database aziendale reale (magari
    su un altro host) non è gratis, farlo ad ogni singola richiesta HTTP lo
    è ancora meno."""
    with _lock:
        engine = _engines.get(connection_string)
        if engine is None:
            engine = create_engine(connection_string, pool_pre_ping=True)
            _engines[connection_string] = engine
        return engine


def get_reflected_table(engine: Engine, table_name: str) -> Table:
    """Tabella riflessa (schema letto dal database), cacheata per non
    rifare l'introspezione ad ogni chiamata — la differenza tra una
    richiesta istantanea e una da 15-20 secondi su un database con tabelle
    larghe. Chiave sull'identità dell'engine (stabile perché get_engine lo
    riusa) + nome tabella, non sulla connection string: evita di doverla
    passare in giro ovunque solo per un dettaglio di caching."""
    chiave = (id(engine), table_name)
    with _lock:
        voce = _tabelle.get(chiave)
        if voce is not None and time.time() - voce[1] < _TTL_SECONDI:
            return voce[0]
    tabella = Table(table_name, MetaData(), autoload_with=engine)
    with _lock:
        _tabelle[chiave] = (tabella, time.time())
    return tabella


def list_table_names(engine: Engine) -> list[str]:
    """Elenco delle tabelle del database, cacheato — usato sia per popolare
    la lista tabelle sia come whitelist prima di riflettere una tabella per
    nome (mai passare un nome arbitrario a `Table(..., autoload_with=...)`)."""
    with _lock:
        voce = _nomi_tabelle.get(id(engine))
        if voce is not None and time.time() - voce[1] < _TTL_SECONDI:
            return voce[0]
    nomi = inspect(engine).get_table_names()
    with _lock:
        _nomi_tabelle[id(engine)] = (nomi, time.time())
    return nomi


def invalida(connection_string: str) -> None:
    """Forza a rileggere lo schema alla prossima chiamata — utile subito
    dopo un'operazione che lo cambia (es. provisioning di un nuovo database
    gestito da Cortex)."""
    with _lock:
        engine = _engines.pop(connection_string, None)
        if engine is not None:
            for k in [k for k in _tabelle if k[0] == id(engine)]:
                del _tabelle[k]
            _nomi_tabelle.pop(id(engine), None)
            engine.dispose()
