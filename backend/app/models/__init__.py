"""
Importa tutti i modelli ORM cosi' che SQLAlchemy possa risolvere le relationship
tra classi (es. User <-> Integration) indipendentemente da chi importa il pacchetto.
"""
from app.models.alert_rule import AlertRule  # noqa: F401
from app.models.azione_pendente import AzionePendente  # noqa: F401
from app.models.integrations import Integration  # noqa: F401
from app.models.membership import Membership  # noqa: F401
from app.models.notifica_inviata import NotificaInviata  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.saved_view import SavedView  # noqa: F401
from app.models.user import User  # noqa: F401
