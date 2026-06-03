from checkpoint import load_checkpoint


def resume_state(path, new_step):
    load_checkpoint(path)
    return {"step": new_step, "resumed": True}
