#!/usr/bin/env bash
# JuStAI5 installer - one command from an empty Linux machine to a running assistant.
#
#   curl -fsSL https://raw.githubusercontent.com/julianstricker/JuStAI5/main/scripts/install.sh | bash
#
# or, inside a checkout:  ./scripts/install.sh
#
# What it does: checks the platform, installs Docker if needed (asks first), downloads
# JuStAI5 if it is not run from a checkout, creates .env (API key, admin password, LAN
# address for the HTTPS certificate, network range for the camera search, free ports),
# builds and starts everything and prints where to log in.
# Running it again on an installed system keeps .env and only rebuilds/starts.
#
# Options:  -y, --yes       no questions (defaults; values from the environment)
#           --dir DIR       where to download JuStAI5 (default: ./JuStAI5)
#           -h, --help
# Environment (optional): GOOGLE_API_KEY, JUSTAI_ADMIN_PASSWORD, JUSTAI_HTTP_PORT,
#           JUSTAI_HTTPS_PORT, JUSTAI_REPO_URL, COMPOSE_PROJECT_NAME,
#           JUSTAI_INSTALL_LANG (en|de|it; default: from LANG)
set -euo pipefail

# Everything runs inside main(): with `curl | bash` bash must have read the whole script
# before the first command runs, otherwise e.g. docker or apt could swallow the rest of it.
main() {

REPO_URL="${JUSTAI_REPO_URL:-https://github.com/julianstricker/JuStAI5.git}"
TARGET_DIR="$PWD/JuStAI5"
ASSUME_YES=0
MIN_COMPOSE="2.24.0"
HEALTH_TIMEOUT_S=300

# Messages in English, German or Italian: L "english" "deutsch" "italiano"
case "${JUSTAI_INSTALL_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}}" in
  de*) UI_LANG=de ;; it*) UI_LANG=it ;; *) UI_LANG=en ;;
esac
L() { case "$UI_LANG" in de) printf '%s' "$2" ;; it) printf '%s' "$3" ;; *) printf '%s' "$1" ;; esac; }
if [ "$UI_LANG" = de ]; then DOC_INSTALL=docs/de/INSTALLATION.md; DOC_EXAMPLES=docs/de/BEISPIELE.md
else DOC_INSTALL=docs/INSTALLATION.md; DOC_EXAMPLES=docs/EXAMPLES.md; fi

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --dir) TARGET_DIR="$2"; shift ;;
    -h|--help) printf "%s\n" "$(L "Install JuStAI5" "JuStAI5 installieren" "Installare JuStAI5"): ./scripts/install.sh [-y|--yes] [--dir DIR]" \
      "Details: $DOC_INSTALL"; exit 0 ;;
    *) echo "$(L "Unknown option" "Unbekannte Option" "Opzione sconosciuta"): $1 (--help)" >&2; exit 2 ;;
  esac
  shift
done

# ------------------------------------------------------------------ output
if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B='' G='' Y='' R='' N=''; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

# Questions go to the terminal even when the script itself comes from a pipe (curl | bash).
TTY=""
if [ "$ASSUME_YES" = 0 ] && { : </dev/tty; } 2>/dev/null; then TTY=/dev/tty; fi

ask() {  # ask "question" "default" -> answer on stdout
  local answer=""
  if [ -n "$TTY" ]; then
    printf '%s [%s]: ' "$1" "$2" >"$TTY"
    IFS= read -r answer <"$TTY" || true
  fi
  printf '%s' "${answer:-$2}"
}

ask_secret() {  # hidden input, empty allowed
  local answer=""
  if [ -n "$TTY" ]; then
    printf '%s: ' "$1" >"$TTY"
    stty -echo <"$TTY" 2>/dev/null || true
    IFS= read -r answer <"$TTY" || true
    stty echo <"$TTY" 2>/dev/null || true
    printf '\n' >"$TTY"
  fi
  printf '%s' "$answer"
}

yes_no() {  # yes_no "question" -> default yes
  local a
  a="$(ask "$1 ($(L "y/n" "j/n" "s/n"))" "$(L y j s)")"
  case "$a" in j|J|ja|Ja|y|Y|yes|Yes|s|S|si|sì|Si) return 0 ;; *) return 1 ;; esac
}

