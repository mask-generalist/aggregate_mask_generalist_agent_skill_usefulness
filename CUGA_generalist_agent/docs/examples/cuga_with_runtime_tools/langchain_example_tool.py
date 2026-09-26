from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import uuid


class Email(BaseModel):
    """Model for an individual email"""

    id: str
    sender: str
    recipient: str
    subject: str
    body: str
    timestamp: datetime
    is_read: bool = False


class EmailsResponse(BaseModel):
    """Response model containing list of emails"""

    emails: List[Email]
    total_emails: int


class SendEmailRequest(BaseModel):
    """Request model for sending emails"""

    recipient: str
    subject: str
    body: str


class SendEmailResponse(BaseModel):
    """Response model for sending emails"""

    success: bool
    message: str
    email_id: Optional[str] = None


# Dummy email storage
DUMMY_EMAILS = [
    Email(
        id="email_001",
        sender="john.doe@company.com",
        recipient="user@gmail.com",
        subject="Weekly Team Meeting",
        body="Hi there! Just a reminder about our weekly team meeting scheduled for Friday at 2 PM. Please come prepared with your project updates.",
        timestamp=datetime.now() - timedelta(hours=2),
        is_read=False,
    ),
    Email(
        id="email_002",
        sender="support@service.com",
        recipient="user@gmail.com",
        subject="Your Account Has Been Updated",
        body="We've successfully updated your account settings as requested. If you have any questions, please don't hesitate to contact our support team.",
        timestamp=datetime.now() - timedelta(days=1),
        is_read=True,
    ),
    Email(
        id="email_003",
        sender="newsletter@techblog.com",
        recipient="user@gmail.com",
        subject="Top 10 AI Trends for 2024",
        body="Discover the latest AI trends that are shaping the future of technology. From machine learning breakthroughs to ethical AI considerations.",
        timestamp=datetime.now() - timedelta(days=2),
        is_read=False,
    ),
    Email(
        id="email_004",
        sender="hr@company.com",
        recipient="user@gmail.com",
        subject="Holiday Schedule Announcement",
        body="Please find attached the holiday schedule for the upcoming quarter. Note the changes to the Thanksgiving week schedule.",
        timestamp=datetime.now() - timedelta(days=3),
        is_read=True,
    ),
]


def read_emails(limit: int = 10, unread_only: bool = False) -> EmailsResponse:
    """Read emails from Gmail inbox with dummy data"""
    emails = DUMMY_EMAILS.copy()

    if unread_only:
        emails = [email for email in emails if not email.is_read]

    # Sort by timestamp (newest first)
    emails.sort(key=lambda x: x.timestamp, reverse=True)

    # Apply limit
    emails = emails[:limit]

    return EmailsResponse(emails=emails, total_emails=len(emails))


def send_email(recipient: str, subject: str, body: str) -> SendEmailResponse:
    """Send an email using Gmail with dummy data"""
    try:
        # Generate a unique email ID
        email_id = f"email_{uuid.uuid4().hex[:8]}"

        # Create the email object
        new_email = Email(
            id=email_id,
            sender="user@gmail.com",
            recipient=recipient,
            subject=subject,
            body=body,
            timestamp=datetime.now(),
            is_read=True,  # Sent emails are marked as read
        )

        # In a real implementation, this would send the email
        # For now, we'll just add it to our dummy storage
        DUMMY_EMAILS.insert(0, new_email)

        return SendEmailResponse(
            success=True, message=f"Email sent successfully to {recipient}", email_id=email_id
        )
    except Exception as e:
        return SendEmailResponse(success=False, message=f"Failed to send email: {str(e)}")


read_tool = StructuredTool.from_function(read_emails)
send_tool = StructuredTool.from_function(send_email)
tools = [read_tool, send_tool]
