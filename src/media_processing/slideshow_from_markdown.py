# %%
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_dir: str
    example_source_path: str
    example_overview_slide_path: str


class MainArgs(Tap):
    in_path: str  # Path to input file
    out_dir: str  # Directory for output files
    example_source_path: str  # Path to example source text
    example_overview_slide_path: str  # Path to example slide format


g_main_args = BaseArgs(
    in_path="../../test/output/vreed/output.md",
    # in_path="../../test/fixture/scientific_article_markdown_2.md",
    example_source_path="../../test/fixture/scientific_article_markdown_1.md",
    example_overview_slide_path="../../test/fixture/markdown_to_slideshow/scientific_article_1_overview_slide.md",
    out_dir="../../test/output",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()


import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import stamina
from llama_index.core import SimpleDirectoryReader
from llama_index.core.llms import LLM, ChatMessage, ChatResponse, MessageRole
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.llms.openrouter import OpenRouter

import media_processing.research_article as ra
import media_processing.slideshow.markdown_slide as ms
import media_processing.slideshow.slide_response as sr
from media_processing.prompt import triple_quote

# from media_processing import event_logging

# event_logging.start()


# %%
def source_context_prompt(text: str) -> str:
    return f"I have the following academic text:\n{triple_quote(text)}"


def get_response_content(res: ChatResponse):
    for choice in cast(Any, res.raw).choices:
        if hasattr(choice, "error"):
            raise ValueError(choice.error)
    if res.message.content is None:
        raise ValueError("respond message is None")
    return res.message.content


def conversion_example_prompt(example_text: str, example_slide: str) -> str:
    return (
        f"{source_context_prompt(example_text)}\n"
        "For reference, here's how it was converted into slide format:\n"
        f"{triple_quote(example_slide)}"
    )


def overview_request_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        f"{
            conversion_example_prompt(
                example_text=example_text, example_slide=example_slide
            )
        }\n"
        + "Please convert the following academic text into a concise, high-level overview using a similar format. The slide content should be brief, and the speaker notes should reference the slide content without adding introductory or concluding remarks. Stop output after the JSON.\n"
        f"{triple_quote(text)}"
    )


def expand_slice(s: slice, length: int) -> range:
    return range(length)[s]


def merge_slice_ranges(slices: Iterable[slice], length: int) -> list[int]:
    return [*dict.fromkeys(i for s in slices for i in expand_slice(s, length))]


@dataclass(frozen=True)
class ContentSlide:
    slide: ms.MarkdownSlide


@dataclass(frozen=True)
class NonContentSlide:
    slide: ms.MarkdownSlide


def condense_existing_slides(
    existing_slides: Sequence[ContentSlide | NonContentSlide],
) -> Sequence[ms.MarkdownSlide]:
    content_slide_indices = [
        i for i, s in enumerate(existing_slides) if isinstance(s, ContentSlide)
    ]
    preserved_indices = [
        content_slide_indices[i]
        for i in merge_slice_ranges(
            [slice(0, 3), slice(-3, None)], len(content_slide_indices)
        )
    ]
    return [
        (
            s.slide
            if i in preserved_indices or not isinstance(s, ContentSlide)
            else ms.MarkdownSlide.from_markdown(
                f"# {ms.MarkdownSlide.render_tokens(s.slide.title.node.to_tokens())}\n\n\\[...\\]"
            )
        )
        for i, s in enumerate(existing_slides)
    ]


