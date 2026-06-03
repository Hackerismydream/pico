def classify_command(command):
    if 'rm' in command:
        return 'high'
    return 'low'
