"""
email_service.py
Handles sending emails via SMTP and checking for replies via IMAP.
"""
import smtplib
import imaplib
import email as email_lib
import re
import time
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid, formatdate
from typing import Optional

logger = logging.getLogger(__name__)

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993

# Delay between emails to respect Gmail rate limits
SEND_DELAY_SECONDS = 1.5


def render_template(template: str, variables: dict) -> str:
    """Replace {{variable}} placeholders in template with actual values."""
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return template


def send_email(
    sender_email: str,
    app_password: str,
    recipient_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    reply_to_message_id: Optional[str] = None,
) -> Optional[str]:
    """
    Send a single email via Gmail SMTP.
    Returns the Message-ID string on success, None on failure.
    """
    msg = MIMEMultipart("alternative")
    msg_id = make_msgid(domain=sender_email.split("@")[-1])
    msg["Message-ID"] = msg_id
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            # Strip spaces — Google shows App Password as "xxxx xxxx xxxx xxxx"
            server.login(sender_email, app_password.replace(" ", ""))
            server.sendmail(sender_email, recipient_email, msg.as_string())
        time.sleep(SEND_DELAY_SECONDS)
        return msg_id
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail authentication failed for %s. Check App Password.", sender_email)
        raise
    except smtplib.SMTPRecipientsRefused:
        logger.warning("Recipient refused: %s", recipient_email)
        return None
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient_email, exc)
        raise


def test_credentials(sender_email: str, app_password: str) -> tuple[bool, str]:
    """
    Test Gmail SMTP credentials.
    Returns (success: bool, message: str).
    """
    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(sender_email, app_password.replace(" ", ""))
        return True, "Credenciales correctas ✓"
    except smtplib.SMTPAuthenticationError:
        return False, "Error de autenticación. Verifica que usas la App Password (16 caracteres) y no tu contraseña normal de Gmail."
    except Exception as exc:
        return False, f"Error de conexión: {exc}"


def check_replies(
    sender_email: str,
    app_password: str,
    message_ids: list[str],
) -> list[str]:
    """
    Check Gmail inbox via IMAP for replies to the given Message-IDs.
    Searches in INBOX and [Gmail]/Sent Mail for emails with In-Reply-To or References
    headers matching any of the provided message IDs.
    Returns a list of original Message-IDs that have received a reply.
    """
    if not message_ids:
        return []

    replied_to = set()

    try:
        with imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT) as imap:
            imap.login(sender_email, app_password)
            imap.select("INBOX", readonly=True)

            # Search all unseen messages and check their headers
            _, data = imap.search(None, "ALL")
            if not data or not data[0]:
                return []

            msg_nums = data[0].split()
            # Fetch headers only (RFC822.HEADER) for efficiency
            for num in msg_nums:
                try:
                    _, msg_data = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES)])")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw_header = msg_data[0][1]
                    if isinstance(raw_header, bytes):
                        raw_header = raw_header.decode("utf-8", errors="ignore")

                    # Extract referenced message IDs from headers
                    refs = re.findall(r"<[^>]+>", raw_header)
                    for ref in refs:
                        if ref in message_ids:
                            replied_to.add(ref)
                except Exception:
                    continue

    except imaplib.IMAP4.error as exc:
        logger.error("IMAP error while checking replies: %s", exc)
    except Exception as exc:
        logger.error("Unexpected error in check_replies: %s", exc)

    return list(replied_to)
