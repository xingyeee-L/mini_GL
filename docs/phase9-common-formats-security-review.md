# 阶段 9 常用文件格式安全准入审查

## 结论

mini_GL 将常用文件划分为纯文本、结构化文本、现代 Office Open XML 和 PDF 四类，并统一接入现有的只读扫描、SHA-256、SQLite 原子同步和权限链路。解析器不会执行公式、脚本、宏、外部关系或附件。任何文件解析失败都会回滚整轮同步，不产生错误的删除事件。

## 已支持格式

- 办公文档：`.pdf`、`.docx`、`.xlsx`、`.pptx`。
- 常规文本：`.txt`、`.md`、`.markdown`、`.rst`、`.log`、`.tex`。
- 表格与结构化文本：`.csv`、`.tsv`、`.json`、`.jsonl`、`.html`、`.htm`、`.xml`。
- 配置文件：`.yaml`、`.yml`、`.toml`、`.ini`、`.cfg`、`.conf`。
- 常见源码：Python、JavaScript/TypeScript、Java、C/C++、C#、Go、Rust、SQL、Shell、PowerShell 和 Windows 批处理文件。

## 解析边界

XLSX 只读取工作表中保存的显示值和公式缓存值，不计算公式、不刷新数据连接，也不加载外部工作簿。PPTX 只读取按幻灯片顺序保存的文字。两类文件都拒绝宏、ActiveX、OLE/嵌入对象、加密条目、包内链接、路径穿越、XML 实体和高压缩比内容。

PDF 使用固定版本的纯 Python `pypdf`，只提取页面文本。加密 PDF、JavaScript、启动动作、文档级附加动作和嵌入附件会被拒绝。扫描前后仍比较文件身份、大小和修改时间，原始字节哈希用于变更判断。

HTML 只保留可见文本，忽略 `script`、`style`、`template` 和 `noscript` 内容，不访问外部资源。XML 禁止 DTD 和实体声明。JSON/JSON Lines、CSV/TSV 会先验证结构与数量限额，再进入标准文档。

## 不在本轮范围

- 旧版二进制 `.doc`、`.xls`、`.ppt`。
- 含宏的 `.docm`、`.xlsm`、`.pptm`。
- PDF 或图片中的 OCR、手写识别和图表视觉理解。
- 密码文件、压缩包、邮件附件、音频、视频和可执行文件。
- Office 批注、脚注、演讲者备注、嵌入附件和完整排版还原。

这些格式需要独立威胁评审和隔离策略，不能通过放宽扩展名白名单直接开放。
