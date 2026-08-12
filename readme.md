

# WikiEpub2md — 維基文庫 EPUB 轉 Markdown

將維基文庫下載的 EPUB/HTML 古籍轉換為乾淨的 Markdown 檔案，自動移除導航欄、頁尾、版權資訊等干擾內容，保留純正文，**並自動注入適配 AI 語料庫的結構化元數據 (YAML)**。

## 為什麼需要這個工具

維基文庫提供了大量中文古籍的 EPUB 下載，但直接轉換為純文字時，會殘留大量導航欄、姊妹計劃連結、版權宣告、空白表格等干擾內容。市面上的通用轉換工具不認識這些維基文庫的專有結構，轉出來的結果往往需要巨大的人工清理成本。

`WikiEpub2md` 專門針對維基文庫的 MediaWiki HTML 結構設計，一鍵輸出極致乾淨的古籍正文，特別適合**構建大模型 (LLM) 訓練語料、RAG 向量數據庫**，或個人 Obsidian 知識庫。

## 核心功能

- 支援 `.epub` 和 `.html` 兩種輸入格式
- **精準 DOM 剝離**：自動識別並移除：
  - 卷首/卷尾導航欄（含箭頭、卷號、上一卷/下一卷連結）
  - 姊妹計劃側欄
  - 頁尾 `noprint` 導航
  - 版權宣告區塊（`licenseContainer`）
  - `mw:Includes` 等 MediaWiki 內部標記與空白表格
- **智能過濾**：自動跳過無正文的封面頁與目錄頁
- **結構化元數據**：自動提取書名與卷號，生成 YAML Front Matter
- **古籍排版優化**：
  - 生僻圖片字 (Gaiji) 還原為文字
  - 雙行夾注 (`<small>`) 自動轉換為全形括號（）
  - 全形空格標準化
  - 內建卷號異體字擴展字典（解決「巻/卷」匹配失效，且不汙染正文）
- **解耦架構**：封面頁（提取書名）、目錄頁（自動跳過）、正文頁（清洗渲染）三層獨立處理，結構清晰、換書不爆。
- **效能優化**：正則表達式預編譯 + DOM 遍歷合併 + 預掃描分類避免重複解析，300 卷大型 EPUB 仍保持流暢。  

## 環境需求

- Python 3.7 或以上版本
- BeautifulSoup4

## 安裝

推薦使用「可編輯模式」安裝。安裝後系統將註冊全域命令 `wiki2md`，您可以脫離原始碼目錄，在任意資料夾中直接跨目錄執行命令。

在包含 `pyproject.toml` 的專案目錄下執行：

```bash
# 安裝相依套件與 CLI 命令
pip install -e .

```

> **註**：加了 `-e` 參數後，未來若修改 `WikiEpub2md.py` 原始碼優化邏輯，**不需重新安裝**，下次執行 `wiki2md` 會自動套用新代碼。
> 
> 

## 使用方式

本工具支援**全自動目錄批次轉換**與單檔轉換，並提供極簡短參數與環境變數支援，特別適合在 Termux 或伺服器上掛機處理上千本古籍。

### 1. 全自動批次轉換 (最強功能)

直接進入您存放古籍 EPUB 的資料夾，無需指定檔名：

```bash
# 自動掃描「當前目錄」下的所有 epub/html，並在原地生成同名 md 檔
wiki2md

# 掃描當前目錄，並將所有轉換後的 md 檔統一輸出到 output_dir 資料夾
wiki2md . output_dir

# 直接指定其他目錄進行批次掃描
wiki2md /sdcard/Download/books/

```

### 2. 單檔轉換基礎命令

```bash
# 轉換單個 EPUB (輸出檔名自動生成同名 .md)
wiki2md input.epub

# 指定輸出路徑
wiki2md input.epub output.md

```

### 3. 進階參數 (短指令)

* `-b` 或 `--hard-break`：Markdown 強制換行（行末追加兩個空格）。保護無標點豎排古籍轉橫排時的文字邊界。


* `-l` 或 `--keep-links`：保留超連結（預設為移除以提升 AI 語料純淨度）。



**組合技示範：**

```bash
# 轉換當前目錄所有古籍，同時開啟強制換行與保留超連結
wiki2md -bl

```

