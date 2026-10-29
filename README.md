# TitanOS-Plugins

Offizielle Plugins für [TitanOS](https://github.com/ra5on/TitanOS): signierte
`systemd-sysext`-Abbilder, die TitanOS unter **Plugins** anbietet. Wie TitanOS
sie findet und prüft, steht in
[`docs/PLUGIN-REPO.md`](https://github.com/ra5on/TitanOS/blob/main/docs/PLUGIN-REPO.md),
was die einzelnen Plugins können, in
[`docs/PLUGINS.md`](https://github.com/ra5on/TitanOS/blob/main/docs/PLUGINS.md).

## Sätze

Jede Veröffentlichung ist ein **Satz**, also eine GitHub-Release mit festem Tag:

| Satz | Inhalt | Neu gebaut |
| --- | --- | --- |
| `common-<n>` | Tailscale, NetBird, Coral USB, Intel GPU Tools | wenn sich eines dieser Plugins ändert; unveränderte behalten ihren Bau und ihre Version |
| `kernel-<Kernelpaket>-<n>` | NVIDIA (mit Bauumgebung für das NAS), `wangxun-nic`, `intel-qat`, `it87-extended` | wenn ein volles TitanOS-Release einen neuen Kernel bringt |

Die feste Release `catalog` enthält den signierten Zeiger `catalog.json` auf die
aktuellen Sätze. Releases werden nie als „latest“ markiert. Signiert ist alles
mit denselben Schlüsseln wie TitanOS (`keys/`).

NVIDIA-Treiberupdates (`nvidia-driver.yml`) hängen an den Kernel-Sätzen; der
Satz selbst und der Zeiger bleiben dabei unverändert.

## Aufbau

- `plugins/<name>/` – was ein Plugin mitbringt (`root/`), Paketsperren
  (`packages.lock.json`) und Lizenzhinweise; `plugins/drivers/drivers.json`
  beschreibt die Treiber-Plugins mit festen Commits und SHA-256.
- `scripts/` – Bau (`make-*-plugin.*`, `make-driver-plugins.py`,
  `make-plugin.sh`), Sätze und Zeiger (`sets.py`), NVIDIA-Updates
  (`nvidia-update-release.py`), Tests in `scripts/tests/`.
- Die Katalogtexte und Hardware-Regeln (`plugins/catalog/<name>.json`) liegen in
  TitanOS, weil das Abbild sie auch ohne Netz braucht. Gebaut wird immer gegen
  ein TitanOS-Abbild: `TITANOS` zeigt auf den TitanOS-Checkout mit gebautem
  `build/mkosi.output`.

## Lokal bauen

```bash
# im TitanOS-Checkout: Abbild bauen (siehe dessen docs/DEVELOPMENT.md)
make build VERSION=0.99.0-dev && MKOSI_SUDO=1 VERSION=0.99.0-dev scripts/make-zip.sh
# hier: Plugins mit Satz-Revision 1 bauen, Ergebnis in out/plugins
sudo env PATH="$PATH" TITANOS=../TitanOS scripts/make-tools-plugins.sh 1
sudo env PATH="$PATH" TITANOS=../TitanOS scripts/make-nvidia-plugin.sh 1
sudo env PATH="$PATH" TITANOS=../TitanOS python3 scripts/make-driver-plugins.py 1
python3 -m unittest discover -s scripts/tests
```

Veröffentlichen: [RELEASING.md](RELEASING.md).

## Lizenz

Eigener Code: FSL-1.1-ALv2 (Fair Source, `LICENSE.md`), wie TitanOS. Jedes Plugin
enthält die Originallizenzen seiner Bestandteile (`*-licenses.tar.gz`);
Kernelmodule sind GPL, ihre Quellen liegen als `*-sources.tar.gz` bzw.
`nvidia-kernel-sources.tar.gz` bei. Beiträge nur mit dem CLA von TitanOS.
