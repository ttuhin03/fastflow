"""
Notifications Module.

Dieses Modul verwaltet E-Mail- und Teams-Benachrichtigungen für Pipeline-Runs.
Benachrichtigungen werden bei Fehlern (FAILED, INTERRUPTED) gesendet.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import httpx

from app.config import config
from app.models import PipelineRun, RunStatus

logger = logging.getLogger(__name__)


async def send_notifications(run: PipelineRun, status: RunStatus) -> None:
    """
    Sendet Benachrichtigungen für einen Pipeline-Run.
    
    Wird nur bei FAILED oder INTERRUPTED Status aufgerufen.
    Fehler beim Senden werden geloggt, aber nicht als Run-Fehler behandelt.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus (FAILED oder INTERRUPTED)
    """
    # Nur bei Fehlern benachrichtigen
    if status not in (RunStatus.FAILED, RunStatus.INTERRUPTED):
        return
    
    # Asynchron im Hintergrund senden (nicht blockierend)
    asyncio.create_task(_send_notifications_async(run, status))


async def _send_notifications_async(run: PipelineRun, status: RunStatus) -> None:
    """
    Interne Funktion zum asynchronen Senden von Benachrichtigungen.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus
    """
    try:
        # E-Mail-Benachrichtigung senden
        if config.EMAIL_ENABLED:
            try:
                await send_email_notification(run, status)
            except Exception as e:
                logger.error(f"Fehler beim Senden der E-Mail-Benachrichtigung für Run {run.id}: {e}", exc_info=True)
        
        # Teams-Benachrichtigung senden
        if config.TEAMS_ENABLED:
            try:
                await send_teams_notification(run, status)
            except Exception as e:
                logger.error(f"Fehler beim Senden der Teams-Benachrichtigung für Run {run.id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Senden von Benachrichtigungen für Run {run.id}: {e}", exc_info=True)


async def send_email_notification(run: PipelineRun, status: RunStatus) -> None:
    """
    Sendet eine E-Mail-Benachrichtigung für einen fehlgeschlagenen Run.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus (FAILED oder INTERRUPTED)
        
    Raises:
        ValueError: Wenn E-Mail-Konfiguration unvollständig ist
    """
    if not config.EMAIL_ENABLED:
        return
    
    # Prüfe Konfiguration
    if not config.SMTP_HOST or not config.SMTP_FROM or not config.EMAIL_RECIPIENTS:
        logger.warning("E-Mail-Benachrichtigung nicht gesendet: Konfiguration unvollständig")
        return
    
    try:
        # E-Mail-Template erstellen
        subject, html_body, text_body = _render_email_template(run, status)
        
        # E-Mail-Nachricht erstellen
        message = MIMEMultipart("alternative")
        message["From"] = config.SMTP_FROM
        message["To"] = ", ".join(config.EMAIL_RECIPIENTS)
        message["Subject"] = subject
        
        # HTML und Text-Version hinzufügen
        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))
        
        # E-Mail senden
        smtp = aiosmtplib.SMTP(
            hostname=config.SMTP_HOST,
            port=config.SMTP_PORT,
            use_tls=config.SMTP_PORT == 587
        )
        
        await smtp.connect()
        
        if config.SMTP_USER and config.SMTP_PASSWORD:
            await smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        
        await smtp.send_message(message)
        await smtp.quit()
        
        logger.info(f"E-Mail-Benachrichtigung für Run {run.id} erfolgreich gesendet")
        
    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail für Run {run.id}: {e}", exc_info=True)
        raise


async def send_teams_notification(run: PipelineRun, status: RunStatus) -> None:
    """
    Sendet eine Microsoft Teams-Benachrichtigung für einen fehlgeschlagenen Run.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus (FAILED oder INTERRUPTED)
        
    Raises:
        ValueError: Wenn Teams-Webhook-URL nicht konfiguriert ist
    """
    if not config.TEAMS_ENABLED:
        return
    
    if not config.TEAMS_WEBHOOK_URL:
        logger.warning("Teams-Benachrichtigung nicht gesendet: Webhook-URL nicht konfiguriert")
        return
    
    try:
        # Teams Adaptive Card erstellen
        card = _create_teams_card(run, status)
        
        # HTTP-Request an Teams-Webhook senden
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                config.TEAMS_WEBHOOK_URL,
                json=card,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
        
        logger.info(f"Teams-Benachrichtigung für Run {run.id} erfolgreich gesendet")
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP-Fehler beim Senden der Teams-Benachrichtigung für Run {run.id}: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Fehler beim Senden der Teams-Benachrichtigung für Run {run.id}: {e}", exc_info=True)
        raise


def _render_email_template(run: PipelineRun, status: RunStatus) -> tuple[str, str, str]:
    """
    Erstellt E-Mail-Template für einen fehlgeschlagenen Run.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus
        
    Returns:
        Tuple von (subject, html_body, text_body)
    """
    status_text = "fehlgeschlagen" if status == RunStatus.FAILED else "abgebrochen"
    status_color = "#F44336" if status == RunStatus.FAILED else "#FF9800"
    
    # Dauer berechnen
    duration = "N/A"
    if run.started_at and run.finished_at:
        delta = run.finished_at - run.started_at
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            duration = f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            duration = f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m"
    
    # Frontend-URL (falls konfiguriert)
    frontend_url = getattr(config, 'FRONTEND_URL', None)
    run_url = f"{frontend_url}/runs/{run.id}" if frontend_url else None
    
    subject = f"[FastFlow] Pipeline {run.pipeline_name} {status_text}"
    
    # Exit-Code HTML erstellen (außerhalb des f-strings wegen Backslash-Problemen)
    exit_code_html = ""
    if run.exit_code is not None:
        exit_code_html = f'<div class="info-row"><span class="label">Exit-Code:</span><span class="value">{run.exit_code}</span></div>'
    
    # Run-URL Button HTML erstellen
    run_url_html = ""
    if run_url:
        run_url_html = f'<a href="{run_url}" class="button">Run-Details anzeigen</a>'
    
    # HTML-Body
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: {status_color}; color: white; padding: 15px; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 5px 5px; }}
            .info-row {{ margin: 10px 0; }}
            .label {{ font-weight: bold; color: #666; }}
            .value {{ color: #333; }}
            .button {{ display: inline-block; padding: 10px 20px; background-color: #2196F3; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Pipeline {status_text.capitalize()}</h2>
            </div>
            <div class="content">
                <div class="info-row">
                    <span class="label">Pipeline:</span>
                    <span class="value">{run.pipeline_name}</span>
                </div>
                <div class="info-row">
                    <span class="label">Run-ID:</span>
                    <span class="value">{run.id}</span>
                </div>
                <div class="info-row">
                    <span class="label">Status:</span>
                    <span class="value">{status.value}</span>
                </div>
                <div class="info-row">
                    <span class="label">Start-Zeit:</span>
                    <span class="value">{run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.started_at else 'N/A'}</span>
                </div>
                <div class="info-row">
                    <span class="label">End-Zeit:</span>
                    <span class="value">{run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.finished_at else 'N/A'}</span>
                </div>
                <div class="info-row">
                    <span class="label">Dauer:</span>
                    <span class="value">{duration}</span>
                </div>
                {exit_code_html}
                {run_url_html}
            </div>
        </div>
    </body>
    </html>
    """
    
    # Text-Body (Fallback)
    text_body = f"""
Pipeline {status_text.capitalize()}

Pipeline: {run.pipeline_name}
Run-ID: {run.id}
Status: {status.value}
Start-Zeit: {run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.started_at else 'N/A'}
End-Zeit: {run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.finished_at else 'N/A'}
Dauer: {duration}
{f'Exit-Code: {run.exit_code}' if run.exit_code is not None else ''}
{f'Run-Details: {run_url}' if run_url else ''}
    """.strip()
    
    return subject, html_body, text_body


