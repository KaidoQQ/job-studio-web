import os


def get_key(name):
    if os.environ.get(name):
        return os.environ[name]
    import keyring

    return keyring.get_password("UpWorkAITool", name)
