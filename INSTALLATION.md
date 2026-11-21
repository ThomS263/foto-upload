# Foto-Upload manuell installieren

Auf CasaOS kannst du Foto-Upload vollständig im Browser installieren. Auf einem anderen Linux-Server kannst du aus dem Git-Checkout starten. Für die Installation aus einem Download gibt es fertige Images für Intel/AMD und 64-Bit-ARM. Wähle einen der folgenden Wege.

Für Android gibt es zusätzlich eine Begleit-App mit QR-Scanner, Teilen-Funktion und Serverauswahl. [Android-App und aktuelle APK herunterladen](https://github.com/ThomS263/foto_upload_offiziell_androidapp/releases/latest)

## 1. In CasaOS über die Oberfläche

1. Die verlinkte YAML im Browser öffnen und den **gesamten Text** kopieren. [CasaOS-Konfiguration für Foto-Upload 3.1.1](https://raw.githubusercontent.com/ThomS263/foto_upload_offiziel/v3.1.1/Apps/FotoUpload/docker-compose.yml)
2. Im CasaOS-Dashboard den **App Store → Custom Install** öffnen. Oben rechts das **Import**-Symbol wählen, die YAML einfügen und bestätigen. [CasaOS-Dokumentation](https://wiki.casaos.io/en/apps)
3. Im Installationsdialog unter **Umgebungsvariablen** bei `PHOTO_ADMIN_PASSWORD` ein eigenes Erstpasswort eingeben. Bei einer bestehenden externen HTTPS-Adresse kannst du auch `PHOTO_PUBLIC_URL` setzen. Der Host-Port ist standardmäßig `8080`, der Datenordner auf dem Server `/DATA/AppData/foto-upload/data`.
4. **Installieren** wählen. CasaOS lädt das Image `ghcr.io/thoms263/foto_upload_offiziel:3.1.1` für die passende Architektur. Öffne die neue Kachel **Foto-Upload**, wähle **Verwaltung** und melde dich mit deinem Erstpasswort an.

Wer das Passwortfeld leer lässt, erhält beim ersten Start ein Zufallspasswort. Du kannst es im Serverterminal mit `docker exec foto-upload cat /data/.initial-admin-password` auslesen.

## 2. Mit Git und Docker Compose

Die Befehle gehören in das Terminal des Linux- oder CasaOS-Servers. Prüfe zuerst, ob Docker läuft und Compose v2 verfügbar ist.

~~~bash
docker info --format '{{.ServerVersion}}'
docker compose version
~~~

Falls Docker den Zugriff verweigert, verwende ein Konto mit Docker-Berechtigung oder führe die Docker-Befehle mit `sudo docker …` aus. Für den Git-Weg brauchst du außerdem Git und für den ersten Build eine Internetverbindung. [Docker Compose für Linux installieren](https://docs.docker.com/compose/install/linux/)

Im gewünschten Installationsverzeichnis ausführen. Der Befehl `git clone` legt den Unterordner `foto-upload` an.

~~~bash
git clone https://github.com/ThomS263/foto_upload_offiziel.git foto-upload
cd foto-upload
docker compose up -d --build --wait
docker compose exec -T foto-upload cat /data/.initial-admin-password
~~~

Den letzten Befehl im Terminal des Servers ausführen und das angezeigte **Erstpasswort** für die Anmeldung verwenden. Der Datenordner `./data` liegt neben `compose.yaml` und wird beim ersten Start angelegt. Anschließend weiter bei **Erste Anmeldung und QR-Code**.

## 3. Direkt aus den Release-Dateien

1. Im Terminal des Servers `uname -m` ausführen. Für `x86_64` das Archiv **amd64**, für `aarch64` oder `arm64` das Archiv **arm64** wählen. Außerdem die Import-YAML für das lokale Image laden. [Archiv AMD64](https://github.com/ThomS263/foto_upload_offiziel/releases/download/v3.1.1/foto-upload-3.1.1-linux-amd64.tar.gz) · [Archiv ARM64](https://github.com/ThomS263/foto_upload_offiziel/releases/download/v3.1.1/foto-upload-3.1.1-linux-arm64.tar.gz) · [Import-YAML für geladenes Image](https://github.com/ThomS263/foto_upload_offiziel/releases/download/v3.1.1/foto-upload-casaos.yaml)
2. Das Docker-Archiv auf den Server übertragen. Dort im Ordner mit dem Download den passenden Befehl ausführen. Das Image wird in die lokale Docker-Installation geladen.

   ~~~bash
   # Intel- oder AMD-Server
   docker load --input foto-upload-3.1.1-linux-amd64.tar.gz
   ~~~

   ~~~bash
   # 64-Bit-ARM-Server
   docker load --input foto-upload-3.1.1-linux-arm64.tar.gz
   ~~~

3. In CasaOS den **App Store → Custom Install** öffnen, **Import** wählen und den gesamten Inhalt von `foto-upload-casaos.yaml` einfügen. Den Dateipfad für den Speicher prüfen und die Installation starten. Standardmäßig speichert CasaOS unter `/DATA/AppData/foto-upload/data` und gibt Port `8080` frei. [CasaOS-Anleitung zur benutzerdefinierten Installation](https://wiki.casaos.io/en/apps)
4. Im Serverterminal das Erstpasswort auslesen.

   ~~~bash
   docker exec foto-upload cat /data/.initial-admin-password
   ~~~

**Installation derselben Downloads direkt im Terminal.** Wenn du die Oberfläche überspringen möchtest, lege `foto-upload-casaos.yaml` auf dem Server ab. Nach `docker load` starte die App aus diesem Verzeichnis. Dabei verwendet Docker das lokal geladene Image.

~~~bash
docker compose -f foto-upload-casaos.yaml up -d --pull never --wait
docker exec foto-upload cat /data/.initial-admin-password
~~~

Die Datei `SHA256SUMS` im Release enthält die Prüfsummen der Downloads. Zum Vergleich für eine einzelne Datei z. B. `sha256sum foto-upload-3.1.1-linux-amd64.tar.gz` ausführen.

## 4. Direkt mit Python

Für Linux mit Python 3.12 und Unterstützung für virtuelle Umgebungen. Der folgende Befehl startet den Webserver im Vordergrund.

~~~bash
git clone https://github.com/ThomS263/foto_upload_offiziel.git foto-upload
cd foto-upload
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 --timeout 180 'foto_upload:create_app()'
~~~

In einem zweiten Terminal im selben Projektverzeichnis `cat data/.initial-admin-password` ausführen. Eigene Einstellungen wie `PHOTO_PUBLIC_URL` oder `PHOTO_DATA_DIR` vor dem Start als Umgebungsvariablen exportieren.

## Erste Anmeldung und QR-Code

1. Handy und Server mit demselben Netz verbinden. Im Browser `http://SERVER-IP:8080` öffnen und `SERVER-IP` durch die LAN-Adresse des Servers ersetzen, etwa `192.168.1.20`. Unter Linux zeigt `hostname -I` die verfügbaren Adressen. Für einen QR-Code, den ein anderes Gerät scannen soll, die Seite mit dieser Adresse öffnen.
2. **Verwaltung** wählen, mit dem Erstpasswort anmelden und unter **Adminpasswort** ein eigenes Passwort speichern. Danach wird die Datei mit dem Erstpasswort entfernt.
3. Unter **Album anlegen** den Namen und ein Albumpasswort eingeben. Zur Startseite zurückkehren, das Album öffnen und ein Foto hochladen. Sobald „1 von 1 gespeichert“ erscheint, ist es in der Galerie verfügbar.
4. Gäste scannen den QR-Code auf der Startseite. Für einen direkten Zugang zu einem bestimmten Album in der Verwaltung **Gästelink ohne Passwort freigeben** aktivieren und speichern. Beim Abschalten der Freigabe werden die zugehörigen Gästelinks widerrufen.

Die App verwendet für den Standard-QR die Adresse, mit der die Seite geöffnet wurde. Gibt es einen vorhandenen HTTPS-Reverse-Proxy oder Tunnel, trage die eigene öffentliche Basisadresse als `PHOTO_PUBLIC_URL` ein. Bei der Git-Installation eine Datei `.env` neben `compose.yaml` anlegen und anschließend `docker compose up -d --wait` ausführen. Beispielwerte durch die eigenen Angaben ersetzen.

~~~dotenv
PHOTO_PUBLIC_URL=https://fotos.example.org
PHOTO_PORT=8080
~~~

In CasaOS lässt sich `PHOTO_PUBLIC_URL` in den App-Einstellungen ändern. Den Host-Port bei Bedarf unter **Ports** anpassen. Den Container-Port dabei auf `8080` lassen. Beim Scannen über Mobilfunk muss die eingetragene HTTPS-Adresse auch von außerhalb des Heimnetzes erreichbar sein.

Einfacher ist die Einstellung direkt in Foto-Upload: **Verwaltung → Öffentliche Adresse & QR-Codes** öffnen, die vollständige Funnel-Adresse eintragen und speichern. Sie wird im persistenten Datenordner gespeichert. Der CasaOS-Containerpfad `/data` ist bereits vorkonfiguriert und muss dafür nicht bearbeitet werden.

## Wenn der erste Start stockt

| Meldung oder Symptom | So gehst du vor |
| --- | --- |
| `destination path 'foto-upload' already exists` | Bei einem vorhandenen Checkout dieser App mit `cd foto-upload` in dessen Verzeichnis wechseln und mit dem Compose-Befehl fortfahren. Für eine zweite Installation einen eigenen Verzeichnisnamen verwenden. |
| `no configuration file provided` | Für den Git-Weg in den Ordner mit `compose.yaml` wechseln. Für den Release-Download ausdrücklich `docker compose -f foto-upload-casaos.yaml` verwenden. |
| CasaOS zeigt „App may not be available“ | Prüfe unter den Einstellungen der Kachel die Webadresse. Schema `http`, Web-UI-Port gleich dem veröffentlichten Host-Port und Pfad `/` einstellen. Bei der Git-Installation `git pull --ff-only` und `docker compose up -d --build` im Projektordner ausführen. Die Kachel erneut öffnen. |
| `unknown flag: --wait` | `docker compose up -d --build` ausführen. Bei der Release-YAML `docker compose -f foto-upload-casaos.yaml up -d --pull never` verwenden. Sobald `docker compose ps` bzw. `docker ps` den Container als `healthy` zeigt, das Erstpasswort lesen. |
| `port is already allocated` | Für die Git-Installation `PHOTO_PORT=8081` in `.env` setzen und Compose erneut starten. Bei der CasaOS-YAML den veröffentlichten Port auf `8081` setzen. Die Seite anschließend über diesen Port öffnen. |
| `denied` beim Abruf des Images | Das Docker-Archiv für die eigene Architektur aus dem öffentlichen Release mit `docker load --input DATEINAME.tar.gz` laden und den Terminal-Befehl mit `--pull never` aus Variante 3 verwenden. |
| Erstpasswort-Datei fehlt | Beim Erststart warten, bis der Container `healthy` meldet. Wurde `PHOTO_ADMIN_PASSWORD` gesetzt oder das Passwort bereits geändert, mit diesem Passwort anmelden. |

## Betrieb, Update und Sicherung

- **Status prüfen.** Auf dem Server `curl -fsS 'http://127.0.0.1:8080/health?ready=1'` ausführen. Bei erfolgreichem Start enthält die Antwort `"ok":true`. Für die Git-Installation zeigen `docker compose ps` und `docker compose logs --tail 60 foto-upload` den Dienstzustand und die letzten Meldungen.
- **Aktualisieren.** Vor dem Update unter **Verwaltung → Sicherung & Pflege → Backup herunterladen** eine Sicherung erstellen. Bei der Git-Installation im Projektordner `./update.sh` ausführen. Bei der Installation aus einem Release das neue Archiv für dieselbe Architektur laden und die neue YAML mit demselben Speicherpfad und den eigenen Einstellungen anwenden.
- **Wiederherstellen.** Den Dienst stoppen, das Backup in ein leeres Datenverzeichnis entpacken, dieses wieder als `/data` einbinden und den Dienst starten. Die Sicherung enthält auch Zugangsdaten und gehört auf einen privaten Speicher. Bei einer externen Konfiguration von `PHOTO_ADMIN_PASSWORD_HASH` denselben Wert wieder setzen.
- **Zweite Kopie.** Einen zweiten Datenträger als weiteres Volume, beispielsweise unter `/backup`, einbinden und `PHOTO_BACKUP_DIR=/backup` im Container setzen. Bei jedem Backup-Download entsteht dort eine zusätzliche ZIP-Datei. Unter „Sicherung & Pflege“ kann zusätzlich eine tägliche automatische Sicherung aktiviert werden. Die Verwaltung zeigt den letzten Erfolg und Fehler. Solange die App läuft, prüft sie jede Minute, ob eine Sicherung fällig ist.
- **Speicherplatz.** Ein Original darf bis zu 2 GiB groß sein. Die App lässt beim Hochladen mindestens 1 GB Speicher frei. Nach einem Verbindungsabbruch auf demselben Gerät im selben Browser dieselbe Datei innerhalb von 24 Stunden erneut auswählen, um einen großen Upload fortzusetzen.
