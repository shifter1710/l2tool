import hashlib
import subprocess


def hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def open_url(url: str):
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"],
        check=False,
    )

def open_url_chrome(url: str):
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    subprocess.run([
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f'Start-Process "{chrome_path}" "{url}"'
    ])