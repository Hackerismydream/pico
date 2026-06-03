def locate_artifacts(output_dir, manifest):
    return manifest.get('evidence_paths', [])