version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

SUDO=""
if [ "$(id -u)" != 0 ]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

# ------------------------------------------------------------------ platform
step "$(L "Checking the system" "System prüfen" "Controllo del sistema")"
[ "$(uname -s)" = "Linux" ] || die "$(L "JuStAI5 runs on Linux" "JuStAI5 läuft auf Linux" "JuStAI5 funziona su Linux") ($(uname -s))."
case "$(uname -m)" in
  x86_64|amd64) ok "Linux $(uname -m)" ;;
  *) die "$(L "JuStAI5 needs an x86_64 processor" "JuStAI5 braucht einen x86_64-Prozessor" "JuStAI5 richiede un processore x86_64") ($(uname -m)). $(L "Raspberry Pi/ARM is not supported." "Raspberry Pi/ARM wird nicht unterstützt." "Raspberry Pi/ARM non è supportato.")" ;;
esac
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${mem_kb:-0}" -lt 3500000 ]; then
  warn "$((mem_kb / 1024)) MB RAM - $(L "at least 4 GB recommended" "empfohlen sind mindestens 4 GB" "consigliati almeno 4 GB")."
else
  ok "$((mem_kb / 1024 / 1024)) GB RAM"
fi

# ------------------------------------------------------------------ docker
step "$(L "Checking Docker" "Docker prüfen" "Controllo di Docker")"
if ! command -v docker >/dev/null 2>&1; then
  warn "$(L "Docker is not installed." "Docker ist nicht installiert." "Docker non è installato.")"
  if [ "$ASSUME_YES" = 1 ] || yes_no "$(L "Install Docker now (official script from get.docker.com)?" "Docker jetzt installieren (offizielles Skript von get.docker.com)?" "Installare Docker ora (script ufficiale di get.docker.com)?")"; then
    command -v curl >/dev/null 2>&1 || die "$(L "curl is missing" "curl fehlt" "manca curl"): sudo apt-get install -y curl"
    curl -fsSL https://get.docker.com | $SUDO sh
    if [ "$(id -u)" != 0 ]; then
      $SUDO usermod -aG docker "$USER" || true
      NEED_RELOGIN=1
    fi
  else
    die "$(L "JuStAI5 needs Docker. Guide" "Ohne Docker geht es nicht. Anleitung" "Senza Docker non funziona. Guida"): $DOC_INSTALL"
  fi