def create_next_slide_context(
    prior_chat_context: Iterable[ChatMessage],
    existing_slides: Sequence[ContentSlide | NonContentSlide],
    source: str,
) -> list[ChatMessage]:
    source_context = source_context_prompt(source)
    next_slide_prompt = """Write the single next slide. The slide content should be brief. The speaker notes should reference the slide content, not the slide itself, without adding introductory or concluding remarks. At the end of the speaker notes, before closing the bracket, write down:
1. The start and end of the range of text referenced in the following JSON format:
{
    "start": "Start of a sentence...",
    "end": "...end of a sentence.",
}
Stop the output after closing the speaker notes.  
Following the text in chronological order. Do not skip any part."""
    condensed_slides_prompt = ms.slides_to_context_prompt(
        condense_existing_slides(existing_slides)
    )
    chat_context = [
        *prior_chat_context,
        ChatMessage(role=MessageRole.USER, content=source_context),
        *(
            [ChatMessage(role=MessageRole.USER, content=condensed_slides_prompt)]
            if len(existing_slides) > 0
            else []
        ),
        ChatMessage(role=MessageRole.USER, content=next_slide_prompt),
    ]

    return chat_context


@dataclass
class TextRange:
    start: int
    end: int
    text: str


class SourceTracker:
    def __init__(self):
        self.sections: list[ra.Section] = []
        self.referenced_ranges: list[TextRange] = []
        self._cached_text: str | None = None

    @property
    def source_text(self) -> str:
        if self._cached_text is None:
            self._cached_text = ra.markdown_from_sections(self.sections)
        return self._cached_text

    def update_sections(self, removed_count: int, new_sections: Sequence[ra.Section]):
        if removed_count > len(self.sections):
            raise ValueError("Cannot remove more sections than exist")

        removed_text_length = len(
            ra.markdown_from_sections(self.sections[:removed_count])
        )

        self.referenced_ranges = [
            TextRange(
                r.start - removed_text_length, r.end - removed_text_length, r.text
            )
            for r in self.referenced_ranges
            if r.start >= removed_text_length
        ]

        self.sections = self.sections[removed_count:] + list(new_sections)
        self._cached_text = None

    def add_reference(self, text: str):
        start = self.source_text.find(text)
        if start >= 0:
            self.referenced_ranges.append(TextRange(start, start + len(text), text))
            self._merge_overlapping_ranges()

    def _merge_overlapping_ranges(self):
        if not self.referenced_ranges:
            return

        self.referenced_ranges.sort(key=lambda r: r.start)
        merged = [self.referenced_ranges[0]]

        for current in self.referenced_ranges[1:]:
            previous = merged[-1]
            if current.start <= previous.end:
                previous.end = max(previous.end, current.end)
                previous.text = self.source_text[previous.start : previous.end]
            else:
                merged.append(current)

        self.referenced_ranges = merged

    def get_marked_source(self) -> str:
        if len(self.referenced_ranges) == 0:
            return self.source_text

        result = []
        last_end = 0

        for r in self.referenced_ranges:
            result.append(self.source_text[last_end : r.start])
            result.append(f"<referenced>{r.text}</referenced>")
            last_end = r.end

        result.append(self.source_text[last_end:])
        return "".join(result)


@stamina.retry(on=ValueError, attempts=3)
def chat_with_retry(llm: LLM, messages: Sequence[ChatMessage]):
    return get_response_content(llm.chat(messages))


