# AI-AGENT Windows 演示机交付说明（方案 C）

适用于 **Windows 演示机、内网快速交付**：打包机预构建前端，目标机只需 Python + Node，无需 Git、无需开发模式热重载。

---

## 一、在开发机打交付包

**环境要求：** Node.js 20+、PowerShell 5+

```powershell
cd E:\AIAGNET
.\scripts\package_win_release.ps1
```

输出：

| 路径 | 说明 |
|------|------|
| `release\aiagnet-win-YYYYMMDD\` | 解压即用目录 |
| `release\aiagnet-win-YYYYMMDD.zip` | 同上，压缩包 |

交付包已包含：

- `backend/` — 后端源码（不含 `.venv`、数据库、上传文件）
- `frontend/` — **预构建** 的 `.next/` + 源码
- `install.ps1` — 目标机首次安装
- `start_prod.ps1` — 生产模式启动
- `README.md` — 本说明

---

## 二、在演示机部署

### 1. 环境准备

| 软件 | 版本 | 下载 |
|------|------|------|
| Python | 3.10+（推荐 3.11） | https://www.python.org/downloads/ |
| Node.js | 18+（推荐 20 LTS） | https://nodejs.org/ |

安装 Python 时勾选 **Add Python to PATH**。

### 2. 解压并安装

```powershell
# 解压 zip 到例如 D:\AIAGNET
cd D:\AIAGNET\aiagnet-win-20260611

# 首次运行（创建 venv、安装依赖、校验 .next）
.\install.ps1
```

`install.ps1` 会自动：

- 创建 `backend\.venv` 并 `pip install`
- 若不存在则从 `.env.example` 生成 `backend\.env`
- 生成 `frontend\.env.local`
- `npm ci --omit=dev`（交付包已含 `.next`，一般 **无需再次 build**）
- 创建 `uploads/`、`chroma_data/` 目录

### 3. 配置（可选）

编辑 `backend\.env`：

```env
SECRET_KEY=your-32-char-secret-key-here!!
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_LLM_MODEL=qwen3.6:35b
# 或使用 BYD EIS / OpenAI 等云端模型
```

编辑 `frontend\.env.local`（局域网访问时改 WS 地址）：

```env
BACKEND_URL=http://127.0.0.1:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

### 4. 启动

```powershell
.\start_prod.ps1
```

- 后端：`uvicorn` **无 `--reload`**，监听 `0.0.0.0:8000`
- 前端：`next start`，端口 `3000`
- 浏览器自动打开 http://localhost:3000

默认账号：**admin / admin123**（请在 `backend\.env` 修改）

自定义端口：

```powershell
$env:AIAGNET_BACKEND_PORT = "8000"
$env:AIAGNET_FRONTEND_PORT = "3000"
.\start_prod.ps1
```

---

## 三、与开发脚本的区别

| 脚本 | 用途 | 后端 | 前端 |
|------|------|------|------|
| `start.ps1` | 本地开发 | `--reload` | `npm run dev` |
| `start_prod.ps1` | 演示 / 交付 | 无 reload | `next start`（生产） |
| `install.ps1` | 交付包首次安装 | 创建 venv | `npm ci --omit=dev` |

---

## 四、常见问题

**Q：install 很慢？**  
首次 `pip install` 与 `npm ci` 约 3–5 分钟，取决于网络。内网无外网时需提前配置 pip / npm 镜像或离线 wheel。

**Q：LLM 无响应？**  
确认本机 Ollama 已启动，或已在 `.env` 配置云端 API Key。

**Q：局域网其他电脑访问？**  
`start_prod.ps1` 后端已绑定 `0.0.0.0`；前端需放行 Windows 防火墙 3000 端口，访问 `http://<演示机IP>:3000`。

**Q：如何更新版本？**  
重新打 zip，覆盖目录后执行 `.\install.ps1`（会保留 `.env` 与数据库文件）。

---

## 五、桌面自动化 Sidecar（可选）

若演示 **桌面 GUI 录放**，除平台外还需在 **演示机 Windows 桌面** 运行 Sidecar。

### 1. 获取 Sidecar exe

开发机打包：

```powershell
cd E:\AIAGNET
.\scripts\build_desktop_sidecar.ps1
```

输出：`release\desktop-sidecar\AIAGNET-Desktop-Sidecar.exe` 与 `sidecar.env.example`

将 `release\desktop-sidecar\` 整个目录复制到演示机（可与平台 zip 分开交付）。

### 2. 配置 sidecar.env

```env
AIAGNET_BASE_URL=http://127.0.0.1:8000
AIAGNET_FRONTEND_URL=http://localhost:3000
AIAGNET_LOGIN=admin
AIAGNET_PASSWORD=admin123
AIAGNET_OPEN_BROWSER=1
```

若平台在局域网其他机器，将 `AIAGNET_BASE_URL` 改为 `http://<服务器IP>:8000`。

### 3. 启动

双击 `AIAGNET-Desktop-Sidecar.exe`，控制台显示 `Sidecar registered` 即成功。

Web 端：**侧边栏 → 桌面自动化**，确认 **Sidecar 在线**。

### 4. 平台侧配置（backend\.env）

```env
DESKTOP_REQUIRE_CONFIRMATION=true
DESKTOP_OPENADAPT_DATA_DIR=./desktop_openadapt_data
HARNESS_REQUIRE_TOOL_CONFIRMATION=true
HARNESS_LLM_TIMEOUT_SEC=120
HARNESS_MAX_ITERATIONS_CAP=25
```

> Sidecar **不能** 在 Docker 内运行；Docker 仅部署平台后端/前端。

详细说明：[桌面自动化与 Harness 说明](./桌面自动化与Harness说明.md)

---

## 六、相关文档

- [打包部署方案](./打包部署方案.md) — 完整部署策略（Docker / Linux / Windows）
- [用户操作手册](./用户操作手册.md)
- [桌面自动化与 Harness 说明](./桌面自动化与Harness说明.md)