fi

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
  if [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER="$SUDO docker"
    NEED_RELOGIN=1
  else
    $SUDO systemctl start docker 2>/dev/null || true
    if docker info >/dev/null 2>&1; then DOCKER="docker"
    elif [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then DOCKER="$SUDO docker"
    else die "$(L "Docker is not running" "Docker läuft nicht" "Docker non è in esecuzione") (sudo systemctl start docker)."
    fi
  fi
fi
compose_version="$($DOCKER compose version --short 2>/dev/null | sed 's/^v//' || true)"
[ -n "$compose_version" ] || die "$(L "Docker Compose is missing" "Docker Compose fehlt" "Manca Docker Compose"): sudo apt-get install -y docker-compose-plugin"
version_ge "$compose_version" "$MIN_COMPOSE" \
  || die "Docker Compose $compose_version $(L "is too old" "ist zu alt" "è troppo vecchio") (>= $MIN_COMPOSE): curl -fsSL https://get.docker.com | sudo sh"
ok "Docker $($DOCKER version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), Compose $compose_version"

# ------------------------------------------------------------------ source
step "$(L "Getting JuStAI5" "JuStAI5 bereitstellen" "Download di JuStAI5")"
is_checkout() { [ -f "$1/docker-compose.yml" ] && [ -f "$1/docker/core.Dockerfile" ]; }
script_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$script_dir" ] && is_checkout "$script_dir/.."; then
  APP_DIR="$(cd "$script_dir/.." && pwd)"
elif is_checkout "$PWD"; then
  APP_DIR="$PWD"
elif is_checkout "$TARGET_DIR"; then
  APP_DIR="$(cd "$TARGET_DIR" && pwd)"
else
  if ! command -v git >/dev/null 2>&1; then
    command -v apt-get >/dev/null 2>&1 || die "$(L "git is missing - please install it." "git fehlt - bitte installieren." "manca git - installarlo.")"
    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq git >/dev/null
  fi
  git clone --depth 1 "$REPO_URL" "$TARGET_DIR" </dev/null
  APP_DIR="$(cd "$TARGET_DIR" && pwd)"
fi
cd "$APP_DIR"
ok "$(L "Folder" "Ordner" "Cartella"): $APP_DIR"

# ------------------------------------------------------------------ .env
lan_ip() {
  local ip=""
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
  [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  printf '%s' "${ip:-127.0.0.1}"
}

port_in_use() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH "sport = :$1" 2>/dev/null | grep -q .
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}

free_port() {  # free_port 8080 -> 8080 or the next free one
  local p="$1"
  while port_in_use "$p"; do p=$((p + 1)); done
  printf '%s' "$p"
}

set_env() {  # set_env KEY VALUE - replaces "KEY=" or "# KEY=", otherwise appends
  KEY="$1" VALUE="$2" awk '
    BEGIN { k = ENVIRON["KEY"]; line = k "=" ENVIRON["VALUE"] }
    !done && ($0 ~ "^" k "=" || $0 ~ "^# *" k "=") { print line; done = 1; next }
    { print }
    END { if (!done) print line }' .env >.env.tmp
  cat .env.tmp >.env && rm -f .env.tmp  # keeps the permissions (600) of .env
}

# An installation without .env (started with the defaults) already has a core container:
# keep its ports instead of treating them as taken, and never print its password.
EXISTING=0
[ -n "$($DOCKER compose ps -a -q core 2>/dev/null </dev/null)" ] && EXISTING=1
published_port() {  # published_port 8080 -> host port of the running core, or empty
  $DOCKER compose port core "$1" 2>/dev/null </dev/null | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n1
}

if [ -f .env ]; then
  ok "$(L "Keeping the existing settings (.env)." "Vorhandene Einstellungen (.env) werden beibehalten." "Le impostazioni esistenti (.env) vengono mantenute.")"
  FRESH_ENV=0
else
  FRESH_ENV=1
  step "$(L "Settings" "Einstellungen" "Impostazioni")"
  cp .env.example .env
  chmod 600 .env
  IP="$(lan_ip)"
  HTTP_PORT="$(published_port 8080)"; HTTPS_PORT="$(published_port 8443)"
  [ -n "$HTTP_PORT" ] || HTTP_PORT="$(free_port "${JUSTAI_HTTP_PORT:-8080}")"
  [ -n "$HTTPS_PORT" ] || HTTPS_PORT="$(free_port "${JUSTAI_HTTPS_PORT:-8443}")"
  [ "$HTTPS_PORT" != "$HTTP_PORT" ] || HTTPS_PORT="$(free_port $((HTTP_PORT + 1)))"
  [ "$HTTP_PORT" = "${JUSTAI_HTTP_PORT:-8080}" ] || warn "Port ${JUSTAI_HTTP_PORT:-8080} $(L "is taken, using" "ist belegt, verwende" "è occupata, uso") $HTTP_PORT."
  [ "$HTTPS_PORT" = "${JUSTAI_HTTPS_PORT:-8443}" ] || warn "Port ${JUSTAI_HTTPS_PORT:-8443} $(L "is taken, using" "ist belegt, verwende" "è occupata, uso") $HTTPS_PORT."
  set_env JUSTAI_HTTP_PORT "$HTTP_PORT"
  set_env JUSTAI_HTTPS_PORT "$HTTPS_PORT"
  set_env JUSTAI_PUBLIC_URL "http://$IP:$HTTP_PORT"
  if [ "$IP" != "127.0.0.1" ]; then
    set_env JUSTAI_TLS_NAMES "[\"$IP\"]"
    set_env JUSTAI_DISCOVERY_DEFAULT_CIDRS "[\"${IP%.*}.0/24\"]"
    ok "$(L "Address in the home network" "Adresse im Heimnetz" "Indirizzo nella rete di casa"): $IP ($(L "camera search in" "Kamerasuche in" "ricerca telecamere in") ${IP%.*}.0/24)"
  fi

  key="${GOOGLE_API_KEY:-}"
  if [ -z "$key" ] && [ -n "$TTY" ]; then
    printf '\n%s\n%s\n' "$(L "To answer, the assistant needs a language model. The easiest:" \
      "Für die Antworten braucht der Assistent ein Sprachmodell. Am einfachsten:" \
      "Per rispondere l'assistente ha bisogno di un modello linguistico. Il modo più semplice:")" \
      "$(L "a free Google API key" "kostenloser Google-API-Key" "una chiave API Google gratuita") - https://aistudio.google.com (Get API key)." >"$TTY"
    key="$(ask_secret "$(L "Paste the Google API key (empty = later in the interface)" \
      "Google-API-Key einfügen (leer = später in der Oberfläche)" \
      "Incolla la chiave API Google (vuoto = più tardi nell'interfaccia)")")"
  fi
  if [ -n "$key" ]; then
    case "$key" in *"'"*|*[[:space:]]*) die "$(L "The API key contains invalid characters." "Der API-Key enthält ungültige Zeichen." "La chiave API contiene caratteri non validi.")" ;; esac
    set_env GOOGLE_API_KEY "'$key'"
    ok "$(L "API key saved" "API-Key gespeichert" "Chiave API salvata")"
  elif [ "$EXISTING" = 0 ]; then
    warn "$(L "No API key - enter it later under Plugins -> Gemini (or use a local model, docs/AI.md)." "Kein API-Key - später unter Plugins -> Gemini eintragen (oder lokales Modell, docs/de/AI.md)." "Nessuna chiave API - inserirla più tardi in Plugin -> Gemini (o modello locale, docs/AI.md).")"
  fi

  pw="${JUSTAI_ADMIN_PASSWORD:-}"
  while [ -z "$pw" ] && [ -n "$TTY" ]; do
    pw="$(ask_secret "$(L "Choose an admin password (min. 8 characters, empty = random)" "Admin-Passwort festlegen (mind. 8 Zeichen, leer = zufällig erzeugen)" "Scegli una password admin (min. 8 caratteri, vuoto = casuale)")")"
    [ -z "$pw" ] && break
    if [ "${#pw}" -lt 8 ]; then warn "$(L "At least 8 characters." "Mindestens 8 Zeichen." "Almeno 8 caratteri.")"; pw=""; continue; fi
    case "$pw" in *"'"*) warn "$(L "Please without an apostrophe" "Bitte ohne Apostroph" "Senza apostrofo, per favore") (')."; pw=""; continue ;; esac
    [ "$(ask_secret "$(L "Repeat the password" "Passwort wiederholen" "Ripeti la password")")" = "$pw" ] || { warn "$(L "Does not match." "Stimmt nicht überein." "Non corrisponde.")"; pw=""; }
  done
  if [ -n "$pw" ]; then
    set_env JUSTAI_ADMIN_PASSWORD "'$pw'"
    ok "$(L "Admin password saved (.env, readable only by you)" "Admin-Passwort gespeichert (.env, nur für dich lesbar)" "Password admin salvata (.env, leggibile solo da te)")"
  fi
  unset key pw
