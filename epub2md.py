#!/usr/bin/env python3
"""
維基文庫 (zh.wikisource.org) 中文古籍專用 EPUB/HTML 轉 Markdown 終極清洗工具
兼顧「人類閱讀排版（支援豎排/無標點古籍）」與「AI 語料庫 / RAG 向量數據庫構建」。

核心特性：
  1. 深度 DOM 解析：精準剝離維基文庫特有導航欄、版權宣告、MediaWiki 空標記 (mw-empty-elt)。
  2. 結構化元數據注入：自動提取「書名」與「卷號」，並生成標準 YAML Front Matter，利於數據庫切分。
  3. 古籍排版與 AI 雙向優化：
     - 生僻字還原：解析圖片字 (Gaiji) 替換為對應 alt 文字。
     - 夾注優化：將 <small> 雙行夾注轉換為符合中文規範的全形括號（）。
     - 語料降噪：保留實質註腳文字，僅剔除 <ruby> 拼音標籤與 [1] 校勘註號，防止干擾 AI 分詞。
     - 排版保護：支援 --hard-break (行末雙空格)，防止無標點豎排文本擠壓糊成一片。
  4. 智能跳過機制：自動過濾封面頁、無效目錄頁與空白頁，輸出純淨正文。
  5. 全自動化：支援單一 HTML 與完整 EPUB 壓縮檔的批次解析。

使用方式：
    python epub2md.py input.epub
    python epub2md.py input.html
    python epub2md.py input.epub output.md --hard-break
"""

import os
import re
import sys
import argparse
import zipfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup, NavigableString, Tag, Comment

# ==========================================
# 參數與全域設定區
# ==========================================

# 屬於網頁廢料或不需要進入 Markdown 的 HTML 標籤
SKIP_TAGS = {
    'script', 'style', 'nav', 'header', 'footer',
    'img', 'meta', 'link', 'figure', 'figcaption',
}

# 區塊級標籤：渲染時會在前後增加換行，確保 Markdown 段落結構清晰
BLOCK_TAGS = {
    'div', 'section', 'article', 'main', 'blockquote',
    'pre', 'ul', 'ol', 'dl', 'table', 'tbody', 'thead',
}

# ==========================================
# 卷號異體字編輯區 (用戶可擴展)
# ==========================================
# 說明：
# 古籍正文應保持原貌，因此本腳本不對正文進行全局異體字替換。
# 但如果某本書的卷號使用了異體字（例如「巻」而非標準的「卷」），
# 會導致卷號提取失敗。請在此字典中新增對應字元。
# 本字典【僅作用於導航欄】，絕不汙染正文。
# 格式：'異體字': '標準字'
JUAN_VARIANT_MAP = {
    '巻': '卷',
}

# ==========================================
# 預先編譯正則表達式 (效能優化)
# ==========================================
# 將所有在迴圈中重複使用的正則表達式預先編譯，
# 避免每次呼叫時重新解析，提升大批量處理效能。

# 卷號匹配
RE_VOL = re.compile(
    r'(?:第[一二三四五六七八九十百千]+卷|'
    r'卷\s*[之]?[一二三四五六七八九十百千\d上下首末]+)'
)

# 類別名稱判斷
RE_LICENSE_CLASS = re.compile(r'licenseContainer')
RE_SISTER_ID = re.compile(r'^plainSister')
RE_REF_CLASS = re.compile(r'reference|cite_note')

# 文字清理
RE_ARROWS = re.compile(r'[◄►◀▶←→]')
RE_MULTI_SPACE = re.compile(r'\s+')
RE_QUANLAN = re.compile(r'全覽\d+')
RE_PUB_DOMAIN_1 = re.compile(r'此作品在全世界都属于公有领域.*?之前出版[。.]', flags=re.DOTALL)
RE_PUB_DOMAIN_2 = re.compile(r'(?i)Public\s*domain\s*public\s*domain\s*false\s*false')
RE_SPACES = re.compile(r'[ \t]+')
RE_EMPTY_LINES = re.compile(r'[ \t]*\n[ \t]*')
RE_TRAILING_ARROWS = re.compile(r'^[◄►◀▶←→\s]+$', flags=re.MULTILINE)
RE_MULTI_NEWLINES = re.compile(r'\n{3,}')


