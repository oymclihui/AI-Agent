# HTML → 可编辑 PPTX（html2pptx）

> 改编自 [huashu-design](https://github.com/alchaincyf/huashu-design) `references/editable-pptx.md`（MIT）。  
> **前提**：HTML 从第一行就按约束写；不是写完再转。

## 何时使用

- 用户要 **可编辑 PowerPoint**（同事能在 PPT 里改文字）
- 已决定走 **Path A**：每页独立 HTML → `html2pptx.js` + pptxgenjs

**不要用于**：强渐变、复杂 SVG、动画 deck → 改出 **PDF** 或浏览器 HTML 演示。

## 画布尺寸（默认）

| HTML body | PPT layout |
|-----------|------------|
| **960pt × 540pt**（推荐） | pptxgenjs `LAYOUT_WIDE`（13.333″×7.5″） |

等价：`1280px×720px` 或 `13.333in×7.5in`。  
演讲用全屏 HTML 仍可用 1920×1080；**导出 PPTX 时单独做 960×540 合规版**。

## 4 条硬约束（违反即导出失败）

1. **DIV 内不得裸文字** — 必须用 `<p>` / `<h1>`–`<h6>` / `<ul><li>` 包裹  
2. **禁止 CSS 渐变** — 仅纯色；多色用 flex 子 div 分段  
3. **背景/边框/阴影只在 DIV 上** — 文字标签只设字体样式  
4. **禁止 div `background-image`** — 用 `<img src="...">`

## 合并文本框

需整段连续编辑时，外层 div 加 `data-pptx-merge="true"`，内部多段 `<p>`/`<h*>` 合并为一个 PPT 文本框。

## 单页 HTML 骨架

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 960pt; height: 540pt; background: #FEFEF9; overflow: hidden; }
  .card { position: absolute; background: #1A4A8A; border-radius: 4pt; padding: 12pt 16pt; }
  .card h2 { font-size: 24pt; color: #FFF; }
  .card p  { font-size: 14pt; color: rgba(255,255,255,0.85); }
</style>
</head>
<body>
  <div style="position:absolute; top:40pt; left:60pt; right:60pt;">
    <h1 style="font-size:36pt;">标题用完整断言句</h1>
    <p style="font-size:16pt; color:#555;">副标题</p>
  </div>
  <div class="card" style="top:130pt; left:60pt; width:240pt;">
    <h2>要点</h2>
    <p>说明文字</p>
  </div>
</body>
</html>
```

## 目录结构

```
deck/
├── slides/01-cover.html
├── slides/02-agenda.html
└── assets/chart.png
```

## 导出（用户本地 Node 环境）

需 clone [huashu-design](https://github.com/alchaincyf/huashu-design) 并 `npm install`（pptxgenjs）。Agent 交付合规 HTML + `build.js` 示例：

```js
const pptxgen = require('pptxgenjs');
const html2pptx = require('./scripts/html2pptx.js'); // 来自 huashu-design 仓库

(async () => {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE';
  for (const file of ['01-cover.html', '02-agenda.html']) {
    await html2pptx(`./slides/${file}`, pres);
  }
  await pres.writeFile({ fileName: 'deck.pptx' });
})();
```

## AI-AGENT 平台说明

- 用户要**可下载 PPTX 文件**时：整理 slide 结构后 **必须调用 `create_presentation` 工具**（JSON slides → `.pptx`），并在最终回复附上 `download_url`  
- 同时可交付：每页 `960×540pt` 合规 HTML + build 脚本（供本机 Node/html2pptx 高保真导出）  
- 平台内置 `create_presentation`（python-pptx）；**不内置** html2pptx Node 运行时  
- 若源 HTML 含渐变/动效，先说明限制，提供 **editable 重写版** + 可选 PDF 双交付

## 常见错误

| 报错 | 修复 |
|------|------|
| unwrapped text in DIV | 文字包进 p/h* |
| CSS gradients not supported | 改纯色 |
| Text element has background | 背景移到外层 div |
| Background images on DIV | 改 img 标签 |
| dimensions don't match layout | body 960×540 + LAYOUT_WIDE |

## 工作流（与 huashu-design 配合）

1. 用 huashu-design 定风格与内容 → 浏览器 deck 可 1920×1080  
2. 用户要 PPTX → 本 skill：**按 4 约束重写/另存 editable 版**  
3. 交付 slides/*.html + build.js + 导出说明  
4. 验收：PPT 内文字可双击编辑
