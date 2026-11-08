from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class AnswerGenerator(Protocol):
    def __call__(self, prompt: str, **kwargs: object) -> str | Sequence[str] | Awaitable[str | Sequence[str]]:
        ...


@dataclass(frozen=True)
class SurveyQuestion:
    num: int
    title: str
    type_code: str = "0"
    provider_question_id: str = ""
    provider_page_id: str = ""
    options: int = 0
    rows: int = 1
    option_texts: tuple[str, ...] = ()
    row_texts: tuple[str, ...] = ()
    page: int = 1
    required: bool = False
    display_num: int | None = None
    description: str = ""
    forced_option_index: int | None = None
    forced_option_text: str = ""
    forced_texts: tuple[str, ...] = ()
    fillable_options: tuple[int, ...] = ()
    attached_option_selects: tuple[dict[str, Any], ...] = ()
    has_attached_option_select: bool = False
    rating_max: int = 0
    text_inputs: int = 0
    text_input_labels: tuple[str, ...] = ()
    is_multi_text: bool = False
    question_media: tuple[dict[str, Any], ...] = ()
    slider_min: Any = None
    slider_max: Any = None
    slider_step: Any = None
    multi_min_limit: Any = None
    multi_max_limit: Any = None
    provider_type: str = ""
    provider_page_raw: Any = None
    is_text_like: bool = False
    is_location: bool = False
    is_description: bool = False
    is_rating: bool = False
    is_slider_matrix: bool = False
    has_jump: bool = False
    jump_rules: tuple[dict[str, Any], ...] = ()
    has_display_condition: bool = False
    display_conditions: tuple[dict[str, Any], ...] = ()
    has_dependent_display_logic: bool = False
    controls_display_targets: tuple[dict[str, Any], ...] = ()
    logic_parse_status: str = "unknown"
    unsupported: bool = False
    unsupported_reason: str = ""


@dataclass(frozen=True)
class SurveyDefinition:
    provider: str
    title: str
    url: str
    questions: tuple[SurveyQuestion, ...]


@dataclass
class QuestionConfig:
    question_type: str
    probabilities: Any = None
    texts: list[str] | None = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"
    custom_weights: Any = None
    question_num: int | None = None
    question_title: str | None = None
    provider_question_id: str | None = None
    provider_page_id: str | None = None
    ai_enabled: bool = False
    multi_text_blank_modes: list[str] = field(default_factory=list)
    multi_text_blank_ai_flags: list[bool] = field(default_factory=list)
    multi_text_blank_int_ranges: list[list[int]] = field(default_factory=list)
    text_random_mode: str = "none"
    text_random_int_range: list[int] = field(default_factory=list)
    option_fill_texts: list[str | None] | None = None
    fillable_option_indices: list[int] | None = None
    attached_option_selects: list[dict[str, Any]] = field(default_factory=list)
    is_location: bool = False
    location_parts: list[str] = field(default_factory=list)
    dimension: str | None = None
    psycho_bias: str = "custom"
    survey_provider: str = "wjx"


@dataclass
class RunConfig:
    url: str
    questions: list[QuestionConfig] = field(default_factory=list)
    target: int = 1
    concurrency: int = 1
    provider: str | None = None
    answer_duration: tuple[int, int] = (60, 120)
    submit_interval: tuple[int, int] = (0, 0)
    answer_datetime_window: tuple[str, str] = ("", "")
    random_user_agent: bool = False
    user_agent_ratios: dict[str, int] = field(default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34})
    reliability_mode: bool = True
    target_alpha: float = 0.85
    answer_rules: list[dict[str, Any]] = field(default_factory=list)
    answer_generator: AnswerGenerator | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SubmissionRequest:
    config: RunConfig
    survey: SurveyDefinition | None = None


@dataclass(frozen=True)
class SubmissionResult:
    attempt: int
    provider: str
    success: bool
    elapsed_seconds: float
    error: str | None = None
