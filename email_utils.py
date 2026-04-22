# email_utils.py - Отправка email через SMTP (Mail.ru)
import smtplib
import ssl
import os
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)


def generate_verification_code() -> str:
    """Генерирует 6-значный код подтверждения"""
    return f"{secrets.randbelow(900000) + 100000}"


def _send_code_email(to_email: str, code: str, subject: str, heading: str) -> bool:
    """Внутренний хелпер для отправки письма с кодом"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    html = f"""\
    <html>
    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
      <div style="max-width: 400px; margin: 0 auto; background: white; border-radius: 12px; padding: 32px; text-align: center;">
        <h2 style="color: #333; margin-bottom: 8px;">Sounduk</h2>
        <p style="color: #666; margin-bottom: 24px;">{heading}</p>
        <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #111; background: #f0f0f0; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
          {code}
        </div>
        <p style="color: #999; font-size: 13px;">Код действителен 10 минут.<br>Если вы не запрашивали код — проигнорируйте это письмо.</p>
      </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[email] Ошибка отправки на {to_email}: {e}")
        return False


def send_verification_email(to_email: str, code: str) -> bool:
    """Отправляет код подтверждения регистрации"""
    return _send_code_email(
        to_email, code,
        subject=f"Sounduk — код подтверждения: {code}",
        heading="Ваш код подтверждения:"
    )


def send_password_reset_email(to_email: str, code: str) -> bool:
    """Отправляет код сброса пароля"""
    return _send_code_email(
        to_email, code,
        subject=f"Sounduk — восстановление пароля: {code}",
        heading="Код для восстановления пароля:"
    )


