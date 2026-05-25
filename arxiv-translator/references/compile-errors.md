# 编译错误速查

## 常见错误与修复

**字体未找到** `Font "XXX" not found`
→ 请求的 CJK 字体在本地不存在。改用已确认可用的字体：`Noto Serif CJK SC`（TeX Live 通常自带）。

**宏包冲突**（`fontenc` 或 `inputenc`）
→ 注释掉 `\usepackage[T1]{fontenc}` 和 `\usepackage[utf8]{inputenc}`——XeLaTeX 的 Unicode 编译栈原生支持 UTF-8，不需要这两个包。

**`\pdfoutput` 未定义** `Undefined control sequence: \pdfoutput`
→ `\pdfoutput` 是 pdfLaTeX 专用命令，XeLaTeX 不支持。注释掉该行。

**CJKutf8 与 xeCJK 冲突**
→ CJKutf8 使用旧式 CJK 编码，与 xeCJK 不兼容。注释掉 `\usepackage{CJKutf8}` 并移除 `\begin{CJK*}{UTF8}{gbsn}` / `\end{CJK*}` 环境包装器。

**宏重复定义** `LaTeX Error: Command \xxx already defined`
→ 常见于为中文支持引入 `xeCJK` 后，与论文源码里的 `\newcommand\xxx...` 冲突。优先把源码中的该行从 `\newcommand` 改为 `\renewcommand`（保留论文作者期望的宏定义）。

**编译"成功"但引用/交叉引用仍是问号**（PDF 里出现 `??` 或 `[?]`）
→ 这意味着编译过程中发生了 LaTeX 错误，且在 `nonstopmode` 下仍生成了 PDF。compile.py 已开启 `-halt-on-error` 并执行三遍编译，通常能解决此问题。

**宏包缺失** `File 'xxx.sty' not found`
→ 该宏包未安装在本地 TeX Live 中。使用 `tlmgr install <pkg>` 安装缺失的宏包，或注释掉该包并替换为等价的可用包。

**中文溢出 / Overfull \hbox**
→ preamble 中已包含 `\setlength{\emergencystretch}{3em}`，通常足够。若仍溢出，添加 `\sloppy`。

**参考文献问题（bibtex/biber）**
→ 确认 `.bib` 文件已存在于工作目录并被正确引用；若论文自带 `.bbl` 而没有 `.bib`，优先复用 `.bbl`。

**spverbatim 缺失** `File 'spverbatim.sty' not found`
→ 该包在某些 TeX Live 发行版中未默认安装。编译前会自动检测并打补丁替换为 `verbatim`。

## 读取错误日志

编译失败时，查看工作目录下的 `<stem>.log` 文件。找到以 `!` 开头的行定位致命错误：

```
! LaTeX Error: ...
! Undefined control sequence ...
! Missing $ inserted ...
```

优先修复第一个错误——后续错误通常是连锁反应。

compile.py 会自动检测 `Command already defined` 错误并修复，最多重试 2 次。
