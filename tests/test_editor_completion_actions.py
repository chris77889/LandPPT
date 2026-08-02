from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_generated_content_is_opened_or_downloaded_on_completion():
    speech = _read(
        "src/landppt/web/static/js/pages/project/slides_editor/"
        "projectSlidesEditor.speechScriptsDialog.js"
    )
    narration = _read(
        "src/landppt/web/static/js/pages/project/slides_editor/"
        "projectEditorNarration.js"
    )

    speech_completion = speech.split("function startProgressTracking(", 1)[1].split(
        "function startSingleScriptProgressTracking(", 1
    )[0]
    video_export = narration.split("async function exportNarrationVideo()", 1)[1].split(
        "async function exportNarrationAudio()", 1
    )[0]

    assert speech_completion.count("showCurrentSpeechScripts();") == 2
    assert "pollForSpeechScripts" not in speech_completion
    assert "language: languageValue" in speech
    assert "triggerFileDownload(downloadUrl);" in video_export
    assert "window.open('about:blank'" not in video_export
