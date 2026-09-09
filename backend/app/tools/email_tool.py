"""
Le "Mani" dell'Agente: invio email tramite SMTP (es. Gmail).
"""
import smtplib
from email.mime.text import MIMEText


def send_email(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    to_address: str,
    subject: str,
    body: str,
) -> dict[str, str]:
    """Invia un'email tramite SMTP usando le credenziali dell'integrazione del cliente.

    STARTTLS e AUTH sono usati solo se il server li offre/servono davvero:
    Gmail li richiede entrambi, ma non tutti i server SMTP lo fanno (es. un
    relay interno sulla porta 25 senza autenticazione) — utile in generale, e
    necessario per poter testare contro un server SMTP locale di sviluppo.
    """
    message = MIMEText(body)
    mittente = username or "cortex@localhost"
    message["Subject"] = subject
    message["From"] = mittente
    message["To"] = to_address

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.ehlo()
        if server.has_extn("starttls"):
            server.starttls()
            server.ehlo()
        if username and password and server.has_extn("auth"):
            server.login(username, password)
        server.sendmail(mittente, [to_address], message.as_string())

    return {"status": "sent", "to": to_address, "subject": subject}
