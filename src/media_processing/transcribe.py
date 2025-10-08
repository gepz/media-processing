# %%
import sys
from dataclasses import dataclass
from pathlib import Path

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_path: str
    model: str
    language: str | None
    prompt: str | None


def validate_txt_suffix(path: str) -> str:
    if not path.lower().endswith(".txt"):
        raise ValueError(f"Output path must have .txt suffix, got: {path}")
    return path


class MainArgs(Tap):
    in_path: str  # Path to input audio file
    out_path: str  # Path to output text file (must have .txt extension)
    model: str = "openai/whisper-large-v3"  # Transcription model to use
    language: str | None = None  # Language code (optional)
    prompt: str | None = None  # Optional prompt to guide transcription

    def process_args(self) -> None:
        super().process_args()
        self.out_path = validate_txt_suffix(self.out_path)


g_main_args = BaseArgs(
    in_path="../../test/fixture/audio.mp3",
    out_path="../../test/output/transcript.txt",
    model="openai/whisper-large-v3",
    language=None,
    prompt=None,
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()

# %%
import os

from together import Together


def transcribe_audio(
    audio_path: str,
    model: str,
    language: str | None,
    prompt: str | None,
) -> str:
    """Transcribe audio file to text using OpenAI's API."""
    client = Together(api_key=os.environ.get("TOGETHER_API_KEY"))

    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            file=audio_file,
            model=model,
            language=language,
            prompt=prompt,
        )

    return response.text


if __name__ == "__main__":
    input_path = Path(g_main_args.in_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_path}")

    output_path = Path(g_main_args.out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    transcript = transcribe_audio(
        audio_path=str(input_path),
        model=g_main_args.model,
        language=g_main_args.language,
        prompt=g_main_args.prompt,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    print(f"Transcription saved to {output_path}")

# %%
