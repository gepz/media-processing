import sys

import openai
import yt_dlp

# Set your OpenAI API key
openai.api_key = "your_api_key_here"


def download_audio(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": "audio.%(ext)s",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return "audio.mp3"


def transcribe_audio(file_path):
    client = openai.OpenAI()
    with open(file_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model="whisper-1", file=audio_file
        )
    return transcription.text


def main():
    if len(sys.argv) != 2:
        print("Usage: python script.py <url_or_file_path>")
        sys.exit(1)

    input_path = sys.argv[1]

    if input_path.startswith(("http://", "https://")):
        audio_file = download_audio(input_path)
    else:
        audio_file = input_path

    transcript = transcribe_audio(audio_file)
    print(transcript)


if __name__ == "__main__":
    main()
