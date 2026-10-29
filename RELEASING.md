# Plugin-Sätze veröffentlichen

## Einmalig durch den Projektinhaber

1. Environment `release` anlegen: Freigabe durch `ra5on`, Deployment nur von
   `main`.
2. Dort `MINISIGN_SECRET_KEY` (Inhalt der geheimen Schlüsseldatei von
   `titanos-release-1`) und `MINISIGN_PASSWORD` hinterlegen, wie in
   `docs/RELEASING.md` von TitanOS. Ohne diese Schlüssel lehnt TitanOS jeden
   Satz ab.
3. Für den Anstoß aus TitanOS einen Fine-grained-Token nur für dieses Repository
   (Recht „Contents: read and write“) als `PLUGINS_DISPATCH_TOKEN` im
   Environment `release` von **TitanOS** hinterlegen.

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
in QEMU (`test-sets`). Erst danach signiert der Job `publish` nach Freigabe, legt
die Releases an und aktualisiert `catalog.json` (Serial + 1). Schlägt etwas fehl,
bleibt der Zeiger unverändert.

## NVIDIA-Treiberupdates

`nvidia-driver.yml` von Hand starten (Treiber `latest` oder eine Version, ein
Kernel-Satz oder die neuesten drei). Signiert wird wieder erst nach Freigabe.
