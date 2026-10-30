# Plugin-Sätze veröffentlichen

## Signieren

Dieses Repository hat **keinen** Signaturschlüssel. Getestete Sätze und
Treiberupdates werden hier nur als Entwurf (unveröffentlichte Release)
angelegt. `ra5on/TitanOS` signiert sie mit `.github/workflows/plugin-sign.yml`
in seinem Environment `release` nach Freigabe durch `ra5on`, veröffentlicht sie
und aktualisiert `catalog.json` (Serial + 1). Dafür braucht TitanOS das
Repository-Secret `PLUGINS_DISPATCH_TOKEN` (Fine-grained-Token nur für dieses
Repository, Contents: read and write); damit stößt es hier auch Bauten an.

TitanOS signiert mit seinem eigenen Skript (`scripts/sign-plugin-set.py`) und
führt keinen Code aus diesem Repository neben dem Schlüssel aus. Hier gibt es
deshalb kein `sets.py sign`/`pointer` und kein `nvidia-update-release.py sign`
mehr; `sets.py rehearsal-sign` signiert nur Proben mit dem Wegwerf-Schlüssel und
bricht ab, sobald `MINISIGN_PASSWORD` gesetzt ist. Dieses Repository hat kein
Environment `release` und keine Signatur-Secrets.

## Abläufe (`.github/workflows/release.yml`)

- **Volles TitanOS-Release:** Dessen Release-Workflow schickt
  `repository_dispatch` `titanos-release` mit Version, Commit, Kernel und
  Kernelpaket und wartet. Hier wird das Abbild aus genau diesem Commit gebaut;
  stimmt sein Kernel nicht mit dem gemeldeten überein, bricht der Lauf ab. Fehlt
  im Katalog ein Satz für diesen Kernel, entsteht `kernel-<Kernelpaket>-<n>`;
  gibt es noch keinen gemeinsamen Satz, auch `common-<n>`.
- **Änderung an Tailscale, NetBird, Coral oder Intel GPU Tools auf `main`:**
  neuer `common-<n>` gegen das neueste TitanOS-Release. Plugins mit
  unveränderten Eingaben behalten Bau und Version des vorigen Satzes; ändert sich
  nichts, wird nichts veröffentlicht. `minBase` ist dieses Release: Ältere
  Systeme behalten ihren bisherigen Satz.
- **Von Hand:** Release, Sätze und erzwungener Neubau wählbar.

Jeder Lauf baut alle Plugins, packt sie wie TitanOS in ein Release und bootet es
in QEMU (`test-sets`). Erst danach legt der Job `draft` die Sätze als Entwurf an.
Schlägt etwas fehl, entsteht kein Entwurf und der Zeiger bleibt unverändert.

## NVIDIA-Treiberupdates

`nvidia-driver.yml` von Hand starten (Treiber `latest` oder eine Version, ein
Kernel-Satz oder die neuesten drei). Das Ergebnis wird ein Entwurf
`pending-nvidia-<lauf>-<satz>`; TitanOS signiert ihn nach Freigabe und hängt ihn
an den Kernel-Satz.
