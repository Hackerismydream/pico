from audit import audit_line
from models import User
from permissions import can


def test_unknown_roles_have_no_permissions_and_blank_token_is_omitted():
    user = User("guest", "unknown")
    assert not can(user, "read")
    assert "[REDACTED]" not in audit_line(user, "read", False)


def test_maintainer_read_permission_and_failed_audit_redacts_token():
    maintainer = User("max", "maintainer", token="tok-hidden")
    assert can(maintainer, "read")
    line = audit_line(maintainer, "write", False)
    assert "tok-hidden" not in line
    assert "[REDACTED]" in line