### 4. 環境變數支援 (批次腳本必備)

如果您有大量的批次任務或自訂腳本，可以提前設定環境變數，免去每次輸入參數的麻煩：

```bash
# 開啟強制換行與保留超連結
export WIKI2MD_HARD_BREAK=1
export WIKI2MD_KEEP_LINKS=1

# 接下來執行的轉換將自動套用上述設定
wiki2md

```

*(支援的環境變數：`WIKI2MD_INPUT`、`WIKI2MD_OUTPUT`、`WIKI2MD_HARD_BREAK`、`WIKI2MD_KEEP_LINKS`)*

> **關於 `-l` (`--keep-links`)**：此參數最初是為輸出印刷級 PDF（保留內部交叉引用如「見卷二」）而設計，目前予以保留以維持功能完整性。如果您需要將維基文庫古籍輸出為紙本書、精排 PDF，歡迎交流討論。
> 
> 

## 適用範圍

**專為維基文庫（zh.wikisource.org）設計。** 不適用於一般 EPUB。
本工具依賴維基文庫 Parsoid 輸出的特定 HTML 結構（如 `section[data-mw-section-id]`、`table.ws-header` 等）。對其他來源的 EPUB 不會報錯，但也沒有特殊清理效果。

## 轉換效果對比

**轉換前（原始 EPUB 內的 HTML 結構）：**

```html
<section data-mw-section-id="0">
  <table class="ws-header">
    <tr><td>目錄</td><td><b>資治通鑑</b></td><td></td></tr>
    <tr><td>全書始</td><td>卷一</td><td>下一卷▶</td></tr>
  </table>
  <meta typeof="mw:Includes/OnlyInclude"/>
</section>
<section data-mw-section-id="1">
  <h2>安寢</h2>
  <p>少寐乃老年大患<sup class="reference">[1]</sup>……</p>
</section>

```

**轉換後（輸出極致乾淨的 Markdown）：**

```Markdown

---
title: "資治通鑑 卷一"
book: "資治通鑑"
volume: "卷一"
source: "zh.wikisource.org"
type: "ancient_text"
---

# 資治通鑑 卷一

## 安寢

少寐乃老年大患……

```

*(註：導航欄已自動轉換為 YAML 標頭與一級標題，維基註腳角標 `[1]` 已被精準清除。)*

## 與通用工具的差異

Pandoc、Calibre 等通用轉換工具無法理解維基文庫的 MediaWiki Parsoid DOM 結構。它們會把導航欄、頁尾連結、版權宣告全部當成正文輸出，且會遺失以圖片呈現的生僻字。「WikiEpub2md」針對中文維基文庫深度定製，基於 DOM 結構精準清理，而非依賴正則表達式猜測。

## 設計哲學：零編譯依賴，處處可跑

僅依賴 Python 標準庫與 BeautifulSoup4，不引入任何需要 C 編譯的第三方庫（如 `lxml`）。

* **Termux 完美相容**：在 Android 手機上無需編譯工具鏈，一步到位。


* **伺服器零折騰**：Linux 伺服器、樹莓派皆可無痛部署。


* **開箱即用**：降低維護成本。犧牲微秒級的解析速度，換來處處可跑的絕對便攜性——對於需要掛機批量轉換上千本古籍的使用者來說，這才是真正的生產力。



## 限制與已知問題

* **來源限制**：僅適用於維基文庫匯出的檔案。


* **表格簡化**：複雜數據表格會簡化為純文字加空格處理。


* **排版降級**：為符合 Markdown 標準，複雜的實體排版（如雙行並排）會降級為線性文本（自動轉為全形括號夾注）。


* **圖片字還原**：極度依賴 `img` 標籤的 `alt` 屬性，若原圖無 `alt` 則無法還原。



> **注意**：維基文庫內容龐大，若遇到轉換異常（標題遺失、段落錯位等），歡迎在 GitHub Issues 貼出原始 EPUB 名稱與截圖。
> 
> 

## 授權

MIT License

## 引用與二次開發

若您引用、修改或用於其他專案，請保留原始出處標註：

```text
WikiEpub2md - 維基文庫 EPUB 轉 Markdown
[https://github.com/Captain17-117/wiki-epub2md](https://github.com/Captain17-117/wiki-epub2md)

```