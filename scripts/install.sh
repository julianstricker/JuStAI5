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
#           JUSTAI_HTTPS_PORT, JUSTAI_REPO_URL, COMPOSE_PROJECT_NAME
set -euo pipefail

# Everything runs inside main(): with `curl | bash` bash must have read the whole script
# before the first command runs, otherwise e.g. docker or apt could swallow the rest of it.
main() {

REPO_URL="${JUSTAI_REPO_URL:-https://github.com/julianstricker/JuStAI5.git}"
TARGET_DIR="$PWD/JuStAI5"
ASSUME_YES=0
MIN_COMPOSE="2.24.0"
HEALTH_TIMEOUT_S=300

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --dir) TARGET_DIR="$2"; shift ;;
    -h|--help) printf "%s\n" "JuStAI5 installieren: ./scripts/install.sh [-y|--yes] [--dir ORDNER]" \
      "Details: docs/INSTALLATION.md"; exit 0 ;;
    *) echo "Unbekannte Option: $1 (Hilfe: --help)" >&2; exit 2 ;;
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

ask() {  # ask "Frage" "Standard" -> answer on stdout
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

yes_no() {  # yes_no "Frage" j|n
  local a
  a="$(ask "$1 (j/n)" "$2")"
  case "$a" in j|J|ja|Ja|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

SUDO=""
if [ "$(id -u)" != 0 ]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

# ------------------------------------------------------------------ platform
step "System prüfen"
[ "$(uname -s)" = "Linux" ] || die "JuStAI5 läuft auf Linux (gefunden: $(uname -s))."
case "$(uname -m)" in
  x86_64|amd64) ok "Linux $(uname -m)" ;;
  *) die "JuStAI5 braucht einen x86_64-Prozessor (gefunden: $(uname -m)). Raspberry Pi/ARM wird nicht unterstützt." ;;
esac
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${mem_kb:-0}" -lt 3500000 ]; then
  warn "Nur $((mem_kb / 1024)) MB Arbeitsspeicher - empfohlen sind mindestens 4 GB."
else
  ok "$((mem_kb / 1024 / 1024)) GB Arbeitsspeicher"
fi

# ------------------------------------------------------------------ docker
step "Docker prüfen"
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker ist nicht installiert."
  if [ "$ASSUME_YES" = 1 ] || yes_no "Docker jetzt installieren (offizielles Skript von get.docker.com)?" j; then
    command -v curl >/dev/null 2>&1 || die "curl fehlt: sudo apt-get install -y curl"
    curl -fsSL https://get.docker.com | $SUDO sh
    if [ "$(id -u)" != 0 ]; then
      $SUDO usermod -aG docker "$USER" || true
      NEED_RELOGIN=1
    fi
  else
    die "Ohne Docker geht es nicht. Anleitung: docs/INSTALLATION.md, Schritt 1."
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
    else die "Docker läuft nicht (sudo systemctl start docker)."
    fi
  fi
fi
compose_version="$($DOCKER compose version --short 2>/dev/null | sed 's/^v//' || true)"
[ -n "$compose_version" ] || die "Docker Compose fehlt: sudo apt-get install -y docker-compose-plugin"
version_ge "$compose_version" "$MIN_COMPOSE" \
  || die "Docker Compose $compose_version ist zu alt (mindestens $MIN_COMPOSE). Aktualisieren: curl -fsSL https://get.docker.com | sudo sh"
ok "Docker $($DOCKER version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), Compose $compose_version"

# ------------------------------------------------------------------ source
step "JuStAI5 bereitstellen"
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
    command -v apt-get >/dev/null 2>&1 || die "git fehlt - bitte installieren."
    $SUDO apt-get update -qq && $SUDO apt-get install -y -qq git >/dev/null
  fi
  git clone --depth 1 "$REPO_URL" "$TARGET_DIR" </dev/null
  APP_DIR="$(cd "$TARGET_DIR" && pwd)"
fi
cd "$APP_DIR"
ok "Ordner: $APP_DIR"

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

if [ -f .env ]; then
  ok "Vorhandene Einstellungen (.env) werden beibehalten."
  FRESH_ENV=0
