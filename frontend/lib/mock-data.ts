import type { ChatResponse, DemoScenario } from "./types"

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "d1",
    label: "Đơn phương chấm dứt",
    prompt: "Đơn phương chấm dứt hợp đồng trái luật thì phải bồi thường gì?",
    tag: "Bồi thường",
  },
  {
    id: "d2",
    label: "Nợ lương — quyền nghỉ",
    prompt: "Công ty tôi nợ lương 2 tháng, tôi có thể nghỉ ngay không cần báo trước không?",
    tag: "Lương",
  },
  {
    id: "d3",
    label: "Lao động nữ mang thai",
    prompt: "Lao động nữ mang thai có được bảo vệ khi chấm dứt hợp đồng không?",
    tag: "Bảo vệ",
  },
  {
    id: "d4",
    label: "Trích nguyên văn Điều 113",
    prompt: "Trích nguyên văn Điều 113 Bộ luật Lao động.",
    tag: "Tra cứu",
  },
  {
    id: "d5",
    label: "Thử việc kỹ sư",
    prompt: "Thử việc tối đa bao lâu với công việc cần trình độ đại học?",
    tag: "Hợp đồng",
  },
  {
    id: "d6",
    label: "Làm thêm giờ",
    prompt: "Làm thêm giờ bị giới hạn thế nào theo luật lao động?",
    tag: "Thời giờ",
  },
  {
    id: "d7",
    label: "Ngoài phạm vi",
    prompt: "Real Madrid tối qua đá sao rồi?",
    tag: "Kiểm tra",
  },
  {
    id: "d8",
    label: "Điều không tồn tại",
    prompt: "Điều 999 quy định gì về sa thải?",
    tag: "Biên",
  },
]

// ── Mock responses keyed by keyword patterns ─────────────────────────────────

