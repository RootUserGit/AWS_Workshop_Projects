#SES VERSION

import boto3
import os
from datetime import datetime, timezone

EMAIL_TO = os.environ['EMAIL_TO']
EMAIL_FROM = os.environ['EMAIL_FROM']

SES_REGION = os.environ["SES_REGION"]
SES_ACCESS_KEY = os.environ["ACCESS_KEY"]
SES_SECRET_KEY = os.environ["ACCESS_SECRET_KEY"]

ec2 = boto3.client('ec2')
ses = boto3.client(
    "ses",
    region_name=SES_REGION,
    aws_access_key_id=SES_ACCESS_KEY,
    aws_secret_access_key=SES_SECRET_KEY
)
cloudtrail = boto3.client('cloudtrail')

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
    ses.send_email(
        Source=EMAIL_FROM,
        Destination={"ToAddresses": [EMAIL_TO]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Html": {"Data": html_body}}
        }
    )


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
            uptime_str = f"{uptime.days*24 + uptime.seconds//3600}h {(uptime.seconds//60)%60}m"

            started_by = get_started_by(instance_id)

            instances_info.append((name, instance_id, state, uptime_str, started_by))

    if not instances_info:
        return {"msg": "No EC2 instances running. No email sent."}

    # Build table
    rows = ""
    for name, instance_id, state, uptime_str, started_by in instances_info:
        rows += f"""
        <tr>
            <td>{name}</td>
            <td>{instance_id}</td>
            <td>{state}</td>
            <td>{uptime_str}</td>
            <td>{started_by}</td>
        </tr>
        """

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
