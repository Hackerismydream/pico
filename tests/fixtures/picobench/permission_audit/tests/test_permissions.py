from audit import audit_line
from models import User
from permissions import can


def test_role_permissions_and_audit_redaction():
    admin = User("ada", "admin", token="sk-secret")
    maintainer = User("max", "maintainer", token="tok-123")
    viewer = User("vic", "viewer", token="tok-456")
    assert can(admin, "delete")
    assert can(maintainer, "read")
    assert can(maintainer, "write")
    assert not can(viewer, "write")
    line = audit_line(admin, "delete", True)
    assert "sk-secret" not in line
    assert "[REDACTED]" in line


def test_blank_token_is_omitted_from_audit_line():
    guest = User("guest", "unknown")
    assert not can(guest, "read")
    assert "[REDACTED]" not in audit_line(guest, "read", False)
