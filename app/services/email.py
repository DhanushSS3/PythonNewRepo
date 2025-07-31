# app/services/email.py

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from app.core.config import get_settings # Import settings
from app.services.email_template import get_margin_call_email_template
from app.core.logging_config import email_sent_logger, email_failed_logger, email_margin_call_logger

settings = get_settings()

async def send_email(to_email: str, subject: str, body: str, email_type: str = "general"):
    """
    Sends an email using the configured SMTP settings with enhanced logging.

    Args:
        to_email: The recipient's email address.
        subject: The subject of the email.
        body: The body of the email (plain text or HTML).
        email_type: Type of email for logging purposes (e.g., "otp", "password_reset", "margin_call").
    """
    # Create a multipart message
    msg = MIMEMultipart()
    msg['From'] = settings.DEFAULT_FROM_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject

    # Attach the body with MIMEText
    msg.attach(MIMEText(body, 'plain')) # Can change 'plain' to 'html' if sending HTML emails

    try:
        # Connect to the SMTP server
        # Use SSL if EMAIL_USE_SSL is True
        if settings.EMAIL_USE_SSL:
            server = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT)
        else:
            server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
            # server.starttls() # Uncomment if using STARTTLS

        # Login to the SMTP server
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

        # Send the email
        server.sendmail(settings.DEFAULT_FROM_EMAIL, to_email, msg.as_bytes())

        # Disconnect from the server
        server.quit()
        
        # Log successful email
        email_sent_logger.info(
            f"EMAIL_SENT - Type: {email_type} | To: {to_email} | Subject: {subject} | "
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Email sent successfully to {to_email}")
    except Exception as e:
        # Log failed email
        email_failed_logger.error(
            f"EMAIL_FAILED - Type: {email_type} | To: {to_email} | Subject: {subject} | "
            f"Error: {str(e)} | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Error sending email to {to_email}: {e}") # Log the error
        # In a real application, you might want to raise this exception
        # or handle it more gracefully (e.g., queue the email for retry).
        raise # Re-raise the exception for now

async def send_margin_call_email(to_email: str, margin_level: str, dashboard_url: str):
    """
    Sends a margin call warning email using the HTML template with specialized logging.
    """
    subject = "Margin Call Warning: Immediate Action Required"
    html_body = get_margin_call_email_template().format(margin_level=margin_level, dashboard_url=dashboard_url)

    # Create a multipart message
    msg = MIMEMultipart()
    msg['From'] = settings.DEFAULT_FROM_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject

    # Attach the HTML body
    msg.attach(MIMEText(html_body, 'html'))

    try:
        if settings.EMAIL_USE_SSL:
            server = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT)
        else:
            server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
            # server.starttls() # Uncomment if using STARTTLS
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        server.sendmail(settings.DEFAULT_FROM_EMAIL, to_email, msg.as_bytes())
        server.quit()
        
        # Log successful margin call email
        email_margin_call_logger.info(
            f"MARGIN_CALL_EMAIL_SENT - To: {to_email} | Margin Level: {margin_level} | "
            f"Dashboard URL: {dashboard_url} | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Margin call email sent successfully to {to_email}")
    except Exception as e:
        # Log failed margin call email
        email_failed_logger.error(
            f"MARGIN_CALL_EMAIL_FAILED - To: {to_email} | Margin Level: {margin_level} | "
            f"Error: {str(e)} | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Error sending margin call email to {to_email}: {e}")
        raise
