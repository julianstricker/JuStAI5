#!/bin/sh
# Creates the shared secrets once (persistent volume). Never overwrites existing ones.
set -eu
umask 077
cd /secrets
gen() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40; }
[ -s db_password ] || gen > db_password
[ -s master_key ] || gen > master_key
[ -s sandbox_token ] || gen > sandbox_token
# postgres (uid 999), core (10001) and sandbox (10002) read these files.
chmod 0444 db_password sandbox_token
chown 10001:10001 master_key && chmod 0400 master_key
echo "secrets ready"