def _create_teams_card(run: PipelineRun, status: RunStatus) -> dict:
    """
    Erstellt eine Microsoft Teams Adaptive Card für einen fehlgeschlagenen Run.
    
    Args:
        run: PipelineRun-Objekt
        status: RunStatus
        
    Returns:
        Dictionary mit Adaptive Card JSON
    """
    status_text = "Fehlgeschlagen" if status == RunStatus.FAILED else "Abgebrochen"
    status_color = "attention" if status == RunStatus.FAILED else "warning"
    
    # Dauer berechnen
    duration = "N/A"
    if run.started_at and run.finished_at:
        delta = run.finished_at - run.started_at
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            duration = f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            duration = f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m"
    
    # Frontend-URL (falls konfiguriert)
    frontend_url = getattr(config, 'FRONTEND_URL', None)
    run_url = f"{frontend_url}/runs/{run.id}" if frontend_url else None
    
    facts = [
        {"title": "Pipeline", "value": run.pipeline_name},
        {"title": "Run-ID", "value": str(run.id)[:8] + "..."},
        {"title": "Status", "value": status.value},
        {"title": "Start-Zeit", "value": run.started_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.started_at else "N/A"},
        {"title": "End-Zeit", "value": run.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.finished_at else "N/A"},
        {"title": "Dauer", "value": duration},
    ]
    
    if run.exit_code is not None:
        facts.append({"title": "Exit-Code", "value": str(run.exit_code)})
    
    # Microsoft Teams MessageCard Format (kompatibel mit Webhooks)
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Pipeline {run.pipeline_name} {status_text}",
        "themeColor": "FF0000" if status == RunStatus.FAILED else "FF9800",  # Rot für FAILED, Orange für INTERRUPTED
        "title": f"Pipeline {status_text}",
        "sections": [
            {
                "activityTitle": f"Pipeline: {run.pipeline_name}",
                "facts": facts,
                "markdown": True
            }
        ]
    }
    
    # Action-Button hinzufügen, falls URL vorhanden
    if run_url:
        card["potentialAction"] = [
            {
                "@type": "OpenUri",
                "name": "Run-Details anzeigen",
                "targets": [
                    {
                        "os": "default",
                        "uri": run_url
                    }
                ]
            }
        ]
    
    return card