export const MOCK_RESPONSES: Record<string, ChatResponse> = {
  default: {
    answer:
      "Theo Bộ luật Lao động 2019, vấn đề bạn đề cập được điều chỉnh bởi các quy định cụ thể. Để trả lời chính xác nhất, bạn có thể nêu rõ hơn tình huống của mình không?",
    route: "clarifying",
    cited_articles: [],
    retrieved_articles: [],
    validation: { grounded: false, reason: "Câu hỏi chưa đủ dữ kiện pháp lý" },
  },

  unilateral: {
    answer:
      "Khi người sử dụng lao động đơn phương chấm dứt hợp đồng lao động trái pháp luật, theo **Điều 41** Bộ luật Lao động 2019, họ có nghĩa vụ:\n\n1. **Nhận người lao động trở lại làm việc** theo hợp đồng đã giao kết; trả tiền lương, đóng BHXH, BHYT, BHTN trong những ngày không được làm việc.\n2. **Bồi thường ít nhất 2 tháng tiền lương** theo hợp đồng, cộng thêm tiền lương những ngày không làm việc.\n3. Nếu **người lao động không muốn trở lại**, ngoài các khoản trên, NSDLĐ phải trả **trợ cấp thôi việc** theo Điều 46.\n4. Nếu **NSDLĐ không muốn nhận lại**, phải trả thêm ít nhất **2 tháng tiền lương** nữa.\n\n**Căn cứ pháp lý:** Điều 40, Điều 41 Bộ luật Lao động 2019.",
    route: "rag",
    cited_articles: ["40", "41"],
    retrieved_articles: [
      {
        article_number: "41",
        article_title: "Nghĩa vụ của người sử dụng lao động khi đơn phương chấm dứt hợp đồng lao động trái pháp luật",
        snippet:
          "1. Phải nhận người lao động trở lại làm việc theo hợp đồng lao động đã giao kết; phải trả tiền lương, đóng bảo hiểm xã hội, bảo hiểm y tế, bảo hiểm thất nghiệp trong những ngày người lao động không được làm việc và phải bồi thường ít nhất 02 tháng tiền lương theo hợp đồng lao động.",
        source_file: "luatlaodong_new.pdf",
        score: 11.24,
      },
      {
        article_number: "40",
        article_title: "Nghĩa vụ của người lao động khi đơn phương chấm dứt hợp đồng lao động trái pháp luật",
        snippet:
          "1. Không được trợ cấp thôi việc. 2. Phải bồi thường cho người sử dụng lao động nửa tháng tiền lương theo hợp đồng lao động và một khoản tiền tương ứng với tiền lương theo hợp đồng lao động trong các ngày không báo trước.",
        source_file: "luatlaodong_new.pdf",
        score: 8.91,
      },
      {
        article_number: "46",
        article_title: "Trợ cấp thôi việc",
        snippet:
          "Khi hợp đồng lao động chấm dứt theo quy định, người sử dụng lao động có trách nhiệm trả trợ cấp thôi việc cho người lao động đã làm việc thường xuyên từ đủ 12 tháng trở lên, mỗi năm làm việc được trợ cấp 1/2 tháng tiền lương.",
        source_file: "luatlaodong_new.pdf",
        score: null,
      },
    ],
    validation: { grounded: true, reason: "Điều 40, 41 có trong nguồn luật và được trích đúng" },
  },

  wage_arrears: {
    answer:
      "Nếu công ty **không trả lương đúng hạn**, theo **Điều 35 khoản 2 điểm c** Bộ luật Lao động 2019, người lao động có quyền **đơn phương chấm dứt hợp đồng mà không cần báo trước**.\n\nNgoài ra, theo **Điều 97**, công ty còn phải:\n- Trả **toàn bộ tiền lương còn nợ** kèm lãi suất\n- Thanh toán trong vòng **14 ngày** kể từ ngày chấm dứt\n\n**Căn cứ pháp lý:** Điều 35, Điều 97 Bộ luật Lao động 2019.",
    route: "rule_followup",
    cited_articles: ["35", "97"],
    retrieved_articles: [
      {
        article_number: "35",
        article_title: "Quyền đơn phương chấm dứt hợp đồng lao động của người lao động",
        snippet:
          "2. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động không cần báo trước trong trường hợp sau đây: c) Không được trả đủ lương hoặc trả lương không đúng thời hạn, trừ trường hợp bất khả kháng.",
        source_file: "luatlaodong_new.pdf",
        score: 12.5,
      },
      {
        article_number: "97",
        article_title: "Nguyên tắc trả lương",
        snippet:
          "1. Người lao động được trả lương trực tiếp, đầy đủ và đúng thời hạn. Trường hợp đặc biệt không thể trả lương đúng thời hạn thì không được chậm quá 30 ngày; nếu trả lương chậm từ 15 ngày trở lên thì người sử dụng lao động phải đền bù cho người lao động một khoản tiền ít nhất bằng số tiền lãi của số tiền trả chậm.",
        source_file: "luatlaodong_new.pdf",
        score: null,
      },
    ],
    validation: { grounded: true, reason: "Điều 35, 97 được trích chính xác từ nguồn luật" },
  },

  pregnant: {
    answer:
      "**Có.** Theo **Điều 137** Bộ luật Lao động 2019, người sử dụng lao động **không được** đơn phương chấm dứt hợp đồng lao động với lao động nữ trong các trường hợp:\n\n- Đang **mang thai**\n- Đang trong thời gian **nghỉ thai sản**\n- Đang **nuôi con dưới 12 tháng tuổi**\n\nNếu hợp đồng hết hạn trong thời gian này, **phải gia hạn** đến khi hết thời gian bảo vệ.\n\n**Căn cứ pháp lý:** Điều 137 Bộ luật Lao động 2019.",
    route: "rule_based",
    cited_articles: ["137"],
    retrieved_articles: [
      {
        article_number: "137",
        article_title: "Bảo vệ thai sản",
        snippet:
          "Người sử dụng lao động không được sa thải hoặc đơn phương chấm dứt hợp đồng lao động đối với người lao động vì lý do kết hôn, mang thai, nghỉ thai sản, nuôi con dưới 12 tháng tuổi, trừ trường hợp người sử dụng lao động là cá nhân chết, bị Tòa án tuyên bố mất năng lực hành vi dân sự...",
        source_file: "luatlaodong_new.pdf",
        score: 14.2,
      },
    ],
    validation: { grounded: true, reason: "Điều 137 có trong nguồn luật, trích dẫn chính xác" },
  },

  article113: {
    answer:
      "**Điều 113. Nghỉ hằng năm**\n\n1. Người lao động làm việc đủ 12 tháng cho một người sử dụng lao động thì được nghỉ hằng năm, hưởng nguyên lương theo hợp đồng lao động như sau:\n   - **12 ngày** làm việc đối với người làm công việc trong điều kiện bình thường;\n   - **14 ngày** làm việc đối với người lao động chưa thành niên, lao động là người khuyết tật, người làm nghề, công việc nặng nhọc, độc hại, nguy hiểm;\n   - **16 ngày** làm việc đối với người làm nghề, công việc đặc biệt nặng nhọc, độc hại, nguy hiểm.\n\n2. Người lao động làm việc chưa đủ 12 tháng thì số ngày nghỉ hằng năm theo tỷ lệ tương ứng với số tháng làm việc.\n\n3. Trường hợp thôi việc, bị mất việc mà chưa nghỉ hằng năm thì được thanh toán tiền lương cho những ngày chưa nghỉ.\n\n**Căn cứ pháp lý:** Điều 113, Điều 114 Bộ luật Lao động 2019.",
    route: "quote_direct",
    cited_articles: ["113", "114"],
    retrieved_articles: [
      {
        article_number: "113",
        article_title: "Nghỉ hằng năm",
        snippet:
          "Điều 113. Nghỉ hằng năm 1. Người lao động làm việc đủ 12 tháng cho một người sử dụng lao động thì được nghỉ hằng năm, hưởng nguyên lương theo hợp đồng lao động như sau: a) 12 ngày làm việc đối với người làm công việc trong điều kiện bình thường...",
        source_file: "luatlaodong_new.pdf",
        score: null,
      },
      {
        article_number: "114",
        article_title: "Ngày nghỉ hằng năm tăng thêm theo thâm niên làm việc",
        snippet:
          "Cứ đủ 05 năm làm việc cho một người sử dụng lao động thì số ngày nghỉ hằng năm của người lao động được tăng thêm tương ứng 01 ngày.",
        source_file: "luatlaodong_new.pdf",
        score: null,
      },
    ],
    validation: { grounded: true, reason: "Trích dẫn khớp trực tiếp với nguồn luật" },
  },

  overtime: {
    answer:
      "Theo **Điều 107** Bộ luật Lao động 2019, thời giờ làm thêm được giới hạn:\n\n- **Không quá 50%** số giờ làm việc bình thường trong 01 ngày\n- Không quá **40 giờ/tháng**\n- Không quá **200 giờ/năm** trong điều kiện thông thường\n- Trường hợp đặc biệt (theo Nghị định Chính phủ): không quá **300 giờ/năm**\n\nNgười lao động chỉ làm thêm giờ khi **được sự đồng ý** của bản thân.\n\n**Căn cứ pháp lý:** Điều 107 Bộ luật Lao động 2019.",
    route: "rag",
    cited_articles: ["107"],
    retrieved_articles: [
      {
        article_number: "107",
        article_title: "Làm thêm giờ",
        snippet:
          "1. Thời gian làm thêm giờ là khoảng thời gian làm việc ngoài thời giờ làm việc bình thường theo quy định của pháp luật, thỏa ước lao động tập thể hoặc theo nội quy lao động. 2. Người sử dụng lao động được sử dụng người lao động làm thêm giờ khi đáp ứng đủ các yêu cầu: a) Phải được sự đồng ý của người lao động...",
        source_file: "luatlaodong_new.pdf",
        score: 9.87,
      },
    ],
    validation: { grounded: true, reason: "Điều 107 có trong nguồn luật" },
  },

  trial: {
    answer:
      "Theo **Điều 25** Bộ luật Lao động 2019, thời gian thử việc:\n\n- **Không quá 180 ngày** với người quản lý doanh nghiệp\n- **Không quá 60 ngày** với công việc có chức danh nghề nghiệp cần trình độ **đại học trở lên**\n- Không quá 30 ngày với trình độ trung cấp, công nhân kỹ thuật\n- Không quá 06 ngày với công việc khác\n\n**Lưu ý:** Mỗi công việc chỉ được thử việc **01 lần**.\n\n**Căn cứ pháp lý:** Điều 24, Điều 25 Bộ luật Lao động 2019.",
    route: "rag",
    cited_articles: ["24", "25"],
    retrieved_articles: [
      {
        article_number: "25",
        article_title: "Thời gian thử việc",
        snippet:
          "Thời gian thử việc do hai bên thỏa thuận căn cứ vào tính chất và mức độ phức tạp của công việc nhưng chỉ được thử việc một lần đối với một công việc và bảo đảm điều kiện sau đây: 1. Không quá 180 ngày đối với công việc của người quản lý doanh nghiệp; 2. Không quá 60 ngày đối với công việc có chức danh nghề cần trình độ đại học trở lên...",
        source_file: "luatlaodong_new.pdf",
        score: 10.3,
      },
    ],
    validation: { grounded: true, reason: "Điều 25 có trong nguồn luật" },
  },

  offtopic: {
    answer:
      "Câu hỏi này nằm ngoài phạm vi tư vấn của mình — mình chỉ hỗ trợ các vấn đề pháp luật lao động Việt Nam như quyền lợi người lao động, hợp đồng, tiền lương, sa thải, kỷ luật... Bạn có câu hỏi nào về những chủ đề này không? 😊",
    route: "intent_non_legal",
    cited_articles: [],
    retrieved_articles: [],
    validation: { grounded: false, reason: "Ngoài phạm vi pháp luật lao động" },
  },

  invalid_article: {
    answer:
      "**Điều 999** không tồn tại trong Bộ luật Lao động 2019. Bộ luật Lao động 2019 có tổng cộng **220 Điều** (từ Điều 1 đến Điều 220).\n\nNếu bạn muốn tra cứu quy định về **sa thải**, các Điều liên quan là: Điều 124, Điều 125, Điều 122 (nguyên tắc kỷ luật lao động).\n\nBạn muốn mình tra cứu nội dung nào cụ thể?",
    route: "article_resolution",
    cited_articles: [],
    retrieved_articles: [],
    validation: { grounded: false, reason: "Điều 999 nằm ngoài phạm vi hợp lệ (1–220)" },
  },
}

export function getMockResponse(message: string): ChatResponse {
  const lower = message.toLowerCase()
  if (lower.includes("real madrid") || lower.includes("bóng đá") || lower.includes("tối qua"))
    return MOCK_RESPONSES.offtopic
  if (lower.includes("999") || lower.includes("điều không tồn tại"))
    return MOCK_RESPONSES.invalid_article
  if (lower.includes("trích nguyên văn") && lower.includes("113"))
    return MOCK_RESPONSES.article113
  if (lower.includes("mang thai") || lower.includes("thai sản"))
    return MOCK_RESPONSES.pregnant
  if (lower.includes("nợ lương") || lower.includes("chậm lương") || lower.includes("không trả lương"))
    return MOCK_RESPONSES.wage_arrears
  if (lower.includes("đơn phương") || lower.includes("bồi thường") || lower.includes("trái luật"))
    return MOCK_RESPONSES.unilateral
  if (lower.includes("làm thêm") || lower.includes("thêm giờ") || lower.includes("overtime"))
    return MOCK_RESPONSES.overtime
  if (lower.includes("thử việc") || lower.includes("đại học") || lower.includes("60 ngày"))
    return MOCK_RESPONSES.trial
  return MOCK_RESPONSES.default
}