def _normalize_juan_variants_in_section(sec0):
    """只在導航欄內做卷號異體字標準化，確保提取成功，且不影響正文"""
    if not sec0 or not JUAN_VARIANT_MAP:
        return
    for tn in sec0.find_all(string=True):
        if tn.parent.name in ['style', 'script']:
            continue
        text = str(tn)
        changed = False
        for variant, standard in JUAN_VARIANT_MAP.items():
            if variant in text:
                text = text.replace(variant, standard)
                changed = True
        if changed:
            tn.replace_with(text)


# ==========================================
# 核心清洗模組 (針對維基文庫 Parsoid 結構)
# ==========================================

def extract_metadata_and_clean_nav(soup):
    """
    識別並清理維基文庫特有的導航結構，同時提取關鍵元數據（書名、卷號）。
    
    技術細節：
    維基文庫的頂部導航通常位於 <section data-mw-section-id="0"> 中的 <table class="ws-header">。
    排版有兩種常見變體：
      A. 兩行分離式：<tr>書名</tr><tr>卷號</tr>
      B. 一行合併式：<td><b>書名</b><br/>卷號</td>
    """
    metadata = {
        'book': '',
        'volume': '',
        'title': ''
    }

    # ---- 步驟 1：處理頂部元數據區塊（Section 0） ----
    sec0 = soup.find('section', attrs={'data-mw-section-id': '0'})
    if sec0:
        # 在提取前，先局部標準化導航欄內的異體字（如「巻」→「卷」）
        _normalize_juan_variants_in_section(sec0)

        ws_header = sec0.find('table', class_='ws-header')
        if ws_header:
            book_name = ''
            vol_name = ''
            
            rows = ws_header.find_all('tr')
            if len(rows) >= 1:
                tds = rows[0].find_all('td')
                if len(tds) >= 3:
                    # 優先透過 <b> 標籤鎖定書名
                    b_tag = tds[1].find('b')
                    if b_tag:
                        book_name = b_tag.get_text(strip=True)
                        
                        # 處理「一行合併式」排版：在書名所在的儲存格中尋找卷號
                        full_text = tds[1].get_text(' ', strip=True)
                        remainder = full_text.replace(book_name, '', 1).strip()
                        
                        # 使用預編譯正則匹配卷號
                        m = RE_VOL.search(remainder)
                        if m:
                            vol_name = m.group(0).strip()
                    else:
                        # 備用方案：若無 <b> 標籤，則直接抓取整個儲存格文字
                        book_name = tds[1].get_text(' ', strip=True)

            # 處理「兩行分離式」排版：若尚未找到卷號，則往第二行尋找
            if not vol_name and len(rows) >= 2:
                tds = rows[1].find_all('td')
                if len(tds) >= 3:
                    vol_name = tds[1].get_text(' ', strip=True)

            # 組合元數據字典
            metadata['book'] = book_name
            metadata['volume'] = vol_name
            
            # 避免書名與卷號相同時產生重複（如書名本身就是卷名）
            if book_name and vol_name and vol_name != book_name:
                metadata['title'] = f'{book_name} {vol_name}'
            else:
                metadata['title'] = book_name or vol_name

        # 提取完畢，徹底刪除導航區塊以防污染正文
        sec0.decompose()

    # ---- 步驟 2：清理頁尾導航與 MediaWiki 生成的冗餘標籤 ----
    # 刪除帶有 'noprint' 的頁尾導航及其關聯的表格
    for div in soup.find_all('div', class_='noprint'):
        about_val = div.get('about')
        div.decompose()
        if about_val:
            for tbl in soup.find_all('table', attrs={'about': about_val}):
                tbl.decompose()

    # 刪除公有領域/版權宣告區塊
    for el in soup.find_all('div', class_=RE_LICENSE_CLASS):
        el.decompose()

    # 刪除 MediaWiki 空標記 (mw-empty-elt)，防止產生無意義的殘留空行
    for el in soup.find_all('span', class_='mw-empty-elt'):
        el.decompose()

    # 刪除 meta 標籤（含 mw:Includes/OnlyInclude）
    for el in soup.find_all('meta'):
        el.decompose()

    # 刪除維基姊妹計劃連結側欄
    for el in soup.find_all('ul', id=RE_SISTER_ID):
        el.decompose()

    # 刪除無效的殘留空表格（避免產生無意義的 Markdown 空白表）
    for tbl in soup.find_all('table'):
        cells = tbl.find_all(['td', 'th'])
        if cells and all(not c.get_text(strip=True) for c in cells):
            tbl.decompose()

    return soup, metadata


