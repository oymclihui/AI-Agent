# AI-AGNET · LowcodeEngine Designer

基于阿里 [LowcodeEngine](https://lowcode-engine.cn/) 的 `demo-basic-antd`，为灵感模板提供 Ant Design 物料的可视化拖拽编排。

## 首次使用

```bash
cd frontend
npm run lowcode:install
npm run lowcode:build
```

构建产物输出到 `frontend/public/lowcode/designer/`，Next.js 通过 iframe 嵌入。

## 开发模式（热更新）

```bash
# 终端 1
npm run lowcode:dev    # http://localhost:5556

# 终端 2 — 在 frontend/.env.local 中设置：
# NEXT_PUBLIC_LOWCODE_DESIGNER_URL=http://localhost:5556/index.html
npm run dev
```

## 与灵感页集成

- 灵感卡片 → **Lowcode 设计** → `/inspiration/{id}/designer`
- iframe 与父页面通过 `postMessage` 同步 Schema
- 设计器工具栏 **保存到灵感** → 写入 `localStorage`（`lowcode` 字段）

## 架构

| 组件 | 说明 |
|------|------|
| `plugin-inspiration-bridge` | postMessage 桥接 + 保存按钮 |
| `plugin-editor-init` | 嵌入模式下等待父页面注入 Schema |
| `src/lib/lowcodeBridge.ts` | 前端消息协议 |

完整生产构建：`npm run build:all`
