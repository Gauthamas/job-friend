"""Pure logic for step 9 (naming cross-group clusters): prompt text, response
parsing, and the validity checks. No model call lives here, so all of it is
testable without LM Studio running. The actual call is in
scripts/09_name_clusters.py."""

VALID_FLAGS = ("style", "topic", "unclear")

PROMPT_TEMPLATE = """Describe in one short sentence what these sentences have in common in HOW \
they are written, not what they are about. Start your sentence with "The author". \
Then, on a new line, write exactly one word: style, topic, or unclear -- \
whether the similarity is about writing style or just about topic.

Sentences:
{numbered_sentences}

Output format:
<one sentence starting with "The author">
<style|topic|unclear>"""


def build_prompt(sentences: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    return PROMPT_TEMPLATE.format(numbered_sentences=numbered)


def parse_response(raw_text: str) -> tuple[str, str]:
    """Returns (name, flag). flag is "invalid" if no style/topic/unclear
    line is found anywhere in the response; name is the first non-empty
    line regardless."""
    lines = [l.strip() for l in raw_text.strip().splitlines() if l.strip()]
    if not lines:
        return "", "invalid"
    name = lines[0]
    flag = "invalid"
    for line in lines[1:]:
        word = line.strip().lower().rstrip(".")
        if word in VALID_FLAGS:
            flag = word
            break
    return name, flag


def validate_name(name: str, sentences: list[str], max_words: int) -> list[str]:
    """Returns a list of problems; empty means the name is valid."""
    errors = []
    if not name.startswith("The author"):
        errors.append("does not start with 'The author'")
    if len(name.split()) > max_words:
        errors.append(f"longer than {max_words} words")
    normalized_name = " ".join(name.lower().split())
    for s in sentences:
        normalized_sentence = " ".join(s.lower().split())
        if normalized_sentence and normalized_sentence in normalized_name:
            errors.append("repeats a source sentence")
            break
    return errors