def slideshow_from_markdown(args: BaseArgs | MainArgs) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    # llm_smart = OpenRouter(
    #     max_tokens=1920,
    #     context_window=16384,
    #     model="neversleep/llama-3.1-lumimaid-70b",
    #     api_base="https://openrouter.ai/api/v1",
    #     api_key=g_api_key,
    #     api_version="v1",
    #     temperature=0.08,
    # )

    llm_smartest = OpenRouter(
        max_tokens=1920,
        context_window=16384,
        model="anthropic/claude-3.5-sonnet",
        api_base="https://openrouter.ai/api/v1",
        api_key=api_key,
        api_version="v1",
        temperature=0.01,
        additional_kwargs={
            "extra_body": {
                "provider": {"order": ["Anthropic"], "allow_fallbacks": False}
            }
        },
    )

    article = ra.ResearchArticle.from_sections(
        ra.sections_from_nodes(
            MarkdownNodeParser().get_nodes_from_documents(
                SimpleDirectoryReader(input_files=[args.in_path]).load_data()
            )
        )
    )
    example_article = ra.ResearchArticle.from_sections(
        ra.sections_from_nodes(
            MarkdownNodeParser().get_nodes_from_documents(
                SimpleDirectoryReader(
                    input_files=[args.example_source_path]
                ).load_data()
            )
        )
    )
    with open(args.example_overview_slide_path, encoding="utf-8") as f:
        example_slide = f.read()

    system_prompt = ChatMessage(
        role=MessageRole.SYSTEM,
        content="Write the next reply in the conversation. Use markdown for formatting when appropriate. Be concise yet helpful. Offer direct answers when possible. Ask questions if needed. Explain complex concepts with brief examples. Avoid repetition and strive to add value with each response.",
    )
    opening_sections = article.get_primary_opening_sections()
    overview_request = ChatMessage(
        role=MessageRole.USER,
        content=overview_request_prompt(
            ra.markdown_from_sections(example_article.get_primary_opening_sections()),
            example_slide,
            ra.markdown_from_sections(opening_sections),
        ),
    )

    overview_slide_response = sr.SlideResponse.from_markdown(
        chat_with_retry(llm_smartest, [system_prompt, overview_request])
    )

    next_section_index = next(
        i
        for i, s in enumerate(article.primary_sections)
        if s.matches_type(ra.CommonPrimarySectionType.INTRODUCTION)
    )
    old_source_sections: Sequence[ra.Section] = []
    new_source_sections: Sequence[ra.Section] = ra.get_sections_until_threshold(
        article.primary_sections[next_section_index:], 2000, 750
    )
    existing_slides: list[ContentSlide | NonContentSlide] = [
        ContentSlide(slide=overview_slide_response.slide)
    ]
    last_level1_title: str | None = None
    while next_section_index < len(article.primary_sections):
        print(next_section_index)
        for section in new_source_sections:
            if section.level == 1 and last_level1_title != section.title:
                last_level1_title = section.title
                existing_slides.append(
                    NonContentSlide(
                        slide=ms.MarkdownSlide.from_markdown(
                            f"---\nlayout: center\n---\n\n# {section.title}"
                        )
                    )
                )
        next_slide_context: Sequence[ChatMessage] = create_next_slide_context(
            prior_chat_context=[system_prompt],
            existing_slides=existing_slides,
            source=ra.markdown_from_sections(old_source_sections + new_source_sections),
        )
        next_slide = sr.SlideResponse.from_markdown(
            chat_with_retry(llm_smartest, next_slide_context)
        )

        existing_slides.append(ContentSlide(slide=next_slide.slide))

        print("slide_title:", next_slide.slide.title.to_segments())
        print("slide_status:", next_slide.reference_status)

        if next_slide.reference_status is None:
            raise ValueError("LLM did not respond with reference status Json")
        source_end_text = ra.markdown_from_sections(new_source_sections)[-1000:]
        stripped_end_status = next_slide.reference_status.end.strip(".")[-300:]
        # if stripped_end_status not in source_end_text:
        #     print(f"{stripped_end_status} not in  {source_end_text}]")

        if stripped_end_status in source_end_text:
            print("stripped_end_status in source_end_text")
            matching_section_index = next(
                (
                    i
                    for i, section in enumerate(new_source_sections)
                    if stripped_end_status in ra.markdown_from_sections([section])
                )
            )

            old_source_sections = new_source_sections[matching_section_index:]

            next_section_index += len(new_source_sections)
            new_source_sections = ra.get_sections_until_threshold(
                article.primary_sections[next_section_index:], 2000, 750
            )

    return ms.MarkdownSlide.render_tokens(
        [
            token
            for s in existing_slides
            for slide_tokens in [s.slide.to_tokens()]
            for token in (
                ms.MarkdownSlide.parser.parse("---") + slide_tokens
                if s.slide.front_matter is None
                else slide_tokens
            )
        ][1:]
    )


# %%
if __name__ == "__main__":
    result = slideshow_from_markdown(g_main_args)
    out_dir = Path(g_main_args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "output.md", "w", encoding="utf-8") as f:
        f.write(result)

# %%
