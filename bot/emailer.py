"""Send the alert email through Gmail."""
from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from typing import List

from .models import Job


def build_message(jobs: List[Job], sender: str, to: str, catch_up: bool = False) -> EmailMessage:
    n = len(jobs)
    noun = "internship" if n == 1 else "internships"
    if catch_up:
        subject = f"Internship bot is running: {n} open engineering {noun} right now"
        intro = "These are all the engineering internships open right now at the companies you watch."
    else:
        reposted = sum(1 for j in jobs if j.title.endswith("(reposted)"))
        subject = f"{n} new {noun} found" + (f" ({reposted} reposted)" if reposted else "")
        intro = ""

    jobs = sorted(jobs, key=lambda j: (j.company.lower(), j.title.lower()))

    text_lines = [intro, ""] if intro else []
    html_parts = [f"<p>{html.escape(intro)}</p>"] if intro else []
    for j in jobs:
        text_lines += [f"{j.company}: {j.title}", f"Apply: {j.url}", ""]
        html_parts.append(
            f'<p><b>{html.escape(j.company)}</b>: {html.escape(j.title)}<br>'
            f'<a href="{html.escape(j.url, quote=True)}">Apply</a></p>'
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content("\n".join(text_lines))
    msg.add_alternative("<html><body>" + "".join(html_parts) + "</body></html>", subtype="html")
    return msg


def send(msg: EmailMessage, sender: str, app_password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(sender, app_password)
        s.send_message(msg)
