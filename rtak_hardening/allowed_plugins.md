# RTAK Approved Plugin List

ATAK plugins run with full application privileges. Any plugin can access CoT data, device location, stored files, and network interfaces. **Disable all plugins not on this list before operations.**

---

## Approval Criteria

A plugin may be added to this list only after:

1. **Source review** — plugin APK decompiled and reviewed for outbound network calls, data exfiltration, logging, analytics SDKs, or permissions not required for stated function
2. **Permission audit** — ATAK plugin permissions declared in `plugin.xml` reviewed; any permission not needed for the stated function is a disqualifier unless explained
3. **Network traffic analysis** — plugin run in isolation on a device with traffic captured; no unexpected outbound connections to external IPs or hostnames
4. **Offline operation test** — plugin verified to function fully without internet access

---

## Currently Approved Plugins

*(None yet — add plugins here as they pass review)*

| Plugin | Version | Source | Purpose | Reviewed by | Date |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

---

## Review Procedure for Adding a Plugin

```
1. Obtain the plugin APK from a trusted source (official TAK product site or
   verified team member — never from unknown third parties or app stores)

2. Decompile with apktool:
   apktool d <plugin>.apk -o plugin_source/

3. Search for outbound network calls:
   grep -r "URL\|HttpURLConnection\|OkHttp\|Retrofit\|socket\|connect" plugin_source/

4. Check declared permissions in plugin_source/res/xml/plugin.xml

5. Run network capture during plugin operation:
   adb shell tcpdump -i wlan0 -w /sdcard/plugin_traffic.pcap
   (import to Wireshark, look for external IPs)

6. Document findings in a review entry and sign off with team lead

7. Add to this list with date and reviewer
```

---

## Disqualifying Findings

Any of these automatically disqualify a plugin:

- Analytics or crash reporting SDKs (Firebase, Crashlytics, Amplitude, Segment, etc.)
- Outbound HTTPS to any external host not explicitly declared and necessary
- Permission to access contacts, call log, SMS, or camera without clear operational justification
- No source available and binary contains obfuscated code
- Plugin installed from Google Play Store or unknown distribution source

---

## Notes

- Plugins should be loaded from local storage, not fetched over a network at runtime
- Disable plugins via: ATAK → Settings → Tool Preferences → (plugin) → disable
- A disabled plugin is still installed; for full removal, uninstall the plugin APK

---

## Repository

<https://github.com/private-nemo/RTAK>
