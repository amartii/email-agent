from datetime import datetime
from app import db


class Campaign(db.Model):
    """Represents one email campaign loaded from an Excel file."""

    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    excel_path = db.Column(db.String(500))
    email_col = db.Column(db.String(100), default="Email")
    name_col = db.Column(db.String(100), default="Nombre")
    sender_email = db.Column(db.String(200))
    sender_password_enc = db.Column(db.Text)        # encrypted with Fernet
    subject = db.Column(db.Text)
    body_html = db.Column(db.Text)
    body_text = db.Column(db.Text)
    followup_subject = db.Column(db.Text)
    followup_body_html = db.Column(db.Text)
    followup_body_text = db.Column(db.Text)
    followup_days = db.Column(db.Integer, default=3)
    last_error = db.Column(db.Text)                 # last critical error message
    # draft | running | paused | completed | error
    status = db.Column(db.String(20), default="draft")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)

    contacts = db.relationship("Contact", backref="campaign", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "sender_email": self.sender_email,
            "followup_days": self.followup_days,
            "status": self.status,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


class Contact(db.Model):
    """One contact row from the uploaded Excel."""

    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(200))
    custom_fields = db.Column(db.JSON)   # all extra columns from Excel
    # pending | sent | replied | followup_sent | bounced
    status = db.Column(db.String(20), default="pending")
    send_error = db.Column(db.Text)      # error message if bounced
    message_id = db.Column(db.String(200))   # SMTP Message-ID for reply tracking
    email_sent_at = db.Column(db.DateTime)
    replied_at = db.Column(db.DateTime)
    followup_sent_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "custom_fields": self.custom_fields,
            "status": self.status,
            "send_error": self.send_error,
            "email_sent_at": self.email_sent_at.isoformat() if self.email_sent_at else None,
            "replied_at": self.replied_at.isoformat() if self.replied_at else None,
            "followup_sent_at": self.followup_sent_at.isoformat() if self.followup_sent_at else None,
        }
