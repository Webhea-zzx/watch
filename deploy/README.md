# systemd 一键安装（不用 vi、不用手改配置文件）

## 你要做的只有两件事

**1）先装好依赖（只需复制粘贴执行）：**

```bash
cd /你的仓库路径
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**2）一键写入 systemd 并启动（会提示你输入本机密码）：**

```bash
cd /你的仓库路径
sudo bash deploy/oneclick-systemd.sh
```

脚本会自动：

- 用**当前仓库路径**、`./.venv/bin/uvicorn` 生成服务文件（**不写 nano/vi**）  
- 用你 `sudo` 时的**登录用户名**跑服务（数据目录可写）  
- 若没有 `.env`，会**自动生成**一份（含随机 `SECRET_KEY`），**不用你编辑**  
- 执行 `systemctl enable --now watch-gateway`

## 之后常用命令（复制即可）

```bash
sudo systemctl restart watch-gateway
sudo systemctl status watch-gateway
sudo journalctl -u watch-gateway -f
```

## 注意

- 项目路径里**不要有空格**。  
- **不要** `uvicorn --workers` 大于 1（本程序 TCP 与 Web 同进程）。  
- 云服务器安全组记得放行 **9000**（手表）和 **8000**（网页）。
