def audit_line(user, action, allowed):
    return f"{user.name} {user.token} {action} {allowed}"
