import fitz
import pdfplumber
import os
import re
import shutil
import pytesseract
from collections import Counter
from PIL import Image
import io
import urllib.parse

# ==========================================
# ⚙️ 配置：环境与路径
# ==========================================
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

PDF_INPUT_DIR = "pdf_source"  # 原始 PDF 存放处
MD_OUTPUT_DIR = "data_source"  # 解析后的 MD 存放处
ASSET_BASE_DIR = "extracted_assets"  # 截图根目录


def merge_rects(rect_list, x_tol=10, y_tol=15):
    """合并相互重叠或靠近的矩形框"""
    merged = []
    for r in rect_list:
        found = False
        for i, m in enumerate(merged):
            if r.intersects(m + (-x_tol, -y_tol, x_tol, y_tol)):
                merged[i] = m | r
                found = True
                break
        if not found: merged.append(r)
    return merged


def multi_pdf_visual_parser():
    # 初始化环境
    os.makedirs(PDF_INPUT_DIR, exist_ok=True)
    os.makedirs(MD_OUTPUT_DIR, exist_ok=True)
    os.makedirs(ASSET_BASE_DIR, exist_ok=True)

    available_pdfs = [f for f in os.listdir(PDF_INPUT_DIR) if f.endswith(".pdf")]
    if not available_pdfs:
        print(f"📂 文件夹 [{PDF_INPUT_DIR}] 为空。请放入 PDF 文件后重新运行。")
        return

    print("\n--- 📄 发现以下 PDF 文档 ---")
    for idx, f in enumerate(available_pdfs):
        print(f"[{idx + 1}] {f}")

    user_input = input("\n👉 请输入编号 (如 '1,2') 或 'all' 全部解析: ").strip().lower()

    target_pdfs = []
    if user_input == 'all':
        target_pdfs = available_pdfs
    else:
        try:
            indices = [int(i.strip()) - 1 for i in user_input.split(',')]
            target_pdfs = [available_pdfs[i] for i in indices if 0 <= i < len(available_pdfs)]
        except:
            print("⚠️ 输入无效，程序退出。")
            return

    for pdf_name in target_pdfs:
        pdf_stem = pdf_name.rsplit('.', 1)[0]
        input_path = os.path.join(PDF_INPUT_DIR, pdf_name)
        output_md_path = os.path.join(MD_OUTPUT_DIR, f"{pdf_stem}.md")

        pdf_asset_dir = os.path.join(ASSET_BASE_DIR, pdf_stem)
        if os.path.exists(pdf_asset_dir): shutil.rmtree(pdf_asset_dir)
        os.makedirs(pdf_asset_dir, exist_ok=True)

        print(f"\n🚀 正在启动深度解析: {pdf_name}")
        doc_fitz = fitz.open(input_path)
        doc_plumber = pdfplumber.open(input_path)

        # 1. 跨页天眼：幽灵水印扫描
        coord_counter = Counter()
        for page in doc_fitz:
            items = [fitz.Rect(img["bbox"]) for img in page.get_image_info()]
            items += [fitz.Rect(d["rect"]) for d in page.get_drawings()]
            for r in items:
                fuzzy_coord = (round(r.x0, -1), round(r.y0, -1), round(r.width, -1), round(r.height, -1))
                coord_counter[fuzzy_coord] += 1
        watermark_blacklist = {c for c, count in coord_counter.items() if count >= 2}

        with open(output_md_path, "w", encoding="utf-8") as f_md:
            for page_num in range(len(doc_fitz)):
                page_f = doc_fitz[page_num]
                page_p = doc_plumber.pages[page_num]
                page_w, page_h = page_f.rect.width, page_f.rect.height
                f_md.write(f"## {pdf_name} - 第 {page_num + 1} 页\n\n")

                # --- 👁️ 2. 核心资产分离提取 ---
                hard_mask_rects = []  # 强遮挡区：里面的文字会被丢弃（避免图片上的乱码）
                soft_asset_rects = []  # 软增强区：只截图，但不干涉原本的文字提取

                # A. 物理图片 -> 强遮挡
                for img in page_f.get_image_info():
                    r = fitz.Rect(img["bbox"])
                    fuzzy_r = (round(r.x0, -1), round(r.y0, -1), round(r.width, -1), round(r.height, -1))
                    if r.width < page_w * 0.9 and fuzzy_r not in watermark_blacklist:
                        hard_mask_rects.append(r)

                # B. 有线表格(三线表探测) -> 强遮挡
                drawings = page_f.get_drawings()
                h_lines = sorted([fitz.Rect(d["rect"]) for d in drawings if
                                  fitz.Rect(d["rect"]).width > 40 and fitz.Rect(d["rect"]).height < 5],
                                 key=lambda x: x.y0)
                if h_lines:
                    temp = [h_lines[0]]
                    for line in h_lines[1:]:
                        if 0 <= (line.y0 - temp[-1].y1) < 250:
                            temp.append(line)
                        else:
                            if len(temp) >= 2: hard_mask_rects.append(
                                fitz.Rect(min(l.x0 for l in temp) - 5, min(l.y0 for l in temp) - 10,
                                          max(l.x1 for l in temp) + 5, max(l.y1 for l in temp) + 10))
                            temp = [line]
                    if len(temp) >= 2: hard_mask_rects.append(
                        fitz.Rect(min(l.x0 for l in temp) - 5, min(l.y0 for l in temp) - 10,
                                  max(l.x1 for l in temp) + 5, max(l.y1 for l in temp) + 10))

                # C. 无边框表格 -> 软增强
                ts = {"vertical_strategy": "text", "horizontal_strategy": "text", "snap_y_tolerance": 5}
                try:
                    for t in page_p.find_tables(table_settings=ts):
                        soft_asset_rects.append(fitz.Rect(t.bbox))
                except:
                    pass

                # 对遮挡区和增强区分别进行内部合并去重
                merged_hard_masks = merge_rects(hard_mask_rects)
                merged_soft_assets = merge_rects(soft_asset_rects)

                # 生成所有需要截图的视觉资产
                all_screenshot_assets = merge_rects(merged_hard_masks + merged_soft_assets)

                # --- 📸 3. 截图与 AI 辅助摘要 ---
                asset_entries = []
                for a_idx, a_rect in enumerate(all_screenshot_assets):
                    # 过滤掉体积过小或体积过大（误判）的区域
                    if a_rect.width < 20 or a_rect.height < 15: continue
                    if a_rect.width > page_w * 0.95 and a_rect.height > page_h * 0.8: continue

                    asset_filename = f"p{page_num + 1}_a{a_idx}.png"
                    save_path = os.path.join(pdf_asset_dir, asset_filename)
                    clip_rect = a_rect.intersect(page_f.rect)
                    page_f.get_pixmap(clip=clip_rect, matrix=fitz.Matrix(3, 3)).save(save_path)

                    # 局部 OCR
                    img_pil = Image.open(
                        io.BytesIO(page_f.get_pixmap(clip=clip_rect, matrix=fitz.Matrix(2, 2)).tobytes()))
                    ocr_res = pytesseract.image_to_string(img_pil, lang='chi_sim+eng').strip().replace("\n", " ")

                    safe_stem = urllib.parse.quote(pdf_stem)
                    safe_file = urllib.parse.quote(asset_filename)
                    md_path = f"../{ASSET_BASE_DIR}/{safe_stem}/{safe_file}"
                    tag = f"\n![视觉资产]({md_path})\n> 📌 **[图片摘要]**: {ocr_res if ocr_res else '图表内容'}\n"
                    asset_entries.append({'rect': a_rect, 'tag': tag})

                # --- 📝 4. 文本提取 (严格保护正文) ---
                blocks = page_f.get_text("blocks")
                raw_text_check = "".join([b[4] for b in blocks if b[6] == 0]).strip()

                if len(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]', raw_text_check)) < 100:
                    # 极端扫描件模式
                    pix = page_f.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                    f_md.write(
                        pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes())), lang='chi_sim+eng') + "\n\n")
                else:
                    # 💡 最关键的修复：只用 hard_mask 过滤文本！
                    # 这样图片里的乱码去掉了，但 pdfplumber 误判的无边框表格文字依然能被保留！
                    valid_text = [b for b in blocks if
                                  b[6] == 0 and not any(fitz.Rect(b[:4]).intersects(m) for m in merged_hard_masks)]

                    mid = page_w / 2
                    elements = []
                    for b in valid_text:
                        elements.append({'type': 'text', 'y': b[1], 'x': b[0], 'val': b[4]})
                    for e in asset_entries:
                        elements.append({'type': 'img', 'y': e['rect'].y0, 'x': e['rect'].x0, 'val': e['tag']})

                    # 简单可靠的双栏排序
                    left = sorted([e for e in elements if e['x'] < mid], key=lambda e: e['y'])
                    right = sorted([e for e in elements if e['x'] >= mid], key=lambda e: e['y'])

                    for e in left + right:
                        val = e['val'].replace("\n", "").strip() if e['type'] == 'text' else e['val']
                        if val: f_md.write(val + "\n\n")

                f_md.write("---\n\n")

        doc_fitz.close()
        doc_plumber.close()
        print(f"✅ 完成解析: {pdf_name}")


if __name__ == "__main__":
    multi_pdf_visual_parser()