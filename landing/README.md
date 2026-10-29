# GIS WorkTable landing page

独立静态页面，不改变现有工作台的首页或启动方式。

在仓库根目录运行 `python -m http.server 8765 --bind 127.0.0.1 --directory landing`，打开 <http://127.0.0.1:8765>。也可以直接打开 `index.html`。

部署时上传本目录即可，无构建依赖。字体从 Google Fonts 加载，无法访问时回退到本机中文字体。产品截图来自 `docs/images/worktable.png`；功能示意已在辅助说明中标识。

公开部署前，把 `og:image` 改成部署域名下的绝对地址。当前使用相对地址，部分社交平台可能无法生成图片预览。

设计参考：<https://github.com/elayadesign/ai-design-skills> 中的 landing-page-design。文案以仓库 README 和演示指南为依据，不添加客户、用户量、效率提升或在线试用承诺。
