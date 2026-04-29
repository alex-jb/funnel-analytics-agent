#!/usr/bin/env bash
# install-cron.sh — install macOS launchd plists for funnel-analytics-agent.
#
# Installs two recurring jobs:
#   1. com.alex.funnel-analytics.brief — daily at 7:03 AM, writes brief
#      to ~/Documents/Obsidian/.../alex-brain/morning-briefs/<date>.md
#      and pushes to configured notifier(s).
#   2. com.alex.funnel-analytics.alert — every 7 minutes, runs --alert,
#      pushes to notifier(s) only when severity is critical or alert.
#
# Idempotent: re-running unloads + reloads. Safe.
#
# Why launchd not cron: macOS Sequoia ships with cron disabled by default
# and fights you on Full Disk Access. launchd is the supported path.
#
# Usage:
#   bash scripts/install-cron.sh
#
# Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.alex.funnel-analytics.brief.plist
#   launchctl unload ~/Library/LaunchAgents/com.alex.funnel-analytics.alert.plist
#   rm ~/Library/LaunchAgents/com.alex.funnel-analytics.{brief,alert}.plist

set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${FUNNEL_ENV_FILE:-$HOME/.funnel-analytics.env}"
BRIEF_DIR="${FUNNEL_BRIEF_DIR:-$HOME/Documents/Obsidian/Projects/alex-brain/morning-briefs}"
PYTHON="$(command -v python3)"
PLIST_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$BRIEF_DIR" "$PLIST_DIR"

# Make sure the agent is importable (pip install -e if not)
if ! "$PYTHON" -c "import funnel_analytics_agent" 2>/dev/null; then
  echo "↳ funnel_analytics_agent not importable — running pip install -e ..."
  "$PYTHON" -m pip install -e "$AGENT_ROOT" 2>/dev/null \
    || "$PYTHON" -m pip install --user -e "$AGENT_ROOT" 2>/dev/null \
    || "$PYTHON" -m pip install --break-system-packages -e "$AGENT_ROOT" 2>/dev/null \
    || { echo "↳ pip install failed — fall back to PYTHONPATH"; }
fi

# Wrapper script that sources the env file and runs the agent. Both plists
# call the same wrapper with different args.
WRAPPER="$AGENT_ROOT/scripts/_run.sh"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
set -e
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a
export PYTHONPATH="$AGENT_ROOT:\${PYTHONPATH:-}"
exec "$PYTHON" -m funnel_analytics_agent "\$@"
EOF
chmod +x "$WRAPPER"

# Brief plist — daily 7:03 AM
cat > "$PLIST_DIR/com.alex.funnel-analytics.brief.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.alex.funnel-analytics.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>$WRAPPER</string>
        <string>--out</string>
        <string>$BRIEF_DIR/\$(date +%Y-%m-%d).md</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>3</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/.funnel-analytics-agent/brief.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.funnel-analytics-agent/brief.err.log</string>
    <key>WorkingDirectory</key>
    <string>$HOME</string>
</dict>
</plist>
EOF

# Alert plist — every 7 minutes
cat > "$PLIST_DIR/com.alex.funnel-analytics.alert.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.alex.funnel-analytics.alert</string>
    <key>ProgramArguments</key>
    <array>
        <string>$WRAPPER</string>
        <string>--alert</string>
    </array>
    <key>StartInterval</key>
    <integer>420</integer>
    <key>StandardOutPath</key>
    <string>$HOME/.funnel-analytics-agent/alert.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.funnel-analytics-agent/alert.err.log</string>
    <key>WorkingDirectory</key>
    <string>$HOME</string>
</dict>
</plist>
EOF

mkdir -p "$HOME/.funnel-analytics-agent"

# Reload (unload-then-load is idempotent)
for label in com.alex.funnel-analytics.brief com.alex.funnel-analytics.alert; do
  launchctl unload "$PLIST_DIR/$label.plist" 2>/dev/null || true
  launchctl load "$PLIST_DIR/$label.plist"
done

echo ""
echo "✓ funnel-analytics-agent launchd jobs installed"
echo ""
echo "  Daily brief: 7:03 AM → $BRIEF_DIR/<YYYY-MM-DD>.md"
echo "  Alert poll:  every 7 minutes (420s)"
echo "  Env file:    $ENV_FILE"
echo "  Logs:        $HOME/.funnel-analytics-agent/{brief,alert}.{log,err.log}"
echo ""
echo "  Force run brief now:"
echo "    launchctl start com.alex.funnel-analytics.brief"
echo ""
echo "  Tail alert log live:"
echo "    tail -f $HOME/.funnel-analytics-agent/alert.log"
echo ""
echo "  Make sure $ENV_FILE has at least:"
echo "    NTFY_TOPIC=alex-vibex-launch  (or your topic)"
echo "    VERCEL_TOKEN=..."
echo "    PH_DEV_TOKEN=..."
echo "    SUPABASE_PERSONAL_ACCESS_TOKEN=..."
echo "    NOTIFIER_DEFAULT=ntfy  (or telegram,slack)"
