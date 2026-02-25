"""
scheduler.py
APScheduler jobs:
  - check_replies_job: polls Gmail IMAP every 30 min for replies
  - send_followups_job: daily job that sends follow-ups to non-responders
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def check_replies_job(app):
    """Check Gmail inbox for replies to sent emails and update contact status."""
    with app.app_context():
        from app import db
        from app.models import Campaign, Contact
        from app.email_service import check_replies
        from app.excel_service import update_contact_status
        from app.crypto import decrypt

        campaign = Campaign.query.filter_by(status="running").first()
        if not campaign:
            return

        contacts = Contact.query.filter_by(
            campaign_id=campaign.id, status="sent"
        ).all()
        if not contacts:
            return

        message_ids = [c.message_id for c in contacts if c.message_id]
        if not message_ids:
            return

        try:
            password = decrypt(campaign.sender_password_enc)
            replied_ids = check_replies(campaign.sender_email, password, message_ids)
        except Exception as exc:
            logger.error("check_replies_job error: %s", exc)
            return

        now = datetime.utcnow()
        for contact in contacts:
            if contact.message_id in replied_ids:
                contact.status = "replied"
                contact.replied_at = now
                try:
                    update_contact_status(
                        campaign.excel_path,
                        contact.email,
                        "replied",
                        email_col=_get_email_col(campaign),
                        replied_at=now,
                    )
                except Exception as exc:
                    logger.warning("Excel update failed for %s: %s", contact.email, exc)

        db.session.commit()
        logger.info("Reply check done. %d replies found.", len(replied_ids))


def send_followups_job(app):
    """Send follow-up emails to contacts who haven't replied after N days."""
    with app.app_context():
        from app import db
        from app.models import Campaign, Contact
        from app.email_service import send_email, render_template
        from app.excel_service import update_contact_status
        from app.crypto import decrypt

        campaign = Campaign.query.filter_by(status="running").first()
        if not campaign or not campaign.followup_body_html:
            return

        cutoff = datetime.utcnow() - timedelta(days=campaign.followup_days)
        contacts = Contact.query.filter(
            Contact.campaign_id == campaign.id,
            Contact.status == "sent",
            Contact.email_sent_at <= cutoff,
        ).all()

        if not contacts:
            return

        try:
            password = decrypt(campaign.sender_password_enc)
        except Exception as exc:
            logger.error("Decrypt failed in send_followups_job: %s", exc)
            return

        now = datetime.utcnow()
        for contact in contacts:
            variables = {"nombre": contact.name, **(contact.custom_fields or {})}
            subject = render_template(campaign.followup_subject or "", variables)
            body_html = render_template(campaign.followup_body_html or "", variables)
            body_text = render_template(campaign.followup_body_text or "", variables)

            try:
                send_email(
                    campaign.sender_email,
                    password,
                    contact.email,
                    subject,
                    body_html,
                    body_text,
                    reply_to_message_id=contact.message_id,
                )
                contact.status = "followup_sent"
                contact.followup_sent_at = now
                try:
                    update_contact_status(
                        campaign.excel_path,
                        contact.email,
                        "followup_sent",
                        email_col=_get_email_col(campaign),
                        followup_sent_at=now,
                    )
                except Exception as exc:
                    logger.warning("Excel update failed for %s: %s", contact.email, exc)
            except Exception as exc:
                logger.error("Follow-up send failed for %s: %s", contact.email, exc)

        db.session.commit()
        logger.info("Follow-up job done. %d follow-ups sent.", len(contacts))


def _get_email_col(campaign) -> str:
    """Return the email column name stored in the campaign, defaulting to 'Email'."""
    return getattr(campaign, "email_col", None) or "Email"


def start_scheduler(app):
    """Initialize and start the background scheduler with the Flask app context."""
    interval_check = app.config.get("REPLY_CHECK_INTERVAL", 1800)
    interval_followup = app.config.get("FOLLOWUP_CHECK_INTERVAL", 86400)

    scheduler.add_job(
        func=check_replies_job,
        args=[app],
        trigger="interval",
        seconds=interval_check,
        id="check_replies",
        replace_existing=True,
    )

    scheduler.add_job(
        func=send_followups_job,
        args=[app],
        trigger="interval",
        seconds=interval_followup,
        id="send_followups",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started (reply check every %ds, follow-up every %ds)",
                    interval_check, interval_followup)
