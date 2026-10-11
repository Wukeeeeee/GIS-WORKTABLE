# 界面 PNG 资源

本目录图形由本仓库已有的界面图形转换为 PNG，保留原有构图；转换文件格式不会改变原素材的授权要求。未引入新的第三方图标包。

- `workspace-*.png` 对应工作台公共入口。
- `icon-*.png` 使用内容标识去重，通常为 96px 宽的透明图标；显示大小由 CSS 决定。
- `logo-*.png` 保留标识及文字，为 960px 宽的 PNG。
- 公共 `.ui-icon` 使用 PNG 的透明度作为 CSS 遮罩，并继承文字颜色，支持深浅主题。Logo 直接使用 PNG 图片。

新增界面图形应使用 PNG 或 CSS，禁止 SVG 文件、内联 SVG 和 SVG data URI。按钮的用途通过文字、`title` 或 `aria-label` 提供，装饰图标不重复朗读。
