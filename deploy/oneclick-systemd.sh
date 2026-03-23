#!/usr/bin/env bash
# systemd 一键安装：无需 vi/nano 改配置。用法见 deploy/README.md
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo "请在本仓库根目录执行（需要管理员权限）："
  echo "  sudo bash deploy/oneclick-systemd.sh"
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "还没装好虚拟环境，请先执行（复制整段即可）："
  echo "  cd \"$REPO\""
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  exit 1
fi

UVICORN="$REPO/.venv/bin/uvicorn"
RUN_AS="${SUDO_USER:-}"
if [[ -z "$RUN_AS" ]]; then
  RUN_AS="$(logname 2>/dev/null || true)"
fi
if [[ -z "$RUN_AS" ]]; then
  echo "无法确定以哪个用户运行服务。请用普通用户执行: sudo bash deploy/oneclick-systemd.sh"
  exit 1
fi

mkdir -p "$REPO/data/files"
chown -R "$RUN_AS:$RUN_AS" "$REPO/data" 2>/dev/null || true

if [[ ! -f "$REPO/.env" ]]; then
  SEC="$(python3 -c "import secrets; print(secrets.token_hex(32))")"
  umask 077
  printf '%s\n' "SECRET_KEY=$SEC" "TCP_HOST=0.0.0.0" "TCP_PORT=9000" >"$REPO/.env"
  chown "$RUN_AS:$RUN_AS" "$REPO/.env"
  echo "已自动生成 $REPO/.env（含 SECRET_KEY，无需手改）"
else
  chown "$RUN_AS:$RUN_AS" "$REPO/.env" 2>/dev/null || true
fi

UNIT=/etc/systemd/system/watch-gateway.service
# systemd 对路径中的特殊字符较敏感，请勿把项目放在含空格的路径下
cat >"$UNIT" <<EOF
[Unit]
Description=儿童手表网关（TCP+Web，单进程）
After=network.target

[Service]
Type=simple
User=$RUN_AS
Group=$RUN_AS
WorkingDirectory=$REPO
EnvironmentFile=-$REPO/.env
ExecStart=$UVICORN app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable --now watch-gateway

echo ""
echo "已完成：服务 watch-gateway 已启用并启动。"
echo "查看状态: systemctl status watch-gateway"
echo "看日志:   journalctl -u watch-gateway -f"
echo "改代码后: systemctl restart watch-gateway"
echo ""
systemctl status watch-gateway --no-pager -l || true
