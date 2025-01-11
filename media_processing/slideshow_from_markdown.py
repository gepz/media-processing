# %%
import sys
from dataclasses import dataclass
from itertools import chain

from tap import Tap

from media_processing.prompt import triple_quote


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_dir: str
    out_name: str
    example_source_path: str
    example_overview_slide_path: str


class MainArgs(Tap):
    in_path: str  # Path to input file
    out_dir: str  # Directory for output files
    out_name: str = "output.md"  # Name of output file
    example_source_path: str  # Path to example source text
    example_overview_slide_path: str  # Path to example slide format


g_main_args = BaseArgs(
    in_path="test/fixture/scientific_article_markdown_2.md",
    example_source_path="test/fixture/scientific_article_markdown_1.md",
    example_overview_slide_path="test/fixture/markdown_to_slideshow/scientific_article_1_overview_slide.md",
    out_dir="test/output",
    out_name="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()


import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from llama_index.core import SimpleDirectoryReader
from llama_index.core.llms import ChatMessage, ChatResponse, MessageRole
from llama_index.llms.openrouter import OpenRouter

import media_processing.research_article as ra
import media_processing.slideshow.markdown_slide as ms
import media_processing.slideshow.slide_response as sr
from media_processing import event_logging

event_logging.start()


# %%
def source_context_prompt(text: str) -> str:
    return f"I have the following academic text:\n{triple_quote(text)}"


def get_response_content(res: ChatResponse):
    for choice in cast(Any, res.raw).choices:
        if hasattr(choice, "error"):
            raise ValueError(f"Error: {choice.error}")
    if res.message.content is None:
        raise ValueError("message is None")
    return res.message.content


def conversion_example_prompt(example_text: str, example_slide: str) -> str:
    return (
        f"{source_context_prompt(example_text)}\n"
        "For reference, here's how it was converted into slide format:\n"
        f"{triple_quote(example_slide)}"
    )


def overview_request_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        f"{conversion_example_prompt(
            example_text=example_text, example_slide=example_slide
        )}\n"
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


def create_next_slide_context(
    prior_chat_context: Iterable[ChatMessage],
    existing_slides: Sequence[ContentSlide | NonContentSlide],
    source_sections: Iterable[ra.Section],
) -> list[ChatMessage]:
    source_context = source_context_prompt(ra.markdown_from_sections(source_sections))
    next_slide_prompt = """Write the single next slide. The slide content should be brief. The speaker notes should reference the slide content, not the slide itself, without adding introductory or concluding remarks. At the end of the speaker notes, write down:
1. The start and end of the range of text referenced (in JSON format)
2. A boolean indicating if this is basically the last available meaningful text to reference

JSON Format:
{
    "start": "Start of a sentence...",
    "end": "...end of a sentence.",
    "isComplete": true/false
}
Stop output after the JSON.
Following the text in chronological order. Do not skip any part."""

    content_slide_indices = [
        i for i, s in enumerate(existing_slides) if isinstance(s, ContentSlide)
    ]
    preserved_indices = [
        content_slide_indices[i]
        for i in merge_slice_ranges(
            [slice(0, 2), slice(-2, None)], len(content_slide_indices)
        )
    ]
    filtered_existing_slides = [
        (
            s.slide
            if i in preserved_indices or not isinstance(s, ContentSlide)
            else ms.MarkdownSlide.from_markdown(
                f"# {s.slide.title}\n\n\\[Content omitted\\]"
            )
        )
        for i, s in enumerate(existing_slides)
    ]
    chat_context = [
        *prior_chat_context,
        ChatMessage(role=MessageRole.USER, content=source_context),
        *(
            [
                ChatMessage(
                    role=MessageRole.USER,
                    content=ms.slides_to_context_prompt(filtered_existing_slides),
                )
            ]
            if len(existing_slides) > 0
            else []
        ),
        ChatMessage(role=MessageRole.USER, content=next_slide_prompt),
    ]

    return chat_context


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
        temperature=0.08,
        additional_kwargs={
            "extra_body": {
                "provider": {"order": ["Anthropic"], "allow_fallbacks": False}
            }
        },
    )

    article = ra.ResearchArticle.from_sections(
        ra.sections_from_documents(
            SimpleDirectoryReader(input_files=[args.in_path]).load_data()
        )
    )
    example_article = ra.ResearchArticle.from_sections(
        ra.sections_from_documents(
            SimpleDirectoryReader(input_files=[args.example_source_path]).load_data()
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
    prior_chat_context: list[ChatMessage] = [system_prompt, overview_request]
    overview_slide_response = sr.SlideResponse.from_markdown(
        get_response_content(llm_smartest.chat(prior_chat_context))
    )
    prior_chat_context.append(
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content=overview_slide_response.slide.to_markdown(),
        )
    )
    next_section_index = next(
        i
        for i, s in enumerate(article.primary_sections)
        if s.matches_type(ra.CommonPrimarySectionType.INTRODUCTION)
    )
    source_sections = ra.get_sections_until_threshold(
        article.primary_sections[next_section_index:], 2000, 750
    )
    existing_slides: list[ContentSlide | NonContentSlide] = []
    last_level1_title: str | None = None

    while next_section_index < len(article.primary_sections):
        print(next_section_index)
        for section in source_sections:
            if section.level == 1 and last_level1_title != section.title:
                last_level1_title = section.title
                existing_slides.append(
                    NonContentSlide(
                        slide=ms.MarkdownSlide.from_markdown(
                            "---\nlayout: center\n---\n\n" f"# {section.title}"
                        )
                    )
                )

        next_slide = sr.SlideResponse.from_markdown(
            get_response_content(
                llm_smartest.chat(
                    create_next_slide_context(
                        prior_chat_context=prior_chat_context,
                        existing_slides=existing_slides,
                        source_sections=source_sections,
                    )
                )
            )
        )

        existing_slides.append(ContentSlide(slide=next_slide.slide))

        if next_slide.reference_status is None:
            raise ValueError("LLM did not respnod with reference status Json")
        if next_slide.reference_status.isComplete:
            next_section_index += len(source_sections)
            source_sections = ra.get_sections_until_threshold(
                article.primary_sections[next_section_index:], 2000, 750
            )

    return ms.MarkdownSlide.render_tokens(
        chain(
            *[
                ms.MarkdownSlide.parser.parse("---") + tokens
                if s.slide.front_matter is None
                else tokens
                for s in existing_slides
                for tokens in [s.slide.to_tokens()]
            ][1:]
        )
    )


# %%
if __name__ == "__main__":
    result = slideshow_from_markdown(g_main_args)
    out_dir = Path(g_main_args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / g_main_args.out_name, "w", encoding="utf-8") as f:
        f.write(result)

# %%
