def latest_checkpoint(checkpoints):
    return checkpoints[-1]['checkpoint_id'] if checkpoints else None
