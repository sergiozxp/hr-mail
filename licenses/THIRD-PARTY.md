# Third-party programs bundled with hr-mail

hr-mail itself is licensed under GPL-3.0-or-later (`hr-mail-GPL-3.0.txt` in the release, `LICENSE` in the repo).

hr-mail ships these programs unmodified, as separate executables, in `bin/`.
They are free software; their licenses are in this folder.

| Program | Version | License | Source code |
|---|---|---|---|
| Mercury (Rhizomatica) — `bin/mercury/mercury.exe` | 1.9.19 (git e9f0072d) | GPL-3.0 (`mercury-GPL-3.0.txt`); includes FreeDV code under LGPL-2.1 (`mercury-freedv-LGPL-2.1.txt`) | https://github.com/Rhizomatica/mercury/tree/v1.9.19 |
| Hamlib — `bin/mercury/libhamlib-4.dll` | 4.6.5 (as shipped in the Mercury release) | LGPL-2.1 | https://github.com/Hamlib/Hamlib |
| libusb — `bin/mercury/libusb-1.0.dll` | as shipped in the Mercury release | LGPL-2.1 | https://github.com/libusb/libusb |
| MinGW-w64 runtime — `libgcc_s_seh-1.dll`, `libwinpthread-1.dll` | as shipped in the Mercury release | GPL-3.0 with GCC Runtime Library Exception / MIT-style | https://www.mingw-w64.org/ |
| Pat — `bin/pat/pat.exe` | 1.0.0 | MIT (`pat-MIT.txt`) | https://github.com/la5nta/pat/tree/v1.0.0 |

The exact release archives (URLs and SHA-256) are pinned in `bins.json`.