async def send_soft_limit_notification(run: PipelineRun, resource_type: str, current_value: float, limit_value: float) -> None:
    """
    Sendet eine Benachrichtigung bei Soft-Limit-Überschreitung.
    
    Args:
        run: PipelineRun-Objekt
        resource_type: Art der Ressource ("CPU" oder "RAM")
        current_value: Aktueller Wert
        limit_value: Soft-Limit-Wert
    """
    if not config.EMAIL_ENABLED and not config.TEAMS_ENABLED:
        return
    
    try:
        subject = f"[FastFlow] Soft-Limit überschritten: {run.pipeline_name}"
        message = f"Pipeline {run.pipeline_name} (Run {run.id}) hat das {resource_type}-Soft-Limit überschritten: {current_value:.1f} > {limit_value:.1f}"
        
        # E-Mail senden
        if config.EMAIL_ENABLED:
            try:
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                import aiosmtplib
                
                msg = MIMEMultipart("alternative")
                msg["From"] = config.SMTP_FROM
                msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)
                msg["Subject"] = subject
                msg.attach(MIMEText(message, "plain"))
                
                smtp = aiosmtplib.SMTP(
                    hostname=config.SMTP_HOST,
                    port=config.SMTP_PORT,
                    use_tls=config.SMTP_PORT == 587
                )
                await smtp.connect()
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    await smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                await smtp.send_message(msg)
                await smtp.quit()
            except Exception as e:
                logger.error(f"Fehler beim Senden der Soft-Limit-E-Mail: {e}")
        
        # Teams senden (falls aktiviert)
        if config.TEAMS_ENABLED:
            try:
                import httpx
                card = {
                    "@type": "MessageCard",
                    "@context": "https://schema.org/extensions",
                    "summary": subject,
                    "themeColor": "FF9800",
                    "title": "Soft-Limit überschritten",
                    "sections": [{
                        "activityTitle": f"Pipeline: {run.pipeline_name}",
                        "facts": [
                            {"title": "Run-ID", "value": str(run.id)[:8] + "..."},
                            {"title": "Ressource", "value": resource_type},
                            {"title": "Aktueller Wert", "value": f"{current_value:.1f}"},
                            {"title": "Soft-Limit", "value": f"{limit_value:.1f}"},
                        ],
                        "markdown": True
                    }]
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(config.TEAMS_WEBHOOK_URL, json=card)
            except Exception as e:
                logger.error(f"Fehler beim Senden der Soft-Limit-Teams-Nachricht: {e}")
    except Exception as e:
        logger.error(f"Fehler beim Senden der Soft-Limit-Benachrichtigung: {e}")


async def send_scheduler_error_notification(pipeline_name: str, error_message: str) -> None:
    """
    Sendet eine Benachrichtigung bei Scheduler-Fehlern.
    
    Args:
        pipeline_name: Name der Pipeline
        error_message: Fehlermeldung
    """
    if not config.EMAIL_ENABLED and not config.TEAMS_ENABLED:
        return
    
    try:
        subject = f"[FastFlow] Scheduler-Fehler: {pipeline_name}"
        message = f"Scheduler konnte Pipeline {pipeline_name} nicht ausführen: {error_message}"
        
        # E-Mail senden
        if config.EMAIL_ENABLED:
            try:
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                import aiosmtplib
                
                msg = MIMEMultipart("alternative")
                msg["From"] = config.SMTP_FROM
                msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)
                msg["Subject"] = subject
                msg.attach(MIMEText(message, "plain"))
                
                smtp = aiosmtplib.SMTP(
                    hostname=config.SMTP_HOST,
                    port=config.SMTP_PORT,
                    use_tls=config.SMTP_PORT == 587
                )
                await smtp.connect()
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    await smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                await smtp.send_message(msg)
                await smtp.quit()
            except Exception as e:
                logger.error(f"Fehler beim Senden der Scheduler-Error-E-Mail: {e}")
        
        # Teams senden
        if config.TEAMS_ENABLED:
            try:
                import httpx
                card = {
                    "@type": "MessageCard",
                    "@context": "https://schema.org/extensions",
                    "summary": subject,
                    "themeColor": "F44336",
                    "title": "Scheduler-Fehler",
                    "sections": [{
                        "activityTitle": f"Pipeline: {pipeline_name}",
                        "facts": [
                            {"title": "Fehler", "value": error_message},
                        ],
                        "markdown": True
                    }]
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(config.TEAMS_WEBHOOK_URL, json=card)
            except Exception as e:
                logger.error(f"Fehler beim Senden der Scheduler-Error-Teams-Nachricht: {e}")
    except Exception as e:
        logger.error(f"Fehler beim Senden der Scheduler-Error-Benachrichtigung: {e}")
