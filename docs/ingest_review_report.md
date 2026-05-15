# Ingest Review Report — Legal PDF RAG

## Mục tiêu report
Report này review file `ingest.py` hiện tại theo đúng mục tiêu của chatbot pháp lý:
- ingest sạch
- preserve cấu trúc pháp lý
- chunk hợp lý cho legal retrieval
- citation đáng tin
- đủ nền cho reasoning sau này

Phạm vi review:
- review thiết kế ingest sẵn có
- phân tích cái nào nên giữ, cái nào nên bỏ
- phản biện các giả định hiện tại
- đề xuất hướng cải thiện tốt nhất

---

## 1) Kết luận ngắn
File ingest hiện tại là **một prototype có tư duy đúng ở mức đầu**, nhưng **chưa đủ chắc cho legal RAG chất lượng cao**.

Đánh giá tổng quan:
- **Điểm mạnh:** đã có cleanup, skip cover/TOC, metadata cơ bản, split có ý thức theo `Điều`/`Chương`/`Mục`
- **Điểm yếu cốt lõi:** vẫn là mô hình **page text -> regex clean -> recursive split**, chưa phải **structural parsing** theo luật
- **Rủi ro lớn nhất:** citation sai, chunk cắt ngang điều/khoản, mất cấu trúc, làm bẩn retrieval

Kết luận kỹ thuật:
> Nếu mục tiêu chỉ là demo nhanh thì file hiện tại dùng được.
>
> Nếu mục tiêu là chatbot luật có thể trả lời chắc, nhớ căn cứ, và suy luận từ tình huống thực tế thì ingest hiện tại cần nâng cấp từ **heuristic ingest** sang **structure-aware ingest**.

---

## 2) Review file ingest sẵn có

### 2.1 Những gì đang làm đúng

#### A. Có bước cleanup trước khi embed
Hiện tại file đã:
- remove watermark/footer phổ biến
- skip cover page
- skip mục lục
- chuẩn hóa whitespace

Đây là hướng đúng vì legal PDF bẩn sẽ kéo chất lượng embedding xuống rõ rệt.

**Đánh giá:** nên giữ tư duy này.

---

#### B. Có ý thức split theo cấu trúc luật
Việc dùng separator:
- `\nĐiều `
- `\nChương `
- `\nMục `

là tốt hơn rất nhiều so với split thuần ký tự.

**Đánh giá:** tư duy đúng, nhưng cách hiện thực chưa đủ mạnh.

---

#### C. Có gắn metadata cơ bản
Hiện có:
- `source_file`
- `law_name`
- `chunk_id`
- `dieu_so` (nếu detect được)

Việc nghĩ tới metadata ngay từ ingest là đúng.

**Đánh giá:** nên giữ, nhưng phải mở rộng mạnh.

---

#### D. Có preview chunk để kiểm tra
`preview_chunks()` là một thói quen dev tốt. Nó giúp phát hiện:
- chunk cắt xấu
- metadata thiếu
- watermark chưa sạch

**Đánh giá:** nên giữ.

---

### 2.2 Những điểm yếu quan trọng

#### A. Đang phụ thuộc quá nhiều vào heuristic theo từng file
Các rule hiện tại bám rất sát đúng file Studocu này:
- `Studocu`
- `Studeersnel`
- `Scan to open`
- `lOMoAR...`

Điều này ổn cho 1 file demo, nhưng không ổn nếu mày ingest:
- file luật từ nguồn khác
- file scan khác layout
- file PDF hành chính khác watermark

**Vấn đề:** ingest đang “fit theo file”, chưa “fit theo họ tài liệu pháp lý”.

---

#### B. `PyPDFLoader` chưa đủ chắc cho legal ingest dạng này
`PyPDFLoader` tiện cho prototype, nhưng legal PDF có thể bị:
- reading order sai
- block trái/phải trộn nhau
- heading chen giữa thân bài
- footer/header dính vào text body

Trong file luật mày đưa, đã có dấu hiệu text extraction không hoàn toàn sạch theo logical order.

**Vấn đề:** nếu order sai thì parser sau đó cũng sai theo.

---

#### C. Recursive splitter không đảm bảo chunk pháp lý chuẩn
Dù có ưu tiên separator `Điều`, `Chương`, `Mục`, nhưng khi văn bản dài quá, splitter vẫn fallback xuống:
- newline
- space
- empty string

Điều đó có nghĩa:
- một chunk có thể bị cắt giữa Khoản
- hoặc tệ hơn, chunk chứa cuối Điều A + đầu Điều B

Trong khi metadata `dieu_so` lại chỉ lấy **Điều đầu tiên tìm thấy trong chunk**.

