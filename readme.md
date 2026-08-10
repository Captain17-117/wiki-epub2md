
---

# epub2md — 維基文庫 EPUB 轉 Markdown

將維基文庫下載的 EPUB/HTML 古籍轉換為乾淨的 Markdown 檔案，自動移除導航欄、頁尾、版權資訊等干擾內容，保留純正文，**並自動注入適配 AI 語料庫的結構化元數據 (YAML)**。

## 為什麼需要這個工具

維基文庫提供了大量中文古籍的 EPUB 下載，但直接轉換為純文字時，會殘留大量導航欄、姊妹計劃連結、版權宣告、空白表格等干擾內容。市面上的通用轉換工具不認識這些維基文庫的專有結構，轉出來的結果往往需要巨大的人工清理成本。

`epub2md` 專門針對維基文庫的 MediaWiki HTML 結構設計，一鍵輸出極致乾淨的古籍正文，特別適合**構建大模型 (LLM) 訓練語料、RAG 向量數據庫**，或個人 Obsidian 知識庫。

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
- 可選 `--hard-break`：Markdown 強制換行，保護無標點豎排古籍轉橫排時的文字邊界

## 環境需求

- Python 3.7 或以上版本

## 安裝

```bash
pip install beautifulsoup4

```

## 使用方式

```bash
# 轉換 EPUB（輸出檔名自動生成同名 .md）
python epub2md.py input.epub

# 指定輸出路徑
python epub2md.py input.epub output.md

# 轉換單個 HTML
python epub2md.py input.html

# 保留超連結
python epub2md.py input.epub --keep-links

# Markdown 強制換行（豎排轉橫排無標點時，每行末尾加兩個空格）
python epub2md.py input.epub --hard-break

```

> **關於 `--keep-links`**：此參數最初是為輸出印刷級 PDF（保留內部交叉引用如「見卷二」）而設計，目前予以保留以維持功能完整性。如果您需要將維基文庫古籍輸出為紙本書、精排 PDF，歡迎交流討論。

## 適用範圍

**專為維基文庫（zh.wikisource.org）設計。** 不適用於一般 EPUB。
本工具依賴維基文庫 Parsoid 輸出的特定 HTML 結構（`section[data-mw-section-id]`、`table.ws-header`、`div.noprint` 等）。對其他來源的 EPUB 不會報錯，但也沒有特殊清理效果。

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

Pandoc、Calibre、MarkItDown 等通用轉換工具無法理解維基文庫的 MediaWiki Parsoid DOM 結構。它們會把導航欄、頁尾連結、版權宣告全部當成正文輸出，且會遺失以圖片呈現的生僻字。而 GitHub 上現有的 MediaWiki 解析庫（如 `mwparserfromhell`）處理的是 Wikicode 原始碼，並非 EPUB 內的渲染 HTML，對一般使用者有較高門檻。

`epub2md` 針對中文維基文庫 EPUB 深度定製，基於 DOM 結構精準清理，而非依賴正則表達式猜測。

## 設計哲學：零編譯依賴，處處可跑

`epub2md` 僅依賴 Python 標準庫與 BeautifulSoup4，不引入任何需要 C 編譯的第三方庫（如 `lxml`）。

這不是技術限制，而是刻意為之：
- **Termux 完美相容**：在 Android 手機上無需編譯工具鏈，`pip install beautifulsoup4` 一步到位
- **伺服器零折騰**：Linux 伺服器、樹莓派、雲端函數（如 AWS Lambda）皆可無痛部署
- **開箱即用**：沒有「裝不起來」的 GitHub Issue，降低你的維護成本

犧牲微秒級的解析速度，換來處處可跑的絕對便攜性——對於需要掛機批量轉換上千本古籍的使用者來說，這才是真正的生產力。

## 限制

* **來源限制**：僅適用於維基文庫匯出的 EPUB/HTML。依賴 Parsoid 渲染結構（`data-mw-section-id`、`ws-header` 等），其他來源的 EPUB 不會報錯但無清理效果。
* **表格簡化**：正文中的複雜數據表格會簡化為純文字加空格處理。
* **排版降級**：為符合 Markdown 標準，複雜的古籍實體排版（如原生的雙行並排）會降級為線性文本（自動轉為全形括號夾注）。
* **圖片字還原**：極度依賴維基文庫 `img` 標籤的 `alt` 屬性，若原圖無 `alt` 則無法還原。

> **注意**：維基文庫內容龐大，各書 EPUB 結構細節不盡相同。本工具已針對常見格式做最大相容，但百密難免一疏。若遇到轉換異常（標題遺失、段落錯位、殘留雜訊等），歡迎在 GitHub Issues 貼出原始 EPUB 名稱與截圖，有空就會修。不保證馬上解決，但保證每條反饋都會看。

## 授權

MIT License

## 引用與二次開發

本工具專為維基文庫 (zh.wikisource.org) 設計。若您引用、修改或用於其他專案，請保留原始出處標註，並在衍生專案中註明來源：
``` 
 epub2md - 維基文庫 EPUB 轉 Markdown
 https://github.com/Captain17-117/epub2md
 
``` 

---
