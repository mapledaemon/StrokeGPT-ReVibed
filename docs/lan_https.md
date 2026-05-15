# LAN and HTTPS access

StrokeGPT binds to localhost over HTTP by default. Mobile browser voice input
needs HTTPS unless the browser is on `localhost`, so LAN/mobile voice sessions
should use the HTTPS launcher or the equivalent environment variables.

## Windows

Double-click **`Run StrokeGPT-ReVibed HTTPS.bat`** in the install folder.
It starts the app on port 5011 with LAN binding and HTTPS enabled.

Manual PowerShell equivalent:

```powershell
$env:STROKEGPT_HOST="0.0.0.0"; $env:STROKEGPT_PORT="5011"; $env:STROKEGPT_HTTPS="1"; .\.venv\Scripts\python.exe app.py
```

Then open `https://<PC-LAN-IP>:5011` from the mobile device. Find the host
PC address with `ipconfig`.

## macOS / Linux

```bash
STROKEGPT_HOST=0.0.0.0 STROKEGPT_PORT=5011 STROKEGPT_HTTPS=1 python app.py
```

Then open `https://<PC-LAN-IP>:5011` from the other device. Find the host
address with `ip addr` or `ifconfig`.

## Certificate trust

The app generates a local certificate authority and server certificate in
`user_data/https/`. Your browser may show a certificate warning the first
time. Proceed only on a trusted LAN, then allow microphone access.

If mobile voice input is still blocked, install and trust
`user_data/https/strokegpt-lan-ca.crt` on the mobile device, then reopen the
`https://` LAN URL.

For your own trusted certificate, set both `STROKEGPT_SSL_CERT` and
`STROKEGPT_SSL_KEY` to your certificate and key paths before starting the app.

## Mobile Chrome

Mobile Chrome is stricter than Firefox about certificates. The generated
certificate must include the exact LAN IP typed in Chrome's address bar.
StrokeGPT tries to discover routed LAN IPs automatically. If Chrome still
refuses to load the page, set `STROKEGPT_HTTPS_IPS` to the host PC's LAN IP
before starting:

```powershell
$env:STROKEGPT_HOST="0.0.0.0"; $env:STROKEGPT_PORT="5011"; $env:STROKEGPT_HTTPS="1"; $env:STROKEGPT_HTTPS_IPS="192.168.0.12"; .\.venv\Scripts\python.exe app.py
```

Use the actual IPv4 address from `ipconfig`, not the example address. The
server certificate is regenerated at startup, so restarting StrokeGPT with the
correct `STROKEGPT_HTTPS_IPS` value is enough.

## Security

Do not port-forward StrokeGPT or expose it to the public internet. The app has
no login wall or per-user session isolation and is built for one trusted active
operator.

Omit `STROKEGPT_HTTPS=1` only when you deliberately want plain HTTP for
non-voice LAN testing.

## Slow chat checks

HTTPS should not meaningfully change Ollama generation speed. If chat feels
slower on mobile, compare the same prompt from the host PC and the mobile
browser. When backend timings are high, focus on Ollama model/GPU status; when
backend timings are similar but mobile rendering lags, focus on the browser,
network, or streaming behavior.