def apply_deep_cleaning(soup):
    """
    執行古籍文本深度清洗，專為提升 AI 語料質量設計。
    包含：異體字還原、註腳過濾、全形空白對齊。
    """
    # 提取元數據並清理導航欄
    soup, metadata = extract_metadata_and_clean_nav(soup)

    # ---- 清理維基註號與引用 (Footnotes) ----
    # 1. 僅刪除正文中的 [1] 引用角標，避免誤殺註腳區塊的實質文字
    for el in soup.find_all('sup', class_=RE_REF_CLASS):
        el.decompose()
    # 2. 刪除註腳區塊（校刊記）開頭的「↑」返回箭頭，讓輸出更乾淨
    for el in soup.find_all('span', class_='mw-cite-backlink'):
        el.decompose()

    # ---- 異體字（Gaiji）還原 ----
    # 維基文庫常使用圖片來代替 Unicode 尚未收錄或罕見的生僻字，此處將其還原為 alt 文字
    for el in soup.find_all('span', attrs={'typeof': 'mw:File'}):
        img = el.find('img')
        if img and img.get('alt'):
            alt = img['alt']
            # 移除維基圖片 alt 描述中多餘的後綴（例如 "字 -- 描述"）
            if ' --' in alt:
                alt = alt.split(' --')[0].strip()
            el.replace_with(alt)

    # ---- 空格全形化與殘留符號清除 (合併遍歷，優化效能) ----
    # 將原本兩次獨立的 DOM 遍歷合併為一次，減少 CPU 開銷
    for tn in soup.find_all(string=True):
        if tn.parent.name in ['style', 'script']:
            continue
        original_text = str(tn)
        # 1. 空格處理：&nbsp; 和半形空格轉全形
        new_text = original_text.replace('\u00a0', '　').replace(' ', '　')
        # 2. 箭頭符號殘留清除
        new_text = RE_ARROWS.sub('', new_text)
        # 只有在文字確實改變時才更新 DOM，節省寫入開銷
        if new_text != original_text:
            tn.replace_with(new_text)

    return soup, metadata


# ==========================================
# 文本渲染與轉換模組 (HTML -> Markdown)
# ==========================================

def render_children(node, keep_links=False):
    """遞迴渲染所有子節點並拼接成字串"""
    return ''.join(render_node(child, keep_links=keep_links) for child in node.children)