else
  FRESH_ENV=1
  step "Einstellungen"
  cp .env.example .env
  chmod 600 .env
  IP="$(lan_ip)"
  HTTP_PORT="$(free_port "${JUSTAI_HTTP_PORT:-8080}")"
  HTTPS_PORT="$(free_port "${JUSTAI_HTTPS_PORT:-8443}")"
  [ "$HTTPS_PORT" != "$HTTP_PORT" ] || HTTPS_PORT="$(free_port $((HTTP_PORT + 1)))"
  [ "$HTTP_PORT" = "${JUSTAI_HTTP_PORT:-8080}" ] || warn "Port ${JUSTAI_HTTP_PORT:-8080} ist belegt, verwende $HTTP_PORT."
  [ "$HTTPS_PORT" = "${JUSTAI_HTTPS_PORT:-8443}" ] || warn "Port ${JUSTAI_HTTPS_PORT:-8443} ist belegt, verwende $HTTPS_PORT."
  set_env JUSTAI_HTTP_PORT "$HTTP_PORT"
  set_env JUSTAI_HTTPS_PORT "$HTTPS_PORT"
  set_env JUSTAI_PUBLIC_URL "http://$IP:$HTTP_PORT"
  if [ "$IP" != "127.0.0.1" ]; then
    set_env JUSTAI_TLS_NAMES "[\"$IP\"]"
    set_env JUSTAI_DISCOVERY_DEFAULT_CIDRS "[\"${IP%.*}.0/24\"]"
    ok "Adresse im Heimnetz: $IP (Kamerasuche in ${IP%.*}.0/24)"
  fi

  key="${GOOGLE_API_KEY:-}"
  if [ -z "$key" ] && [ -n "$TTY" ]; then
    printf '\nFür die Antworten braucht der Assistent ein Sprachmodell. Am einfachsten:\n' >"$TTY"
    printf 'kostenloser Google-API-Key von https://aistudio.google.com (Get API key).\n' >"$TTY"
    key="$(ask_secret "Google-API-Key einfügen (leer = später in der Oberfläche)")"
  fi
  if [ -n "$key" ]; then
    case "$key" in *"'"*|*[[:space:]]*) die "Der API-Key enthält ungültige Zeichen." ;; esac
    set_env GOOGLE_API_KEY "'$key'"
    ok "API-Key gespeichert"
  else
    warn "Kein API-Key - später unter Plugins -> Gemini eintragen (oder lokales Modell, docs/AI.md)."
  fi

  pw="${JUSTAI_ADMIN_PASSWORD:-}"
  while [ -z "$pw" ] && [ -n "$TTY" ]; do
    pw="$(ask_secret "Admin-Passwort festlegen (mind. 8 Zeichen, leer = zufällig erzeugen)")"
    [ -z "$pw" ] && break
    if [ "${#pw}" -lt 8 ]; then warn "Mindestens 8 Zeichen."; pw=""; continue; fi
    case "$pw" in *"'"*) warn "Bitte ohne Apostroph (')."; pw=""; continue ;; esac
    [ "$(ask_secret "Passwort wiederholen")" = "$pw" ] || { warn "Stimmt nicht überein."; pw=""; }
  done
  if [ -n "$pw" ]; then
    set_env JUSTAI_ADMIN_PASSWORD "'$pw'"
    ok "Admin-Passwort gespeichert (.env, nur für dich lesbar)"
  fi
  unset key pw
fi

HTTP_PORT="$(sed -n 's/^JUSTAI_HTTP_PORT=//p' .env | tail -n1)"; HTTP_PORT="${HTTP_PORT:-8080}"
HTTPS_PORT="$(sed -n 's/^JUSTAI_HTTPS_PORT=//p' .env | tail -n1)"; HTTPS_PORT="${HTTPS_PORT:-8443}"

# ------------------------------------------------------------------ start
step "Bauen und starten (beim ersten Mal einige Minuten, lädt ca. 3 GB)"
$DOCKER compose up -d --build </dev/null

step "Warten, bis JuStAI5 bereit ist"
health() {
  if command -v curl >/dev/null 2>&1; then curl -fsS "http://127.0.0.1:$HTTP_PORT/api/health" 2>/dev/null
  else wget -qO- "http://127.0.0.1:$HTTP_PORT/api/health" 2>/dev/null; fi
}
waited=0
until health | grep -q '"ok":true'; do
  [ "$waited" -lt "$HEALTH_TIMEOUT_S" ] || die "JuStAI5 antwortet nicht. Logs: $DOCKER compose logs core"
  sleep 3; waited=$((waited + 3))
done
ok "JuStAI5 läuft"

# ------------------------------------------------------------------ summary
IP="$(lan_ip)"
if [ "$FRESH_ENV" = 0 ]; then
  PW_TEXT="unverändert (dein bisheriges Passwort)"
elif grep -q "^JUSTAI_ADMIN_PASSWORD=" .env; then
  PW_TEXT="das Passwort, das du gerade festgelegt hast (steht auch in $APP_DIR/.env)"
else
  PW_TEXT="$($DOCKER compose exec -T core cat /data/initial_admin_password.txt </dev/null 2>/dev/null \
    | sed -n 's/^password: //p' || true)"
  [ -n "$PW_TEXT" ] && PW_TEXT="$PW_TEXT  (bitte gleich unter Einstellungen -> Benutzer ändern)" \
    || PW_TEXT="siehe: $DOCKER compose exec core cat /data/initial_admin_password.txt"
fi

cat <<EOF

${G}${B}JuStAI5 ist installiert.${N}

  Oberfläche:   ${B}http://$IP:$HTTP_PORT${N}
  Benutzer:     admin
  Passwort:     $PW_TEXT

  Handy/Tablet als Mikrofon, Lautsprecher und Kamera:
                https://$IP:$HTTPS_PORT/app
                (vorher Einstellungen -> Geräte-App: Zertifikat installieren)
  Fernseher/Monitor als Bildschirm:
                http://$IP:$HTTP_PORT/display

  Nächste Schritte:  $APP_DIR/docs/INSTALLATION.md (ab Schritt 5)
  Ideen:             $APP_DIR/docs/BEISPIELE.md
  Aktualisieren:     cd $APP_DIR && git pull && ./scripts/install.sh
EOF
if [ "${NEED_RELOGIN:-0}" = 1 ]; then
  printf '\n%s!%s Einmal ab- und wieder anmelden, damit du Docker ohne sudo verwenden kannst.\n' "$Y" "$N"
fi
}

main "$@"
