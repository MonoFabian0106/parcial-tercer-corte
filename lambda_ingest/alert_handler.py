"""Lambda de alerta: publica en SNS cuando un job Glue falla.

Trigger: EventBridge rule o Glue Workflow ON_FAILURE trigger
         invocando esta Lambda con el evento de fallo del job.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_sns = boto3.client("sns")


def _extract_details(event: dict) -> tuple[str, str]:
    """Extrae job_name y mensaje de distintos formatos de evento."""
    # Formato de Glue Workflow ON_FAILURE trigger
    if "detail" in event:
        detail = event["detail"]
        job_name = detail.get("jobName", detail.get("crawlerName", "unknown"))
        state = detail.get("state", "FAILED")
        run_id = detail.get("jobRunId", detail.get("crawlId", ""))
        message = (
            f"Job/Crawler: {job_name}\n"
            f"Estado: {state}\n"
            f"Run ID: {run_id}\n"
            f"Cuenta: {event.get('account', '')}\n"
            f"Región: {event.get('region', '')}\n"
            f"Hora: {event.get('time', '')}\n\n"
            f"Evento completo:\n{json.dumps(event, indent=2, default=str)}"
        )
        return job_name, message

    # Formato genérico (invocación directa)
    job_name = event.get("jobName", "unknown-job")
    message = f"Fallo en pipeline ShopStream.\n\nDetalles:\n{json.dumps(event, indent=2, default=str)}"
    return job_name, message


def handler(event: dict, context) -> dict:
    logger.info("Alert event received: %s", json.dumps(event, default=str))

    topic_arn = os.environ["SNS_TOPIC_ARN"]
    job_name, message = _extract_details(event)
    subject = f"[ShopStream] Pipeline failure: {job_name}"

    response = _sns.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message,
    )

    logger.info("SNS published. MessageId=%s", response["MessageId"])
    return {"statusCode": 200, "messageId": response["MessageId"]}
