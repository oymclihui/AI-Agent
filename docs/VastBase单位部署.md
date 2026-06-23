# VastBase 单位服务器部署指南

适用安装包：`aiagnet-vastbase-linux-*.tar.gz`（Docker 方式，连接单位 VastBase）

---

## 一、前置条件

| 项目 | 要求 |
|------|------|
| 服务器 | Linux 64 位（Ubuntu / CentOS / OpenEuler 等） |
| Docker | 20+，含 `docker compose` |
| 数据库 | **VastBase 海量** @ `10.9.240.114:5432`，库 `fian`，schema `aiagent` |
| Redis | **10.138.133.102:6479**（消息/任务；密码 URL 编码） |
| 网络 | 应用服务器能访问 VastBase 与 Redis；用户浏览器能访问应用端口（默认 3000） |

> VastBase 由单位 DBA 提供连接信息（主机、端口、用户名、密码、库名、schema）。

---

## 二、快速安装（推荐）

```bash
# 1. 上传并解压
scp aiagnet-vastbase-linux-*.tar.gz user@server:/opt/
ssh user@server
cd /opt && tar -xzf aiagnet-vastbase-linux-*.tar.gz && cd aiagnet-vastbase-linux-*

# 2a. 单位一键安装（包内已带 .env.unit 时）
sudo bash install_unit.sh

# 2b. 或交互安装（可修改连接信息）
sudo bash install.sh
#   数据库类型选 vastbase
#   DB: 10.9.240.114 / fian / schema aiagent
#   Redis URL: redis://:密码@10.138.133.102:6479/0  （密码含 % 写 %25）

# 3. 管理员浏览器打开 SETUP_TOKEN.admin.txt 中的 setup 链接，完成建表

# 4. 用户访问
#   http://<服务器IP>:3000
#   默认 admin / admin123（首次登录后请改密）
```

---

## 三、方式 A — 界面建表（/setup）

1. 管理员打开 `SETUP_TOKEN.admin.txt` 中的 `/setup?token=...` 链接  
2. 数据库类型选 **VastBase 海量**  
3. 填写连接 → **测试连接** → **测试连接并初始化**  
4. 重启：`docker compose -f docker-compose.prod.yml restart backend`  
5. 访问 `/health`，确认 `"database":{"backend":"vastbase","status":"connected"}`  

---

## 四、方式 B — DBA 先执行 SQL（离线建表）

若单位要求 DBA 先审 SQL：

```bash
# 在能连 VastBase 的机器上（需 psql 或 VastBase 客户端）
psql -h <vastbase-host> -p 5432 -U <user> -d "AI-AGENT" \
  -f backend/scripts/sql/init_vastbase_complete.sql
```

建表完成后，在 `.env` 中设置 `DB_DRIVER=vastbase` 及连接参数，启动 Docker 即可（跳过 /setup 建表步骤，仍需创建管理员账号）。

---

## 五、从现有 PostgreSQL 迁移数据

若家里/测试环境已有 PG 数据，需复制到单位 VastBase：

```bash
# 在开发机 backend/ 目录
cp .env.vastbase.example .env
# 编辑 TARGET_DB_* = 单位 VastBase
# 编辑 SOURCE_DB_* = 现有 PostgreSQL

python scripts/migrate_to_vastbase.py --source postgres --dry-run
python scripts/migrate_to_vastbase.py --source postgres
```

迁移完成后将服务器 `.env` 中 `DB_DRIVER=vastbase` 指向同一库，重启 backend。

> Chroma 向量索引与 `uploads/` 不在关系库中，需单独拷贝或重新上传文档。

---

## 六、常用运维命令

```bash
cd /opt/aiagnet-vastbase-linux-*   # 解压目录

docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml restart backend
docker compose -f docker-compose.prod.yml down
```

---

## 七、检查清单（明天部署前）

- [ ] 向 DBA 确认：VastBase 主机、端口、库名、用户名、密码、schema  
- [ ] 确认防火墙：应用服务器 → VastBase 5432 通  
- [ ] 确认用户访问：办公网 → 应用服务器 3000 通  
- [ ] 准备好 LLM（Ollama 或 BYD EIS Key）  
- [ ] `SETUP_TOKEN.admin.txt` 仅管理员持有，勿发给普通用户  

---

**平台由李辉（Li Hui）共同创建。** 部署问题可查看 `docs/单位部署与首次登录.md`。
