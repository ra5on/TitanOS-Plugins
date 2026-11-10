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
- **Jede Nacht (`upstream.yml`):** neuere stabile Versionen von Tailscale und
  NetBird werden auf `main` festgeschrieben, danach baut und testet
  `release.yml` einen `common-<n>`. TitanOS signiert ihn ohne Freigabe nur,
  wenn sich nichts als diese Versionen geändert hat (`scripts/plugin-guard.py`
  dort); sonst gibt `ra5on` frei wie immer.

Jeder Lauf baut alle Plugins, packt sie wie TitanOS in ein Release und bootet es
in QEMU (`test-sets`). Erst danach legt der Job `draft` die Sätze als Entwurf an.
Schlägt etwas fehl, entsteht kein Entwurf und der Zeiger bleibt unverändert.

## Herkunftsnachweis

Der Job `draft` stellt für jede Datei eines Satzes einen Herkunftsnachweis aus
(GitHub Artifact Attestation): Er bindet die Datei an `release.yml`, den Commit
und den Lauf. TitanOS prüft ihn vor dem Signieren für jede Datei des Entwurfs
(`gh attestation verify`, Workflow `release.yml` dieses Repositorys, Zweig
`main`). Ein Entwurf, den jemand anders angelegt hat, oder eine im Entwurf
ausgetauschte Datei hat keinen Nachweis und wird nicht signiert. Ein Lauf von
Hand aus einem anderen Zweig als `main` wird deshalb auch mit Freigabe nicht
signiert.

Aktionen in den Abläufen sind auf Commits festgelegt (Kommentar nennt die
Version).

## NVIDIA-Treiberupdates

`nvidia-driver.yml` von Hand starten (Treiber `latest` oder eine Version, ein
Kernel-Satz oder die neuesten drei). Das Ergebnis wird ein Entwurf
`pending-nvidia-<lauf>-<satz>`; TitanOS signiert ihn nach Freigabe und hängt ihn
an den Kernel-Satz.
