import json
import os

import streamlit as st

from tutor.models import SPECS
from tutor.grok_client import GrokClient, TutorError, DEFAULT_MODEL
from tutor.config import load_env
from tutor.workflow import build_graph
from tutor.render import dot, section_markdown, export_markdown, export_pdf


load_env()

st.set_page_config(
    page_title="Seven-Step Topic Tutor",
    page_icon="📚",
    layout="wide",
)

TOTAL_SECTIONS = len(SPECS)


def empty_usage():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "reported_responses": 0,
    }


def safe_error(error, api_key):
    message = str(error)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


st.title("📚 Seven-Step Topic Tutor")
st.write(
    "One topic. Seven specialist agents. "
    "A complete learning path powered by Gemini."
)


# --------------------------------------------------
# Sidebar settings
# --------------------------------------------------
with st.sidebar:
    st.header("Gemini API settings")

    api_key = st.text_input(
        "Gemini API key",
        type="password",
        help=(
            "Leave blank to use GEMINI_API_KEY "
            "from your environment or .env file."
        ),
    )

    effective_key = (
        api_key.strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )

    model = st.text_input(
        "Gemini model ID",
        value=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
    ).strip().removeprefix("models/")

    max_tokens = st.number_input(
        "Output token budget per request",
        min_value=2000,
        max_value=32000,
        value=8000,
        step=1000,
    )

    timeout = st.number_input(
        "Timeout per request (seconds)",
        min_value=60,
        max_value=3600,
        value=180,
        step=60,
    )

    language = st.selectbox(
        "Explanation language",
        ["English", "Telugu", "Hindi"],
    )

    audience = st.selectbox(
        "Audience",
        [
            "Beginner",
            "Software engineer",
            "Senior engineer / Tech Lead",
        ],
    )

    if st.button("Check key and available models"):
        if not effective_key:
            st.warning(
                "Enter your Gemini API key or set "
                "GEMINI_API_KEY in .env."
            )
        else:
            try:
                check_client = GrokClient(
                    api_key=effective_key,
                    model=model or DEFAULT_MODEL,
                    timeout=int(timeout),
                    max_output_tokens=int(max_tokens),
                )

                available_models = check_client.models()

                if available_models:
                    st.success("Model list retrieved successfully.")
                    st.code(
                        "\n".join(available_models),
                        language="text",
                    )
                else:
                    st.warning("Google returned an empty model list.")

            except Exception as exc:
                st.error(safe_error(exc, effective_key))

    st.caption(
        "Requires a Gemini API key and internet access. "
        "Topics and lesson context are sent to Google. "
        "No web search is performed."
    )

    st.caption(
        "Normally seven generation requests per lesson. "
        "Retries can add requests and consume additional quota "
        "or incur charges. Generated code is never executed."
    )


# --------------------------------------------------
# New lesson form
# --------------------------------------------------
with st.form("topic_form"):
    topic = st.text_area(
        "What would you like to understand?",
        placeholder="Example: JWT authentication in Spring Boot 3",
        max_chars=1500,
    )

    submitted = st.form_submit_button(
        "Explain in seven steps",
        type="primary",
    )


if submitted:
    if not topic.strip():
        st.warning("Enter a topic first.")

    elif not effective_key:
        st.warning(
            "Enter your Gemini API key in the sidebar "
            "or set GEMINI_API_KEY in .env."
        )

    elif not model:
        st.warning("Enter a Gemini model ID.")

    else:
        st.session_state.lesson = {
            "topic": topic.strip(),
            "language": language,
            "audience": audience,
            "sections": {},
        }

        # Credentials are not stored in the lesson or downloads.
        st.session_state.settings = {
            "model": model,
            "timeout": int(timeout),
            "max_output_tokens": int(max_tokens),
        }

        st.session_state.usage = empty_usage()
        st.session_state.pop("actual_model", None)
        st.session_state.pop("generation_error", None)
        st.session_state.run_lesson = True


lesson = st.session_state.get("lesson")


