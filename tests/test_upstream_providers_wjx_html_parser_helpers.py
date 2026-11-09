from __future__ import annotations

import pytest
from selectolax.lexbor import LexborHTMLParser

from surveycore.wjx.provider import html_parser_choice, html_parser_common, html_parser_rules


def _parser(html: str):
    return LexborHTMLParser(html)


class TestWjxHtmlParserHelper:
    def test_force_select_text_helpers_and_fragment_dedupe(self) -> None:
        question_div = _parser(
            """
            <div>
              <div class="topichtml">请务必选 A 项</div>
              <div class="field-label">请务必选 A 项</div>
            </div>
            """
        ).css_first("div")

        assert html_parser_choice._normalize_force_select_text(" 【A】 选项 ") == "a选项"
        assert html_parser_choice._extract_force_select_option_label("(B) 香蕉") == "B"
        assert html_parser_choice._extract_force_select_option_label("普通文本") is None
        assert html_parser_choice._collect_force_select_fragments(
            question_div, "请务必选 A 项"
        ) == ["请务必选 A 项"]

    def test_text_input_helpers_detect_shared_other_inputs(self) -> None:
        ui_other_div = _parser("<div class='ui-other'><input type='text' /></div>").css_first("div")
        keyword_div = _parser("<div><input id='other_reason' type='text' /></div>").css_first("div")

        assert html_parser_choice._is_text_input_element(_parser("<textarea></textarea>").css_first("textarea"))
        assert html_parser_choice._is_text_input_element(_parser("<input type='text' />").css_first("input"))
        assert not html_parser_choice._is_text_input_element(_parser("<input type='radio' />").css_first("input"))
        assert html_parser_choice._element_contains_text_input(ui_other_div)
        assert html_parser_choice._question_div_has_shared_text_input(ui_other_div)
        assert html_parser_choice._question_div_has_shared_text_input(keyword_div)

    def test_extract_option_text_from_attrs_prefers_primary_and_child_attrs(self) -> None:
        primary = _parser("<div title='主标题'></div>").css_first("div")
        child = _parser("<div><span aria-label='子标题'></span></div>").css_first("div")
        fallback = _parser("<div data-val='备用值'></div>").css_first("div")

        assert html_parser_choice._extract_option_text_from_attrs(primary) == "主标题"
        assert html_parser_choice._extract_option_text_from_attrs(child) == "子标题"
        assert html_parser_choice._extract_option_text_from_attrs(fallback) == "备用值"
        assert html_parser_choice._extract_option_text_from_attrs(None) == ""

    def test_extract_rating_option_texts_can_fall_back_to_numbering(self) -> None:
        rating_div = _parser(
            """
            <div>
              <ul class="modlen3">
                <li><a class="rate-off"></a></li>
                <li><a class="rate-off" val="2"></a></li>
                <li><a class="rate-off"></a></li>
              </ul>
            </div>
            """
        ).css_first("div")

        assert html_parser_choice._extract_rating_option_texts(rating_div) == ["1", "2", "3"]
        assert html_parser_choice._text_looks_meaningful("A1")
        assert not html_parser_choice._text_looks_meaningful("   ")

    def test_extract_survey_title_from_html_strips_wjx_suffix(self) -> None:
        html = """
        <html>
          <head><title>备用标题 ｜ 问卷星</title></head>
          <body><div id="divTitle"><h1>正式标题 ｜ 问卷星</h1></div></body>
        </html>
        """
        assert html_parser_common.extract_survey_title_from_html(html) == "正式标题"

    def test_extract_question_number_and_cleanup_helpers(self) -> None:
        soup = _parser("<div id='div12' topic='12'></div>")
        assert html_parser_common._extract_question_number_from_div(soup.css_first("div")) == 12
        assert (
            html_parser_common._extract_question_number_from_div(
                _parser("<div id='div77'></div>").css_first("div")
            )
            == 77
        )
        assert (
            html_parser_common._cleanup_question_title(" １． 【单选题】 题目标题 ") == "题目标题"
        )
        assert (
            html_parser_common._cleanup_question_title(" 第1题 【多选题】 题目标题 ") == "题目标题"
        )
        assert html_parser_common._cleanup_question_title(" Q1 题目标题 ") == "题目标题"
        assert html_parser_common._extract_display_question_number("* 18. 题目") == 18
        assert html_parser_common._extract_display_question_number("第8题 题目") == 8
        assert html_parser_common._extract_display_question_number("Q9 题目") == 9
        assert html_parser_common._extract_display_question_number("10、题目") == 10

    def test_extract_display_heading_text_includes_split_topic_number(self) -> None:
        soup = _parser(
            """
            <div id="div23" topic="23" type="2">
              <div class="field-label">
                <span class="req">*</span>
                <div class="topicnumber">22.</div>
                <div class="topichtml">请评价培训和实习</div>
              </div>
            </div>
            """
        )
        heading = html_parser_common._extract_display_heading_text(soup.css_first("div"))
        assert heading == "22. 请评价培训和实习"
        assert html_parser_common._extract_display_question_number(heading) == 22

    def test_count_text_inputs_and_extract_labels_from_mixed_nodes(self) -> None:
        soup = _parser(
            """
            <div>
              <input type="text" placeholder="姓名" />
              性别：<input type="text" />
              <textarea aria-label="备注"></textarea>
              <div contenteditable="true"></div>
              <input type="hidden" />
              <input type="text" /><span class="textedit"></span>
            </div>
            """
        )
        assert html_parser_common._count_text_inputs(soup.css_first("div")) == 5
        assert html_parser_common._extract_text_input_labels(soup.css_first("div")) == [
            "姓名",
            "性别",
            "备注",
            "填空4",
            "填空5",
        ]

    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            (
                "项目评价<!-- 表单控件 -->"
                "<input style='display:none' type='text'>"
                "<label class='textEdit'><span class='textCont' contenteditable='true'></span></label>",
                ["项目评价"],
            ),
            (
                "<b>项目</b>评价<input style='display:none' type='text'>"
                "<label class='textEdit'><span class='textCont' contenteditable='true'></span></label>",
                ["项目 评价"],
            ),
            (
                "姓名：<input style='display:none' type='text'>"
                "<label class='textEdit'><span class='textCont' contenteditable='true'></span></label>"
                "电话：<input style='display:none' type='text'>"
                "<label class='textEdit'><span class='textCont' contenteditable='true'></span></label>",
                ["姓名", "电话"],
            ),
        ],
    )
    def test_textcont_labels_keep_text_siblings_and_stop_at_previous_editor(
        self, markup: str, expected: list[str]
    ) -> None:
        question_div = _parser(f"<div>{markup}</div>").css_first("div")

        assert html_parser_common._extract_text_input_labels(question_div) == expected

    def test_extract_display_heading_text_falls_back_to_blockquote_and_plain_text(self) -> None:
        blockquote_div = _parser("<div><blockquote> 引用标题 </blockquote></div>").css_first("div")
        plain_div = _parser("<div> 普通标题 </div>").css_first("div")

        assert html_parser_common._extract_display_heading_text(blockquote_div) == "引用标题"
        assert html_parser_common._extract_display_heading_text(plain_div) == "普通标题"

    def test_description_reorder_scale_and_rating_detection(self) -> None:
        description_div = _parser("<div><div class='topichtml'>说明</div></div>").css_first("div")
        reorder_div = _parser(
            "<div><ul><li>A</li><li>B</li></ul><div class='ui-sortable'></div></div>"
        ).css_first("div")
        scale_div = _parser(
            """
            <div>
              <div class="scaleTitle"></div>
              <ul tp="d">
                <li><a>1</a></li><li><a>2</a></li><li><a>3</a></li><li><a>4</a></li><li><a>5</a></li>
                <li><a>6</a></li><li><a>7</a></li><li><a>8</a></li><li><a>9</a></li><li><a>10</a></li>
              </ul>
            </div>
            """
        ).css_first("div")
        rating_div = _parser(
            "<div><div class='evaluateTagWrap'></div><a class='rate-off'>星</a></div>"
        ).css_first("div")
        rating_count_div = _parser("<div><ul class='modlen5'><li></li></ul></div>").css_first("div")

        assert html_parser_common._question_looks_like_description(description_div, "3")
        assert not html_parser_common._question_looks_like_description(
            _parser("<div><input type='radio'/></div>").css_first("div"), "3"
        )
        assert html_parser_common._question_looks_like_reorder(reorder_div)
        assert html_parser_common._question_looks_like_numeric_scale(scale_div)
        assert not html_parser_common._question_looks_like_rating(scale_div)
        assert html_parser_common._question_looks_like_rating(rating_div)
        assert html_parser_common._extract_rating_option_count(rating_count_div) == 5

    def test_dval_scale_with_blank_rate_icons_is_not_rating(self) -> None:
        scale_div = _parser(
            """
            <div>
              <div class="scaleTitle_frist">很不同意</div>
              <div class="scaleTitle_last">很同意</div>
              <ul tp="d">
                <li><a class="rate-off" dval="1"></a></li>
                <li><a class="rate-off" dval="2"></a></li>
                <li><a class="rate-off" dval="3"></a></li>
                <li><a class="rate-off" dval="4"></a></li>
                <li><a class="rate-off" dval="5"></a></li>
              </ul>
            </div>
            """
        ).css_first("div")

        assert html_parser_common._question_looks_like_numeric_scale(scale_div)
        assert not html_parser_common._question_looks_like_rating(scale_div)

    def test_required_and_select_placeholder_helpers(self) -> None:
        question_div = _parser("<div req='1'><div class='topichtml'>题目</div></div>").css_first("div")
        heading_required = _parser("<div><div class='topichtml'>* 必答题</div></div>").css_first("div")
        selector_required = _parser("<div><span class='required'></span></div>").css_first("div")
        assert html_parser_common._question_is_required(question_div)
        assert html_parser_common._question_is_required(heading_required)
        assert html_parser_common._question_is_required(selector_required)
        assert html_parser_common._text_looks_like_select_placeholder(" 请选择省份 ")
        assert html_parser_common._is_select_placeholder_option(0, "", "请选择")
        assert not html_parser_common._is_select_placeholder_option(1, "1", "北京")

    def test_should_mark_as_multi_text_respects_type_and_flags(self) -> None:
        assert html_parser_common._should_mark_as_multi_text("1", 0, 2, False)
        assert html_parser_common._should_mark_as_multi_text("9", 0, 1, False, has_gapfill=True)
        assert not html_parser_common._should_mark_as_multi_text("3", 4, 2, False)
        assert not html_parser_common._should_mark_as_multi_text("1", 0, 2, True)
        assert not html_parser_common._should_mark_as_multi_text(
            "1", 0, 2, False, has_slider_matrix=True
        )

    def test_force_select_detection_supports_text_label_and_index(self) -> None:
        text_div = _parser("<div><div class='topichtml'>本题检测，请选择 非常满意。</div></div>").css_first("div")
        label_div = _parser("<div><div class='topichtml'>请务必选A项</div></div>").css_first("div")
        index_div = _parser("<div><div class='topichtml'>请直接选第2项</div></div>").css_first("div")

        assert html_parser_choice._extract_force_select_option(
            text_div, "本题检测，请选择 非常满意。", ["非常不满意", "非常满意"]
        ) == (1, "非常满意")
        assert html_parser_choice._extract_force_select_option(
            label_div, "请务必选A项", ["(A) 苹果", "(B) 香蕉"]
        ) == (0, "(A) 苹果")
        assert html_parser_choice._extract_force_select_option(
            index_div, "请直接选第2项", ["甲", "乙", "丙"]
        ) == (1, "乙")
        assert html_parser_choice._extract_force_select_option(
            None, "请直接选第9项", ["甲", "乙"]
        ) == (None, None)

    def test_force_select_text_matching_requires_exact_normalized_text(self) -> None:
        question_div = _parser("<div><div class='topichtml'>请直接选满意</div></div>").css_first("div")
        assert html_parser_choice._extract_force_select_option(
            question_div, "请直接选满意", ["不满意", "满意度一般"]
        ) == (None, None)
        assert html_parser_choice._extract_force_select_option(
            question_div, "请直接选满意", ["数字1", "满意"]
        ) == (1, "满意")

    def test_choice_option_and_attached_select_parsing_marks_fillable_options(self) -> None:
        question_div = _parser(
            """
            <div>
              <div class="ui-controlgroup">
                <div>
                  <span class="label">选项A</span>
                </div>
                <div>
                  <span class="label">其他</span>
                  <input type="text" />
                  <select>
                    <option value="">请选择</option>
                    <option>红色</option>
                    <option>蓝色</option>
                  </select>
                </div>
              </div>
            </div>
            """
        ).css_first("div")

        texts, fillable_indices = html_parser_choice._collect_choice_option_texts(question_div)
        attached = html_parser_choice._extract_choice_attached_selects(question_div)

        assert texts == ["选项A", "其他"]
        assert fillable_indices == [1]
        assert attached == [
            {
                "option_index": 1,
                "option_text": "其他",
                "select_options": ["红色", "蓝色"],
                "select_option_count": 2,
            }
        ]

    def test_choice_option_parsing_falls_back_to_plain_list_and_shared_input(self) -> None:
        question_div = _parser(
            """
            <div>
              <ul>
                <li>选项一</li>
                <li>选项二</li>
              </ul>
              <div class="ui-other"><input type="text" /></div>
            </div>
            """
        ).css_first("div")

        texts, fillable_indices = html_parser_choice._collect_choice_option_texts(question_div)
        assert texts == ["选项一", "选项二"]
        assert fillable_indices == [1]

    def test_custom_select_and_location_helpers(self) -> None:
        custom_input = _parser("<input custom='请选择, 苹果,香蕉, 苹果' />").css_first("input")
        typo_custom_input = _parser("<input cusom='北京|上海|北京' />").css_first("input")
        location_div = _parser("<div><input verify='地图定位' /></div>").css_first("div")
        location_input = _parser(
            "<input type='text' verify='省市区' onclick='openCityBox(this,3,event,1);' readonly='readonly' />"
        ).css_first("input")
        soup = _parser(
            """
            <div>
              <div topic="7">
                <select id="q7">
                  <option value="">请选择</option>
                  <option value="1">北京</option>
                  <option value="2">上海</option>
                </select>
              </div>
            </div>
            """
        )

        assert html_parser_choice._extract_custom_select_option_texts(custom_input) == [
            "苹果",
            "香蕉",
        ]
        assert html_parser_choice._extract_custom_select_option_texts(typo_custom_input) == [
            "北京",
            "上海",
        ]
        assert html_parser_choice._verify_text_indicates_location("腾讯地图")
        assert html_parser_choice._verify_text_indicates_location("省市区")
        assert not html_parser_choice._verify_text_indicates_location("city")
        assert not html_parser_choice._verify_text_indicates_location("province")
        assert not html_parser_choice._verify_text_indicates_location("area")
        assert not html_parser_choice._verify_text_indicates_location("普通文本")
        assert html_parser_choice._question_is_location(location_div)
        assert html_parser_choice._question_is_location(
            _parser("<div><input verify='省市区' onclick='openCityBox(this,3,event,1);' /></div>").css_first("div")
        )
        assert html_parser_choice._question_is_location(
            _parser("<div><input onclick='openCityBox(this,3,event,1);' /></div>").css_first("div")
        )
        assert not html_parser_choice._question_is_location(
            _parser("<div><input verify='city' /></div>").css_first("div")
        )
        assert (
            html_parser_common._count_text_inputs(_parser(f"<div>{location_input.html}</div>").css_first("div"))
            == 0
        )
        assert html_parser_choice._collect_select_option_texts(soup.css_first("div"), soup, 7) == [
            "北京",
            "上海",
        ]
        assert html_parser_choice._extract_select_option_texts_from_element(
            soup.css_first("select")
        ) == ["北京", "上海"]

    def test_question_title_limits_jump_and_display_rules(self) -> None:
        question_div = _parser(
            """
            <div relation="1,1|1,1|3,1,2">
              <div class="topichtml">2. 请选择你喜欢的项目 [至少选2项，最多选4项]</div>
              <input type="checkbox" jumpto="5" />
              <input type="checkbox" />
            </div>
            """
        ).css_first("div")

        assert (
            html_parser_rules._extract_question_title(question_div, 2)
            == "请选择你喜欢的项目 [至少选2项，最多选4项]"
        )
        assert html_parser_rules._extract_jump_rules_from_html(question_div, 2, ["A", "B"]) == (
            True,
            [{"option_index": 0, "jumpto": 5, "option_text": "A", "terminates_survey": False}],
        )
        assert html_parser_rules._extract_display_conditions_from_html(question_div, 2) == (
            True,
            [
                {
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "raw_relation": "1,1",
                },
                {
                    "condition_question_num": 3,
                    "condition_mode": "selected",
                    "condition_option_indices": [0, 1],
                    "raw_relation": "3,1,2",
                },
            ],
        )

    def test_attach_display_condition_metadata_marks_source_question(self) -> None:
        questions = [
            {"num": 1, "display_conditions": [], "controls_display_targets": []},
            {
                "num": 2,
                "display_conditions": [
                    {
                        "condition_question_num": 1,
                        "condition_mode": "selected",
                        "condition_option_indices": [1],
                    }
                ],
                "controls_display_targets": [],
            },
        ]

        html_parser_rules._attach_display_condition_metadata(questions)

        assert questions[0]["has_dependent_display_logic"] is True
        assert questions[0]["controls_display_targets"] == [
            {
                "target_question_num": 2,
                "condition_option_indices": [1],
                "condition_mode": "selected",
            }
        ]

    def test_multi_limit_fragment_collection_and_metadata_helpers(self) -> None:
        question_div = _parser(
            """
            <div topic="7" type="7">
              <div class="topichtml">至少选1项，最多选3项</div>
              <ul><li>选项1</li><li>选项2</li></ul>
              <select><option value="">请选择</option><option>北京</option></select>
              <input id="other_city" type="text" />
            </div>
            """
        ).css_first("div")
        soup = _parser(question_div.html)

        fragments = html_parser_rules._collect_multi_limit_text_fragments(question_div)
        metadata = html_parser_rules._extract_question_metadata_from_html(
            soup, question_div, 7, "7"
        )

        assert fragments == ["至少选1项，最多选3项"]
        assert metadata[0] == ["北京"]
        assert metadata[1] == 1
        assert metadata[4] == [0]

    def test_jump_and_display_rule_helpers_ignore_invalid_values(self) -> None:
        question_div = _parser(
            """
            <div relation="bad|1,a|2,0|3,2,2">
              <input type="checkbox" data-jumpto="跳到第8题" />
              <input type="text" jumpto="9" />
            </div>
            """
        ).css_first("div")

        has_jump, jump_rules = html_parser_rules._extract_jump_rules_from_html(
            question_div, 3, ["A", "B"]
        )
        has_display, display_rules = html_parser_rules._extract_display_conditions_from_html(
            question_div, 3
        )

        assert has_jump is True
        assert jump_rules == [
            {"option_index": 0, "jumpto": 8, "option_text": "A", "terminates_survey": False}
        ]
        assert has_display is True
        assert display_rules == [
            {
                "condition_question_num": 3,
                "condition_mode": "selected",
                "condition_option_indices": [1],
                "raw_relation": "3,2,2",
            }
        ]

    def test_jump_rule_helper_rejects_undefined_text_format(self) -> None:
        question_div = _parser(
            """
            <div hasjump="1" type="3">
              <input type="radio" data-jumpto="去第8题" />
            </div>
            """
        ).css_first("div")

        assert html_parser_rules._extract_jump_rules_from_html(question_div, 1, ["A"]) == (True, [])

    def test_display_rule_helper_skips_dirty_chunks_and_keeps_valid_blocks(self) -> None:
        question_div = _parser("<div relation='1,1|脏数据|3,2,3|4,a,1|5,1'></div>").css_first("div")

        assert html_parser_rules._extract_display_conditions_from_html(question_div, 6) == (
            True,
            [
                {
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "raw_relation": "1,1",
                },
                {
                    "condition_question_num": 3,
                    "condition_mode": "selected",
                    "condition_option_indices": [1, 2],
                    "raw_relation": "3,2,3",
                },
                {
                    "condition_question_num": 5,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "raw_relation": "5,1",
                },
            ],
        )

    def test_jump_rule_helper_supports_select_option_jumps(self) -> None:
        question_div = _parser(
            """
            <div hasjump="1" type="7">
              <select>
                <option value="">请选择</option>
                <option value="1" jumpto="9">北京</option>
                <option value="2">上海</option>
              </select>
            </div>
            """
        ).css_first("div")

        assert html_parser_rules._extract_jump_rules_from_html(
            question_div, 7, ["北京", "上海"]
        ) == (
            True,
            [{"option_index": 0, "jumpto": 9, "option_text": "北京", "terminates_survey": False}],
        )

    def test_jump_rule_helper_supports_unconditional_question_jump(self) -> None:
        question_div = _parser(
            """
            <div hasjump="1" jumpto="11" type="3">
              <input type="radio" />
              <input type="radio" />
            </div>
            """
        ).css_first("div")

        assert html_parser_rules._extract_jump_rules_from_html(question_div, 10, ["A", "B"]) == (
            True,
            [{"option_index": -1, "jumpto": 11, "option_text": None}],
        )

    def test_jump_rule_helper_marks_wjx_end_option_as_terminate(self) -> None:
        question_div = _parser(
            """
            <div hasjump="1" type="3">
              <input type="radio" value="1" />
              <input type="radio" value="2" jumpto="1" />
            </div>
            """
        ).css_first("div")

        assert html_parser_rules._extract_jump_rules_from_html(
            question_div,
            1,
            ["有（继续作答）", "没有（结束作答）"],
        ) == (
            True,
            [
                {
                    "option_index": 1,
                    "jumpto": 1,
                    "option_text": "没有（结束作答）",
                    "terminates_survey": True,
                }
            ],
        )

    def test_jump_rule_helper_treats_wjx_mobile_jumpto_one_as_terminate_without_keyword(
        self,
    ) -> None:
        question_div = _parser(
            """
            <div hasjump="1" type="3">
              <input type="radio" value="1" />
              <input type="radio" value="2" jumpto="1" />
            </div>
            """
        ).css_first("div")

        assert html_parser_rules._extract_jump_rules_from_html(
            question_div,
            1,
            ["是，应届毕业生", "否，暂时不是应届毕业生或准毕业生"],
        ) == (
            True,
            [
                {
                    "option_index": 1,
                    "jumpto": 1,
                    "option_text": "否，暂时不是应届毕业生或准毕业生",
                    "terminates_survey": True,
                }
            ],
        )

    def test_attach_display_condition_metadata_dedupes_and_clears_empty_targets(self) -> None:
        questions = [
            {"num": 1, "display_conditions": [], "controls_display_targets": []},
            {
                "num": 2,
                "display_conditions": [
                    {
                        "condition_question_num": 1,
                        "condition_mode": "selected",
                        "condition_option_indices": [0, 0],
                    },
                    {
                        "condition_question_num": 1,
                        "condition_mode": "selected",
                        "condition_option_indices": [0],
                    },
                ],
                "controls_display_targets": [],
            },
            {"num": 3, "display_conditions": "bad", "controls_display_targets": []},
        ]

        html_parser_rules._attach_display_condition_metadata(questions)

        assert questions[0]["controls_display_targets"] == [
            {
                "target_question_num": 2,
                "condition_option_indices": [0],
                "condition_mode": "selected",
            }
        ]
        assert questions[2]["controls_display_targets"] == []
        assert questions[2]["has_dependent_display_logic"] is False
