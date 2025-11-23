#SMTP VERSION

import boto3
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

# Environment variables
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ["EMAIL_FROM"]

SMTP_USERNAME = os.environ["SMTP_USERNAME"]   # SMTP Access Key
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]   # SMTP Secret Key
SMTP_REGION   = os.environ["SMTP_REGION"]     # Example: us-east-1
SMTP_HOST     = os.environ["SMTP_HOST"]       # Example: email-smtp.us-east-1.amazonaws.com
SMTP_PORT     = int(os.environ["SMTP_PORT"])  # Example: 587

ec2 = boto3.client("ec2")
cloudtrail = boto3.client("cloudtrail")


def get_started_by(instance_id):
    try:
        events = cloudtrail.lookup_events(
            LookupAttributes=[{
                "AttributeKey": "ResourceName",
                "AttributeValue": instance_id
            }],
            MaxResults=10
        )
        for ev in events["Events"]:
            if "StartInstances" in ev["EventName"]:
                return ev.get("Username", "Unknown")
    except:
        pass
    return "Unknown"


def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    html_part = MIMEText(html_body, "html")
    msg.attach(html_part)

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    server.quit()


def lambda_handler(event, context):
    instances_info = []

    resp = ec2.describe_instances()

    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            state = inst["State"]["Name"]
            if state != "running":
                continue

            instance_id = inst["InstanceId"]
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                "(no Name tag)"
            )

            launch_time = inst["LaunchTime"]
            now = datetime.now(timezone.utc)
            uptime = now - launch_time
            uptime_str = f"{uptime.days * 24 + uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"

            started_by = get_started_by(instance_id)

            instances_info.append((name, instance_id, state, uptime_str, started_by))

    if not instances_info:
        return {"msg": "No EC2 instances running. No email sent."}

    # Build table
    rows = "".join([
        f"""
        <tr>
            <td>{name}</td>
            <td>{instance_id}</td>
            <td>{state}</td>
            <td>{uptime_str}</td>
            <td>{started_by}</td>
        </tr>
        """ for name, instance_id, state, uptime_str, started_by in instances_info
    ])

    html = f"""
    <html>
    <body>
        <h3>EC2 Running Instances Report</h3>
        <table border="1" cellpadding="6" style="border-collapse: collapse;">
            <tr>
                <th>Name</th>
                <th>Instance ID</th>
                <th>Status</th>
                <th>Uptime</th>
                <th>Started By</th>
            </tr>
            {rows}
        </table>
        <p>Regards, <br> Monitoring Team</p>
    </body>
    </html>
    """

    send_email("EC2 Running Instances Report", html)

    return {"msg": "Email sent", "instances": len(instances_info)}