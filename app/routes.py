"""
routes.py
HTTP endpoints for the Email Agent web app.
"""
import logging
import smtplib
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, session

from app import db
from app.models import Campaign, Contact
from app.excel_service import save_upload, read_columns, read_contacts, update_contact_status
from app.email_service import send_email, render_template as render_tmpl, test_credentials
from app.crypto import encrypt, decrypt

logger = logging.getLogger(__name__)
main = Blueprint("main", __name__)


# ── Pages ──────────────────────────────────────────────────────────────────────

@main.route("/")
def index():
    """Step 1: Home page / upload Excel."""
    return render_template("index.html")


@main.route("/configure")
def configure():
    """Step 2: Configure campaign (template, credentials)."""
    return render_template("configure.html")


@main.route("/dashboard")
def dashboard():
    """Step 3: Live dashboard showing campaign status."""
    return render_template("dashboard.html")


# ── API ────────────────────────────────────────────────────────────────────────

@main.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload Excel file. Returns detected column headers."""
    if "file" not in request.files:
        return jsonify({"error": "No se ha enviado ningún archivo"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    try:
        path = save_upload(file)
        columns = read_columns(path)
        session["excel_path"] = path
        return jsonify({"columns": columns, "excel_path": path})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Upload error")
        return jsonify({"error": f"Error al procesar el archivo: {exc}"}), 500


@main.route("/api/test-credentials", methods=["POST"])
def api_test_credentials():
    """Test Gmail credentials before saving the campaign."""
    data = request.get_json()
    sender_email = data.get("sender_email", "").strip()
    app_password = data.get("app_password", "").strip()
    if not sender_email or not app_password:
        return jsonify({"ok": False, "message": "Email y contraseña requeridos"}), 400

    ok, message = test_credentials(sender_email, app_password)
    return jsonify({"ok": ok, "message": message})


@main.route("/api/configure", methods=["POST"])
def api_configure():
    """Save campaign configuration (credentials, templates, follow-up settings)."""
    data = request.get_json()

    required = ["sender_email", "app_password", "subject", "excel_path", "name_col", "email_col"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Campo requerido: {field}"}), 400

    # Deactivate any existing campaign
    Campaign.query.filter(Campaign.status.in_(["draft", "running", "paused"])).update({"status": "archived"})
    db.session.flush()

    campaign = Campaign(
        name=data.get("campaign_name") or f"Campaña {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}",
        excel_path=data["excel_path"],
        email_col=data["email_col"],
        name_col=data["name_col"],
        sender_email=data["sender_email"],
        sender_password_enc=encrypt(data["app_password"]),
        subject=data["subject"],
        body_html=data.get("body_html", ""),
        body_text=data.get("body_text", ""),
        followup_subject=data.get("followup_subject", ""),
        followup_body_html=data.get("followup_body_html", ""),
        followup_body_text=data.get("followup_body_text", ""),
        followup_days=int(data.get("followup_days", 3)),
        status="draft",
        created_at=datetime.utcnow(),
    )
    db.session.add(campaign)
    db.session.commit()
    return jsonify({"campaign_id": campaign.id})


@main.route("/api/launch", methods=["POST"])
def api_launch():
    """Load contacts from Excel and start sending emails."""
    campaign = Campaign.query.filter_by(status="draft").order_by(Campaign.id.desc()).first()
    if not campaign:
        return jsonify({"error": "No hay campaña configurada. Vuelve al paso 2."}), 400

    try:
        contacts_data = read_contacts(campaign.excel_path, campaign.name_col, campaign.email_col)
    except Exception as exc:
        logger.exception("Error reading Excel")
        return jsonify({"error": f"Error leyendo el Excel: {exc}"}), 500

    if not contacts_data:
        return jsonify({"error": "No se encontraron contactos válidos en el Excel. Comprueba que las columnas Nombre y Email están correctamente mapeadas."}), 400

    # Deduplication: find emails already sent in ANY previous campaign
    already_sent = set(
        row[0] for row in db.session.query(Contact.email).filter(
            Contact.status.in_(["sent", "replied", "followup_sent"])
        ).all()
    )

    new_contacts = [c for c in contacts_data if c["email"].lower() not in {e.lower() for e in already_sent}]
    skipped = len(contacts_data) - len(new_contacts)

    if not new_contacts:
        return jsonify({"error": f"Todos los contactos del Excel ya recibieron un email en campañas anteriores ({skipped} omitidos)."}), 400

    # Delete previous contacts for this campaign
    Contact.query.filter_by(campaign_id=campaign.id).delete()

    # Insert only NEW contacts
    contacts_objs = [
        Contact(
            campaign_id=campaign.id,
            email=c["email"],
            name=c["name"],
            custom_fields=c["custom_fields"],
            status="pending",
        )
        for c in new_contacts
    ]
    db.session.add_all(contacts_objs)
    campaign.status = "running"
    campaign.started_at = datetime.utcnow()
    db.session.commit()

    msg = f"Campaña iniciada. Enviando emails a {len(new_contacts)} contactos."
    if skipped:
        msg += f" ({skipped} omitidos por ya haber recibido email anteriormente.)"

    # Pass the current app instance to the thread (do NOT create a new one)
    from flask import current_app
    import threading
    app = current_app._get_current_object()
    thread = threading.Thread(target=_send_campaign_emails, args=[campaign.id, app], daemon=False)
    thread.start()

    return jsonify({"message": msg})


def _send_campaign_emails(campaign_id: int, app):
    """Background thread: send all pending emails for a campaign."""
    with app.app_context():
        campaign = db.session.get(Campaign, campaign_id)
        if not campaign:
            logger.error("Campaign %d not found in send thread", campaign_id)
            return

        try:
            password = decrypt(campaign.sender_password_enc)
        except Exception as exc:
            logger.error("Decrypt error in send thread: %s", exc)
            return

        contacts = Contact.query.filter_by(campaign_id=campaign_id, status="pending").all()
        logger.info("Starting email send: %d contacts for campaign %d", len(contacts), campaign_id)

        auth_failed = False

        for contact in contacts:
            # Re-query campaign status to detect pause
            db.session.expire(campaign)
            if campaign.status == "paused":
                logger.info("Campaign paused, stopping send loop.")
                break

            # Build template variables — support both "nombre" and the original column name
            variables = {
                "nombre": contact.name,
                campaign.name_col: contact.name,   # e.g. {{Nombre}} also works
                **(contact.custom_fields or {}),
            }
            subject  = render_tmpl(campaign.subject, variables)
            body_html = render_tmpl(campaign.body_html or "", variables)
            body_text = render_tmpl(campaign.body_text or "", variables)

            now = datetime.utcnow()
            try:
                message_id = send_email(
                    campaign.sender_email, password,
                    contact.email, subject, body_html, body_text,
                )
                if message_id:
                    contact.status = "sent"
                    contact.message_id = message_id
                    contact.email_sent_at = now
                    contact.send_error = None
                    logger.info("✓ Sent to %s", contact.email)
                else:
                    contact.status = "bounced"
                    contact.send_error = "Email rechazado por el servidor"
                    logger.warning("Bounced: %s", contact.email)
            except smtplib.SMTPAuthenticationError as exc:
                error_msg = "Error de autenticación Gmail. Comprueba el email y la App Password."
                contact.status = "bounced"
                contact.send_error = error_msg
                logger.error("Auth failed for %s: %s", contact.email, exc)
                # Auth failure affects all contacts — mark rest as bounced and stop
                auth_failed = True
                campaign.last_error = error_msg
                campaign.status = "error"
                db.session.commit()
                for remaining in Contact.query.filter_by(campaign_id=campaign_id, status="pending").all():
                    remaining.status = "bounced"
                    remaining.send_error = error_msg
                db.session.commit()
                break
            except Exception as exc:
                contact.status = "bounced"
                contact.send_error = str(exc)[:200]
                logger.error("Send failed for %s: %s", contact.email, exc)

            db.session.commit()

            try:
                update_contact_status(
                    campaign.excel_path, contact.email, contact.status,
                    email_col=campaign.email_col,
                    sent_at=now if contact.status == "sent" else None,
                )
            except Exception as exc:
                logger.warning("Excel update error for %s: %s", contact.email, exc)

        if not auth_failed:
            campaign.status = "running"
            db.session.commit()
        logger.info("Email send loop finished for campaign %d", campaign_id)


@main.route("/api/status", methods=["GET"])
def api_status():
    """Return current campaign status and all contacts."""
    campaign = Campaign.query.filter(
        Campaign.status.in_(["running", "paused", "completed"])
    ).order_by(Campaign.id.desc()).first()

    if not campaign:
        # Also check for draft (configured but not launched)
        campaign = Campaign.query.filter_by(status="draft").order_by(Campaign.id.desc()).first()

    if not campaign:
        return jsonify({"campaign": None, "contacts": []})

    contacts = Contact.query.filter_by(campaign_id=campaign.id).all()
    stats = {
        "total": len(contacts),
        "pending": sum(1 for c in contacts if c.status == "pending"),
        "sent": sum(1 for c in contacts if c.status == "sent"),
        "replied": sum(1 for c in contacts if c.status == "replied"),
        "followup_sent": sum(1 for c in contacts if c.status == "followup_sent"),
        "bounced": sum(1 for c in contacts if c.status == "bounced"),
    }

    return jsonify({
        "campaign": campaign.to_dict(),
        "stats": stats,
        "contacts": [c.to_dict() for c in contacts],
    })


@main.route("/api/pause", methods=["POST"])
def api_pause():
    """Pause or resume the active campaign."""
    campaign = Campaign.query.filter(
        Campaign.status.in_(["running", "paused"])
    ).order_by(Campaign.id.desc()).first()

    if not campaign:
        return jsonify({"error": "No hay campaña activa"}), 404

    campaign.status = "paused" if campaign.status == "running" else "running"
    db.session.commit()
    return jsonify({"status": campaign.status})


@main.route("/api/reset", methods=["POST"])
def api_reset():
    """Archive current campaign and return to step 1."""
    Campaign.query.filter(Campaign.status != "archived").update({"status": "archived"})
    db.session.commit()
    return jsonify({"message": "Campaña archivada. Puedes iniciar una nueva."})


@main.route("/api/debug", methods=["GET"])
def api_debug():
    """Debug endpoint: shows DB state, last campaign and contacts."""
    campaigns = Campaign.query.order_by(Campaign.id.desc()).limit(5).all()
    result = []
    for c in campaigns:
        contacts = Contact.query.filter_by(campaign_id=c.id).all()
        result.append({
            "campaign": c.to_dict(),
            "excel_path": c.excel_path,
            "email_col": c.email_col,
            "name_col": c.name_col,
            "contacts_count": len(contacts),
            "contacts_preview": [{"email": x.email, "name": x.name, "status": x.status} for x in contacts[:5]],
        })
    return jsonify(result)