**Hệ quả:** citation có thể sai hoặc mơ hồ.

---

#### D. Chưa parse thật sự cấu trúc pháp lý
Hiện tại chưa có bước parse ra cây cấu trúc:
- Chương
- Mục
- Điều
- Khoản
- Điểm

Đây là thiếu sót lớn nhất.

Legal RAG mạnh không nên index dựa trên “page text đã split”, mà nên index dựa trên “đơn vị pháp lý đã parse”.

---

#### E. Một số regex cleanup có nguy cơ xóa nhầm nội dung
Ví dụ:
```python
text = re.sub(r"^\d{1,3}\s*\n\s*\n", "", text.lstrip())
```
Mục đích là xóa số trang.

Nhưng về bản chất, regex này cũng có thể đụng vào:
- `1.` đầu khoản
- hoặc một số cấu trúc hợp lệ ở đầu trang

**Vấn đề:** cleanup legal text phải cực bảo thủ. Xóa nhầm cấu trúc luật là lỗi nặng hơn việc còn sót rác.

---

#### F. Logic skip page còn dễ gây mất dữ liệu thật
Ví dụ:
```python
if len(stripped) < 80:
    return True
```

Đây là rule tiện, nhưng không chắc.
Có thể tồn tại trang:
- ngắn
- ít text
- nhưng vẫn là phần hợp lệ của văn bản

Tương tự, rule detect TOC hiện tại phụ thuộc vào việc `MỤC LỤC` xuất hiện đúng vị trí/đúng casing mong đợi.

**Vấn đề:** skip theo heuristic cứng dễ bỏ mất dữ liệu tốt hoặc giữ lại dữ liệu xấu.

---

## 3) Cái nào nên giữ, cái nào nên bỏ, vì sao

## 3.1 Nên giữ

### 1. Tư duy cleanup trước embedding
**Giữ.**

**Vì sao:**
- legal PDF thường có noise
- noise làm hỏng retrieval
- cleanup là bắt buộc

**Nhưng:** chuyển từ regex cứng theo 1 file sang cơ chế cleaner an toàn hơn, có cấu hình.

---

### 2. Preview/debug chunk
**Giữ.**

**Vì sao:**
- rất hữu ích để QA ingest
- rẻ, dễ dùng
- giúp nhìn lỗi sớm

---

### 3. Metadata enrichment mindset
**Giữ.**

**Vì sao:**
- legal system cần metadata mạnh
- retriever, citation, filtering, debugging đều cần nó

**Nhưng:** mở rộng metadata lên mức cấu trúc pháp lý thật sự.

---

### 4. Ý tưởng dùng cấu trúc `Điều/Chương/Mục`
**Giữ tư duy, bỏ cách hiện thực hiện tại.**

**Vì sao:**
- đây là hướng đúng
- nhưng phải chuyển từ separator heuristic sang parser cấu trúc

---

## 3.2 Nên bỏ hoặc thay mạnh

### 1. `PyPDFLoader` làm extractor chính
**Nên thay.**

**Vì sao nên thay:**
- không đủ kiểm soát block/layout
- khó xử lý header/footer theo tọa độ
- khó xử lý order khi PDF có layout lẫn

**Thay bằng gì:**
- ưu tiên **PyMuPDF**
- hoặc **pdfplumber**

**Phản biện nếu ai bảo “PyPDFLoader đủ rồi”:**
- đủ cho RAG demo đơn giản
- không đủ cho legal ingest cần citation fidelity và structural parsing tốt

---

### 2. `RecursiveCharacterTextSplitter` làm lõi chunking
**Nên bỏ khỏi vai trò lõi chính.**

**Vì sao nên thay:**
- không bảo toàn Khoản/Điểm chắc chắn
- không hiểu cấu trúc pháp lý
- dễ tạo chunk lai giữa nhiều đơn vị luật

**Thay bằng gì:**
- parser cấu trúc -> emit chunk theo `Khoản`
- nếu khoản quá dài thì split tiếp theo `Điểm`
- chỉ dùng text splitter phụ trong trường hợp bất đắc dĩ

**Phản biện nếu ai bảo “separator là đủ rồi”:**
- separator chỉ là ưu tiên cắt
- không phải bảo chứng cấu trúc
- legal citation không thể dựa trên “hy vọng splitter sẽ đẹp”

---

### 3. Skip page theo độ dài cố định
**Nên bỏ.**

**Vì sao nên bỏ:**
- dễ mất dữ liệu thật
- độ dài không phải tín hiệu cấu trúc đáng tin

