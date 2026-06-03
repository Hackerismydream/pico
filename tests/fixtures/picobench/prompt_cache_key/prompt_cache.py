def build_cache_key(model, sections, metadata=None):
    metadata = metadata or {}
    return f"{model}:{sections}:{metadata}"
