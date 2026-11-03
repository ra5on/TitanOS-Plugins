# titanos-keys

Community-Plugin, das die öffentlichen Schlüssel `titanos-release-2` und
`titanos-recovery-2` (aus `keys/`) nach `/usr/share/titanos/update-keys`
legt. Damit prüft ein NAS mit TitanOS 0.45.1 das Update auf 0.46.2 (die alten
Signierschlüssel sind verloren). Bewusst unsigniert und nicht Teil eines
Satzes; liegt als Release `titanos-keys-2`.

Bauen:

    mkdir -p stage/usr/share/titanos/update-keys
    cp keys/titanos-release-2.pub keys/titanos-recovery-2.pub stage/usr/share/titanos/update-keys/
    cp extras/titanos-keys/plugin.json stage/
    sh scripts/make-plugin.sh titanos-keys 2 stage out

Geprüft in TitanOS mit `scripts/test-key-plugin-update.py`.