fi

HTTP_PORT="$(sed -n 's/^JUSTAI_HTTP_PORT=//p' .env | tail -n1)"; HTTP_PORT="${HTTP_PORT:-8080}"
HTTPS_PORT="$(sed -n 's/^JUSTAI_HTTPS_PORT=//p' .env | tail -n1)"; HTTPS_PORT="${HTTPS_PORT:-8443}"

# ------------------------------------------------------------------ start
step "$(L "Building and starting (a few minutes the first time, downloads about 3 GB)" "Bauen und starten (beim ersten Mal einige Minuten, lädt ca. 3 GB)" "Build e avvio (la prima volta alcuni minuti, scarica circa 3 GB)")"
$DOCKER compose up -d --build </dev/null

step "$(L "Waiting until JuStAI5 is ready" "Warten, bis JuStAI5 bereit ist" "Attesa che JuStAI5 sia pronto")"
health() {
  if command -v curl >/dev/null 2>&1; then curl -fsS "http://127.0.0.1:$HTTP_PORT/api/health" 2>/dev/null
  else wget -qO- "http://127.0.0.1:$HTTP_PORT/api/health" 2>/dev/null; fi
}
waited=0
until health | grep -q '"ok":true'; do
  [ "$waited" -lt "$HEALTH_TIMEOUT_S" ] || die "$(L "JuStAI5 does not answer. Logs" "JuStAI5 antwortet nicht. Logs" "JuStAI5 non risponde. Log"): $DOCKER compose logs core"
  sleep 3; waited=$((waited + 3))
