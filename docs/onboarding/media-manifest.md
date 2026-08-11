# Onboarding media manifest

Repository policy keeps screenshots, GIFs, videos, and other report assets outside Git. This text manifest defines the scenes and acceptance checks so externally hosted media can be reproduced without committing binaries.

| ID | Scene | Required visible proof | Secret treatment |
| --- | --- | --- | --- |
| `first-turn` | `pico onboard` from language selection through the first reply | Provider selected, Myna preview, consent, `Agent:` reply | API key field must be masked; paths use a disposable repository |
| `feishu-config` | Feishu Open Platform plus Pico CLI | long connection, `im.message.receive_v1`, published version, redacted `pico channels get feishu` | App Secret, Encrypt Key, Verification Token, tenant identity redacted |
| `feishu-live` | One inbound Feishu message and Pico reply | inbound message, Gateway accepted log, reply in the same conversation | user names, open IDs, message IDs, credentials redacted |
| `agent-install` | Two-wheel installation and JSON health checks | paired Pico/Myna install, `pico doctor --json`, `myna doctor --format json` | signed wheel query strings and local home paths redacted |

## Capture rules

- Capture the released wheel composition, not an editable developer environment.
- Bind every asset to a Pico tag, Myna version, operating system, and capture date in the external asset description.
- Use a disposable Git repository and disposable Provider/Feishu credentials.
- Keep commands and output readable at README width; crop terminal chrome rather than shrinking text.
- A skipped probe, fixture, or simulated bot reply cannot be labelled as a live success.
- Publish assets only to a maintainer-approved external location. Add README links only after the URLs are stable and publicly readable.
