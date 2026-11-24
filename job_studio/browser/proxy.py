import json
import zipfile


def _create_proxy_auth_extension(
    host: str, port: int, username: str, password: str
) -> str:
    """Creates a Chrome extension for authorization on an HTTP/HTTPS proxy.\n    Returns the path to the extension's .zip file."""

    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Proxy Auth",
        "permissions": [
            "proxy",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = """
    var config = {
            mode: "fixed_servers",
            rules: {
              singleProxy: {
                host: %s,
                port: %d
              },
              bypassList: ["localhost"]
            }
          };
          chrome.proxy.settings.set(
              {value: config, scope: "regular"},
              function() {}
          );
        function callbackFn(details) {
            return {
                authCredentials: {
                    username: %s,
                    password: %s
                }
            };
        }
        chrome.webRequest.onAuthRequired.addListener(
            callbackFn,
            {urls: ["<all_urls>"]},
            ['blocking']
        );
    """ % (json.dumps(host), port, json.dumps(username), json.dumps(password))

    # Save it to a temporary file next to your profile
    import tempfile

    temp_file = tempfile.NamedTemporaryFile(
        delete=False, prefix="proxy_auth_", suffix=".zip"
    )

    unique_path = temp_file.name

    temp_file.close()

    with zipfile.ZipFile(unique_path, "w") as zip_file:
        zip_file.writestr("manifest.json", manifest_json)
        zip_file.writestr("background.js", background_js)

    return unique_path