def render_node(node, keep_links=False):
    """
    核心渲染引擎：將單個 BeautifulSoup 節點轉換為標準 Markdown 語法。
    針對古籍特性進行了微調（如 small 夾注、ruby 拼音處理）。
    """
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    tag_name = node.name

    if tag_name in SKIP_TAGS:
        return ""
    if tag_name == 'br':
        return "\n"
        
    # 處理雙行小字（夾注）：古籍中極為常見（如裴松之注）。改用全形括號更符合中文規範。
    if tag_name == 'small':
        inner = render_children(node, keep_links=keep_links).strip()
        if inner:
            return f"（{inner}）"
        return ""
        
    # 處理拼音與注音 (<ruby>)：捨棄發音標籤 <rt>，僅保留漢字本體，避免中英夾雜污染 AI 語料
    if tag_name == 'ruby':
        for rt in node.find_all('rt'):
            rt.decompose()
        return render_children(node, keep_links=keep_links)

    # 標題渲染 (h1-h6)
    if tag_name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = int(tag_name[1])
        inner = render_children(node, keep_links=keep_links)
        inner = RE_MULTI_SPACE.sub(' ', inner).strip()
        if inner:
            return f"\n\n{'#' * level} {inner}\n\n"
        return ""

    # 段落渲染
    if tag_name == 'p':
        inner = render_children(node, keep_links=keep_links)
        return f"\n\n{inner}\n\n"

    # 超連結渲染
    if tag_name == 'a':
        inner = render_children(node, keep_links=keep_links)
        inner = RE_MULTI_SPACE.sub(' ', inner).strip()
        if not keep_links:
            return inner
        href = node.get('href', '')
        if href and inner:
            return f"[{inner}]({href})"
        return inner

    # 列表與表格基礎渲染
    if tag_name == 'li':
        inner = render_children(node, keep_links=keep_links)
        inner = RE_MULTI_SPACE.sub(' ', inner).strip()
        if inner:
            return f"- {inner}\n"
        return ""
    if tag_name == 'tr':
        inner = render_children(node, keep_links=keep_links)
        return inner + "\n"
    if tag_name in ('td', 'th'):
        inner = render_children(node, keep_links=keep_links)
        return inner + " "

    # 區塊級元素換行保護
    if tag_name in BLOCK_TAGS:
        inner = render_children(node, keep_links=keep_links)
        return f"\n\n{inner}\n\n"

    return render_children(node, keep_links=keep_links)


# ==========================================
# 結構化輸出與後處理模組
# ==========================================

def markdown_hard_break(text):
    """
    Markdown 強制換行：在非空行、非標題/列表/YAML 區塊行末尾追加兩個空格。
    特別適用於無標點古籍或豎排轉橫排文本，確保文字分行清晰、不擠壓糊成一片。
    """
    lines = text.split('\n')
    result = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            result.append('')
            continue
        # 標題、列表、引用塊、YAML 邊界線等不需要硬換行
        if stripped.startswith(('#', '-', '*', '>', '---')):
            result.append(line.rstrip())
            continue
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
        if next_line and not next_line.startswith(('#', '-', '*', '>', '---')):
            result.append(line.rstrip() + '  ')
        else:
            result.append(line.rstrip())
    return '\n'.join(result)


def generate_yaml_front_matter(metadata):
    """
    生成標準 YAML Front Matter 元數據標頭。
    將非結構化文本轉化為結構化數據，是 RAG 向量切分與 AI 標籤化的最佳實踐。
    """
    if not metadata.get('book') and not metadata.get('title'):
        return ""
        
    lines = ["---"]
    if metadata.get('title'):
        lines.append(f"title: \"{metadata['title']}\"")
    if metadata.get('book'):
        lines.append(f"book: \"{metadata['book']}\"")
    if metadata.get('volume'):
        lines.append(f"volume: \"{metadata['volume']}\"")
    lines.append("source: \"zh.wikisource.org\"")
    lines.append("type: \"ancient_text\"")
    lines.append("---")
    
    return "\n".join(lines) + "\n\n"