# --------------------------------------------------
# Execute the LangGraph workflow
# --------------------------------------------------
if lesson is not None and st.session_state.get("run_lesson", False):
    st.session_state.run_lesson = False
    st.session_state.pop("generation_error", None)

    progress = st.progress(
        min(len(lesson["sections"]) / TOTAL_SECTIONS, 1.0)
    )

    client = None
    status_box = st.status(
        "Checking Gemini model access…",
        expanded=True,
    )

    try:
        if not effective_key:
            raise TutorError(
                "Enter your Gemini API key before retrying."
            )

        client = GrokClient(
            api_key=effective_key,
            **st.session_state.settings,
        )

        resolved_model = client.resolve_model()

        st.session_state.settings["model"] = resolved_model
        st.session_state.actual_model = resolved_model

        status_box.update(
            label=f"Generating with {resolved_model}…",
            state="running",
        )

        with status_box:
            graph = build_graph(client)

            for update in graph.stream(
                lesson,
                stream_mode="updates",
            ):
                for agent_name, values in update.items():
                    if (
                        isinstance(values, dict)
                        and isinstance(values.get("sections"), dict)
                    ):
                        lesson["sections"] = values["sections"]

                        # Explicitly retain progress across UI reruns.
                        st.session_state.lesson = lesson

                        st.write(
                            "✓ "
                            + agent_name.replace("_", " ").title()
                            + " completed"
                        )

                        progress.progress(
                            min(
                                len(lesson["sections"]) / TOTAL_SECTIONS,
                                1.0,
                            )
                        )

        if len(lesson["sections"]) != TOTAL_SECTIONS:
            raise TutorError(
                "The workflow ended before all sections were completed."
            )

        status_box.update(
            label="All seven sections are ready",
            state="complete",
            expanded=False,
        )

    except Exception as exc:
        st.session_state.generation_error = safe_error(
            exc,
            effective_key,
        )

        status_box.update(
            label="Generation stopped",
            state="error",
            expanded=False,
        )

    finally:
        if client is not None:
            totals = st.session_state.get("usage", empty_usage())
            reported_usage = getattr(client, "usage", {})

            if isinstance(reported_usage, dict):
                for name in empty_usage():
                    count = reported_usage.get(name, 0)

                    if isinstance(count, int) and count >= 0:
                        totals[name] = totals.get(name, 0) + count

            st.session_state.usage = totals


# --------------------------------------------------
# Error display and retry
# --------------------------------------------------
generation_error = st.session_state.get("generation_error")

if generation_error:
    st.error(f"Generation stopped: {generation_error}")


if lesson is not None and len(lesson["sections"]) < TOTAL_SECTIONS:
    saved_settings = st.session_state.get("settings", {})

    saved_model = (
        saved_settings.get("model", "")
        .strip()
        .removeprefix("models/")
    )

    settings_changed = (
        model != saved_model
        or language != lesson["language"]
        or audience != lesson["audience"]
    )

    st.info(
        "Completed sections are preserved in this browser session. "
        "Retry uses the current API key, timeout and token budget. "
        "To change the model, language, audience or topic, "
        "submit a fresh lesson."
    )

    if settings_changed:
        st.warning(
            "The sidebar settings differ from this lesson. "
            "Restore the original settings to retry, or click "
            "“Explain in seven steps” to start again."
        )

    if st.button(
        "Retry remaining sections",
        key="retry_remaining",
        disabled=settings_changed or not effective_key,
    ):
        st.session_state.settings.update(
            timeout=int(timeout),
            max_output_tokens=int(max_tokens),
        )

        st.session_state.run_lesson = True
        st.rerun()


# --------------------------------------------------
# Display completed sections
# --------------------------------------------------
if lesson is not None:
    st.header(lesson["topic"])

    shown_model = st.session_state.get(
        "actual_model",
        st.session_state.get("settings", {}).get(
            "model",
            "not connected",
        ),
    )

    st.caption(
        f'{len(lesson["sections"])}/{TOTAL_SECTIONS} sections '
        f"• Model: {shown_model}"
    )

    for index, (section_key, title, _, _) in enumerate(SPECS, 1):
        if section_key not in lesson["sections"]:
            continue

        data = lesson["sections"][section_key]

        with st.expander(
            f"{index}. {title}",
            expanded=True,
        ):
            st.markdown(section_markdown(section_key, data))

            if "diagram" in data:
                st.graphviz_chart(dot(data["diagram"]))

    usage = st.session_state.get("usage", empty_usage())

    st.caption(
        f"API-reported tokens: "
        f"{usage.get('input_tokens', 0):,} input / "
        f"{usage.get('output_tokens', 0):,} output. "
        "Requests without returned usage are not included."
    )

    if lesson["sections"]:
        markdown_column, json_column, pdf_column = st.columns(3)

        with markdown_column:
            st.download_button(
                label="Download Markdown",
                icon="📄",
                data=export_markdown(
                    lesson["topic"],
                    lesson["sections"],
                ),
                file_name="topic_lesson.md",
                mime="text/markdown",
            )

        with json_column:
            st.download_button(
                label="Download JSON",
                icon="🧾",
                data=json.dumps(
                    lesson,
                    ensure_ascii=False,
                    indent=2,
                ),
                file_name="topic_lesson.json",
                mime="application/json",
            )

        with pdf_column:
            st.download_button(
                label="Download PDF",
                icon="📑",
                data=export_pdf(
                    lesson["topic"],
                    lesson["sections"],
                ),
                file_name="topic_lesson.pdf",
                mime="application/pdf",
            )