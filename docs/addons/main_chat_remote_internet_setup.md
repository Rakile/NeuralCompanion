# Main Chat Remote: Secure Internet Setup

Internet Remote is optional. The existing LAN connection remains available and unchanged when Internet Remote is disabled, misconfigured, or temporarily offline.

> Public HTTP is not supported. Do not forward LAN backend port `8777`. Only expose the TLS gateway and the temporary ACME HTTP challenge port described below.

## Before you start

- Reserve the NeuralCompanion PC's LAN address in your router so its local IP does not change.
- Configure a free Dynamic DNS hostname using your router or the DDNS provider's updater.
- Confirm that your ISP gives you a reachable public address. Carrier-grade NAT (CGNAT) normally prevents inbound port forwarding.
- Keep Windows, the router, and NeuralCompanion updated.

## Router forwarding

Create these TCP forwards to the reserved NC PC address:

| Public port | Local port | Purpose |
| --- | --- | --- |
| `443` | `8788` | Secure phone gateway |
| `80` | `8780` | Certificate HTTP-01 issue and renewal |

If you intentionally choose a different public HTTPS port or advanced local ports in the addon, use those values instead. Never forward `8776` or `8777`.

## Certificate and gateway

1. Open **Main Chat Remote → Internet** in NeuralCompanion.
2. Enter the DDNS hostname, detected/confirmed numeric public IP, HTTPS port, certificate email, and accept the certificate authority terms.
3. Save the settings.
4. Select **Install verified helper**. NC downloads the pinned lego 5.2.1 Windows asset and accepts it only when its SHA-256 checksum and reported version match.
5. Select **Run staging test**. A staging certificate is kept separate and never replaces the active production certificate.
6. Select **Issue production certificate**.
7. Enable **Internet Remote**. The saved enable switch opens only the TLS gateway; LAN stays independent.

Certificate checks run in the background. Failed renewals retry after 5 minutes, 15 minutes, 1 hour, 3 hours, and then at most every 6 hours. The UI shows the next check and the last exact failure without blocking the NC window.

## Enroll a phone

1. Prefer doing the first enrollment while the phone is on the same LAN.
2. Select **Create enrollment QR** in the desktop Internet tab.
3. In the phone app choose **Auto** or **Internet**, then scan the QR.
4. The phone displays **Waiting for approval on desktop**.
5. Verify the phone name in the desktop pending list and select **Approve selected phone**.
6. The raw device token is delivered once and stored in the phone's SecureStore. If delivery is interrupted, create a new enrollment QR.

Auto mode tries LAN first, then the DDNS hostname, then the certified numeric-IP fallback. Authentication, certificate, or gateway identity errors stop fallback for safety.

## Test outside the LAN

Disable Wi-Fi on the phone and use cellular data. Verify both:

1. DDNS connection.
2. Certified numeric-IP fallback.

Then test chat, phone-only TTS, a long TTS response, Live Mic interruption, the 48-band fullscreen VU, Visual Reply, fullscreen photo input, Buddy Chat, MuseTalk, reconnect, and Internet-off/LAN-still-on behavior.

## Lost phone or changed network

- Revoke a lost phone immediately from **Paired Internet devices**. Revocation invalidates its Bearer token, WebSocket tickets, and newly verified media URLs.
- If the public IP changes, update DDNS first. Use **Detect public IP**, review the change, save, and reissue the certificate so the numeric IP SAN stays valid.
- Never copy a token, enrollment secret, signing key, or certificate private key into diagnostics or chat.

## Troubleshooting

- **CGNAT:** Compare the router WAN address with the two-source public IP result. If they differ, request a public address from the ISP or use only LAN.
- **Port 80 blocked:** HTTP-01 issuance and renewal cannot complete. Check router forwarding, Windows Firewall, ISP filtering, and whether another service owns the port mapping.
- **DDNS mismatch:** The hostname must resolve to the configured public IP before production issuance.
- **Certificate expired or wrong identity:** Keep Internet Remote off, correct DDNS/IP, reissue, and verify the shown SANs and expiry.
- **Numeric IP does not connect:** The public IP must be present in the valid certificate. A private/router address is rejected.
- **Gateway does not open:** Check the cached error in the Internet tab. LAN remains usable; do not expose port `8777` as a workaround.