**Thay bằng gì:**
- rule dựa trên pattern cover/TOC/noise cụ thể hơn
- nếu cần, đánh dấu `page_type` thay vì skip sớm

---

### 4. Regex xóa số đầu trang quá mạnh
**Nên bỏ hoặc thay cách xử lý.**

**Vì sao nên thay:**
- nguy cơ xóa nhầm Khoản
- legal text không được phép mất numbering

**Thay bằng gì:**
- detect page number theo line độc lập
- hoặc xử theo header/footer region nếu dùng PyMuPDF/pdfplumber

---

## 4) Phản biện các giả định hiện tại

### Giả định 1: “Mỗi Điều khoảng 400-900 ký tự nên chunk 1000 là đủ”
**Phản biện:** không đủ chắc.

Vì:
- có Điều rất dài
- có Điều chứa nhiều Khoản/Điểm
- mục tiêu legal retrieval không phải “fit vừa chunk”, mà là “bảo toàn đơn vị pháp lý có nghĩa”

**Kết luận:** chunk size không nên là tiêu chí chính. Cấu trúc pháp lý mới là tiêu chí chính.

---

### Giả định 2: “Nếu chunk có `Điều X` ở đầu thì metadata `dieu_so = X` là ổn”
**Phản biện:** không ổn.

Vì chunk có thể:
- chứa hơn 1 Điều
- nhắc tới Điều khác trong nội dung
- bị cắt giữa điều

**Kết luận:** `dieu_so` chỉ đáng tin khi chunk được sinh ra từ parser cấu trúc, không phải regex sau split.

---

### Giả định 3: “Skip mục lục bằng keyword là đủ”
**Phản biện:** chưa đủ.

Vì:
- mục lục có thể kéo dài nhiều trang
- có thể không hiện đúng keyword ở đúng vị trí
- có thể có appendix/heading khác gây nhầm

**Kết luận:** TOC detection nên là 1 bước riêng, có trạng thái hoặc pattern chắc hơn.

---

### Giả định 4: “Page-level ingest rồi split sau là ổn”
**Phản biện:** đây là điểm gốc khiến ingest hiện tại chưa đủ tốt.

Với legal text, pipeline nên là:
- extract block
- clean
- parse hierarchy
- chunk theo hierarchy

không nên là:
- page text
- clean
- split by heuristic

---

## 5) Hướng cải thiện tốt nhất

## 5.1 Mục tiêu ingest v2
Biến PDF thành dữ liệu pháp lý có cấu trúc, sao cho mỗi chunk cuối cùng:
- có ranh giới pháp lý rõ
- có citation rõ
- có metadata giàu ngữ cảnh
- có thể truy ngược nguồn dễ dàng

---

## 5.2 Nên thay cái gì có sẵn, và vì sao nên thay

### A. Thay extractor: `PyPDFLoader` -> `PyMuPDF` hoặc `pdfplumber`
**Nên thay vì:**
- cần block-level extraction
- cần tọa độ để xử header/footer
- cần reading order tốt hơn

**Lợi ích:**
- sạch hơn
- dễ parse heading hơn
- ít rủi ro trộn text hơn

---

### B. Thay split heuristic -> structural parser
**Nên thay vì:**
- legal citation phụ thuộc vào Điều/Khoản/Điểm
- recursive splitter không có awareness về cấu trúc luật

**Lợi ích:**
- chunk đáng tin hơn
- citation chuẩn hơn
- retrieval mạnh hơn
- reasoning sau này dễ hơn

---

### C. Thay skip logic sớm -> classify page/section rồi xử lý
**Nên thay vì:**
- skip sớm dễ mất dữ liệu
- nhiều rule hiện tại quá cứng

**Lợi ích:**
- an toàn hơn
- dễ audit hơn
- dễ mở rộng sang PDF khác

---

### D. Thay metadata mỏng -> metadata pháp lý đầy đủ
**Nên thay vì:**
- metadata hiện tại chưa đủ cho citation và filtering

**Nên có ít nhất:**
- `law_name`
- `law_number`
- `law_year`
- `chapter_no`
- `chapter_title`
- `section_no`
- `section_title`
- `article_no`
- `article_title`
- `clause_no`
- `point_letter`
- `page_start`
- `page_end`
- `citation`
- `chunk_type`
- `source_file`
- `parser_version`

**Lợi ích:**
- tăng trust
- dễ debug
- dễ render căn cứ luật trong câu trả lời

---

## 5.3 Pipeline v2 được khuyến nghị

### Bước 1 — Extract block-level
- dùng PyMuPDF/pdfplumber
- lấy text + page + bbox

