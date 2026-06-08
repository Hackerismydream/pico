def _usage():
    return "Usage: /dream [status|review <task_id>|apply <task_id>|discard <task_id>]"


def _missing_task_usage(action):
    return f"Usage: /dream {action} <task_id>"


def handle_dream_command(agent, command_args):
    command_args = str(command_args or "").strip()
    if not command_args:
        return agent.run_dream()

    action, _, rest = command_args.partition(" ")
    action = action.strip().lower()
    task_id = rest.strip()

    if action == "status":
        return agent.dream_status_text()

    if action == "review":
        if not task_id:
            return _missing_task_usage("review")
        return agent.dream_review_text(task_id)

    if action == "apply":
        if not task_id:
            return _missing_task_usage("apply")
        try:
            return agent.apply_dream(task_id)
        except Exception as exc:
            return f"error: {exc}"

    if action == "discard":
        if not task_id:
            return _missing_task_usage("discard")
        return agent.discard_dream(task_id)

    return _usage()