def clean_final_text(text, hard_break=False):
    """
    最終字串整理：移除零寬字元、清洗頑固的版權宣告文字、壓縮多餘的空白換行，
    並根據需求執行 --hard-break 行末空格處理。
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\u00a0', ' ')
    
    # 移除隱形零寬字元（對 AI 分詞極度有害）
    text = text.replace('\ufeff', '').replace('\u200b', '')
    
    # 暴力清除維基文庫殘留的版權與瀏覽模板純文字
    text = RE_QUANLAN.sub('', text)
    text = RE_PUB_DOMAIN_1.sub('', text)
    text = RE_PUB_DOMAIN_2.sub('', text)
    
    # 壓縮空白與換行，維持 Markdown 版面整潔
    text = RE_SPACES.sub(' ', text)
    text = RE_EMPTY_LINES.sub('\n', text)
    text = RE_TRAILING_ARROWS.sub('', text)
    
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = RE_MULTI_NEWLINES.sub('\n\n', text)
    
    # 若開啟強制換行，則進行行末空格處理
    if hard_break:
        text = markdown_hard_break(text)
        
    return text.strip()


# ==========================================
# 檔案解析模組 (EPUB / HTML)
# ==========================================

def epub_to_md(epub_path, hard_break=False, keep_links=False):
    """解壓並循序解析 EPUB 結構（讀取 manifest 與 spine），採用解耦架構提升效能"""
    with zipfile.ZipFile(epub_path, 'r') as zf:
        # 解析 container.xml 定位 OPF 檔案
        container = ET.fromstring(zf.read('META-INF/container.xml'))
        ns = {'ct': 'urn:oasis:names:tc:opendocument:xmlns:container'}
        opf_path = container.find('.//ct:rootfile', ns).attrib['full-path']
        print(f"  OPF 路徑: {opf_path}")
        
        opf = ET.fromstring(zf.read(opf_path))
        ns_opf = {'opf': 'http://www.idpf.org/2007/opf'}
        if not opf.findall('.//opf:manifest', ns_opf):
            ns_opf = {'opf': ''}
            if opf.findall('.//{http://www.idpf.org/2007/opf}manifest'):
                ns_opf = {'opf': 'http://www.idpf.org/2007/opf'}
        
        opf_dir = opf_path.rsplit('/', 1)[0] if '/' in opf_path else ''
        
        # 建立資源清單 (Manifest)
        manifest = {}
        for item in (opf.findall('.//opf:manifest/opf:item', ns_opf) or 
                     opf.findall('.//{http://www.idpf.org/2007/opf}manifest/{http://www.idpf.org/2007/opf}item')):
            mid = item.attrib.get('id', '')
            href = item.attrib.get('href', '')
            mtype = item.attrib.get('media-type', '')
            if mid and href and mtype in ('application/xhtml+xml', 'text/html', 'application/xml'):
                full = f"{opf_dir}/{href}" if (opf_dir and not href.startswith('/')) else href
                full = os.path.normpath(full)
                manifest[mid] = full
                
        # 讀取閱讀順序 (Spine)
        spine_items = (opf.findall('.//opf:spine/opf:itemref', ns_opf) or 
                       opf.findall('.//{http://www.idpf.org/2007/opf}spine/{http://www.idpf.org/2007/opf}itemref'))
        spine_ids = [it.attrib['idref'] for it in spine_items if it.attrib.get('idref')]

        # ---- 分類頁面 ----
        # title 頁：沒有 data-mw-section-id → 提取書名
        # 目錄頁：第一個有 data-mw-section-id 的頁面 → 跳過
        # 正文頁：其餘所有頁面 → 迴圈清洗

        global_book_name = ''
        content_ids = []          # 正文頁的 spine ID 列表
        found_directory = False   # 是否已遇到目錄頁

        # ---- 第一階段：預掃描與分類 ----
        for sid in spine_ids:
            if sid not in manifest:
                continue
                
            # 效能優化：如果已經找到目錄，後面的直接全部歸類為正文，不讀檔、不解析
            if found_directory:
                content_ids.append(sid)
                continue

            try:
                content = zf.read(manifest[sid]).decode('utf-8')
            except Exception:
                continue

            soup = BeautifulSoup(content, 'html.parser')
            body = soup.body if soup.body else soup

            # 先剝離垃圾標籤再判斷
            for tag in body.find_all(list(SKIP_TAGS)):
                tag.decompose()

            has_section = body.find(attrs={'data-mw-section-id': True})

            if not has_section:
                # ---- 標題頁：只取書名 ----
                if not global_book_name:
                    title_tag = soup.find('title')
                    if title_tag:
                        global_book_name = title_tag.get_text(strip=True)
                    else:
                        h_tag = body.find(['h1', 'h2'])
                        if h_tag:
                            global_book_name = h_tag.get_text(strip=True)
                # 標題頁不進入正文處理
                continue

            if not found_directory:
                # ---- 目錄頁：第一個有 section-id 的頁面，跳過 ----
                found_directory = True
                continue

        print(f"  書名: {global_book_name or '(未提取到)'}")
        print(f"  正文頁數: {len(content_ids)}")

        # ---- 第二階段：迴圈處理所有正文頁 ----
        all_parts = []
        ok = 0
        
        for i, sid in enumerate(content_ids):
            try:
                content = zf.read(manifest[sid]).decode('utf-8')
            except Exception as e:
                print(f"  [{i+1}/{len(content_ids)}] 無法讀取 {manifest[sid]}: {e}")
                continue

            soup = BeautifulSoup(content, 'html.parser')
            body = soup.body if soup.body else soup

            # 初步剝離垃圾標籤，加速後續解析
            for tag in body.find_all(list(SKIP_TAGS)):
                tag.decompose()

            body, metadata = apply_deep_cleaning(body)
            text = render_node(body, keep_links=keep_links).strip()

            # 若該章節解析出有效文本，則注入 YAML 元數據標頭與一級標題
            if text:
                yaml_header = generate_yaml_front_matter(metadata)
                title_header = f"# {metadata['title']}\n\n" if metadata.get('title') else ""
                full_chapter_text = f"{yaml_header}{title_header}{text}"
                all_parts.append(full_chapter_text)
                ok += 1

            if (i + 1) % 50 == 0:
                print(f"  進度: {i+1}/{len(content_ids)}")

        print(f"  成功: {ok}/{len(content_ids)} 章節")

    # 合併輸出：最前面放書名
    final_text = '\n\n'.join(all_parts)
    if global_book_name:
        final_text = f'# {global_book_name}\n\n{final_text}'

    # 使用 \n\n 作為分隔符，避免與 YAML 的 --- 衝突
    return clean_final_text(final_text, hard_break=hard_break)


def html_to_md(html_path, hard_break=False, keep_links=False):
    """處理單個 HTML 檔案（用於測試或單頁轉換）"""
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
    body = soup.body if soup.body else soup
    
    for tag in body.find_all(list(SKIP_TAGS)):
        tag.decompose()
        
    body, metadata = apply_deep_cleaning(body)
    text = render_node(body, keep_links=keep_links).strip()
    
    if text:
        yaml_header = generate_yaml_front_matter(metadata)
        title_header = f"# {metadata['title']}\n\n" if metadata.get('title') else ""
        text = f"{yaml_header}{title_header}{text}"
        
    return clean_final_text(text, hard_break=hard_break)


def get_default_output_path(input_path):
    return os.path.splitext(input_path)[0] + '.md'


# ==========================================
# 命令列介面 (CLI)
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description='將維基文庫古籍 EPUB/HTML 轉為乾淨 Markdown (自動注入 YAML 元數據，兼顧 AI 語料與閱讀體驗)'
    )
    parser.add_argument('input', help='輸入檔案路徑（.html 或 .epub）')
    parser.add_argument('output', nargs='?', help='輸出 Markdown 路徑（預設為同目錄下同名 .md）')
    parser.add_argument('--hard-break', action='store_true',
                        help='Markdown 強制換行（每行末尾追加兩個空格），適合無標點古籍與豎排排版')
    parser.add_argument('--keep-links', action='store_true',
                        help='保留超連結（預設為移除以提升 AI 語料純淨度）')
    
    args = parser.parse_args()
    
    if not os.path.isfile(args.input):
        print(f"錯誤：找不到檔案 {args.input}")
        sys.exit(1)
        
    output = args.output or get_default_output_path(args.input)
    print(f"開始轉換: {args.input} -> {output}")
    
    try:
        ext = os.path.splitext(args.input)[1].lower()
        if ext == '.epub':
            md = epub_to_md(args.input, hard_break=args.hard_break, keep_links=args.keep_links)
        else:
            md = html_to_md(args.input, hard_break=args.hard_break, keep_links=args.keep_links)
            
        with open(output, 'w', encoding='utf-8') as f:
            f.write(md)
            
        if md and not md.endswith('\n'):
            with open(output, 'a', encoding='utf-8') as f:
                f.write('\n')
                
        print(f"轉換完成！共輸出 {md.count(chr(10)) + 1} 行，{len(md)} 個字元。")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()