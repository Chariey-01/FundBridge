"""`flask --app run:app fundbridge-admin create-admin --email ...`: create the first administrator.

Public registration always creates donors, so a fresh deployment needs one operator-created
admin. That admin then assigns every other role through ``PUT /api/v1/admin/users/<id>/role``.
The password is read from ``FUNDBRIDGE_ADMIN_PASSWORD`` or prompted for (hidden, confirmed),
and is never echoed.
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup

admin_cli = AppGroup("fundbridge-admin", help="Operator commands (first admin bootstrap).")


@admin_cli.command("create-admin")
@click.option("--email", required=True, help="Email address of the administrator account.")
@click.option("--password", envvar="FUNDBRIDGE_ADMIN_PASSWORD", prompt=True, hide_input=True,
              confirmation_prompt=True, help="At least 12 characters. Prefer the env var or the prompt.")
@click.option("--promote-existing", is_flag=True, help="Make an existing account an admin (and reset its password).")
def create_admin(email: str, password: str, promote_existing: bool) -> None:
    from app.extensions import db
    from app.models.core import AuditLog, Role, User

    email = email.strip()
    if "@" not in email:
        raise click.ClickException("Provide a valid email address.")
    if len(password) < 12:
        raise click.ClickException("The password must be at least 12 characters.")
    user = User.query.filter_by(email=email).first()
    if user is not None and not promote_existing:
        raise click.ClickException("An account with this email exists. Re-run with --promote-existing to make it an admin.")
    action = "user.admin_promoted_by_operator" if user else "user.admin_created_by_operator"
    if user is None:
        user = User(email=email, role=Role.admin)
        db.session.add(user)
    user.role = Role.admin
    user.status = "active"
    user.set_password(password)
    db.session.flush()
    db.session.add(AuditLog(actor_id=None, action=action, resource_type="user", resource_id=user.id,
                            metadata_json={"via": "cli"}))
    db.session.commit()
    click.echo(f"Administrator ready: {email} (id {user.id}).")


def register_admin_cli(app: Flask) -> None:
    app.cli.add_command(admin_cli)