done
ok "$(L "JuStAI5 is running" "JuStAI5 läuft" "JuStAI5 è in esecuzione")"

# ------------------------------------------------------------------ summary
IP="$(lan_ip)"
if [ "$FRESH_ENV" = 0 ] || [ "$EXISTING" = 1 ]; then
  PW_TEXT="$(L "unchanged (your previous password)" "unverändert (dein bisheriges Passwort)" "invariata (la tua password precedente)")"
elif grep -q "^JUSTAI_ADMIN_PASSWORD=" .env; then
  PW_TEXT="$(L "the password you just chose (also in" "das Passwort, das du gerade festgelegt hast (steht auch in" "la password appena scelta (anche in") $APP_DIR/.env)"
else
  PW_TEXT="$($DOCKER compose exec -T core cat /data/initial_admin_password.txt </dev/null 2>/dev/null \
    | sed -n 's/^password: //p' || true)"
  [ -n "$PW_TEXT" ] && PW_TEXT="$PW_TEXT  ($(L "please change it under Settings -> Users" "bitte gleich unter Einstellungen -> Benutzer ändern" "cambiala subito in Impostazioni -> Utenti"))" \
    || PW_TEXT="$DOCKER compose exec core cat /data/initial_admin_password.txt"
fi

cat <<EOF

${G}${B}$(L "JuStAI5 is installed." "JuStAI5 ist installiert." "JuStAI5 è installato.")${N}

  $(L "Interface:    " "Oberfläche:   " "Interfaccia:  ") ${B}http://$IP:$HTTP_PORT${N}
  $(L "User:         " "Benutzer:     " "Utente:       ") admin
  $(L "Password:     " "Passwort:     " "Password:     ") $PW_TEXT

  $(L "Phone/tablet as microphone, speaker and camera:" "Handy/Tablet als Mikrofon, Lautsprecher und Kamera:" "Telefono/tablet come microfono, altoparlante e telecamera:")
                 https://$IP:$HTTPS_PORT/app
                 ($(L "first Settings -> Device app: install the certificate" "vorher Einstellungen -> Geräte-App: Zertifikat installieren" "prima Impostazioni -> App dispositivo: installare il certificato"))
  $(L "TV/monitor as screen:" "Fernseher/Monitor als Bildschirm:" "TV/monitor come schermo:")
                 http://$IP:$HTTP_PORT/display

  $(L "Next steps:   " "Nächste Schritte:" "Prossimi passi:") $APP_DIR/$DOC_INSTALL ($(L "from step 5" "ab Schritt 5" "dal passo 5"))
  $(L "Ideas:        " "Ideen:           " "Idee:          ") $APP_DIR/$DOC_EXAMPLES
  $(L "Update:       " "Aktualisieren:   " "Aggiornare:    ") cd $APP_DIR && git pull && ./scripts/install.sh
EOF
if [ "${NEED_RELOGIN:-0}" = 1 ]; then
  printf '\n%s!%s %s\n' "$Y" "$N" "$(L "Log out and in once so you can use Docker without sudo." "Einmal ab- und wieder anmelden, damit du Docker ohne sudo verwenden kannst." "Esci e rientra una volta per usare Docker senza sudo.")"
fi
}

main "$@"