### Bước 2 — Noise cleanup an toàn
- xóa watermark/footer/header theo pattern hoặc region
- normalize Unicode/whitespace
- không xóa numbering pháp lý

### Bước 3 — Rebuild paragraph
- merge line vỡ
- giữ heading riêng
- chuẩn hóa đoạn văn

### Bước 4 — Parse hierarchy
Detect và build tree:
- `Chương`
- `Mục`
- `Điều`
- `Khoản`
- `Điểm`

### Bước 5 — Emit legal units
Tạo unit có cấu trúc:
- article node
- clause node
- point node

### Bước 6 — Chunk theo đơn vị pháp lý
Ưu tiên:
- 1 chunk = 1 Khoản
- nếu Khoản dài quá: split theo Điểm
- nếu vẫn quá dài: split sentence-aware nhưng giữ nguyên metadata

### Bước 7 — Persist structured data trước
Lưu:
- JSON/JSONL structured output
- rồi mới index vào Chroma

### Bước 8 — Validate
Kiểm tra:
- parse đủ số Điều chưa
- chunk nào thiếu article metadata
- còn watermark không
- có chunk lai nhiều Điều không
- TOC có lọt vào corpus chính không

---

## 6) Đề xuất giữ/bỏ cụ thể theo function

## `should_skip_page()`
### Nên giữ:
- tư duy phân loại page xấu / page tốt

### Nên bỏ/thay:
- rule `len(stripped) < 80`
- rule TOC quá cứng
- logic cover gắn chặt 1 watermark source

### Nên đổi thành:
- `classify_page(page) -> body | cover | toc | noise | uncertain`
- uncertain thì log ra review chứ không bỏ ngay

---

## `clean_text()`
### Nên giữ:
- xóa watermark rõ ràng là rác
- normalize whitespace

### Nên bỏ/thay:
- regex xóa số đầu trang quá mạnh
- cleanup không phân biệt header/footer/body

### Nên đổi thành:
- line-level cleanup
- block-level cleanup nếu dùng extractor có bbox
- test riêng cho mỗi pattern xóa

---

## `load_and_clean_pdfs()`
### Nên giữ:
- loop qua nhiều file
- attach metadata cơ bản

### Nên bỏ/thay:
- loader hiện tại
- skip sớm ngay tại page loop theo heuristic cứng

### Nên đổi thành:
- extract -> classify -> clean -> normalize -> emit intermediate blocks

---

## `split_into_chunks()`
### Nên giữ:
- tư duy chunk riêng thay vì nhét nguyên trang

### Nên bỏ/thay:
- `RecursiveCharacterTextSplitter` làm lõi
- regex `Điều` sau split để gắn metadata

### Nên đổi thành:
- `parse_structure()`
- `build_legal_units()`
- `chunk_legal_units()`

---

## 7) Ưu tiên hành động

### P0 — phải làm trước
1. Đổi extractor sang PyMuPDF/pdfplumber
2. Bỏ skip-page theo độ dài
3. Sửa cleanup để không đụng vào numbering pháp lý
4. Thiết kế parser `Chương -> Mục -> Điều -> Khoản -> Điểm`

### P1 — làm tiếp ngay
5. Chunk theo Khoản/Điểm thay vì recursive split
6. Mở rộng metadata/citation
7. Tạo structured JSON output trước khi index

### P2 — nâng cấp chất lượng
8. Validation script
9. Diagnostic report sau ingest
10. Cache/hash để tránh rebuild toàn bộ

---

## 8) Kết luận cuối
File ingest hiện tại **không phải sai hướng**. Vấn đề là nó mới dừng ở mức:
- làm sạch văn bản
- chia nhỏ heuristic
- index nhanh để demo

Trong khi legal chatbot mà mày đang muốn xây cần ingest ở mức:
- **có cấu trúc pháp lý rõ**
- **citation đáng tin**
- **retrieval bám đúng Điều/Khoản**
- **làm nền cho suy luận từ tình huống thực tế**

Khuyến nghị cuối cùng:
> Giữ lại tư duy cleanup + metadata + preview.
>
> Thay extractor, thay chunking core, và thêm structural parser.
>
> Đừng vá thêm regex vào pipeline cũ quá lâu, vì trần chất lượng của pipeline hiện tại đã khá rõ.

---

## 9) Một câu chốt thực dụng
Nếu muốn bot legal của mày “nghe thông minh hơn”, phần ingest tốt sẽ cho hiệu quả lớn hơn rất nhiều so với chỉ thay model.

Với bài toán này, ingest không phải phần phụ.
**Ingest chính là nền móng của chất lượng trả lời.**
