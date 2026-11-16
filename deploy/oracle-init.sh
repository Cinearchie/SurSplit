#!/bin/bash
# SurSplit: one-shot setup for an Oracle Cloud (Ubuntu) server.
#
# Paste this whole file into "Show advanced options → Management → Initialization script"
# when creating the instance. Replace the Tailscale auth key below first.
#
# The server will:
#   • install Docker + Tailscale and join your Tailscale network (private access only)
#   • build SurSplit from GitHub and run it, restarting automatically on crash/reboot
#   • serve it on port 80. Oracle's default firewall blocks that from the internet,
#     so it is reachable only through Tailscale. Do NOT add an ingress rule for port 80.
#
# Progress log on the server: /var/log/sursplit-setup.log

TAILSCALE_AUTHKEY="tskey-auth-REPLACE_ME"   # https://login.tailscale.com/admin/settings/keys
HOSTNAME_TS="sursplit"                        # becomes http://sursplit in Tailscale
REPO="https://github.com/Cinearchie/SurSplit.git"

exec > /var/log/sursplit-setup.log 2>&1
set -eux

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl ca-certificates

# ---- Docker ----
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# ---- Tailscale (private network) ----
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname="${HOSTNAME_TS}" --ssh

# ---- SurSplit ----
mkdir -p /opt/sursplit/cookies
git clone --depth 1 "${REPO}" /opt/sursplit/src
docker build -t sursplit /opt/sursplit/src

docker run -d --name sursplit --restart unless-stopped \
  -p 80:7860 \
  -e ENABLED_MODELS=hq \
  -e ENABLE_YOUTUBE=true \
  -e TRUST_PROXY=false \
  -e MAX_CONCURRENT_JOBS=2 \
  -e YTDLP_COOKIES=/app/cookies/cookies.txt \
  -v /opt/sursplit/cookies:/app/cookies:ro \
  sursplit

# ---- Weekly rebuild, which picks up yt-dlp updates and your latest GitHub code ----
cat > /usr/local/bin/sursplit-update <<'EOF'
#!/bin/bash
set -e
cd /opt/sursplit/src && git pull --ff-only
docker build --pull -t sursplit /opt/sursplit/src
docker rm -f sursplit
docker run -d --name sursplit --restart unless-stopped -p 80:7860 \
  -e ENABLED_MODELS=hq -e ENABLE_YOUTUBE=true -e TRUST_PROXY=false -e MAX_CONCURRENT_JOBS=2 \
  -e YTDLP_COOKIES=/app/cookies/cookies.txt -v /opt/sursplit/cookies:/app/cookies:ro sursplit
docker image prune -f
EOF
chmod +x /usr/local/bin/sursplit-update
echo "0 4 * * 1 root /usr/local/bin/sursplit-update >> /var/log/sursplit-update.log 2>&1" > /etc/cron.d/sursplit-update

echo "SurSplit is ready at http://${HOSTNAME_TS} (via Tailscale)"
