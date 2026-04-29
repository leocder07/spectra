# This is a defensive squat

You almost certainly meant to install **`spectra-ai`** — the real
package that ships the Spectra CLI.

```bash
pip install spectra-ai
```

This package contains no executable code. It exists only to reserve
the name on PyPI so that an attacker cannot publish a typosquat that
exfiltrates your API key when you fat-finger the install command.

- **Real project:** https://pypi.org/project/spectra-ai/
- **Repository:** https://github.com/leocder07/spectra
- **Security policy:** https://github.com/leocder07/spectra/security/policy

If you have any concerns about a Spectra release, please use GitHub
Private Vulnerability Reporting:
https://github.com/leocder07/spectra/security/advisories/new
